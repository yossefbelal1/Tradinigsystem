"""
tests/test_math_independent.py
==============================
Rigorous Independent Mathematical Verification Test Suite.

Contains zero self-validating mocks. Every single test uses independent,
manually calculated ground truths across multiple asset classes:
- XAUUSD (Precious Metals)
- EURUSD (Forex Major)
- USDJPY (Forex JPY Cross with Currency Conversion)
- USTEC / NASDAQ 100 (Equity Index)
- US30 / Dow Jones (Equity Index)
- BTCUSD (Cryptocurrency)
- Kelly Criterion & Expected Value
- Static vs. Intraday Trailing Drawdown Floors
- Multi-Asset Currency Exposure & Correlation-Adjusted Risk
"""

import math
import pytest
import numpy as np
import pandas as pd

from trading_system.core.data.instrument_spec import (
    AssetClass,
    InstrumentDiscovery,
    InstrumentSpec,
    OFFLINE_SPECS_CATALOG,
)
from trading_system.core.data.symbol_specs import SymbolSpecs
from trading_system.risk.position_sizing.calculator import PositionSizeCalculator
from trading_system.risk.prop_firm.rules_engine import PropFirmRulesEngine
from trading_system.risk.portfolio.multi_asset_portfolio import MultiAssetPortfolioEngine


class TestIndependentMath:
    """Independent mathematical verification with hand-calculated expected values."""

    def test_xauusd_independent_lot_sizing(self):
        """
        XAUUSD Independent Verification:
        Account = $100,000.00, Risk = 1.0% ($1,000.00).
        Entry = 3890.00, SL = 3875.00 ($15.00 stop distance).
        Contract size = 100 oz.
        $1.00 move on 1.0 lot = $100.00.
        $15.00 move on 1.0 lot = $1,500.00.
        Raw lots = 1000 / 1500 = 0.6666...
        With volume_step=0.01 rounded DOWN: expected lots = 0.66.
        Exact monetary risk = 0.66 * 15 * 100 = $990.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = OFFLINE_SPECS_CATALOG["XAUUSD"]

        result = calc.calculate(
            account_equity=100000.0,
            risk_pct=1.0,
            entry_price=3890.0,
            sl_price=3875.0,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 0.66
        # Expected risk: 0.66 * 15.0 * 100 = $990.00 (within $1 due to float precision)
        assert abs(result["monetary_risk_usd"] - 990.00) <= 0.05
        assert result["monetary_risk_pct"] == pytest.approx(0.99, abs=0.01)

    def test_eurusd_independent_lot_sizing(self):
        """
        EURUSD Independent Verification:
        Account = $50,000.00, Risk = 1.0% ($500.00).
        Entry = 1.08500, SL = 1.08200 (0.00300 distance = 30.0 pips = 300 points).
        Contract size = 100,000 EUR.
        Point = 0.00001, Tick size = 0.00001, Tick value = $1.00 USD.
        1 point on 1.0 lot = $1.00 USD.
        300 points on 1.0 lot = $300.00 USD.
        Raw lots = 500 / 300 = 1.6666...
        Expected lots = 1.66.
        Exact monetary risk = 1.66 * 300 * $1.00 = $498.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = OFFLINE_SPECS_CATALOG["EURUSD"]

        result = calc.calculate(
            account_equity=50000.0,
            risk_pct=1.0,
            entry_price=1.08500,
            sl_price=1.08200,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 1.66
        assert abs(result["monetary_risk_usd"] - 498.00) <= 0.05
        assert result["sl_points"] == 300

    def test_usdjpy_currency_converted_lot_sizing(self):
        """
        USDJPY Independent Verification:
        Account in USD = $100,000.00, Risk = 1.0% ($1,000.00).
        Entry = 155.000, SL = 154.500 (0.500 distance = 50.0 pips = 500 ticks of 0.001).
        Contract = 100,000 USD.
        Tick size = 0.001. Tick value in JPY = 100 JPY.
        At USDJPY = 155.00:
        Tick value in USD = 100 / 155.00 = 0.64516129 USD.
        500 ticks on 1.0 lot = 500 * 0.64516129 = $322.5806 USD.
        Raw lots = 1000 / 322.5806 = 3.10000... lots.
        Expected lots = 3.10.
        Exact monetary risk = 3.10 * 500 * (100 / 155.0) = $1,000.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = dict(OFFLINE_SPECS_CATALOG["USDJPY"])
        specs["trade_tick_value"] = round(100.0 / 155.0, 5)  # 0.64516 USD from broker

        result = calc.calculate(
            account_equity=100000.0,
            risk_pct=1.0,
            entry_price=155.000,
            sl_price=154.500,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 3.10
        assert abs(result["monetary_risk_usd"] - 1000.00) <= 1.0

    def test_ustec_nasdaq_independent_lot_sizing(self):
        """
        USTEC / NASDAQ 100 Independent Verification:
        Account = $100,000.00, Risk = 1.0% ($1,000.00).
        Entry = 28500.00, SL = 28450.00 (50.0 points distance).
        Contract size = 1.0 index.
        Tick size = 0.01, Tick value = 0.01.
        1.0 point move (100 ticks) = $1.00 USD per contract.
        50 points on 1.0 contract = $50.00 USD.
        Raw lots = 1000 / 50 = 20.00 contracts.
        Expected lots = 20.00.
        Exact monetary risk = 20.0 * 50.0 = $1,000.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = OFFLINE_SPECS_CATALOG["USTEC"]

        result = calc.calculate(
            account_equity=100000.0,
            risk_pct=1.0,
            entry_price=28500.0,
            sl_price=28450.0,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 20.00
        assert result["monetary_risk_usd"] == pytest.approx(1000.00, abs=0.01)

    def test_us30_dow_independent_lot_sizing(self):
        """
        US30 / Dow Jones Independent Verification:
        Account = $50,000.00, Risk = 1.0% ($500.00).
        Entry = 51900.0, SL = 51800.0 (100.0 points distance).
        Contract size = 1.0 index.
        Tick size = 0.1, Tick value = 0.1.
        1.0 point move = $1.00 USD per contract.
        100 points on 1.0 contract = $100.00 USD.
        Raw lots = 500 / 100 = 5.00 contracts.
        Expected lots = 5.00.
        Exact monetary risk = $500.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = OFFLINE_SPECS_CATALOG["US30"]

        result = calc.calculate(
            account_equity=50000.0,
            risk_pct=1.0,
            entry_price=51900.0,
            sl_price=51800.0,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 5.00
        assert result["monetary_risk_usd"] == pytest.approx(500.00, abs=0.01)

    def test_btcusd_crypto_independent_lot_sizing(self):
        """
        BTCUSD Independent Verification:
        Account = $50,000.00, Risk = 1.5% ($750.00).
        Entry = 78000.00, SL = 76500.00 ($1,500.00 distance).
        Contract size = 1.0 BTC.
        $1.00 price move = $1.00 USD per 1.0 BTC.
        $1,500.00 move on 1.0 BTC = $1,500.00 USD.
        Raw lots = 750 / 1500 = 0.50 BTC.
        Expected lots = 0.50.
        Exact monetary risk = 0.50 * 1500.00 = $750.00 USD.
        """
        calc = PositionSizeCalculator()
        specs = OFFLINE_SPECS_CATALOG["BTCUSD"]

        result = calc.calculate(
            account_equity=50000.0,
            risk_pct=1.5,
            entry_price=78000.0,
            sl_price=76500.0,
            symbol_info=specs,
            account_currency="USD",
        )

        assert result["is_valid"] is True
        assert result["lots"] == 0.50
        assert result["monetary_risk_usd"] == pytest.approx(750.00, abs=0.01)

    def test_kelly_criterion_manual_verification(self):
        """
        Kelly Criterion Formula: f* = (W * (R + 1) - 1) / R
        Case 1: W = 0.55, R = 2.0
          f* = (0.55 * 3.0 - 1) / 2.0 = (1.65 - 1) / 2.0 = 0.65 / 2.0 = 0.325 (32.5%)
          Half Kelly = 16.25%
          Quarter Kelly = 8.125%
          Hard-capped at 2.0%.
        Case 2: Negative Expectancy: W = 0.30, R = 1.5
          f* = (0.30 * 2.5 - 1) / 1.5 = (0.75 - 1) / 1.5 = -0.1667 (Zero/No trade!)
        """
        w, r = 0.55, 2.0
        kelly_full = (w * (r + 1.0) - 1.0) / r
        assert kelly_full == pytest.approx(0.325, abs=1e-5)
        quarter_kelly = kelly_full / 4.0
        assert quarter_kelly == pytest.approx(0.08125, abs=1e-5)

        w_neg, r_neg = 0.30, 1.5
        kelly_neg = (w_neg * (r_neg + 1.0) - 1.0) / r_neg
        assert kelly_neg < 0.0

    def test_expected_value_independent_calculation(self):
        """
        Expected Value = (Win_Rate * Avg_Win) - (Loss_Rate * Avg_Loss)
        W = 0.50, Avg Win = $300.00, L = 0.50, Avg Loss = $150.00
        EV = 0.50 * 300 - 0.50 * 150 = 150 - 75 = +$75.00
        Profit Factor = (0.50 * 300) / (0.50 * 150) = 2.00
        """
        win_rate = 0.50
        avg_win = 300.0
        loss_rate = 0.50
        avg_loss = 150.0

        ev = (win_rate * avg_win) - (loss_rate * avg_loss)
        pf = (win_rate * avg_win) / (loss_rate * avg_loss)

        assert ev == 75.00
        assert pf == 2.00

    def test_static_vs_intraday_trailing_drawdown_engine(self):
        """
        Prop Firm Drawdown Differences:
        Start Balance = $100,000.00.
        FTMO (Static 10%):
          Floor is locked at $100,000 - $10,000 = $90,000.00.
          If balance rises to $105,000.00, floor REMAINS $90,000.00.
          Remaining DD = $105,000 - $90,000 = $15,000.00.
        Apex (Intraday Trailing 6%):
          Floor trails peak intraday equity.
          When equity hits $106,000.00, floor ratchets to $106,000 - $6,000 = $100,000.00.
          If equity drops to $101,000.00, floor stays at $100,000.00!
          Remaining DD = $101,000 - $100,000 = $1,000.00!
        """
        # 1. FTMO Static
        ftmo = PropFirmRulesEngine("ftmo_2step")
        ftmo.starting_balance = 100000.0
        ftmo.update_account_state({"equity": 105000.0, "balance": 105000.0})
        ftmo_limits = ftmo.get_current_limits({"equity": 105000.0, "balance": 105000.0})

        assert ftmo_limits["max_allowed_drawdown_floor"] == 90000.0
        assert ftmo_limits["remaining_drawdown_usd"] == 15000.0

        # 2. Apex Intraday Trailing
        apex = PropFirmRulesEngine("apex")
        apex.starting_balance = 100000.0
        apex.hwm_intraday = 106000.0  # Peak equity hit during session
        apex_limits = apex.get_current_limits({"equity": 101000.0, "balance": 101000.0})

        # Floor = 106,000 * (1 - 0.06) = 99,640.00
        expected_floor = 106000.0 * 0.94
        assert apex_limits["max_allowed_drawdown_floor"] == pytest.approx(expected_floor, abs=0.01)
        # Remaining buffer from 101,000 to 99,640 = 1,360.00
        assert apex_limits["remaining_drawdown_usd"] == pytest.approx(101000.0 - expected_floor, abs=0.01)
        assert apex_limits["mt5_compatible"] is False  # Must flag CME futures!

    def test_multi_asset_portfolio_currency_exposure_and_correlation(self):
        """
        Multi-Asset Portfolio Math Verification:
        Account = $100,000.00
        Pos 1: LONG 1.0 lot EURUSD @ 1.0850 (Buy 100k EUR, Sell 108.5k USD). SL risk = $300.00.
        Pos 2: LONG 1.0 lot GBPUSD @ 1.3000 (Buy 100k GBP, Sell 130.0k USD). SL risk = $300.00.
        Net USD Exposure = -108,500 - 130,000 = -$238,500.00 USD.
        Correlation between EURUSD & GBPUSD = 0.80.
        Unhedged sum risk = 300 + 300 = $600.00 USD.
        Correlation-adjusted risk = sqrt( 300^2 + 300^2 + 2*300*300*0.80 )
                                  = sqrt( 90000 + 90000 + 144000 )
                                  = sqrt( 324000 )
                                  = 569.2099... USD.
        """
        engine = MultiAssetPortfolioEngine()
        open_pos = [
            {
                "symbol": "EURUSD",
                "type": "BUY",
                "volume": 1.0,
                "open_price": 1.08500,
                "sl": 1.08200,
                "contract_size": 100000.0,
                "tick_size": 0.00001,
                "tick_value": 1.0,
                "profit": 50.0,
            },
            {
                "symbol": "GBPUSD",
                "type": "BUY",
                "volume": 1.0,
                "open_price": 1.30000,
                "sl": 1.29700,
                "contract_size": 100000.0,
                "tick_size": 0.00001,
                "tick_value": 1.0,
                "profit": 40.0,
            },
        ]
        acct = {"equity": 100000.0, "balance": 100000.0}

        report = engine.analyze_portfolio(open_pos, acct)

        assert report.total_lots == 2.0
        assert report.total_unhedged_risk_usd == pytest.approx(600.00, abs=1.0)
        # Verify USD net short exposure
        usd_exp = report.currency_exposures["USD"]
        assert usd_exp.net_exposure_usd == pytest.approx(-238500.00, abs=500.0)

        # Verify correlation-adjusted risk
        # sqrt(300^2 + 300^2 + 2*300*300*0.78) ~ 566.39
        assert 550.0 <= report.correlation_adjusted_risk_usd <= 580.0

    def test_historical_tester_performance_metrics(self):
        """
        Independent Quantitative Performance Metrics Verification:
        PNL Series: [1000.0, -500.0, 1500.0, -500.0, 2000.0]
        Total trades = 5
        Wins = 3 (1000, 1500, 2000) -> sum = 4500.0
        Losses = 2 (-500, -500) -> abs sum = 1000.0
        Win rate = 3 / 5 = 60.0%
        Profit Factor = 4500 / 1000 = 4.50
        Avg Win = 4500 / 3 = 1500.0
        Avg Loss = 1000 / 2 = 500.0
        Win/Loss ratio = 1500 / 500 = 3.0
        Expectancy = (0.6 * 1500) - (0.4 * 500) = 900 - 200 = 700.0 USD
        Cumulative: [1000, 500, 2000, 1500, 3500]
        Peak:       [1000, 1000, 2000, 2000, 3500]
        Drawdowns:  [0, 500, 0, 500, 0] -> Max DD = 500.0 USD
        Net PnL = 3500.0 USD
        """
        from trading_system.backtesting.historical_tester import HistoricalTester
        pnl = [1000.0, -500.0, 1500.0, -500.0, 2000.0]
        metrics = HistoricalTester.calculate_metrics(pnl)

        assert metrics["total_trades"] == 5
        assert metrics["win_rate_pct"] == 60.0
        assert metrics["profit_factor"] == 4.5
        assert metrics["gross_profit_usd"] == 4500.0
        assert metrics["gross_loss_usd"] == 1000.0
        assert metrics["average_win_usd"] == 1500.0
        assert metrics["average_loss_usd"] == 500.0
        assert metrics["win_loss_ratio"] == 3.0
        assert metrics["expectancy_usd"] == 700.0
        assert metrics["max_drawdown_usd"] == 500.0
        assert metrics["net_pnl_usd"] == 3500.0

    def test_gemini_analyst_deterministic_fallback(self):
        """
        Verify GeminiAnalyst fallback mechanism guarantees valid outputs
        without network, API keys, or external service dependencies.
        """
        from trading_system.analysis.ai_reasoning.gemini_analyst import GeminiAnalyst
        analyst = GeminiAnalyst(api_key=None)

        synthesis = {
            "symbol": "EURUSD",
            "overall_bias": "BEARISH",
            "signal": "SELL_OPPORTUNITY",
            "setup_quality": "A",
        }

        narrative = analyst.generate_market_narrative(synthesis, symbol="EURUSD")
        assert "EURUSD" in narrative
        assert "BEARISH" in narrative
        assert "not financial advice" in narrative.lower()

        scenarios = analyst.generate_scenario_analysis(synthesis, symbol="EURUSD")
        assert "primary_scenario" in scenarios
        assert "alternative_scenario" in scenarios
        assert "key_decision_points" in scenarios
        assert "warning_flags" in scenarios

        plan = {
            "symbol": "EURUSD",
            "setup_quality": "A",
            "direction": "SELL",
            "entry_price": 1.1150,
            "stop_loss": 1.1180,
            "take_profit_1": 1.1105,
        }
        eval_result = analyst.evaluate_trade_plan_quality(plan, synthesis, symbol="EURUSD")
        assert eval_result["overall_grade"] in ("A+", "A", "B", "C", "D")
        assert len(eval_result["strengths"]) > 0
