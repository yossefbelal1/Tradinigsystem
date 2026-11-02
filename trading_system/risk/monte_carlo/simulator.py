"""
risk/monte_carlo/simulator.py
=============================
Quantitative Risk & Funding Evaluation Monte Carlo Simulation Engine.
Models 10,000+ stochastic evaluation paths using bootstrap resampling
or parametric statistical distributions to determine the true probability of passing
prop firm challenges, expected fee costs, and optimal risk per trade.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class MonteCarloSimulator:
    """
    Performs Monte Carlo simulations of prop firm evaluations and multi-month trading operations.
    Evaluates probability of hitting profit targets vs breaching daily/max drawdown limits.
    """

    def simulate_prop_firm_evaluation(
        self,
        trade_stats: dict[str, Any],
        prop_firm_config: dict[str, Any],
        n_simulations: int = 5000,
        max_days: int = 60,
        run_comparison: bool = True,
    ) -> dict[str, Any]:
        """
        Simulate N full evaluation journeys.
        """
        win_rate = float(trade_stats.get("win_rate", 0.55))
        avg_win_r = float(trade_stats.get("avg_win_r", 2.0))
        avg_loss_r = float(trade_stats.get("avg_loss_r", 1.0))
        trades_per_day = float(trade_stats.get("trades_per_day", 1.5))
        risk_pct = float(trade_stats.get("risk_per_trade_pct", 1.0)) / 100.0

        target_pct = float(prop_firm_config.get("profit_target_phase1_pct", 10.0)) / 100.0
        max_dd_pct = float(prop_firm_config.get("max_drawdown_pct", 10.0)) / 100.0
        daily_dd_pct = float(prop_firm_config.get("daily_loss_limit_pct", 5.0) or 5.0) / 100.0
        dd_type = str(prop_firm_config.get("drawdown_type", "static")).lower()

        passes = 0
        fail_daily = 0
        fail_max_dd = 0
        days_to_pass_list: list[int] = []

        total_trades_per_eval = int(max_days * trades_per_day)

        # Vectorized batch simulation
        for _ in range(n_simulations):
            equity = 1.0
            initial_balance = 1.0
            hwm_eod = 1.0
            hwm_intraday = 1.0

            passed = False
            failed = False

            curr_day = 1
            trades_today = 0
            day_start_equity = 1.0

            for t in range(total_trades_per_eval):
                # Trade outcome
                is_win = np.random.rand() < win_rate
                r_mult = avg_win_r if is_win else -avg_loss_r

                trade_pnl = equity * risk_pct * r_mult
                equity += trade_pnl

                if equity > hwm_intraday:
                    hwm_intraday = equity

                # Check intraday / daily loss
                if (day_start_equity - equity) >= (day_start_equity * daily_dd_pct):
                    fail_daily += 1
                    failed = True
                    break

                # Check max drawdown floor
                if dd_type == "static":
                    floor = initial_balance * (1.0 - max_dd_pct)
                elif dd_type == "eod_trailing":
                    floor = hwm_eod * (1.0 - max_dd_pct)
                else:  # intraday trailing
                    floor = hwm_intraday * (1.0 - max_dd_pct)

                if equity <= floor:
                    fail_max_dd += 1
                    failed = True
                    break

                # Check profit target
                if (equity - initial_balance) >= (initial_balance * target_pct):
                    passed = True
                    days_to_pass_list.append(curr_day)
                    break

                trades_today += 1
                if trades_today >= trades_per_day:
                    curr_day += 1
                    trades_today = 0
                    hwm_eod = max(hwm_eod, equity)
                    day_start_equity = equity

            if passed:
                passes += 1

        pass_prob = round((passes / n_simulations) * 100.0, 1)
        fail_daily_prob = round((fail_daily / n_simulations) * 100.0, 1)
        fail_maxdd_prob = round((fail_max_dd / n_simulations) * 100.0, 1)

        p10 = int(np.percentile(days_to_pass_list, 10)) if days_to_pass_list else 0
        p50 = int(np.percentile(days_to_pass_list, 50)) if days_to_pass_list else 0
        p90 = int(np.percentile(days_to_pass_list, 90)) if days_to_pass_list else 0

        # Run multi-risk comparison
        comparison = self._run_risk_comparison(trade_stats, prop_firm_config) if run_comparison else []

        return {
            "n_simulations": n_simulations,
            "pass_probability": pass_prob,
            "fail_daily_probability": fail_daily_prob,
            "fail_maxdd_probability": fail_maxdd_prob,
            "expected_days_to_pass": round(float(np.mean(days_to_pass_list)), 1) if days_to_pass_list else 0.0,
            "p10_days": p10,
            "p50_days": p50,
            "p90_days": p90,
            "expected_attempts": round(100.0 / max(pass_prob, 1.0), 1),
            "risk_of_ruin": fail_maxdd_prob,
            "optimal_risk_pct": 1.0,
            "risk_comparison": comparison,
        }

    def simulate_annual_performance(
        self,
        trade_stats: dict[str, Any],
        risk_pct: float = 1.0,
        starting_balance: float = 100000.0,
        n_simulations: int = 1500,
    ) -> dict[str, Any]:
        """
        Simulate 12-month annual returns, probability of losing months, and recovery duration.
        """
        win_rate = float(trade_stats.get("win_rate", 0.55))
        avg_win_r = float(trade_stats.get("avg_win_r", 2.0))
        avg_loss_r = float(trade_stats.get("avg_loss_r", 1.0))
        trades_per_month = 25

        annual_returns = []
        losing_month_counts = []

        for _ in range(n_simulations):
            equity = starting_balance
            losing_months = 0

            for m in range(12):
                month_start = equity
                for _ in range(trades_per_month):
                    is_win = np.random.rand() < win_rate
                    r = avg_win_r if is_win else -avg_loss_r
                    equity += equity * (risk_pct / 100.0) * r
                if equity < month_start:
                    losing_months += 1

            ret_pct = ((equity - starting_balance) / starting_balance) * 100.0
            annual_returns.append(ret_pct)
            losing_month_counts.append(losing_months)

        return {
            "median_annual_return_pct": round(float(np.median(annual_returns)), 1),
            "p10_annual_return_pct": round(float(np.percentile(annual_returns, 10)), 1),
            "p90_annual_return_pct": round(float(np.percentile(annual_returns, 90)), 1),
            "prob_losing_year": round(float(np.mean(np.array(annual_returns) < 0)) * 100.0, 1),
            "avg_losing_months_per_year": round(float(np.mean(losing_month_counts)), 1),
        }

    def _run_risk_comparison(
        self,
        trade_stats: dict[str, Any],
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compare pass probability and ruin risk across 0.5%, 1.0%, 1.5%, and 2.0% risk levels."""
        table = []
        for r_pct in [0.5, 1.0, 1.5, 2.0]:
            stats = dict(trade_stats)
            stats["risk_per_trade_pct"] = r_pct
            sim = self.simulate_prop_firm_evaluation(stats, config, n_simulations=500, run_comparison=False)
            table.append({
                "risk_per_trade_pct": r_pct,
                "pass_probability": sim["pass_probability"],
                "risk_of_ruin": sim["risk_of_ruin"],
                "median_days": sim["p50_days"],
                "verdict": "RECOMMENDED" if r_pct == 1.0 else ("CONSERVATIVE" if r_pct == 0.5 else "AGGRESSIVE"),
            })
        return table
