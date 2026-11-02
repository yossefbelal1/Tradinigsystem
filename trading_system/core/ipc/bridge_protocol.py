"""
core/ipc/bridge_protocol.py
===========================
Structured Protocol Definitions for Bidirectional MT5 <-> Python IPC.
Handles active chart context synchronization, on-demand analysis requests,
and visual rendering payloads.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional


@dataclass
class ChartContextMessage:
    """Telemetry transmitted from the MT5 active chart EA."""
    chart_id: int
    symbol: str
    period: str
    period_minutes: int
    bid: float
    ask: float
    spread_points: int
    digits: int
    timestamp: str
    action: str = "CHART_SYNC"  # "CHART_SYNC", "REQUEST_ANALYSIS", "HEARTBEAT"
    auto_sync: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChartContextMessage:
        return cls(
            chart_id=int(data.get("chart_id", 0)),
            symbol=str(data.get("symbol", "XAUUSD")),
            period=str(data.get("period", "H1")),
            period_minutes=int(data.get("period_minutes", 60)),
            bid=float(data.get("bid", 0.0)),
            ask=float(data.get("ask", 0.0)),
            spread_points=int(data.get("spread_points", 0)),
            digits=int(data.get("digits", 2)),
            timestamp=str(data.get("timestamp", "")),
            action=str(data.get("action", "CHART_SYNC")),
            auto_sync=bool(data.get("auto_sync", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SRLevelPayload:
    price: float
    type: str  # "SUPPORT" or "RESISTANCE"
    timeframe: str
    label: str = ""


@dataclass
class ZonePayload:
    type: str  # "DEMAND" or "SUPPLY"
    top: float
    bottom: float
    state: str  # "FRESH", "TESTED", "MITIGATED"
    timeframe: str


@dataclass
class TradeBlueprintPayload:
    direction: str  # "BUY", "SELL", "NEUTRAL"
    setup_quality: str  # "A+", "A", "B", "C", "D"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    position_size_lots: float
    monetary_risk_usd: float
    risk_reward_tp1: float
    is_valid: bool = True
    invalidation_reason: Optional[str] = None


@dataclass
class AnalysisResponseMessage:
    """Full analytical synthesis sent back to MT5 to plot on active chart."""
    chart_id: int
    symbol: str
    period: str
    timestamp: str
    overall_bias: str  # "BULLISH", "BEARISH", "NEUTRAL"
    bias_strength: float
    levels: list[dict[str, Any]] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    trade_plan: Optional[dict[str, Any]] = None
    candle_expectation: str = ""
    status: str = "SUCCESS"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisResponseMessage:
        return cls(
            chart_id=int(data.get("chart_id", 0)),
            symbol=str(data.get("symbol", "")),
            period=str(data.get("period", "")),
            timestamp=str(data.get("timestamp", "")),
            overall_bias=str(data.get("overall_bias", "NEUTRAL")),
            bias_strength=float(data.get("bias_strength", 0.0)),
            levels=list(data.get("levels", [])),
            zones=list(data.get("zones", [])),
            trade_plan=data.get("trade_plan"),
            candle_expectation=str(data.get("candle_expectation", "")),
            status=str(data.get("status", "SUCCESS")),
        )
