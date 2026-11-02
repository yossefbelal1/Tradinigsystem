"""
core/data/mt5_connector.py
==========================
Read-only MetaTrader 5 connector for the XAUUSD trading analysis system.

IMPORTANT: This module is STRICTLY READ-ONLY. It contains NO order
placement, modification, or cancellation functions whatsoever.

Features
--------
- Lazy MT5 import with graceful degradation when the library is not installed.
- Thread-safe connection state management.
- Automatic reconnection on detected drops.
- All timestamps returned as UTC-aware pandas Timestamps.
- Symbol info caching to minimise redundant API round-trips.
- Candle completion detection (CONFIRMED vs FORMING).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import pytz

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Optional MT5 import
# ─────────────────────────────────────────────────────────────────────────────

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
    logger.debug("MetaTrader5 library loaded successfully.")
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 library is NOT installed or not available on this platform. "
        "MT5Connector will raise RuntimeError on connect(). "
        "Install it with:  pip install MetaTrader5"
    )

# ─────────────────────────────────────────────────────────────────────────────
# MT5 Timeframe Mapping
# ─────────────────────────────────────────────────────────────────────────────

def _build_tf_map() -> dict[str, Any]:
    if not MT5_AVAILABLE:
        return {}
    return {
        "MN1": mt5.TIMEFRAME_MN1,
        "W1":  mt5.TIMEFRAME_W1,
        "D1":  mt5.TIMEFRAME_D1,
        "H4":  mt5.TIMEFRAME_H4,
        "H1":  mt5.TIMEFRAME_H1,
        "M30": mt5.TIMEFRAME_M30,
        "M15": mt5.TIMEFRAME_M15,
        "M5":  mt5.TIMEFRAME_M5,
        "M1":  mt5.TIMEFRAME_M1,
    }


MT5_TIMEFRAME_MAP: dict[str, Any] = _build_tf_map()

# Seconds in each timeframe — used for candle-completion detection
_TF_SECONDS: dict[str, int] = {
    "MN1": 30 * 24 * 3600,
    "W1":   7 * 24 * 3600,
    "D1":       24 * 3600,
    "H4":        4 * 3600,
    "H1":            3600,
    "M30":          1800,
    "M15":           900,
    "M5":            300,
    "M1":             60,
}


def _to_utc_timestamp(ts: Any) -> pd.Timestamp:
    """Convert an MT5 Unix timestamp (int) or datetime to UTC-aware Timestamp."""
    if isinstance(ts, (int, float)):
        return pd.Timestamp(ts, unit="s", tz="UTC")
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return pd.Timestamp(ts, tz="UTC")
        return pd.Timestamp(ts).tz_convert("UTC")
    return pd.Timestamp(ts, tz="UTC")


# ─────────────────────────────────────────────────────────────────────────────
# MT5Connector
# ─────────────────────────────────────────────────────────────────────────────


class MT5Connector:
    """
    Read-only MetaTrader 5 data connector.

    All methods that retrieve data are safe to call from background threads.
    No trade execution logic is present by design.

    Parameters
    ----------
    login:
        MT5 account number.
    password:
        MT5 account password.
    server:
        Broker server name (e.g. ``"ICMarkets-Demo"``).
    mt5_path:
        Full path to ``terminal64.exe``.
    reconnect_attempts:
        How many times to try reconnecting before giving up.
    reconnect_delay_s:
        Seconds to wait between reconnection attempts.
    """

    def __init__(
        self,
        login: Optional[int] = None,
        password: str = "",
        server: str = "",
        mt5_path: Optional[str] = None,
        path: Optional[str] = None,
        reconnect_attempts: int = 3,
        reconnect_delay_s: float = 5.0,
    ) -> None:
        if not MT5_AVAILABLE:
            raise RuntimeError(
                "MetaTrader5 is not installed. Run:  pip install MetaTrader5\n"
                "Note: MetaTrader5 is only available on Windows."
            )

        self._login = login or 0
        self._password = password or ""
        self._server = server or ""
        self._mt5_path = path or mt5_path or "C:/Program Files/MetaTrader 5/terminal64.exe"
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay_s = reconnect_delay_s

        self._connected: bool = False
        self._lock = threading.RLock()
        self._symbol_cache: dict[str, dict] = {}

    # ── Connection Management ─────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Initialise the MT5 terminal and log in.

        Returns
        -------
        bool
            ``True`` on success, ``False`` otherwise.
        """
        with self._lock:
            if self._connected and self.is_connected():
                logger.debug("Already connected to MT5.")
                return True

            logger.info("Connecting to MT5 terminal...")

            initialised = False
            # If explicit credentials provided and path exists, try them
            if self._login and self._password and self._server:
                initialised = mt5.initialize(
                    path=self._mt5_path,
                    login=self._login,
                    password=self._password,
                    server=self._server,
                    timeout=10_000,
                )

            # If not initialized or credentials omitted, attach to currently running terminal
            if not initialised:
                logger.info("Attempting attachment to MT5 terminal at %s...", self._mt5_path)
                try:
                    initialised = mt5.initialize(path=self._mt5_path, timeout=10_000)
                except Exception as e:
                    logger.warning("Attachment with path failed: %s", e)
                    initialised = False
                if not initialised:
                    logger.info("Retrying attachment without explicit path...")
                    try:
                        initialised = mt5.initialize(timeout=5_000)
                    except Exception:
                        initialised = False

            if not initialised:
                err = mt5.last_error()
                logger.error("MT5 initialisation failed: %s", err)
                self._connected = False
                return False

            # Verify account info is accessible
            account = mt5.account_info()
            if account is None:
                err = mt5.last_error()
                logger.error("MT5 login failed — cannot retrieve account info: %s", err)
                mt5.shutdown()
                self._connected = False
                return False

            self._connected = True
            term_info = mt5.terminal_info()
            term_path = term_info.path if term_info else "active"
            logger.info(
                "Connected to MT5 | Account: %s | Server: %s | Balance: %.2f %s | Path: %s",
                account.login,
                account.server,
                account.balance,
                account.currency,
                term_path,
            )
            return True

    def disconnect(self) -> None:
        """Cleanly shut down the MT5 connection."""
        with self._lock:
            if self._connected:
                mt5.shutdown()
                self._connected = False
                self._symbol_cache.clear()
                logger.info("Disconnected from MT5.")

    def is_connected(self) -> bool:
        """
        Check whether the MT5 terminal is reachable.

        Performs a lightweight ``account_info()`` probe rather than relying
        solely on the internal flag.
        """
        if not MT5_AVAILABLE:
            return False
        try:
            info = mt5.account_info()
            alive = info is not None
            if not alive and self._connected:
                logger.warning("MT5 connection lost (account_info returned None).")
                self._connected = False
            return alive
        except Exception as exc:
            logger.warning("MT5 connectivity check raised: %s", exc)
            self._connected = False
            return False

    def _ensure_connected(self) -> None:
        """Attempt reconnection if the connection has dropped."""
        if self.is_connected():
            return

        logger.warning("MT5 not connected — attempting reconnection …")
        for attempt in range(1, self._reconnect_attempts + 1):
            logger.info("Reconnect attempt %d / %d", attempt, self._reconnect_attempts)
            if self.connect():
                return
            time.sleep(self._reconnect_delay_s)

        raise ConnectionError(
            f"Failed to reconnect to MT5 after {self._reconnect_attempts} attempts."
        )

    # ── Symbol Information ────────────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> dict:
        """
        Retrieve and cache symbol specification from MT5.

        Parameters
        ----------
        symbol:
            Instrument ticker, e.g. ``"XAUUSD"``.

        Returns
        -------
        dict
            Keys: symbol, digits, point, tick_size, tick_value,
            contract_size, volume_min, volume_max, volume_step,
            currency_profit, currency_margin, spread, description.
        """
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        self._ensure_connected()

        info = mt5.symbol_info(symbol)
        if info is None:
            err = mt5.last_error()
            raise ValueError(f"Symbol '{symbol}' not found in MT5: {err}")

        # Ensure the symbol is visible in the Market Watch
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise ValueError(f"Failed to add '{symbol}' to Market Watch.")
            info = mt5.symbol_info(symbol)

        result: dict = {
            "symbol":            info.name,
            "digits":            info.digits,
            "point":             info.point,
            "tick_size":         info.trade_tick_size,
            "tick_value":        info.trade_tick_value,
            "contract_size":     info.trade_contract_size,
            "volume_min":        info.volume_min,
            "volume_max":        info.volume_max,
            "volume_step":       info.volume_step,
            "currency_profit":   info.currency_profit,
            "currency_margin":   info.currency_margin,
            "currency_base":     info.currency_base,
            "trade_calc_mode":   info.trade_calc_mode,
            "spread":            info.spread,
            "bid":               info.bid,
            "ask":               info.ask,
            "description":       info.description,
            "path":              info.path,
        }

        self._symbol_cache[symbol] = result
        logger.debug("Symbol info cached for %s: %s", symbol, result)
        return result

    def get_all_symbols(self) -> list[str]:
        """Retrieve names of all tradable symbols available on the broker."""
        self._ensure_connected()
        symbols = mt5.symbols_get()
        if symbols is None:
            return []
        return [s.name for s in symbols]

    def discover_all_instruments(self) -> dict[str, list[dict]]:
        """
        Scan all broker symbols and group them into structured categories:
        FOREX, METALS, INDICES, COMMODITIES, CRYPTO, EQUITIES.
        """
        self._ensure_connected()
        symbols = mt5.symbols_get()
        if symbols is None:
            return {}

        from trading_system.core.data.instrument_spec import InstrumentDiscovery

        grouped: dict[str, list[dict]] = {
            "METALS": [],
            "FOREX": [],
            "INDICES": [],
            "COMMODITIES": [],
            "CRYPTO": [],
            "EQUITIES": [],
            "OTHER": [],
        }

        for s in symbols:
            ac = InstrumentDiscovery.classify_asset(s.name, s.path)
            cat_key = "OTHER"
            if ac.value in ("FOREX_MAJOR", "FOREX_CROSS", "FOREX_EXOTIC"):
                cat_key = "FOREX"
            elif ac.value == "METALS":
                cat_key = "METALS"
            elif ac.value == "INDICES":
                cat_key = "INDICES"
            elif ac.value == "COMMODITIES":
                cat_key = "COMMODITIES"
            elif ac.value == "CRYPTO":
                cat_key = "CRYPTO"
            elif ac.value == "EQUITIES":
                cat_key = "EQUITIES"

            item = {
                "symbol": s.name,
                "description": s.description,
                "path": s.path,
                "digits": s.digits,
                "point": s.point,
                "bid": s.bid,
                "ask": s.ask,
                "spread": s.spread,
                "visible": s.visible,
            }
            grouped[cat_key].append(item)

        return grouped

    def invalidate_symbol_cache(self, symbol: str | None = None) -> None:
        """Clear the symbol info cache for one or all symbols."""
        if symbol:
            self._symbol_cache.pop(symbol, None)
        else:
            self._symbol_cache.clear()

    # ── OHLCV Data ────────────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        symbol: str,
        timeframe_str: str,
        count: int = 500,
    ) -> pd.DataFrame:
        """
        Retrieve the most recent OHLCV bars from MT5.

        Parameters
        ----------
        symbol:
            Instrument ticker.
        timeframe_str:
            Timeframe string, e.g. ``"H4"`` or ``"M15"``.
        count:
            Number of bars to retrieve (includes the currently forming bar).

        Returns
        -------
        pd.DataFrame
            Columns: ``time`` (UTC-aware Timestamp index), ``open``, ``high``,
            ``low``, ``close``, ``volume``, ``is_confirmed``.
        """
        self._ensure_connected()

        tf = self._resolve_timeframe(timeframe_str)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            logger.error(
                "No data returned for %s %s (count=%d): %s",
                symbol, timeframe_str, count, err,
            )
            return self._empty_ohlcv()

        df = self._rates_to_dataframe(rates, timeframe_str)
        logger.debug(
            "Fetched %d bars for %s %s (last: %s)",
            len(df), symbol, timeframe_str, df.index[-1],
        )
        return df

    def get_ohlcv_range(
        self,
        symbol: str,
        timeframe_str: str,
        date_from: datetime,
        date_to: datetime,
    ) -> pd.DataFrame:
        """
        Retrieve OHLCV bars between two UTC datetimes.

        Parameters
        ----------
        symbol:
            Instrument ticker.
        timeframe_str:
            Timeframe string, e.g. ``"D1"``.
        date_from:
            Start of the range (UTC).  Timezone-naive is treated as UTC.
        date_to:
            End of the range (UTC).  Timezone-naive is treated as UTC.

        Returns
        -------
        pd.DataFrame
            Same columns as :meth:`get_ohlcv`.
        """
        self._ensure_connected()

        # Normalise to UTC-aware datetimes
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)

        tf = self._resolve_timeframe(timeframe_str)
        rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            logger.error(
                "No range data for %s %s [%s, %s]: %s",
                symbol, timeframe_str, date_from, date_to, err,
            )
            return self._empty_ohlcv()

        df = self._rates_to_dataframe(rates, timeframe_str)
        logger.debug(
            "Range fetch: %d bars for %s %s [%s → %s]",
            len(df), symbol, timeframe_str, date_from, date_to,
        )
        return df

    # ── Live Tick ─────────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> dict:
        """
        Retrieve the latest bid/ask tick for a symbol.

        Returns
        -------
        dict
            Keys: ``bid``, ``ask``, ``spread`` (in points), ``time`` (UTC Timestamp).
        """
        self._ensure_connected()

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            err = mt5.last_error()
            raise RuntimeError(f"Failed to get tick for '{symbol}': {err}")

        info = self.get_symbol_info(symbol)
        point = info.get("point", 0.01)

        spread_pts = round((tick.ask - tick.bid) / point) if point else 0

        return {
            "bid":    tick.bid,
            "ask":    tick.ask,
            "spread": spread_pts,
            "time":   _to_utc_timestamp(tick.time),
        }

    # ── Account Information ───────────────────────────────────────────────────

    def get_account_info(self) -> dict:
        """
        Retrieve current account metrics.

        Returns
        -------
        dict
            Keys: balance, equity, margin, free_margin, profit, currency,
            leverage, name, server.
        """
        self._ensure_connected()

        acc = mt5.account_info()
        if acc is None:
            err = mt5.last_error()
            raise RuntimeError(f"Failed to retrieve account info: {err}")

        return {
            "balance":     acc.balance,
            "equity":      acc.equity,
            "margin":      acc.margin,
            "free_margin": acc.margin_free,
            "profit":      acc.profit,
            "currency":    acc.currency,
            "leverage":    acc.leverage,
            "name":        acc.name,
            "server":      acc.server,
        }

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_open_positions(self, symbol: Optional[str] = None) -> list[dict]:
        """
        Retrieve currently open positions (read-only).

        Parameters
        ----------
        symbol:
            If given, filter to this symbol only.

        Returns
        -------
        list[dict]
            Each dict has: ticket, symbol, type, volume, open_price,
            sl, tp, profit, swap, comment, open_time.
        """
        self._ensure_connected()

        positions = (
            mt5.positions_get(symbol=symbol)
            if symbol
            else mt5.positions_get()
        )

        if positions is None:
            err = mt5.last_error()
            logger.warning("get_open_positions returned None: %s", err)
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket":     pos.ticket,
                "symbol":     pos.symbol,
                "type":       "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume":     pos.volume,
                "open_price": pos.price_open,
                "sl":         pos.sl,
                "tp":         pos.tp,
                "profit":     pos.profit,
                "swap":       pos.swap,
                "comment":    pos.comment,
                "open_time":  _to_utc_timestamp(pos.time),
            })

        return result

    # ── Order History ─────────────────────────────────────────────────────────

    def get_order_history(
        self,
        symbol: Optional[str] = None,
        days: int = 30,
    ) -> list[dict]:
        """
        Retrieve historical (closed) orders.

        Parameters
        ----------
        symbol:
            If given, filter to this symbol only.
        days:
            How many days back to look.

        Returns
        -------
        list[dict]
            Each dict contains order metadata fields.
        """
        self._ensure_connected()

        date_from = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        import datetime as dt_mod
        date_from = date_from - dt_mod.timedelta(days=days)

        orders = (
            mt5.history_orders_get(date_from, datetime.now(tz=timezone.utc), symbol=symbol)
            if symbol
            else mt5.history_orders_get(date_from, datetime.now(tz=timezone.utc))
        )

        if orders is None:
            err = mt5.last_error()
            logger.warning("get_order_history returned None: %s", err)
            return []

        result = []
        for o in orders:
            result.append({
                "ticket":       o.ticket,
                "symbol":       o.symbol,
                "type":         o.type,
                "type_str":     self._order_type_str(o.type),
                "volume":       o.volume_initial,
                "volume_done":  o.volume_current,
                "price_open":   o.price_open,
                "sl":           o.sl,
                "tp":           o.tp,
                "price_current": o.price_current,
                "state":        o.state,
                "comment":      o.comment,
                "setup_time":   _to_utc_timestamp(o.time_setup),
                "done_time":    _to_utc_timestamp(o.time_done) if o.time_done else None,
            })

        return result

    def get_deals_history(self, days: int = 30) -> list[dict]:
        """
        Retrieve closed deal history for P&L calculation.

        Parameters
        ----------
        days:
            How many calendar days back to retrieve.

        Returns
        -------
        list[dict]
            Each dict contains deal fields including profit, commission, swap.
        """
        self._ensure_connected()

        import datetime as dt_mod
        date_from = datetime.now(tz=timezone.utc) - dt_mod.timedelta(days=days)

        deals = mt5.history_deals_get(date_from, datetime.now(tz=timezone.utc))

        if deals is None:
            err = mt5.last_error()
            logger.warning("get_deals_history returned None: %s", err)
            return []

        result = []
        for d in deals:
            result.append({
                "ticket":     d.ticket,
                "order":      d.order,
                "symbol":     d.symbol,
                "type":       d.type,
                "type_str":   self._deal_type_str(d.type),
                "volume":     d.volume,
                "price":      d.price,
                "profit":     d.profit,
                "commission": d.commission,
                "swap":       d.swap,
                "fee":        d.fee,
                "comment":    d.comment,
                "entry":      d.entry,  # 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY
                "time":       _to_utc_timestamp(d.time),
            })

        return result

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _resolve_timeframe(self, timeframe_str: str) -> Any:
        """Convert a timeframe string to the MT5 constant."""
        tf = MT5_TIMEFRAME_MAP.get(timeframe_str.upper())
        if tf is None:
            raise ValueError(
                f"Unknown timeframe '{timeframe_str}'. "
                f"Valid options: {list(MT5_TIMEFRAME_MAP.keys())}"
            )
        return tf

    def _rates_to_dataframe(
        self,
        rates: Any,
        timeframe_str: str,
    ) -> pd.DataFrame:
        """
        Convert MT5 rates structured array to a clean DataFrame.

        The last row is flagged as FORMING if its bar has not yet closed,
        all prior rows are CONFIRMED.
        """
        df = pd.DataFrame(rates)
        df.rename(
            columns={
                "time":        "time",
                "open":        "open",
                "high":        "high",
                "low":         "low",
                "close":       "close",
                "tick_volume": "volume",
                "real_volume": "real_volume",
                "spread":      "spread",
            },
            inplace=True,
        )

        # Keep only standard OHLCV + extras
        keep_cols = [c for c in ["time", "open", "high", "low", "close", "volume",
                                  "real_volume", "spread"] if c in df.columns]
        df = df[keep_cols].copy()

        # Convert timestamps
        df["time"] = df["time"].apply(_to_utc_timestamp)
        df.set_index("time", inplace=True)

        # Candle confirmation flag
        tf_secs = _TF_SECONDS.get(timeframe_str.upper(), 60)
        now_utc = pd.Timestamp.now(tz="UTC")
        last_bar_time = df.index[-1]
        bar_close_time = last_bar_time + pd.Timedelta(seconds=tf_secs)

        df["is_confirmed"] = True
        if now_utc < bar_close_time:
            df.iloc[-1, df.columns.get_loc("is_confirmed")] = False

        return df

    @staticmethod
    def _empty_ohlcv() -> pd.DataFrame:
        """Return an empty OHLCV DataFrame with the expected schema."""
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "is_confirmed"]
        ).rename_axis("time")

    @staticmethod
    def _order_type_str(order_type: int) -> str:
        """Map MT5 order type integer to human-readable string."""
        if not MT5_AVAILABLE:
            return str(order_type)
        mapping = {
            mt5.ORDER_TYPE_BUY:             "BUY",
            mt5.ORDER_TYPE_SELL:            "SELL",
            mt5.ORDER_TYPE_BUY_LIMIT:       "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT:      "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP:        "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP:       "SELL_STOP",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT:  "BUY_STOP_LIMIT",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL_STOP_LIMIT",
        }
        return mapping.get(order_type, f"UNKNOWN({order_type})")

    @staticmethod
    def _deal_type_str(deal_type: int) -> str:
        """Map MT5 deal type integer to human-readable string."""
        if not MT5_AVAILABLE:
            return str(deal_type)
        mapping = {
            mt5.DEAL_TYPE_BUY:        "BUY",
            mt5.DEAL_TYPE_SELL:       "SELL",
            mt5.DEAL_TYPE_BALANCE:    "BALANCE",
            mt5.DEAL_TYPE_CREDIT:     "CREDIT",
            mt5.DEAL_TYPE_COMMISSION: "COMMISSION",
            mt5.DEAL_TYPE_BONUS:      "BONUS",
            mt5.DEAL_TYPE_CORRECTION: "CORRECTION",
        }
        return mapping.get(deal_type, f"UNKNOWN({deal_type})")

    # ── Context Manager Support ────────────────────────────────────────────────

    def __enter__(self) -> "MT5Connector":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"MT5Connector(login={self._login}, server={self._server!r}, status={status})"
