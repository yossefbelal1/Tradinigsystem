"""
tests/test_position_sizing.py
=============================
Unit tests for XAUUSD Position Sizing, Monetary Risk, and Volatility Adjustment.
"""

import pytest
from trading_system.core.data.symbol_specs import SymbolSpecs, DEFAULT_XAUUSD_SPECS
from trading_system.risk.position_sizing.calculator import PositionSizeCalculator


def test_symbol_specs_points_conversion():
    specs = SymbolSpecs(DEFAULT_XAUUSD_SPECS)
    # $10.00 price difference in Gold with point=0.01 is 1000 points
    points = specs.price_to_points(10.0)
    assert points == 1000

    # 500 points = $5.00
    price_diff = specs.points_to_price(500)
    assert price_diff == 5.00


def test_calculate_pip_value():
    specs = SymbolSpecs(DEFAULT_XAUUSD_SPECS)
    # On 1.0 lot of 100oz Gold, a 1 point (0.01) move is $1.00 USD
    val = specs.calculate_pip_value()
    assert val == 1.0


def test_calculate_monetary_risk():
    specs = SymbolSpecs(DEFAULT_XAUUSD_SPECS)
    # 0.50 lots with 500 points SL ($5.00 move)
    # Risk = 0.50 * 500 * $1.00 = $250.00
    risk = specs.calculate_monetary_risk(lots=0.50, sl_points=500)
    assert risk == 250.00


def test_position_sizing_standard_calculation():
    specs = SymbolSpecs(DEFAULT_XAUUSD_SPECS)
    # $100,000 account, 1% risk = $1,000 risk budget
    # Entry: $2700.00, SL: $2690.00 (1000 points = $10.00)
    # Required lots = $1000 / (1000 * $1.00) = 1.00 lot
    lots, reason = specs.calculate_position_size(risk_usd=1000.0, sl_points=1000)
    assert reason is None
    assert lots == 1.00


def test_position_sizing_minimum_rejection():
    specs = SymbolSpecs(DEFAULT_XAUUSD_SPECS)
    # Tiny risk budget ($0.50) with 1000 points SL would require 0.0005 lots, below min (0.01)
    lots, reason = specs.calculate_position_size(risk_usd=0.50, sl_points=1000)
    assert lots == 0.0
    assert reason is not None
    assert "below broker minimum" in reason


def test_position_size_calculator_class():
    calc = PositionSizeCalculator()
    symbol_info = DEFAULT_XAUUSD_SPECS

    res = calc.calculate(
        account_equity=100000.0,
        risk_pct=1.0,
        entry_price=2700.0,
        sl_price=2690.0,
        symbol_info=symbol_info,
    )

    assert res["is_valid"] is True
    assert res["lots"] == 1.00
    assert res["monetary_risk_usd"] == 1000.0
