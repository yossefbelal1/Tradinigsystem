"""
risk/portfolio/exposure_monitor.py
==================================
Portfolio Exposure and Correlation Monitor for Multi-Asset Trading.
Delegates to MultiAssetPortfolioEngine to enforce cumulative risk limits,
currency concentration caps, and correlation-adjusted drawdown limits.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from trading_system.config.settings import MAX_DAILY_RISK_PCT, MAX_RISK_PCT
from trading_system.risk.portfolio.multi_asset_portfolio import MultiAssetPortfolioEngine
from trading_system.risk.trade_manager.trade_plan import TradePlan

logger = logging.getLogger(__name__)


class PortfolioExposureMonitor:
    """
    Computes real-time portfolio-level exposure, netting, correlated risks,
    and enforces maximum allowable portfolio drawdown limits.
    """

    def __init__(self, engine: Optional[MultiAssetPortfolioEngine] = None):
        self.engine = engine or MultiAssetPortfolioEngine()

    def calculate_exposure(
        self,
        open_positions: list[dict[str, Any]],
        account_info: dict[str, Any],
        default_pip_value: float = 1.0,
    ) -> dict[str, Any]:
        """
        Compute total open exposure, direction netting, and worst-case risk across all positions.
        """
        report = self.engine.analyze_portfolio(open_positions, account_info)

        long_lots = sum(
            float(p.get("volume", 0.0)) for p in open_positions
            if str(p.get("type", "")).upper() in ("BUY", "0")
        )
        short_lots = sum(
            float(p.get("volume", 0.0)) for p in open_positions
            if str(p.get("type", "")).upper() in ("SELL", "1")
        )

        curr_exp_dict = {
            k: {
                "net_usd": v.net_exposure_usd,
                "pct_equity": v.exposure_pct_of_equity,
                "is_concentrated": v.is_concentrated,
            }
            for k, v in report.currency_exposures.items()
        }

        return {
            "total_lots": report.total_lots,
            "net_lots": round(long_lots - short_lots, 2),
            "long_lots": round(long_lots, 2),
            "short_lots": round(short_lots, 2),
            "total_monetary_risk_usd": report.total_unhedged_risk_usd,
            "total_risk_pct": report.total_unhedged_risk_pct,
            "correlation_adjusted_risk_usd": report.correlation_adjusted_risk_usd,
            "correlation_adjusted_risk_pct": report.correlation_adjusted_risk_pct,
            "worst_case_loss_usd": report.worst_case_loss_usd,
            "floating_pnl_usd": report.floating_pnl_usd,
            "currency_exposures": curr_exp_dict,
            "high_correlation_pairs": report.high_correlation_pairs,
            "concentration_warning": len(report.concentration_warnings) > 0,
            "warnings": report.concentration_warnings,
        }

    def check_new_trade_impact(
        self,
        current_exposure: dict[str, Any],
        new_plan: TradePlan,
        account_info: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Evaluate if adding this planned trade would breach portfolio or daily risk boundaries.
        """
        equity = float(account_info.get("equity", 10000.0))
        cur_risk_usd = float(current_exposure.get("total_monetary_risk_usd", 0.0))
        projected_risk_usd = cur_risk_usd + new_plan.monetary_risk_usd
        projected_risk_pct = (projected_risk_usd / max(equity, 1.0)) * 100.0

        max_allowed_pct = MAX_DAILY_RISK_PCT * 100.0
        warnings: list[str] = []

        allowed = True
        if projected_risk_pct > max_allowed_pct:
            allowed = False
            warnings.append(
                f"Adding this setup would push total risk to {projected_risk_pct:.2f}%, "
                f"exceeding max portfolio limit of {max_allowed_pct:.1f}%."
            )

        # Check hedging / opposing positions
        net_lots = float(current_exposure.get("net_lots", 0.0))
        if (new_plan.direction == "BUY" and net_lots < -0.01) or (new_plan.direction == "SELL" and net_lots > 0.01):
            warnings.append("Note: This trade opposes existing net position direction (creates hedge).")

        return {
            "allowed": allowed,
            "current_risk_usd": round(cur_risk_usd, 2),
            "new_trade_risk_usd": round(new_plan.monetary_risk_usd, 2),
            "projected_risk_usd": round(projected_risk_usd, 2),
            "projected_risk_pct": round(projected_risk_pct, 2),
            "warnings": warnings,
        }
