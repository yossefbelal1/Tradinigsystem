"""
pattern_detector.py
===================
PatternDetector – detects professional-grade price-action patterns for XAUUSD.

Pattern families implemented
-----------------------------
Al Brooks:
  - Signal bars  (bullish / bearish)
  - Reversal bars
  - Breakout bars

Nial Fuller:
  - Pin bars        (bullish / bearish)
  - Inside bars     (with sequence count + breakout detection)
  - Fakey patterns  (inside-bar false breakout)

Classic candlestick:
  - Engulfing       (bullish / bearish)
  - Hammers & shooting stars
  - Doji patterns   (4 subtypes with trend context)
  - Rejection candles at key levels

Every pattern dict includes:
  - pattern_type (str)
  - timestamp
  - candle_idx (int)
  - signal_direction: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  - location_score  (0-1)  – proximity to S/R or supply/demand
  - is_confirmed    (bool) – pattern candle is a closed candle
  - (pattern-specific fields)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_get(df: pd.DataFrame, idx: int, col: str, default: Any = np.nan) -> Any:
    """Safe indexed row access."""
    try:
        return df.iloc[idx][col]
    except (IndexError, KeyError):
        return default


def _nearest_sr_distance(price: float, sr_levels: list[float], atr: float) -> float:
    """Return the distance in ATR units from ``price`` to the nearest S/R level."""
    if not sr_levels or atr <= 0:
        return float('inf')
    distances = [abs(price - lvl) for lvl in sr_levels]
    return min(distances) / atr


def _location_score_from_distance(dist_atr: float) -> float:
    """Convert distance (in ATR units) to a 0-1 location score."""
    if dist_atr <= 0.3:
        return 1.0
    if dist_atr <= 0.6:
        return 0.7
    if dist_atr <= 1.0:
        return 0.4
    if dist_atr <= 2.0:
        return 0.2
    return 0.05


def _location_score_no_sr() -> float:
    """Default score when no S/R levels are available."""
    return 0.3


# ---------------------------------------------------------------------------
# PatternDetector
# ---------------------------------------------------------------------------

class PatternDetector:
    """
    Detects price-action patterns across multiple methodologies.

    All public methods return a ``list[dict]``.  Every dict always contains the
    keys: pattern_type, timestamp, candle_idx, signal_direction, location_score,
    is_confirmed.
    """

    # ================================================================
    # AL BROOKS PATTERNS
    # ================================================================

    def detect_signal_bars(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect Al Brooks signal bars.

        Bullish signal bar:
          - Closes in upper 2/3 of its range
          - Lower wick provides some rejection (> 5 % of range)
          - Range ≥ 0.5 × ATR
        Bearish signal bar:
          - Closes in lower 2/3 of its range
          - Upper wick provides some rejection (> 5 % of range)
          - Range ≥ 0.5 × ATR
        """
        sr_levels = sr_levels or []
        results = []

        for i in range(len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0 or rng < 0.5 * atr:
                continue

            mid = l + rng / 3  # upper 2/3 starts at lower-third mark

            # Position of close within range (0 = at low, 1 = at high)
            close_pct = (c - l) / rng
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l

            is_confirmed = bool(candle.get('is_confirmed', True))
            ts = candle.name if hasattr(candle, 'name') else i
            dist_atr = _nearest_sr_distance(c, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            # Bullish
            if close_pct >= 2 / 3 and lower_wick / rng > 0.05 and c > o:
                results.append({
                    'pattern_type':      'BULLISH_SIGNAL_BAR',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BULLISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'close_pct_range':   round(close_pct, 3),
                    'lower_wick_pct':    round(lower_wick / rng, 3),
                    'range_atr_ratio':   round(rng / atr, 2) if atr else None,
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

            # Bearish
            elif close_pct <= 1 / 3 and upper_wick / rng > 0.05 and c < o:
                results.append({
                    'pattern_type':      'BEARISH_SIGNAL_BAR',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BEARISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'close_pct_range':   round(close_pct, 3),
                    'upper_wick_pct':    round(upper_wick / rng, 3),
                    'range_atr_ratio':   round(rng / atr, 2) if atr else None,
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

        return results

    def detect_reversal_bars(
        self,
        df: pd.DataFrame,
        atr: float,
        trend_lookback: int = 10,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect Al Brooks reversal bars.

        A reversal bar:
          - Has a large range (> ATR)
          - Closes strongly AGAINST the prevailing trend direction
          - Occurs after an extended move (at least ``trend_lookback`` candles)

        The prior trend is measured by the direction of the last
        ``trend_lookback`` closes.
        """
        sr_levels = sr_levels or []
        results = []
        if len(df) < trend_lookback + 1:
            return results

        closes = df['close'].values

        for i in range(trend_lookback, len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0 or rng < atr:
                continue

            prior_window = closes[i - trend_lookback: i]
            trend_direction = np.sign(prior_window[-1] - prior_window[0])

            # Count consecutive bars in same direction
            direction_changes = np.sign(np.diff(prior_window))
            consecutive = 0
            for d in reversed(direction_changes):
                if d == trend_direction:
                    consecutive += 1
                else:
                    break

            if consecutive < int(trend_lookback * 0.5):
                continue  # not an extended move

            body = c - o
            body_direction = np.sign(body)

            # Must close against prior trend
            if body_direction == trend_direction or abs(body) < 0.4 * rng:
                continue

            signal_dir = 'BULLISH' if body_direction > 0 else 'BEARISH'
            is_confirmed = bool(candle.get('is_confirmed', True))
            ts = candle.name if hasattr(candle, 'name') else i
            dist_atr = _nearest_sr_distance(c, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            results.append({
                'pattern_type':      'REVERSAL_BAR',
                'timestamp':         ts,
                'candle_idx':        i,
                'signal_direction':  signal_dir,
                'open':              o, 'high': h, 'low': l, 'close': c,
                'prior_trend':       'BULLISH' if trend_direction > 0 else 'BEARISH',
                'consecutive_bars':  consecutive,
                'range_atr_ratio':   round(rng / atr, 2) if atr else None,
                'location_score':    round(loc_score, 3),
                'is_confirmed':      is_confirmed,
            })

        return results

    def detect_breakout_bars(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect Al Brooks breakout bars.

        A breakout bar:
          - Has a large body (> 0.6 × range)
          - Closes significantly beyond a key S/R level (within 0.5 ATR of level)
          - Range ≥ 1.0 × ATR
        """
        sr_levels = sr_levels or []
        results = []

        for i in range(1, len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0 or rng < atr:
                continue

            body = abs(c - o)
            if body / rng < 0.60:
                continue

            # Check if we've crossed an S/R level
            broken_levels = []
            for lvl in sr_levels:
                prev_close = float(df.iloc[i - 1]['close'])
                if prev_close < lvl < c:
                    broken_levels.append(('BULLISH', lvl))
                elif prev_close > lvl > c:
                    broken_levels.append(('BEARISH', lvl))

            if not broken_levels:
                # Still report if very strong bar close at extremes, but lower score
                direction = 'BULLISH' if c > o else 'BEARISH'
                dist_atr = _nearest_sr_distance(c, sr_levels, atr)
                loc_score = _location_score_from_distance(dist_atr) * 0.5 if sr_levels else 0.15
                if loc_score < 0.3:
                    continue
                broken_levels = [(direction, None)]

            for direction, level in broken_levels:
                is_confirmed = bool(candle.get('is_confirmed', True))
                ts = candle.name if hasattr(candle, 'name') else i
                dist_atr = _nearest_sr_distance(c, sr_levels, atr)
                loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

                results.append({
                    'pattern_type':      'BREAKOUT_BAR',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  direction,
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'broken_level':      level,
                    'body_pct':          round(body / rng, 3),
                    'range_atr_ratio':   round(rng / atr, 2) if atr else None,
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

        return results

    # ================================================================
    # NIAL FULLER PATTERNS
    # ================================================================

    def detect_pin_bars(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect Nial Fuller pin bars.

        Bullish pin bar:
          - Long lower wick ≥ 2/3 of total range
          - Small body in upper 1/3 of range
          - Nose (upper wick) small

        Bearish pin bar:
          - Long upper wick ≥ 2/3 of total range
          - Small body in lower 1/3 of range
          - Nose (lower wick) small
        """
        sr_levels = sr_levels or []
        results = []
        TAIL_MIN_RATIO = 2 / 3
        NOSE_MAX_RATIO = 0.15

        for i in range(len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0 or rng < 0.5 * atr:
                continue

            body_top    = max(o, c)
            body_bottom = min(o, c)
            upper_wick  = h - body_top
            lower_wick  = body_bottom - l
            body_size   = body_top - body_bottom

            is_confirmed = bool(candle.get('is_confirmed', True))
            ts = candle.name if hasattr(candle, 'name') else i
            dist_atr = _nearest_sr_distance((h + l) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            # Bullish pin bar – tail = lower wick
            tail_ratio_bull = lower_wick / rng
            nose_ratio_bull = upper_wick / rng
            body_pct_bull   = body_size / rng
            body_pos_pct    = (body_bottom - l) / rng  # where body starts

            if (
                tail_ratio_bull >= TAIL_MIN_RATIO
                and nose_ratio_bull <= NOSE_MAX_RATIO
                and body_pos_pct >= (1 - body_pct_bull - NOSE_MAX_RATIO)
            ):
                results.append({
                    'pattern_type':      'PIN_BAR',
                    'type':              'BULLISH_PIN',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BULLISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'tail_ratio':        round(tail_ratio_bull, 3),
                    'nose_ratio':        round(nose_ratio_bull, 3),
                    'body_pct':          round(body_pct_bull, 3),
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })
                continue

            # Bearish pin bar – tail = upper wick
            tail_ratio_bear = upper_wick / rng
            nose_ratio_bear = lower_wick / rng
            body_pct_bear   = body_size / rng
            body_pos_pct_bear = (h - body_top) / rng  # how far body is from top

            if (
                tail_ratio_bear >= TAIL_MIN_RATIO
                and nose_ratio_bear <= NOSE_MAX_RATIO
                and body_pos_pct_bear >= (1 - body_pct_bear - NOSE_MAX_RATIO)
            ):
                results.append({
                    'pattern_type':      'PIN_BAR',
                    'type':              'BEARISH_PIN',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BEARISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'tail_ratio':        round(tail_ratio_bear, 3),
                    'nose_ratio':        round(nose_ratio_bear, 3),
                    'body_pct':          round(body_pct_bear, 3),
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

        return results

    def detect_inside_bars(
        self,
        df: pd.DataFrame,
        sr_levels: Optional[list] = None,
        atr: float = 1.0,
    ) -> list[dict]:
        """
        Detect Nial Fuller inside bars.

        Supports sequences of multiple inside bars within the same mother candle.
        Includes breakout_direction if the bar immediately after the sequence
        breaks out of the mother candle range.
        """
        sr_levels = sr_levels or []
        results = []
        n = len(df)
        i = 1  # start from second bar

        while i < n:
            mother = df.iloc[i - 1]
            m_high = float(mother['high'])
            m_low  = float(mother['low'])

            # Count consecutive inside bars
            inside_count = 0
            j = i
            while j < n:
                bar = df.iloc[j]
                b_high = float(bar['high'])
                b_low  = float(bar['low'])
                if b_high <= m_high and b_low >= m_low:
                    inside_count += 1
                    j += 1
                else:
                    break

            if inside_count == 0:
                i += 1
                continue

            # Check breakout direction on the candle immediately after the sequence
            breakout_direction = None
            if j < n:
                next_bar = df.iloc[j]
                nb_close = float(next_bar['close'])
                if nb_close > m_high:
                    breakout_direction = 'BULLISH'
                elif nb_close < m_low:
                    breakout_direction = 'BEARISH'

            # Timestamp of the FIRST inside bar
            first_inside = df.iloc[i]
            ts = first_inside.name if hasattr(first_inside, 'name') else i
            is_confirmed = bool(first_inside.get('is_confirmed', True))

            dist_atr = _nearest_sr_distance((m_high + m_low) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            results.append({
                'pattern_type':        'INSIDE_BAR',
                'timestamp':           ts,
                'candle_idx':          i,
                'signal_direction':    breakout_direction or 'NEUTRAL',
                'mother_candle_high':  m_high,
                'mother_candle_low':   m_low,
                'mother_candle_idx':   i - 1,
                'inside_bar_count':    inside_count,
                'breakout_direction':  breakout_direction,
                'location_score':      round(loc_score, 3),
                'is_confirmed':        is_confirmed,
            })

            i = j  # skip past the inside bars

        return results

    def detect_fakey_patterns(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect Nial Fuller fakey patterns.

        Setup:
          1. Inside bar formation (inside_bar + mother candle)
          2. False breakout beyond mother candle range
          3. Candle closes BACK within the mother candle range
        Signal direction = OPPOSITE to the false breakout direction.
        """
        sr_levels = sr_levels or []
        results = []
        n = len(df)

        # First find inside bar positions
        inside_bar_positions = []
        for i in range(1, n):
            bar  = df.iloc[i]
            prev = df.iloc[i - 1]
            if float(bar['high']) <= float(prev['high']) and float(bar['low']) >= float(prev['low']):
                inside_bar_positions.append(i)

        for ib_idx in inside_bar_positions:
            if ib_idx + 1 >= n:
                continue

            mother_idx  = ib_idx - 1
            mother      = df.iloc[mother_idx]
            m_high      = float(mother['high'])
            m_low       = float(mother['low'])

            # Candle after inside bar = potential false breakout candle
            fb_candle   = df.iloc[ib_idx + 1]
            fb_high     = float(fb_candle['high'])
            fb_low      = float(fb_candle['low'])
            fb_close    = float(fb_candle['close'])

            false_break_dir   = None
            entry_direction   = None

            # Bullish false breakout (break above, close back inside)
            if fb_high > m_high and fb_close < m_high:
                false_break_dir = 'BULLISH'
                entry_direction = 'BEARISH'
            # Bearish false breakout (break below, close back inside)
            elif fb_low < m_low and fb_close > m_low:
                false_break_dir = 'BEARISH'
                entry_direction = 'BULLISH'
            else:
                continue

            ts = fb_candle.name if hasattr(fb_candle, 'name') else ib_idx + 1
            is_confirmed = bool(fb_candle.get('is_confirmed', True))
            dist_atr = _nearest_sr_distance((m_high + m_low) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            results.append({
                'pattern_type':        'FAKEY',
                'timestamp':           ts,
                'candle_idx':          ib_idx + 1,
                'signal_direction':    entry_direction,
                'direction':           false_break_dir,    # direction of false break
                'entry_direction':     entry_direction,
                'mother_candle_high':  m_high,
                'mother_candle_low':   m_low,
                'inside_bar_idx':      ib_idx,
                'false_break_high':    fb_high,
                'false_break_low':     fb_low,
                'false_break_close':   fb_close,
                'location_score':      round(loc_score, 3),
                'is_confirmed':        is_confirmed,
            })

        return results

    # ================================================================
    # CLASSIC CANDLESTICK PATTERNS
    # ================================================================

    def detect_engulfing(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect bullish and bearish engulfing patterns.

        Bullish engulfing:
          - Prior candle is bearish
          - Current candle is bullish
          - Current BODY fully engulfs prior BODY

        Bearish engulfing:
          - Prior candle is bullish
          - Current candle is bearish
          - Current BODY fully engulfs prior BODY
        """
        sr_levels = sr_levels or []
        results = []

        for i in range(1, len(df)):
            prev  = df.iloc[i - 1]
            curr  = df.iloc[i]

            prev_o, prev_c = float(prev['open']), float(prev['close'])
            curr_o, curr_c = float(curr['open']),  float(curr['close'])

            prev_body_top    = max(prev_o, prev_c)
            prev_body_bottom = min(prev_o, prev_c)
            curr_body_top    = max(curr_o, curr_c)
            curr_body_bottom = min(curr_o, curr_c)

            prev_body = abs(prev_c - prev_o)
            curr_body = abs(curr_c - curr_o)

            if prev_body <= 0 or curr_body <= 0:
                continue

            engulfing_strength = curr_body / prev_body if prev_body else 0

            ts = curr.name if hasattr(curr, 'name') else i
            is_confirmed = bool(curr.get('is_confirmed', True))
            dist_atr = _nearest_sr_distance((float(curr['high']) + float(curr['low'])) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            # Bullish engulfing
            if (
                prev_c < prev_o       # prior bearish
                and curr_c > curr_o   # current bullish
                and curr_body_bottom < prev_body_bottom
                and curr_body_top    > prev_body_top
            ):
                results.append({
                    'pattern_type':        'ENGULFING',
                    'type':                'BULLISH_ENGULFING',
                    'timestamp':           ts,
                    'candle_idx':          i,
                    'signal_direction':    'BULLISH',
                    'engulfing_strength':  round(engulfing_strength, 2),
                    'location_score':      round(loc_score, 3),
                    'is_confirmed':        is_confirmed,
                })

            # Bearish engulfing
            elif (
                prev_c > prev_o       # prior bullish
                and curr_c < curr_o   # current bearish
                and curr_body_top    > prev_body_top
                and curr_body_bottom < prev_body_bottom
            ):
                results.append({
                    'pattern_type':        'ENGULFING',
                    'type':                'BEARISH_ENGULFING',
                    'timestamp':           ts,
                    'candle_idx':          i,
                    'signal_direction':    'BEARISH',
                    'engulfing_strength':  round(engulfing_strength, 2),
                    'location_score':      round(loc_score, 3),
                    'is_confirmed':        is_confirmed,
                })

        return results

    def detect_hammers_and_shooting_stars(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect hammer and shooting-star patterns.

        Hammer (bullish, appears after downtrend):
          - Lower wick ≥ 2 × body
          - Upper wick < body

        Shooting star (bearish, appears after uptrend):
          - Upper wick ≥ 2 × body
          - Lower wick < body
        """
        sr_levels = sr_levels or []
        results = []
        WICK_BODY_MULT = 2.0

        for i in range(1, len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            body_top    = max(o, c)
            body_bottom = min(o, c)
            body_size   = body_top - body_bottom
            upper_wick  = h - body_top
            lower_wick  = body_bottom - l
            rng         = h - l

            if body_size <= 0 or rng < 0.3 * atr:
                continue

            ts = candle.name if hasattr(candle, 'name') else i
            is_confirmed = bool(candle.get('is_confirmed', True))
            dist_atr = _nearest_sr_distance((h + l) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            # Hammer
            if lower_wick >= WICK_BODY_MULT * body_size and upper_wick < body_size:
                # Verify downtrend context (prior 3 bars lower)
                if i >= 3:
                    prior_closes = [float(df.iloc[i - k]['close']) for k in range(1, 4)]
                    context = 'at_support' if all(pc > c for pc in prior_closes) else 'neutral'
                else:
                    context = 'neutral'

                results.append({
                    'pattern_type':      'HAMMER',
                    'type':              'HAMMER',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BULLISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'lower_wick_body_ratio': round(lower_wick / body_size, 2),
                    'context':           context,
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

            # Shooting star
            elif upper_wick >= WICK_BODY_MULT * body_size and lower_wick < body_size:
                if i >= 3:
                    prior_closes = [float(df.iloc[i - k]['close']) for k in range(1, 4)]
                    context = 'at_resistance' if all(pc < c for pc in prior_closes) else 'neutral'
                else:
                    context = 'neutral'

                results.append({
                    'pattern_type':      'SHOOTING_STAR',
                    'type':              'SHOOTING_STAR',
                    'timestamp':         ts,
                    'candle_idx':        i,
                    'signal_direction':  'BEARISH',
                    'open':              o, 'high': h, 'low': l, 'close': c,
                    'upper_wick_body_ratio': round(upper_wick / body_size, 2),
                    'context':           context,
                    'location_score':    round(loc_score, 3),
                    'is_confirmed':      is_confirmed,
                })

        return results

    def detect_doji_patterns(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
        trend_lookback: int = 5,
    ) -> list[dict]:
        """
        Detect doji patterns with subtype classification.

        Subtypes:
          - DOJI_REGULAR          : body < 5 % range, balanced wicks
          - DOJI_GRAVESTONE       : long upper wick, near-zero lower wick
          - DOJI_DRAGONFLY        : long lower wick, near-zero upper wick
          - DOJI_LONG_LEGGED      : long upper AND lower wicks

        Context enrichment:
          - After uptrend  → bearish warning
          - After downtrend → bullish warning
        """
        sr_levels = sr_levels or []
        results = []
        DOJI_BODY_PCT = 0.05
        GRAVESTONE_LOWER_MAX = 0.10
        DRAGONFLY_UPPER_MAX  = 0.10
        LONG_LEGGED_MIN      = 0.30

        for i in range(len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0 or rng < 0.3 * atr:
                continue

            body_size  = abs(c - o)
            body_pct   = body_size / rng
            if body_pct >= DOJI_BODY_PCT:
                continue  # not a doji

            upper_wick_pct = (h - max(o, c)) / rng
            lower_wick_pct = (min(o, c) - l) / rng

            # Subtype
            if (
                upper_wick_pct >= LONG_LEGGED_MIN
                and lower_wick_pct >= LONG_LEGGED_MIN
            ):
                subtype = 'DOJI_LONG_LEGGED'
            elif upper_wick_pct >= LONG_LEGGED_MIN and lower_wick_pct <= GRAVESTONE_LOWER_MAX:
                subtype = 'DOJI_GRAVESTONE'
            elif lower_wick_pct >= LONG_LEGGED_MIN and upper_wick_pct <= DRAGONFLY_UPPER_MAX:
                subtype = 'DOJI_DRAGONFLY'
            else:
                subtype = 'DOJI_REGULAR'

            # Trend context
            signal_direction = 'NEUTRAL'
            context_warning  = None
            if i >= trend_lookback:
                prior_closes = [float(df.iloc[i - k]['close']) for k in range(1, trend_lookback + 1)]
                prior_trend = np.sign(float(df.iloc[i - 1]['close']) - prior_closes[-1])
                if prior_trend > 0:
                    context_warning  = 'BEARISH_WARNING'  # doji after uptrend
                    signal_direction = 'BEARISH'
                elif prior_trend < 0:
                    context_warning  = 'BULLISH_WARNING'  # doji after downtrend
                    signal_direction = 'BULLISH'

            # Override for specific subtypes
            if subtype == 'DOJI_GRAVESTONE':
                signal_direction = 'BEARISH'
            elif subtype == 'DOJI_DRAGONFLY':
                signal_direction = 'BULLISH'

            ts = candle.name if hasattr(candle, 'name') else i
            is_confirmed = bool(candle.get('is_confirmed', True))
            dist_atr = _nearest_sr_distance((h + l) / 2, sr_levels, atr)
            loc_score = _location_score_from_distance(dist_atr) if sr_levels else _location_score_no_sr()

            results.append({
                'pattern_type':      'DOJI',
                'type':              subtype,
                'timestamp':         ts,
                'candle_idx':        i,
                'signal_direction':  signal_direction,
                'open':              o, 'high': h, 'low': l, 'close': c,
                'upper_wick_pct':    round(upper_wick_pct, 3),
                'lower_wick_pct':    round(lower_wick_pct, 3),
                'context_warning':   context_warning,
                'location_score':    round(loc_score, 3),
                'is_confirmed':      is_confirmed,
            })

        return results

    def detect_rejection_candles(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> list[dict]:
        """
        Detect rejection candles at key levels.

        Criteria:
          - Long wick (> 0.4 × range) touching a level within 0.3 × ATR
          - Candle closes away from the level (rejected)
        """
        sr_levels = sr_levels or []
        results = []
        WICK_MIN_PCT   = 0.40
        LEVEL_PROX_ATR = 0.30

        for i in range(len(df)):
            candle = df.iloc[i]
            o, h, l, c = (
                float(candle['open']),
                float(candle['high']),
                float(candle['low']),
                float(candle['close']),
            )
            rng = h - l
            if rng <= 0:
                continue

            body_top    = max(o, c)
            body_bottom = min(o, c)
            upper_wick  = h - body_top
            lower_wick  = body_bottom - l

            ts = candle.name if hasattr(candle, 'name') else i
            is_confirmed = bool(candle.get('is_confirmed', True))

            for level in sr_levels:
                # Upper wick rejection (bearish rejection at resistance)
                if (
                    upper_wick / rng >= WICK_MIN_PCT
                    and abs(h - level) <= LEVEL_PROX_ATR * atr
                    and c < level  # closed below resistance
                ):
                    dist_atr = abs(h - level) / atr if atr else 0
                    loc_score = _location_score_from_distance(dist_atr)
                    results.append({
                        'pattern_type':    'REJECTION_CANDLE',
                        'type':            'BEARISH_REJECTION',
                        'timestamp':       ts,
                        'candle_idx':      i,
                        'signal_direction':'BEARISH',
                        'open':            o, 'high': h, 'low': l, 'close': c,
                        'rejected_level':  level,
                        'wick_pct':        round(upper_wick / rng, 3),
                        'distance_atr':    round(dist_atr, 3),
                        'location_score':  round(loc_score, 3),
                        'is_confirmed':    is_confirmed,
                    })
                    break  # one rejection per candle

                # Lower wick rejection (bullish rejection at support)
                elif (
                    lower_wick / rng >= WICK_MIN_PCT
                    and abs(l - level) <= LEVEL_PROX_ATR * atr
                    and c > level  # closed above support
                ):
                    dist_atr = abs(l - level) / atr if atr else 0
                    loc_score = _location_score_from_distance(dist_atr)
                    results.append({
                        'pattern_type':    'REJECTION_CANDLE',
                        'type':            'BULLISH_REJECTION',
                        'timestamp':       ts,
                        'candle_idx':      i,
                        'signal_direction':'BULLISH',
                        'open':            o, 'high': h, 'low': l, 'close': c,
                        'rejected_level':  level,
                        'wick_pct':        round(lower_wick / rng, 3),
                        'distance_atr':    round(dist_atr, 3),
                        'location_score':  round(loc_score, 3),
                        'is_confirmed':    is_confirmed,
                    })
                    break

        return results

    # ================================================================
    # AGGREGATE
    # ================================================================

    def detect_all_patterns(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
    ) -> dict[str, list[dict]]:
        """
        Run all pattern detectors and return results grouped by family.

        Returns
        -------
        dict with keys: signal_bars, reversal_bars, breakout_bars, pin_bars,
            inside_bars, fakey, engulfing, hammers_shooting_stars, doji,
            rejection_candles
        """
        return {
            'signal_bars':           self.detect_signal_bars(df, atr, sr_levels),
            'reversal_bars':         self.detect_reversal_bars(df, atr),
            'breakout_bars':         self.detect_breakout_bars(df, atr, sr_levels),
            'pin_bars':              self.detect_pin_bars(df, atr, sr_levels),
            'inside_bars':           self.detect_inside_bars(df, sr_levels, atr),
            'fakey':                 self.detect_fakey_patterns(df, atr, sr_levels),
            'engulfing':             self.detect_engulfing(df, atr, sr_levels),
            'hammers_shooting_stars':self.detect_hammers_and_shooting_stars(df, atr, sr_levels),
            'doji':                  self.detect_doji_patterns(df, atr, sr_levels),
            'rejection_candles':     self.detect_rejection_candles(df, atr, sr_levels),
        }

    def detect_all(
        self,
        df: pd.DataFrame,
        atr: float,
        sr_levels: Optional[list] = None,
        lookback: int = 5,
    ) -> list[dict]:
        """Convenience method returning a flat list of patterns within lookback candles."""
        sr_floats = [
            lvl["price"] if isinstance(lvl, dict) else float(lvl)
            for lvl in (sr_levels or [])
        ]
        grouped = self.detect_all_patterns(df, atr=atr, sr_levels=sr_floats)
        all_pats = []
        for pat_list in grouped.values():
            all_pats.extend(pat_list)

        if lookback and lookback > 0:
            n = len(df)
            all_pats = [p for p in all_pats if p.get('candle_idx', 0) >= (n - lookback)]

        return all_pats
