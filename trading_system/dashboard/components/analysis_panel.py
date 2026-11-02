"""
dashboard/components/analysis_panel.py
======================================
Dash Component Builder for Universal Multi-Timeframe Bias Strip,
Market Overview, and Actionable Trade Setup Cards for any financial instrument.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import dash_bootstrap_components as dbc
from dash import html

from trading_system.core.data.instrument_spec import AssetClass, InstrumentDiscovery, InstrumentSpec

logger = logging.getLogger(__name__)


def _format_price(val: float, digits: int = 2) -> str:
    """Format price with appropriate precision based on digits."""
    if digits == 5:
        return f"{val:.5f}"
    elif digits == 4:
        return f"{val:.4f}"
    elif digits == 3:
        return f"{val:.3f}"
    elif digits == 1:
        return f"{val:.1f}"
    elif digits == 0:
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def build_mtf_bias_strip(timeframe_analyses: dict[str, dict[str, Any]]) -> html.Div:
    """
    Construct the horizontal multi-timeframe bias alignment strip.
    """
    tfs = ["MN1", "W1", "D1", "H4", "H1", "M30", "M15"]
    cols = []

    for tf in tfs:
        data = timeframe_analyses.get(tf, {})
        bias = data.get("bias", "NEUTRAL")
        status = data.get("current_candle_status", "CONFIRMED")
        is_forming = status == "FORMING"

        if bias == "BULLISH":
            color = "success"
            icon = "▲"
        elif bias == "BEARISH":
            color = "danger"
            icon = "▼"
        else:
            color = "secondary"
            icon = "■"

        cols.append(
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.Div(tf, className="fw-bold small text-secondary"),
                        html.H6(f"{icon} {bias}", className=f"text-{color} fw-bold mb-0 mt-1"),
                        html.Small(
                            "forming" if is_forming else "closed",
                            className="text-warning small" if is_forming else "text-muted small",
                        ),
                    ], className="p-2 text-center"),
                ], className="bg-dark border-secondary shadow-sm"),
                className="px-1",
            )
        )

    return html.Div([
        html.H6("MULTI-TIMEFRAME STRUCTURAL ALIGNMENT", className="text-secondary mb-2 small fw-bold"),
        dbc.Row(cols, className="g-1 mb-3"),
    ])


def build_market_overview(
    symbol: str,
    current_price: float,
    spread_points: int = 25,
    session_name: str = "Standard Session",
    volatility_regime: str = "NORMAL",
    overall_bias: str = "BULLISH",
    bias_strength: float = 0.85,
    spec: Optional[InstrumentSpec] = None,
) -> html.Div:
    """
    Construct the hero header displaying asset details, spot price, spread, session, and macro bias.
    """
    if spec is None:
        spec = InstrumentDiscovery.get_fallback_spec(symbol)

    digits = spec.digits
    price_str = _format_price(current_price, digits)
    prefix = "$" if spec.currency_profit.upper() == "USD" and spec.asset_class != AssetClass.FOREX_MAJOR else ""

    bias_color = "success" if overall_bias == "BULLISH" else ("danger" if overall_bias == "BEARISH" else "warning")

    # Asset class color pill
    ac_color = "primary"
    if spec.asset_class == AssetClass.METALS:
        ac_color = "warning"
    elif spec.asset_class == AssetClass.CRYPTO:
        ac_color = "info"
    elif spec.asset_class == AssetClass.INDICES:
        ac_color = "success"
    elif spec.asset_class == AssetClass.COMMODITIES:
        ac_color = "danger"

    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        dbc.Badge(spec.asset_class.value, color=ac_color, className="me-2"),
                        html.Span(f"{spec.broker_symbol} ({spec.description})", className="text-light fw-bold small"),
                    ], className="mb-1"),
                    html.H2(f"{prefix}{price_str}", className="fw-bold text-light mb-0"),
                    html.Small(
                        f"Spread: {spread_points} pts | Tick Val: ${spec.tick_value:,.4f} | CSize: {spec.contract_size:,.1f}",
                        className="text-secondary",
                    ),
                ], width=12, md=4),

                dbc.Col([
                    html.Small("MACRO MARKET BIAS", className="text-secondary fw-bold"),
                    html.H3(
                        dbc.Badge(f"{overall_bias} ({bias_strength * 100:.0f}%)", color=bias_color, className="p-2"),
                        className="mb-0",
                    ),
                    html.Small("Derived from Top-Down MTF Weighted Synthesis", className="text-secondary"),
                ], width=12, md=4),

                dbc.Col([
                    html.Small("SESSION & VOLATILITY REGIME", className="text-secondary fw-bold"),
                    html.H4(
                        dbc.Badge(volatility_regime, color="info", className="p-2 me-2"),
                        className="mb-1",
                    ),
                    html.Small(f"Session: {session_name}", className="text-secondary d-block"),
                ], width=12, md=4),
            ], className="align-items-center"),
        ], className="bg-dark p-3"),
    ], className="border-secondary mb-3")


def build_setup_card(
    trade_plan: Optional[dict[str, Any]] = None,
    spec: Optional[InstrumentSpec] = None,
) -> html.Div:
    """
    Construct the actionable trade setup card.
    Clearly emphasizes manual execution protocol and asset-specific precision.
    """
    if not trade_plan or trade_plan.get("direction") == "NEUTRAL":
        return dbc.Card([
            dbc.CardHeader("Actionable Trade Setup Blueprint", className="fw-bold bg-black text-light"),
            dbc.CardBody([
                html.H5("NO TRADE OPPORTUNITY (STAND ASIDE)", className="text-warning fw-bold mb-2"),
                html.P(
                    "The system does not force trades. Market condition is either range-bound, conflicting, "
                    "or awaiting valid price-action confirmation at high-value technical areas.",
                    className="text-secondary mb-0",
                ),
            ], className="bg-dark text-center py-4"),
        ], className="border-secondary mb-4")

    sym = trade_plan.get("symbol", "INSTRUMENT")
    if spec is None:
        spec = InstrumentDiscovery.get_fallback_spec(sym)

    digits = spec.digits
    direction = trade_plan.get("direction", "BUY")
    quality = trade_plan.get("setup_quality", "A")
    entry = float(trade_plan.get("entry_price", 0.0))
    sl = float(trade_plan.get("stop_loss", 0.0))
    tp1 = float(trade_plan.get("take_profit_1", 0.0))
    tp2 = float(trade_plan.get("take_profit_2", 0.0))
    rr = float(trade_plan.get("risk_reward_tp1", 1.5))
    lots = float(trade_plan.get("position_size_lots", 0.10))
    risk_usd = float(trade_plan.get("monetary_risk_usd", 100.0))
    risk_pct = float(trade_plan.get("risk_pct_of_equity", 1.0))

    dir_color = "success" if direction == "BUY" else "danger"

    entry_str = _format_price(entry, digits)
    sl_str = _format_price(sl, digits)
    tp1_str = _format_price(tp1, digits)

    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                dbc.Badge(f"{direction} SETUP", color=dir_color, className="fs-6 me-2"),
                dbc.Badge(f"GRADE: {quality}", color="info", className="fs-6 me-2"),
                dbc.Badge(sym, color="secondary", className="fs-6"),
                html.Span("Trade Plan Specification", className="fw-bold text-light ms-2"),
            ]),
            className="bg-black border-secondary py-2",
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H6("ENTRY ZONE", className="text-secondary small mb-1"),
                    html.H4(entry_str, className="fw-bold text-light"),
                    html.Small("Limit / Confirmation Zone", className="text-secondary"),
                ], width=6, md=3),

                dbc.Col([
                    html.H6("STOP LOSS", className="text-secondary small mb-1"),
                    html.H4(sl_str, className="fw-bold text-danger"),
                    html.Small(f"Risk: ${risk_usd:,.2f} ({risk_pct:.1f}%)", className="text-secondary"),
                ], width=6, md=3),

                dbc.Col([
                    html.H6("TAKE PROFIT 1 (1.5R)", className="text-secondary small mb-1"),
                    html.H4(tp1_str, className="fw-bold text-success"),
                    html.Small(f"R:R: 1:{rr:.2f} (Close 50%)", className="text-secondary"),
                ], width=6, md=3),

                dbc.Col([
                    html.H6("POSITION SIZE", className="text-secondary small mb-1"),
                    html.H4(f"{lots:.2f} Lots", className="fw-bold text-warning"),
                    html.Small("Broker Spec Sized", className="text-secondary"),
                ], width=6, md=3),
            ], className="mb-3 text-center"),

            html.Hr(className="border-secondary my-2"),

            # Actionable human instructions
            dbc.Alert([
                html.I(className="bi bi-shield-exclamation me-2"),
                html.Strong("MANUAL EXECUTION INSTRUCTION: "),
                "This system NEVER executes trades automatically. If you approve this setup, ",
                html.Strong(f"manually enter a {direction} order for {lots:.2f} lots on {sym} at ~{entry_str} with SL at {sl_str} and TP at {tp1_str} "),
                "via your MetaTrader 5 terminal.",
            ], color="info", className="mb-0 small py-2"),
        ], className="bg-dark"),
    ], className="border-secondary mb-4")
