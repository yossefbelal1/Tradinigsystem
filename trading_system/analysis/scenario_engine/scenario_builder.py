"""
analysis/scenario_engine/scenario_builder.py
============================================
Scenario Generation Engine for Multi-Timeframe Analysis.
Constructs Primary and Alternative Conditional Scenarios based on deterministic
market structure evidence without arbitrary or uncalibrated percentage guesses.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ScenarioBuilder:
    """
    Constructs structured PRIMARY and ALTERNATIVE market scenarios.
    Categorizes confidence qualitatively as HIGH, MEDIUM, or LOW based on confluence count.
    """

    def build_scenarios(
        self,
        timeframe_analyses: dict[str, dict[str, Any]],
        synthesis: dict[str, Any],
        sr_levels: Optional[list[dict[str, Any]]] = None,
        zones: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Build conditional primary and alternative scenarios from pre-computed technical facts.
        """
        overall_bias = synthesis.get("overall_bias", "NEUTRAL").upper()
        aligned_count = int(synthesis.get("aligned_timeframes_count", 0))

        d1 = timeframe_analyses.get("D1", {})
        h4 = timeframe_analyses.get("H4", {})
        h1 = timeframe_analyses.get("H1", {})

        current_price = float(d1.get("current_price", h4.get("current_price", 2700.0)))
        atr = float(d1.get("atr", 15.0))

        # Extract levels if not passed
        if sr_levels is None:
            sr_levels = d1.get("sr_levels", [])
        if zones is None:
            zones = d1.get("supply_zones", []) + d1.get("demand_zones", [])

        # Resistances above and supports below
        res_prices = [lvl["price"] if isinstance(lvl, dict) else float(lvl) for lvl in sr_levels if (lvl["price"] if isinstance(lvl, dict) else float(lvl)) > current_price]
        sup_prices = [lvl["price"] if isinstance(lvl, dict) else float(lvl) for lvl in sr_levels if (lvl["price"] if isinstance(lvl, dict) else float(lvl)) < current_price]

        res_prices.sort()
        sup_prices.sort(reverse=True)

        target_res = res_prices[:2] if res_prices else [round(current_price + (atr * 2), 2)]
        target_sup = sup_prices[:2] if sup_prices else [round(current_price - (atr * 2), 2)]

        # Determine Primary Direction
        if overall_bias == "BULLISH":
            prim_dir = "BULLISH"
            alt_dir = "BEARISH"
            prim_targets = target_res
            alt_targets = target_sup
            inval = target_sup[0] if target_sup else current_price - (atr * 1.5)

            prim_trigger = f"Break and confirmed candle close above immediate resistance ({target_res[0]:.2f})"
            prim_desc = f"Bullish expansion targeting key institutional liquidity at {target_res[0]:.2f}."
            alt_trigger = f"Breakdown and close below structural support at {target_sup[0]:.2f}"
            alt_desc = f"Bearish liquidation driving price down toward deeper demand around {target_sup[0]:.2f}."

        elif overall_bias == "BEARISH":
            prim_dir = "BEARISH"
            alt_dir = "BULLISH"
            prim_targets = target_sup
            alt_targets = target_res
            inval = target_res[0] if target_res else current_price + (atr * 1.5)

            prim_trigger = f"Break and confirmed candle close below immediate support ({target_sup[0]:.2f})"
            prim_desc = f"Bearish expansion targeting key structural liquidity at {target_sup[0]:.2f}."
            alt_trigger = f"Reclaim and close above structural resistance at {target_res[0]:.2f}"
            alt_desc = f"Bullish short-squeeze driving price up toward supply around {target_res[0]:.2f}."

        else:
            prim_dir = "NEUTRAL"
            alt_dir = "BREAKOUT"
            prim_targets = [target_res[0], target_sup[0]]
            alt_targets = target_res
            inval = target_sup[0]

            prim_trigger = f"Oscillation between support ({target_sup[0]:.2f}) and resistance ({target_res[0]:.2f})"
            prim_desc = "Range-bound mean reversion within prevailing consolidation boundaries."
            alt_trigger = f"Clean impulse break out of range bounds [{target_sup[0]:.2f} - {target_res[0]:.2f}]"
            alt_desc = "Directional expansion upon structural range breakout."

        # Qualitative Confidence Label
        if aligned_count >= 5:
            confidence = "HIGH"
        elif aligned_count >= 3:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # Key evidence
        evidence = [
            f"Macro MTF Bias: {overall_bias} with {aligned_count} aligned timeframes",
            f"Daily Structure: {d1.get('trend', 'SIDEWAYS')} ({d1.get('bias', 'NEUTRAL')})",
            f"H1 Short-term Flow: {h1.get('bias', 'NEUTRAL')}",
        ]

        wait_conditions = [
            "Wait for active timeframe candle close to eliminate forming bar noise",
            f"Monitor price reaction within buffer of nearest structural level (${target_res[0]:.2f} / ${target_sup[0]:.2f})",
            "Verify volume expansion on entry timeframe before manual execution",
        ]

        return {
            "primary_scenario": {
                "direction": prim_dir,
                "description": prim_desc,
                "probability_label": confidence,
                "trigger": prim_trigger,
                "target_levels": prim_targets,
                "invalidation_level": round(inval, 2),
                "key_evidence": evidence,
            },
            "alternative_scenario": {
                "direction": alt_dir,
                "description": alt_desc,
                "probability_label": "LOW" if confidence == "HIGH" else "MEDIUM",
                "trigger": alt_trigger,
                "target_levels": alt_targets,
                "invalidation_level": round(current_price, 2),
                "key_evidence": ["Failure of primary scenario structural invalidation"],
            },
            "scenario_confidence": confidence,
            "wait_conditions": wait_conditions,
        }
