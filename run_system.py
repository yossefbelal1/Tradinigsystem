"""
run_system.py
=============
One-Click Master Launcher for Universal AI Trading Intelligence Platform.
- Automatically connects to live MetaTrader 5 terminal.
- Starts the Bidirectional MT5 Active Chart Bridge Server.
- Automatically opens your web browser to http://127.0.0.1:8050.
- Serves the institutional multi-asset trading dashboard.
"""

import logging
import os
import sys
import threading
import time
import webbrowser

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from trading_system.core.data.mt5_connector import MT5Connector
from trading_system.dashboard.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Launcher")


def open_browser_delayed():
    """Wait for server to bind then launch browser automatically."""
    time.sleep(2.5)
    url = "http://127.0.0.1:8050"
    logger.info("Opening dashboard automatically in default browser: %s", url)
    webbrowser.open(url)


def main():
    print("=" * 72)
    print("   UNIVERSAL AI TRADING INTELLIGENCE PLATFORM - ONE-CLICK LAUNCHER")
    print("   Strictly Read-Only Analysis & Telemetry | 100% Manual Trader Control")
    print("=" * 72)

    # 1. Initialize MT5 Connector
    logger.info("Checking connection to MetaTrader 5 terminal...")
    mt5_conn = MT5Connector()
    connected = mt5_conn.connect()

    if connected:
        acct = mt5_conn.get_account_info()
        logger.info(
            "SUCCESS: Connected to MT5 | Account: %s | Server: %s | Balance: $%.2f USD",
            acct.get("login", "N/A"),
            acct.get("server", "N/A"),
            acct.get("balance", 0.0),
        )
    else:
        logger.warning(
            "MT5 terminal could not be attached automatically. "
            "Please ensure MetaTrader 5 is running. Running with fallback data."
        )

    # 2. Launch browser in background thread
    threading.Thread(target=open_browser_delayed, daemon=True).start()

    # 3. Create & run Dash application and Bridge server
    logger.info("Starting Dash Web Interface and MT5 Active Chart Bridge...")
    app_wrapper = create_app(mt5_connector=mt5_conn, prop_firm="ftmo_2step")

    print("\n" + "=" * 72)
    print("  🚀 DASHBOARD ACTIVE: http://127.0.0.1:8050")
    print("  📡 MT5 CHART BRIDGE: Listening on Common folder for EA events")
    print("  👉 Press Ctrl+C in this terminal window to stop the system anytime.")
    print("=" * 72 + "\n")

    app_wrapper.run(host="127.0.0.1", port=8050, debug=False)


if __name__ == "__main__":
    main()
