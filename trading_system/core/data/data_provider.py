"""
core/data/data_provider.py
==========================
Unified multi-timeframe market data provider.
Integrates MT5 real-time data with strict Data Integrity governance.
Ensures incomplete candles are strictly flagged as unconfirmed.
Never silently presents synthetic or fallback data as live MT5 telemetry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytz

from trading_system.config.settings import (
    DATA_CACHE_DIR,
    DEFAULT_CANDLE_COUNTS,
    SYMBOL,
    TIMEFRAME_HIERARCHY,
    TIMEFRAME_SECONDS,
    YFINANCE_SYMBOL_MAP,
)
from trading_system.core.data.data_integrity import DataIntegrityManager, DataSourceState
from trading_system.core.data.mt5_connector import MT5Connector

logger = logging.getLogger(__name__)


class DataProvider:
    """
    Unified market data engine providing multi-timeframe OHLCV data.
    Enforces strict Data Integrity: Live trade plans require authoritative MT5 connection.
    """

    def __init__(
        self,
        mt5_connector: Optional[MT5Connector] = None,
        use_cache: bool = True,
        cache_dir: Optional[Path] = None,
        integrity_manager: Optional[DataIntegrityManager] = None,
        is_demo_mode: bool = False,
    ):
        self.mt5 = mt5_connector
        self.use_cache = use_cache
        self.cache_dir = cache_dir or DATA_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_source: dict[str, str] = {}

        # Authoritative Data Integrity Manager
        self.integrity = integrity_manager or DataIntegrityManager()
        if self.is_mt5_connected:
            self.integrity.set_state(DataSourceState.MT5_LIVE, reason="MT5 active live connection")
        elif is_demo_mode:
            self.integrity.set_state(DataSourceState.DEMO_SIMULATED, reason="Explicit demo mode selected")
        elif self.mt5 is not None:
            self.integrity.set_state(DataSourceState.OFFLINE_DISCONNECTED, reason="MT5 terminal disconnected")
        else:
            self.integrity.set_state(DataSourceState.DEMO_SIMULATED, reason="No MT5 connector configured")

    @property
    def is_mt5_connected(self) -> bool:
        connected = self.mt5 is not None and self.mt5.is_connected()
        if connected and self.integrity.state != DataSourceState.MT5_LIVE:
            self.integrity.set_state(DataSourceState.MT5_LIVE, reason="MT5 connected")
        elif not connected and self.mt5 is not None and self.integrity.state == DataSourceState.MT5_LIVE:
            self.integrity.set_state(DataSourceState.OFFLINE_DISCONNECTED, reason="MT5 disconnected")
        return connected

    @property
    def data_source_state(self) -> DataSourceState:
        # Trigger dynamic health check
        _ = self.is_mt5_connected
        return self.integrity.state

    @property
    def is_live_executable(self) -> bool:
        return self.data_source_state == DataSourceState.MT5_LIVE

    def validate_plan_generation_allowed(self) -> tuple[bool, Optional[str]]:
        """Gating check ensuring live trade plans are only generated on verified MT5 data."""
        return self.integrity.validate_plan_generation_allowed()

    def get_source_label(self, timeframe: str) -> str:
        return self._last_source.get(timeframe, self.integrity.state.value)

    def get_current_price(self, symbol: str = SYMBOL) -> float:
        """Get the latest real-time or near-real-time price for symbol."""
        if self.is_mt5_connected:
            tick = self.mt5.get_tick(symbol)
            if tick and "bid" in tick and tick["bid"] > 0:
                self.integrity.record_tick()
                return float((tick["bid"] + tick["ask"]) / 2.0 if "ask" in tick else tick["bid"])

        # If MT5 is disconnected, log integrity warning
        if self.mt5 is not None:
            self.integrity.set_state(DataSourceState.OFFLINE_DISCONNECTED, reason="get_tick failed on MT5")

        # Fallback via Daily or M15 candle close
        df = self.get_ohlcv(symbol, "M15", count=2)
        if not df.empty and "close" in df.columns:
            return float(df["close"].iloc[-1])

        df_d1 = self.get_ohlcv(symbol, "D1", count=2)
        if not df_d1.empty and "close" in df_d1.columns:
            return float(df_d1["close"].iloc[-1])

        # Dynamic fallback baseline based on instrument
        from trading_system.core.data.instrument_spec import InstrumentDiscovery
        spec = InstrumentDiscovery.get_fallback_spec(symbol)
        if spec.digits == 5:
            return 1.10000
        elif "JPY" in symbol.upper():
            return 155.000
        elif "30" in symbol.upper():
            return 50000.0
        elif "TEC" in symbol.upper() or "100" in symbol.upper():
            return 28000.0
        elif "500" in symbol.upper():
            return 7600.0
        elif "BTC" in symbol.upper():
            return 80000.0
        elif "OIL" in symbol.upper():
            return 75.0
        return 3900.0  # Gold current baseline

    def get_ohlcv(
        self,
        symbol: str = SYMBOL,
        timeframe: str = "H1",
        count: int = 500,
    ) -> pd.DataFrame:
        """
        Retrieve OHLCV DataFrame for a specific timeframe.
        Columns: [time, open, high, low, close, volume, is_confirmed]
        """
        df = pd.DataFrame()
        source = "NONE"

        # 1. Try MT5 Live authoritative data
        if self.is_mt5_connected:
            try:
                df = self.mt5.get_ohlcv(symbol, timeframe, count=count)
                if not df.empty:
                    source = "MT5_LIVE"
                    self._last_source[timeframe] = source
                    self.integrity.set_state(DataSourceState.MT5_LIVE, reason="Live MT5 OHLCV stream")
            except Exception as e:
                logger.warning("MT5 get_ohlcv error for %s %s: %s", symbol, timeframe, e)
                if self.mt5 is not None:
                    self.integrity.set_state(DataSourceState.OFFLINE_DISCONNECTED, reason=f"MT5 stream error: {e}")

        # 2. Try yfinance fallback (Strictly marked as non-authoritative)
        if df.empty:
            df = self._fetch_yfinance(symbol, timeframe, count=count)
            if not df.empty:
                source = "YFINANCE_FALLBACK"
                self._last_source[timeframe] = source
                if self.integrity.state != DataSourceState.HISTORICAL_BACKTEST:
                    self.integrity.set_state(DataSourceState.DEMO_SIMULATED, reason="Yahoo Finance fallback used")

        # 3. If still empty, try disk cache
        if df.empty and self.use_cache:
            df = self._load_from_cache(symbol, timeframe)
            if not df.empty:
                source = "DISK_CACHE"
                self._last_source[timeframe] = source

        # 4. Fallback to built-in synthetic market simulation for offline / demo mode
        if df.empty:
            df = self._generate_synthetic_data(symbol, timeframe, count=count)
            source = "DEMO_SIMULATION"
            self._last_source[timeframe] = source
            if self.integrity.state != DataSourceState.HISTORICAL_BACKTEST:
                self.integrity.set_state(DataSourceState.DEMO_SIMULATED, reason="Synthetic demo data generated")

        if df.empty:
            logger.error("Failed to retrieve market data for %s %s from any source.", symbol, timeframe)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "is_confirmed"])

        # Ensure column standardisation and incomplete candle detection
        df = self._standardise_df(df)
        df = self.flag_incomplete_candle(df, timeframe)

        # Cache on disk
        if self.use_cache and source in ("MT5_LIVE", "YFINANCE_FALLBACK"):
            self._save_to_cache(symbol, timeframe, df)

        return df

    def get_all_timeframes(
        self,
        symbol: str = SYMBOL,
        timeframe_hierarchy: Optional[list[str]] = None,
        counts_per_tf: Optional[dict[str, int]] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Retrieve synchronized OHLCV DataFrames across all target timeframes.
        """
        tfs = timeframe_hierarchy or TIMEFRAME_HIERARCHY
        counts = counts_per_tf or DEFAULT_CANDLE_COUNTS

        results: dict[str, pd.DataFrame] = {}
        for tf in tfs:
            needed_count = counts.get(tf, 300)
            df = self.get_ohlcv(symbol=symbol, timeframe=tf, count=needed_count)
            results[tf] = df
            logger.info("Loaded %s: %d candles (source: %s)", tf, len(df), self.get_source_label(tf))

        return results

    def flag_incomplete_candle(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        Determine if the most recent candle in df is confirmed (closed)
        or still currently forming based on server/UTC time vs bar open time.
        """
        if df.empty or "time" not in df.columns:
            return df

        df = df.copy()
        if "is_confirmed" not in df.columns:
            df["is_confirmed"] = True

        # All historical bars except the last one are definitely confirmed
        df["is_confirmed"] = True

        # Check last bar
        period_seconds = TIMEFRAME_SECONDS.get(timeframe, 3600)
        last_time = df["time"].iloc[-1]

        if isinstance(last_time, str):
            last_time = pd.to_datetime(last_time)

        if last_time.tzinfo is None:
            last_time = pytz.UTC.localize(last_time)

        now_utc = datetime.now(timezone.utc)
        elapsed_seconds = (now_utc - last_time).total_seconds()

        # If elapsed time since candle start is less than the timeframe duration, it's still forming!
        if elapsed_seconds < period_seconds:
            df.iloc[-1, df.columns.get_loc("is_confirmed")] = False
        else:
            df.iloc[-1, df.columns.get_loc("is_confirmed")] = True

        return df

    # ── Fallback Implementations ──────────────────────────────────────────────

    def _fetch_yfinance(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500,
    ) -> pd.DataFrame:
        """Fetch historical bars from Yahoo Finance."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance package not installed. Cannot use fallback.")
            return pd.DataFrame()

        ticker_sym = YFINANCE_SYMBOL_MAP.get(symbol, symbol)
        yf_interval_map = {
            "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
            "H1": "1h", "H4": "1h", "D1": "1d", "W1": "1wk", "MN1": "1mo",
        }
        interval = yf_interval_map.get(timeframe, "1h")

        period_map = {
            "M1": "5d", "M5": "1mo", "M15": "1mo", "M30": "1mo",
            "H1": "2y", "H4": "2y", "D1": "5y", "W1": "10y", "MN1": "max",
        }
        period = period_map.get(timeframe, "1y")

        try:
            ticker = yf.Ticker(ticker_sym)
            raw = ticker.history(period=period, interval=interval)
            if raw.empty:
                return pd.DataFrame()

            raw = raw.reset_index()
            # Standardize column names to lowercase
            raw.columns = [str(c).lower() for c in raw.columns]
            rename_map = {"datetime": "time", "date": "time"}
            raw = raw.rename(columns=rename_map)

            # Ensure UTC timezone
            if "time" in raw.columns:
                raw["time"] = pd.to_datetime(raw["time"], utc=True)

            if timeframe == "H4" and interval == "1h" and len(raw) >= 4:
                raw = self._resample_to_h4(raw)

            return raw.tail(count).reset_index(drop=True)

        except Exception as e:
            logger.warning("yfinance fetch error for %s (%s): %s", symbol, ticker_sym, e)
            return pd.DataFrame()

    def _resample_to_h4(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample 1-hour dataframe to 4-hour candles."""
        if df.empty or "time" not in df.columns:
            return df
        df = df.set_index("time")
        agg_rules = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        available_rules = {k: v for k, v in agg_rules.items() if k in df.columns}
        resampled = df.resample("4h").agg(available_rules).dropna().reset_index()
        return resampled

    def _generate_synthetic_data(
        self,
        symbol: str,
        timeframe: str,
        count: int = 500,
    ) -> pd.DataFrame:
        """
        Produce realistic multi-timeframe synthetic OHLCV data for offline demo mode.
        """
        from trading_system.core.data.instrument_spec import InstrumentDiscovery
        spec = InstrumentDiscovery.get_fallback_spec(symbol)
        digits = spec.digits

        if digits == 5:
            base_price = 1.11500
            atr_pct = 0.0004
        elif "JPY" in symbol.upper():
            base_price = 157.500
            atr_pct = 0.001
        elif "30" in symbol.upper():
            base_price = 44000.0
            atr_pct = 0.002
        elif "TEC" in symbol.upper() or "100" in symbol.upper():
            base_price = 20500.0
            atr_pct = 0.0025
        elif "BTC" in symbol.upper():
            base_price = 92000.0
            atr_pct = 0.005
        else:
            base_price = 3900.0
            atr_pct = 0.003

        np.random.seed(hash(symbol + timeframe) % (2**31))

        sec_per_bar = TIMEFRAME_SECONDS.get(timeframe, 3600)
        end_time = datetime.now(timezone.utc)
        times = [end_time - pd.Timedelta(seconds=sec_per_bar * (count - i)) for i in range(count)]

        # Generate price series with trending cycles and volatility
        t = np.linspace(0, 4 * np.pi, count)
        trend = np.sin(t) * (base_price * 0.03)
        noise = np.cumsum(np.random.normal(0, base_price * atr_pct * 0.5, count))
        close = base_price + trend + noise

        high = close + np.abs(np.random.normal(0, base_price * atr_pct, count))
        low = close - np.abs(np.random.normal(0, base_price * atr_pct, count))
        open_price = np.roll(close, 1)
        open_price[0] = base_price

        for i in range(count):
            high[i] = max(high[i], open_price[i], close[i])
            low[i] = min(low[i], open_price[i], close[i])

        volume = np.random.randint(100, 5000, size=count).astype(float)

        df = pd.DataFrame({
            "time": times,
            "open": np.round(open_price, digits),
            "high": np.round(high, digits),
            "low": np.round(low, digits),
            "close": np.round(close, digits),
            "volume": volume,
            "is_confirmed": True,
        })
        df.iloc[-1, df.columns.get_loc("is_confirmed")] = False
        return df

    def _standardise_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard types and required columns."""
        df = df.copy()
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df.reset_index(drop=True)

    def _get_cache_path(self, symbol: str, timeframe: str) -> Path:
        clean_sym = symbol.replace("/", "_").replace("=", "_")
        return self.cache_dir / f"{clean_sym}_{timeframe}.parquet"

    def _save_to_cache(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        try:
            p = self._get_cache_path(symbol, timeframe)
            df.to_parquet(p, index=False)
        except Exception as e:
            logger.debug("Could not write cache file: %s", e)

    def _load_from_cache(self, symbol: str, timeframe: str) -> pd.DataFrame:
        p = self._get_cache_path(symbol, timeframe)
        if p.exists():
            try:
                df = pd.read_parquet(p)
                return df
            except Exception as e:
                logger.debug("Could not read cache file %s: %s", p, e)
        return pd.DataFrame()
