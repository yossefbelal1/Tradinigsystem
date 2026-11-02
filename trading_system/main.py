#!/usr/bin/env python3
"""
main.py
=======
Main Execution Entry Point for the AI-Powered XAUUSD Trading Intelligence System.

Operating Philosophy:
- STRICT MANUAL EXECUTION SUPPORT: System provides top-down technical analysis,
  dynamic position sizing, and trade plans, but NEVER executes orders autonomously.
- READ-ONLY MT5 TELEMETRY: Interacts with MetaTrader 5 strictly to stream market data,
  monitor open positions, and audit account risk.

Usage
-----
    python main.py                       # Launch with MT5 and Dash Web Dashboard
    python main.py --demo                # Launch in Demo Mode (Yahoo Finance data)
    python main.py --analyze-only        # Run one-shot top-down MTF analysis and print report
    python main.py --prop-firm topstep   # Enforce TopStep prop firm rules
    python main.py --port 8080           # Run dashboard on custom port
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure root package directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

from trading_system.config.settings import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_PATH,
    MT5_SERVER,
    SYMBOL,
    configure_logging,
)
from trading_system.core.data.data_provider import DataProvider
from trading_system.core.data.mt5_connector import MT5Connector
from trading_system.core.mtf.bias_synthesizer import BiasSynthesizer
from trading_system.core.mtf.conflict_detector import ConflictDetector
from trading_system.core.mtf.timeframe_analyzer import TimeframeAnalyzer
from trading_system.analysis.report_generator.report_builder import ReportBuilder
from trading_system.analysis.scenario_engine.scenario_builder import ScenarioBuilder

logger = logging.getLogger("trading_system.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="XAUUSD AI-Powered Multi-Timeframe Trading Analysis System",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode using Yahoo Finance data (no MT5 terminal required)",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Run a single top-down analysis, print formal report to stdout, and exit",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DASHBOARD_PORT,
        help=f"Dashboard web server port (default: {DASHBOARD_PORT})",
    )
    parser.add_argument(
        "--prop-firm",
        type=str,
        default="ftmo_2step",
        help="Prop firm configuration profile (e.g., ftmo_2step, ftmo_1step, topstep, apex)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=SYMBOL,
        help=f"Trading symbol (default: {SYMBOL})",
    )
    return parser.parse_args()


def run_one_shot_analysis(data_provider: DataProvider, symbol: str) -> None:
    """Execute top-down analysis and output formal Markdown report."""
    logger.info("Executing comprehensive top-down analysis for %s...", symbol)

    tf_analyzer = TimeframeAnalyzer()
    conflict_detector = ConflictDetector()
    bias_synthesizer = BiasSynthesizer()
    report_builder = ReportBuilder()

    current_price = data_provider.get_current_price(symbol)
    tf_data = data_provider.get_all_timeframes(symbol)

    tf_analyses = {}
    for tf, df in tf_data.items():
        if not df.empty:
            tf_analyses[tf] = tf_analyzer.analyze(tf, df)

    conflicts = conflict_detector.detect_conflicts(tf_analyses)
    synthesis = bias_synthesizer.synthesize(tf_analyses, conflicts)

    # Scenarios
    scenarios_builder = ScenarioBuilder()
    scenarios = scenarios_builder.build_scenarios(
        timeframe_analyses=tf_analyses,
        synthesis=synthesis,
    )

    report = report_builder.build_full_report(
        symbol=symbol,
        current_price=current_price,
        data_timestamp="",
        data_source=data_provider.get_source_label("H1"),
        timeframe_analyses=tf_analyses,
        synthesis=synthesis,
        scenarios=scenarios,
        ai_narrative=synthesis.get("narrative", ""),
    )

    print("\n" + "=" * 80)
    print(report["markdown"])
    print("=" * 80 + "\n")


def main() -> None:
    args = parse_args()
    configure_logging()

    print(r"""
================================================================================
   __  __ ___   __  __ _   _ ____  ____    _    ___ 
   \ \/ // _ \ | | | | | | / ___||  _ \  / \  |_ _|
    \  /| | | || | | | | | \___ \| | | |/ _ \  | | 
    /  \| |_| || |_| | |_| |___) | |_| / ___ \ | | 
   /_/\_\\___(_)____/ \___/|____/|____//_/   \_|___|
                                                    
   AI-POWERED MULTI-TIMEFRAME TRADING ANALYSIS SYSTEM
   Strictly Semi-Independent | Human Trader In The Loop
================================================================================
    """)

    mt5_conn = None
    if not args.demo:
        logger.info("Connecting to MetaTrader 5 (READ-ONLY mode)...")
        mt5_conn = MT5Connector(
            login=MT5_LOGIN,
            password=MT5_PASSWORD,
            server=MT5_SERVER,
            path=MT5_PATH,
        )
        connected = mt5_conn.connect()
        if not connected:
            logger.warning("Could not connect to MT5 terminal. Falling back to Demo / Yahoo Finance data.")
            mt5_conn = None
        else:
            logger.info("MetaTrader 5 connection confirmed. Telemetry active.")

    data_provider = DataProvider(mt5_connector=mt5_conn)

    # Mode 1: One-Shot Analysis Report
    if args.analyze_only:
        run_one_shot_analysis(data_provider, args.symbol)
        if mt5_conn:
            mt5_conn.disconnect()
        return

    # Mode 2: Interactive Web Dashboard
    try:
        from trading_system.dashboard.app import create_app
    except ImportError as e:
        logger.error(
            "Dashboard requirements not fully installed: %s. "
            "Please run: pip install dash dash-bootstrap-components plotly",
            e,
        )
        return

    dashboard = create_app(mt5_connector=mt5_conn, prop_firm=args.prop_firm)
    logger.info("Initializing Dash Dashboard on http://%s:%d ...", DASHBOARD_HOST, args.port)

    try:
        dashboard.run(host=DASHBOARD_HOST, port=args.port, debug=False)
    except KeyboardInterrupt:
        logger.info("User requested shutdown. Cleaning up resources...")
    finally:
        if mt5_conn:
            mt5_conn.disconnect()
            logger.info("MetaTrader 5 session disconnected cleanly.")


if __name__ == "__main__":
    main()
