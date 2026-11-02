"""
tests/test_technical_analysis.py
================================
Unit tests for Market Structure, Support/Resistance, Supply/Demand, and Multi-Timeframe Synthesis.
"""

import numpy as np
import pandas as pd
import pytest

from trading_system.core.market_structure.swing_detector import SwingDetector
from trading_system.core.market_structure.trend_analyzer import TrendAnalyzer
from trading_system.core.classical_ta.support_resistance import SupportResistanceDetector
from trading_system.core.supply_demand.zone_detector import SupplyDemandDetector
from trading_system.core.supply_demand.zone_validator import ZoneValidator
from trading_system.core.mtf.conflict_detector import ConflictDetector
from trading_system.core.mtf.bias_synthesizer import BiasSynthesizer
from trading_system.risk.monte_carlo.simulator import MonteCarloSimulator


def generate_synthetic_ohlcv(n: int = 150, trend_slope: float = 0.5) -> pd.DataFrame:
    """Generate realistic trending OHLCV data for testing."""
    np.random.seed(42)
    t = pd.date_range("2026-01-01", periods=n, freq="1h")
    base = 2600.0 + np.cumsum(np.random.randn(n) * 2.0 + trend_slope)
    high = base + np.abs(np.random.randn(n) * 3.0) + 1.0
    low = base - np.abs(np.random.randn(n) * 3.0) - 1.0
    close = base + np.random.randn(n) * 1.5
    open_p = np.roll(close, 1)
    open_p[0] = base[0]
    volume = np.random.randint(500, 3000, size=n)

    return pd.DataFrame({
        "time": t,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "is_confirmed": True,
    })


def test_swing_detector_fractal():
    df = generate_synthetic_ohlcv(100)
    detector = SwingDetector()
    annotated = detector.detect_swings(df, order=4)

    assert "swing_high" in annotated.columns
    assert "swing_low" in annotated.columns

    # Highs and lows should be detected
    assert annotated["swing_high"].sum() > 0
    assert annotated["swing_low"].sum() > 0

    # Last `order` bars must never be marked as swing high/low (future confirmation constraint)
    assert not annotated["swing_high"].iloc[-4:].any()
    assert not annotated["swing_low"].iloc[-4:].any()


def test_trend_analyzer_uptrend():
    # Construct a clear higher-high, higher-low price series
    t = pd.date_range("2026-01-01", periods=100, freq="1h")
    trend = np.linspace(2600.0, 2800.0, 100)
    cycle = 6.0 * np.sin(np.linspace(0, 8 * np.pi, 100))
    close = trend + cycle
    high = close + 3.0
    low = close - 3.0
    open_p = np.roll(close, 1)
    open_p[0] = close[0]
    df = pd.DataFrame({"time": t, "open": open_p, "high": high, "low": low, "close": close, "volume": 1000})

    detector = SwingDetector()
    analyzer = TrendAnalyzer(detector)
    trend_info = analyzer.identify_trend(df)

    assert trend_info["primary_trend"] in ("BULLISH", "SIDEWAYS")
    assert trend_info["strength"] >= 0.0


def test_support_resistance_detection():
    df = generate_synthetic_ohlcv(120)
    detector = SupportResistanceDetector()
    levels = detector.detect_levels(df)

    assert isinstance(levels, list)
    if levels:
        lvl = levels[0]
        assert "price" in lvl
        assert "strength" in lvl
        assert "type" in lvl


def test_supply_demand_zone_detector():
    df = generate_synthetic_ohlcv(120)
    detector = SupplyDemandDetector()
    zones = detector.detect_zones(df)

    assert isinstance(zones, list)
    validator = ZoneValidator()
    updated = validator.update_zone_states(zones, df)
    valid = validator.filter_valid_zones(updated, current_price=float(df["close"].iloc[-1]))

    assert isinstance(valid, list)
    for z in valid:
        assert z["state"] in ("FRESH", "TESTED")


def test_multi_timeframe_synthesis():
    detector = ConflictDetector()
    synthesizer = BiasSynthesizer()

    # Synthetic multi-TF analyses where macro is bullish
    mock_tf_analyses = {
        "MN1": {"bias": "BULLISH", "trend_strength": 0.8},
        "W1":  {"bias": "BULLISH", "trend_strength": 0.7},
        "D1":  {"bias": "BULLISH", "trend_strength": 0.6},
        "H4":  {"bias": "BULLISH", "trend_strength": 0.5},
        "H1":  {"bias": "BEARISH", "trend_strength": 0.4},  # Pullback
        "M15": {"bias": "BEARISH", "trend_strength": 0.3},
    }

    conflicts = detector.detect_conflicts(mock_tf_analyses)
    assert len(conflicts) > 0  # H4 vs H1 conflict

    synthesis = synthesizer.synthesize(mock_tf_analyses, conflicts)
    # Higher timeframes (MN1, W1, D1) carry heavy weight, so overall bias remains BULLISH
    assert synthesis["overall_bias"] == "BULLISH"
    assert synthesis["signal"] in ("BUY_OPPORTUNITY", "WAIT_FOR_CONFIRMATION")


def test_monte_carlo_simulator():
    simulator = MonteCarloSimulator()
    trade_stats = {
        "win_rate": 0.55,
        "avg_win_r": 2.0,
        "avg_loss_r": 1.0,
        "trades_per_day": 1.5,
        "risk_per_trade_pct": 1.0,
    }
    prop_config = {
        "profit_target_phase1_pct": 10.0,
        "max_drawdown_pct": 10.0,
        "daily_loss_limit_pct": 5.0,
        "drawdown_type": "static",
    }

    res = simulator.simulate_prop_firm_evaluation(trade_stats, prop_config, n_simulations=100, run_comparison=True)
    assert res["pass_probability"] > 0.0
    assert "p50_days" in res
    assert "risk_comparison" in res
