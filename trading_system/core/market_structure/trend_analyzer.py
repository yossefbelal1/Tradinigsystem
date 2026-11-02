"""
Trend Analyzer
==============
Multi-method trend identification using ADX, swing-sequence analysis,
linear regression channels, and range-bound detection.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from trading_system.core.market_structure.swing_detector import SwingDetector

logger = logging.getLogger(__name__)

_swing_detector = SwingDetector()


class TrendAnalyzer:
    """
    Comprehensive trend analysis for a single timeframe.

    All public methods expect a DataFrame with columns:
        open, high, low, close  (and optionally 'volume' / 'tick_volume')
    indexed by timestamp (datetime).
    """

    def __init__(self, swing_detector: Optional[SwingDetector] = None):
        self.swing_detector = swing_detector or _swing_detector

    # ------------------------------------------------------------------ #
    #  Primary trend identification                                        #
    # ------------------------------------------------------------------ #

    def identify_trend(self, df: pd.DataFrame) -> dict:
        """
        Identify the dominant trend using ADX + swing structure.

        Returns
        -------
        dict:
            primary_trend      : str   – 'BULLISH' | 'BEARISH' | 'SIDEWAYS'
            strength           : float – 0-1 normalised from ADX
            higher_highs_count : int
            higher_lows_count  : int
            lower_highs_count  : int
            lower_lows_count   : int
            adx                : float
            trend_consistency  : float – fraction of bars moving in trend dir
        """
        if len(df) < 20:
            return self._empty_trend_result()

        # ADX
        adx_val, plus_di, minus_di = self._calculate_adx(df)

        # Swing structure
        structure = self.swing_detector.classify_market_structure(df)
        hh = structure["hh_count"]
        hl = structure["hl_count"]
        lh = structure["lh_count"]
        ll = structure["ll_count"]

        # Determine trend from swing structure first, use ADX DI for tie-break
        if structure["trend"] == "BULLISH":
            primary_trend = "BULLISH"
        elif structure["trend"] == "BEARISH":
            primary_trend = "BEARISH"
        else:
            # Use DI crossover as secondary signal
            if plus_di > minus_di and adx_val > 20:
                primary_trend = "BULLISH"
            elif minus_di > plus_di and adx_val > 20:
                primary_trend = "BEARISH"
            else:
                primary_trend = "SIDEWAYS"

        # Normalise ADX to 0-1 (ADX > 50 is very strong; cap at 60)
        strength = float(np.clip(adx_val / 60.0, 0.0, 1.0))

        # Trend consistency: what fraction of candles moved in the trend dir
        consistency = self._calculate_trend_consistency(df, primary_trend)

        return {
            "primary_trend": primary_trend,
            "strength": round(strength, 4),
            "higher_highs_count": hh,
            "higher_lows_count": hl,
            "lower_highs_count": lh,
            "lower_lows_count": ll,
            "adx": round(float(adx_val), 2),
            "plus_di": round(float(plus_di), 2),
            "minus_di": round(float(minus_di), 2),
            "trend_consistency": round(consistency, 4),
        }

    # ------------------------------------------------------------------ #
    #  Trend channels                                                      #
    # ------------------------------------------------------------------ #

    def detect_trend_channels(self, df: pd.DataFrame) -> List[dict]:
        """
        Identify parallel trendline channels from swing highs and lows.

        Returns
        -------
        list of channel dicts, each with:
            upper_line     : dict(slope, intercept)
            lower_line     : dict(slope, intercept)
            channel_width  : float – price distance between lines at latest bar
            direction      : str   – 'ASCENDING' | 'DESCENDING' | 'HORIZONTAL'
            r_squared      : float – quality of fit
            touches        : int   – combined touch count
        """
        if len(df) < 30:
            return []

        annotated = self.swing_detector.detect_swings(df, order=5)
        channels: List[dict] = []

        # Build numeric x-axis (bar index)
        bar_idx = np.arange(len(annotated))

        # ---- Resistance channel (swing highs) ----
        sh_mask = annotated["swing_high"].to_numpy()
        sh_prices = annotated["swing_high_price"].to_numpy()
        sh_x = bar_idx[sh_mask & ~np.isnan(sh_prices)]
        sh_y = sh_prices[sh_mask & ~np.isnan(sh_prices)]

        # ---- Support channel (swing lows) ----
        sl_mask = annotated["swing_low"].to_numpy()
        sl_prices = annotated["swing_low_price"].to_numpy()
        sl_x = bar_idx[sl_mask & ~np.isnan(sl_prices)]
        sl_y = sl_prices[sl_mask & ~np.isnan(sl_prices)]

        if len(sh_x) < 2 or len(sl_x) < 2:
            return []

        # Linear regression for resistance line
        r_slope, r_intercept, r_r, _, _ = scipy_stats.linregress(sh_x, sh_y)
        r_squared_h = r_r ** 2

        # Linear regression for support line
        s_slope, s_intercept, s_r, _, _ = scipy_stats.linregress(sl_x, sl_y)
        r_squared_l = s_r ** 2

        # Combine into one channel if slopes are within 10% of each other
        if len(sh_x) >= 2 and len(sl_x) >= 2:
            slope_diff = abs(r_slope - s_slope) / (abs(r_slope) + 1e-10)
            if slope_diff < 0.50:  # allow reasonable parallelism
                n = len(annotated) - 1
                upper_price = r_slope * n + r_intercept
                lower_price = s_slope * n + s_intercept
                channel_width = upper_price - lower_price

                avg_slope = (r_slope + s_slope) / 2
                if avg_slope > 0.001:
                    direction = "ASCENDING"
                elif avg_slope < -0.001:
                    direction = "DESCENDING"
                else:
                    direction = "HORIZONTAL"

                r_squared = (r_squared_h + r_squared_l) / 2

                channels.append({
                    "upper_line": {"slope": round(r_slope, 6), "intercept": round(r_intercept, 4)},
                    "lower_line": {"slope": round(s_slope, 6), "intercept": round(s_intercept, 4)},
                    "channel_width": round(abs(channel_width), 4),
                    "direction": direction,
                    "r_squared": round(r_squared, 4),
                    "touches": int(len(sh_x) + len(sl_x)),
                })

        return channels

    # ------------------------------------------------------------------ #
    #  Trading range detection                                             #
    # ------------------------------------------------------------------ #

    def is_in_trading_range(
        self, df: pd.DataFrame, lookback: int = 50
    ) -> dict:
        """
        Detect whether the market is range-bound over the last `lookback` bars.

        A market is considered range-bound when:
            * ADX < 25  (weak trend)
            * The price range (high-to-low) is < 3 × ATR on average

        Returns
        -------
        dict:
            range_bound     : bool
            range_high      : float
            range_low       : float
            range_width_pct : float – range as % of midpoint price
            adx             : float
        """
        window = df.iloc[-lookback:] if len(df) >= lookback else df

        range_high = float(window["high"].max())
        range_low = float(window["low"].min())
        mid = (range_high + range_low) / 2
        range_width_pct = ((range_high - range_low) / mid) * 100 if mid else 0.0

        adx_val, _, _ = self._calculate_adx(window)

        # ATR-based range check
        atr = _swing_detector._calculate_atr(window, period=14)
        atr_ratio = (range_high - range_low) / atr if atr else 999

        # Range-bound when ADX weak AND price range is compressed
        range_bound = bool(adx_val < 25 and atr_ratio < 6)

        return {
            "range_bound": range_bound,
            "range_high": round(range_high, 4),
            "range_low": round(range_low, 4),
            "range_width_pct": round(range_width_pct, 2),
            "adx": round(float(adx_val), 2),
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _calculate_adx(
        df: pd.DataFrame, period: int = 14
    ) -> tuple[float, float, float]:
        """
        Wilder-smoothed ADX / +DI / -DI.

        Returns (adx, plus_di, minus_di) for the most-recent bar.
        """
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        n = len(close)

        if n < period + 1:
            return 20.0, 25.0, 25.0

        # True range
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)

        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)

            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]

            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move

        # Wilder smoothing
        def wilder_smooth(arr, p):
            out = np.zeros(len(arr))
            out[p] = arr[1 : p + 1].sum()
            for i in range(p + 1, len(arr)):
                out[i] = out[i - 1] - out[i - 1] / p + arr[i]
            return out

        atr_s = wilder_smooth(tr, period)
        pdm_s = wilder_smooth(plus_dm, period)
        mdm_s = wilder_smooth(minus_dm, period)

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = np.where(atr_s != 0, 100 * pdm_s / atr_s, 0.0)
            mdi = np.where(atr_s != 0, 100 * mdm_s / atr_s, 0.0)
            dx = np.where(
                (pdi + mdi) != 0,
                100 * np.abs(pdi - mdi) / (pdi + mdi),
                0.0,
            )

        adx_arr = wilder_smooth(dx, period)
        # Normalise adx_arr from index period*2 onward
        idx = min(n - 1, max(period * 2, period + 1))
        return float(adx_arr[idx]), float(pdi[idx]), float(mdi[idx])

    @staticmethod
    def _calculate_trend_consistency(
        df: pd.DataFrame, trend: str, lookback: int = 30
    ) -> float:
        """
        Fraction of recent bars whose close-to-close move agrees with the trend.
        """
        window = df.iloc[-lookback:] if len(df) >= lookback else df
        closes = window["close"].to_numpy(dtype=float)
        if len(closes) < 2:
            return 0.5

        moves = np.diff(closes)
        if trend == "BULLISH":
            agree = (moves > 0).sum()
        elif trend == "BEARISH":
            agree = (moves < 0).sum()
        else:
            agree = (np.abs(moves) < np.std(moves)).sum()

        return float(agree / len(moves))

    @staticmethod
    def _empty_trend_result() -> dict:
        return {
            "primary_trend": "SIDEWAYS",
            "strength": 0.0,
            "higher_highs_count": 0,
            "higher_lows_count": 0,
            "lower_highs_count": 0,
            "lower_lows_count": 0,
            "adx": 0.0,
            "plus_di": 0.0,
            "minus_di": 0.0,
            "trend_consistency": 0.5,
        }
