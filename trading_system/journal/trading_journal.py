"""
journal/trading_journal.py
==========================
SQLite-backed Trading Journal and Post-Trade Analytical Performance Review Engine.
Records every trade blueprint, tracks actual execution vs. theoretical plan,
computes R-multiples, and analyzes whether outcomes were driven by market dynamics or execution errors.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from trading_system.config.settings import JOURNAL_DB_PATH
from trading_system.risk.trade_manager.trade_plan import TradePlan

logger = logging.getLogger(__name__)


class TradingJournal:
    """
    Manages historical trade records and objective performance reviews in SQLite.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or JOURNAL_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT UNIQUE,
                created_at TEXT,
                symbol TEXT,
                direction TEXT,
                status TEXT,
                entry_price REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                lots REAL,
                monetary_risk_usd REAL,
                risk_pct REAL,
                setup_quality TEXT,
                htf_bias TEXT,
                risk_reward_tp1 REAL,
                risk_reward_tp2 REAL,
                actual_entry REAL,
                actual_sl REAL,
                actual_tp REAL,
                actual_lots REAL,
                mt5_ticket INTEGER,
                exit_price REAL,
                exit_time TEXT,
                realized_pnl_usd REAL,
                commission_usd REAL,
                swap_usd REAL,
                net_pnl_usd REAL,
                r_multiple REAL,
                outcome TEXT,
                exit_reason TEXT,
                analysis_accuracy TEXT,
                lessons_learned TEXT,
                plan_json TEXT
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_performance (
                date TEXT PRIMARY KEY,
                starting_balance REAL,
                ending_equity REAL,
                daily_pnl REAL,
                daily_pnl_pct REAL,
                trades_count INTEGER,
                wins INTEGER,
                losses INTEGER
            );
            """)
            conn.commit()

    def save_plan(self, plan: TradePlan) -> str:
        """Record a newly generated TradePlan."""
        plan_dict = plan.to_dict()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO trades (
                plan_id, created_at, symbol, direction, status,
                entry_price, sl, tp1, tp2, lots, monetary_risk_usd,
                risk_pct, setup_quality, htf_bias, risk_reward_tp1, risk_reward_tp2,
                plan_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan.plan_id,
                str(plan.created_at),
                plan.symbol,
                plan.direction,
                plan.status,
                plan.entry_price,
                plan.stop_loss,
                plan.take_profit_1,
                plan.take_profit_2,
                plan.position_size_lots,
                plan.monetary_risk_usd,
                plan.risk_pct_of_equity,
                plan.setup_quality,
                plan.htf_bias,
                plan.risk_reward_tp1,
                plan.risk_reward_tp2,
                json.dumps(plan_dict),
            ))
            conn.commit()
        return plan.plan_id

    def update_plan_status(
        self,
        plan_id: str,
        status: str,
        mt5_ticket: Optional[int] = None,
        actual_entry: Optional[float] = None,
        actual_lots: Optional[float] = None,
    ) -> None:
        """Update live execution status when trader executes in MT5."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE trades SET
                status = ?,
                mt5_ticket = COALESCE(?, mt5_ticket),
                actual_entry = COALESCE(?, actual_entry),
                actual_lots = COALESCE(?, actual_lots)
            WHERE plan_id = ?
            """, (status, mt5_ticket, actual_entry, actual_lots, plan_id))
            conn.commit()

    def record_trade_closed(
        self,
        plan_id: str,
        exit_data: dict[str, Any],
    ) -> None:
        """Record the realized outcome and compute R-multiple once position closes."""
        exit_p = float(exit_data.get("exit_price", 0.0))
        realized_pnl = float(exit_data.get("realized_pnl_usd", 0.0))
        comm = float(exit_data.get("commission_usd", 0.0))
        swap = float(exit_data.get("swap_usd", 0.0))
        net_pnl = realized_pnl + comm + swap

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT monetary_risk_usd FROM trades WHERE plan_id = ?", (plan_id,))
            row = cursor.fetchone()
            risk_usd = float(row["monetary_risk_usd"]) if row and row["monetary_risk_usd"] else 100.0

            r_mult = round(net_pnl / max(risk_usd, 1.0), 2)
            outcome = "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BREAKEVEN")

            cursor.execute("""
            UPDATE trades SET
                status = 'COMPLETED',
                exit_price = ?,
                exit_time = ?,
                realized_pnl_usd = ?,
                commission_usd = ?,
                swap_usd = ?,
                net_pnl_usd = ?,
                r_multiple = ?,
                outcome = ?,
                exit_reason = ?,
                lessons_learned = ?
            WHERE plan_id = ?
            """, (
                exit_p,
                datetime.now(timezone.utc).isoformat(),
                realized_pnl,
                comm,
                swap,
                net_pnl,
                r_mult,
                outcome,
                exit_data.get("exit_reason", "Target / Stop Hit"),
                exit_data.get("lessons_learned", ""),
                plan_id,
            ))
            conn.commit()

    def get_trade_history(self, days: int = 90) -> list[dict[str, Any]]:
        """Retrieve recent trade history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_performance_stats(self, days: int = 90) -> dict[str, Any]:
        """Compute aggregate performance statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE status = 'COMPLETED'")
            rows = cursor.fetchall()

        if not rows:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy_r": 0.0,
                "max_consecutive_losses": 0,
            }

        trades = [dict(r) for r in rows]
        wins = [t for t in trades if t["net_pnl_usd"] and t["net_pnl_usd"] > 0]
        losses = [t for t in trades if t["net_pnl_usd"] and t["net_pnl_usd"] < 0]

        total = len(trades)
        win_rate = round((len(wins) / total) * 100.0, 1)

        gross_profit = sum(float(w["net_pnl_usd"]) for w in wins)
        gross_loss = abs(sum(float(l["net_pnl_usd"]) for l in losses))
        profit_factor = round(gross_profit / max(gross_loss, 1.0), 2)

        r_multiples = [float(t.get("r_multiple", 0.0)) for t in trades]
        expectancy = round(float(pd.Series(r_multiples).mean()), 2) if r_multiples else 0.0

        # Calculate max consecutive losses
        max_consec = 0
        curr_consec = 0
        for t in trades:
            if t["net_pnl_usd"] and t["net_pnl_usd"] < 0:
                curr_consec += 1
                max_consec = max(max_consec, curr_consec)
            else:
                curr_consec = 0

        return {
            "total_trades": total,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy_r": expectancy,
            "max_consecutive_losses": max_consec,
            "gross_profit_usd": round(gross_profit, 2),
            "gross_loss_usd": round(gross_loss, 2),
        }
