"""
core/market_conditions/instrument_context.py
============================================
Universal Instrument-Aware Market Conditions & Session Context Engine.

Evaluates trading sessions, volatility regimes, macro drivers, event sensitivities,
and contextual liquidity characteristics for any financial instrument.
Ensures context is evaluated dynamically rather than applying rigid generic rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from trading_system.core.data.instrument_spec import AssetClass, InstrumentSpec

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """Current active global trading session status."""
    utc_time: datetime
    is_weekend: bool
    is_asian_session: bool
    is_london_session: bool
    is_ny_session: bool
    is_london_ny_overlap: bool
    is_us_cash_open: bool
    is_rollover_spread_risk: bool
    active_sessions: List[str] = field(default_factory=list)


@dataclass
class MarketConditionsReport:
    """Complete contextual assessment for a specific instrument."""
    symbol: str
    asset_class: str
    session_status: str
    is_market_open: bool
    optimal_execution_window: bool
    liquidity_condition: str      # 'HIGH', 'NORMAL', 'THIN', 'CLOSED'
    spread_risk: str              # 'NORMAL', 'ELEVATED', 'EXTREME'
    macro_drivers: List[str]      # Primary catalysts driving this instrument
    event_sensitivities: List[str] # High-impact recurring events
    contextual_warnings: List[str]
    session_context: SessionContext


class MarketConditionsAnalyzer:
    """
    Analyzes live market conditions adapted to each instrument's asset class
    and current global trading session.
    """

    @classmethod
    def get_current_session(cls, now_utc: Optional[datetime] = None) -> SessionContext:
        """Evaluate which global trading sessions are active right now."""
        now = now_utc or datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
        hour = now.hour
        minute = now.minute
        time_decimal = hour + minute / 60.0

        # Weekend: Saturday 00:00 UTC through Sunday ~21:00 UTC
        is_weekend = (weekday == 5) or (weekday == 6 and time_decimal < 21.0) or (weekday == 4 and time_decimal >= 22.0)

        # Global Session Windows in UTC:
        # Asian / Tokyo: 00:00 - 09:00 UTC
        is_asian = (0.0 <= time_decimal < 9.0) and not is_weekend
        # London: 07:00 - 16:00 UTC
        is_london = (7.0 <= time_decimal < 16.0) and not is_weekend
        # New York: 12:00 - 21:00 UTC
        is_ny = (12.0 <= time_decimal < 21.0) and not is_weekend
        # London / New York Overlap: 12:00 - 16:00 UTC (Peak global liquidity)
        is_overlap = is_london and is_ny
        # US Equity Cash Session: 13:30 - 20:00 UTC (Standard 09:30 - 16:00 EST)
        is_us_cash = (13.5 <= time_decimal < 20.0) and not is_weekend
        # Daily Rollover Window: 21:00 - 23:00 UTC (Spreads typically widen drastically)
        is_rollover = (21.0 <= time_decimal < 23.0) and not is_weekend

        active = []
        if is_overlap:
            active.append("London/New York Overlap (Peak Liquidity)")
        elif is_london:
            active.append("London Session")
        elif is_ny:
            active.append("New York Session")
        elif is_asian:
            active.append("Asian / Tokyo Session")
        elif is_weekend:
            active.append("Weekend (Traditional Markets Closed)")
        else:
            active.append("Inter-Session Transition")

        if is_us_cash:
            active.append("US Cash Equities Open")
        if is_rollover:
            active.append("Rollover Window (Wide Spreads)")

        return SessionContext(
            utc_time=now,
            is_weekend=is_weekend,
            is_asian_session=is_asian,
            is_london_session=is_london,
            is_ny_session=is_ny,
            is_london_ny_overlap=is_overlap,
            is_us_cash_open=is_us_cash,
            is_rollover_spread_risk=is_rollover,
            active_sessions=active,
        )

    @classmethod
    def evaluate(
        cls,
        spec: InstrumentSpec,
        now_utc: Optional[datetime] = None,
    ) -> MarketConditionsReport:
        """
        Produce a tailored contextual market report for the instrument.
        """
        session = cls.get_current_session(now_utc)
        ac = spec.asset_class
        symbol = spec.symbol.upper()

        macro_drivers: List[str] = []
        event_sensitivities: List[str] = []
        warnings: List[str] = []

        is_market_open = True
        optimal_window = False
        liquidity = "NORMAL"
        spread_risk = "NORMAL"

        # ── 1. CRYPTOCURRENCIES ──────────────────────────────────────────────
        if ac == AssetClass.CRYPTO:
            macro_drivers = [
                "Continuous 24/7 liquidity and perpetual funding rates",
                "BTC spot ETF flows & institutional adoption metrics",
                "Regulatory developments & stablecoin liquidity shifts",
            ]
            event_sensitivities = [
                "Weekend liquidity contractions & liquidation cascades",
                "Monthly/Quarterly options expiry (last Friday 08:00 UTC)",
                "US CPI and FOMC macro volatility spillover",
            ]
            if session.is_weekend:
                liquidity = "THIN"
                spread_risk = "ELEVATED"
                warnings.append("Weekend crypto trading: order book depth is thinner, raising slippage risk on large orders.")
                optimal_window = False
            else:
                optimal_window = session.is_ny_session or session.is_london_session
                liquidity = "HIGH" if optimal_window else "NORMAL"

        # ── 2. METALS (Gold, Silver) ─────────────────────────────────────────
        elif ac == AssetClass.METALS:
            macro_drivers = [
                "US Dollar Index (DXY) inverse sensitivity",
                "US 10-Year Real Yields (TIPS yields inverse relationship)",
                "Global central bank gold reserve purchases",
                "Geopolitical safe-haven hedging flows",
            ]
            event_sensitivities = [
                "FOMC rate decisions and Fed Chair press conferences",
                "US Non-Farm Payrolls (NFP - First Friday of month 12:30/13:30 UTC)",
                "US CPI / Core PCE inflation prints",
            ]
            if session.is_weekend:
                is_market_open = False
                liquidity = "CLOSED"
                warnings.append("Metals markets are closed for the weekend.")
            elif session.is_rollover_spread_risk:
                liquidity = "THIN"
                spread_risk = "EXTREME"
                warnings.append("Daily broker rollover (21:00-23:00 UTC): Gold spreads may expand by 3x-5x. Avoid market entry.")
            else:
                optimal_window = session.is_london_ny_overlap or session.is_london_session
                liquidity = "HIGH" if optimal_window else "NORMAL"
                if session.is_asian_session and not session.is_london_session:
                    warnings.append("Asian session for Gold typically exhibits range-bound, lower volume behavior unless Asia news breaks.")

        # ── 3. STOCK INDICES (NASDAQ, US30, US500, DAX) ─────────────────────
        elif ac == AssetClass.INDICES:
            is_us_index = any(idx in symbol for idx in ["USTEC", "US100", "NAS", "US30", "DJ30", "US500", "SPX"])
            is_eu_index = any(idx in symbol for idx in ["GER", "DAX", "UK100", "FTSE"])

            if is_us_index:
                macro_drivers = [
                    "Mega-cap tech earnings (Apple, Microsoft, Nvidia, Alphabet, Amazon)",
                    "Treasury yield curve dynamics and monetary policy path",
                    "US retail sales, GDP revisions, and consumer sentiment",
                ]
                event_sensitivities = [
                    "US Cash Equity Open (13:30 UTC / 09:30 EST) opening auction volatility",
                    "FOMC rate decisions and economic projections (SEP)",
                    "Triple/Quadruple Witching options expiration days",
                ]
                if session.is_weekend:
                    is_market_open = False
                    liquidity = "CLOSED"
                    warnings.append("Index CFD markets are closed for the weekend.")
                elif session.is_us_cash_open:
                    optimal_window = True
                    liquidity = "HIGH"
                elif session.is_asian_session:
                    liquidity = "THIN"
                    spread_risk = "ELEVATED"
                    warnings.append("US index futures trade in low liquidity during Asian hours with wider spreads.")
            elif is_eu_index:
                macro_drivers = [
                    "ECB/BoE interest rate decisions and monetary guidance",
                    "European manufacturing/services PMI surveys",
                    "EUR/GBP foreign exchange competitiveness",
                ]
                event_sensitivities = [
                    "European market open (07:00/08:00 UTC)",
                    "ECB policy statements and inflation reports",
                ]
                optimal_window = session.is_london_session and not session.is_weekend
                liquidity = "HIGH" if optimal_window else "NORMAL"

        # ── 4. COMMODITIES (Crude Oil, Natural Gas) ─────────────────────────
        elif ac == AssetClass.COMMODITIES:
            macro_drivers = [
                "OPEC+ production quota decisions and compliance",
                "US Strategic Petroleum Reserve (SPR) policy and crude inventories",
                "Global economic growth expectations and refinery utilization",
            ]
            event_sensitivities = [
                "EIA Weekly Petroleum Status Report (Wednesdays 14:30 UTC)",
                "OPEC monthly oil market report (MOMR)",
                "Monthly futures contract expiry rollover dates",
            ]
            if session.is_weekend:
                is_market_open = False
                liquidity = "CLOSED"
                warnings.append("Commodities markets are closed for the weekend.")
            elif session.is_rollover_spread_risk:
                spread_risk = "ELEVATED"
            else:
                optimal_window = session.is_london_ny_overlap or session.is_us_cash_open
                liquidity = "HIGH" if optimal_window else "NORMAL"

        # ── 5. FOREX (Major, Cross, Exotic) ──────────────────────────────────
        else:
            macro_drivers = [
                f"Interest rate differentials between {spec.currency_base} and {spec.currency_profit}",
                "Central bank policy divergence (Fed, ECB, BoE, BoJ, RBA)",
                "Balance of payments, trade balances, and sovereign yield spreads",
            ]
            event_sensitivities = [
                "Central bank rate decisions (FOMC, ECB, BoE, BoJ)",
                "CPI Inflation prints for base and quote currencies",
                "Employment reports (NFP, Labour Force Surveys)",
            ]
            if session.is_weekend:
                is_market_open = False
                liquidity = "CLOSED"
                warnings.append("Forex markets are closed for the weekend.")
            elif session.is_rollover_spread_risk:
                liquidity = "THIN"
                spread_risk = "EXTREME"
                warnings.append("Daily 21:00-23:00 UTC bank rollover: spreads widen significantly. New market orders discouraged.")
            else:
                # Optimal window depends on pair
                if "JPY" in symbol:
                    optimal_window = session.is_asian_session or session.is_london_ny_overlap
                else:
                    optimal_window = session.is_london_ny_overlap or session.is_london_session
                liquidity = "HIGH" if optimal_window else "NORMAL"

        session_desc = " + ".join(session.active_sessions) if session.active_sessions else "Standard Market Hours"

        return MarketConditionsReport(
            symbol=symbol,
            asset_class=ac.value,
            session_status=session_desc,
            is_market_open=is_market_open,
            optimal_execution_window=optimal_window,
            liquidity_condition=liquidity,
            spread_risk=spread_risk,
            macro_drivers=macro_drivers,
            event_sensitivities=event_sensitivities,
            contextual_warnings=warnings,
            session_context=session,
        )
