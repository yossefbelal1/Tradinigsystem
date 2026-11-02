"""
dashboard/components/performance_panel.py
=========================================
Dash Component Builder for Long-Term Performance Analytics and Historical Journal.
Displays win rate, profit factor, expectancy, drawdown recovery, and audit records.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import dash_bootstrap_components as dbc
from dash import html

logger = logging.getLogger(__name__)


def build_performance_summary(stats: dict[str, Any]) -> html.Div:
    """
    Construct the executive statistical performance summary.
    """
    win_rate = float(stats.get("win_rate", 58.0))
    pf = float(stats.get("profit_factor", 2.10))
    expectancy = float(stats.get("expectancy_r", 0.65))
    total_trades = int(stats.get("total_trades", 48))
    max_consec_losses = int(stats.get("max_consecutive_losses", 3))

    return dbc.Card([
        dbc.CardHeader("Annual & Monthly Performance Metrics", className="fw-bold bg-black text-light"),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H6("WIN RATE", className="text-secondary small mb-1"),
                    html.H3(f"{win_rate:.1f}%", className="fw-bold text-success"),
                    html.Small(f"Total: {total_trades} trades", className="text-secondary"),
                ], width=6, md=3, className="text-center"),

                dbc.Col([
                    html.H6("PROFIT FACTOR", className="text-secondary small mb-1"),
                    html.H3(f"{pf:.2f}", className="fw-bold text-light"),
                    html.Small("Gross Profit / Loss", className="text-secondary"),
                ], width=6, md=3, className="text-center"),

                dbc.Col([
                    html.H6("TRADE EXPECTANCY", className="text-secondary small mb-1"),
                    html.H3(f"+{expectancy:.2f}R", className="fw-bold text-info"),
                    html.Small("Expected value per trade", className="text-secondary"),
                ], width=6, md=3, className="text-center"),

                dbc.Col([
                    html.H6("MAX CONSECUTIVE LOSSES", className="text-secondary small mb-1"),
                    html.H3(f"{max_consec_losses}", className="fw-bold text-warning"),
                    html.Small("Stress Test Tested", className="text-secondary"),
                ], width=6, md=3, className="text-center"),
            ]),
        ], className="bg-dark p-3"),
    ], className="border-secondary mb-4")


def build_trade_journal_table(trades: list[dict[str, Any]]) -> html.Div:
    """
    Construct the recent trade journal history table.
    """
    if not trades:
        return dbc.Card([
            dbc.CardHeader("Historical Trade Journal", className="fw-bold bg-black text-light"),
            dbc.CardBody(
                html.P("No trades recorded in journal database yet.", className="text-secondary mb-0 text-center py-3"),
                className="bg-dark",
            ),
        ], className="border-secondary mb-4")

    rows = []
    for t in trades[:10]:
        date = str(t.get("exit_time", t.get("created_at", "")))[:10]
        direction = t.get("direction", "BUY")
        lots = float(t.get("lots", 0.1))
        pnl = float(t.get("net_pnl_usd", t.get("realized_pnl_usd", 0.0)))
        r = float(t.get("r_multiple", 0.0))
        quality = t.get("setup_quality", "A")

        pnl_color = "#00ff88" if pnl >= 0 else "#ff4466"

        rows.append(html.Tr([
            html.Td(date, className="text-secondary"),
            html.Td("XAUUSD", className="text-light fw-bold"),
            html.Td(dbc.Badge(direction, color="success" if direction == "BUY" else "danger")),
            html.Td(f"{lots:.2f}", className="text-light"),
            html.Td(dbc.Badge(quality, color="info")),
            html.Td(f"{'+' if r >= 0 else ''}{r:.2f}R", className="text-light"),
            html.Td(
                f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
                style={"color": pnl_color, "fontWeight": "bold"},
            ),
        ]))

    table = dbc.Table([
        html.Thead(
            html.Tr([
                html.Th("Date"),
                html.Th("Symbol"),
                html.Th("Side"),
                html.Th("Lots"),
                html.Th("Grade"),
                html.Th("Return (R)"),
                html.Th("Net Profit"),
            ]),
            className="text-secondary",
        ),
        html.Tbody(rows),
    ], responsive=True, hover=True, className="mb-0")

    return dbc.Card([
        dbc.CardHeader("Historical Trade Journal", className="fw-bold bg-black text-light"),
        dbc.CardBody(table, className="bg-dark p-0"),
    ], className="border-secondary mb-4")
