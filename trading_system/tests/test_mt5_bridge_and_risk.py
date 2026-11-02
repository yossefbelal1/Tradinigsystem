"""
trading_system/tests/test_mt5_bridge_and_risk.py
================================================
Comprehensive Integration Tests for:
1. Native MT5 Active Chart IPC Bridge (serialization, request processing, outbox files).
2. Strict Market Data Integrity gating (MT5_LIVE vs OFFLINE_DISCONNECTED).
3. Dynamic Quantitative Risk Management (order_calc_profit, commissions, spreads, slippage).
4. Prop firm dynamic baseline initialization & drawdown protection.
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest

from trading_system.core.data.data_integrity import DataIntegrityManager, DataSourceState
from trading_system.core.data.instrument_spec import OFFLINE_SPECS_CATALOG, InstrumentDiscovery
from trading_system.core.ipc.bridge_protocol import (
    AnalysisResponseMessage,
    ChartContextMessage,
    SRLevelPayload,
    TradeBlueprintPayload,
    ZonePayload,
)
from trading_system.core.ipc.mt5_bridge_server import MT5BridgeServer, get_mt5_common_path
from trading_system.risk.position_sizing.calculator import PositionSizeCalculator
from trading_system.risk.prop_firm.rules_engine import PropFirmRulesEngine
from trading_system.risk.trade_manager.trade_plan import TradePlan


class TestMT5BridgeAndRiskIntegration:
    """Test suite verifying MT5 bridge communication, data integrity, and risk controls."""

    def test_ipc_protocol_serialization_deserialization(self):
        """Verify ChartContextMessage and AnalysisResponseMessage round-trip cleanly."""
        msg = ChartContextMessage(
            chart_id=133281,
            symbol="XAUUSD",
            period="H1",
            period_minutes=60,
            bid=2745.20,
            ask=2745.55,
            spread_points=35,
            digits=2,
            timestamp="2026-11-02T02:00:00Z",
            action="REQUEST_ANALYSIS",
            auto_sync=True,
        )

        msg_dict = msg.to_dict()
        assert msg_dict["chart_id"] == 133281
        assert msg_dict["symbol"] == "XAUUSD"
        assert msg_dict["action"] == "REQUEST_ANALYSIS"

        reconstructed = ChartContextMessage.from_dict(msg_dict)
        assert reconstructed.chart_id == 133281
        assert reconstructed.symbol == "XAUUSD"
        assert reconstructed.bid == 2745.20
        assert reconstructed.spread_points == 35

        # Test AnalysisResponseMessage
        resp = AnalysisResponseMessage(
            chart_id=133281,
            symbol="XAUUSD",
            period="H1",
            timestamp="2026-11-02T02:00:01Z",
            overall_bias="BULLISH",
            bias_strength=0.85,
            levels=[{"price": 2720.0, "type": "SUPPORT", "timeframe": "D1"}],
            zones=[{"type": "DEMAND", "top": 2735.0, "bottom": 2725.0, "state": "FRESH", "timeframe": "H4"}],
            trade_plan={"direction": "BUY", "entry_price": 2740.0, "stop_loss": 2730.0, "is_valid": True},
            candle_expectation="Bullish expansion continuation",
            status="SUCCESS",
        )

        json_str = resp.to_json()
        data = json.loads(json_str)
        assert data["overall_bias"] == "BULLISH"
        assert len(data["levels"]) == 1
        assert len(data["zones"]) == 1
        assert data["trade_plan"]["entry_price"] == 2740.0

    def test_bridge_server_request_processing_and_outbox(self):
        """Verify MT5BridgeServer reads inbox JSON and generates outbox analysis file."""
        server = MT5BridgeServer(prop_firm_name="ftmo_2step", enable_socket=False)

        # Create a test chart request in the inbox
        chart_id = 999999
        req_msg = ChartContextMessage(
            chart_id=chart_id,
            symbol="EURUSD",
            period="H1",
            period_minutes=60,
            bid=1.08500,
            ask=1.08515,
            spread_points=15,
            digits=5,
            timestamp="2026-11-02T02:00:00Z",
            action="REQUEST_ANALYSIS",
            auto_sync=True,
        )

        req_file = server.inbox / f"req_{chart_id}.json"
        req_file.write_text(json.dumps(req_msg.to_dict()), encoding="utf-8")

        # Process the file synchronously
        server._process_request_file(req_file)

        # Check that request was deleted from inbox
        assert not req_file.exists()

        # Check that response was written to outbox
        resp_file = server.outbox / f"analysis_EURUSD_{chart_id}.json"
        assert resp_file.exists()

        resp_content = json.loads(resp_file.read_text(encoding="utf-8"))
        assert resp_content["symbol"] == "EURUSD"
        assert resp_content["chart_id"] == chart_id
        assert resp_content["status"] == "SUCCESS"
        assert "overall_bias" in resp_content

        # Clean up test file
        resp_file.unlink(missing_ok=True)
        (server.outbox / "analysis_EURUSD.json").unlink(missing_ok=True)

    def test_strict_data_integrity_gating(self):
        """Verify data integrity transitions and safety gating of trade plans."""
        mgr = DataIntegrityManager()

        # Initial state is OFFLINE
        assert mgr.current_state == DataSourceState.OFFLINE_DISCONNECTED
        assert mgr.is_live is False
        assert mgr.can_formulate_live_trade_plan() is False

        # Transition to LIVE
        mgr.set_state(DataSourceState.MT5_LIVE, source_name="Exness-MT5Trial16")
        assert mgr.current_state == DataSourceState.MT5_LIVE
        assert mgr.is_live is True
        assert mgr.can_formulate_live_trade_plan() is True

        # Fallback to DEMO/SIMULATED should NOT allow live trade execution plans
        mgr.set_state(DataSourceState.DEMO_SIMULATED, source_name="SyntheticDemo")
        assert mgr.is_live is False
        assert mgr.can_formulate_live_trade_plan() is False

    def test_dynamic_risk_with_commissions_and_spread(self):
        """Verify position sizing accounts for commission, spread, and slippage when requested."""
        calc = PositionSizeCalculator(commission_per_lot_usd=7.00, slippage_points=5)
        specs = OFFLINE_SPECS_CATALOG["XAUUSD"]

        # Account: $100k, 1% risk = $1,000. Stop = $10.00 (1000 pts).
        # Loss per lot = 10 * 100 = $1,000.
        # Spread = 25 pts = $25/lot.
        # Commission = $7.00/lot.
        # Slippage = 5 pts = $5.00/lot.
        # Total cost per lot = 1000 + 25 + 7 + 5 = $1037.00.
        # Raw lots = 1000 / 1037 = 0.9643 -> rounded to 0.96 lots.
        res = calc.calculate(
            account_equity=100000.0,
            risk_pct=1.0,
            entry_price=2740.0,
            sl_price=2730.0,
            symbol_info=specs,
            spread_points=25,
            commission_per_lot=7.00,
            slippage_points=5,
        )

        assert res["is_valid"] is True
        assert res["lots"] == 0.96
        assert res["commission_cost_usd"] == round(0.96 * 7.00, 2)
        assert res["spread_cost_usd"] == round(0.96 * 25.00, 2)
        assert res["total_execution_risk_usd"] <= 1000.00  # Stays strictly inside $1,000 risk budget!

    def test_prop_firm_dynamic_baseline_initialization(self):
        """Verify prop firm engine dynamically initializes to any account balance."""
        engine = PropFirmRulesEngine("ftmo_2step")

        # Live account with arbitrary balance $432.39 (like current Exness test account)
        acct = {"balance": 432.39, "equity": 432.39}
        engine.update_account_state(acct)

        limits = engine.get_current_limits(acct)
        assert limits["starting_balance"] == 432.39
        # 10% max DD floor on $432.39 is $389.15
        assert limits["max_allowed_drawdown_floor"] == pytest.approx(389.15, abs=0.01)
        assert limits["is_breached"] is False
        assert limits["remaining_drawdown_usd"] == pytest.approx(43.24, abs=0.01)
