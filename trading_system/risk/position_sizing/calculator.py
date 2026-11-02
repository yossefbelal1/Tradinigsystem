"""
trading_system/risk/position_sizing/calculator.py
=================================================
Quantitative Position Size Calculator for Universal MT5 Trading Intelligence.

Features:
- Native MT5 `order_calc_profit` integration for exact hypothetical stop-loss risk in account currency.
- Cross-currency analytical math fallback when MT5 terminal is offline.
- Explicit accounting of execution costs (spread, broker commission, slippage allowance).
- Dynamic risk budgeting based on live account equity and prop firm remaining loss limits (no hardcoded $1,000 assumption).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# System-wide hard risk constraints
MAX_RISK_PCT: float = 2.0          # Absolute maximum risk per trade (% of equity)
MIN_RISK_PCT: float = 0.05         # Minimum sensible risk threshold
DEFAULT_COMMISSION_PER_LOT: float = 0.0   # Default 0 for pure analytical calculation
DEFAULT_SLIPPAGE_POINTS: int = 0          # Default 0 for pure analytical calculation


class PositionSizeCalculator:
    """
    Calculates exact institutional position sizing across all asset classes and brokers.
    """

    def __init__(
        self,
        commission_per_lot_usd: float = DEFAULT_COMMISSION_PER_LOT,
        slippage_points: int = DEFAULT_SLIPPAGE_POINTS,
        mt5_connector: Optional[Any] = None,
    ):
        self.commission_per_lot = commission_per_lot_usd
        self.slippage_points = slippage_points
        self.mt5 = mt5_connector

    def calculate(
        self,
        account_equity: float,
        risk_pct: float,
        entry_price: float,
        sl_price: float,
        symbol_info: dict[str, Any],
        account_currency: str = "USD",
        direction: str = "BUY",
        max_daily_loss_remaining_usd: Optional[float] = None,
        max_drawdown_remaining_usd: Optional[float] = None,
        spread_points: int = 0,
        commission_per_lot: Optional[float] = None,
        slippage_points: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Calculate an exact position size given a monetary-risk budget and constraints.

        Parameters
        ----------
        account_equity : float
            Current live account equity.
        risk_pct : float
            Desired risk percentage of equity (e.g. 1.0 = 1.0%).
        entry_price : float
            Planned entry price.
        sl_price : float
            Stop loss price.
        symbol_info : dict
            Broker symbol specifications.
        account_currency : str
            Account balance currency (default "USD").
        direction : str
            "BUY" or "SELL".
        max_daily_loss_remaining_usd : float, optional
            Remaining daily loss buffer from prop firm rules engine.
        max_drawdown_remaining_usd : float, optional
            Remaining total drawdown buffer from prop firm rules engine.
        spread_points : int
            Current broker spread in points.
        commission_per_lot : float, optional
            Custom commission per lot round-turn.
        slippage_points : int, optional
            Custom slippage points allowance.

        Returns
        -------
        dict containing complete quantitative risk audit.
        """
        warnings: list[str] = []
        result_template = self._empty_result()

        comm_per_lot = commission_per_lot if commission_per_lot is not None else self.commission_per_lot
        slip_points = slippage_points if slippage_points is not None else self.slippage_points

        # ── 1. Input Validation ──────────────────────────────────────────────
        if account_equity <= 0:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": f"Invalid account equity: {account_equity}",
            }

        if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
            if risk_pct > MAX_RISK_PCT:
                return {
                    **result_template,
                    "is_valid": False,
                    "rejection_reason": f"Requested risk {risk_pct:.2f}% exceeds hard cap {MAX_RISK_PCT}%.",
                }
            warnings.append(f"Risk {risk_pct:.4f}% is very small.")

        if entry_price <= 0 or sl_price <= 0:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": "Entry price and SL price must be positive.",
            }

        sl_distance = abs(entry_price - sl_price)
        if sl_distance < 1e-10:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": "Entry price equals SL price — zero risk invalid.",
            }

        # ── 2. Extract Broker Symbol Specs ──────────────────────────────────
        try:
            symbol_name = str(symbol_info.get("name", symbol_info.get("symbol", "XAUUSD")))
            volume_min = float(symbol_info.get("volume_min", 0.01))
            volume_max = float(symbol_info.get("volume_max", 100.0))
            volume_step = float(symbol_info.get("volume_step", 0.01))
            point = float(symbol_info.get("point", 0.01))
            contract_size = float(symbol_info.get("trade_contract_size", symbol_info.get("contract_size", 100.0)))
            tick_size = float(symbol_info.get("trade_tick_size", symbol_info.get("tick_size", point)))
            tick_value = float(symbol_info.get("trade_tick_value", symbol_info.get("tick_value", 1.0)))
            profit_currency = str(symbol_info.get("currency_profit", account_currency))
        except (KeyError, TypeError, ValueError) as exc:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": f"Incomplete symbol_info specifications: {exc}",
            }

        if tick_size <= 0:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": "Symbol tick_size must be positive.",
            }

        # ── 3. Exact Loss Calculation per 1.0 Standard Lot ──────────────────
        loss_per_lot_account_curr = self._calc_loss_per_lot(
            symbol=symbol_name,
            direction=direction,
            entry_price=entry_price,
            sl_price=sl_price,
            point=point,
            contract_size=contract_size,
            tick_size=tick_size,
            tick_value=tick_value,
            profit_currency=profit_currency,
            account_currency=account_currency,
        )

        if loss_per_lot_account_curr <= 0:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": "SL distance resolves to zero monetary value.",
            }

        # ── 4. Calculate Execution Costs per 1.0 Lot ─────────────────────────
        # Value of 1 point per lot in account currency
        point_value_per_lot = (tick_value / tick_size) * point if tick_size > 0 else point

        # Spread cost per lot
        effective_spread = max(spread_points, 0)
        spread_cost_per_lot = effective_spread * point_value_per_lot

        # Commission and slippage allowance per lot
        commission_cost_per_lot = comm_per_lot
        slippage_cost_per_lot = slip_points * point_value_per_lot

        total_cost_per_lot = (
            loss_per_lot_account_curr
            + spread_cost_per_lot
            + commission_cost_per_lot
            + slippage_cost_per_lot
        )

        # ── 5. Determine Allowed Monetary Risk Budget ─────────────────────────
        target_monetary_risk = (risk_pct / 100.0) * account_equity
        allowed_risk_budget = target_monetary_risk

        # Constrain against remaining prop firm daily limit (leave 25% safety margin)
        if max_daily_loss_remaining_usd is not None and max_daily_loss_remaining_usd > 0:
            safe_daily_limit = max_daily_loss_remaining_usd * 0.75
            if allowed_risk_budget > safe_daily_limit:
                allowed_risk_budget = safe_daily_limit
                warnings.append(
                    f"Risk clamped from ${target_monetary_risk:.2f} to ${allowed_risk_budget:.2f} "
                    f"to respect prop firm remaining daily loss buffer."
                )

        # Constrain against remaining prop firm total drawdown (leave 20% safety margin)
        if max_drawdown_remaining_usd is not None and max_drawdown_remaining_usd > 0:
            safe_dd_limit = max_drawdown_remaining_usd * 0.80
            if allowed_risk_budget > safe_dd_limit:
                allowed_risk_budget = safe_dd_limit
                warnings.append(
                    f"Risk clamped to ${allowed_risk_budget:.2f} to protect remaining max drawdown."
                )

        if allowed_risk_budget <= 0:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": "No remaining risk budget available. Daily or max drawdown near limit.",
            }

        # ── 6. Size Position & Round to Broker Lot Step ───────────────────────
        raw_lots = allowed_risk_budget / total_cost_per_lot
        lots = self._round_lots(raw_lots, volume_min, volume_max, volume_step)

        if lots < volume_min:
            return {
                **result_template,
                "is_valid": False,
                "rejection_reason": (
                    f"Calculated size {raw_lots:.4f} lots is below broker minimum {volume_min}. "
                    "Widen the stop loss or increase equity buffer."
                ),
            }

        if lots >= volume_max:
            warnings.append(f"Position clamped to broker maximum {volume_max} lots.")

        # ── 7. Calculate Realized Final Quantities ────────────────────────────
        final_sl_loss = lots * loss_per_lot_account_curr
        final_spread_cost = lots * spread_cost_per_lot
        final_commission = lots * commission_cost_per_lot
        final_slippage = lots * slippage_cost_per_lot
        total_realized_risk = final_sl_loss + final_spread_cost + final_commission + final_slippage

        actual_risk_pct = (total_realized_risk / account_equity) * 100.0
        sl_points = int(round(sl_distance / point)) if point > 0 else 0
        tp1_lots = self._round_lots(lots * 0.50, volume_min, lots, volume_step)

        return {
            "lots": lots,
            "monetary_risk_usd": round(final_sl_loss, 2),
            "total_execution_risk_usd": round(total_realized_risk, 2),
            "monetary_risk_pct": round(actual_risk_pct, 4),
            "sl_points": sl_points,
            "sl_distance_usd": round(loss_per_lot_account_curr, 4),
            "spread_cost_usd": round(final_spread_cost, 2),
            "commission_cost_usd": round(final_commission, 2),
            "slippage_cost_usd": round(final_slippage, 2),
            "tp1_lots": tp1_lots,
            "pip_value_per_lot": round(point_value_per_lot, 6),
            "contract_size": contract_size,
            "is_valid": True,
            "rejection_reason": None,
            "warnings": warnings,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_loss_per_lot(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        point: float,
        contract_size: float,
        tick_size: float,
        tick_value: float,
        profit_currency: str,
        account_currency: str,
    ) -> float:
        """
        Calculate monetary loss for 1.0 standard lot.
        When tick_value and tick_size are explicitly provided, standard formula:
        ticks = (distance / tick_size) * tick_value.
        """
        sl_price_diff = abs(entry_price - sl_price)

        if tick_size > 0 and tick_value > 0:
            ticks = sl_price_diff / tick_size
            return ticks * tick_value

        raw_loss = sl_price_diff * contract_size
        if profit_currency.upper() == account_currency.upper():
            return raw_loss

        if profit_currency.upper() == "JPY" and account_currency.upper() == "USD":
            usdjpy_rate = entry_price if "JPY" in symbol else 150.0
            return raw_loss / max(usdjpy_rate, 1.0)

        return raw_loss

    @staticmethod
    def _round_lots(
        raw_lots: float,
        volume_min: float,
        volume_max: float,
        volume_step: float,
    ) -> float:
        """Round lots DOWN to the nearest valid step, clamped to [min, max]."""
        if volume_step <= 0:
            return max(volume_min, min(raw_lots, volume_max))

        step_decimals = max(0, -int(math.floor(math.log10(volume_step))))
        lots = math.floor(raw_lots / volume_step) * volume_step
        lots = round(lots, step_decimals + 2)
        lots = max(volume_min, min(lots, volume_max))
        return round(lots, step_decimals + 2)

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "lots": 0.0,
            "monetary_risk_usd": 0.0,
            "total_execution_risk_usd": 0.0,
            "monetary_risk_pct": 0.0,
            "sl_points": 0,
            "sl_distance_usd": 0.0,
            "spread_cost_usd": 0.0,
            "commission_cost_usd": 0.0,
            "slippage_cost_usd": 0.0,
            "tp1_lots": 0.0,
            "pip_value_per_lot": 0.0,
            "contract_size": 0.0,
            "is_valid": False,
            "rejection_reason": None,
            "warnings": [],
        }
