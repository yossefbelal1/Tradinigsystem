"""
core/mtf/bias_synthesizer.py
============================
Multi-Timeframe Bias Synthesizer & Decision Coordinator.
Integrates top-down technical observations from Monthly down to M15 using a mathematically
weighted hierarchical framework. Emits transparent, disciplined trading decisions:
BUY_OPPORTUNITY, SELL_OPPORTUNITY, WAIT_FOR_CONFIRMATION, NO_TRADE, or HIGHER_TIMEFRAME_CONFLICT.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from trading_system.config.settings import (
    Bias,
    SetupQuality,
    Signal,
    TIMEFRAME_HIERARCHY,
    TIMEFRAME_WEIGHTS,
)

logger = logging.getLogger(__name__)


class BiasSynthesizer:
    """
    Synthesizes the complete multi-timeframe hierarchy into an actionable directional thesis.
    Enforces that higher timeframes set the directional context and lower timeframes
    serve exclusively to refine and confirm timing.
    """

    def synthesize(
        self,
        timeframe_analyses: dict[str, dict[str, Any]],
        conflicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Synthesize multi-timeframe analyses and conflicts into a final analytical signal and plan.
        """
        if not timeframe_analyses:
            return self._empty_synthesis()

        # ── 1. Calculate Weighted Bias Score ─────────────────────────────────
        total_weight = 0.0
        weighted_score = 0.0  # +1 for BULLISH, -1 for BEARISH, 0 for NEUTRAL

        for tf, data in timeframe_analyses.items():
            w = TIMEFRAME_WEIGHTS.get(tf, 1.0)
            b = data.get("bias", Bias.NEUTRAL.value)
            total_weight += w

            if b == Bias.BULLISH.value:
                weighted_score += w * 1.0
            elif b == Bias.BEARISH.value:
                weighted_score += w * (-1.0)

        normalized_score = weighted_score / max(total_weight, 1.0)  # -1.0 to +1.0
        bias_strength = round(abs(normalized_score), 2)

        if normalized_score >= 0.35:
            overall_bias = Bias.BULLISH.value
        elif normalized_score <= -0.35:
            overall_bias = Bias.BEARISH.value
        else:
            overall_bias = Bias.NEUTRAL.value

        # Identify dominant timeframe driving the market
        d1_data = timeframe_analyses.get("D1", {})
        w1_data = timeframe_analyses.get("W1", {})
        mn1_data = timeframe_analyses.get("MN1", {})

        dominant_tf = "D1"
        if w1_data.get("trend_strength", 0) > 0.7:
            dominant_tf = "W1"
        elif mn1_data.get("trend_strength", 0) > 0.8:
            dominant_tf = "MN1"

        # ── 2. Check for Severe Conflicts ────────────────────────────────────
        high_severity_conflicts = [c for c in conflicts if c.get("severity") == "HIGH"]

        # ── 3. Evaluate Setup & Intraday Execution Timing ────────────────────
        h4_data = timeframe_analyses.get("H4", {})
        h1_data = timeframe_analyses.get("H1", {})
        m15_data = timeframe_analyses.get("M15", {})

        # Count aligned timeframes with overall bias
        aligned_count = sum(
            1 for tf, d in timeframe_analyses.items()
            if d.get("bias") == overall_bias and overall_bias != Bias.NEUTRAL.value
        )

        # Look for execution patterns on lower timeframes
        m15_patterns = m15_data.get("recent_patterns", [])
        h1_patterns = h1_data.get("recent_patterns", [])

        has_entry_trigger = False
        entry_pattern_desc = ""
        best_entry_tf = "M15"

        for p in m15_patterns + h1_patterns:
            p_dir = p.get("signal_direction", "")
            if p.get("trade_worthy", False) and p_dir == overall_bias:
                has_entry_trigger = True
                entry_pattern_desc = p.get("pattern_type", "Price Action Trigger")
                best_entry_tf = p.get("timeframe", "M15")
                break

        # ── 4. Formulate Signal & Quality Grade ──────────────────────────────
        signal = Signal.NO_TRADE.value
        reasoning = ""
        quality = SetupQuality.C.value

        if high_severity_conflicts:
            signal = Signal.HIGHER_TIMEFRAME_CONFLICT.value
            conflict_msgs = [c["interpretation"] for c in high_severity_conflicts]
            reasoning = f"Conflicting structural bias: {'; '.join(conflict_msgs)}"
            quality = SetupQuality.D.value

        elif overall_bias == Bias.NEUTRAL.value:
            signal = Signal.NO_TRADE.value
            reasoning = "Market is in range-bound consolidation across primary timeframes with no directional edge."
            quality = SetupQuality.D.value

        elif aligned_count >= 3:
            if has_entry_trigger:
                signal = Signal.BUY_OPPORTUNITY.value if overall_bias == Bias.BULLISH.value else Signal.SELL_OPPORTUNITY.value
                reasoning = (
                    f"Aligned {overall_bias} structure across {aligned_count} timeframes. "
                    f"Confirmed entry trigger on {best_entry_tf}: {entry_pattern_desc}."
                )
                quality = SetupQuality.A_PLUS.value if aligned_count >= 5 else SetupQuality.A.value
            else:
                signal = Signal.WAIT_FOR_CONFIRMATION.value
                reasoning = (
                    f"Macro bias is {overall_bias} ({aligned_count} timeframes aligned), "
                    f"but intraday execution trigger ({best_entry_tf}) has not completed confirmation."
                )
                quality = SetupQuality.B.value

        else:
            signal = Signal.WAIT_FOR_CONFIRMATION.value
            reasoning = f"Developing {overall_bias} bias ({aligned_count} aligned), awaiting daily structural alignment."
            quality = SetupQuality.C.value

        # ── 5. Generate Market Narrative ─────────────────────────────────────
        narrative = self._build_narrative(
            overall_bias=overall_bias,
            bias_strength=bias_strength,
            dominant_tf=dominant_tf,
            aligned_count=aligned_count,
            timeframe_analyses=timeframe_analyses,
            signal=signal,
            reasoning=reasoning,
        )

        return {
            "overall_bias": overall_bias,
            "bias_strength": bias_strength,
            "normalized_score": round(normalized_score, 3),
            "dominant_timeframe": dominant_tf,
            "aligned_timeframes_count": aligned_count,
            "signal": signal,
            "signal_reasoning": reasoning,
            "setup_quality": quality,
            "entry_timeframe": best_entry_tf if has_entry_trigger else "M15",
            "has_entry_trigger": has_entry_trigger,
            "entry_pattern": entry_pattern_desc,
            "conflicts": conflicts,
            "narrative": narrative,
        }

    def _build_narrative(
        self,
        overall_bias: str,
        bias_strength: float,
        dominant_tf: str,
        aligned_count: int,
        timeframe_analyses: dict[str, dict[str, Any]],
        signal: str,
        reasoning: str,
    ) -> str:
        """Create a professional multi-timeframe analytical narrative."""
        mn1 = timeframe_analyses.get("MN1", {}).get("bias", "NEUTRAL")
        w1 = timeframe_analyses.get("W1", {}).get("bias", "NEUTRAL")
        d1 = timeframe_analyses.get("D1", {}).get("bias", "NEUTRAL")
        h4 = timeframe_analyses.get("H4", {}).get("bias", "NEUTRAL")
        h1 = timeframe_analyses.get("H1", {}).get("bias", "NEUTRAL")

        lines = [
            f"**Multi-Timeframe Market Narrative:**",
            f"- Macro Context (MN1: {mn1}, W1: {w1}): Dominant driver is {dominant_tf} with structural bias leaning {overall_bias} (Strength: {bias_strength * 100:.0f}%).",
            f"- Intermediate Structure (D1: {d1}, H4: {h4}): Setup identification indicates {d1} momentum aligning with the broader thesis.",
            f"- Execution Alignment: {aligned_count} of 7 timeframes currently support {overall_bias}.",
            f"- **System Recommendation:** {signal} ({reasoning})",
        ]
        return "\n".join(lines)

    def _empty_synthesis(self) -> dict[str, Any]:
        return {
            "overall_bias": Bias.NEUTRAL.value,
            "bias_strength": 0.0,
            "normalized_score": 0.0,
            "dominant_timeframe": "D1",
            "aligned_timeframes_count": 0,
            "signal": Signal.NO_TRADE.value,
            "signal_reasoning": "No timeframe analyses provided.",
            "setup_quality": SetupQuality.D.value,
            "entry_timeframe": "M15",
            "has_entry_trigger": False,
            "entry_pattern": "",
            "conflicts": [],
            "narrative": "Awaiting market data synchronization.",
        }
