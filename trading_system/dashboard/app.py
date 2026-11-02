"""
dashboard/app.py
================
Central Universal Dash Web Application for Multi-Asset Trading Intelligence.
Dark-themed, institutional trading dashboard providing multi-timeframe chart intelligence,
dynamic instrument discovery, active MT5 chart synchronization via IPC, multi-asset portfolio risk,
strict market data integrity gating, and audited trade plan blueprints.

STRICTLY MANUAL EXECUTION: Never executes trades automatically.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html

from trading_system.analysis.ai_reasoning.gemini_analyst import GeminiAnalyst
from trading_system.config.settings import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    TIMEFRAME_HIERARCHY,
)
from trading_system.core.data.data_integrity import DataSourceState
from trading_system.core.data.data_provider import DataProvider
from trading_system.core.data.instrument_spec import (
    AssetClass,
    InstrumentDiscovery,
    InstrumentSpec,
    OFFLINE_SPECS_CATALOG,
)
from trading_system.core.data.mt5_connector import MT5Connector
from trading_system.core.data.symbol_specs import SymbolSpecs
from trading_system.core.ipc.bridge_protocol import (
    AnalysisResponseMessage,
    ChartContextMessage,
)
from trading_system.core.ipc.mt5_bridge_server import MT5BridgeServer
from trading_system.core.market_conditions.instrument_context import MarketConditionsAnalyzer
from trading_system.core.mtf.bias_synthesizer import BiasSynthesizer
from trading_system.core.mtf.conflict_detector import ConflictDetector
from trading_system.core.mtf.timeframe_analyzer import TimeframeAnalyzer
from trading_system.dashboard.charts.candlestick_chart import CandlestickChartBuilder
from trading_system.dashboard.components.ai_reasoning_panel import build_ai_reasoning_panel
from trading_system.dashboard.components.analysis_panel import (
    build_market_overview,
    build_mtf_bias_strip,
    build_setup_card,
)
from trading_system.dashboard.components.performance_panel import (
    build_performance_summary,
    build_trade_journal_table,
)
from trading_system.dashboard.components.risk_panel import (
    build_position_monitor,
    build_risk_panel,
)
from trading_system.journal.trading_journal import TradingJournal
from trading_system.risk.portfolio.exposure_monitor import PortfolioExposureMonitor
from trading_system.risk.position_sizing.calculator import PositionSizeCalculator
from trading_system.risk.position_sizing.volatility_adjuster import VolatilityRegimeDetector
from trading_system.risk.prop_firm.rules_engine import PropFirmRulesEngine
from trading_system.risk.trade_manager.trade_plan import TradePlan

logger = logging.getLogger(__name__)


class DashboardApp:
    """
    Main application wrapper encapsulating engines, layouts, and reactive Dash callbacks.
    """

    def __init__(
        self,
        mt5_connector: Optional[MT5Connector] = None,
        prop_firm_name: str = "ftmo_2step",
    ):
        self.mt5 = mt5_connector
        self.data_provider = DataProvider(mt5_connector=self.mt5)
        self.tf_analyzer = TimeframeAnalyzer()
        self.conflict_detector = ConflictDetector()
        self.bias_synthesizer = BiasSynthesizer()
        self.pos_calculator = PositionSizeCalculator(mt5_connector=self.mt5)
        self.vol_detector = VolatilityRegimeDetector()
        self.exposure_monitor = PortfolioExposureMonitor()
        self.prop_firm = PropFirmRulesEngine(prop_firm_name)
        self.journal = TradingJournal()
        self.chart_builder = CandlestickChartBuilder()
        self.ai_analyst = GeminiAnalyst()

        # Dynamic symbol specs cache
        self._specs_cache: Dict[str, SymbolSpecs] = {}

        # Cache latest analysis state
        self._current_symbol: str = "XAUUSD"
        self._latest_tf_analyses: dict[str, dict[str, Any]] = {}
        self._latest_synthesis: dict[str, Any] = {}
        self._latest_trade_plan: Optional[TradePlan] = None
        self._current_price: float = 3900.0

        # Active MT5 Chart telemetry from bridge
        self._last_active_chart_context: Optional[ChartContextMessage] = None
        self._last_active_chart_response: Optional[AnalysisResponseMessage] = None

        # Start Bidirectional MT5 Bridge Server
        self.bridge_server = MT5BridgeServer(
            mt5_connector=self.mt5,
            data_provider=self.data_provider,
            prop_firm_name=prop_firm_name,
        )
        self.bridge_server.register_callback(self._on_mt5_bridge_event)
        try:
            self.bridge_server.start()
            logger.info("MT5 Bridge Server initialized and listening for active chart requests.")
        except Exception as e:
            logger.warning("Could not start MT5 bridge server: %s", e)

        # Initialize Dash app with Cyborg dark theme
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.CYBORG, dbc.icons.BOOTSTRAP],
            suppress_callback_exceptions=True,
            title="Universal Multi-Asset AI Trading Intelligence Platform",
        )
        self._build_layout()
        self._register_callbacks()

    def _on_mt5_bridge_event(
        self, ctx: ChartContextMessage, resp: AnalysisResponseMessage
    ) -> None:
        """Callback invoked when MT5 active chart sends a sync or analysis request."""
        self._last_active_chart_context = ctx
        self._last_active_chart_response = resp
        logger.info(
            "Dashboard received bridge sync: %s (%s) ChartID: %d",
            ctx.symbol,
            ctx.period,
            ctx.chart_id,
        )

    def _get_symbol_spec(self, symbol: str) -> SymbolSpecs:
        """Get or initialize SymbolSpecs for target instrument."""
        if symbol not in self._specs_cache:
            if self.mt5 and self.mt5.is_connected():
                try:
                    info = self.mt5.get_symbol_info(symbol)
                    self._specs_cache[symbol] = SymbolSpecs(raw_specs=info, symbol=symbol)
                except Exception:
                    self._specs_cache[symbol] = SymbolSpecs(symbol=symbol)
            else:
                self._specs_cache[symbol] = SymbolSpecs(symbol=symbol)
        return self._specs_cache[symbol]

    def _build_layout(self) -> None:
        """Construct the complete universal multi-tab interface."""
        # Dynamically discover available symbols from MT5
        discovered_symbols = InstrumentDiscovery.discover_available_instruments(self.mt5)

        self.app.layout = dbc.Container([
            # Interval triggers
            dcc.Interval(id="fast-interval", interval=4000, n_intervals=0),      # Every 4s
            dcc.Interval(id="analysis-interval", interval=60000, n_intervals=0),  # Every 60s
            dcc.Store(id="selected-tf-store", data="H1"),

            # ── 1. Top Navbar Header ─────────────────────────────────────────
            dbc.Navbar(
                dbc.Container([
                    dbc.Row([
                        dbc.Col(
                            html.I(className="bi bi-graph-up-arrow fs-3 text-info me-2"),
                            width="auto",
                        ),
                        dbc.Col([
                            html.H4("UNIVERSAL TRADING INTELLIGENCE PLATFORM", className="fw-bold mb-0 text-light"),
                            html.Small(
                                "Multi-Asset MTF Technical Analyst & Risk Engine | Strictly Manual Execution Support",
                                className="text-secondary",
                            ),
                        ], width="auto"),

                        # Dynamic Instrument Dropdown
                        dbc.Col([
                            html.Span("Instrument: ", className="text-secondary small me-1"),
                            dcc.Dropdown(
                                id="instrument-selector",
                                options=discovered_symbols,
                                value="XAUUSD",
                                clearable=False,
                                className="text-dark fw-bold small",
                                style={"minWidth": "260px"},
                            ),
                        ], width="auto", className="ms-3"),

                        # Prop Firm Dropdown
                        dbc.Col([
                            html.Span("Prop Firm: ", className="text-secondary small me-1"),
                            dcc.Dropdown(
                                id="prop-firm-selector",
                                options=[
                                    {"label": "FTMO (2-Step MT5)", "value": "ftmo_2step"},
                                    {"label": "FundedNext (Stellar MT5)", "value": "fundednext_stellar"},
                                    {"label": "The5ers (High Stakes MT5)", "value": "the5ers_highstakes"},
                                    {"label": "Alpha Capital (MT5)", "value": "alphacapital"},
                                    {"label": "Topstep (CME Futures)", "value": "topstep"},
                                    {"label": "Apex Trader (CME Futures)", "value": "apex"},
                                ],
                                value="ftmo_2step",
                                clearable=False,
                                className="text-dark fw-bold small",
                                style={"minWidth": "210px"},
                            ),
                        ], width="auto", className="ms-2"),
                    ], align="center", className="g-1"),

                    dbc.Nav([
                        dbc.NavItem(
                            html.Div(id="active-chart-badge", className="d-flex align-items-center me-2"),
                        ),
                        dbc.NavItem(
                            html.Div(id="connection-badge", className="d-flex align-items-center me-3"),
                        ),
                        dbc.NavItem(
                            dbc.Button(
                                [html.I(className="bi bi-arrow-clockwise me-1"), "Refresh"],
                                id="manual-refresh-btn",
                                color="outline-info",
                                size="sm",
                            ),
                        ),
                    ], className="ms-auto", navbar=True),
                ], fluid=True),
                color="black",
                dark=True,
                className="border-bottom border-secondary mb-3 py-2",
            ),

            # ── 2. Data Integrity Warning Banner (Conditional) ────────────────
            html.Div(id="data-integrity-banner"),

            # ── 3. Market Hero Overview & Bias Strip ─────────────────────────
            html.Div(id="market-overview-container"),
            html.Div(id="mtf-bias-strip-container"),

            # ── 4. Main Navigation Tabs ──────────────────────────────────────
            dbc.Tabs([
                # TAB 1: Chart & Setup
                dbc.Tab(label="Interactive Chart & Trade Setup", tab_id="tab-chart", children=[
                    dbc.Row([
                        dbc.Col([
                            dbc.Card([
                                dbc.CardHeader(
                                    dbc.Row([
                                        dbc.Col(
                                            html.Span(id="chart-header-title", children="Multi-Timeframe Candlestick Chart", className="fw-bold text-light"),
                                        ),
                                        dbc.Col(
                                            dbc.ButtonGroup([
                                                dbc.Button("MN1", id="btn-tf-MN1", size="sm", color="dark", outline=True),
                                                dbc.Button("W1",  id="btn-tf-W1",  size="sm", color="dark", outline=True),
                                                dbc.Button("D1",  id="btn-tf-D1",  size="sm", color="dark", outline=True),
                                                dbc.Button("H4",  id="btn-tf-H4",  size="sm", color="dark", outline=True),
                                                dbc.Button("H1",  id="btn-tf-H1",  size="sm", color="info", outline=False),
                                                dbc.Button("M30", id="btn-tf-M30", size="sm", color="dark", outline=True),
                                                dbc.Button("M15", id="btn-tf-M15", size="sm", color="dark", outline=True),
                                            ], size="sm", className="float-end"),
                                            width="auto",
                                        ),
                                    ], align="center"),
                                    className="bg-black border-secondary py-2",
                                ),
                                dbc.CardBody(
                                    dcc.Graph(
                                        id="primary-candlestick-chart",
                                        style={"height": "600px"},
                                        config={"displayModeBar": True, "scrollZoom": True},
                                    ),
                                    className="bg-dark p-0",
                                ),
                            ], className="border-secondary mb-4"),
                        ], width=12, lg=8),

                        dbc.Col([
                            html.Div(id="setup-card-container"),
                        ], width=12, lg=4),
                    ]),
                ]),

                # TAB 2: Multi-Asset Portfolio Risk & Prop Firm
                dbc.Tab(label="Portfolio Risk & Prop Firm Dashboard", tab_id="tab-risk", children=[
                    html.Div(id="risk-dashboard-container", className="mt-3"),
                    html.Div(id="position-monitor-container"),
                ]),

                # TAB 3: AI Reasoning & Scenarios
                dbc.Tab(label="AI Reasoning & Scenario Engine", tab_id="tab-ai", children=[
                    html.Div(id="ai-reasoning-container", className="mt-3"),
                ]),

                # TAB 4: Multi-Timeframe Drilldown
                dbc.Tab(label="Detailed Timeframe Analysis", tab_id="tab-mtf", children=[
                    html.Div(id="detailed-mtf-container", className="mt-3"),
                ]),

                # TAB 5: Performance & Journal
                dbc.Tab(label="Performance & Trade Journal", tab_id="tab-performance", children=[
                    html.Div(id="performance-summary-container", className="mt-3"),
                    html.Div(id="journal-table-container"),
                ]),
            ], id="main-tabs", active_tab="tab-chart", className="mb-3"),

            # Footer
            html.Footer(
                html.P(
                    "Universal Trading Intelligence Platform | Strict Read-Only Integration | "
                    "All trade decisions & orders must be manually executed by human trader through MetaTrader 5.",
                    className="text-secondary small text-center my-4",
                ),
            ),
        ], fluid=True, className="p-3 bg-black min-vh-100")

    def _register_callbacks(self) -> None:
        """Register dynamic Dash callbacks."""

        # Timeframe button switcher
        for tf in ["MN1", "W1", "D1", "H4", "H1", "M30", "M15"]:
            @self.app.callback(
                Output("selected-tf-store", "data", allow_duplicate=True),
                Input(f"btn-tf-{tf}", "n_clicks"),
                prevent_initial_call=True,
            )
            def update_tf(n, target_tf=tf):
                if n:
                    return target_tf
                return "H1"

        # Main Data & Analysis Refresh Callback
        @self.app.callback(
            [
                Output("connection-badge", "children"),
                Output("active-chart-badge", "children"),
                Output("data-integrity-banner", "children"),
                Output("chart-header-title", "children"),
                Output("market-overview-container", "children"),
                Output("mtf-bias-strip-container", "children"),
                Output("primary-candlestick-chart", "figure"),
                Output("setup-card-container", "children"),
                Output("risk-dashboard-container", "children"),
                Output("position-monitor-container", "children"),
                Output("detailed-mtf-container", "children"),
                Output("ai-reasoning-container", "children"),
                Output("performance-summary-container", "children"),
                Output("journal-table-container", "children"),
            ],
            [
                Input("fast-interval", "n_intervals"),
                Input("manual-refresh-btn", "n_clicks"),
                Input("selected-tf-store", "data"),
                Input("instrument-selector", "value"),
                Input("prop-firm-selector", "value"),
            ],
        )
        def refresh_ui(n_fast, n_manual, selected_tf, target_symbol, target_firm):
            symbol = target_symbol or "XAUUSD"
            selected_timeframe = selected_tf or "H1"

            # 1. Update Prop Firm Engine if changed
            if target_firm and self.prop_firm.config.get("name") != target_firm:
                self.prop_firm.load_config(target_firm)

            # 2. Retrieve Instrument Specs & Live Data
            is_mt5 = self.data_provider.is_mt5_connected
            data_source_state = self.data_provider.integrity_manager.current_state
            sym_spec = self._get_symbol_spec(symbol)
            current_price = self.data_provider.get_current_price(symbol)
            self._current_price = current_price

            # Connection status badge with truthful telemetry
            if data_source_state == DataSourceState.MT5_LIVE:
                conn_badge = dbc.Badge([
                    html.Span("● ", className="text-success me-1"),
                    "MT5 LIVE (AUTHORITATIVE)",
                ], color="dark", className="border border-success p-2")
            elif data_source_state == DataSourceState.DEMO_SIMULATED:
                conn_badge = dbc.Badge([
                    html.Span("● ", className="text-warning me-1"),
                    "DEMO / SIMULATED",
                ], color="dark", className="border border-warning p-2")
            elif data_source_state == DataSourceState.HISTORICAL_BACKTEST:
                conn_badge = dbc.Badge([
                    html.Span("● ", className="text-info me-1"),
                    "HISTORICAL / BACKTEST",
                ], color="dark", className="border border-info p-2")
            else:
                conn_badge = dbc.Badge([
                    html.Span("● ", className="text-danger me-1"),
                    "OFFLINE / DISCONNECTED",
                ], color="dark", className="border border-danger p-2")

            # Active MT5 Chart telemetry badge
            if self._last_active_chart_context:
                act = self._last_active_chart_context
                chart_badge = dbc.Badge([
                    html.I(className="bi bi-display me-1 text-info"),
                    f"Active MT5 Chart: {act.symbol} ({act.period}) #{act.chart_id}",
                ], color="dark", className="border border-info p-2")
            else:
                chart_badge = dbc.Badge([
                    html.I(className="bi bi-display me-1 text-secondary"),
                    "No Active MT5 Chart Attached",
                ], color="dark", className="border border-secondary p-2")

            # Data Integrity Safety Banner
            if not is_mt5 or data_source_state != DataSourceState.MT5_LIVE:
                integrity_banner = dbc.Alert([
                    html.I(className="bi bi-shield-exclamation me-2 fs-5 text-warning"),
                    html.Strong("STRICT MARKET DATA INTEGRITY GATING: "),
                    "MetaTrader 5 terminal is currently OFFLINE or DISCONNECTED. "
                    "Live trade plan blueprint generation is strictly SUSPENDED to prevent execution with unverified data. "
                    "Connect MT5 terminal to restore live institutional execution blueprints.",
                ], color="warning", className="d-flex align-items-center mb-3 py-2")
            else:
                integrity_banner = html.Div()

            # 3. Multi-Timeframe Analysis for Selected Instrument
            tf_data = self.data_provider.get_all_timeframes(symbol)
            tf_analyses: dict[str, dict[str, Any]] = {}

            for tf, df in tf_data.items():
                if not df.empty:
                    analysis = self.tf_analyzer.analyze(tf, df)
                    tf_analyses[tf] = analysis

            self._latest_tf_analyses = tf_analyses

            # 4. Detect Conflicts & Synthesize Top-Down Bias
            conflicts = self.conflict_detector.detect_conflicts(tf_analyses)
            synthesis = self.bias_synthesizer.synthesize(tf_analyses, conflicts)
            self._latest_synthesis = synthesis

            # 5. Account & Prop Firm Limits
            if is_mt5 and self.mt5:
                account_info = self.mt5.get_account_info()
                open_positions = self.mt5.get_open_positions()
            else:
                account_info = {"balance": 100000.0, "equity": 100000.0, "free_margin": 100000.0}
                open_positions = []

            self.prop_firm.update_account_state(account_info)
            prop_limits = self.prop_firm.get_current_limits(account_info)
            exposure = self.exposure_monitor.calculate_exposure(open_positions, account_info)

            # 6. Formulate Universal Trade Plan Blueprint (Gated by MT5 Live connection)
            if is_mt5 and data_source_state == DataSourceState.MT5_LIVE:
                trade_plan = self._generate_trade_plan(
                    synthesis, tf_analyses, current_price, sym_spec, account_info, prop_limits
                )
            else:
                # Gated: Never generate live trade plans from fallback/synthetic data!
                trade_plan = None
            self._latest_trade_plan = trade_plan

            # 7. Session Context & Macro Conditions
            market_cond = MarketConditionsAnalyzer.evaluate(sym_spec.instrument_spec)

            # 8. Render UI Panels
            chart_title = f"{symbol} Candlestick Chart ({selected_timeframe}) — {sym_spec.instrument_spec.description}"

            overview_html = build_market_overview(
                symbol=symbol,
                current_price=current_price,
                spread_points=int(sym_spec.instrument_spec.spread),
                session_name=market_cond.session_status,
                volatility_regime="NORMAL",
                overall_bias=synthesis.get("overall_bias", "NEUTRAL"),
                bias_strength=synthesis.get("bias_strength", 0.0),
                spec=sym_spec.instrument_spec,
            )

            strip_html = build_mtf_bias_strip(tf_analyses)

            chart_df = tf_data.get(selected_timeframe, tf_data.get("H1"))
            chart_analysis = tf_analyses.get(selected_timeframe, {})
            fig = self.chart_builder.build_chart(
                df=chart_df,
                timeframe=selected_timeframe,
                analysis=chart_analysis,
                trade_plan=trade_plan.to_dict() if trade_plan else None,
            )

            setup_html = build_setup_card(
                trade_plan.to_dict() if trade_plan else None,
                spec=sym_spec.instrument_spec,
            )

            risk_html = build_risk_panel(account_info, prop_limits, exposure)
            pos_html = build_position_monitor(open_positions)
            detailed_mtf_html = self._build_detailed_mtf_view(tf_analyses)

            # AI Market Reasoning & Scenario Generation
            narrative = self.ai_analyst.generate_market_narrative(synthesis, symbol=symbol)
            scenarios = self.ai_analyst.generate_scenario_analysis(synthesis, symbol=symbol)
            trade_plan_dict = trade_plan.to_dict() if trade_plan else None
            evaluation = (
                self.ai_analyst.evaluate_trade_plan_quality(trade_plan_dict, synthesis, symbol=symbol)
                if trade_plan_dict else None
            )

            ai_html = build_ai_reasoning_panel(
                narrative=narrative,
                scenarios=scenarios,
                trade_plan=trade_plan_dict,
                evaluation=evaluation,
                has_api_key=self.ai_analyst.is_ai_connected,
            )

            perf_stats = self.journal.get_performance_stats()
            perf_html = build_performance_summary(perf_stats)
            trade_history = self.journal.get_trade_history()
            journal_html = build_trade_journal_table(trade_history)

            return (
                conn_badge,
                chart_badge,
                integrity_banner,
                chart_title,
                overview_html,
                strip_html,
                fig,
                setup_html,
                risk_html,
                pos_html,
                detailed_mtf_html,
                ai_html,
                perf_html,
                journal_html,
            )

    def _generate_trade_plan(
        self,
        synthesis: dict[str, Any],
        tf_analyses: dict[str, dict[str, Any]],
        current_price: float,
        sym_spec: SymbolSpecs,
        account_info: dict[str, Any],
        prop_limits: dict[str, Any],
    ) -> Optional[TradePlan]:
        """
        Formulate a mathematically rigorous TradePlan dataclass for any instrument.
        Uses actual live equity, exact order_calc_profit, commissions, spread, and slippage.
        """
        signal = synthesis.get("signal")
        if signal not in ("BUY_OPPORTUNITY", "SELL_OPPORTUNITY"):
            return None

        spec = sym_spec.instrument_spec
        digits = spec.digits
        direction = "BUY" if signal == "BUY_OPPORTUNITY" else "SELL"
        h1 = tf_analyses.get("H1", {})
        atr = float(h1.get("atr", current_price * 0.005))
        if atr <= 0:
            atr = current_price * 0.005

        if direction == "BUY":
            entry = current_price
            sl = round(entry - (atr * 1.5), digits)
            tp1 = round(entry + ((entry - sl) * 1.5), digits)
            tp2 = round(entry + ((entry - sl) * 2.5), digits)
        else:
            entry = current_price
            sl = round(entry + (atr * 1.5), digits)
            tp1 = round(entry - ((sl - entry) * 1.5), digits)
            tp2 = round(entry - ((sl - entry) * 2.5), digits)

        equity = float(account_info.get("equity", 100000.0))
        daily_rem = prop_limits.get("daily_loss_remaining_usd")
        max_rem = prop_limits.get("remaining_drawdown_usd")
        spread_pts = int(spec.spread)

        # Dynamic quantitative sizing factoring in spread, commission, slippage
        calc_res = self.pos_calculator.calculate(
            account_equity=equity,
            risk_pct=1.0,
            entry_price=entry,
            sl_price=sl,
            symbol_info=spec.to_dict(),
            account_currency="USD",
            direction=direction,
            max_daily_loss_remaining_usd=daily_rem,
            max_drawdown_remaining_usd=max_rem,
            spread_points=spread_pts,
        )

        if not calc_res.get("is_valid", False):
            logger.warning("Trade plan calculation invalid: %s", calc_res.get("rejection_reason"))
            return None

        lots = calc_res["lots"]
        monetary_risk = calc_res["monetary_risk_usd"]
        delta = max(atr * 0.1, 10 ** (-digits))

        plan = TradePlan(
            symbol=sym_spec.symbol,
            direction=direction,
            status="PENDING_CONFIRMATION",
            market_context=synthesis.get("narrative", ""),
            htf_bias=synthesis.get("overall_bias", "BULLISH"),
            setup_quality=synthesis.get("setup_quality", "A"),
            entry_price=entry,
            entry_zone_low=round(entry - delta, digits),
            entry_zone_high=round(entry + delta, digits),
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward_tp1=1.5,
            risk_reward_tp2=2.5,
            position_size_lots=lots,
            monetary_risk_usd=monetary_risk,
            risk_pct_of_equity=round(calc_res.get("monetary_risk_pct", 1.0), 2),
            invalidation_price=sl,
        )

        # Validate against prop firm rules
        is_safe, violations = self.prop_firm.validate_new_trade(plan, account_info)
        if not is_safe:
            logger.warning("Trade plan rejected by prop firm engine: %s", violations)
            return None

        return plan

    def _build_detailed_mtf_view(self, tf_analyses: dict[str, dict[str, Any]]) -> html.Div:
        """Construct detailed timeframe cards."""
        items = []
        for tf in TIMEFRAME_HIERARCHY:
            if tf not in tf_analyses:
                continue
            data = tf_analyses[tf]
            bias = data.get("bias", "NEUTRAL")
            color = "success" if bias == "BULLISH" else ("danger" if bias == "BEARISH" else "warning")

            card = dbc.Card([
                dbc.CardHeader([
                    dbc.Badge(tf, color="dark", className="me-2 fs-6"),
                    dbc.Badge(bias, color=color, className="me-2"),
                    html.Span(f"Candle: {data.get('current_candle_status')} | ATR: {data.get('atr', 0):.4f}", className="text-secondary small"),
                ], className="bg-black py-2"),
                dbc.CardBody([
                    html.P(f"Structural Context: {data.get('bias_reasoning')}", className="text-light mb-1 small"),
                    html.P(f"Expectation: {data.get('next_candle_expectation')}", className="text-info mb-1 small"),
                    html.Small(f"Bullish Scenario: {data.get('bullish_scenario')}", className="text-secondary d-block"),
                    html.Small(f"Bearish Scenario: {data.get('bearish_scenario')}", className="text-secondary d-block"),
                ], className="bg-dark p-3"),
            ], className="border-secondary mb-3")
            items.append(card)

        return html.Div(items)

    def run(self, host: str = DASHBOARD_HOST, port: int = DASHBOARD_PORT, debug: bool = False) -> None:
        """Start the Dash web application."""
        logger.info("Starting Universal Trading Platform Dashboard at http://%s:%d", host, port)
        self.app.run(host=host, port=port, debug=debug)


def create_app(mt5_connector: Optional[MT5Connector] = None, prop_firm: str = "ftmo_2step") -> DashboardApp:
    return DashboardApp(mt5_connector=mt5_connector, prop_firm_name=prop_firm)


if __name__ == "__main__":
    app_instance = create_app()
    app_instance.run(debug=True)
