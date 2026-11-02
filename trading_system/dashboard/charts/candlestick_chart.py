"""
dashboard/charts/candlestick_chart.py
=====================================
Plotly-based Multi-Timeframe Candlestick Chart Engine.
Produces institutional-grade dark-themed charts with Support/Resistance levels,
Supply & Demand zone shading, swing markers, pattern callouts, and volume subplots.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading_system.dashboard.charts.zone_overlay import ZoneOverlayBuilder

logger = logging.getLogger(__name__)


class CandlestickChartBuilder:
    """
    Constructs high-fidelity, interactive technical analysis charts with clean overlays.
    """

    def __init__(self):
        self.overlay_builder = ZoneOverlayBuilder()

    def build_chart(
        self,
        df: pd.DataFrame,
        timeframe: str,
        analysis: dict[str, Any],
        trade_plan: Optional[dict[str, Any]] = None,
        max_bars: int = 150,
    ) -> go.Figure:
        """
        Assemble the complete 2-panel chart (Price + Volume) with all technical overlays.
        """
        if df.empty or len(df) < 5:
            fig = go.Figure()
            fig.update_layout(
                title=f"No data available for {timeframe}",
                template="plotly_dark",
                paper_bgcolor="#0a0a0f",
                plot_bgcolor="#0a0a0f",
            )
            return fig

        # Slice to recent window for responsive rendering
        plot_df = df.iloc[-max_bars:].copy().reset_index(drop=True)
        times = plot_df["time"] if "time" in plot_df.columns else plot_df.index
        x_start = times.iloc[0]
        x_end = times.iloc[-1]

        # ── 1. Create Subplots: Row 1 = Candlestick, Row 2 = Volume ──────────
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.80, 0.20],
        )

        # ── 2. Primary Candlestick Trace ─────────────────────────────────────
        candle_colors = [
            "#00ff88" if c >= o else "#ff4466"
            for o, c in zip(plot_df["open"], plot_df["close"])
        ]

        fig.add_trace(
            go.Candlestick(
                x=times,
                open=plot_df["open"],
                high=plot_df["high"],
                low=plot_df["low"],
                close=plot_df["close"],
                name="XAUUSD",
                increasing_line_color="#00ff88",
                increasing_fillcolor="#00ff88",
                decreasing_line_color="#ff4466",
                decreasing_fillcolor="#ff4466",
                hoverinfo="all",
            ),
            row=1, col=1,
        )

        # ── 3. EMA Overlays (20 & 50) ────────────────────────────────────────
        ema_20 = plot_df["close"].ewm(span=20, adjust=False).mean()
        ema_50 = plot_df["close"].ewm(span=50, adjust=False).mean()

        fig.add_trace(
            go.Scatter(x=times, y=ema_20, mode="lines", name="EMA 20", line=dict(color="#ffaa00", width=1.2)),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=times, y=ema_50, mode="lines", name="EMA 50", line=dict(color="#00d4ff", width=1.2)),
            row=1, col=1,
        )

        # ── 4. Volume Histogram Trace ────────────────────────────────────────
        if "volume" in plot_df.columns:
            fig.add_trace(
                go.Bar(
                    x=times,
                    y=plot_df["volume"],
                    name="Volume",
                    marker_color=candle_colors,
                    opacity=0.65,
                ),
                row=2, col=1,
            )

        # ── 5. Technical Overlays (Zones, S/R, Trade Plan) ───────────────────
        all_shapes: list[dict[str, Any]] = []
        all_annotations: list[dict[str, Any]] = []

        # Supply & Demand Zones
        all_zones = analysis.get("supply_zones", []) + analysis.get("demand_zones", [])
        zone_shapes = self.overlay_builder.create_zone_shapes(all_zones, x_start, x_end)
        all_shapes.extend(zone_shapes)

        # S/R Levels
        sr_levels = analysis.get("sr_levels", [])
        sr_shapes, sr_annot = self.overlay_builder.create_sr_lines(sr_levels, x_start, x_end)
        all_shapes.extend(sr_shapes)
        all_annotations.extend(sr_annot)

        # Trade Plan (if provided)
        if trade_plan:
            tp_shapes, tp_annot = self.overlay_builder.create_trade_plan_shapes(trade_plan, x_start, x_end)
            all_shapes.extend(tp_shapes)
            all_annotations.extend(tp_annot)

        # ── 6. Forming Candle Indicator ──────────────────────────────────────
        is_forming = analysis.get("is_forming", False)
        if is_forming:
            all_annotations.append({
                "x": x_end,
                "y": float(plot_df["high"].iloc[-1]) + float(analysis.get("atr", 5.0)) * 0.4,
                "xref": "x",
                "yref": "y",
                "text": "FORMING BAR (Unconfirmed)",
                "showarrow": True,
                "arrowhead": 2,
                "arrowcolor": "#ffaa00",
                "font": {"size": 10, "color": "#ffaa00", "weight": "bold"},
                "bgcolor": "rgba(20, 20, 30, 0.9)",
            })

        # ── 7. Layout & Styling ──────────────────────────────────────────────
        bias = analysis.get("bias", "NEUTRAL")
        atr_val = analysis.get("atr", 0.0)

        fig.update_layout(
            title=dict(
                text=f"<b>XAUUSD {timeframe}</b> | Bias: <span style='color:{'#00ff88' if bias=='BULLISH' else ('#ff4466' if bias=='BEARISH' else '#ffaa00')}'>{bias}</span> | ATR: ${atr_val:.2f}",
                font=dict(size=15, color="#e0e0f0"),
            ),
            template="plotly_dark",
            paper_bgcolor="#0a0a0f",
            plot_bgcolor="#12121a",
            xaxis_rangeslider_visible=False,
            shapes=all_shapes,
            annotations=all_annotations,
            margin=dict(l=40, r=80, t=50, b=30),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1.0,
                font=dict(size=10),
            ),
            yaxis=dict(
                title="Price (USD)",
                gridcolor="#1e1e2e",
                showgrid=True,
                zeroline=False,
            ),
            yaxis2=dict(
                title="Vol",
                gridcolor="#1e1e2e",
                showgrid=False,
            ),
            xaxis=dict(
                gridcolor="#1e1e2e",
                showgrid=True,
            ),
        )

        return fig
