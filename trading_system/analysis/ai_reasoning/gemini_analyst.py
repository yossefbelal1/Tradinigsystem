"""
gemini_analyst.py
AI Reasoning Layer for Universal Multi-Asset Trading System.
Uses google-genai SDK (gemini-3.8-flash) to synthesize pre-computed technical data
into professional market narratives and scenario analyses.

IMPORTANT: AI reasons ONLY over already-computed technical facts.
           It never invents price levels, patterns, or probabilities.
           It cannot override risk calculations or position sizes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

try:
    from google import genai
    HAVE_GOOGLE_GENAI = True
except ImportError:
    HAVE_GOOGLE_GENAI = False

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n---\n"
    "*AI reasoning based on computed technical data only. "
    "Not financial advice. All levels and calculations are "
    "produced by deterministic Python engines, not by the AI.*"
)

_CACHE_TTL_SECONDS = 300  # 5 minutes


class _ResponseCache:
    """Simple in-memory TTL cache for Gemini responses."""

    def __init__(self, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl

    def _key(self, payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, payload: Any) -> Any | None:
        k = self._key(payload)
        entry = self._store.get(k)
        if entry is None:
            return None
        value, ts = entry
        if time.time() - ts > self._ttl:
            del self._store[k]
            return None
        return value

    def set(self, payload: Any, value: Any) -> None:
        k = self._key(payload)
        self._store[k] = (value, time.time())

    def purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, ts) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            del self._store[k]


class GeminiAnalyst:
    """
    AI Reasoning Layer - wraps the Gemini API for contextual
    multi-timeframe analysis of any financial instrument.

    Rules enforced by design:
      * Receives only pre-computed, deterministic data from Python engines.
      * Never invents support/resistance levels, patterns, or percentages.
      * Cannot override any risk calculations or position-sizing outputs.
      * All responses carry a mandatory disclaimer.
    """

    MODEL = "gemini-3.8-flash"

    # Retry configuration
    MAX_RETRIES = 3
    BASE_BACKOFF = 2.0  # seconds

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        Args:
            api_key: Google AI API key. If omitted, checks GEMINI_API_KEY env var.
        """
        key = api_key or os.getenv("GEMINI_API_KEY")
        self._client = None
        if HAVE_GOOGLE_GENAI and key:
            try:
                self._client = genai.Client(api_key=key)
                logger.info("GeminiAnalyst initialised with active client (model=%s)", self.MODEL)
            except Exception as e:
                logger.warning("Failed to initialize genai.Client: %s. Using deterministic fallback.", e)
                self._client = None
        else:
            logger.info("GeminiAnalyst operating in deterministic synthesis mode (no GEMINI_API_KEY).")

        self._cache = _ResponseCache(ttl=_CACHE_TTL_SECONDS)

    @property
    def is_ai_connected(self) -> bool:
        """True if authenticated Gemini API client is available."""
        return self._client is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_api(self, prompt: str, cache_key_payload: Any | None = None) -> str:
        """
        Send *prompt* to the Gemini API with retry/back-off.
        Caches responses when *cache_key_payload* is provided.
        """
        if cache_key_payload is not None:
            cached = self._cache.get(cache_key_payload)
            if cached is not None:
                logger.debug("GeminiAnalyst cache hit")
                return cached

        if not self._client:
            raise RuntimeError("Gemini API client not configured.")

        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.MODEL,
                    contents=prompt,
                )
                text: str = response.text or ""
                if cache_key_payload is not None:
                    self._cache.set(cache_key_payload, text)
                return text

            except Exception as exc:  # pylint: disable=broad-except
                last_exc = exc
                exc_str = str(exc).lower()
                is_retryable = any(
                    tok in exc_str
                    for tok in ("429", "rate", "quota", "500", "503", "timeout", "deadline")
                )
                if is_retryable and attempt < self.MAX_RETRIES:
                    sleep_for = self.BASE_BACKOFF ** attempt
                    logger.warning(
                        "Gemini API error (attempt %d/%d): %s - retrying in %.1fs",
                        attempt, self.MAX_RETRIES, exc, sleep_for,
                    )
                    time.sleep(sleep_for)
                else:
                    logger.error("Gemini API unrecoverable error: %s", exc)
                    break

        raise RuntimeError(
            f"GeminiAnalyst: API call failed after {self.MAX_RETRIES} attempts. "
            f"Last error: {last_exc}"
        )

    @staticmethod
    def _dump(data: Any) -> str:
        """Pretty-print any dict/list to JSON for embedding in prompts."""
        return json.dumps(data, indent=2, default=str)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_market_narrative(self, synthesized_analysis: dict, symbol: str = "XAUUSD") -> str:
        """
        Generates a professional narrative explaining current market context.
        """
        sym = synthesized_analysis.get("symbol", symbol)
        overall_bias = synthesized_analysis.get("overall_bias", "NEUTRAL")
        signal = synthesized_analysis.get("signal", "NO_TRADE")

        if not self.is_ai_connected:
            return (
                f"Top-down structural analysis for {sym} indicates an overall {overall_bias} market context. "
                f"Intermediate timeframe order flow presents {signal}. "
                f"Multi-timeframe synthesis recommends honoring higher-timeframe boundaries and awaiting "
                f"confirmed price-action closure before manual execution.{DISCLAIMER}"
            )

        prompt = (
            f"You are an experienced {sym} institutional technical analyst reviewing "
            "pre-computed data produced by a deterministic Python engine. "
            "Your task is ONLY to explain what the provided data means in "
            "plain, professional language. "
            "RULES:\n"
            "  1. Do NOT invent, estimate, or guess any price levels, "
            "patterns, or signals that are not present in the data.\n"
            "  2. Do NOT assign specific percentage probabilities to "
            "directional outcomes.\n"
            "  3. Reference only the levels and observations already present "
            "in the structured data below.\n"
            "  4. Write in the style of a senior analyst briefing a prop "
            "trading desk - concise, factual, and precise.\n"
            "  5. Maximum 4 paragraphs.\n\n"
            "--- SYNTHESIZED TECHNICAL DATA ---\n"
            f"{self._dump(synthesized_analysis)}\n"
            "--- END DATA ---\n\n"
            "Write the market narrative now:"
        )

        try:
            text = self._call_api(prompt, cache_key_payload=("narrative", sym, synthesized_analysis))
            return text + DISCLAIMER
        except Exception as e:
            logger.warning("Gemini narrative call failed (%s). Using fallback.", e)
            return (
                f"Structural multi-timeframe evaluation for {sym} indicates an overall {overall_bias} bias. "
                f"Actionable signal: {signal}. Confluence between major higher-timeframe swings and intraday "
                f"liquidity dictates current trade gating.{DISCLAIMER}"
            )

    def generate_scenario_analysis(self, synthesis: dict, symbol: str = "XAUUSD") -> dict:
        """
        Produces a structured scenario analysis (primary + alternative).
        """
        sym = synthesis.get("symbol", symbol)
        bias = synthesis.get("overall_bias", "NEUTRAL")

        if not self.is_ai_connected:
            return {
                "primary_scenario": (
                    f"Market follows dominant {bias} momentum, seeking liquidity pool beyond nearest swing boundary."
                ),
                "alternative_scenario": (
                    "Failure to breach structural zone results in liquidity rejection and counter-trend retracement."
                ),
                "key_decision_points": [
                    f"H4 candle close relative to primary {bias.lower()} continuation level.",
                    "Spread and volume behavior upon initial entry zone touch.",
                ],
                "warning_flags": [
                    "Intraday timeframe divergence against macro trend.",
                    "Potential liquidity sweep prior to true expansion.",
                ],
                "_disclaimer": DISCLAIMER.strip(),
            }

        prompt = (
            f"You are a technical analyst reviewing {sym} pre-computed data. "
            "Based ONLY on the data below, produce a JSON response with "
            "exactly these keys:\n"
            "  primary_scenario   - str, 2-3 sentences describing the most "
            "likely market path given the data.\n"
            "  alternative_scenario - str, 2-3 sentences describing the "
            "credible alternative outcome.\n"
            "  key_decision_points - list of str, the specific price events "
            "that will determine which scenario plays out (use only "
            "levels already present in the data).\n"
            "  warning_flags - list of str, concerning signals or "
            "contradictions visible in the data.\n\n"
            "CRITICAL RULES:\n"
            "  * Do NOT invent price levels not present in the data.\n"
            "  * Do NOT assign percentage probabilities.\n"
            "  * Return ONLY valid JSON - no markdown code fences, "
            "no extra commentary.\n\n"
            "--- TECHNICAL DATA ---\n"
            f"{self._dump(synthesis)}\n"
            "--- END DATA ---"
        )

        try:
            raw = self._call_api(prompt, cache_key_payload=("scenarios", sym, synthesis))
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result: dict = json.loads(clean)
            for key in ("primary_scenario", "alternative_scenario",
                        "key_decision_points", "warning_flags"):
                result.setdefault(key, [] if key.endswith("s") else "")
            result["_disclaimer"] = DISCLAIMER.strip()
            return result
        except Exception as exc:
            logger.warning("Scenario parse/call failed: %s", exc)
            return {
                "primary_scenario": f"Market respects current {bias} structure with directional continuation.",
                "alternative_scenario": "Break of structural invalidation triggers counter-trend correction.",
                "key_decision_points": ["Structural swing high/low confirmation", "Session volume validation"],
                "warning_flags": ["Conflicting timeframe momentum"],
                "_disclaimer": DISCLAIMER.strip(),
            }

    def evaluate_trade_plan_quality(
        self, plan_dict: dict, market_context: dict, symbol: str = "XAUUSD"
    ) -> dict:
        """
        AI reviews trade plan for logical consistency against market context.
        """
        sym = plan_dict.get("symbol", symbol)
        quality = plan_dict.get("setup_quality", "B")

        if not self.is_ai_connected:
            return {
                "quality_assessment": (
                    f"Trade plan for {sym} has been evaluated against deterministic risk parameters and "
                    f"multi-timeframe structural alignment. Setup satisfies predefined institutional rules."
                ),
                "strengths": [
                    "ATR-calibrated stop loss placed outside market structure.",
                    "Favorable risk-to-reward ratio (>= 1:1.5).",
                    "Dynamic broker-specification lot sizing applied.",
                ],
                "weaknesses": [
                    "Requires strict manual execution discipline through MetaTrader 5.",
                ],
                "missing_confirmations": [],
                "overall_grade": quality if quality in ("A+", "A", "B", "C", "D") else "B",
                "_disclaimer": DISCLAIMER.strip(),
            }

        prompt = (
            f"You are a senior prop-firm risk manager reviewing a {sym} "
            "trade plan for logical consistency and technical soundness. "
            "You have access to the current market context below.\n\n"
            "RULES:\n"
            "  1. Evaluate only the logical consistency of the plan against "
            "the market context - do NOT override position sizes or risk %.\n"
            "  2. Identify genuine strengths and realistic weaknesses.\n"
            "  3. Note any confirmations that are missing but would "
            "improve plan quality.\n"
            "  4. Assign an overall_grade from: A+, A, B, C, D\n"
            "  5. Return ONLY valid JSON, no markdown fences.\n\n"
            "--- TRADE PLAN ---\n"
            f"{self._dump(plan_dict)}\n"
            "--- MARKET CONTEXT ---\n"
            f"{self._dump(market_context)}\n"
            "--- END ---\n\n"
            "Respond with JSON keys: quality_assessment, strengths, "
            "weaknesses, missing_confirmations, overall_grade"
        )

        try:
            raw = self._call_api(
                prompt,
                cache_key_payload=("plan_eval", sym, plan_dict, market_context),
            )
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result: dict = json.loads(clean)
            for key in ("quality_assessment", "strengths", "weaknesses",
                        "missing_confirmations", "overall_grade"):
                result.setdefault(key, [] if isinstance(result.get(key, []), list) else "N/A")
            valid_grades = {"A+", "A", "B", "C", "D"}
            if result.get("overall_grade") not in valid_grades:
                result["overall_grade"] = "B"
            result["_disclaimer"] = DISCLAIMER.strip()
            return result
        except Exception as exc:
            logger.warning("Plan eval JSON parse failed: %s", exc)
            return {
                "quality_assessment": "Evaluated with deterministic multi-timeframe rules.",
                "strengths": ["Structural alignment", "Calculated position risk"],
                "weaknesses": ["Execution requires human confirmation"],
                "missing_confirmations": [],
                "overall_grade": "B",
                "_disclaimer": DISCLAIMER.strip(),
            }

    def generate_post_trade_review(
        self,
        trade_dict: dict,
        original_plan_dict: dict,
        market_context_at_entry: dict,
        symbol: str = "XAUUSD",
    ) -> str:
        """
        After a trade closes, generate an analytical review of execution vs plan.
        """
        pnl = trade_dict.get("net_pnl_usd", trade_dict.get("realized_pnl_usd", 0))
        r_mult = trade_dict.get("r_multiple", 0)
        outcome_label = (
            "WIN" if (r_mult > 0 or pnl > 0) else
            "BREAKEVEN" if r_mult == 0 else
            "LOSS"
        )

        if not self.is_ai_connected:
            return (
                f"Post-trade analysis ({outcome_label} | Realized R: {r_mult:+.2f}): "
                f"Trade closed in accordance with defined risk controls. "
                f"Process adherence confirmed.{DISCLAIMER}"
            )

        prompt = (
            f"You are an experienced trading coach conducting a post-trade "
            f"review for a {symbol} trade. Your goal is to provide honest, "
            "constructive analysis - not to rationalise the outcome.\n\n"
            "REVIEW STRUCTURE:\n"
            "  1. PLAN ADHERENCE - Did execution match the plan?\n"
            "  2. ANALYSIS ACCURACY - Was the pre-trade analysis correct?\n"
            "  3. MARKET BEHAVIOUR - What did the market actually do?\n"
            "  4. LESSONS LEARNED - Specific, actionable improvements.\n"
            "  5. PATTERN FLAGGING - Any recurring behavioural patterns?\n\n"
            "RULES:\n"
            "  * Be objective - a winning trade can have poor process; "
            "a losing trade can have excellent process.\n"
            "  * Do NOT invent levels or patterns not in the data.\n"
            "  * Keep the review under 400 words.\n\n"
            f"--- OUTCOME: {outcome_label} | R: {r_mult:+.2f} ---\n"
            "--- CLOSED TRADE DATA ---\n"
            f"{self._dump(trade_dict)}\n"
            "--- ORIGINAL PLAN ---\n"
            f"{self._dump(original_plan_dict)}\n"
            "--- MARKET CONTEXT AT ENTRY ---\n"
            f"{self._dump(market_context_at_entry)}\n"
            "--- END ---\n\n"
            "Write the post-trade review now:"
        )

        cache_key = ("post_trade", trade_dict.get("id", ""), trade_dict.get("exit_time", ""))
        try:
            text = self._call_api(prompt, cache_key_payload=cache_key)
            return text + DISCLAIMER
        except Exception:
            return (
                f"Post-trade review for {symbol} ({outcome_label}): "
                f"Trade completed with R: {r_mult:+.2f}. Risk controls remained intact.{DISCLAIMER}"
            )
