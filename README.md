# Universal Multi-Asset AI Trading Intelligence Platform

A professional **broker-independent, AI-powered manual trading analysis platform** capable of analyzing virtually any tradable financial instrument through MetaTrader 5 (Forex, Precious Metals, Stock Indices, Commodities, and Cryptocurrencies).

> ⚠️ **STRICT SAFETY RESTRICTION — THIS IS NOT AN AUTOMATED TRADING BOT:**
> The system operates in **strictly read-only mode** with MetaTrader 5. It performs top-down technical analysis, detects institutional supply/demand zones, evaluates market structure, calculates mathematically justified risk and position sizes, and monitors portfolio exposure. **All trade executions and orders must be manually placed by the human trader.**

---

## Universal System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   UNIVERSAL DASH WEB DASHBOARD (localhost:8050)                        │
│   Dynamic Instrument Selector (Forex, Metals, Indices, Crypto) │ Prop Firm Selector    │
│   MTF Candlestick Chart │ S/R & S&D Overlays │ Currency Exposure │ Risk KPI Gauges     │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                       UNIVERSAL PYTHON INTELLIGENCE ENGINE                             │
│                                                                                        │
│  ┌───────────────────────┐  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │ Instrument Discovery  │  │  Universal Multi-TF TA  │  │ Dynamic Specification    │  │
│  │ & Broker Normalization│→ │  (MN1 down to M15)      │→ │ & Currency Conversion    │  │
│  └───────────────────────┘  └─────────────────────────┘  └──────────────────────────┘  │
│                                                                                        │
│  ┌───────────────────────┐  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │ Session Context &     │  │  Multi-Asset Portfolio  │  │ Prop Firm Compliance     │  │
│  │ Macro Sensitivity     │→ │  Risk & Correlation     │→ │ (FTMO, The5ers, etc.)    │  │
│  └───────────────────────┘  └─────────────────────────┘  └──────────────────────────┘  │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Read-Only Telemetry
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│               MetaTrader 5 Connected Broker Terminal (Exness / FTMO / IC)               │
│               UniversalAnalystBridge.mq5 / GoldAnalystBridge.mq5                        │
│       Real-time OHLCV │ Tick Data │ Account Equity │ Open Positions Telemetry          │
│               STRICTLY READ ONLY — ZERO ORDER EXECUTION FUNCTIONS                      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Supported Asset Classes

| Asset Class | Representative Instruments | Key Characteristics Handled Dynamically |
|:---|:---|:---|
| **Forex Majors & Crosses** | EURUSD, GBPUSD, USDJPY, GBPJPY, AUDUSD, USDCAD | Session overlaps (London/NY), pip value scaling, currency conversion for non-USD profit |
| **Precious Metals** | XAUUSD (Gold), XAGUSD (Silver) | 100oz/5000oz contract specifications, USD yield sensitivity, rollover spread expansion |
| **Stock Indices** | USTEC (NASDAQ), US30 (Dow Jones), US500 (S&P 500), GER40 (DAX) | Cash opening auction volatility (09:30 EST), index contract point values |
| **Commodities & Energies** | USOIL (WTI Crude), UKOIL (Brent Crude) | EIA inventory event sensitivity, contract rollover dates |
| **Cryptocurrencies** | BTCUSD (Bitcoin), ETHUSD (Ethereum) | 24/7 continuous trading, weekend liquidity contractions, crypto contract sizes |

---

## Quick Start Guide

### 1. Requirements & Installation
```bash
# Clone or navigate to the repository
cd "d:/Tradinig system/trading_system"

# Install Python requirements
pip install -r requirements.txt
```

### 2. Live MT5 Integration (Windows)
The system **automatically connects to any active running MetaTrader 5 terminal** on Windows.
- Simply open your MetaTrader 5 terminal and log into your demo or live account.
- The Python engine attaches automatically via `MetaTrader5.initialize()`.

### 3. Optional Companion MQL5 Bridge
- Copy `mql5/UniversalAnalystBridge.mq5` to your MT5 `MQL5/Experts/` folder.
- Compile in MetaEditor.
- Attach to any chart. The HUD displays real-time telemetry and verifies **Read-Only Mode**.

### 4. Running the Dashboard
```bash
# Launch the universal web dashboard
python main.py

# Or launch directly analyzing a specific instrument:
python main.py --symbol EURUSD
python main.py --symbol USTEC
python main.py --symbol BTCUSD
python main.py --symbol XAUUSD

# Or run a one-shot institutional report:
python main.py --analyze-only --symbol USTEC
```
Dashboard URL: **http://localhost:8050**

---

## Proprietary Trading Firm Environments

The platform includes verified rule configurations for MT5 CFD prop firms and strictly isolates them from CME Futures firms:

| Firm Profile | Config File | Platform | Drawdown Model | Daily Limit | Max Loss | Status |
|:---|:---|:---|:---|:---|:---|:---|
| **FTMO (2-Step)** | `ftmo_2step.yaml` | MetaTrader 5 | Static | 5.0% | 10.0% | Supported MT5 CFD |
| **FundedNext (Stellar)**| `fundednext_stellar.yaml`| MetaTrader 5 | Static | 5.0% | 10.0% | Supported MT5 CFD |
| **The5ers (High Stakes)**| `the5ers_highstakes.yaml`| MetaTrader 5 | Static | 5.0% | 10.0% | Supported MT5 CFD |
| **Alpha Capital Group** | `alphacapital.yaml` | MetaTrader 5 | Trailing-to-Initial| 5.0% | 10.0% | Supported MT5 CFD |
| **Topstep (Combine)** | `topstep.yaml` | CME Futures | EOD Trailing | 2.0% | 4.0% | ⚠️ CME Futures Only |
| **Apex Trader Funding** | `apex.yaml` | CME Futures | Intraday Trailing | None | 6.0% | ⚠️ CME Futures Only |

---

## Quantitative Risk & Mathematical Verification

All formulas are tested via an independent verification test suite:
- **Universal Position Sizing:**
  $$\text{Lots} = \frac{\text{Account Equity} \times \text{Risk \%}}{\frac{|\text{Entry} - \text{SL}|}{\text{Tick Size}} \times \text{Tick Value In Account Currency}}$$
- **Correlation-Adjusted Portfolio Risk:**
  $$\sigma_{\text{portfolio}} = \sqrt{\mathbf{R}^T \mathbf{P} \mathbf{R}}$$
- **Kelly Criterion & Expected Value:** Bounded quarter-Kelly with negative-expectancy rejection.

Run the test suite:
```bash
python -m pytest tests/ -v
```
