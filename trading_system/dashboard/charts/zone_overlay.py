"""
dashboard/charts/zone_overlay.py
================================
Plotly shape generator for Support/Resistance, Supply/Demand zones, and Trade Plans.
Formats clean, uncluttered visual overlays for financial charts.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ZoneOverlayBuilder:
    """
    Constructs Plotly shape definitions and text annotations for technical levels and zones.
    """

    def create_zone_shapes(
        self,
        zones: list[dict[str, Any]],
        x_start: Any,
        x_end: Any,
    ) -> list[dict[str, Any]]:
        """
        Generate rectangle shapes for Supply (red) and Demand (green) zones.
        """
        shapes: list[dict[str, Any]] = []

        for z in zones[:6]:  # Limit to 6 most relevant to prevent clutter
            z_type = z.get("type", "DEMAND")
            top = float(z["top"])
            bottom = float(z["bottom"])

            if z_type == "SUPPLY":
                fill_color = "rgba(255, 68, 102, 0.18)"
                line_color = "rgba(255, 68, 102, 0.6)"
            else:
                fill_color = "rgba(0, 255, 136, 0.18)"
                line_color = "rgba(0, 255, 136, 0.6)"

            shapes.append({
                "type": "rect",
                "xref": "x",
                "yref": "y",
                "x0": x_start,
                "x1": x_end,
                "y0": bottom,
                "y1": top,
                "fillcolor": fill_color,
                "line": {"color": line_color, "width": 1, "dash": "dot"},
                "layer": "below",
            })

        return shapes

    def create_sr_lines(
        self,
        sr_levels: list[dict[str, Any]],
        x_start: Any,
        x_end: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Generate horizontal lines and label annotations for Support/Resistance levels.
        """
        shapes: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []

        for sr in sr_levels[:10]:
            price = float(sr["price"])
            is_major = sr.get("is_major", False)
            lvl_type = sr.get("type", "S/R")

            line_color = "rgba(0, 212, 255, 0.75)" if is_major else "rgba(160, 160, 180, 0.4)"
            dash_style = "solid" if is_major else "dash"
            width = 1.5 if is_major else 1.0

            shapes.append({
                "type": "line",
                "xref": "x",
                "yref": "y",
                "x0": x_start,
                "x1": x_end,
                "y0": price,
                "y1": price,
                "line": {"color": line_color, "width": width, "dash": dash_style},
                "layer": "below",
            })

            # Right-aligned text tag
            annotations.append({
                "x": x_end,
                "y": price,
                "xref": "x",
                "yref": "y",
                "text": f"{lvl_type} {price:.2f}",
                "showarrow": False,
                "xanchor": "left",
                "yanchor": "middle",
                "font": {"size": 10, "color": line_color},
                "bgcolor": "rgba(18, 18, 26, 0.7)",
            })

        return shapes, annotations

    def create_trade_plan_shapes(
        self,
        plan: dict[str, Any],
        x_start: Any,
        x_end: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Generate visual overlays for Entry, Stop Loss, and Take Profit targets.
        """
        shapes: list[dict[str, Any]] = []
        annotations: list[dict[str, Any]] = []

        entry = float(plan.get("entry_price", 0.0))
        sl = float(plan.get("stop_loss", 0.0))
        tp1 = float(plan.get("take_profit_1", 0.0))
        tp2 = float(plan.get("take_profit_2", 0.0))

        if entry <= 0:
            return shapes, annotations

        # Entry line (Cyan)
        shapes.append({
            "type": "line", "xref": "x", "yref": "y", "x0": x_start, "x1": x_end,
            "y0": entry, "y1": entry,
            "line": {"color": "#00d4ff", "width": 2, "dash": "solid"},
        })
        annotations.append({
            "x": x_end, "y": entry, "xref": "x", "yref": "y",
            "text": f"ENTRY: ${entry:.2f}", "showarrow": False, "xanchor": "left",
            "font": {"size": 11, "color": "#00d4ff", "weight": "bold"},
            "bgcolor": "#12121a",
        })

        # Stop Loss line (Red)
        if sl > 0:
            shapes.append({
                "type": "line", "xref": "x", "yref": "y", "x0": x_start, "x1": x_end,
                "y0": sl, "y1": sl,
                "line": {"color": "#ff4466", "width": 2, "dash": "dash"},
            })
            annotations.append({
                "x": x_end, "y": sl, "xref": "x", "yref": "y",
                "text": f"STOP LOSS: ${sl:.2f}", "showarrow": False, "xanchor": "left",
                "font": {"size": 11, "color": "#ff4466", "weight": "bold"},
                "bgcolor": "#12121a",
            })

        # Take Profit 1 (Green)
        if tp1 > 0:
            shapes.append({
                "type": "line", "xref": "x", "yref": "y", "x0": x_start, "x1": x_end,
                "y0": tp1, "y1": tp1,
                "line": {"color": "#00ff88", "width": 2, "dash": "dot"},
            })
            annotations.append({
                "x": x_end, "y": tp1, "xref": "x", "yref": "y",
                "text": f"TP1: ${tp1:.2f} (1.5R)", "showarrow": False, "xanchor": "left",
                "font": {"size": 11, "color": "#00ff88", "weight": "bold"},
                "bgcolor": "#12121a",
            })

        # Take Profit 2 (Green)
        if tp2 > 0:
            shapes.append({
                "type": "line", "xref": "x", "yref": "y", "x0": x_start, "x1": x_end,
                "y0": tp2, "y1": tp2,
                "line": {"color": "#00ff88", "width": 1.5, "dash": "dot"},
            })
            annotations.append({
                "x": x_end, "y": tp2, "xref": "x", "yref": "y",
                "text": f"TP2: ${tp2:.2f} (2.5R)", "showarrow": False, "xanchor": "left",
                "font": {"size": 11, "color": "#00ff88"},
                "bgcolor": "#12121a",
            })

        return shapes, annotations
