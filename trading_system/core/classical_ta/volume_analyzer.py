"""
core/classical_ta/volume_analyzer.py
===================================
Volume Analysis Engine for XAUUSD.
CRITICAL INTEGRITY PRINCIPLE: Explicitly acknowledges when data is broker tick
volume rather than centralized exchange volume. Provides Relative Volume (RVOL),
Volume Climax detection, Breakout Confirmation, and Volume Profile nodes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VolumeAnalyzer:
    """
    Performs volume behavior analysis, relative volume scoring,
    and breakout verification while preserving analytical integrity.
    """

    def analyze(
        self,
        df: pd.DataFrame,
        window: int = 20,
        volume_source: str = "MT5_TICK_VOLUME",
    ) -> dict[str, Any]:
        """
        Analyze volume trends, relative volume (RVOL), and abnormal spikes.
        """
        if df.empty or "volume" not in df.columns or len(df) < 5:
            return {
                "avg_volume": 0.0,
                "current_volume": 0.0,
                "relative_volume": 1.0,
                "volume_trend": "NEUTRAL",
                "breakout_volume_confirmed": False,
                "climax_detected": False,
                "volume_source": volume_source,
                "volume_disclosure": (
                    "Data represents broker tick activity (order frequency), "
                    "not total centralized traded cash volume."
                ),
            }

        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        curr_vol = float(vol.iloc[-1])
        recent_window = vol.iloc[-window:]
        avg_vol = float(recent_window.mean()) if len(recent_window) > 0 else 1.0
        avg_vol = max(avg_vol, 1.0)

        rvol = round(curr_vol / avg_vol, 2)

        # Volume Trend: compare short 5-bar SMA vs 20-bar SMA
        vol_5 = float(vol.iloc[-5:].mean()) if len(vol) >= 5 else curr_vol
        if vol_5 > avg_vol * 1.2:
            vol_trend = "INCREASING"
        elif vol_5 < avg_vol * 0.8:
            vol_trend = "DECREASING"
        else:
            vol_trend = "NEUTRAL"

        # Breakout volume confirmation: rvol >= 1.5
        breakout_confirmed = rvol >= 1.5

        # Volume climax: spike >= 2.5x average
        climax = rvol >= 2.5

        # Simple Volume Profile (Price Bins)
        nodes = self._calculate_volume_profile(df, n_bins=10)

        return {
            "avg_volume": round(avg_vol, 1),
            "current_volume": round(curr_vol, 1),
            "relative_volume": rvol,
            "volume_trend": vol_trend,
            "breakout_volume_confirmed": breakout_confirmed,
            "climax_detected": climax,
            "high_volume_nodes": nodes,
            "volume_source": volume_source,
            "volume_disclosure": (
                "Broker tick volume represents incoming quotation updates and broker order activity. "
                "Useful for relative activity comparisons and climax spikes, but not centralized volume."
            ),
        }

    def detect_climax_volume(
        self,
        df: pd.DataFrame,
        threshold_mult: float = 2.5,
        window: int = 20,
    ) -> list[dict[str, Any]]:
        """Identify historic volume climax bars."""
        if df.empty or "volume" not in df.columns or len(df) < window + 2:
            return []

        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        climaxes: list[dict[str, Any]] = []

        for i in range(window, len(df)):
            roll_mean = vol.iloc[i - window : i].mean()
            if roll_mean <= 0:
                continue
            cur = vol.iloc[i]
            ratio = cur / roll_mean
            if ratio >= threshold_mult:
                row = df.iloc[i]
                climaxes.append({
                    "index": i,
                    "time": str(row.get("time", "")),
                    "volume": float(cur),
                    "relative_multiple": round(float(ratio), 2),
                    "price_high": float(row.get("high", 0.0)),
                    "price_low": float(row.get("low", 0.0)),
                    "close": float(row.get("close", 0.0)),
                })

        return climaxes[-5:]

    def calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate standard volume-weighted average price (VWAP) across the DataFrame.
        """
        if df.empty or not {"high", "low", "close", "volume"}.issubset(df.columns):
            return pd.Series(dtype=float)

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = pd.to_numeric(df["volume"], errors="coerce").fillna(1.0)
        cum_vol_price = (typical_price * vol).cumsum()
        cum_vol = vol.cumsum()
        return (cum_vol_price / cum_vol).round(2)

    def _calculate_volume_profile(
        self,
        df: pd.DataFrame,
        n_bins: int = 10,
    ) -> list[dict[str, Any]]:
        """Divide the price range into bins and aggregate volume to find High Volume Nodes (HVNs)."""
        if len(df) < 10 or "close" not in df.columns or "volume" not in df.columns:
            return []

        low_p = float(df["low"].min())
        high_p = float(df["high"].max())
        if high_p <= low_p:
            return []

        bins = np.linspace(low_p, high_p, n_bins + 1)
        bin_vols = np.zeros(n_bins)

        closes = df["close"].to_numpy()
        vols = df["volume"].to_numpy(dtype=float)

        for c, v in zip(closes, vols):
            bin_idx = np.digitize(c, bins) - 1
            bin_idx = min(max(bin_idx, 0), n_bins - 1)
            bin_vols[bin_idx] += v

        # Identify top 2 bins with greatest volume (High Volume Nodes)
        sorted_bin_indices = np.argsort(bin_vols)[::-1]
        top_nodes = []
        for b_idx in sorted_bin_indices[:2]:
            price_mid = (bins[b_idx] + bins[b_idx + 1]) / 2.0
            top_nodes.append({
                "price": round(float(price_mid), 2),
                "volume": round(float(bin_vols[b_idx]), 1),
                "is_poc": len(top_nodes) == 0,  # First is Point of Control
            })

        return top_nodes
