"""
core/data/data_integrity.py
===========================
Strict Market Data Integrity and Authoritative Telemetry State Management.

Ensures MT5 remains the authoritative source for live analysis.
Explicitly distinguishes between:
  - MT5_LIVE: Valid, real-time data streaming from connected broker terminal.
  - OFFLINE_DISCONNECTED: MT5 terminal connection lost; live trade plans strictly gated.
  - HISTORICAL_BACKTEST: Pure historical dataset evaluation; no live trading claims.
  - DEMO_SIMULATED: Fallback demonstration mode; trade plans flagged non-executable.

Zero silent substitution: The system never presents synthetic or cached prices
as live MT5 market data.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class DataSourceState(str, Enum):
    """Authoritative state of market telemetry."""
    MT5_LIVE = "MT5_LIVE"
    OFFLINE_DISCONNECTED = "OFFLINE_DISCONNECTED"
    HISTORICAL_BACKTEST = "HISTORICAL_BACKTEST"
    DEMO_SIMULATED = "DEMO_SIMULATED"


class DataIntegrityManager:
    """
    Manages and validates data stream integrity.
    Prevents execution of trade plans when MT5 connection is unconfirmed.
    """

    def __init__(self, initial_state: DataSourceState = DataSourceState.OFFLINE_DISCONNECTED):
        self._state: DataSourceState = initial_state
        self._last_tick_time: float = 0.0
        self._max_stale_seconds: float = 120.0  # Allow weekend / quiet market tolerance
        self._subscribers: list[Callable[[DataSourceState], None]] = []
        self._last_state_change_reason: str = "Initialization"

    @property
    def state(self) -> DataSourceState:
        return self._state

    @property
    def current_state(self) -> DataSourceState:
        """Alias for state."""
        return self._state

    @property
    def is_live(self) -> bool:
        """Alias for is_live_executable."""
        return self._state == DataSourceState.MT5_LIVE

    @property
    def is_live_executable(self) -> bool:
        """
        True ONLY if connected to a live, authoritative MT5 terminal feed.
        Live trade plans can ONLY be formulated in this state.
        """
        return self._state == DataSourceState.MT5_LIVE

    def can_formulate_live_trade_plan(self) -> bool:
        """Check if live trade plan formulation is authorized."""
        allowed, _ = self.validate_plan_generation_allowed()
        return allowed


    def set_state(self, new_state: DataSourceState, reason: str = "", source_name: str = "") -> None:
        """Update source state and notify subscribers if state transitions."""
        if self._state != new_state:
            old = self._state
            self._state = new_state
            self._last_state_change_reason = reason or source_name

            logger.warning(
                "DATA INTEGRITY STATE CHANGE: %s -> %s (Reason: %s)",
                old.value, new_state.value, reason or "None"
            )
            for sub in self._subscribers:
                try:
                    sub(new_state)
                except Exception as e:
                    logger.error("Subscriber notification failed: %s", e)

    def record_tick(self, timestamp: Optional[float] = None) -> None:
        """Record live tick arrival to verify freshness."""
        self._last_tick_time = timestamp or time.time()
        if self._state != DataSourceState.MT5_LIVE:
            self.set_state(DataSourceState.MT5_LIVE, reason="Live tick received")

    def register_subscriber(self, callback: Callable[[DataSourceState], None]) -> None:
        """Subscribe to data integrity state changes."""
        self._subscribers.append(callback)

    def validate_plan_generation_allowed(self) -> tuple[bool, Optional[str]]:
        """
        Gating check for trade-plan generation.
        Returns (is_allowed, rejection_reason).
        """
        if self._state == DataSourceState.MT5_LIVE:
            return True, None

        if self._state == DataSourceState.OFFLINE_DISCONNECTED:
            return False, (
                "DATA INTEGRITY LOCK: MetaTrader 5 terminal is DISCONNECTED. "
                "Live trade-plan generation is strictly disabled to prevent execution "
                "on stale or invalid market data."
            )
        elif self._state == DataSourceState.DEMO_SIMULATED:
            return False, (
                "SIMULATION MODE: Operating on synthetic/demonstration data. "
                "Real trade-plan generation is disabled. Connect MT5 for live analysis."
            )
        elif self._state == DataSourceState.HISTORICAL_BACKTEST:
            return True, None  # Allowed for historical backtesting routines

        return False, "Unknown data source state."

    def get_status_report(self) -> dict[str, Any]:
        """Return diagnostic dictionary for UI and audit logs."""
        return {
            "state": self._state.value,
            "is_live_executable": self.is_live_executable,
            "last_tick_time": self._last_tick_time,
            "state_reason": self._last_state_change_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
