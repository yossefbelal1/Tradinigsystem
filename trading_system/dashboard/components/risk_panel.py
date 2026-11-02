"""
dashboard/components/risk_panel.py
==================================
Universal Dash Component Builder for Multi-Asset Risk, Prop Firm Compliance,
Currency Exposure Breakdown, and Open Positions Monitor.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import dash_bootstrap_components as dbc
from dash import html

from trading_system.core.data.instrument_spec import InstrumentDiscovery

logger = logging.getLogger(__name__)


def build_risk_panel(
    account_info: dict[str, Any],
    prop_firm_limits: Optional[dict[str, Any]] = None,
    exposure: Optional[dict[str, Any]] = None,
) -> html.Div:
    """
    Construct the executive account equity, prop firm gauge, and multi-asset currency exposure layout.
    """
    equity = float(account_info.get("equity", 100000.0))
    balance = float(account_info.get("balance", 100000.0))
    floating_pnl = equity - balance

    limits = prop_firm_limits or {}
    firm_name = limits.get("firm_name", "Prop Firm Rule Monitor")
    platform = limits.get("platform", "MetaTrader 5")
    mt5_comp = limits.get("mt5_compatible", True)
    daily_rem_usd = limits.get("daily_loss_remaining_usd", 5000.0)
    daily_rem_pct = limits.get("daily_loss_remaining_pct", 5.0)
    max_rem_usd = limits.get("remaining_drawdown_usd", 10000.0)
    max_rem_pct = limits.get("remaining_drawdown_pct", 10.0)
    dd_type = str(limits.get("drawdown_type", "static")).upper()
    is_breached = limits.get("is_breached", False)
    firm_warnings = limits.get("warnings", [])

    expo = exposure or {}
    total_lots = expo.get("total_lots", 0.0)
    total_risk_usd = expo.get("total_monetary_risk_usd", 0.0)
    total_risk_pct = expo.get("total_risk_pct", 0.0)
    adj_risk_usd = expo.get("correlation_adjusted_risk_usd", total_risk_usd)
    adj_risk_pct = expo.get("correlation_adjusted_risk_pct", total_risk_pct)
    curr_exposures = expo.get("currency_exposures", {})
    high_corr_pairs = expo.get("high_correlation_pairs", [])

    # Status Pill
    if is_breached:
        badge = dbc.Badge("RULE BREACHED", color="danger", className="p-2 fs-6")
    elif max_rem_pct < 3.0 or daily_rem_pct < 1.5:
        badge = dbc.Badge("WARNING: DANGER ZONE", color="warning", className="p-2 fs-6")
    else:
        badge = dbc.Badge("COMPLIANT & ACTIVE", color="success", className="p-2 fs-6")

    pnl_color = "#00ff88" if floating_pnl >= 0 else "#ff4466"

    # Currency Exposure Pills
    curr_rows = []
    if curr_exposures:
        for c_code, c_data in sorted(curr_exposures.items()):
            net_val = float(c_data.get("net_usd", 0.0))
            is_conc = bool(c_data.get("is_concentrated", False))
            c_color = "danger" if is_conc else ("success" if net_val >= 0 else "info")
            sign = "+" if net_val > 0 else ""
            curr_rows.append(
                dbc.Col(
                    dbc.Card([
                        dbc.CardBody([
                            html.Small(f"NET {c_code}", className="text-secondary fw-bold"),
                            html.H6(f"{sign}${net_val:,.0f}", className=f"text-{c_color} fw-bold mb-0"),
                            html.Small(f"{c_data.get('pct_equity', 0.0):.1f}% equity", className="text-muted"),
                        ], className="p-2 text-center"),
                    ], className="bg-dark border-secondary"),
                    width=4, md=2, className="mb-2",
                )
            )

    return html.Div([
        # Row 1: High Level KPI Cards
        dbc.Row([
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.H6("ACCOUNT EQUITY", className="text-secondary mb-1"),
                        html.H3(f"${equity:,.2f}", className="fw-bold mb-0 text-light"),
                        html.Small(f"Balance: ${balance:,.2f}", className="text-secondary"),
                    ])
                ], className="bg-dark border-secondary shadow-sm mb-3"),
                width=12, md=3,
            ),
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.H6("FLOATING P&L", className="text-secondary mb-1"),
                        html.H3(
                            f"{'+' if floating_pnl >= 0 else ''}${floating_pnl:,.2f}",
                            className="fw-bold mb-0",
                            style={"color": pnl_color},
                        ),
                        html.Small(f"Open Lots: {total_lots:.2f} lots", className="text-secondary"),
                    ])
                ], className="bg-dark border-secondary shadow-sm mb-3"),
                width=12, md=3,
            ),
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.H6("DAILY LOSS BUFFER", className="text-secondary mb-1"),
                        html.H3(f"${daily_rem_usd:,.2f}", className="fw-bold mb-0 text-info"),
                        html.Small(f"{daily_rem_pct:.1f}% remaining today", className="text-secondary"),
                    ])
                ], className="bg-dark border-secondary shadow-sm mb-3"),
                width=12, md=3,
            ),
            dbc.Col(
                dbc.Card([
                    dbc.CardBody([
                        html.H6(f"MAX DRAWDOWN ({dd_type})", className="text-secondary mb-1"),
                        html.H3(f"${max_rem_usd:,.2f}", className="fw-bold mb-0 text-warning"),
                        html.Small(f"{max_rem_pct:.1f}% buffer before breach", className="text-secondary"),
                    ])
                ], className="bg-dark border-secondary shadow-sm mb-3"),
                width=12, md=3,
            ),
        ]),

        # Row 2: Compliance Banner & Portfolio Risk
        dbc.Card([
            dbc.CardHeader(
                html.Div([
                    html.Span(f"Rules Engine: {firm_name} | Platform: {platform} | Model: {dd_type}", className="fw-bold text-light"),
                    html.Div(badge, className="float-end"),
                ]),
                className="bg-black border-secondary py-2",
            ),
            dbc.CardBody([
                # Futures incompatibility warning if applicable
                dbc.Alert(
                    [html.I(className="bi bi-exclamation-triangle-fill me-2"), firm_warnings[0]],
                    color="warning",
                    className="py-2 mb-3 small",
                ) if not mt5_comp and firm_warnings else html.Div(),

                dbc.Row([
                    dbc.Col([
                        html.P("Cumulative Portfolio Exposure (Unhedged vs. Correlation-Adjusted):", className="text-secondary mb-1"),
                        html.H5([
                            html.Span(f"${total_risk_usd:,.2f} (${total_risk_pct:.2f}%)", className="text-light fw-bold"),
                            html.Small(f" | Corr-Adj: ${adj_risk_usd:,.2f} ({adj_risk_pct:.2f}%)", className="text-info ms-2"),
                        ]),
                        dbc.Progress(
                            value=min(total_risk_pct * 25.0, 100),
                            color="danger" if total_risk_pct > 3.0 else ("warning" if total_risk_pct > 1.5 else "success"),
                            className="mt-2",
                            style={"height": "8px"},
                        ),
                    ], width=12, md=6),
                    dbc.Col([
                        html.P("Drawdown Safety Distance:", className="text-secondary mb-1"),
                        html.H5(
                            f"{max_rem_pct:.2f}% buffer to account disqualification floor",
                            className="text-light fw-bold",
                        ),
                        dbc.Progress(
                            value=max(0, 100 - (max_rem_pct * 10.0)),
                            color="success" if max_rem_pct > 6.0 else ("warning" if max_rem_pct > 3.0 else "danger"),
                            className="mt-2",
                            style={"height": "8px"},
                        ),
                    ], width=12, md=6),
                ]),

                # Currency Exposure Cards
                html.Hr(className="border-secondary my-3"),
                html.H6("MULTI-ASSET CURRENCY & COMMODITY NET EXPOSURE BREAKDOWN", className="text-secondary small fw-bold mb-2"),
                dbc.Row(curr_rows, className="g-1 mb-2") if curr_rows else html.Small("No open multi-asset currency commitments.", className="text-muted"),

                # High correlation pair alerts
                html.Div([
                    dbc.Alert(
                        f"Overlapping Portfolio Risk: {p['symbol_1']} and {p['symbol_2']} have strong correlation ({p['correlation']:+.2f}). "
                        "Avoid treating simultaneous positions as independent risks.",
                        color="warning",
                        className="py-1 px-2 mb-1 small",
                    ) for p in high_corr_pairs
                ], className="mt-2") if high_corr_pairs else html.Div(),
            ], className="bg-dark"),
        ], className="border-secondary mb-4"),
    ])


def build_position_monitor(
    open_positions: list[dict[str, Any]],
    lifecycle_states: Optional[list[dict[str, Any]]] = None,
) -> html.Div:
    """
    Construct the active open positions and thesis health monitor table for all MT5 instruments.
    """
    if not open_positions:
        return dbc.Card([
            dbc.CardHeader("Open Positions & Trade Lifecycle Monitor (MT5 Multi-Asset)", className="fw-bold bg-black text-light"),
            dbc.CardBody(
                html.P("No open positions currently active in MetaTrader 5.", className="text-secondary mb-0 text-center py-4"),
                className="bg-dark",
            ),
        ], className="border-secondary mb-4")

    rows = []
    for pos in open_positions:
        ticket = pos.get("ticket", "")
        sym = str(pos.get("symbol", "UNKNOWN")).upper()
        vol = float(pos.get("volume", 0.0))
        direction = "BUY" if str(pos.get("type")).upper() in ("0", "BUY") else "SELL"
        open_price = float(pos.get("open_price", 0.0))
        sl = float(pos.get("sl", 0.0))
        tp = float(pos.get("tp", 0.0))
        profit = float(pos.get("profit", 0.0))

        spec = InstrumentDiscovery.get_fallback_spec(sym)
        digits = spec.digits
        fmt = f".{digits}f"

        color = "#00ff88" if profit >= 0 else "#ff4466"

        rows.append(html.Tr([
            html.Td(str(ticket), className="text-secondary"),
            html.Td(dbc.Badge(sym, color="info", className="fw-bold")),
            html.Td(dbc.Badge(direction, color="success" if direction == "BUY" else "danger")),
            html.Td(f"{vol:.2f}", className="text-light"),
            html.Td(f"{open_price:{fmt}}", className="text-light"),
            html.Td(f"{sl:{fmt}}" if sl > 0 else "NONE", className="text-danger" if sl == 0 else "text-secondary"),
            html.Td(f"{tp:{fmt}}" if tp > 0 else "NONE", className="text-secondary"),
            html.Td(
                f"{'+' if profit >= 0 else ''}${profit:,.2f}",
                style={"color": color, "fontWeight": "bold"},
            ),
            html.Td(
                dbc.Badge("Thesis Intact", color="success") if profit >= 0 else dbc.Badge("Monitoring", color="warning"),
            ),
        ]))

    table = dbc.Table([
        html.Thead(
            html.Tr([
                html.Th("Ticket"),
                html.Th("Symbol"),
                html.Th("Side"),
                html.Th("Lots"),
                html.Th("Entry"),
                html.Th("SL"),
                html.Th("TP"),
                html.Th("Floating P&L"),
                html.Th("Thesis State"),
            ]),
            className="text-secondary",
        ),
        html.Tbody(rows),
    ], responsive=True, hover=True, className="mb-0 align-middle")

    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.Span("Open Positions & Trade Lifecycle Monitor (MT5 Read-Only)", className="fw-bold text-light"),
                html.Small(f" — {len(open_positions)} active position(s) across all instruments", className="text-secondary ms-2"),
            ]),
            className="bg-black border-secondary py-2",
        ),
        dbc.CardBody(table, className="bg-dark p-0"),
    ], className="border-secondary mb-4")
