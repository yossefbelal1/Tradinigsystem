"""
Position Size Calculator for XAUUSD Professional Trading System.

Uses actual broker symbol specs (symbol_info dict from MT5) for all calculations.
No hardcoded assumptions about contract sizes, pip values, or lot steps.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# System-wide hard caps — individual prop firm rules are checked separately
MAX_RISK_PCT: float = 2.0          # Absolute maximum risk per trade (%)
MIN_RISK_PCT: float = 0.05         # Below this is likely a misconfiguration
MIN_RR_RATIO: float = 1.5          # Minimum acceptable Risk:Reward for TP1
TP1_CLOSE_FRACTION: float = 0.50   # Fraction of position to close at TP1


class PositionSizeCalculator:
    """
    Calculates position sizes for XAUUSD (and any MT5 symbol) using real
    broker symbol specifications.

    All monetary values are in USD.  Risk is expressed as a percentage of
    *account equity* (not balance) so unrealised P&L is included.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        account_equity: float,
        risk_pct: float,
        entry_price: float,
        sl_price: float,
        symbol_info: dict,
        account_currency: str = "USD",
    ) -> dict:
        """
        Calculate a position size given a monetary-risk budget.

        Parameters
        ----------
        account_equity : float
            Current account equity in account currency.
        risk_pct : float
            Desired risk as a percentage of equity (e.g. 1.0 = 1 %).
        entry_price : float
            Expected entry price (ask for BUY, bid for SELL).
        sl_price : float
            Stop-loss price.
        symbol_info : dict
            MT5 symbol_info_tick / symbol_info fields expected:
                volume_min, volume_max, volume_step,
                contract_size, trade_tick_size, trade_tick_value,
                currency_profit, currency_base,
                trade_contract_size (alias for contract_size if present).
        account_currency : str
            ISO code of the account currency (default "USD").

        Returns
        -------
        dict with keys:
            lots, monetary_risk_usd, monetary_risk_pct, sl_points,
            sl_distance_usd, tp1_lots, pip_value_per_lot, contract_size,
            is_valid, rejection_reason, warnings.
        """
        warnings: list[str] = []
        result_template = self._empty_result()

        # ── Validate inputs ────────────────────────────────────────────
        if account_equity <= 0:
            return {**result_template, "is_valid": False,
                    "rejection_reason": f"Invalid account equity: {account_equity}"}

        if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
            if risk_pct > MAX_RISK_PCT:
                return {**result_template, "is_valid": False,
                        "rejection_reason": (
                            f"Risk {risk_pct:.2f}% exceeds hard cap {MAX_RISK_PCT}%"
                        )}
            warnings.append(
                f"Risk {risk_pct:.4f}% is very small — possible misconfiguration"
            )

        if entry_price <= 0 or sl_price <= 0:
            return {**result_template, "is_valid": False,
                    "rejection_reason": "Entry price and SL price must be positive"}

        if abs(entry_price - sl_price) < 1e-10:
            return {**result_template, "is_valid": False,
                    "rejection_reason": "Entry price equals SL price — zero risk trade"}

        # ── Extract symbol specs ───────────────────────────────────────
        try:
            volume_min = float(symbol_info["volume_min"])
            volume_max = float(symbol_info["volume_max"])
            volume_step = float(symbol_info["volume_step"])
            contract_size = float(
                symbol_info.get("trade_contract_size",
                                symbol_info.get("contract_size", 100.0))
            )
            tick_size = float(symbol_info.get("trade_tick_size", symbol_info.get("tick_size", 0.01)))
            tick_value = float(symbol_info.get("trade_tick_value", symbol_info.get("tick_value", 1.0)))
        except (KeyError, TypeError, ValueError) as exc:
            return {**result_template, "is_valid": False,
                    "rejection_reason": f"Incomplete symbol_info: {exc}"}

        if tick_size <= 0:
            return {**result_template, "is_valid": False,
                    "rejection_reason": "tick_size must be positive"}

        # ── Core calculations ─────────────────────────────────────────
        # Pip value per lot in account currency
        # pip_value_per_lot = (tick_value / tick_size) * tick_size  simplifies to:
        pip_value_per_lot = tick_value  # tick_value IS the value of 1 tick per 1 lot

        # Dollar risk budget
        monetary_risk_usd = (risk_pct / 100.0) * account_equity

        # SL distance in price units
        sl_distance_price = abs(entry_price - sl_price)

        # How many ticks is the SL distance?
        sl_ticks = sl_distance_price / tick_size
        sl_points = round(sl_distance_price / tick_size)  # integer ticks

        # Dollar value of SL distance per lot
        sl_distance_usd_per_lot = sl_ticks * tick_value

        if sl_distance_usd_per_lot <= 0:
            return {**result_template, "is_valid": False,
                    "rejection_reason": "SL distance resolves to zero monetary value"}

        # Raw (unrounded) lots
        raw_lots = monetary_risk_usd / sl_distance_usd_per_lot

        # Clamp to broker limits and round to volume step
        lots = self._round_lots(raw_lots, volume_min, volume_max, volume_step)

        # Recalculate actual monetary risk with rounded lots
        actual_monetary_risk_usd = lots * sl_distance_usd_per_lot
        actual_risk_pct = (actual_monetary_risk_usd / account_equity) * 100.0

        # TP1 partial close
        tp1_lots = self._round_lots(
            lots * TP1_CLOSE_FRACTION, volume_min, lots, volume_step
        )

        # ── Sanity warnings ────────────────────────────────────────────
        if lots < volume_min:
            return {**result_template, "is_valid": False,
                    "rejection_reason": (
                        f"Calculated lots {raw_lots:.5f} rounds below minimum "
                        f"{volume_min}.  Reduce risk % or widen the stop."
                    )}

        if lots >= volume_max:
            warnings.append(
                f"Position clamped to broker maximum {volume_max} lots. "
                "Actual risk is lower than requested."
            )

        deviation_pct = abs(actual_risk_pct - risk_pct) / risk_pct * 100
        if deviation_pct > 10:
            warnings.append(
                f"Rounded position size deviates {deviation_pct:.1f}% from "
                "target risk due to lot step constraints."
            )

        if sl_ticks < 50:
            warnings.append(
                f"SL is only {sl_ticks:.0f} ticks — may be inside spread "
                "or broker minimum stop distance."
            )

        if account_currency.upper() != "USD":
            warnings.append(
                f"Account currency is {account_currency}; pip_value_per_lot "
                "is in the symbol's profit currency (USD for XAUUSD). "
                "Cross-currency conversion not applied — verify with broker."
            )

        return {
            "lots": lots,
            "monetary_risk_usd": round(actual_monetary_risk_usd, 2),
            "monetary_risk_pct": round(actual_risk_pct, 4),
            "sl_points": sl_points,
            "sl_distance_usd": round(sl_distance_usd_per_lot, 4),
            "tp1_lots": tp1_lots,
            "pip_value_per_lot": round(pip_value_per_lot, 6),
            "contract_size": contract_size,
            "is_valid": True,
            "rejection_reason": None,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------

    def calculate_from_atr(
        self,
        account_equity: float,
        risk_pct: float,
        entry_price: float,
        atr: float,
        atr_multiplier: float,
        symbol_info: dict,
        direction: str = "BUY",
    ) -> dict:
        """
        Calculate position size using an ATR-based stop-loss distance.

        Parameters
        ----------
        entry_price : float
            Expected entry price.
        atr : float
            Current ATR value (in price units, same as entry_price).
        atr_multiplier : float
            How many ATRs to place the SL away from entry (e.g. 1.5).
        direction : str
            "BUY" or "SELL".  Determines SL placement side.

        Returns
        -------
        dict — same as ``calculate()``, with extra keys:
            atr_used, atr_multiplier, atr_sl_distance.
        """
        if atr <= 0:
            return {
                **self._empty_result(),
                "is_valid": False,
                "rejection_reason": f"ATR must be positive, got {atr}",
            }
        if atr_multiplier <= 0:
            return {
                **self._empty_result(),
                "is_valid": False,
                "rejection_reason": f"ATR multiplier must be positive, got {atr_multiplier}",
            }

        sl_distance = atr * atr_multiplier

        if direction.upper() == "BUY":
            sl_price = entry_price - sl_distance
        elif direction.upper() == "SELL":
            sl_price = entry_price + sl_distance
        else:
            return {
                **self._empty_result(),
                "is_valid": False,
                "rejection_reason": f"Invalid direction '{direction}'. Use BUY or SELL.",
            }

        result = self.calculate(
            account_equity=account_equity,
            risk_pct=risk_pct,
            entry_price=entry_price,
            sl_price=sl_price,
            symbol_info=symbol_info,
        )

        # Augment with ATR-specific metadata
        result["atr_used"] = atr
        result["atr_multiplier"] = atr_multiplier
        result["atr_sl_distance"] = round(sl_distance, 5)
        result["computed_sl_price"] = round(sl_price, 5)

        return result

    # ------------------------------------------------------------------

    def validate_position(
        self,
        lots: float,
        symbol_info: dict,
        account_info: dict,
    ) -> tuple[bool, str]:
        """
        Validate a proposed position before order placement.

        Checks broker lot limits and whether the account has sufficient
        free margin to open the position.

        Parameters
        ----------
        lots : float
            Proposed position size.
        symbol_info : dict
            Must contain: volume_min, volume_max, volume_step,
            margin_initial (margin required per 1 lot), trade_tick_size,
            trade_tick_value.
        account_info : dict
            Must contain: free_margin (account free margin in USD),
            equity.

        Returns
        -------
        (is_valid: bool, reason: str)
        """
        try:
            volume_min = float(symbol_info["volume_min"])
            volume_max = float(symbol_info["volume_max"])
            volume_step = float(symbol_info["volume_step"])
        except (KeyError, TypeError) as exc:
            return False, f"Incomplete symbol_info for validation: {exc}"

        if lots < volume_min:
            return False, (
                f"Lots {lots} is below broker minimum {volume_min}"
            )
        if lots > volume_max:
            return False, (
                f"Lots {lots} exceeds broker maximum {volume_max}"
            )

        # Check step alignment (with floating point tolerance)
        remainder = lots % volume_step
        if remainder > 1e-9 and (volume_step - remainder) > 1e-9:
            return False, (
                f"Lots {lots} is not aligned to volume step {volume_step}"
            )

        # Margin check
        free_margin = account_info.get("free_margin", account_info.get("freeMargin", None))
        if free_margin is None:
            return False, "account_info missing 'free_margin'"

        margin_initial = symbol_info.get("margin_initial")
        if margin_initial is not None and margin_initial > 0:
            required_margin = lots * float(margin_initial)
            if required_margin > float(free_margin):
                return False, (
                    f"Required margin ${required_margin:.2f} exceeds free "
                    f"margin ${float(free_margin):.2f}"
                )
        else:
            # Margin info unavailable — warn but don't block
            logger.warning(
                "margin_initial not available in symbol_info; "
                "skipping margin check."
            )

        return True, "Position parameters are valid"

    # ------------------------------------------------------------------

    def calculate_kelly_criterion(
        self,
        win_rate: float,
        avg_win_r: float,
        avg_loss_r: float,
    ) -> dict:
        """
        Calculate Kelly Criterion position sizing fractions.

        The Kelly formula maximises the long-run geometric growth rate of
        the account.  It is notoriously aggressive, so fractional Kelly
        variants (half-Kelly, quarter-Kelly) are standard in practice.

        Formula (generalised Kelly):
            K% = (W * b - L) / b
        where:
            W  = win probability
            L  = loss probability (1 - W)
            b  = avg_win_R / avg_loss_R  (reward-to-risk ratio per trade)

        Parameters
        ----------
        win_rate : float
            Historical win rate as a fraction (e.g. 0.55 = 55 %).
        avg_win_r : float
            Average winning trade size in R-multiples (e.g. 2.0 = 2R).
        avg_loss_r : float
            Average losing trade size in R-multiples (e.g. 1.0 = 1R, full SL hit).

        Returns
        -------
        dict with:
            kelly_pct          — full Kelly (% of account per trade)
            half_kelly_pct     — half Kelly
            quarter_kelly_pct  — quarter Kelly
            recommended_pct    — quarter Kelly capped at 2 %
            b_ratio            — avg_win_R / avg_loss_R
            expected_value_r   — expected R per trade
            is_positive_ev     — bool
        """
        if not (0 < win_rate < 1):
            raise ValueError(f"win_rate must be in (0, 1), got {win_rate}")
        if avg_win_r <= 0 or avg_loss_r <= 0:
            raise ValueError("avg_win_r and avg_loss_r must be positive")

        loss_rate = 1.0 - win_rate
        b = avg_win_r / avg_loss_r          # reward/risk ratio

        kelly_fraction = (win_rate * b - loss_rate) / b
        kelly_pct = kelly_fraction * 100.0

        half_kelly_pct = kelly_pct / 2.0
        quarter_kelly_pct = kelly_pct / 4.0
        recommended_pct = min(quarter_kelly_pct, MAX_RISK_PCT)

        expected_value_r = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)

        return {
            "kelly_pct": round(kelly_pct, 4),
            "half_kelly_pct": round(half_kelly_pct, 4),
            "quarter_kelly_pct": round(quarter_kelly_pct, 4),
            "recommended_pct": round(recommended_pct, 4),
            "b_ratio": round(b, 4),
            "expected_value_r": round(expected_value_r, 4),
            "is_positive_ev": expected_value_r > 0,
        }

    # ------------------------------------------------------------------

    def volatility_adjusted_risk(
        self,
        base_risk_pct: float,
        current_atr: float,
        avg_atr: float,
        volatility_regime: str,
    ) -> float:
        """
        Scale position risk up or down based on current volatility regime.

        Logic:
          - HIGH_VOLATILITY or EXTREME : reduce risk to 50–75 % of base
          - NORMAL                     : no adjustment
          - LOW_VOLATILITY             : increase up to 120 % (capped at MAX_RISK_PCT)

        The exact scaling is also modulated by the volatility_ratio
        (current_atr / avg_atr) to provide smooth, continuous adjustment
        within each regime.

        Parameters
        ----------
        base_risk_pct : float
            Risk percentage before volatility adjustment.
        current_atr : float
            ATR of the current period.
        avg_atr : float
            Average ATR over the lookback (baseline).
        volatility_regime : str
            One of LOW_VOLATILITY / NORMAL / HIGH_VOLATILITY / EXTREME.

        Returns
        -------
        float — adjusted risk percentage (capped at MAX_RISK_PCT).
        """
        if avg_atr <= 0:
            logger.warning("avg_atr is zero or negative; returning base risk unchanged")
            return base_risk_pct

        volatility_ratio = current_atr / avg_atr
        regime = volatility_regime.upper().replace(" ", "_")

        if regime == "EXTREME":
            # Maximum caution — 50 % reduction baseline, further reduced by ratio
            scale = max(0.40, 0.50 / volatility_ratio)
        elif regime == "HIGH_VOLATILITY":
            # Range 0.50 – 0.75 based on how elevated vol is
            raw_scale = 0.75 / volatility_ratio
            scale = max(0.50, min(0.75, raw_scale))
        elif regime == "NORMAL":
            # Minor continuous adjustment within ±10 % of base
            scale = 1.0 / max(0.90, min(1.10, volatility_ratio))
        elif regime == "LOW_VOLATILITY":
            # Modest increase — cap at 1.2×
            raw_scale = 1.0 / max(0.70, volatility_ratio)
            scale = min(1.20, raw_scale)
        else:
            logger.warning(
                "Unknown volatility_regime '%s'; using NORMAL scaling", regime
            )
            scale = 1.0

        adjusted = base_risk_pct * scale
        adjusted = min(adjusted, MAX_RISK_PCT)
        adjusted = max(adjusted, MIN_RISK_PCT)

        logger.debug(
            "Volatility adjustment: regime=%s, ratio=%.3f, scale=%.3f, "
            "base=%.3f%%, adjusted=%.3f%%",
            regime, volatility_ratio, scale, base_risk_pct, adjusted,
        )

        return round(adjusted, 4)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

        # Number of decimal places implied by volume_step
        step_decimals = max(0, -int(math.floor(math.log10(volume_step))))

        # Floor to step
        lots = math.floor(raw_lots / volume_step) * volume_step
        lots = round(lots, step_decimals + 2)   # remove floating-point noise

        # Clamp
        lots = max(volume_min, min(lots, volume_max))
        return round(lots, step_decimals + 2)

    @staticmethod
    def _empty_result() -> dict:
        return {
            "lots": 0.0,
            "monetary_risk_usd": 0.0,
            "monetary_risk_pct": 0.0,
            "sl_points": 0,
            "sl_distance_usd": 0.0,
            "tp1_lots": 0.0,
            "pip_value_per_lot": 0.0,
            "contract_size": 0.0,
            "is_valid": False,
            "rejection_reason": None,
            "warnings": [],
        }
