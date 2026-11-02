"""
core/data/data_provider.py
==========================
Unified multi-timeframe market data provider.
Integrates MT5 real-time data with intelligent fallback to Yahoo Finance (GC=F)
and Alpha Vantage. Ensures incomplete candles are strictly flagged as unconfirmed.
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
from trading_system.core.data.mt5_connector import MT5Connector

logger = logging.getLogger(__name__)


class DataProvider:
    """
    Unified market data engine providing multi-timeframe OHLCV data.
    Attempts MT5 first; seamlessly falls back to yfinance or cached data.
    """

    def __init__(
        self,
        mt5_connector: Optional[MT5Connector] = None,
        use_cache: bool = True,
        cache_dir: Optional[Path] = None,
    ):
        self.mt5 = mt5_connector
        self.use_cache = use_cache
        self.cache_dir = cache_dir or DATA_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_source: dict[str, str] = {}

    @property
    def is_mt5_connected(self) -> bool:
        return self.mt5 is not None and self.mt5.is_connected()

    def get_source_label(self, timeframe: str) -> str:
        return self._last_source.get(timeframe, "UNKNOWN")

    def get_current_price(self, symbol: str = SYMBOL) -> float:
        """Get the latest real-time or near-real-time price for symbol."""
        if self.is_mt5_connected:
            tick = self.mt5.get_tick(symbol)
            if tick and "bid" in tick and tick["bid"] > 0:
                return float((tick["bid"] + tick["ask"]) / 2.0 if "ask" in tick else tick["bid"])

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

        # 1. Try MT5
        if self.is_mt5_connected:
            try:
                df = self.mt5.get_ohlcv(symbol, timeframe, count=count)
                if not df.empty:
                    source = "MT5_LIVE"
                    self._last_source[timeframe] = source
            except Exception as e:
                logger.warning("MT5 get_ohlcv error for %s %s: %s", symbol, timeframe, e)

        # 2. Try yfinance fallback
        if df.empty:
            df = self._fetch_yfinance(symbol, timeframe, count=count)
            if not df.empty:
                source = "YFINANCE"
                self._last_source[timeframe] = source

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

        if df.empty:
            logger.error("Failed to retrieve market data for %s %s from any source.", symbol, timeframe)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "is_confirmed"])

        # Ensure column standardisation and incomplete candle detection
        df = self._standardise_df(df)
        df = self.flag_incomplete_candle(df, timeframe)

        # Cache on disk
        if self.use_cache and source in ("MT5_LIVE", "YFINANCE"):
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
            df.loc[df.index[-1], "is_confirmed"] = False
            logger.debug(
                "Timeframe %s last candle is FORMING (elapsed %ds / period %ds)",
                timeframe, int(elapsed_seconds), period_seconds
            )
        else:
            df.loc[df.index[-1], "is_confirmed"] = True

        return df

    # ─────────────────────────────────────────────────────────────────────────
    # Internal Fetchers & Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_yfinance(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Fetch historical data from Yahoo Finance."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance package not installed. Cannot use fallback.")
            return pd.DataFrame()

        yf_ticker = YFINANCE_SYMBOL_MAP.get(symbol, symbol)

        # Map timeframe to yfinance interval and period
        interval_map = {
            "MN1": ("1mo", "10y"),
            "W1":  ("1wk", "5y"),
            "D1":  ("1d", "2y"),
            "H4":  ("1h", "730d"),   # yfinance doesn't have 4h, pull 1h and resample
            "H1":  ("1h", "730d"),
            "M30": ("30m", "60d"),
            "M15": ("15m", "60d"),
            "M5":  ("5m", "60d"),
            "M1":  ("1m", "7d"),
        }

        if timeframe not in interval_map:
            interval, period = "1d", "1y"
        else:
            interval, period = interval_map[timeframe]

        try:
            logger.debug("Downloading %s via yfinance (interval=%s, period=%s)...", yf_ticker, interval, period)
            raw = yf.download(
                tickers=yf_ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )

            if raw is None or raw.empty:
                return pd.DataFrame()

            # Flatten MultiIndex columns if present
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = [c[0].lower() for c in raw.columns]
            else:
                raw.columns = [str(c).lower() for c in raw.columns]

            raw = raw.reset_index()
            # Find date column
            date_col = next((c for c in raw.columns if "date" in c or "time" in c), raw.columns[0])
            raw = raw.rename(columns={date_col: "time"})

            # Handle H4 resample from 1h if needed
            if timeframe == "H4":
                raw["time"] = pd.to_datetime(raw["time"])
                raw = raw.set_index("time").resample("4h").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna().reset_index()

            # Keep only standard columns
            cols = ["time", "open", "high", "low", "close", "volume"]
            available_cols = [c for c in cols if c in raw.columns]
            raw = raw[available_cols]

            # Slice to requested count
            if len(raw) > count:
                raw = raw.iloc[-count:].copy()

            return raw.reset_index(drop=True)

        except Exception as e:
            logger.warning("yfinance fetch error for %s (%s): %s", yf_ticker, timeframe, e)
            return pd.DataFrame()

    def _standardise_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard types, lower-case columns, UTC timestamps."""
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)

        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        return df

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        return self.cache_dir / f"{symbol}_{timeframe}.parquet"

    def _save_to_cache(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        try:
            path = self._cache_path(symbol, timeframe)
            df.to_parquet(path, index=False)
        except Exception as e:
            logger.debug("Failed to cache %s %s to disk: %s", symbol, timeframe, e)

    def _load_from_cache(self, symbol: str, timeframe: str) -> pd.DataFrame:
        path = self._cache_path(symbol, timeframe)
        if path.exists():
            try:
                df = pd.read_parquet(path)
                logger.info("Loaded %s %s from disk cache (%d rows)", symbol, timeframe, len(df))
                return df
            except Exception as e:
                logger.warning("Error reading disk cache %s: %s", path, e)
        return pd.DataFrame()

    def _generate_synthetic_data(self, symbol: str = "XAUUSD", timeframe: str = "H1", count: int = 200) -> pd.DataFrame:
        """Generate realistic geometric Brownian motion multi-asset OHLCV data for offline demo mode."""
        seed_val = int(abs(hash(symbol) + hash(timeframe))) % 100000
        np.random.seed(seed_val)
        now = datetime.now(timezone.utc)
        period_sec = TIMEFRAME_SECONDS.get(timeframe, 3600)
        times = [now - pd.Timedelta(seconds=(count - i) * period_sec) for i in range(count)]

        s_upper = symbol.upper()
        if "BTC" in s_upper:
            base_p, vol_p, digits = 80000.0, 450.0, 2
        elif "ETH" in s_upper:
            base_p, vol_p, digits = 3200.0, 35.0, 2
        elif "30" in s_upper:
            base_p, vol_p, digits = 50000.0, 120.0, 1
        elif "100" in s_upper or "TEC" in s_upper:
            base_p, vol_p, digits = 28000.0, 80.0, 2
        elif "500" in s_upper:
            base_p, vol_p, digits = 7600.0, 20.0, 2
        elif "JPY" in s_upper:
            base_p, vol_p, digits = 155.0, 0.45, 3
        elif any(f in s_upper for f in ["EUR", "GBP", "AUD", "CAD", "NZD", "CHF"]):
            base_p, vol_p, digits = 1.1000, 0.0025, 5
        elif "OIL" in s_upper:
            base_p, vol_p, digits = 75.0, 0.60, 3
        else:
            base_p, vol_p, digits = 3900.0, 8.0, 2  # Gold

        returns = np.random.normal(0.0001, 0.003, count)
        price_curve = base_p * np.exp(np.cumsum(returns))

        highs = price_curve + np.abs(np.random.normal(vol_p, vol_p * 0.4, count))
        lows = price_curve - np.abs(np.random.normal(vol_p, vol_p * 0.4, count))
        closes = price_curve + np.random.normal(0.0, vol_p * 0.3, count)
        opens = np.roll(closes, 1)
        opens[0] = price_curve[0]

        delta = max(vol_p * 0.1, 10 ** (-digits))
        highs = np.maximum(highs, np.maximum(opens, closes) + delta)
        lows = np.minimum(lows, np.minimum(opens, closes) - delta)
        volumes = np.random.randint(500, 6000, count)

        df = pd.DataFrame({
            "time": times,
            "open": np.round(opens, digits),
            "high": np.round(highs, digits),
            "low": np.round(lows, digits),
            "close": np.round(closes, digits),
            "volume": volumes,
            "is_confirmed": True,
        })
        df.iloc[-1, df.columns.get_loc("is_confirmed")] = False
        return df

    def _generate_synthetic_gold_data(self, timeframe: str, count: int = 200) -> pd.DataFrame:
        """Backward compatible helper for gold demo."""
        return self._generate_synthetic_data(symbol="XAUUSD", timeframe=timeframe, count=count)
