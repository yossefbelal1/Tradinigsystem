"""
core/data/symbol_specs.py
=========================
Universal Broker-Specific Symbol Specification Handler & Risk Mapping.
Supports all asset classes (Forex, Metals, Indices, Commodities, Crypto, Equities)
dynamically via InstrumentSpec and InstrumentDiscovery.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Tuple

from trading_system.core.data.instrument_spec import (
    AssetClass,
    InstrumentDiscovery,
    InstrumentSpec,
    OFFLINE_SPECS_CATALOG,
)

logger = logging.getLogger(__name__)

# Standard fallback defaults for Gold (XAUUSD) when offline/demo
DEFAULT_XAUUSD_SPECS: dict[str, Any] = OFFLINE_SPECS_CATALOG["XAUUSD"]


class SymbolSpecs:
    """
    Manages and parses broker symbol specifications, point/pip conversions,
    and monetary risk mappings for any financial instrument on MetaTrader 5.
    """

    def __init__(
        self,
        raw_specs: Optional[dict[str, Any]] = None,
        symbol: str = "XAUUSD",
    ):
        self._symbol = symbol
        if raw_specs and "symbol" in raw_specs:
            self._symbol = raw_specs["symbol"]

        if raw_specs:
            self._spec = InstrumentDiscovery.from_mt5_symbol_info(self._symbol, raw_specs)
        else:
            self._spec = InstrumentDiscovery.get_fallback_spec(self._symbol)

    def update(self, raw_specs: dict[str, Any]) -> None:
        """Update active symbol specifications from an MT5 symbol info dict."""
        sym = raw_specs.get("symbol", self._symbol)
        self._symbol = sym
        self._spec = InstrumentDiscovery.from_mt5_symbol_info(sym, raw_specs)
        logger.debug("SymbolSpecs updated for %s", sym)

    @property
    def instrument_spec(self) -> InstrumentSpec:
        """Return the underlying InstrumentSpec object."""
        return self._spec

    @property
    def specs(self) -> dict[str, Any]:
        """Return specifications as a dictionary."""
        return {
            "symbol": self._spec.symbol,
            "broker_symbol": self._spec.broker_symbol,
            "asset_class": self._spec.asset_class.value,
            "digits": self._spec.digits,
            "point": self._spec.point,
            "tick_size": self._spec.tick_size,
            "tick_value": self._spec.tick_value,
            "contract_size": self._spec.contract_size,
            "volume_min": self._spec.volume_min,
            "volume_max": self._spec.volume_max,
            "volume_step": self._spec.volume_step,
            "currency_base": self._spec.currency_base,
            "currency_profit": self._spec.currency_profit,
            "currency_margin": self._spec.currency_margin,
            "spread": self._spec.spread,
            "bid": self._spec.bid,
            "ask": self._spec.ask,
            "description": self._spec.description,
        }

    @property
    def symbol(self) -> str:
        return self._spec.symbol

    @property
    def asset_class(self) -> AssetClass:
        return self._spec.asset_class

    @property
    def point(self) -> float:
        return self._spec.point

    @property
    def digits(self) -> int:
        return self._spec.digits

    @property
    def tick_size(self) -> float:
        return self._spec.tick_size

    @property
    def tick_value(self) -> float:
        return self._spec.tick_value

    @property
    def contract_size(self) -> float:
        return self._spec.contract_size

    @property
    def volume_min(self) -> float:
        return self._spec.volume_min

    @property
    def volume_max(self) -> float:
        return self._spec.volume_max

    @property
    def volume_step(self) -> float:
        return self._spec.volume_step

    @property
    def currency_profit(self) -> str:
        return self._spec.currency_profit

    @property
    def currency_base(self) -> str:
        return self._spec.currency_base

    def price_to_points(self, price_diff: float) -> int:
        """Convert a floating price difference to integer broker points."""
        return self._spec.price_to_points(price_diff)

    def points_to_price(self, points: int | float) -> float:
        """Convert broker points to floating price value."""
        return self._spec.points_to_price(points)

    def calculate_pip_value(
        self,
        symbol_info: Optional[dict[str, Any]] = None,
        account_currency: str = "USD",
        exchange_rate_to_account: float = 1.0,
    ) -> float:
        """
        Calculate value of 1 point (or tick) per 1.0 standard lot in account currency.
        Universal across all asset classes.
        """
        if symbol_info:
            tick_sz = float(symbol_info.get("trade_tick_size", symbol_info.get("tick_size", self.tick_size)))
            tick_val = float(symbol_info.get("trade_tick_value", symbol_info.get("tick_value", self.tick_value)))
            pt_val = float(symbol_info.get("point", self.point))
            profit_curr = str(symbol_info.get("currency_profit", self.currency_profit)).upper()
        else:
            tick_sz = self.tick_size
            tick_val = self.tick_value
            pt_val = self.point
            profit_curr = self.currency_profit.upper()

        if tick_sz > 0:
            value_per_point_in_profit_curr = tick_val * (pt_val / tick_sz)
        else:
            value_per_point_in_profit_curr = tick_val

        acct_curr = account_currency.upper()
        if profit_curr == acct_curr or exchange_rate_to_account == 1.0:
            return value_per_point_in_profit_curr
        else:
            return value_per_point_in_profit_curr * exchange_rate_to_account

    def calculate_monetary_risk(
        self,
        lots: float,
        sl_points: int,
        account_currency: str = "USD",
        exchange_rate_to_account: float = 1.0,
    ) -> float:
        """
        Compute monetary risk in account currency for given lots and stop loss points.
        Risk = Lots * Points * ValuePerPoint
        """
        point_val = self.calculate_pip_value(
            account_currency=account_currency,
            exchange_rate_to_account=exchange_rate_to_account,
        )
        return round(lots * sl_points * point_val, 2)

    def calculate_position_size(
        self,
        risk_usd: float,
        sl_points: int,
        account_currency: str = "USD",
        exchange_rate_to_account: float = 1.0,
    ) -> tuple[float, Optional[str]]:
        """
        Calculate lots given dollar risk and stop loss points.
        Returns: (lots, rejection_reason_or_none)
        """
        if risk_usd <= 0:
            return 0.0, "Risk amount must be greater than zero."
        if sl_points <= 0:
            return 0.0, "Stop loss points must be greater than zero."

        point_val = self.calculate_pip_value(
            account_currency=account_currency,
            exchange_rate_to_account=exchange_rate_to_account,
        )

        if point_val <= 0:
            return 0.0, "Point value calculation yielded zero or negative value."

        raw_lots = risk_usd / (sl_points * point_val)

        step = self.volume_step
        min_vol = self.volume_min
        max_vol = self.volume_max

        # Round down to nearest volume step to never exceed intended risk
        steps = math.floor(raw_lots / step)
        stepped_lots = round(steps * step, 8)

        if stepped_lots < min_vol:
            return 0.0, (
                f"Required lots ({raw_lots:.4f}) is below broker minimum ({min_vol:.2f}). "
                f"Stop loss is too wide or risk budget (${risk_usd:.2f}) is too small."
            )

        if stepped_lots > max_vol:
            stepped_lots = max_vol
            logger.warning("Position size clamped to broker max volume: %.2f", max_vol)

        return stepped_lots, None
