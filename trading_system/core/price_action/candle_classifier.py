"""
candle_classifier.py
====================
CandleClassifier – classifies individual OHLC candles with full context awareness.

Candle type labels:
    STRONG_BULL   – large bullish body, minimal wicks
    STRONG_BEAR   – large bearish body, minimal wicks
    BULL_REJECTION– bullish candle with long lower wick (demand rejection)
    BEAR_REJECTION– bearish candle with long upper wick (supply rejection)
    DOJI          – body < 10 % of total range
    INSIDE        – entire candle within previous candle's range
    SPINNING_TOP  – small body, significant wicks on both sides
    NEUTRAL       – does not qualify for any specialised label

Relative size labels (vs ATR):
    LARGE  – range > 1.5 × ATR
    NORMAL – range between 0.5 × ATR and 1.5 × ATR
    SMALL  – range < 0.5 × ATR
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper constants
# ---------------------------------------------------------------------------

_DOJI_BODY_THRESHOLD = 0.10        # body must be < 10 % of range to be a doji
_SPINNING_TOP_BODY_THRESHOLD = 0.30 # body < 30 % of range
_SPINNING_TOP_WICK_THRESHOLD = 0.20 # each wick > 20 % of range
_STRONG_BODY_THRESHOLD = 0.70       # body > 70 % of range → strong candle
_REJECTION_WICK_THRESHOLD = 0.40    # wick > 40 % of range → rejection candle
_LARGE_RANGE_MULT = 1.5
_SMALL_RANGE_MULT = 0.5


# ---------------------------------------------------------------------------
# CandleClassifier
# ---------------------------------------------------------------------------

class CandleClassifier:
    """
    Classifies individual candles and enriches a DataFrame with classification
    columns.

    Usage
    -----
    classifier = CandleClassifier()
    info = classifier.classify_candle(candle_series, atr_value)
    enriched_df = classifier.classify_all(df, atr_period=14)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_candle(self, candle: pd.Series, atr: float) -> dict:
        """
        Classify a single OHLC candle.

        Parameters
        ----------
        candle : pd.Series
            Must contain keys/index: 'open', 'high', 'low', 'close'.
            Optionally: 'is_confirmed' (bool, defaults to True).
        atr : float
            Average True Range value for the current period.

        Returns
        -------
        dict
            body_size, upper_wick, lower_wick, body_pct, upper_wick_pct,
            lower_wick_pct, is_bullish, is_bearish, is_doji, is_spinning_top,
            candle_type, relative_size, is_confirmed
        """
        open_  = float(candle['open'])
        high   = float(candle['high'])
        low    = float(candle['low'])
        close  = float(candle['close'])

        total_range = high - low
        if total_range <= 0:
            total_range = 1e-10  # prevent division-by-zero on degenerate bars

        body_top    = max(open_, close)
        body_bottom = min(open_, close)
        body_size   = body_top - body_bottom
        upper_wick  = high - body_top
        lower_wick  = body_bottom - low

        body_pct       = body_size / total_range
        upper_wick_pct = upper_wick / total_range
        lower_wick_pct = lower_wick / total_range

        is_bullish = close > open_
        is_bearish = close < open_

        is_doji = body_pct < _DOJI_BODY_THRESHOLD

        is_spinning_top = (
            not is_doji
            and body_pct < _SPINNING_TOP_BODY_THRESHOLD
            and upper_wick_pct > _SPINNING_TOP_WICK_THRESHOLD
            and lower_wick_pct > _SPINNING_TOP_WICK_THRESHOLD
        )

        # Relative size vs ATR
        if atr and atr > 0:
            relative_size = self._classify_relative_size(total_range, atr)
        else:
            relative_size = 'NORMAL'

        candle_type = self._determine_candle_type(
            is_doji=is_doji,
            is_spinning_top=is_spinning_top,
            is_bullish=is_bullish,
            is_bearish=is_bearish,
            body_pct=body_pct,
            upper_wick_pct=upper_wick_pct,
            lower_wick_pct=lower_wick_pct,
        )

        is_confirmed = bool(candle.get('is_confirmed', True))

        return {
            'body_size':       body_size,
            'upper_wick':      upper_wick,
            'lower_wick':      lower_wick,
            'body_pct':        round(body_pct, 4),
            'upper_wick_pct':  round(upper_wick_pct, 4),
            'lower_wick_pct':  round(lower_wick_pct, 4),
            'is_bullish':      is_bullish,
            'is_bearish':      is_bearish,
            'is_doji':         is_doji,
            'is_spinning_top': is_spinning_top,
            'candle_type':     candle_type,
            'relative_size':   relative_size,
            'is_confirmed':    is_confirmed,
        }

    def classify_all(self, df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
        """
        Classify every candle in the DataFrame and append classification columns.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with at least columns: open, high, low, close.
        atr_period : int
            Period for the ATR calculation.

        Returns
        -------
        pd.DataFrame
            Original DataFrame plus columns:
            atr, body_size, upper_wick, lower_wick, body_pct, upper_wick_pct,
            lower_wick_pct, is_bullish, is_bearish, is_doji, is_spinning_top,
            candle_type, relative_size, is_confirmed
        """
        df = df.copy()
        df = self._compute_atr(df, atr_period)

        classification_records = []
        for idx in range(len(df)):
            candle = df.iloc[idx]
            atr_val = float(candle.get('atr', 0)) if 'atr' in df.columns else 0.0
            record = self.classify_candle(candle, atr_val)
            classification_records.append(record)

        cls_df = pd.DataFrame(classification_records, index=df.index)

        # Drop columns already in df to avoid conflicts (except atr which we computed)
        cols_to_add = [c for c in cls_df.columns if c not in df.columns]
        df = pd.concat([df, cls_df[cols_to_add]], axis=1)
        return df

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Compute ATR using Wilder's smoothing and add as 'atr' column."""
        if 'atr' in df.columns:
            return df  # already computed upstream

        high  = df['high']
        low   = df['low']
        close = df['close']

        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
        atr = tr.ewm(span=period, adjust=False).mean()
        df = df.copy()
        df['atr'] = atr
        return df

    @staticmethod
    def _classify_relative_size(total_range: float, atr: float) -> str:
        if total_range > _LARGE_RANGE_MULT * atr:
            return 'LARGE'
        if total_range < _SMALL_RANGE_MULT * atr:
            return 'SMALL'
        return 'NORMAL'

    @staticmethod
    def _determine_candle_type(
        is_doji: bool,
        is_spinning_top: bool,
        is_bullish: bool,
        is_bearish: bool,
        body_pct: float,
        upper_wick_pct: float,
        lower_wick_pct: float,
    ) -> str:
        """Map candle geometry to a label string."""

        if is_doji:
            return 'DOJI'

        if is_spinning_top:
            return 'SPINNING_TOP'

        # Strong directional candles
        if body_pct >= _STRONG_BODY_THRESHOLD:
            if is_bullish:
                return 'STRONG_BULL'
            if is_bearish:
                return 'STRONG_BEAR'

        # Rejection candles – significant wick on the opposite side
        if is_bullish and lower_wick_pct >= _REJECTION_WICK_THRESHOLD:
            return 'BULL_REJECTION'

        if is_bearish and upper_wick_pct >= _REJECTION_WICK_THRESHOLD:
            return 'BEAR_REJECTION'

        return 'NEUTRAL'
