"""
Structure Break Detector
========================
Identifies Break of Structure (BOS) and Change of Character (CHoCH) events,
as well as failed breakouts — key building blocks of Smart Money Concepts (SMC)
and ICT-style analysis.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class StructureBreakDetector:
    """
    Detects three types of structural price events:

    1. Break of Structure (BOS)  – continuation signal
    2. Change of Character (CHoCH) – potential reversal signal
    3. Failed Breakouts          – fakeouts at S/R levels
    """

    def __init__(self, swing_detector: Optional[Any] = None):
        self.swing_detector = swing_detector

    # ------------------------------------------------------------------ #
    #  Break of Structure                                                  #
    # ------------------------------------------------------------------ #

    def detect_bos(
        self, df: pd.DataFrame, swings: pd.DataFrame
    ) -> List[dict]:
        """
        Detect Break-of-Structure events.

        A BOS occurs when:
        * BULLISH BOS : a candle *closes* above the most-recent significant
                        swing high.
        * BEARISH BOS : a candle *closes* below the most-recent significant
                        swing low.

        Parameters
        ----------
        df     : OHLC DataFrame (full history used to find break candles).
        swings : DataFrame with 'swing_high', 'swing_low', 'swing_high_price',
                 'swing_low_price' columns (output of SwingDetector).

        Returns
        -------
        List of dicts:
            type          : 'BULLISH_BOS' | 'BEARISH_BOS'
            timestamp     : pandas Timestamp of break candle
            price         : close price of break candle
            broken_level  : float – the swing price that was violated
            strength      : float – (close - broken_level) / ATR
        """
        if len(df) < 10 or "swing_high" not in swings.columns:
            return []

        atr = self._atr(df)
        bos_events: List[dict] = []

        # Extract confirmed swing highs and lows in chronological order
        sh_df = swings[swings["swing_high"]].sort_index()
        sl_df = swings[swings["swing_low"]].sort_index()

        close_arr = df["close"]

        # Iterate each bar in df looking for BOS
        sh_idx_list = list(sh_df.index)
        sl_idx_list = list(sl_df.index)

        # Track which swings have already been "broken" to avoid duplicates
        broken_high_set: set = set()
        broken_low_set: set = set()

        for bar_ts, bar in df.iterrows():
            close = bar["close"]

            # --- BULLISH BOS: close above the latest confirmed swing high
            #     that occurred BEFORE this bar
            prior_highs = [
                ts for ts in sh_idx_list
                if ts < bar_ts and ts not in broken_high_set
            ]
            if prior_highs:
                latest_sh_ts = prior_highs[-1]
                sh_price = float(swings.at[latest_sh_ts, "swing_high_price"])
                if close > sh_price:
                    strength = (close - sh_price) / atr if atr else 0.0
                    bos_events.append({
                        "type": "BULLISH_BOS",
                        "timestamp": bar_ts,
                        "price": round(float(close), 4),
                        "broken_level": round(sh_price, 4),
                        "strength": round(strength, 3),
                    })
                    broken_high_set.add(latest_sh_ts)

            # --- BEARISH BOS: close below the latest confirmed swing low
            prior_lows = [
                ts for ts in sl_idx_list
                if ts < bar_ts and ts not in broken_low_set
            ]
            if prior_lows:
                latest_sl_ts = prior_lows[-1]
                sl_price = float(swings.at[latest_sl_ts, "swing_low_price"])
                if close < sl_price:
                    strength = (sl_price - close) / atr if atr else 0.0
                    bos_events.append({
                        "type": "BEARISH_BOS",
                        "timestamp": bar_ts,
                        "price": round(float(close), 4),
                        "broken_level": round(sl_price, 4),
                        "strength": round(strength, 3),
                    })
                    broken_low_set.add(latest_sl_ts)

        logger.debug("detect_bos: %d BOS events found", len(bos_events))
        return bos_events

    # ------------------------------------------------------------------ #
    #  Change of Character                                                 #
    # ------------------------------------------------------------------ #

    def detect_choch(
        self, df: pd.DataFrame, swings: pd.DataFrame
    ) -> List[dict]:
        """
        Detect Change of Character (CHoCH) events.

        CHoCH = the *first* BOS that occurs *against* the prevailing trend.
        It signals a potential reversal rather than continuation.

        Algorithm
        ---------
        1. Find all BOS events.
        2. Determine the prevailing trend at the time of each BOS using the
           last 3 BOS events before it.
        3. If a BOS is opposite to the established trend, flag it as CHoCH.

        Returns
        -------
        List of dicts same as detect_bos() but with extra keys:
            choch_type   : 'BULLISH_CHOCH' | 'BEARISH_CHOCH'
            prior_trend  : str
        """
        bos_list = self.detect_bos(df, swings)
        if not bos_list:
            return []

        choch_events: List[dict] = []

        # Determine running trend from sequence of BOS
        # We look at the last N bos events to gauge trend direction
        window = 3
        for i, bos in enumerate(bos_list):
            if i < window:
                continue  # Not enough history

            prior_bos = bos_list[i - window : i]
            bull_count = sum(1 for b in prior_bos if b["type"] == "BULLISH_BOS")
            bear_count = sum(1 for b in prior_bos if b["type"] == "BEARISH_BOS")

            if bull_count > bear_count:
                established_trend = "BULLISH"
            elif bear_count > bull_count:
                established_trend = "BEARISH"
            else:
                continue  # Mixed trend, no clear CHoCH

            is_choch = (
                (established_trend == "BULLISH" and bos["type"] == "BEARISH_BOS")
                or (established_trend == "BEARISH" and bos["type"] == "BULLISH_BOS")
            )

            if is_choch:
                choch_type = (
                    "BEARISH_CHOCH"
                    if bos["type"] == "BEARISH_BOS"
                    else "BULLISH_CHOCH"
                )
                event = bos.copy()
                event["choch_type"] = choch_type
                event["prior_trend"] = established_trend
                choch_events.append(event)

        logger.debug("detect_choch: %d CHoCH events found", len(choch_events))
        return choch_events

    # ------------------------------------------------------------------ #
    #  Failed Breakouts                                                    #
    # ------------------------------------------------------------------ #

    def detect_failed_breakouts(
        self, df: pd.DataFrame, sr_levels: List[float]
    ) -> List[dict]:
        """
        Identify failed breakouts (fakeouts) at S/R levels.

        A FAILED BULLISH breakout: price closes above `level` but within
        the next 3 candles closes back below it.

        A FAILED BEARISH breakout: price closes below `level` but within
        the next 3 candles closes back above it.

        Parameters
        ----------
        df        : OHLC DataFrame.
        sr_levels : List of price levels to monitor.

        Returns
        -------
        List of dicts:
            level     : float
            direction : 'FAILED_BULLISH' | 'FAILED_BEARISH'
            timestamp : Timestamp of the initial break candle
            type      : same as direction (legacy compat)
            candles_to_fail : int (1-3)
        """
        if len(df) < 5 or not sr_levels:
            return []

        atr = self._atr(df)
        tolerance = atr * 0.1  # Small tolerance for close vs level

        closes = df["close"].to_numpy(dtype=float)
        timestamps = df.index.to_numpy()
        n = len(closes)

        events: List[dict] = []

        for level in sr_levels:
            for i in range(1, n - 1):
                prev_close = closes[i - 1]
                curr_close = closes[i]

                # Potential BULLISH breakout: prev below, curr above
                if prev_close <= level + tolerance and curr_close > level + tolerance:
                    # Check next 1-3 candles for close back below
                    for j in range(1, min(4, n - i)):
                        future_close = closes[i + j]
                        if future_close < level - tolerance:
                            events.append({
                                "level": round(float(level), 4),
                                "direction": "FAILED_BULLISH",
                                "type": "FAILED_BULLISH",
                                "timestamp": pd.Timestamp(timestamps[i]),
                                "candles_to_fail": j,
                            })
                            break

                # Potential BEARISH breakout: prev above, curr below
                elif prev_close >= level - tolerance and curr_close < level - tolerance:
                    # Check next 1-3 candles for close back above
                    for j in range(1, min(4, n - i)):
                        future_close = closes[i + j]
                        if future_close > level + tolerance:
                            events.append({
                                "level": round(float(level), 4),
                                "direction": "FAILED_BEARISH",
                                "type": "FAILED_BEARISH",
                                "timestamp": pd.Timestamp(timestamps[i]),
                                "candles_to_fail": j,
                            })
                            break

        logger.debug(
            "detect_failed_breakouts: %d fakeouts found at %d levels",
            len(events), len(sr_levels),
        )
        return events

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range, most-recent value."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        val = tr.rolling(period, min_periods=1).mean().iloc[-1]
        return float(val) if not np.isnan(val) else 1.0
