"""
core/mtf/conflict_detector.py
=============================
Multi-Timeframe Conflict Detection Engine.
Identifies directional discrepancies across the timeframe hierarchy.
Crucially interprets conflicts contextually (e.g., a lower-timeframe bearish divergence
at major weekly resistance represents a healthy pullback/retracement, not a software bug).
"""

from __future__ import annotations

import logging
from typing import Any

from trading_system.config.settings import Bias, TIMEFRAME_HIERARCHY

logger = logging.getLogger(__name__)


class ConflictDetector:
    """
    Evaluates cross-timeframe alignment and detects structural conflicts.
    """

    def detect_conflicts(
        self,
        timeframe_analyses: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Inspect adjacent and macro-to-micro timeframe pairs to flag directional tensions.
        """
        conflicts: list[dict[str, Any]] = []
        ordered_tfs = [tf for tf in TIMEFRAME_HIERARCHY if tf in timeframe_analyses]

        for i in range(len(ordered_tfs) - 1):
            htf = ordered_tfs[i]
            ltf = ordered_tfs[i + 1]

            h_data = timeframe_analyses[htf]
            l_data = timeframe_analyses[ltf]

            h_bias = h_data.get("bias", Bias.NEUTRAL.value)
            l_bias = l_data.get("bias", Bias.NEUTRAL.value)

            # Skip if either is neutral or both are identical
            if h_bias == Bias.NEUTRAL.value or l_bias == Bias.NEUTRAL.value or h_bias == l_bias:
                continue

            # Directional opposition detected!
            severity, c_type, interp = self._assess_conflict(htf, ltf, h_data, l_data)

            conflicts.append({
                "higher_tf": htf,
                "lower_tf": ltf,
                "higher_bias": h_bias,
                "lower_bias": l_bias,
                "conflict_type": c_type,
                "severity": severity,
                "interpretation": interp,
            })

        return conflicts

    def is_tradeable_despite_conflict(
        self,
        conflicts: list[dict[str, Any]],
        execution_tf: str = "M15",
    ) -> tuple[bool, str]:
        """
        Determine whether an opportunity can still be executed responsibly
        in light of the detected cross-timeframe conflicts.
        """
        high_severity = [c for c in conflicts if c.get("severity") == "HIGH"]

        if high_severity:
            reasons = [f"{c['higher_tf']}/{c['lower_tf']}: {c['interpretation']}" for c in high_severity]
            return False, f"Trading blocked due to severe multi-timeframe conflict: {'; '.join(reasons)}"

        medium_conflicts = [c for c in conflicts if c.get("severity") == "MEDIUM"]
        if len(medium_conflicts) >= 2:
            return False, "Multiple intermediate timeframe conflicts present. Market is consolidating or reversing."

        if medium_conflicts:
            c = medium_conflicts[0]
            return True, f"Tradeable with caution: {c['interpretation']}. Requires tight invalidation and reduced risk."

        return True, "Multi-timeframe hierarchy is clean and aligned."

    def _assess_conflict(
        self,
        htf: str,
        ltf: str,
        h_data: dict[str, Any],
        l_data: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Assess conflict severity, type, and clinical market interpretation."""
        h_bias = h_data.get("bias", "")
        l_bias = l_data.get("bias", "")
        curr_price = float(l_data.get("current_price", 0.0))

        # Check if LTF is reversing at a major HTF key level
        near_res = h_data.get("nearest_resistance", [])
        near_sup = h_data.get("nearest_support", [])

        at_htf_res = near_res and abs(curr_price - near_res[0]["price"]) <= h_data.get("atr", 10.0) * 0.8
        at_htf_sup = near_sup and abs(curr_price - near_sup[0]["price"]) <= h_data.get("atr", 10.0) * 0.8

        # 1. Macro Conflict (Monthly / Weekly / Daily)
        if htf in ("MN1", "W1") and ltf in ("W1", "D1"):
            if (h_bias == "BULLISH" and at_htf_res and l_bias == "BEARISH") or \
               (h_bias == "BEARISH" and at_htf_sup and l_bias == "BULLISH"):
                return (
                    "HIGH",
                    "MAJOR_REVERSAL_REACTION",
                    f"{htf} is {h_bias}, but {ltf} shows strong counter-reaction at major {htf} technical boundary. "
                    f"Expect significant multi-day correction or potential macro trend reversal."
                )
            return (
                "MEDIUM",
                "INTERMEDIATE_PULLBACK",
                f"{ltf} is undergoing a corrective retracement ({l_bias}) against the dominant {htf} {h_bias} market structure."
            )

        # 2. Daily vs Intraday (D1 vs H4 / H1)
        if htf == "D1":
            if (h_bias == "BULLISH" and at_htf_res and l_bias == "BEARISH") or \
               (h_bias == "BEARISH" and at_htf_sup and l_bias == "BULLISH"):
                return (
                    "MEDIUM",
                    "PULLBACK_AT_KEY_LEVEL",
                    f"{ltf} is rejecting key Daily structural area. Do not force {h_bias} trades until reaction resolves."
                )
            return (
                "LOW",
                "INTRADAY_CONSOLIDATION",
                f"{ltf} is briefly opposing Daily {h_bias} momentum. Likely normal intraday liquidity seeking."
            )

        # 3. Lower timeframe minor conflict
        return (
            "LOW",
            "LOCAL_MICRO_NOISE",
            f"Minor disagreement between {htf} and {ltf}. Normal intraday order flow oscillation."
        )
