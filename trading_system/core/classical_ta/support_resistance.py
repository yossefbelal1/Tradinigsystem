"""
core/classical_ta/support_resistance.py
======================================
Classical Support & Resistance Level Detection Engine.
Identifies institutional reaction zones, swing clustering, role reversals,
and distinguishes major vs. minor levels without chart clutter.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.core.market_structure.swing_detector import SwingDetector

logger = logging.getLogger(__name__)


class SupportResistanceDetector:
    """
    Robust Support and Resistance detection using swing cluster analysis,
    touch counting, role reversal identification, and round number weighting.
    """

    def __init__(self, swing_detector: Optional[SwingDetector] = None):
        self.swing_detector = swing_detector or SwingDetector()

    def detect_levels(
        self,
        df: pd.DataFrame,
        lookback: int = 200,
        min_touches: int = 2,
        atr_proximity_pct: float = 0.003,
        max_levels: int = 12,
    ) -> list[dict[str, Any]]:
        """
        Identify significant S/R levels over the given lookback window.
        """
        if df.empty or len(df) < 15:
            return []

        # Slice to lookback window
        window = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()

        # Detect swings
        annotated = self.swing_detector.detect_swings(window, order=4)
        atr = self._calculate_atr(window)
        proximity_threshold = max(atr * 0.75, window["close"].iloc[-1] * atr_proximity_pct)

        # Gather swing points
        high_swings = []
        low_swings = []

        for idx, row in annotated.iterrows():
            t = row.get("time", idx)
            if row.get("swing_high", False):
                high_swings.append((t, float(row["high"]), "RESISTANCE"))
            if row.get("swing_low", False):
                low_swings.append((t, float(row["low"]), "SUPPORT"))

        all_swings = high_swings + low_swings
        if not all_swings:
            return []

        # Cluster swing prices into candidate levels
        levels_clusters = self._cluster_swings(all_swings, proximity_threshold)

        # Score and qualify each cluster
        scored_levels: list[dict[str, Any]] = []
        current_price = float(window["close"].iloc[-1])

        for cluster in levels_clusters:
            touches = len(cluster)
            if touches < min_touches:
                continue

            prices = [item[1] for item in cluster]
            types = [item[2] for item in cluster]
            times = [item[0] for item in cluster]

            avg_price = float(np.mean(prices))
            first_time = times[0]
            last_time = times[-1]

            # Role reversal: has both SUPPORT touches and RESISTANCE touches
            has_sup = "SUPPORT" in types
            has_res = "RESISTANCE" in types
            role_reversal = has_sup and has_res

            if role_reversal:
                level_type = "BOTH"
            elif has_res:
                level_type = "RESISTANCE"
            else:
                level_type = "SUPPORT"

            # Universal psychological round number weighting across all asset scales
            is_round_hundred, is_round_fifty = self._is_psychological_level(avg_price, atr)

            # Strength score calculation (0.0 to 1.0)
            score = 0.0
            score += min(touches * 0.15, 0.45)           # Up to 0.45 for touch count
            if role_reversal:
                score += 0.20                            # 0.20 bonus for polarity flip
            if is_round_hundred:
                score += 0.20
            elif is_round_fifty:
                score += 0.10

            # Recency bonus
            score += 0.15

            strength = float(np.clip(score, 0.1, 1.0))
            is_major = strength >= 0.65 or touches >= 4 or role_reversal or is_round_hundred

            # Dynamic precision based on price magnitude
            price_prec = 5 if avg_price < 5.0 else (3 if avg_price < 250.0 else 2)

            scored_levels.append({
                "price": round(avg_price, price_prec),
                "type": level_type,
                "strength": round(strength, 2),
                "touch_count": touches,
                "last_touch_time": str(last_time),
                "first_touch_time": str(first_time),
                "role_reversals": role_reversal,
                "is_major": is_major,
                "distance_to_price": round(abs(avg_price - current_price), price_prec),
            })

        # Sort by strength desc, keep top max_levels
        scored_levels.sort(key=lambda x: (x["strength"], x["touch_count"]), reverse=True)
        final_levels = scored_levels[:max_levels]

        # Re-sort by price ascending for easy reading
        final_levels.sort(key=lambda x: x["price"])
        return final_levels

    def get_nearest_levels(
        self,
        levels: list[dict[str, Any]],
        current_price: float,
        n_above: int = 3,
        n_below: int = 3,
    ) -> dict[str, list[dict[str, Any]]]:
        """Separate levels into nearest resistances above and supports below current price."""
        above = [lvl for lvl in levels if lvl["price"] > current_price]
        below = [lvl for lvl in levels if lvl["price"] < current_price]

        above.sort(key=lambda x: x["price"])                   # lowest above first
        below.sort(key=lambda x: x["price"], reverse=True)     # highest below first

        return {
            "resistance": above[:n_above],
            "support": below[:n_below],
        }

    def classify_breakout(
        self,
        df: pd.DataFrame,
        level: float,
        candle_idx: int = -1,
        atr: Optional[float] = None,
    ) -> str:
        """
        Classify the interaction between the latest candle and an S/R level.
        Returns: BREAKOUT_ABOVE / BREAKOUT_BELOW / RETEST / REJECTION / NONE
        """
        if df.empty or len(df) < 2:
            return "NONE"

        c = df.iloc[candle_idx]
        prev = df.iloc[candle_idx - 1] if abs(candle_idx) < len(df) else c
        local_atr = atr or self._calculate_atr(df)
        buf = local_atr * 0.25

        c_close = float(c["close"])
        c_open = float(c["open"])
        c_high = float(c["high"])
        c_low = float(c["low"])
        prev_close = float(prev["close"])

        # Breakout Above: previously below, now cleanly closed above level + buffer
        if prev_close <= level and c_close > (level + buf):
            return "BREAKOUT_ABOVE"

        # Breakout Below: previously above, now cleanly closed below level - buf
        if prev_close >= level and c_close < (level - buf):
            return "BREAKOUT_BELOW"

        # Rejection: candle wick crossed level but close pulled back strongly
        wick_high_crossed = c_high >= level and c_close < level
        wick_low_crossed = c_low <= level and c_close > level

        if wick_high_crossed and (c_high - max(c_open, c_close)) >= (local_atr * 0.35):
            return "REJECTION_BEARISH"

        if wick_low_crossed and (min(c_open, c_close) - c_low) >= (local_atr * 0.35):
            return "REJECTION_BULLISH"

        # Retest: price touched level within buffer and reversed in trend direction
        if abs(c_low - level) <= buf and c_close > level:
            return "RETEST_SUPPORT"
        if abs(c_high - level) <= buf and c_close < level:
            return "RETEST_RESISTANCE"

        return "NONE"

    # ─────────────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _cluster_swings(
        self,
        swings: list[tuple[Any, float, str]],
        threshold: float,
    ) -> list[list[tuple[Any, float, str]]]:
        """Greedy agglomerative clustering of prices within threshold distance."""
        sorted_swings = sorted(swings, key=lambda x: x[1])
        clusters: list[list[tuple[Any, float, str]]] = []

        current_cluster: list[tuple[Any, float, str]] = []

        for item in sorted_swings:
            if not current_cluster:
                current_cluster.append(item)
            else:
                cluster_mean = np.mean([p[1] for p in current_cluster])
                if abs(item[1] - cluster_mean) <= threshold:
                    current_cluster.append(item)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [item]

        if current_cluster:
            clusters.append(current_cluster)

        return clusters

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < 2:
            return float(df["close"].iloc[-1] * 0.005) if not df.empty else 1.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        if len(tr) == 0:
            return float(df["close"].iloc[-1] * 0.005) if not df.empty else 1.0
        return float(np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr))

    @staticmethod
    def _is_psychological_level(price: float, atr: float) -> tuple[bool, bool]:
        """
        Check if price is near a major or minor psychological round number across any asset scale.
        Returns: (is_major_round, is_minor_round)
        """
        import math
        if price <= 0:
            return False, False

        log_val = math.floor(math.log10(price))
        if log_val <= 0:  # e.g. Forex 1.xxxx
            major_step = 0.0100   # 100 pips
            minor_step = 0.0050   # 50 pips
        elif log_val in (1, 2):  # e.g. Crude oil 70.0, or JPY 155.0
            major_step = 1.00 if price < 100 else 10.0
            minor_step = 0.50 if price < 100 else 5.0
        elif log_val == 3:  # e.g. Gold 2700-3900, S&P 500 5000-7600
            major_step = 100.0
            minor_step = 50.0
        else:  # e.g. Indices 28000-50000, Bitcoin 80000+
            major_step = 1000.0
            minor_step = 500.0

        dist_to_major = abs(price - round(price / major_step) * major_step)
        dist_to_minor = abs(price - round(price / minor_step) * minor_step)

        tolerance = max(atr * 0.25, major_step * 0.05)
        is_major = dist_to_major <= tolerance
        is_minor = dist_to_minor <= tolerance and not is_major

        return is_major, is_minor
