"""
Swing High / Swing Low Detector
================================
Fractal-based swing detection for multi-timeframe market structure analysis.
Used as the foundation for trend classification, BOS/CHoCH detection,
and supply & demand zone identification.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SwingDetector:
    """
    Detects swing highs and swing lows using the fractal (pivot-point) method.

    A swing high at bar *i* is confirmed when the high at *i* is the
    maximum across the window [i-order … i+order].  The symmetric condition
    applies for swing lows.  Because future bars are needed for confirmation,
    the last `order` bars are never marked.
    """

    # ------------------------------------------------------------------ #
    #  Core detection                                                      #
    # ------------------------------------------------------------------ #

    def detect_swings(self, df: pd.DataFrame, order: int = 5) -> pd.DataFrame:
        """
        Annotate a price DataFrame with swing high / swing low columns.

        Parameters
        ----------
        df    : DataFrame with at least 'high' and 'low' columns.
        order : Half-window size for the fractal comparison.

        Returns
        -------
        Same DataFrame (copy) with four added columns:
            swing_high       (bool)  – True when bar is a confirmed swing high
            swing_low        (bool)  – True when bar is a confirmed swing low
            swing_high_price (float) – high price when swing_high, else NaN
            swing_low_price  (float) – low  price when swing_low,  else NaN
        """
        required = {"high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing required columns: {missing}")

        result = df.copy()
        n = len(result)

        swing_high = np.zeros(n, dtype=bool)
        swing_low = np.zeros(n, dtype=bool)

        highs = result["high"].to_numpy(dtype=float)
        lows = result["low"].to_numpy(dtype=float)

        # We need [i-order : i+order+1] to be fully inside the array,
        # AND we must not mark the last `order` bars (no future confirmation).
        for i in range(order, n - order):
            window_h = highs[i - order : i + order + 1]
            window_l = lows[i - order : i + order + 1]

            # Drop NaN values before comparison
            if np.isnan(window_h).any() or np.isnan(highs[i]):
                pass
            elif highs[i] == np.nanmax(window_h):
                swing_high[i] = True

            if np.isnan(window_l).any() or np.isnan(lows[i]):
                pass
            elif lows[i] == np.nanmin(window_l):
                swing_low[i] = True

        result["swing_high"] = swing_high
        result["swing_low"] = swing_low
        result["swing_high_price"] = np.where(swing_high, highs, np.nan)
        result["swing_low_price"] = np.where(swing_low, lows, np.nan)

        logger.debug(
            "detect_swings: %d highs, %d lows detected (order=%d, bars=%d)",
            swing_high.sum(),
            swing_low.sum(),
            order,
            n,
        )
        return result

    # ------------------------------------------------------------------ #
    #  Significant swing extraction                                        #
    # ------------------------------------------------------------------ #

    def get_significant_swings(
        self, df: pd.DataFrame, n: int = 10
    ) -> dict:
        """
        Return the N most-recent *significant* swing highs and lows.

        Significance filter: two swings of the same type must be separated
        by at least 0.5 × ATR(14) to eliminate micro-fractal noise.

        Parameters
        ----------
        df : DataFrame that has already passed through `detect_swings`.
        n  : Maximum number of swings to return for each type.

        Returns
        -------
        dict with keys:
            'highs': list of (timestamp, price) tuples, newest first
            'lows':  list of (timestamp, price) tuples, newest first
        """
        if "swing_high" not in df.columns:
            df = self.detect_swings(df)

        atr = self._calculate_atr(df, period=14)
        min_distance = 0.5 * atr

        # --- Highs ---
        raw_highs = df[df["swing_high"]].copy()
        raw_highs = raw_highs.sort_index()  # chronological order
        significant_highs: List[Tuple] = []
        last_price = None
        for ts, row in raw_highs.iterrows():
            price = row["swing_high_price"]
            if np.isnan(price):
                continue
            if last_price is None or abs(price - last_price) >= min_distance:
                significant_highs.append((ts, price))
                last_price = price

        # --- Lows ---
        raw_lows = df[df["swing_low"]].copy()
        raw_lows = raw_lows.sort_index()
        significant_lows: List[Tuple] = []
        last_price = None
        for ts, row in raw_lows.iterrows():
            price = row["swing_low_price"]
            if np.isnan(price):
                continue
            if last_price is None or abs(price - last_price) >= min_distance:
                significant_lows.append((ts, price))
                last_price = price

        # Return the N most recent (reverse chronological)
        return {
            "highs": significant_highs[-n:][::-1],
            "lows": significant_lows[-n:][::-1],
        }

    # ------------------------------------------------------------------ #
    #  Market structure classification                                     #
    # ------------------------------------------------------------------ #

    def classify_market_structure(self, df: pd.DataFrame) -> dict:
        """
        Analyse the recent sequence of swing highs and lows to classify
        the overall market structure.

        Logic
        -----
        BULLISH  : higher highs (HH) AND higher lows (HL)
        BEARISH  : lower  highs (LH) AND lower  lows (LL)
        SIDEWAYS : mixed or equal pattern

        Returns
        -------
        dict:
            trend        : str  – 'BULLISH' | 'BEARISH' | 'SIDEWAYS'
            last_hh      : float | None – price of the most-recent higher high
            last_hl      : float | None – price of the most-recent higher low
            last_lh      : float | None – price of the most-recent lower high
            last_ll      : float | None – price of the most-recent lower low
            hh_count     : int
            hl_count     : int
            lh_count     : int
            ll_count     : int
            swing_highs  : list[(ts, price)]
            swing_lows   : list[(ts, price)]
        """
        swings = self.get_significant_swings(df, n=20)
        highs = swings["highs"]   # newest first
        lows = swings["lows"]     # newest first

        # Reverse to chronological for pattern detection
        highs_chron = highs[::-1]
        lows_chron = lows[::-1]

        hh_count = hl_count = lh_count = ll_count = 0
        last_hh = last_hl = last_lh = last_ll = None

        # Classify consecutive pairs of swing highs
        for i in range(1, len(highs_chron)):
            prev_price = highs_chron[i - 1][1]
            curr_price = highs_chron[i][1]
            if curr_price > prev_price:
                hh_count += 1
                last_hh = curr_price
            elif curr_price < prev_price:
                lh_count += 1
                last_lh = curr_price

        # Classify consecutive pairs of swing lows
        for i in range(1, len(lows_chron)):
            prev_price = lows_chron[i - 1][1]
            curr_price = lows_chron[i][1]
            if curr_price > prev_price:
                hl_count += 1
                last_hl = curr_price
            elif curr_price < prev_price:
                ll_count += 1
                last_ll = curr_price

        # Determine trend
        if hh_count > 0 and hl_count > 0 and hh_count >= lh_count and hl_count >= ll_count:
            trend = "BULLISH"
        elif lh_count > 0 and ll_count > 0 and lh_count >= hh_count and ll_count >= hl_count:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"

        logger.debug(
            "Market structure: %s  HH=%d HL=%d LH=%d LL=%d",
            trend, hh_count, hl_count, lh_count, ll_count,
        )

        return {
            "trend": trend,
            "last_hh": last_hh,
            "last_hl": last_hl,
            "last_lh": last_lh,
            "last_ll": last_ll,
            "hh_count": hh_count,
            "hl_count": hl_count,
            "lh_count": lh_count,
            "ll_count": ll_count,
            "swing_highs": highs,
            "swing_lows": lows,
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Return the most-recent ATR value (simple average of True Range)."""
        high = df["high"]
        low = df["low"]
        close = df["close"] if "close" in df.columns else (high + low) / 2

        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr_series = tr.rolling(window=period, min_periods=1).mean()
        val = atr_series.iloc[-1]
        return float(val) if not np.isnan(val) else 1.0
