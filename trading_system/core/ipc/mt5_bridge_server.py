"""
core/ipc/mt5_bridge_server.py
=============================
Bidirectional IPC Server connecting MetaTrader 5 Active Charts with Python Engine.

Supports:
- Robust File-Based IPC in MT5 Common Data Path (zero DLL, native sandbox compliant).
- Dual-mode TCP Socket Server on 127.0.0.1:8765 for zero-latency streaming.
- Full Top-Down Multi-Timeframe Analysis triggered directly from the MT5 chart button.
- Seamless transmission of S/R levels, Supply/Demand zones, and Trade Blueprints back to MT5.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from trading_system.core.data.data_provider import DataProvider
from trading_system.core.data.instrument_spec import InstrumentDiscovery
from trading_system.core.data.mt5_connector import MT5Connector
from trading_system.core.data.symbol_specs import SymbolSpecs
from trading_system.core.ipc.bridge_protocol import (
    AnalysisResponseMessage,
    ChartContextMessage,
)
from trading_system.core.mtf.bias_synthesizer import BiasSynthesizer
from trading_system.core.mtf.conflict_detector import ConflictDetector
from trading_system.core.mtf.timeframe_analyzer import TimeframeAnalyzer
from trading_system.risk.position_sizing.calculator import PositionSizeCalculator
from trading_system.risk.prop_firm.rules_engine import PropFirmRulesEngine

logger = logging.getLogger(__name__)


def get_mt5_common_path() -> Path:
    """Resolve the MT5 Terminal Common Files directory."""
    appdata = os.getenv("APPDATA")
    if appdata:
        p = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    else:
        p = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
    p.mkdir(parents=True, exist_ok=True)
    return p


class MT5BridgeServer:
    """
    Server managing communication with the MQL5 Companion on active MT5 charts.
    """

    def __init__(
        self,
        mt5_connector: Optional[MT5Connector] = None,
        data_provider: Optional[DataProvider] = None,
        prop_firm_name: str = "ftmo_2step",
        poll_interval_s: float = 0.5,
        enable_socket: bool = True,
        socket_port: int = 8765,
    ):
        self.mt5 = mt5_connector
        self.data_provider = data_provider or DataProvider(mt5_connector=self.mt5)
        self.tf_analyzer = TimeframeAnalyzer()
        self.conflict_detector = ConflictDetector()
        self.bias_synthesizer = BiasSynthesizer()
        self.pos_calculator = PositionSizeCalculator()
        self.prop_firm = PropFirmRulesEngine(prop_firm_name)

        self.poll_interval_s = poll_interval_s
        self.enable_socket = enable_socket
        self.socket_port = socket_port

        # Common directories
        self.common_root = get_mt5_common_path() / "agy_bridge"
        self.inbox = self.common_root / "inbox"
        self.outbox = self.common_root / "outbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)

        # State tracking
        self.active_charts: dict[int, ChartContextMessage] = {}
        self.last_analyzed_chart: Optional[int] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket_thread: Optional[threading.Thread] = None
        self._subscribers: list[Callable[[ChartContextMessage, AnalysisResponseMessage], None]] = []

    def start(self) -> None:
        """Start the background IPC worker threads."""
        if self._running:
            return
        self._running = True

        # 1. Start File IPC Watcher Thread
        self._thread = threading.Thread(target=self._file_watcher_loop, daemon=True, name="MT5FileIPC")
        self._thread.start()
        logger.info("MT5 File-Based Bridge started (Inbox: %s)", self.inbox)

        # 2. Start Socket Listener Thread (if enabled)
        if self.enable_socket:
            self._socket_thread = threading.Thread(target=self._socket_listener_loop, daemon=True, name="MT5SocketIPC")
            self._socket_thread.start()
            logger.info("MT5 Socket Bridge listening on 127.0.0.1:%d", self.socket_port)

    def stop(self) -> None:
        """Stop background IPC threads cleanly."""
        self._running = False
        logger.info("MT5 Bridge Server stopped.")

    def register_callback(self, cb: Callable[[ChartContextMessage, AnalysisResponseMessage], None]) -> None:
        """Register a callback invoked when an active chart is analyzed."""
        self._subscribers.append(cb)

    # ── File-Based IPC Watcher ────────────────────────────────────────────────

    def _file_watcher_loop(self) -> None:
        """Continuously check inbox for chart requests from MQL5."""
        while self._running:
            try:
                for req_file in list(self.inbox.glob("*.json")):
                    try:
                        self._process_request_file(req_file)
                    except Exception as e:
                        logger.error("Error processing request file %s: %s", req_file.name, e)
                        try:
                            req_file.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception as e:
                logger.error("Error in file watcher loop: %s", e)
            time.sleep(self.poll_interval_s)

    def _process_request_file(self, file_path: Path) -> None:
        """Read and process an incoming chart request file."""
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            return

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return

        ctx = ChartContextMessage.from_dict(data)
        self.active_charts[ctx.chart_id] = ctx
        logger.info(
            "MT5 Active Chart Event: [%s %s | ChartID: %d | Action: %s]",
            ctx.symbol, ctx.period, ctx.chart_id, ctx.action
        )

        # Execute Top-Down Analysis
        response = self.execute_chart_analysis(ctx)

        # Write response to outbox
        resp_file = self.outbox / f"analysis_{ctx.symbol}_{ctx.chart_id}.json"
        resp_file.write_text(response.to_json(), encoding="utf-8")

        # Also write a generic symbol file for quick polling
        sym_file = self.outbox / f"analysis_{ctx.symbol}.json"
        sym_file.write_text(response.to_json(), encoding="utf-8")

        self.last_analyzed_chart = ctx.chart_id

        # Notify callbacks
        for cb in self._subscribers:
            try:
                cb(ctx, response)
            except Exception as e:
                logger.error("Error notifying bridge callback: %s", e)

        # Remove processed request
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Socket IPC Listener ───────────────────────────────────────────────────

    def _socket_listener_loop(self) -> None:
        """Optional socket server for real-time JSON exchange."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind(("127.0.0.1", self.socket_port))
            server_sock.listen(5)
            server_sock.settimeout(1.0)
        except Exception as e:
            logger.warning("Could not bind MT5 bridge socket server to port %d: %s", self.socket_port, e)
            return

        while self._running:
            try:
                client, addr = server_sock.accept()
                threading.Thread(target=self._handle_socket_client, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error("Socket accept error: %s", e)

        server_sock.close()

    def _handle_socket_client(self, client: socket.socket) -> None:
        try:
            client.settimeout(5.0)
            data_raw = client.recv(65536).decode("utf-8")
            if data_raw.strip():
                data = json.loads(data_raw)
                ctx = ChartContextMessage.from_dict(data)
                self.active_charts[ctx.chart_id] = ctx
                response = self.execute_chart_analysis(ctx)
                client.sendall(response.to_json().encode("utf-8"))
        except Exception as e:
            logger.debug("Socket client handle exception: %s", e)
        finally:
            try:
                client.close()
            except Exception:
                pass

    # ── Core Analysis Execution ───────────────────────────────────────────────

    def execute_chart_analysis(self, ctx: ChartContextMessage) -> AnalysisResponseMessage:
        """
        Execute full multi-timeframe analysis for target active chart.
        Constructs S/R levels, zones, and trade plan blueprint.
        """
        symbol = ctx.symbol
        period = ctx.period

        # 1. Fetch multi-timeframe market data
        tf_data = self.data_provider.get_all_timeframes(symbol)
        tf_analyses: dict[str, dict[str, Any]] = {}

        for tf, df in tf_data.items():
            if not df.empty:
                tf_analyses[tf] = self.tf_analyzer.analyze(tf, df)

        # 2. Detect conflicts & synthesize top-down bias
        conflicts = self.conflict_detector.detect_conflicts(tf_analyses)
        synthesis = self.bias_synthesizer.synthesize(tf_analyses, conflicts)

        # 3. Extract visible levels and zones for on-chart plotting
        levels_payload = []
        zones_payload = []

        # Pull levels from primary intermediate timeframes (D1, H4, H1)
        for tf_key in ("D1", "H4", "H1"):
            analysis = tf_analyses.get(tf_key, {})
            # S/R levels
            for lvl in analysis.get("sr_levels", []):
                p = float(lvl.get("price", 0.0))
                l_type = lvl.get("type", "SUPPORT")
                if p > 0:
                    levels_payload.append({
                        "price": p,
                        "type": l_type,
                        "timeframe": tf_key,
                        "label": f"{tf_key} {l_type} ({p:.5g})",
                    })

            # Supply / Demand zones
            for z in analysis.get("supply_demand_zones", []):
                top = float(z.get("high", z.get("top", 0.0)))
                bot = float(z.get("low", z.get("bottom", 0.0)))
                z_type = z.get("type", "DEMAND")
                state = z.get("state", "FRESH")
                if top > 0 and bot > 0:
                    zones_payload.append({
                        "type": z_type,
                        "top": top,
                        "bottom": bot,
                        "state": state,
                        "timeframe": tf_key,
                    })

        # 4. Formulate Actionable Trade Plan (if setup is valid)
        trade_plan_payload = None
        is_live = self.data_provider.is_live_executable
        signal = synthesis.get("signal", "NO_TRADE")

        if is_live and signal in ("BUY_OPPORTUNITY", "SELL_OPPORTUNITY"):
            plan = self._formulate_trade_plan(symbol, synthesis, tf_analyses, ctx)
            if plan:
                trade_plan_payload = plan

        return AnalysisResponseMessage(
            chart_id=ctx.chart_id,
            symbol=symbol,
            period=period,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            overall_bias=synthesis.get("overall_bias", "NEUTRAL"),
            bias_strength=round(float(synthesis.get("bias_strength", 0.0)), 2),
            levels=levels_payload[:10],  # Top 10 cleanest levels
            zones=zones_payload[:6],    # Top 6 most relevant zones
            trade_plan=trade_plan_payload,
            candle_expectation=synthesis.get("narrative", ""),
            status="SUCCESS",
        )

    def _formulate_trade_plan(
        self,
        symbol: str,
        synthesis: dict[str, Any],
        tf_analyses: dict[str, dict[str, Any]],
        ctx: ChartContextMessage,
    ) -> Optional[dict[str, Any]]:
        """Formulate mathematically justified Trade Plan with exact broker lot sizing."""
        spec = InstrumentDiscovery.get_fallback_spec(symbol)
        digits = spec.digits
        current_price = ctx.ask if ctx.ask > 0 else (ctx.bid if ctx.bid > 0 else self.data_provider.get_current_price(symbol))
        h1 = tf_analyses.get("H1", {})
        atr = float(h1.get("atr", current_price * 0.005))
        if atr <= 0:
            atr = current_price * 0.005

        direction = "BUY" if synthesis.get("signal") == "BUY_OPPORTUNITY" else "SELL"

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

        # Get Account Telemetry
        if self.mt5 and self.mt5.is_connected():
            acct = self.mt5.get_account_info()
        else:
            acct = {"equity": 100000.0, "balance": 100000.0}

        equity = float(acct.get("equity", 100000.0))
        self.prop_firm.update_account_state(acct)
        limits = self.prop_firm.get_current_limits(acct)

        # Dynamic risk budget calculation (NEVER hardcoded $1,000!)
        desired_risk = equity * 0.01  # 1% standard
        safe_risk = min(desired_risk, limits["daily_loss_remaining_usd"] * 0.70, limits["remaining_drawdown_usd"] * 0.75)
        if safe_risk <= 0:
            return None

        # Position sizing via order_calc_profit or specs
        lots, monetary_risk = self._calculate_lots(symbol, direction, entry, sl, safe_risk, spec)

        return {
            "direction": direction,
            "setup_quality": synthesis.get("setup_quality", "A"),
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "position_size_lots": lots,
            "monetary_risk_usd": round(monetary_risk, 2),
            "risk_reward_tp1": 1.5,
            "is_valid": lots >= spec.volume_min,
            "invalidation_reason": None if lots >= spec.volume_min else "Volume below broker minimum",
        }

    def _calculate_lots(
        self,
        symbol: str,
        direction: str,
        entry: float,
        sl: float,
        target_risk_usd: float,
        spec: Any,
    ) -> tuple[float, float]:
        """Compute exact lots using MT5 order_calc_profit if available."""
        if self.mt5 and self.mt5.is_connected():
            try:
                import MetaTrader5 as mt5
                action = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
                loss_1lot = abs(mt5.order_calc_profit(action, symbol, 1.0, entry, sl) or 0.0)
                if loss_1lot > 0:
                    raw_lots = target_risk_usd / loss_1lot
                    lots = round(int(raw_lots / spec.volume_step) * spec.volume_step, 2)
                    lots = max(spec.volume_min, min(spec.volume_max, lots))
                    actual_risk = lots * loss_1lot
                    return lots, actual_risk
            except Exception as e:
                logger.warning("order_calc_profit failed: %s. Falling back to analytical formula.", e)

        # Analytical fallback
        dist = abs(entry - sl)
        ticks = dist / spec.tick_size
        cost_per_lot = ticks * spec.tick_value
        if cost_per_lot <= 0:
            return spec.volume_min, target_risk_usd
        raw_lots = target_risk_usd / cost_per_lot
        lots = round(int(raw_lots / spec.volume_step) * spec.volume_step, 2)
        lots = max(spec.volume_min, min(spec.volume_max, lots))
        return lots, lots * cost_per_lot
