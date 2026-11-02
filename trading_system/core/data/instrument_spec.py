"""
core/data/instrument_spec.py
============================
Universal Dynamic Instrument Specification & Discovery Engine.

Dynamically discovers, classifies, normalizes, and manages specifications
for any tradable instrument available via MetaTrader 5 (Forex, Metals,
Indices, Commodities, Crypto, Equities, etc.).
Eliminates hardcoded symbol assumptions across the entire system.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AssetClass(str, Enum):
    """Broad asset class categorization for financial instruments."""
    FOREX_MAJOR = "FOREX_MAJOR"
    FOREX_CROSS = "FOREX_CROSS"
    FOREX_EXOTIC = "FOREX_EXOTIC"
    METALS = "METALS"
    INDICES = "INDICES"
    COMMODITIES = "COMMODITIES"
    CRYPTO = "CRYPTO"
    EQUITIES = "EQUITIES"
    UNKNOWN = "UNKNOWN"


# Known canonical aliases and mappings across brokers
CANONICAL_ALIASES: Dict[str, List[str]] = {
    "XAUUSD": ["XAUUSD", "GOLD", "XAUUSDm", "XAUUSD.a", "XAUUSD.raw", "XAUUSD247"],
    "XAGUSD": ["XAGUSD", "SILVER", "XAGUSDm", "XAGUSD.a"],
    "EURUSD": ["EURUSD", "EURUSDm", "EURUSD.a", "EURUSD.raw", "EURUSD_i"],
    "GBPUSD": ["GBPUSD", "GBPUSDm", "GBPUSD.a", "GBPUSD.raw", "GBPUSD_i"],
    "USDJPY": ["USDJPY", "USDJPYm", "USDJPY.a", "USDJPY.raw", "USDJPY_i"],
    "GBPJPY": ["GBPJPY", "GBPJPYm", "GBPJPY.a"],
    "AUDUSD": ["AUDUSD", "AUDUSDm", "AUDUSD.a"],
    "USDCAD": ["USDCAD", "USDCADm", "USDCAD.a"],
    "USDCHF": ["USDCHF", "USDCHFm", "USDCHF.a"],
    "NZDUSD": ["NZDUSD", "NZDUSDm", "NZDUSD.a"],
    "USTEC":  ["USTEC", "US100", "NAS100", "NDX", "USTEC_x100", "US100.cash", "NAS100.cash"],
    "US30":   ["US30", "DJ30", "WS30", "US30_x10", "US30.cash", "DJ30.cash"],
    "US500":  ["US500", "SPX500", "SP500", "US500_x100", "US500.cash"],
    "GER40":  ["GER40", "DAX40", "GER30", "DAX30", "DE40", "GER40.cash"],
    "UK100":  ["UK100", "FTSE100", "UK100.cash"],
    "USOIL":  ["USOIL", "WTI", "CRUDE", "CL", "USOIL.cash"],
    "UKOIL":  ["UKOIL", "BRENT", "UKOIL.cash"],
    "BTCUSD": ["BTCUSD", "BTCUSDm", "BTCUSDT", "BTCUSD.a"],
    "ETHUSD": ["ETHUSD", "ETHUSDm", "ETHUSDT", "ETHUSD.a"],
}

# Standard offline fallback specifications
OFFLINE_SPECS_CATALOG: Dict[str, Dict[str, Any]] = {
    "XAUUSD": {
        "symbol": "XAUUSD",
        "description": "Gold vs US Dollar (Spot)",
        "asset_class": AssetClass.METALS.value,
        "digits": 2,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 1.0,         # $1.00 per 0.01 tick on 100oz contract
        "contract_size": 100.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "currency_base": "XAU",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 25,
    },
    "XAGUSD": {
        "symbol": "XAGUSD",
        "description": "Silver vs US Dollar (Spot)",
        "asset_class": AssetClass.METALS.value,
        "digits": 3,
        "point": 0.001,
        "tick_size": 0.001,
        "tick_value": 5.0,         # $5.00 per 0.001 tick on 5000oz contract
        "contract_size": 5000.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "currency_base": "XAG",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 30,
    },
    "EURUSD": {
        "symbol": "EURUSD",
        "description": "Euro vs US Dollar",
        "asset_class": AssetClass.FOREX_MAJOR.value,
        "digits": 5,
        "point": 0.00001,
        "tick_size": 0.00001,
        "tick_value": 1.0,         # $1.00 per 0.00001 tick on 100,000 contract
        "contract_size": 100000.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "currency_base": "EUR",
        "currency_profit": "USD",
        "currency_margin": "EUR",
        "spread": 12,
    },
    "GBPUSD": {
        "symbol": "GBPUSD",
        "description": "British Pound vs US Dollar",
        "asset_class": AssetClass.FOREX_MAJOR.value,
        "digits": 5,
        "point": 0.00001,
        "tick_size": 0.00001,
        "tick_value": 1.0,
        "contract_size": 100000.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "currency_base": "GBP",
        "currency_profit": "USD",
        "currency_margin": "GBP",
        "spread": 15,
    },
    "USDJPY": {
        "symbol": "USDJPY",
        "description": "US Dollar vs Japanese Yen",
        "asset_class": AssetClass.FOREX_MAJOR.value,
        "digits": 3,
        "point": 0.001,
        "tick_size": 0.001,
        "tick_value": 0.65,        # converted from 100 JPY to USD (~$0.65)
        "contract_size": 100000.0,
        "volume_min": 0.01,
        "volume_max": 200.0,
        "volume_step": 0.01,
        "currency_base": "USD",
        "currency_profit": "JPY",
        "currency_margin": "USD",
        "spread": 14,
    },
    "USTEC": {
        "symbol": "USTEC",
        "description": "US Tech 100 / NASDAQ Index",
        "asset_class": AssetClass.INDICES.value,
        "digits": 2,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,        # $0.01 per 0.01 point per 1.0 index contract
        "contract_size": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 150,
    },
    "US30": {
        "symbol": "US30",
        "description": "Wall Street 30 / Dow Jones Index",
        "asset_class": AssetClass.INDICES.value,
        "digits": 1,
        "point": 0.1,
        "tick_size": 0.1,
        "tick_value": 0.1,         # $0.10 per 0.1 point per 1.0 index contract
        "contract_size": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 250,
    },
    "US500": {
        "symbol": "US500",
        "description": "US S&P 500 Index",
        "asset_class": AssetClass.INDICES.value,
        "digits": 2,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "contract_size": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 50,
    },
    "USOIL": {
        "symbol": "USOIL",
        "description": "Crude Oil (WTI)",
        "asset_class": AssetClass.COMMODITIES.value,
        "digits": 3,
        "point": 0.001,
        "tick_size": 0.001,
        "tick_value": 1.0,         # $1.00 per 0.001 tick on 1000 barrel contract
        "contract_size": 1000.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
        "spread": 35,
    },
    "BTCUSD": {
        "symbol": "BTCUSD",
        "description": "Bitcoin vs US Dollar",
        "asset_class": AssetClass.CRYPTO.value,
        "digits": 2,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,        # $0.01 per 0.01 tick on 1.0 BTC contract
        "contract_size": 1.0,
        "volume_min": 0.01,
        "volume_max": 20.0,
        "volume_step": 0.01,
        "currency_base": "BTC",
        "currency_profit": "USD",
        "currency_margin": "BTC",
        "spread": 2500,
    },
}


@dataclass
class InstrumentSpec:
    """
    Complete dynamic specification for a single tradable instrument.
    Enforces exact precision, volume boundaries, and conversion metrics.
    """
    symbol: str
    broker_symbol: str
    asset_class: AssetClass
    digits: int
    point: float
    tick_size: float
    tick_value: float          # In account currency per 1.0 standard lot
    contract_size: float
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    currency_base: str = "USD"
    currency_profit: str = "USD"
    currency_margin: str = "USD"
    trade_calc_mode: int = 0
    spread: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    description: str = ""
    session_active: bool = True
    extra_meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def pip_size(self) -> float:
        """Standard pip size for the instrument."""
        if self.asset_class in (AssetClass.FOREX_MAJOR, AssetClass.FOREX_CROSS, AssetClass.FOREX_EXOTIC):
            if self.digits in (3, 5):
                return self.point * 10.0
            return self.point
        # Metals, indices, crypto: 1 pip = 1.0 full point / price unit
        if self.asset_class == AssetClass.METALS:
            return 0.10 if "XAU" in self.symbol else 0.01
        if self.asset_class in (AssetClass.INDICES, AssetClass.COMMODITIES):
            return 1.0 if self.digits <= 2 else self.point * 10.0
        if self.asset_class == AssetClass.CRYPTO:
            return 1.0
        return self.point

    def price_to_points(self, price_diff: float) -> int:
        """Convert a floating price difference to integer broker points."""
        if self.point <= 0:
            return int(round(abs(price_diff) * 100))
        return int(round(abs(price_diff) / self.point))

    def points_to_price(self, points: int | float) -> float:
        """Convert broker points to floating price value."""
        return round(float(points) * self.point, self.digits)

    def calculate_tick_value_in_account(
        self,
        account_currency: str = "USD",
        exchange_rates: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Ensure tick value is expressed in account currency.
        If MT5 provided tick_value, it is typically already in account currency.
        If offline, convert from currency_profit to account_currency.
        """
        if self.tick_value > 0 and self.currency_profit.upper() == account_currency.upper():
            return self.tick_value

        if self.tick_value <= 0:
            # Theoretical fallback: contract_size * tick_size
            raw_tick_val = self.contract_size * self.tick_size
        else:
            raw_tick_val = self.tick_value

        profit_curr = self.currency_profit.upper()
        acct_curr = account_currency.upper()

        if profit_curr == acct_curr:
            return raw_tick_val

        # Conversion logic
        rates = exchange_rates or {}
        pair_direct = f"{profit_curr}{acct_curr}"
        pair_inverse = f"{acct_curr}{profit_curr}"

        if pair_direct in rates and rates[pair_direct] > 0:
            return raw_tick_val * rates[pair_direct]
        elif pair_inverse in rates and rates[pair_inverse] > 0:
            return raw_tick_val / rates[pair_inverse]

        # Standard approximations for common currencies vs USD
        if acct_curr == "USD":
            if profit_curr == "JPY":
                return raw_tick_val / 155.0
            elif profit_curr == "EUR":
                return raw_tick_val * 1.08
            elif profit_curr == "GBP":
                return raw_tick_val * 1.28
            elif profit_curr == "AUD":
                return raw_tick_val * 0.65
            elif profit_curr == "CAD":
                return raw_tick_val / 1.38
            elif profit_curr == "CHF":
                return raw_tick_val / 0.88

        logger.debug(
            "Could not precisely convert tick value from %s to %s for %s. Using raw value.",
            profit_curr, acct_curr, self.symbol
        )
        return raw_tick_val


class InstrumentDiscovery:
    """
    Discovers, classifies, and loads specifications from connected MT5 terminal
    or falls back cleanly to the multi-asset catalog.
    """

    @staticmethod
    def classify_asset(symbol_name: str, path: str = "") -> AssetClass:
        """Classify symbol into an AssetClass enum based on name and broker group path."""
        s = symbol_name.upper()
        p = path.upper()

        # Check path first if broker grouped them cleanly
        if "FOREX" in p or "FX" in p:
            if any(major in s for major in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]):
                return AssetClass.FOREX_MAJOR
            return AssetClass.FOREX_CROSS
        if "CRYPTO" in p:
            return AssetClass.CRYPTO
        if "METAL" in p:
            return AssetClass.METALS
        if "IND" in p or "IDX" in p:
            return AssetClass.INDICES
        if "COMMOD" in p or "ENERG" in p or "OIL" in p:
            return AssetClass.COMMODITIES
        if "STOCK" in p or "EQUITY" in p or "SHARE" in p:
            return AssetClass.EQUITIES

        # Fallback to symbol name heuristics
        if any(m in s for m in ["XAU", "GOLD", "XAG", "SILVER", "PLAT", "XPT", "XPD"]):
            return AssetClass.METALS
        if any(c in s for c in ["BTC", "ETH", "SOL", "XRP", "LTC", "DOGE", "BNB"]):
            return AssetClass.CRYPTO
        if any(idx in s for idx in ["USTEC", "US100", "NAS", "US30", "DJ30", "US500", "SPX", "GER40", "DAX", "UK100", "JP225", "HK50"]):
            return AssetClass.INDICES
        if any(cmd in s for cmd in ["OIL", "BRENT", "WTI", "GAS", "NGAS", "COPPER"]):
            return AssetClass.COMMODITIES
        if any(major in s for major in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]):
            return AssetClass.FOREX_MAJOR
        if len(s) >= 6 and any(curr in s for curr in ["EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]):
            return AssetClass.FOREX_CROSS

        return AssetClass.UNKNOWN

    @classmethod
    def resolve_broker_symbol(cls, target_symbol: str, available_symbols: List[str]) -> str:
        """
        Match a target symbol (e.g. 'US100', 'XAUUSD', 'EURUSD') to the broker's
        actual symbol name, taking into account suffixes and aliases.
        """
        target = target_symbol.upper().strip()

        # Direct exact match
        if target in available_symbols:
            return target

        # Check aliases
        aliases = CANONICAL_ALIASES.get(target, [target])
        for alias in aliases:
            if alias in available_symbols:
                return alias

        # Case-insensitive / prefix / suffix match
        for avail in available_symbols:
            avail_upper = avail.upper()
            if avail_upper == target:
                return avail
            # Check if any alias is contained inside the symbol
            for alias in aliases:
                if alias.upper() in avail_upper:
                    return avail

        # If not found, return target as best-effort
        return target_symbol

    @classmethod
    def from_mt5_symbol_info(cls, symbol_name: str, info: Any) -> InstrumentSpec:
        """Build InstrumentSpec from MT5 symbol_info object or dict."""
        if hasattr(info, "_asdict"):
            data = info._asdict()
        elif isinstance(info, dict):
            data = info
        else:
            data = {attr: getattr(info, attr, None) for attr in dir(info) if not attr.startswith("_")}

        path = str(data.get("path", ""))
        asset_class = cls.classify_asset(symbol_name, path)

        digits = int(data.get("digits", 2))
        point = float(data.get("point", 0.01))
        tick_size = float(data.get("trade_tick_size", data.get("tick_size", point)))
        if tick_size <= 0:
            tick_size = point

        tick_value = float(data.get("trade_tick_value", data.get("tick_value", 1.0)))
        contract_size = float(data.get("trade_contract_size", data.get("contract_size", 100.0)))
        if contract_size <= 0:
            contract_size = 1.0

        volume_min = float(data.get("volume_min", 0.01))
        volume_max = float(data.get("volume_max", 100.0))
        volume_step = float(data.get("volume_step", 0.01))

        currency_base = str(data.get("currency_base", "USD"))
        currency_profit = str(data.get("currency_profit", "USD"))
        currency_margin = str(data.get("currency_margin", "USD"))
        calc_mode = int(data.get("trade_calc_mode", 0))

        bid = float(data.get("bid", 0.0))
        ask = float(data.get("ask", 0.0))
        spread = float(data.get("spread", 0.0))
        desc = str(data.get("description", symbol_name))

        return InstrumentSpec(
            symbol=symbol_name,
            broker_symbol=symbol_name,
            asset_class=asset_class,
            digits=digits,
            point=point,
            tick_size=tick_size,
            tick_value=tick_value,
            contract_size=contract_size,
            volume_min=volume_min,
            volume_max=volume_max,
            volume_step=volume_step,
            currency_base=currency_base,
            currency_profit=currency_profit,
            currency_margin=currency_margin,
            trade_calc_mode=calc_mode,
            spread=spread,
            bid=bid,
            ask=ask,
            description=desc,
            session_active=True,
            extra_meta={"path": path},
        )

    @classmethod
    def get_fallback_spec(cls, symbol: str) -> InstrumentSpec:
        """Retrieve standard fallback specification from catalog."""
        sym_clean = symbol.upper().replace(".M", "").replace(".A", "").replace(".RAW", "")
        # Check direct or aliases
        spec_dict = None
        if sym_clean in OFFLINE_SPECS_CATALOG:
            spec_dict = OFFLINE_SPECS_CATALOG[sym_clean]
        else:
            for canon, aliases in CANONICAL_ALIASES.items():
                if sym_clean in [a.upper() for a in aliases]:
                    spec_dict = OFFLINE_SPECS_CATALOG.get(canon)
                    break

        if not spec_dict:
            spec_dict = OFFLINE_SPECS_CATALOG["XAUUSD"]

        ac_str = spec_dict.get("asset_class", AssetClass.METALS.value)
        asset_class = AssetClass(ac_str) if ac_str in AssetClass.__members__.values() else AssetClass.UNKNOWN

        return InstrumentSpec(
            symbol=symbol,
            broker_symbol=symbol,
            asset_class=asset_class,
            digits=spec_dict["digits"],
            point=spec_dict["point"],
            tick_size=spec_dict["tick_size"],
            tick_value=spec_dict["tick_value"],
            contract_size=spec_dict["contract_size"],
            volume_min=spec_dict.get("volume_min", 0.01),
            volume_max=spec_dict.get("volume_max", 100.0),
            volume_step=spec_dict.get("volume_step", 0.01),
            currency_base=spec_dict.get("currency_base", "USD"),
            currency_profit=spec_dict.get("currency_profit", "USD"),
            currency_margin=spec_dict.get("currency_margin", "USD"),
            spread=spec_dict.get("spread", 20.0),
            description=spec_dict.get("description", symbol),
        )

    @classmethod
    def discover_available_instruments(cls, mt5_connector: Optional[Any] = None) -> List[Dict[str, str]]:
        """
        Dynamically discover tradable symbols from connected MT5 broker.
        Returns formatted dropdown options categorized by asset class.
        Falls back to comprehensive catalog when offline.
        """
        discovered: List[Dict[str, str]] = []
        try:
            import MetaTrader5 as mt5_mod
            symbols_raw = mt5_mod.symbols_get()
            if symbols_raw and len(symbols_raw) > 0:
                # Group symbols by class
                seen = set()
                # Prioritize majors, metals, indices, crypto
                for s in symbols_raw:
                    name = s.name
                    if name in seen:
                        continue
                    path = getattr(s, "path", "")
                    ac = cls.classify_asset(name, path)
                    
                    # Filter out custom junk or inactive symbols
                    if not getattr(s, "visible", True) and not getattr(s, "select", False):
                        # Still allow well-known instruments
                        if not any(k in name.upper() for k in ["XAU", "EURUSD", "GBPUSD", "USDJPY", "US100", "USTEC", "US30", "BTC"]):
                            continue

                    icon = "📊"
                    if ac == AssetClass.METALS:
                        icon = "🥇" if "XAU" in name.upper() or "GOLD" in name.upper() else "🥈"
                    elif ac in (AssetClass.FOREX_MAJOR, AssetClass.FOREX_CROSS):
                        icon = "💱"
                    elif ac == AssetClass.INDICES:
                        icon = "📈"
                    elif ac == AssetClass.COMMODITIES:
                        icon = "🛢"
                    elif ac == AssetClass.CRYPTO:
                        icon = "₿"

                    desc = getattr(s, "description", name)
                    label = f"{icon} {name} ({desc})"
                    discovered.append({"label": label, "value": name})
                    seen.add(name)

                if discovered:
                    return discovered
        except Exception:
            pass

        # Fallback curated list
        return [
            {"label": "🥇 Metals: XAUUSD (Gold)", "value": "XAUUSD"},
            {"label": "🥈 Metals: XAGUSD (Silver)", "value": "XAGUSD"},
            {"label": "💶 Forex: EURUSD (Euro / USD)", "value": "EURUSD"},
            {"label": "💷 Forex: GBPUSD (Pound / USD)", "value": "GBPUSD"},
            {"label": "💴 Forex: USDJPY (USD / Yen)", "value": "USDJPY"},
            {"label": "🇦🇺 Forex: AUDUSD (Aussie / USD)", "value": "AUDUSD"},
            {"label": "📈 Index: USTEC / US100 (Nasdaq)", "value": "USTEC"},
            {"label": "🏛 Index: US30 (Dow Jones)", "value": "US30"},
            {"label": "📊 Index: US500 (S&P 500)", "value": "US500"},
            {"label": "🛢 Commod: USOIL (WTI Crude)", "value": "USOIL"},
            {"label": "₿ Crypto: BTCUSD (Bitcoin)", "value": "BTCUSD"},
            {"label": "Ξ Crypto: ETHUSD (Ethereum)", "value": "ETHUSD"},
        ]

