"""
core/price_action/context_scorer.py
===================================
Contextual Price Action Scoring Engine.
CRITICAL PRINCIPLE: Never evaluate a candlestick pattern in isolation.
A pin bar or engulfing candle at major S/R with trend alignment has institutional
edge; the identical pattern in the middle of a consolidation is random noise.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.config.settings import SetupQuality

logger = logging.getLogger(__name__)


class ContextScorer:
    """
    Evaluates price action patterns within their holistic technical context:
    Structural location, Higher-Timeframe alignment, S/R confluence,
    Supply/Demand freshness, and volume behavior.
    """

    def score_pattern(
        self,
        pattern: dict[str, Any],
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Produce a comprehensive context-graded score for a detected pattern.
        """
        enriched = dict(pattern)
        direction = pattern.get("signal_direction", "NEUTRAL").upper()
        pat_price = float(pattern.get("close", pattern.get("price", 0.0)))
        atr = float(market_context.get("atr", 5.0))
        trend = market_context.get("trend", "SIDEWAYS").upper()
        htf_bias = market_context.get("higher_tf_bias", "NEUTRAL").upper()
        sr_levels = market_context.get("sr_levels", [])
        zones = market_context.get("supply_demand_zones", [])

        # ── 1. Location Score (0 - 100) ──────────────────────────────────────
        is_at_key, location_desc = self.is_pattern_at_key_level(pattern, sr_levels, zones, atr)
        if is_at_key:
            # Check if at major S/R or fresh zone
            if "MAJOR" in location_desc or "FRESH" in location_desc:
                location_score = 90.0
            else:
                location_score = 70.0
        else:
            location_score = 25.0  # In no-man's land

        # ── 2. Alignment Score (0 - 100) ────────────────────────────────────
        alignment_score = 50.0  # default neutral
        if direction in ("BULLISH", "BUY"):
            if htf_bias == "BULLISH":
                alignment_score += 30.0
            elif htf_bias == "BEARISH":
                alignment_score -= 30.0

            if trend == "BULLISH":
                alignment_score += 20.0
            elif trend == "BEARISH":
                alignment_score -= 20.0

        elif direction in ("BEARISH", "SELL"):
            if htf_bias == "BEARISH":
                alignment_score += 30.0
            elif htf_bias == "BULLISH":
                alignment_score -= 30.0

            if trend == "BEARISH":
                alignment_score += 20.0
            elif trend == "BULLISH":
                alignment_score -= 20.0

        alignment_score = float(np.clip(alignment_score, 0.0, 100.0))

        # ── 3. Confluence Score (0 - 100) ───────────────────────────────────
        confluence_score = 20.0
        reasons = []

        if is_at_key:
            confluence_score += 35.0
            reasons.append(location_desc)

        # Volume confirmation
        vol_info = market_context.get("volume_analysis", {})
        if vol_info.get("breakout_volume_confirmed", False) or vol_info.get("relative_volume", 1.0) >= 1.3:
            confluence_score += 25.0
            reasons.append("Above-average volume confirmation")

        # Momentum sequence context
        seq_info = market_context.get("candle_sequence", {})
        if seq_info.get("is_exhausting", False):
            if (direction == "BULLISH" and seq_info.get("momentum_direction") == "BEARISH") or \
               (direction == "BEARISH" and seq_info.get("momentum_direction") == "BULLISH"):
                confluence_score += 20.0
                reasons.append(f"Counters exhausted {seq_info.get('momentum_direction')} momentum run")

        confluence_score = float(np.clip(confluence_score, 0.0, 100.0))

        # ── 4. Overall Weighted Score ───────────────────────────────────────
        overall = (location_score * 0.40) + (alignment_score * 0.35) + (confluence_score * 0.25)
        overall = round(float(np.clip(overall, 0.0, 100.0)), 1)

        # ── 5. Quality Grade ────────────────────────────────────────────────
        if overall >= 85.0:
            quality = SetupQuality.A_PLUS.value
        elif overall >= 70.0:
            quality = SetupQuality.A.value
        elif overall >= 55.0:
            quality = SetupQuality.B.value
        elif overall >= 40.0:
            quality = SetupQuality.C.value
        else:
            quality = SetupQuality.D.value

        # Explanation narrative
        pat_name = pattern.get("pattern_type", "Price Action Pattern")
        explanation = (
            f"{pat_name} [{direction}] at {pat_price:.2f}. "
            f"Location: {location_desc} (Score: {location_score:.0f}). "
            f"HTF Bias: {htf_bias}, Trend: {trend} (Alignment: {alignment_score:.0f}). "
            f"Confluence factors: {', '.join(reasons) if reasons else 'Limited confluence'}."
        )

        trade_worthy = overall >= 60.0 and pattern.get("is_confirmed", True)

        enriched.update({
            "location_score": location_score,
            "alignment_score": alignment_score,
            "confluence_score": confluence_score,
            "overall_score": overall,
            "quality_label": quality,
            "context_explanation": explanation,
            "trade_worthy": trade_worthy,
        })
        return enriched

    def evaluate_candle_sequence(
        self,
        df: pd.DataFrame,
        lookback: int = 5,
    ) -> dict[str, Any]:
        """
        Evaluate recent candle momentum flow, streak counts, and exhaustion.
        """
        if df.empty or len(df) < lookback:
            return {
                "momentum_direction": "NEUTRAL",
                "momentum_strength": 0.0,
                "consecutive_count": 0,
                "is_exhausting": False,
            }

        recent = df.iloc[-lookback:]
        bull_count = sum(recent["close"] > recent["open"])
        bear_count = sum(recent["close"] < recent["open"])

        # Determine streak
        closes = recent["close"].values
        opens = recent["open"].values
        bodies = np.abs(closes - opens)

        if bull_count >= 4:
            direction = "BULLISH"
            consec = bull_count
        elif bear_count >= 4:
            direction = "BEARISH"
            consec = bear_count
        else:
            direction = "MIXED"
            consec = 1

        # Check for exhaustion: bodies shrinking or last candle has huge wick opposing streak
        is_exhausting = False
        if len(bodies) >= 3 and bodies[-1] < bodies[-2] * 0.6 and bodies[-2] < bodies[-3]:
            is_exhausting = True

        return {
            "momentum_direction": direction,
            "momentum_strength": round(max(bull_count, bear_count) / lookback, 2),
            "consecutive_count": consec,
            "is_exhausting": is_exhausting,
        }

    def is_pattern_at_key_level(
        self,
        pattern: dict[str, Any],
        sr_levels: list[dict[str, Any]],
        zones: list[dict[str, Any]],
        atr: float,
    ) -> tuple[bool, str]:
        """
        Verify whether the pattern formed at or immediately adjacent to a key structural area.
        """
        price = float(pattern.get("close", pattern.get("high", pattern.get("low", 0.0))))
        tolerance = atr * 0.40

        # Check Supply/Demand zones first
        for z in zones:
            top = z["top"]
            bottom = z["bottom"]
            z_type = z["type"]
            state = z.get("state", "FRESH")

            if (bottom - tolerance) <= price <= (top + tolerance):
                return True, f"Inside {state} {z_type} Zone [{bottom:.2f} - {top:.2f}]"

        # Check Classical S/R levels
        for sr in sr_levels:
            sr_p = sr["price"]
            if abs(price - sr_p) <= tolerance:
                major_flag = "MAJOR " if sr.get("is_major", False) else ""
                sr_type = sr.get("type", "S/R")
                return True, f"At {major_flag}{sr_type} level {sr_p:.2f}"

        return False, "Not at recognized key level"
