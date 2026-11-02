"""
Volatility Regime Detector for XAUUSD.

Classifies current market volatility into LOW / NORMAL / HIGH / EXTREME
using ATR percentiles and intraday range.  Results drive position size
scaling and SL multiplier selection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── ATR percentile thresholds (empirical for XAUUSD) ─────────────────
_REGIME_THRESHOLDS = {
    "LOW": 25,        # Below 25th percentile
    "NORMAL_LOW": 25,
    "NORMAL_HIGH": 75,
    "HIGH": 75,       # Above 75th percentile
    "EXTREME": 90,    # Above 90th percentile
}

# ── SL multiplier recommendations per regime ──────────────────────────
_ATR_MULTIPLIER_MAP = {
    "LOW": 1.8,       # Tighter SL acceptable in calm markets
    "NORMAL": 1.5,    # Standard
    "HIGH": 2.0,      # Wider SL needed — volatility can spike through tight stops
    "EXTREME": 2.5,   # Very wide — or avoid trading altogether
}

# ── Risk scaling per regime ───────────────────────────────────────────
_RISK_SCALING_MAP = {
    "LOW": 1.10,
    "NORMAL": 1.00,
    "HIGH": 0.65,
    "EXTREME": 0.40,
}

# ── XAUUSD intraday session volatility profile (UTC hours) ────────────
# Maps UTC hour → expected volatility label
_SESSION_VOL_MAP: dict[int, str] = {
    0: "LOW",
    1: "LOW",
    2: "LOW",
    3: "LOW",
    4: "LOW",
    5: "LOW",
    6: "NORMAL",         # Pre-London drift
    7: "HIGH",           # London open
    8: "HIGH",           # London open peak
    9: "NORMAL",         # London session stabilises
    10: "NORMAL",
    11: "NORMAL",
    12: "NORMAL",
    13: "HIGH",          # NY open overlap with London
    14: "HIGH",          # NY open peak
    15: "NORMAL",        # NY session active but calmer
    16: "NORMAL",
    17: "NORMAL",
    18: "NORMAL",
    19: "LOW",           # NY afternoon / pre-close
    20: "LOW",
    21: "LOW",
    22: "LOW",
    23: "LOW",
}

# 13:30 UTC is a special EXTREME WARNING time (US economic data releases)
_NEWS_RELEASE_HOUR_UTC = 13
_NEWS_RELEASE_MINUTE_UTC = 30


class VolatilityRegimeDetector:
    """
    Detects volatility regime from OHLCV data and provides XAUUSD-specific
    session-based volatility guidance.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_regime(
        self,
        df: pd.DataFrame,
        atr_period: int = 14,
        lookback: int = 50,
    ) -> dict:
        """
        Classify current volatility regime from a price DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns: high, low, close (case-insensitive).
            Rows are in chronological order (oldest first).
            At least ``atr_period + 1`` rows are required.
        atr_period : int
            Wilder's ATR period (default 14).
        lookback : int
            Number of recent bars used for percentile calculation (default 50).
            Must be >= atr_period.

        Returns
        -------
        dict with:
            regime, current_atr, avg_atr, atr_percentile, volatility_ratio,
            intraday_range, recommended_atr_multiplier_for_sl, risk_scaling_factor.
        """
        df = self._normalize_columns(df)
        self._validate_df(df, atr_period)

        atr_series = self._compute_atr(df, atr_period)

        # Slice to lookback window for statistics
        window = atr_series.iloc[-lookback:].dropna()
        if len(window) < max(5, atr_period // 2):
            raise ValueError(
                f"Not enough ATR data in lookback window (got {len(window)}, "
                f"need at least {max(5, atr_period // 2)})"
            )

        current_atr = float(window.iloc[-1])
        avg_atr = float(window.mean())
        volatility_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0
        atr_percentile = float(
            (window < current_atr).sum() / len(window) * 100
        )

        # Intraday range of last complete bar
        last_bar = df.iloc[-1]
        intraday_range = float(last_bar["high"] - last_bar["low"])

        regime = self._classify_regime(atr_percentile)

        return {
            "regime": regime,
            "current_atr": round(current_atr, 5),
            "avg_atr": round(avg_atr, 5),
            "atr_percentile": round(atr_percentile, 2),
            "volatility_ratio": round(volatility_ratio, 4),
            "intraday_range": round(intraday_range, 5),
            "recommended_atr_multiplier_for_sl": _ATR_MULTIPLIER_MAP[regime],
            "risk_scaling_factor": _RISK_SCALING_MAP[regime],
        }

    # ------------------------------------------------------------------

    def get_xauusd_session_volatility(self, hour_utc: int) -> str:
        """
        Return expected XAUUSD volatility level for a given UTC hour.

        Based on empirical trading session behaviour:
          - Asian session (00:00–06:59 UTC)  → LOW or LOW-NORMAL
          - Pre-London drift (06:00–06:59)   → NORMAL
          - London open (07:00–08:59)        → HIGH
          - London session (09:00–12:59)     → NORMAL
          - NY open / London-NY overlap (13:00–14:59) → HIGH
          - US economic data releases (~13:30) → EXTREME WARNING
          - NY session (15:00–18:59)         → NORMAL
          - NY afternoon / close (19:00–23:59) → LOW

        Parameters
        ----------
        hour_utc : int
            UTC hour in range [0, 23].

        Returns
        -------
        str — one of: LOW / NORMAL / HIGH / EXTREME_WARNING
        """
        if not (0 <= hour_utc <= 23):
            raise ValueError(f"hour_utc must be in [0, 23], got {hour_utc}")
        return _SESSION_VOL_MAP.get(hour_utc, "NORMAL")

    def get_xauusd_session_volatility_now(self) -> dict:
        """
        Return current session volatility with news-time EXTREME detection.

        Returns
        -------
        dict with:
            hour_utc, minute_utc, volatility, is_near_news_release,
            description.
        """
        now = datetime.now(tz=timezone.utc)
        hour = now.hour
        minute = now.minute

        base_vol = self.get_xauusd_session_volatility(hour)

        # Flag 13:15–13:45 UTC as potential news time
        is_near_news = (
            hour == _NEWS_RELEASE_HOUR_UTC
            and abs(minute - _NEWS_RELEASE_MINUTE_UTC) <= 15
        )

        effective_vol = "EXTREME" if is_near_news else base_vol

        descriptions = {
            "LOW": "Asian session — low participation, range-bound",
            "NORMAL": "Active session — normal volatility",
            "HIGH": "Session open — elevated volatility expected",
            "EXTREME": "Near major news release (13:30 UTC) — AVOID or use extreme caution",
        }

        return {
            "hour_utc": hour,
            "minute_utc": minute,
            "volatility": effective_vol,
            "is_near_news_release": is_near_news,
            "description": descriptions.get(effective_vol, "Unknown"),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Normalise column names to lowercase."""
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]
        missing = [c for c in ("high", "low", "close") if c not in df.columns]
        if missing:
            raise ValueError(
                f"DataFrame missing required columns: {missing}. "
                f"Available: {list(df.columns)}"
            )
        return df

    @staticmethod
    def _validate_df(df: pd.DataFrame, atr_period: int) -> None:
        min_rows = atr_period + 2
        if len(df) < min_rows:
            raise ValueError(
                f"DataFrame has {len(df)} rows; need at least {min_rows} "
                f"(atr_period={atr_period} + 2)"
            )

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
        """
        Wilder's Average True Range.

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = Wilder's smoothed MA of TR over ``period`` bars.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Wilder's smoothing: first value = simple mean, then EWM
        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return atr

    @staticmethod
    def _classify_regime(atr_percentile: float) -> str:
        """Map ATR percentile to a regime label."""
        if atr_percentile >= _REGIME_THRESHOLDS["EXTREME"]:
            return "EXTREME"
        if atr_percentile >= _REGIME_THRESHOLDS["HIGH"]:
            return "HIGH"
        if atr_percentile >= _REGIME_THRESHOLDS["NORMAL_LOW"]:
            return "NORMAL"
        return "LOW"
