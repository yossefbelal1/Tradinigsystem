"""
analysis/report_generator/report_builder.py
===========================================
Professional Structured Analytical Report Generator for XAUUSD.
Produces comprehensive, publication-grade technical analysis reports (Sections A through F)
in Markdown and HTML for the trader's decision-making and journal archiving.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ReportBuilder:
    """
    Builds the formal, 6-section multi-timeframe analytical report.
    """

    def build_full_report(
        self,
        symbol: str,
        current_price: float,
        data_timestamp: str,
        data_source: str,
        timeframe_analyses: dict[str, dict[str, Any]],
        synthesis: dict[str, Any],
        scenarios: dict[str, Any],
        ai_narrative: str,
        trade_plan: Optional[dict[str, Any]] = None,
        account_info: Optional[dict[str, Any]] = None,
        prop_firm_limits: Optional[dict[str, Any]] = None,
        volatility_info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Assemble the complete institutional market report dictionary.
        """
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        prec = 5 if current_price < 5.0 else (3 if current_price < 250.0 else 2)

        # Section A: Market Overview
        sec_a = {
            "instrument": symbol,
            "current_price": round(current_price, prec),
            "price_precision": prec,
            "data_timestamp": data_timestamp or now_str,
            "data_source": data_source,
            "overall_bias": synthesis.get("overall_bias", "NEUTRAL"),
            "bias_strength": synthesis.get("bias_strength", 0.0),
            "dominant_timeframe": synthesis.get("dominant_timeframe", "D1"),
            "volatility_regime": volatility_info.get("regime", "NORMAL") if volatility_info else "NORMAL",
            "current_atr": round(volatility_info.get("current_atr", current_price * 0.005) if volatility_info else current_price * 0.005, prec),
        }

        # Section B: Monthly Analysis
        mn1 = timeframe_analyses.get("MN1", {})
        sec_b = {
            "timeframe": "MN1",
            "candle_status": mn1.get("current_candle_status", "FORMING"),
            "trend": mn1.get("trend", "SIDEWAYS"),
            "bias": mn1.get("bias", "NEUTRAL"),
            "bias_reasoning": mn1.get("bias_reasoning", "N/A"),
            "key_resistance": [round(r["price"], prec) for r in mn1.get("nearest_resistance", [])],
            "key_support": [round(s["price"], prec) for s in mn1.get("nearest_support", [])],
            "supply_zones": [f"{z['bottom']:.{prec}f}-{z['top']:.{prec}f} ({z.get('state')})" for z in mn1.get("supply_zones", [])],
            "demand_zones": [f"{z['bottom']:.{prec}f}-{z['top']:.{prec}f} ({z.get('state')})" for z in mn1.get("demand_zones", [])],
            "next_candle_expectation": mn1.get("next_candle_expectation", ""),
            "bullish_scenario": mn1.get("bullish_scenario", ""),
            "bearish_scenario": mn1.get("bearish_scenario", ""),
            "invalidation_level": mn1.get("invalidation_level"),
        }

        # Section C: Weekly Analysis
        w1 = timeframe_analyses.get("W1", {})
        sec_c = {
            "timeframe": "W1",
            "candle_status": w1.get("current_candle_status", "FORMING"),
            "trend": w1.get("trend", "SIDEWAYS"),
            "bias": w1.get("bias", "NEUTRAL"),
            "bias_reasoning": w1.get("bias_reasoning", "N/A"),
            "relationship_with_monthly": "ALIGNED" if w1.get("bias") == mn1.get("bias") else "CONFLICTING/PULLBACK",
            "key_resistance": [round(r["price"], prec) for r in w1.get("nearest_resistance", [])],
            "key_support": [round(s["price"], prec) for s in w1.get("nearest_support", [])],
            "next_candle_expectation": w1.get("next_candle_expectation", ""),
            "bullish_scenario": w1.get("bullish_scenario", ""),
            "bearish_scenario": w1.get("bearish_scenario", ""),
        }

        # Section D: Daily Analysis
        d1 = timeframe_analyses.get("D1", {})
        sec_d = {
            "timeframe": "D1",
            "candle_status": d1.get("current_candle_status", "FORMING"),
            "trend": d1.get("trend", "SIDEWAYS"),
            "bias": d1.get("bias", "NEUTRAL"),
            "alignment_with_weekly": "ALIGNED" if d1.get("bias") == w1.get("bias") else "COUNTER-TREND / RETRACEMENT",
            "patterns": [p.get("pattern_type") for p in d1.get("recent_patterns", [])],
            "fresh_zones": [f"{z['type']} [{z['bottom']:.{prec}f}-{z['top']:.{prec}f}]" for z in d1.get("supply_zones", []) + d1.get("demand_zones", [])],
            "next_candle_expectation": d1.get("next_candle_expectation", ""),
        }

        # Section E: Intraday Analysis (H4, H1, M30, M15)
        sec_e = {
            "h4_bias": timeframe_analyses.get("H4", {}).get("bias", "NEUTRAL"),
            "h1_bias": timeframe_analyses.get("H1", {}).get("bias", "NEUTRAL"),
            "m30_bias": timeframe_analyses.get("M30", {}).get("bias", "NEUTRAL"),
            "m15_bias": timeframe_analyses.get("M15", {}).get("bias", "NEUTRAL"),
            "best_execution_timeframe": synthesis.get("entry_timeframe", "M15"),
            "intraday_trigger": synthesis.get("entry_pattern", "None confirmed"),
            "entry_zone": f"{trade_plan.get('entry_zone_low', 0):.{prec}f} - {trade_plan.get('entry_zone_high', 0):.{prec}f}" if trade_plan else "N/A",
            "stop_loss": trade_plan.get("stop_loss") if trade_plan else None,
            "take_profit_1": trade_plan.get("take_profit_1") if trade_plan else None,
            "take_profit_2": trade_plan.get("take_profit_2") if trade_plan else None,
            "risk_reward_tp1": trade_plan.get("risk_reward_tp1") if trade_plan else None,
            "price_precision": prec,
        }

        # Section F: Final Decision
        sec_f = {
            "decision": synthesis.get("signal", "NO_TRADE"),
            "setup_quality": synthesis.get("setup_quality", "D"),
            "decision_reasoning": synthesis.get("signal_reasoning", ""),
            "ai_narrative": ai_narrative,
            "trade_plan": trade_plan,
            "prop_firm_status": prop_firm_limits.get("firm_name") if prop_firm_limits else "Standard Risk",
            "remaining_daily_risk_usd": prop_firm_limits.get("daily_loss_remaining_usd") if prop_firm_limits else None,
            "actionable_instructions": (
                "Review the trade plan parameters above. If confirmed, MANUALLY enter the order in MetaTrader 5. "
                "The system will monitor the position once open." if trade_plan else "No trading action recommended. Stand aside."
            ),
        }

        report = {
            "title": f"Institutional Technical Analysis Report: {symbol}",
            "generated_at": now_str,
            "section_a_market_overview": sec_a,
            "section_b_monthly_analysis": sec_b,
            "section_c_weekly_analysis": sec_c,
            "section_d_daily_analysis": sec_d,
            "section_e_intraday_analysis": sec_e,
            "section_f_final_decision": sec_f,
        }

        report["markdown"] = self.format_as_markdown(report)
        return report

    def format_as_markdown(self, report: dict[str, Any]) -> str:
        """Render report as clean GitHub-Flavored Markdown."""
        a = report["section_a_market_overview"]
        b = report["section_b_monthly_analysis"]
        c = report["section_c_weekly_analysis"]
        d = report["section_d_daily_analysis"]
        e = report["section_e_intraday_analysis"]
        f = report["section_f_final_decision"]

        prec = a.get("price_precision", 2)
        sym = str(a.get("instrument", ""))
        prefix = "$" if "USD" in sym and not any(f in sym for f in ["EUR", "GBP", "AUD", "NZD"]) else ""

        lines = [
            f"# {report['title']}",
            f"> Generated: {report['generated_at']} | Data Source: {a['data_source']} | Price: **{prefix}{a['current_price']:.{prec}f}**",
            "",
            "---",
            "## A. Market Overview",
            f"- **Instrument:** {a['instrument']}",
            f"- **Current Spot Price:** {prefix}{a['current_price']:.{prec}f}",
            f"- **Overall Market Bias:** **{a['overall_bias']}** (Strength: {a['bias_strength'] * 100:.0f}%)",
            f"- **Dominant Macro Timeframe:** {a['dominant_timeframe']}",
            f"- **Volatility Regime:** {a['volatility_regime']} (Current ATR: {a['current_atr']:.{prec}f})",
            "",
            "---",
            "## B. Monthly (MN1) Analysis",
            f"> Status: `{b['candle_status']}` (Never treat an unfinished monthly bar as confirmed close)",
            f"- **Macro Trend:** {b['trend']} | **Bias:** {b['bias']}",
            f"- **Structural Reasoning:** {b['bias_reasoning']}",
            f"- **Key Resistances Above:** {', '.join(f'{p:.{prec}f}' for p in b['key_resistance']) or 'None nearby'}",
            f"- **Key Supports Below:** {', '.join(f'{p:.{prec}f}' for p in b['key_support']) or 'None nearby'}",
            f"- **Active Supply Zones:** {', '.join(b['supply_zones']) or 'None'}",
            f"- **Active Demand Zones:** {', '.join(b['demand_zones']) or 'None'}",
            f"- **Candle Expectation:** {b['next_candle_expectation']}",
            "",
            "---",
            "## C. Weekly (W1) Analysis",
            f"- **Intermediate Trend:** {c['trend']} | **Bias:** {c['bias']}",
            f"- **Relationship with Monthly:** **{c['relationship_with_monthly']}**",
            f"- **Weekly Reaction Levels:** Resistance: {', '.join(f'{p:.{prec}f}' for p in c['key_resistance']) or 'None'} | Support: {', '.join(f'{p:.{prec}f}' for p in c['key_support']) or 'None'}",
            f"- **Weekly Candle Scenarios:** {c['next_candle_expectation']}",
            "",
            "---",
            "## D. Daily (D1) Setup Identification",
            f"- **Daily Structure:** {d['trend']} | **Bias:** {d['bias']} ({d['alignment_with_weekly']})",
            f"- **Active Price Action Formations:** {', '.join(d['patterns']) or 'No major reversal patterns'}",
            f"- **Fresh Technical Zones:** {', '.join(d['fresh_zones']) or 'None in immediate range'}",
            f"- **Daily Expectation:** {d['next_candle_expectation']}",
            "",
            "---",
            "## E. Intraday Opportunity Analysis (H4 / H1 / M30 / M15)",
            f"- **Timeframe Alignment Strip:** H4: `{e['h4_bias']}` | H1: `{e['h1_bias']}` | M30: `{e['m30_bias']}` | M15: `{e['m15_bias']}`",
            f"- **Optimal Execution Timeframe:** {e['best_execution_timeframe']}",
            f"- **Intraday Entry Trigger:** {e['intraday_trigger']}",
        ]

        if e.get("stop_loss"):
            lines.extend([
                f"- **Entry Zone:** {e['entry_zone']}",
                f"- **Stop Loss Level:** {e['stop_loss']:.{prec}f}",
                f"- **Take Profit 1:** {e['take_profit_1']:.{prec}f} (R:R: {e['risk_reward_tp1']:.2f})",
                f"- **Take Profit 2:** {e['take_profit_2']:.{prec}f}",
            ])

        lines.extend([
            "",
            "---",
            "## F. Final Decision & Synthesis",
            f"### **DECISION: {f['decision']}** (Setup Grade: `{f['setup_quality']}`)",
            f"> **Reasoning:** {f['decision_reasoning']}",
            "",
            "### AI Contextual Synthesis",
            f['ai_narrative'],
            "",
            "### Actionable Guidance",
            f"> **[MANUAL TRADING PROTOCOL]:** {f['actionable_instructions']}",
        ])

        return "\n".join(lines)
