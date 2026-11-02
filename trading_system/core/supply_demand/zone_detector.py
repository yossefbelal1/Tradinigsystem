"""
core/supply_demand/zone_detector.py
===================================
Supply and Demand Zone Identification Engine.
Detects Rally-Base-Drop (Supply) and Drop-Base-Rally (Demand) formations
based on impulsive departures, base consolidation quality, and institutional order blocks.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.config.settings import SD_ATR_MULTIPLIER, SD_MAX_BASE_CANDLES, ZoneState

logger = logging.getLogger(__name__)


class SupplyDemandDetector:
    """
    Identifies institutional Supply and Demand zones from raw price action.
    """

    def __init__(
        self,
        atr_multiplier: float = SD_ATR_MULTIPLIER,
        max_base_candles: int = SD_MAX_BASE_CANDLES,
    ):
        self.atr_multiplier = atr_multiplier
        self.max_base_candles = max_base_candles

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(df) < 2:
            return float(df["close"].iloc[-1] * 0.005) if not df.empty else 1.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        return float(np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr))

    def detect_zones(
        self,
        df: pd.DataFrame,
        atr: Optional[float] = None,
        lookback: int = 150,
    ) -> list[dict[str, Any]]:
        """
        Scan price history to detect Rally-Base-Drop (Supply) and Drop-Base-Rally (Demand) zones.
        """
        if df.empty or len(df) < 10:
            return []

        window = df.iloc[-lookback:].copy().reset_index(drop=True)
        local_atr = atr or self.calculate_atr(window)
        n = len(window)

        zones: list[dict[str, Any]] = []

        # Iterate through candles looking for impulsive departure bars
        for i in range(2, n - 1):
            curr_open = float(window["open"].iloc[i])
            curr_close = float(window["close"].iloc[i])
            curr_high = float(window["high"].iloc[i])
            curr_low = float(window["low"].iloc[i])

            body = abs(curr_close - curr_open)
            is_bullish = curr_close > curr_open
            is_bearish = curr_close < curr_open

            # Check if this candle is a strong impulsive departure
            if body < (self.atr_multiplier * local_atr):
                continue

            # ── 1. DEMAND ZONE: Drop-Base-Rally (Bullish Departure) ─────────
            if is_bullish and curr_close > float(window["high"].iloc[i - 1]):
                # Look backwards for base candles (up to max_base_candles)
                base_start = i - 1
                while base_start > 0 and (i - base_start) <= self.max_base_candles:
                    base_open = float(window["open"].iloc[base_start])
                    base_close = float(window["close"].iloc[base_start])
                    base_body = abs(base_close - base_open)

                    # Base candle should have smaller body
                    if base_body <= (local_atr * 1.0):
                        base_start -= 1
                    else:
                        break

                actual_base_start = max(0, base_start + 1)
                if actual_base_start < i:
                    base_slice = window.iloc[actual_base_start:i]
                    top = float(base_slice["high"].max())
                    bottom = float(base_slice["low"].min())
                    midpoint = (top + bottom) / 2.0

                    departure_strength = round(body / local_atr, 2)
                    base_quality = round(1.0 - (len(base_slice) - 1) * 0.2, 2)

                    zones.append({
                        "zone_id": str(uuid.uuid4())[:8],
                        "type": "DEMAND",
                        "top": round(top, 2),
                        "bottom": round(bottom, 2),
                        "midpoint": round(midpoint, 2),
                        "base_start_idx": actual_base_start,
                        "departure_candle_idx": i,
                        "creation_time": str(window["time"].iloc[i] if "time" in window.columns else i),
                        "atr_at_creation": round(local_atr, 2),
                        "departure_strength": departure_strength,
                        "base_quality": max(0.2, base_quality),
                        "state": ZoneState.FRESH.value,
                        "touch_count": 0,
                    })

            # ── 2. SUPPLY ZONE: Rally-Base-Drop (Bearish Departure) ─────────
            elif is_bearish and curr_close < float(window["low"].iloc[i - 1]):
                base_start = i - 1
                while base_start > 0 and (i - base_start) <= self.max_base_candles:
                    base_open = float(window["open"].iloc[base_start])
                    base_close = float(window["close"].iloc[base_start])
                    base_body = abs(base_close - base_open)

                    if base_body <= (local_atr * 1.0):
                        base_start -= 1
                    else:
                        break

                actual_base_start = max(0, base_start + 1)
                if actual_base_start < i:
                    base_slice = window.iloc[actual_base_start:i]
                    top = float(base_slice["high"].max())
                    bottom = float(base_slice["low"].min())
                    midpoint = (top + bottom) / 2.0

                    departure_strength = round(body / local_atr, 2)
                    base_quality = round(1.0 - (len(base_slice) - 1) * 0.2, 2)

                    zones.append({
                        "zone_id": str(uuid.uuid4())[:8],
                        "type": "SUPPLY",
                        "top": round(top, 2),
                        "bottom": round(bottom, 2),
                        "midpoint": round(midpoint, 2),
                        "base_start_idx": actual_base_start,
                        "departure_candle_idx": i,
                        "creation_time": str(window["time"].iloc[i] if "time" in window.columns else i),
                        "atr_at_creation": round(local_atr, 2),
                        "departure_strength": departure_strength,
                        "base_quality": max(0.2, base_quality),
                        "state": ZoneState.FRESH.value,
                        "touch_count": 0,
                    })

        return zones
