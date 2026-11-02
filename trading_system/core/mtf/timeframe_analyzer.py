"""
core/mtf/timeframe_analyzer.py
==============================
Single-Timeframe Technical Analysis Coordinator.
Executes complete technical analysis (Market Structure, S/R, Supply/Demand,
Price Action, Volume) on any single timeframe DataFrame.
Never confuses an incomplete forming candle with a confirmed closed candle.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from trading_system.config.settings import Bias, CandleStatus
from trading_system.core.classical_ta.support_resistance import SupportResistanceDetector
from trading_system.core.classical_ta.trendlines import TrendlineDetector
from trading_system.core.classical_ta.volume_analyzer import VolumeAnalyzer
from trading_system.core.market_structure.structure_break import StructureBreakDetector
from trading_system.core.market_structure.swing_detector import SwingDetector
from trading_system.core.market_structure.trend_analyzer import TrendAnalyzer
from trading_system.core.price_action.context_scorer import ContextScorer
from trading_system.core.price_action.pattern_detector import PatternDetector
from trading_system.core.supply_demand.zone_detector import SupplyDemandDetector
from trading_system.core.supply_demand.zone_validator import ZoneValidator

logger = logging.getLogger(__name__)


class TimeframeAnalyzer:
    """
    Coordinates and synthesizes all deterministic technical analysis engines
    for a specific timeframe.
    """

    def __init__(self):
        self.swing_detector = SwingDetector()
        self.trend_analyzer = TrendAnalyzer(self.swing_detector)
        self.structure_break = StructureBreakDetector(self.swing_detector)
        self.sr_detector = SupportResistanceDetector(self.swing_detector)
        self.trendline_detector = TrendlineDetector(self.swing_detector)
        self.sd_detector = SupplyDemandDetector()
        self.zone_validator = ZoneValidator()
        self.pattern_detector = PatternDetector()
        self.context_scorer = ContextScorer()
        self.volume_analyzer = VolumeAnalyzer()

    def analyze(
        self,
        timeframe: str,
        df: pd.DataFrame,
        is_current_candle_forming: Optional[bool] = None,
        higher_tf_bias: str = "NEUTRAL",
    ) -> dict[str, Any]:
        """
        Run complete technical analysis on the provided timeframe DataFrame.
        """
        if df.empty or len(df) < 15:
            logger.warning("Insufficient data to analyze timeframe %s (%d rows)", timeframe, len(df))
            return self._empty_analysis(timeframe)

        # Confirm forming status
        if is_current_candle_forming is not None:
            is_forming = is_current_candle_forming
        elif "is_confirmed" in df.columns:
            is_forming = not bool(df["is_confirmed"].iloc[-1])
        else:
            is_forming = False

        status_str = CandleStatus.FORMING.value if is_forming else CandleStatus.CONFIRMED.value
        current_price = float(df["close"].iloc[-1])
        atr = self._calculate_atr(df)

        # 1. Market Structure & Trend
        trend_info = self.trend_analyzer.identify_trend(df)
        swings = self.swing_detector.get_significant_swings(df, n=8)
        trend_dir = trend_info.get("primary_trend", "SIDEWAYS")
        trend_strength = trend_info.get("strength", 0.5)

        # 2. Support & Resistance Levels
        sr_levels = self.sr_detector.detect_levels(df, lookback=min(200, len(df)))
        nearest_sr = self.sr_detector.get_nearest_levels(sr_levels, current_price, n_above=2, n_below=2)

        # 3. Trendlines
        trendlines = self.trendline_detector.detect_trendlines(df)

        # 4. Supply & Demand Zones
        raw_zones = self.sd_detector.detect_zones(df, atr=atr)
        updated_zones = self.zone_validator.update_zone_states(raw_zones, df, current_price)
        valid_zones = self.zone_validator.filter_valid_zones(updated_zones, current_price, min_score=40.0, sr_levels=sr_levels)

        supply_zones = [z for z in valid_zones if z["type"] == "SUPPLY"]
        demand_zones = [z for z in valid_zones if z["type"] == "DEMAND"]

        # 5. Volume Analysis
        vol_info = self.volume_analyzer.analyze(df)

        # 6. Price Action Patterns (last 5 candles)
        market_ctx = {
            "atr": atr,
            "trend": trend_dir,
            "higher_tf_bias": higher_tf_bias,
            "sr_levels": sr_levels,
            "supply_demand_zones": valid_zones,
            "volume_analysis": vol_info,
            "candle_sequence": self.context_scorer.evaluate_candle_sequence(df, lookback=5),
        }

        raw_patterns = self.pattern_detector.detect_all(df, atr=atr, sr_levels=sr_levels, lookback=5)
        scored_patterns = [self.context_scorer.score_pattern(p, market_ctx) for p in raw_patterns]

        # Filter to trade worthy or recent significant patterns
        trade_worthy_patterns = [p for p in scored_patterns if p.get("overall_score", 0) >= 55.0]

        # 7. Directional Bias & Scenarios
        bias, reasoning = self._derive_bias(
            trend_dir=trend_dir,
            current_price=current_price,
            nearest_sr=nearest_sr,
            supply_zones=supply_zones,
            demand_zones=demand_zones,
            patterns=trade_worthy_patterns,
            atr=atr,
        )

        invalidation_level = self._compute_invalidation_level(
            bias=bias,
            current_price=current_price,
            nearest_sr=nearest_sr,
            swings=swings,
            atr=atr,
        )

        next_candle, bull_scen, bear_scen = self._generate_scenarios(
            timeframe=timeframe,
            bias=bias,
            current_price=current_price,
            nearest_sr=nearest_sr,
            patterns=trade_worthy_patterns,
            is_forming=is_forming,
            atr=atr,
        )

        prec = 5 if current_price < 5.0 else (3 if current_price < 250.0 else 2)

        return {
            "timeframe": timeframe,
            "candle_count": len(df),
            "current_candle_status": status_str,
            "is_forming": is_forming,
            "current_price": round(current_price, prec),
            "atr": round(atr, prec),
            "market_structure": trend_info,
            "trend": trend_dir,
            "trend_strength": trend_strength,
            "swings": swings,
            "sr_levels": sr_levels,
            "nearest_resistance": nearest_sr.get("resistance", []),
            "nearest_support": nearest_sr.get("support", []),
            "trendlines": trendlines,
            "supply_zones": supply_zones[:3],
            "demand_zones": demand_zones[:3],
            "recent_patterns": trade_worthy_patterns[:5],
            "volume_analysis": vol_info,
            "bias": bias,
            "bias_reasoning": reasoning,
            "invalidation_level": round(invalidation_level, prec) if invalidation_level else None,
            "next_candle_expectation": next_candle,
            "bullish_scenario": bull_scen,
            "bearish_scenario": bear_scen,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private Derivations
    # ─────────────────────────────────────────────────────────────────────────

    def _derive_bias(
        self,
        trend_dir: str,
        current_price: float,
        nearest_sr: dict[str, list[dict[str, Any]]],
        supply_zones: list[dict[str, Any]],
        demand_zones: list[dict[str, Any]],
        patterns: list[dict[str, Any]],
        atr: float,
    ) -> tuple[str, str]:
        """
        Derive local directional bias combining market structure, zones, and patterns.
        """
        bull_points = 0
        bear_points = 0
        reasons = []

        if trend_dir == "BULLISH":
            bull_points += 3
            reasons.append("Higher swing highs & higher lows")
        elif trend_dir == "BEARISH":
            bear_points += 3
            reasons.append("Lower swing highs & lower lows")

        # Proximity to Supply vs Demand
        res_list = nearest_sr.get("resistance", [])
        sup_list = nearest_sr.get("support", [])

        if sup_list and abs(current_price - sup_list[0]["price"]) <= (atr * 0.75):
            bull_points += 2
            reasons.append(f"At key support ({sup_list[0]['price']:.2f})")

        if res_list and abs(current_price - res_list[0]["price"]) <= (atr * 0.75):
            bear_points += 2
            reasons.append(f"At key resistance ({res_list[0]['price']:.2f})")

        # Demand zone reaction
        for dz in demand_zones:
            if dz["bottom"] <= current_price <= dz["top"] + (atr * 0.5):
                bull_points += 2
                reasons.append(f"Reacting at Demand zone [{dz['bottom']:.2f}-{dz['top']:.2f}]")
                break

        # Supply zone reaction
        for sz in supply_zones:
            if sz["bottom"] - (atr * 0.5) <= current_price <= sz["top"]:
                bear_points += 2
                reasons.append(f"Reacting at Supply zone [{sz['bottom']:.2f}-{sz['top']:.2f}]")
                break

        # Price action patterns
        for p in patterns:
            p_dir = p.get("signal_direction", "")
            if p_dir == "BULLISH":
                bull_points += 2
                reasons.append(f"Bullish pattern: {p.get('pattern_type')}")
            elif p_dir == "BEARISH":
                bear_points += 2
                reasons.append(f"Bearish pattern: {p.get('pattern_type')}")

        if bull_points >= bear_points + 2:
            return Bias.BULLISH.value, "; ".join(reasons) or "Dominant bullish structural momentum"
        elif bear_points >= bull_points + 2:
            return Bias.BEARISH.value, "; ".join(reasons) or "Dominant bearish structural momentum"
        else:
            return Bias.NEUTRAL.value, "Balanced order flow / conflicting structural signals"

    def _compute_invalidation_level(
        self,
        bias: str,
        current_price: float,
        nearest_sr: dict[str, list[dict[str, Any]]],
        swings: dict[str, list[tuple[Any, float]]],
        atr: float,
    ) -> Optional[float]:
        """Compute structural price level that would invalidate the current directional bias."""
        if bias == Bias.BULLISH.value:
            # Invalidation is below recent swing low or primary support
            lows = swings.get("lows", [])
            if lows:
                return float(lows[-1][1] - (atr * 0.2))
            sup = nearest_sr.get("support", [])
            if sup:
                return float(sup[0]["price"] - (atr * 0.3))
            return float(current_price - (atr * 2.0))

        elif bias == Bias.BEARISH.value:
            # Invalidation is above recent swing high or primary resistance
            highs = swings.get("highs", [])
            if highs:
                return float(highs[-1][1] + (atr * 0.2))
            res = nearest_sr.get("resistance", [])
            if res:
                return float(res[0]["price"] + (atr * 0.3))
            return float(current_price + (atr * 2.0))

        return None

    def _generate_scenarios(
        self,
        timeframe: str,
        bias: str,
        current_price: float,
        nearest_sr: dict[str, list[dict[str, Any]]],
        patterns: list[dict[str, Any]],
        is_forming: bool,
        atr: float = 0.0,
    ) -> tuple[str, str, str]:
        """Generate human-readable next candle expectations and primary/alternative scenarios."""
        res = nearest_sr.get("resistance", [])
        sup = nearest_sr.get("support", [])

        fallback_delta = (atr * 1.5) if atr > 0 else (current_price * 0.01)
        next_res = res[0]["price"] if res else (current_price + fallback_delta)
        next_sup = sup[0]["price"] if sup else max(10 ** (-5), current_price - fallback_delta)

        price_prec = 5 if current_price < 5.0 else (3 if current_price < 250.0 else 2)
        res_str = f"{next_res:.{price_prec}f}"
        sup_str = f"{next_sup:.{price_prec}f}"

        candle_prefix = "Active bar is still FORMING; " if is_forming else "Confirmed bar; "

        if bias == Bias.BULLISH.value:
            next_candle = f"{candle_prefix}expecting upward expansion toward {res_str}."
            bull_scen = f"Continuation impulse breaking above {res_str} with target at next structural liquidity."
            bear_scen = f"Rejection at {res_str} or breakdown below {sup_str} would neutralize bullish thesis."
        elif bias == Bias.BEARISH.value:
            next_candle = f"{candle_prefix}expecting downward expansion targeting liquidity at {sup_str}."
            bull_scen = f"Reversal if price holds {sup_str} and forms bullish reversal price action."
            bear_scen = f"Breakdown and close below {sup_str} leading to continuation lower."
        else:
            next_candle = f"{candle_prefix}consolidation between support {sup_str} and resistance {res_str}."
            bull_scen = f"Clean breakout and close above {res_str} required to confirm bullish bias."
            bear_scen = f"Clean breakdown and close below {sup_str} required to confirm bearish bias."

        return next_candle, bull_scen, bear_scen

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < 2:
            return float(df["close"].iloc[-1] * 0.005) if not df.empty else 1.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        if len(tr) == 0:
            return float(df["close"].iloc[-1] * 0.005) if not df.empty else 1.0
        return float(np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr))
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        return float(np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr))

    def _empty_analysis(self, timeframe: str) -> dict[str, Any]:
        return {
            "timeframe": timeframe,
            "candle_count": 0,
            "current_candle_status": CandleStatus.FORMING.value,
            "is_forming": True,
            "current_price": 0.0,
            "atr": 5.0,
            "market_structure": {},
            "trend": "SIDEWAYS",
            "trend_strength": 0.0,
            "swings": {"highs": [], "lows": []},
            "sr_levels": [],
            "nearest_resistance": [],
            "nearest_support": [],
            "trendlines": [],
            "supply_zones": [],
            "demand_zones": [],
            "recent_patterns": [],
            "volume_analysis": {},
            "bias": Bias.NEUTRAL.value,
            "bias_reasoning": "Insufficient historical data",
            "invalidation_level": None,
            "next_candle_expectation": "Waiting for data",
            "bullish_scenario": "N/A",
            "bearish_scenario": "N/A",
        }
