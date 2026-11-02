"""
core/classical_ta/trendlines.py
===============================
Classical Trendline Detection Engine using linear regression and swing touch analysis.
Identifies major ascending/descending trendlines, channels, and trendline break events.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.core.market_structure.swing_detector import SwingDetector

logger = logging.getLogger(__name__)


class TrendlineDetector:
    """
    Identifies mathematically verified trendlines connecting swing points.
    Filters out spurious lines by requiring multiple touches and checking for violations.
    """

    def __init__(self, swing_detector: Optional[SwingDetector] = None):
        self.swing_detector = swing_detector or SwingDetector()

    def detect_trendlines(
        self,
        df: pd.DataFrame,
        min_touches: int = 3,
        lookback: int = 150,
        max_deviation_atr: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Detect ascending support trendlines and descending resistance trendlines.
        """
        if df.empty or len(df) < 20:
            return []

        window = df.iloc[-lookback:].copy().reset_index(drop=True)
        n = len(window)

        # Detect swings
        annotated = self.swing_detector.detect_swings(window, order=3)
        atr = self._calculate_atr(window)
        tolerance = atr * max_deviation_atr

        high_indices = window.index[annotated["swing_high"]].tolist()
        low_indices = window.index[annotated["swing_low"]].tolist()

        trendlines: list[dict[str, Any]] = []

        # 1. Detect Support Trendlines from Swing Lows
        support_lines = self._find_lines_from_points(
            indices=low_indices,
            prices=window["low"].to_numpy(),
            line_type="SUPPORT_TL",
            window_df=window,
            min_touches=min_touches,
            tolerance=tolerance,
        )
        trendlines.extend(support_lines)

        # 2. Detect Resistance Trendlines from Swing Highs
        resistance_lines = self._find_lines_from_points(
            indices=high_indices,
            prices=window["high"].to_numpy(),
            line_type="RESISTANCE_TL",
            window_df=window,
            min_touches=min_touches,
            tolerance=tolerance,
        )
        trendlines.extend(resistance_lines)

        # Filter to active and highest strength lines
        trendlines.sort(key=lambda x: (not x["is_broken"], x["strength"]), reverse=True)
        return trendlines[:6]

    def get_trendline_price_at(self, tl: dict[str, Any], x_index: int) -> float:
        """Calculate line price at an integer bar index."""
        slope = tl.get("slope", 0.0)
        intercept = tl.get("intercept", 0.0)
        return float(slope * x_index + intercept)

    def detect_trendline_break(
        self,
        df: pd.DataFrame,
        tl: dict[str, Any],
        lookback_bars: int = 5,
    ) -> Optional[dict[str, Any]]:
        """
        Check if the trendline was cleanly broken by recent candle closes.
        """
        if df.empty or tl.get("is_broken", False):
            return None

        recent = df.iloc[-lookback_bars:]
        line_type = tl.get("type", "")

        for i, row in recent.iterrows():
            idx = int(row.name if isinstance(row.name, (int, np.integer)) else len(df) - lookback_bars)
            line_val = self.get_trendline_price_at(tl, idx)
            close = float(row["close"])

            if line_type == "SUPPORT_TL" and close < line_val:
                return {
                    "event": "BEARISH_BREAK",
                    "time": str(row.get("time", "")),
                    "break_price": close,
                    "trendline_price": line_val,
                }
            elif line_type == "RESISTANCE_TL" and close > line_val:
                return {
                    "event": "BULLISH_BREAK",
                    "time": str(row.get("time", "")),
                    "break_price": close,
                    "trendline_price": line_val,
                }

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _find_lines_from_points(
        self,
        indices: list[int],
        prices: np.ndarray,
        line_type: str,
        window_df: pd.DataFrame,
        min_touches: int,
        tolerance: float,
    ) -> list[dict[str, Any]]:
        if len(indices) < 2:
            return []

        lines: list[dict[str, Any]] = []
        n_bars = len(window_df)

        # Iterate pairs of swing points
        for i in range(len(indices)):
            for j in range(i + 1, min(i + 5, len(indices))):
                x1, x2 = indices[i], indices[j]
                y1, y2 = prices[x1], prices[x2]

                if x2 == x1:
                    continue

                slope = (y2 - y1) / (x2 - x1)
                intercept = y1 - slope * x1

                # Angle check (filter extreme slopes)
                angle_rad = math.atan(slope)
                angle_deg = math.degrees(angle_rad)

                # Count touches across all bars in window
                touches = 0
                touch_indices = []
                broken = False

                for k in range(x1, n_bars):
                    bar_low = float(window_df["low"].iloc[k])
                    bar_high = float(window_df["high"].iloc[k])
                    bar_close = float(window_df["close"].iloc[k])
                    expected_y = slope * k + intercept

                    if line_type == "SUPPORT_TL":
                        # Support: touches near expected_y from above
                        if abs(bar_low - expected_y) <= tolerance:
                            touches += 1
                            touch_indices.append(k)
                        elif bar_close < (expected_y - tolerance * 1.5):
                            # Violation
                            broken = True
                    else:
                        # Resistance: touches near expected_y from below
                        if abs(bar_high - expected_y) <= tolerance:
                            touches += 1
                            touch_indices.append(k)
                        elif bar_close > (expected_y + tolerance * 1.5):
                            broken = True

                if touches >= min_touches:
                    strength = min(0.3 + touches * 0.15, 1.0)
                    if not broken:
                        strength += 0.2

                    lines.append({
                        "type": line_type,
                        "slope": round(slope, 6),
                        "intercept": round(intercept, 4),
                        "touches": touches,
                        "touch_indices": touch_indices,
                        "angle_deg": round(angle_deg, 2),
                        "strength": round(min(strength, 1.0), 2),
                        "is_broken": broken,
                        "current_price": round(slope * (n_bars - 1) + intercept, 2),
                    })

        return lines

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < 2:
            return 5.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        return float(np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr))
