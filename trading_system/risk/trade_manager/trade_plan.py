"""
risk/trade_manager/trade_plan.py
================================
Complete Trade Plan Schema and Rigorous Pre-Trade Validation Engine.
CRITICAL SAFETY RULE: Every trade plan is an analytical blueprint for the human trader.
It NEVER executes autonomously.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from trading_system.config.settings import MAX_RISK_PCT, MIN_RR_TP1, MIN_RR_TP2, SetupQuality, TradeStatus

logger = logging.getLogger(__name__)


@dataclass
class TradePlan:
    """
    Formalized, evidence-grounded trade setup blueprint.
    """
    # Identification
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str = "XAUUSD"
    direction: str = "BUY"  # BUY or SELL
    status: str = TradeStatus.PENDING.value

    # Market context
    market_context: str = ""
    htf_bias: str = "BULLISH"
    setup_quality: str = SetupQuality.A.value

    # Key Price levels
    entry_price: float = 0.0
    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: Optional[float] = None

    # Risk & Reward Metrics
    risk_reward_tp1: float = 0.0
    risk_reward_tp2: float = 0.0
    position_size_lots: float = 0.0
    monetary_risk_usd: float = 0.0
    risk_pct_of_equity: float = 1.0

    # Rules of Engagement
    confirmation_conditions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    invalidation_price: float = 0.0

    # Analysis Evidence
    pattern_signals: list[str] = field(default_factory=list)
    zone_confluence: list[str] = field(default_factory=list)
    sr_confluence: list[str] = field(default_factory=list)

    # Metadata & Provenance
    data_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_source: str = "MT5"
    analyst_notes: str = ""

    # Human Execution Tracking (Populated once trader manually enters in MT5)
    mt5_ticket: Optional[int] = None
    actual_entry_price: Optional[float] = None
    actual_sl: Optional[float] = None
    actual_tp: Optional[float] = None
    actual_lots: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert trade plan dataclass to standard JSON-serializable dictionary."""
        data = asdict(self)
        if isinstance(self.created_at, datetime):
            data["created_at"] = self.created_at.isoformat()
        return data


class TradePlanValidator:
    """
    Validates trade plan integrity prior to presenting to the trader.
    Rejects setups that violate mathematical risk rules, R:R limits, or directional sanity.
    """

    def validate(
        self,
        plan: TradePlan,
        account_info: Optional[dict[str, Any]] = None,
        prop_firm_rules: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, list[str]]:
        """
        Run complete validation checklist.
        Returns: (is_valid: bool, list_of_violations: list[str])
        """
        violations: list[str] = []

        # 1. Price Geometry
        if plan.direction == "BUY":
            if plan.stop_loss >= plan.entry_price:
                violations.append(f"BUY setup SL ({plan.stop_loss:.2f}) must be strictly below entry ({plan.entry_price:.2f}).")
            if plan.take_profit_1 <= plan.entry_price:
                violations.append(f"BUY setup TP1 ({plan.take_profit_1:.2f}) must be strictly above entry ({plan.entry_price:.2f}).")
            if plan.take_profit_2 <= plan.take_profit_1:
                violations.append(f"BUY setup TP2 ({plan.take_profit_2:.2f}) must be higher than TP1 ({plan.take_profit_1:.2f}).")

        elif plan.direction == "SELL":
            if plan.stop_loss <= plan.entry_price:
                violations.append(f"SELL setup SL ({plan.stop_loss:.2f}) must be strictly above entry ({plan.entry_price:.2f}).")
            if plan.take_profit_1 >= plan.entry_price:
                violations.append(f"SELL setup TP1 ({plan.take_profit_1:.2f}) must be strictly below entry ({plan.entry_price:.2f}).")
            if plan.take_profit_2 >= plan.take_profit_1:
                violations.append(f"SELL setup TP2 ({plan.take_profit_2:.2f}) must be lower than TP1 ({plan.take_profit_1:.2f}).")
        else:
            violations.append(f"Unknown direction '{plan.direction}'. Must be BUY or SELL.")

        # 2. Risk-to-Reward Criteria
        if plan.risk_reward_tp1 < MIN_RR_TP1:
            violations.append(f"Risk:Reward for TP1 ({plan.risk_reward_tp1:.2f}) is below minimum required {MIN_RR_TP1:.2f}.")

        # 3. Maximum Risk Percentage
        if plan.risk_pct_of_equity > MAX_RISK_PCT:
            violations.append(f"Risk percentage ({plan.risk_pct_of_equity:.2f}%) exceeds maximum limit ({MAX_RISK_PCT:.2f}%).")

        # 4. Account Info & Free Margin Check
        if account_info:
            free_margin = float(account_info.get("free_margin", account_info.get("equity", 10000.0)))
            equity = float(account_info.get("equity", 10000.0))

            if plan.monetary_risk_usd > (equity * (MAX_RISK_PCT / 100.0)):
                violations.append(f"Monetary risk (${plan.monetary_risk_usd:.2f}) exceeds {MAX_RISK_PCT}% equity cap (${equity * 0.02:.2f}).")

            if plan.monetary_risk_usd > free_margin:
                violations.append("Insufficient free margin to sustain required stop loss distance.")

        # 5. Prop Firm Rule Checks
        if prop_firm_rules:
            daily_remaining = float(prop_firm_rules.get("daily_loss_remaining_usd", float("inf")))
            if plan.monetary_risk_usd > daily_remaining:
                violations.append(
                    f"Monetary risk (${plan.monetary_risk_usd:.2f}) would breach remaining daily loss limit (${daily_remaining:.2f})."
                )

        is_valid = len(violations) == 0
        return is_valid, violations
