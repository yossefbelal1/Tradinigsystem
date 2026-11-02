"""
risk/prop_firm/rules_engine.py
==============================
Proprietary Trading Firm Rules Engine.
CRITICAL QUANTITATIVE DIFFERENTIATOR:
Implements exact, firm-specific drawdown algorithms (Static vs. End-of-Day Trailing vs. Live Intraday Trailing).
Never confuses static floors with trailing ratchets.
Continuously calculates remaining daily and total risk capacity to prevent rule breaches.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from trading_system.config.settings import DrawdownType, PROP_FIRMS_DIR
from trading_system.risk.trade_manager.trade_plan import TradePlan

logger = logging.getLogger(__name__)


class PropFirmRulesEngine:
    """
    Simulates and enforces exact evaluation and funded account rules for proprietary trading firms.
    """

    def __init__(self, config_path_or_name: Optional[str] = "ftmo_2step"):
        self.config: dict[str, Any] = {}
        self.load_config(config_path_or_name)

        # State tracking
        self.starting_balance: float = 100000.0
        self.hwm_eod: float = 100000.0
        self.hwm_intraday: float = 100000.0
        self.daily_starting_equity: float = 100000.0
        self.is_breached: bool = False
        self.breach_reason: Optional[str] = None

    def load_config(self, config_name_or_path: Optional[str]) -> None:
        """Load YAML configuration for the target firm."""
        if not config_name_or_path:
            config_name_or_path = "ftmo_2step"

        p = Path(config_name_or_path)
        if not p.exists() and not str(config_name_or_path).endswith(".yaml"):
            p = PROP_FIRMS_DIR / f"{config_name_or_path}.yaml"

        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                logger.info("Loaded prop firm rules from %s: %s", p.name, self.config.get("name"))
            except Exception as e:
                logger.error("Failed to parse prop firm config %s: %s", p, e)
                self._load_default_ftmo_config()
        else:
            logger.warning("Prop firm config '%s' not found. Using standard FTMO 2-step defaults.", config_name_or_path)
            self._load_default_ftmo_config()

    def update_account_state(
        self,
        account_info: dict[str, Any],
        is_new_day: bool = False,
    ) -> None:
        """
        Update the internal equity tracking state with live account data.
        """
        equity = float(account_info.get("equity", 100000.0))
        balance = float(account_info.get("balance", 100000.0))

        if self.starting_balance <= 0:
            self.starting_balance = balance
            self.hwm_eod = balance
            self.hwm_intraday = max(balance, equity)
            self.daily_starting_equity = equity

        # Track live intraday high water mark
        if equity > self.hwm_intraday:
            self.hwm_intraday = equity

        # If a new trading day has started (e.g. 00:00 server time)
        if is_new_day:
            self.daily_starting_equity = equity
            self.hwm_eod = max(self.hwm_eod, balance)

    def get_current_limits(self, account_info: dict[str, Any]) -> dict[str, Any]:
        """
        Calculate live drawdown floors, remaining daily risk, and breach state.
        """
        equity = float(account_info.get("equity", self.starting_balance))
        balance = float(account_info.get("balance", self.starting_balance))

        dd_type = str(self.config.get("drawdown_type", DrawdownType.STATIC.value)).lower()
        max_dd_pct = float(self.config.get("max_drawdown_pct", 10.0))
        daily_loss_pct = float(self.config.get("daily_loss_limit_pct", 5.0) or 5.0)
        target_pct = float(self.config.get("profit_target_phase1_pct", 10.0))

        # ── 1. Calculate Maximum Drawdown Floor ──────────────────────────────
        if dd_type == DrawdownType.STATIC.value:
            # Fixed absolute floor from initial balance
            max_dd_floor = self.starting_balance * (1.0 - (max_dd_pct / 100.0))
        elif dd_type == DrawdownType.EOD_TRAILING.value:
            # Floor trails highest end-of-day balance
            max_dd_floor = self.hwm_eod * (1.0 - (max_dd_pct / 100.0))
        elif dd_type == DrawdownType.INTRADAY_TRAILING.value:
            # Floor trails live intraday equity peak in real-time
            max_dd_floor = self.hwm_intraday * (1.0 - (max_dd_pct / 100.0))
        else:
            max_dd_floor = self.starting_balance * (1.0 - (max_dd_pct / 100.0))

        remaining_dd_usd = max(0.0, equity - max_dd_floor)
        current_dd_pct = round(((self.hwm_intraday - equity) / max(self.hwm_intraday, 1.0)) * 100.0, 2)
        remaining_dd_pct = round((remaining_dd_usd / max(equity, 1.0)) * 100.0, 2)

        # ── 2. Calculate Daily Loss Limit ───────────────────────────────────
        daily_basis = str(self.config.get("daily_loss_basis", "equity")).lower()
        ref_daily = self.daily_starting_equity if daily_basis == "equity" else balance
        daily_loss_floor = ref_daily * (1.0 - (daily_loss_pct / 100.0))

        daily_remaining_usd = max(0.0, equity - daily_loss_floor)
        daily_loss_used_usd = max(0.0, ref_daily - equity)
        daily_remaining_pct = round((daily_remaining_usd / max(equity, 1.0)) * 100.0, 2)

        # ── 3. Profit Target Progress ───────────────────────────────────────
        target_balance = self.starting_balance * (1.0 + (target_pct / 100.0))
        profit_usd = equity - self.starting_balance
        profit_progress_pct = round((profit_usd / (target_balance - self.starting_balance)) * 100.0, 1)

        # ── 4. Breach Detection & Platform Verification ─────────────────────
        is_breached = False
        breach_reason = None
        warnings = []

        mt5_comp = self.config.get("mt5_compatible", True)
        if not mt5_comp:
            warning_msg = self.config.get(
                "futures_warning",
                "NOTICE: This firm operates on CME Futures and is NOT directly compatible with MT5 CFD trading."
            )
            warnings.append(warning_msg)

        if equity <= max_dd_floor:
            is_breached = True
            breach_reason = f"Maximum drawdown breached! Equity (${equity:.2f}) dropped below floor (${max_dd_floor:.2f})."
        elif equity <= daily_loss_floor:
            is_breached = True
            breach_reason = f"Daily loss limit breached! Equity (${equity:.2f}) dropped below daily floor (${daily_loss_floor:.2f})."
        elif remaining_dd_pct < 2.0:
            warnings.append(f"CRITICAL: Less than 2% drawdown remaining (${remaining_dd_usd:.2f}) until account breach!")
        elif daily_remaining_pct < 1.5:
            warnings.append(f"WARNING: Less than 1.5% daily loss capacity remaining (${daily_remaining_usd:.2f})!")

        self.is_breached = is_breached
        self.breach_reason = breach_reason

        return {
            "firm_name": self.config.get("name", "Prop Firm"),
            "platform": self.config.get("platform", "MetaTrader 5"),
            "mt5_compatible": mt5_comp,
            "supported_instruments": self.config.get("supported_instruments", []),
            "drawdown_type": dd_type,
            "max_allowed_drawdown_floor": round(max_dd_floor, 2),
            "current_drawdown_pct": current_dd_pct,
            "remaining_drawdown_usd": round(remaining_dd_usd, 2),
            "remaining_drawdown_pct": remaining_dd_pct,
            "daily_loss_limit_floor": round(daily_loss_floor, 2),
            "daily_loss_used_usd": round(daily_loss_used_usd, 2),
            "daily_loss_remaining_usd": round(daily_remaining_usd, 2),
            "daily_loss_remaining_pct": daily_remaining_pct,
            "profit_target_pct": target_pct,
            "profit_progress_pct": profit_progress_pct,
            "is_passing": profit_usd >= 0 and not is_breached,
            "is_breached": is_breached,
            "breach_reason": breach_reason,
            "warnings": warnings,
        }

    def validate_new_trade(
        self,
        plan: TradePlan,
        account_info: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        Check if executing this planned trade could cause an immediate daily or max DD breach.
        """
        limits = self.get_current_limits(account_info)
        violations: list[str] = []

        if limits["is_breached"]:
            violations.append(f"Cannot take new trade: Account is already BREACHED ({limits['breach_reason']}).")
            return False, violations

        trade_risk = plan.monetary_risk_usd
        daily_rem = limits["daily_loss_remaining_usd"]
        max_rem = limits["remaining_drawdown_usd"]

        # Ensure trade risk does not exceed 75% of remaining daily capacity (leave buffer for slippage)
        safe_daily_limit = daily_rem * 0.75
        if trade_risk > safe_daily_limit:
            violations.append(
                f"Trade risk (${trade_risk:.2f}) exceeds 75% of remaining daily buffer (${safe_daily_limit:.2f}). "
                f"Slippage or spread expansion would risk daily breach."
            )

        if trade_risk > (max_rem * 0.80):
            violations.append(
                f"Trade risk (${trade_risk:.2f}) exceeds 80% of remaining overall drawdown (${max_rem * 0.80:.2f})."
            )

        is_valid = len(violations) == 0
        return is_valid, violations

    def _load_default_ftmo_config(self) -> None:
        self.config = {
            "name": "FTMO 2-Step Challenge",
            "type": "evaluation",
            "drawdown_type": "static",
            "max_drawdown_pct": 10.0,
            "daily_loss_limit_pct": 5.0,
            "daily_loss_basis": "equity",
            "profit_target_phase1_pct": 10.0,
            "profit_target_phase2_pct": 5.0,
            "min_trading_days": 4,
            "max_trading_days": 30,
        }
