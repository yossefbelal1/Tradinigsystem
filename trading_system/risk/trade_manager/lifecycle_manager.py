"""
risk/trade_manager/lifecycle_manager.py
======================================
Open Position Lifecycle and Active Thesis Monitoring Engine.
Tracks manually executed positions, computes real-time R-multiples, verifies thesis validity,
and provides objective recommendations for the human trader without automatic intervention.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from trading_system.risk.trade_manager.trade_plan import TradePlan

logger = logging.getLogger(__name__)


class TradeLifecycleManager:
    """
    Monitors live positions opened by the human trader against the active TradePlan.
    Evaluates thesis health, detects invalidation signals, and issues non-binding guidance.
    """

    def update_position_state(
        self,
        plan: TradePlan,
        mt5_position: Optional[dict[str, Any]],
        current_price: float,
        current_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute live position metrics, distance to targets/invalidation, and thesis status.
        """
        entry_price = plan.actual_entry_price or plan.entry_price
        sl_price = plan.actual_sl or plan.stop_loss
        tp1_price = plan.take_profit_1
        tp2_price = plan.take_profit_2
        initial_risk = max(plan.monetary_risk_usd, 1.0)
        direction = plan.direction.upper()

        # If connected to MT5 position, use live floating P&L
        if mt5_position:
            floating_pnl = float(mt5_position.get("profit", 0.0))
        else:
            # Estimate P&L using points difference
            if direction == "BUY":
                pt_diff = current_price - entry_price
            else:
                pt_diff = entry_price - current_price
            # Approximate for standard 100oz Gold lot: 1 lot = $100 per $1.00 move
            lots = plan.actual_lots or plan.position_size_lots
            floating_pnl = pt_diff * 100.0 * lots

        # Current R-multiple
        current_r = round(floating_pnl / initial_risk, 2)

        # Distances to milestones
        total_sl_dist = abs(entry_price - sl_price)
        cur_to_sl = abs(current_price - sl_price)
        dist_to_sl_pct = round((cur_to_sl / total_sl_dist) * 100.0, 1) if total_sl_dist > 0 else 100.0

        total_tp1_dist = abs(tp1_price - entry_price)
        cur_to_tp1 = abs(tp1_price - current_price)
        dist_to_tp1_pct = round((cur_to_tp1 / total_tp1_dist) * 100.0, 1) if total_tp1_dist > 0 else 0.0

        # Invalidation check
        inval_info = self.check_trade_invalidation(plan, current_analysis, current_price)

        # Breakeven check
        be_info = self.detect_breakeven_opportunity(plan, current_price, current_r)

        # Generate non-binding advice
        recs: list[str] = []
        alerts: list[str] = []

        if dist_to_sl_pct < 20.0:
            alerts.append(f"WARNING: Price is within {dist_to_sl_pct}% of Stop Loss ({sl_price:.2f}).")

        if be_info.get("eligible", False):
            recs.append(f"CONSIDERATION: Trade has reached {current_r:.1f}R. Moving SL to Break-Even ({entry_price:.2f}) is statistically favored.")

        if current_r >= plan.risk_reward_tp1:
            recs.append(f"TARGET 1 HIT ({tp1_price:.2f}): Consider taking 50% partial profits and trailing remainder.")

        if inval_info.get("is_invalidated", False):
            alerts.append(f"THESIS BREACH: {inval_info.get('reason')}. Consider manual closure to minimize loss.")

        return {
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "direction": direction,
            "entry_price": entry_price,
            "current_price": current_price,
            "stop_loss": sl_price,
            "take_profit_1": tp1_price,
            "take_profit_2": tp2_price,
            "floating_pnl_usd": round(floating_pnl, 2),
            "floating_r": current_r,
            "distance_to_sl_pct": dist_to_sl_pct,
            "distance_to_tp1_pct": dist_to_tp1_pct,
            "thesis_intact": not inval_info.get("is_invalidated", False),
            "thesis_notes": inval_info.get("reason", "Structural thesis remains valid."),
            "recommendations": recs,
            "alerts": alerts,
        }

    def check_trade_invalidation(
        self,
        plan: TradePlan,
        current_analysis: dict[str, Any],
        current_price: float,
    ) -> dict[str, Any]:
        """
        Verify whether market structure on H1 or H4 has broken against the trade thesis.
        """
        direction = plan.direction.upper()
        h1_bias = current_analysis.get("bias", "")
        h1_trend = current_analysis.get("trend", "")

        # Check if invalidation price was hit
        if plan.invalidation_price > 0:
            if direction == "BUY" and current_price <= plan.invalidation_price:
                return {
                    "is_invalidated": True,
                    "reason": f"Price crossed structural invalidation level ({plan.invalidation_price:.2f}).",
                }
            elif direction == "SELL" and current_price >= plan.invalidation_price:
                return {
                    "is_invalidated": True,
                    "reason": f"Price crossed structural invalidation level ({plan.invalidation_price:.2f}).",
                }

        # Check for structural shift
        if direction == "BUY" and h1_trend == "BEARISH" and h1_bias == "BEARISH":
            return {
                "is_invalidated": True,
                "reason": "H1 market structure has flipped to confirmed BEARISH with lower lows.",
            }
        elif direction == "SELL" and h1_trend == "BULLISH" and h1_bias == "BULLISH":
            return {
                "is_invalidated": True,
                "reason": "H1 market structure has flipped to confirmed BULLISH with higher highs.",
            }

        return {"is_invalidated": False, "reason": "Market structure supports trade direction."}

    def detect_breakeven_opportunity(
        self,
        plan: TradePlan,
        current_price: float,
        current_r: float,
    ) -> dict[str, Any]:
        """
        Determine if moving SL to break-even is statistically defensible.
        Moving to BE too early (<1.0R) stops out valid trades prematurely on normal noise.
        """
        if current_r >= 1.5:
            return {
                "eligible": True,
                "message": f"Floating profit at {current_r:.1f}R exceeds minimum threshold (1.5R) for BE transition.",
            }
        return {"eligible": False, "message": f"Current {current_r:.1f}R is below 1.5R threshold."}
