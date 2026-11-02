"""
core/supply_demand/zone_validator.py
===================================
Supply & Demand Zone Lifecycle and Freshness Validator.
Evaluates zone mitigation, touch degradation, invalidation, and scores valid zones
so only high-probability fresh institutional areas are presented to the trader.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.config.settings import ZoneState

logger = logging.getLogger(__name__)


class ZoneValidator:
    """
    Validates, updates lifecycle state, and scores Supply and Demand zones.
    Filters out depleted, mitigated, or invalidated zones.
    """

    def update_zone_states(
        self,
        zones: list[dict[str, Any]],
        df: pd.DataFrame,
        current_price: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """
        Track price interaction with each zone from its departure candle to the current bar.
        Assigns ZoneState: FRESH, TESTED, MITIGATED, or INVALIDATED.
        """
        if df.empty or not zones:
            return zones

        curr_p = current_price if current_price is not None else float(df["close"].iloc[-1])
        updated_zones: list[dict[str, Any]] = []

        for z in zones:
            zone = dict(z)
            dep_idx = zone.get("departure_candle_idx", 0)
            top = zone["top"]
            bottom = zone["bottom"]
            midpoint = zone["midpoint"]
            z_type = zone["type"]

            # Subsequent price action after zone departure
            subsequent_df = df.iloc[dep_idx + 1:] if dep_idx < len(df) - 1 else pd.DataFrame()

            if subsequent_df.empty:
                zone["state"] = ZoneState.FRESH.value
                zone["touch_count"] = 0
                updated_zones.append(zone)
                continue

            touches = 0
            state = ZoneState.FRESH.value

            for _, row in subsequent_df.iterrows():
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])

                if z_type == "DEMAND":
                    # Entered zone: low dipped below top
                    if l <= top and h >= bottom:
                        touches += 1
                        # If close below bottom: cleanly invalidated
                        if c < bottom:
                            state = ZoneState.INVALIDATED.value
                            break
                        # If closed below 50% midpoint: mitigated
                        elif c < midpoint:
                            state = ZoneState.MITIGATED.value
                        else:
                            if state != ZoneState.MITIGATED.value:
                                state = ZoneState.TESTED.value

                    elif c < bottom:
                        state = ZoneState.INVALIDATED.value
                        break

                elif z_type == "SUPPLY":
                    # Entered zone: high pushed above bottom
                    if h >= bottom and l <= top:
                        touches += 1
                        # If close above top: cleanly invalidated
                        if c > top:
                            state = ZoneState.INVALIDATED.value
                            break
                        # If closed above 50% midpoint: mitigated
                        elif c > midpoint:
                            state = ZoneState.MITIGATED.value
                        else:
                            if state != ZoneState.MITIGATED.value:
                                state = ZoneState.TESTED.value

                    elif c > top:
                        state = ZoneState.INVALIDATED.value
                        break

            # If touched 3 or more times, liquidity is exhausted
            if touches >= 3 and state != ZoneState.INVALIDATED.value:
                state = ZoneState.INVALIDATED.value

            zone["state"] = state
            zone["touch_count"] = touches
            zone["distance_to_price"] = round(
                abs(curr_p - bottom) if curr_p > top else (abs(curr_p - top) if curr_p < bottom else 0.0),
                2
            )
            updated_zones.append(zone)

        return updated_zones

    def score_zone(
        self,
        zone: dict[str, Any],
        current_price: float,
        sr_levels: Optional[list[dict[str, Any]]] = None,
    ) -> float:
        """
        Score a zone from 0 to 100 based on departure momentum, base quality,
        lifecycle state, and confluence with classical S/R levels.
        """
        state = zone.get("state", ZoneState.FRESH.value)
        if state == ZoneState.INVALIDATED.value:
            return 0.0

        score = 0.0

        # 1. State bonus
        if state == ZoneState.FRESH.value:
            score += 35.0
        elif state == ZoneState.TESTED.value:
            score += 15.0
        elif state == ZoneState.MITIGATED.value:
            score += 5.0

        # 2. Departure strength (up to 30 points)
        dep_str = zone.get("departure_strength", 1.5)
        score += min(dep_str * 12.0, 30.0)

        # 3. Base quality (up to 20 points)
        base_qual = zone.get("base_quality", 0.5)
        score += base_qual * 20.0

        # 4. Confluence with classical S/R (up to 15 points)
        if sr_levels:
            mid = zone["midpoint"]
            for sr in sr_levels:
                if abs(sr["price"] - mid) <= (sr.get("distance_to_price", 10.0) * 0.15):
                    score += 15.0
                    break

        return round(float(np.clip(score, 0.0, 100.0)), 1)

    def filter_valid_zones(
        self,
        zones: list[dict[str, Any]],
        current_price: float,
        min_score: float = 40.0,
        sr_levels: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """
        Filter and return only active, valid FRESH or TESTED zones scoring above min_score.
        """
        scored = []
        for z in zones:
            score = self.score_zone(z, current_price, sr_levels)
            if score >= min_score and z["state"] in (ZoneState.FRESH.value, ZoneState.TESTED.value):
                item = dict(z)
                item["score"] = score
                scored.append(item)

        # Sort descending by score
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def get_zones_near_price(
        self,
        zones: list[dict[str, Any]],
        price: float,
        atr: float,
        max_distance_atr: float = 3.5,
    ) -> list[dict[str, Any]]:
        """Return zones within max_distance_atr multiples of the current price."""
        max_dist = atr * max_distance_atr
        near = []
        for z in zones:
            dist = z.get("distance_to_price", abs(price - z["midpoint"]))
            if dist <= max_dist:
                near.append(z)
        return near
