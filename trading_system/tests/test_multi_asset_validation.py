"""
tests/test_multi_asset_validation.py
====================================
Multi-Asset Historical & Structural Validation Test Suite.

Verifies that the entire technical analysis, support/resistance,
supply/demand, and risk pipeline runs across representative instruments
from each asset class:
- XAUUSD (Metals)
- EURUSD (Forex)
- USTEC (Indices)
- BTCUSD (Crypto)
"""

import pytest
import pandas as pd
import numpy as np

from trading_system.core.data.data_provider import DataProvider
from trading_system.core.data.instrument_spec import InstrumentDiscovery, AssetClass
from trading_system.core.mtf.timeframe_analyzer import TimeframeAnalyzer
from trading_system.core.mtf.conflict_detector import ConflictDetector
from trading_system.core.mtf.bias_synthesizer import BiasSynthesizer
from trading_system.backtesting.historical_tester import HistoricalTester
from trading_system.core.market_conditions.instrument_context import MarketConditionsAnalyzer


@pytest.fixture
def data_provider():
    return DataProvider(mt5_connector=None, use_cache=False)


@pytest.mark.parametrize("symbol,expected_class", [
    ("XAUUSD", AssetClass.METALS),
    ("EURUSD", AssetClass.FOREX_MAJOR),
    ("USTEC",  AssetClass.INDICES),
    ("US30",   AssetClass.INDICES),
    ("BTCUSD", AssetClass.CRYPTO),
    ("USOIL",  AssetClass.COMMODITIES),
])
def test_universal_instrument_classification(symbol, expected_class):
    """Verify that every instrument is accurately classified."""
    ac = InstrumentDiscovery.classify_asset(symbol)
    assert ac == expected_class


@pytest.mark.parametrize("symbol", ["XAUUSD", "EURUSD", "USTEC", "BTCUSD"])
def test_multi_asset_technical_analysis_pipeline(data_provider, symbol):
    """
    Verify complete top-down analysis pipeline runs without error
    across vastly different price scales (from 1.10 to 80,000.00).
    """
    tf_analyzer = TimeframeAnalyzer()
    conflict_detector = ConflictDetector()
    bias_synthesizer = BiasSynthesizer()

    # Generate or fetch multi-timeframe data
    timeframes = ["MN1", "W1", "D1", "H4", "H1", "M15"]
    analyses = {}

    for tf in timeframes:
        df = data_provider.get_ohlcv(symbol=symbol, timeframe=tf, count=150)
        assert not df.empty, f"Failed to get data for {symbol} {tf}"
        assert len(df) >= 50
        analysis = tf_analyzer.analyze(tf, df)
        assert "bias" in analysis
        assert "current_price" in analysis
        assert analysis["current_price"] > 0
        assert analysis["atr"] > 0
        analyses[tf] = analysis

    # Test conflict detection & bias synthesis
    conflicts = conflict_detector.detect_conflicts(analyses)
    synthesis = bias_synthesizer.synthesize(analyses, conflicts)

    assert "overall_bias" in synthesis
    assert "signal" in synthesis
    assert synthesis["overall_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")


@pytest.mark.parametrize("symbol", ["XAUUSD", "EURUSD", "USTEC", "BTCUSD"])
def test_historical_tester_across_assets(data_provider, symbol):
    """Verify historical S/R and zone freshness tests across different assets."""
    tester = HistoricalTester()
    df = data_provider.get_ohlcv(symbol=symbol, timeframe="D1", count=250)

    sr_result = tester.run_sr_quality_test(df)
    assert "bounce_rate_pct" in sr_result
    assert 0.0 <= sr_result["bounce_rate_pct"] <= 100.0

    zone_result = tester.run_zone_freshness_test(df)
    assert "total_zones_identified" in zone_result
    assert zone_result["total_zones_identified"] >= 0


def test_market_conditions_session_analyzer():
    """Verify that global sessions and macro drivers evaluate cleanly."""
    spec_gold = InstrumentDiscovery.get_fallback_spec("XAUUSD")
    cond_gold = MarketConditionsAnalyzer.evaluate(spec_gold)
    assert len(cond_gold.macro_drivers) > 0
    assert any("DXY" in d or "Yields" in d for d in cond_gold.macro_drivers)

    spec_crypto = InstrumentDiscovery.get_fallback_spec("BTCUSD")
    cond_crypto = MarketConditionsAnalyzer.evaluate(spec_crypto)
    assert any("24/7" in d or "ETF" in d for d in cond_crypto.macro_drivers)
