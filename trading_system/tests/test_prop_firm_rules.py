"""
tests/test_prop_firm_rules.py
=============================
Unit tests for Prop Firm Drawdown Calculations (Static vs EOD Trailing vs Intraday Trailing).
"""

import pytest
from trading_system.risk.prop_firm.rules_engine import PropFirmRulesEngine
from trading_system.risk.trade_manager.trade_plan import TradePlan


def test_static_drawdown_floor_immutability():
    """Verify that under static drawdown, profits increase the buffer and floor never moves."""
    engine = PropFirmRulesEngine("ftmo_2step")
    # Starting balance $100k, 10% max static DD -> floor is $90,000
    acct_start = {"balance": 100000.0, "equity": 100000.0}
    engine.update_account_state(acct_start)

    limits1 = engine.get_current_limits(acct_start)
    assert limits1["max_allowed_drawdown_floor"] == 90000.0
    assert limits1["remaining_drawdown_usd"] == 10000.0

    # Account gains $5,000 profit (equity = $105k)
    acct_profit = {"balance": 105000.0, "equity": 105000.0}
    engine.update_account_state(acct_profit)
    limits2 = engine.get_current_limits(acct_profit)

    # Floor must STILL be $90,000.00
    assert limits2["max_allowed_drawdown_floor"] == 90000.0
    # Remaining buffer is now $15,000.00
    assert limits2["remaining_drawdown_usd"] == 15000.0


def test_intraday_trailing_drawdown_ratchet():
    """Verify that intraday trailing ratchets the floor upwards with floating equity peaks."""
    engine = PropFirmRulesEngine("apex")  # Apex uses intraday trailing
    max_dd_pct = float(engine.config.get("max_drawdown_pct", 6.0))

    acct_start = {"balance": 100000.0, "equity": 100000.0}
    engine.update_account_state(acct_start)

    limits1 = engine.get_current_limits(acct_start)
    expected_floor1 = 100000.0 * (1.0 - (max_dd_pct / 100.0))
    assert limits1["max_allowed_drawdown_floor"] == pytest.approx(expected_floor1, abs=0.01)

    # Floating profit spikes to $104,000 (even if unrealized)
    acct_spike = {"balance": 100000.0, "equity": 104000.0}
    engine.update_account_state(acct_spike)
    limits2 = engine.get_current_limits(acct_spike)

    # Floor ratcheted up: 104,000 * (1 - max_dd_pct / 100)
    expected_floor2 = 104000.0 * (1.0 - (max_dd_pct / 100.0))
    assert limits2["max_allowed_drawdown_floor"] == pytest.approx(expected_floor2, abs=0.01)


def test_trade_rejection_on_daily_limit_proximity():
    """Ensure trades that exceed remaining daily risk are cleanly rejected."""
    engine = PropFirmRulesEngine("ftmo_2step")
    acct = {"balance": 100000.0, "equity": 96000.0}  # Already down $4,000 today
    engine.update_account_state(acct)

    plan = TradePlan(
        entry_price=2700.0,
        stop_loss=2690.0,
        monetary_risk_usd=1200.0,  # $1,200 risk when only $1,000 daily room left
        risk_pct_of_equity=1.2,
    )

    is_valid, violations = engine.validate_new_trade(plan, acct)
    assert is_valid is False
    assert any("remaining daily buffer" in v for v in violations)
