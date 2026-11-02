"""
config/settings.py
==================
Central configuration module for the AI-Powered XAUUSD Trading System.

Loads environment variables from .env, defines all constants, enums,
and logging configuration used across the system.
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum
from pathlib import Path

try:
    import colorlog
    HAVE_COLORLOG = True
except ImportError:
    HAVE_COLORLOG = False

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# Environment Loading
# ─────────────────────────────────────────────────────────────────────────────

# Walk up from this file to find .env (project root)
_HERE = Path(__file__).resolve().parent  # config/
_ROOT = _HERE.parent                     # trading_system/
_ENV_FILE = _ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    # Fall back to a .env in cwd or any parent
    load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Timeframe Constants
# ─────────────────────────────────────────────────────────────────────────────

MN1  = "MN1"
W1   = "W1"
D1   = "D1"
H4   = "H4"
H1   = "H1"
M30  = "M30"
M15  = "M15"
M5   = "M5"
M1   = "M1"

# Ordered from highest (longest) to lowest (shortest) timeframe
TIMEFRAME_HIERARCHY: list[str] = [MN1, W1, D1, H4, H1, M30, M15, M5, M1]

# Seconds per timeframe bar — used for candle-completion checks
TIMEFRAME_SECONDS: dict[str, int] = {
    MN1: 30 * 24 * 3600,   # approximate (30 days)
    W1:   7 * 24 * 3600,
    D1:       24 * 3600,
    H4:        4 * 3600,
    H1:            3600,
    M30:          30 * 60,
    M15:          15 * 60,
    M5:            5 * 60,
    M1:                60,
}

# MT5 timeframe mapping — populated lazily so import does not hard-fail
# when MetaTrader5 is not installed.
def _build_mt5_timeframe_map() -> dict[str, int]:
    """Return string -> mt5.TIMEFRAME_* mapping, or empty dict if MT5 absent."""
    try:
        import MetaTrader5 as mt5  # type: ignore
        return {
            MN1: mt5.TIMEFRAME_MN1,
            W1:  mt5.TIMEFRAME_W1,
            D1:  mt5.TIMEFRAME_D1,
            H4:  mt5.TIMEFRAME_H4,
            H1:  mt5.TIMEFRAME_H1,
            M30: mt5.TIMEFRAME_M30,
            M15: mt5.TIMEFRAME_M15,
            M5:  mt5.TIMEFRAME_M5,
            M1:  mt5.TIMEFRAME_M1,
        }
    except ImportError:
        return {}


MT5_TIMEFRAME_MAP: dict[str, int] = _build_mt5_timeframe_map()


# ─────────────────────────────────────────────────────────────────────────────
# Symbol & Trading Defaults
# ─────────────────────────────────────────────────────────────────────────────

SYMBOL: str = "XAUUSD"

# Risk management
DEFAULT_RISK_PCT: float = 0.01   # 1 % per trade
MAX_RISK_PCT: float     = 0.02   # hard cap at 2 %

# Technical analysis parameters
ATR_PERIOD:                 int   = 14
SWING_LOOKBACK:             int   = 5
SR_LOOKBACK:                int   = 200
SUPPLY_DEMAND_ATR_MULTIPLIER: float = 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class ZoneState(str, Enum):
    """Lifecycle state of a Supply / Demand zone."""
    FRESH        = "FRESH"        # Never touched after formation
    TESTED       = "TESTED"       # Price entered zone but bounced
    MITIGATED    = "MITIGATED"    # Zone largely consumed by price action
    INVALIDATED  = "INVALIDATED"  # Price closed through zone


class CandleStatus(str, Enum):
    """Whether the most recent candle has closed or is still forming."""
    CONFIRMED = "CONFIRMED"  # Candle has fully closed
    FORMING   = "FORMING"    # Candle is still in progress


class Bias(str, Enum):
    """Directional market bias derived from multi-timeframe analysis."""
    BULLISH  = "BULLISH"
    BEARISH  = "BEARISH"
    NEUTRAL  = "NEUTRAL"


class Signal(str, Enum):
    """Trading signal output from the analysis engine."""
    BUY_OPPORTUNITY          = "BUY_OPPORTUNITY"
    SELL_OPPORTUNITY         = "SELL_OPPORTUNITY"
    WAIT_FOR_CONFIRMATION    = "WAIT_FOR_CONFIRMATION"
    NO_TRADE                 = "NO_TRADE"
    HIGHER_TIMEFRAME_CONFLICT = "HIGHER_TIMEFRAME_CONFLICT"


class DrawdownType(str, Enum):
    """Prop firm drawdown calculation method."""
    STATIC            = "static"
    EOD_TRAILING      = "eod_trailing"
    INTRADAY_TRAILING = "intraday_trailing"


class SetupQuality(str, Enum):
    """Trade setup quality grades."""
    A_PLUS = "A+"
    A      = "A"
    B      = "B"
    C      = "C"
    D      = "D"


class TradeStatus(str, Enum):
    """Trade plan lifecycle status."""
    PENDING   = "PENDING_CONFIRMATION"
    ACTIVE    = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class VolatilityRegime(str, Enum):
    """Market volatility regime."""
    LOW     = "LOW"
    NORMAL  = "NORMAL"
    HIGH    = "HIGH"
    EXTREME = "EXTREME"


# Hierarchy weights for bias synthesis
TIMEFRAME_WEIGHTS: dict[str, float] = {
    MN1: 5.0,
    W1:  4.0,
    D1:  3.0,
    H4:  2.0,
    H1:  1.0,
    M30: 0.5,
    M15: 0.3,
    M5:  0.1,
    M1:  0.05,
}

# Default candle counts per timeframe
DEFAULT_CANDLE_COUNTS: dict[str, int] = {
    MN1: 60,
    W1:  104,
    D1:  365,
    H4:  500,
    H1:  500,
    M30: 500,
    M15: 400,
    M5:  300,
    M1:  300,
}

# Additional parameters
MIN_RR_TP1: float          = 1.5
MIN_RR_TP2: float          = 2.0
MAX_DAILY_RISK_PCT: float  = 0.04
SD_MAX_BASE_CANDLES: int   = 4
SD_ATR_MULTIPLIER: float   = 1.5

YFINANCE_SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "GC=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
}

# Directories
BASE_DIR: Path = _ROOT
LOG_DIR: Path = _ROOT / "logs"
PROP_FIRMS_DIR: Path = _HERE / "prop_firms"
PROP_FIRMS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Environment / Infrastructure Settings
# ─────────────────────────────────────────────────────────────────────────────

# API keys
GEMINI_API_KEY:       str | None = os.getenv("GEMINI_API_KEY")
ALPHA_VANTAGE_API_KEY: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")

# MT5 connection
MT5_LOGIN:    int | None = int(os.getenv("MT5_LOGIN")) if os.getenv("MT5_LOGIN") else None
MT5_PASSWORD: str | None = os.getenv("MT5_PASSWORD")
MT5_SERVER:   str | None = os.getenv("MT5_SERVER")

def _detect_mt5_path() -> str:
    env_path = os.getenv("MT5_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    candidates = [
        r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe",
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\IC Markets Global MT5\terminal64.exe",
        r"C:\Program Files\FTMO MetaTrader 5\terminal64.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return env_path or r"C:\Program Files\MetaTrader 5\terminal64.exe"

MT5_PATH: str = _detect_mt5_path()

# Dashboard
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8050"))
DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")

# Storage
DATA_CACHE_DIR: Path = Path(os.getenv("DATA_CACHE_DIR", "./data_cache"))
JOURNAL_DB_PATH: Path = Path(os.getenv("JOURNAL_DB_PATH", "./journal/trades.db"))

# Log level
_LOG_LEVEL_STR: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL: int = getattr(logging, _LOG_LEVEL_STR, logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────────────────────

def configure_logging(
    level: int = LOG_LEVEL,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """
    Configure the root logger with coloured console output and an optional
    rotating file handler.

    Parameters
    ----------
    level:
        Logging level (e.g. ``logging.INFO``).
    log_file:
        If provided, also write logs to this file path.

    Returns
    -------
    logging.Logger
        The configured root logger.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove pre-existing handlers to avoid duplicate output on re-configuration
    root_logger.handlers.clear()

    # ── Console handler ───────────────────────────────────────────────────────
    if HAVE_COLORLOG:
        console_formatter = colorlog.ColoredFormatter(
            fmt=(
                "%(log_color)s%(asctime)s [%(levelname)-8s]%(reset)s "
                "%(cyan)s%(name)-25s%(reset)s %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG":    "white",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            },
            secondary_log_colors={},
            style="%",
        )
    else:
        console_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)-25s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # ── Optional file handler ─────────────────────────────────────────────────
    if log_file is not None:
        from logging.handlers import RotatingFileHandler

        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)-25s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Quieten noisy third-party loggers
    for noisy in ("urllib3", "requests", "websocket", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root_logger


# Auto-configure logging when this module is first imported
configure_logging()
