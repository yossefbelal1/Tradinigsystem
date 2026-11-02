//+------------------------------------------------------------------+
//|                                           GoldAnalystBridge.mq5  |
//|                    Copyright 2026, Trading Intelligence Systems  |
//|                                       https://www.tradingai.com  |
//+------------------------------------------------------------------+
#property copyright   "Trading Intelligence Systems"
#property link        "https://www.tradingai.com"
#property version     "1.00"
#property description "READ-ONLY MT5 Companion Bridge for Universal Multi-Asset Analysis System."
#property description "THIS EXPERT ADVISOR DOES NOT TRADE. Pure Data Telemetry Only."

// STRICT SAFETY DIRECTIVE:
// This EA is compiled without any trade permissions or execution functions.
// Any execution function call will cause a compiler failure.
#define STRICT_READ_ONLY_MODE 1

//+------------------------------------------------------------------+
//| Input Parameters                                                 |
//+------------------------------------------------------------------+
input group "=== TELEMETRY SETTINGS ==="
input int      InpTimerIntervalSec = 15;        // Status broadcast interval (seconds)
input bool     InpVerboseLogging   = true;      // Enable detailed terminal logs

//+------------------------------------------------------------------+
//| Global Variables                                                 |
//+------------------------------------------------------------------+
datetime g_last_bar_m15 = 0;
datetime g_last_bar_m30 = 0;
datetime g_last_bar_h1  = 0;
datetime g_last_bar_h4  = 0;
datetime g_last_bar_d1  = 0;
datetime g_last_bar_w1  = 0;
datetime g_last_bar_mn1 = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("==================================================================");
   PrintFormat(" [UNIVERSAL ANALYST BRIDGE] Initializing Read-Only Bridge on %s", _Symbol);
   Print(" [SAFETY NOTICE] Automated trade execution is strictly disabled. ");
   Print("==================================================================");

   // Print complete broker symbol specifications for verification
   PrintSymbolSpecifications();

   // Print account initial telemetry
   PrintAccountTelemetry();

   // Start regular timer for account updates
   EventSetTimer(InpTimerIntervalSec);

   // Set HUD comment on chart
   UpdateChartHUD();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
   Print("[XAUUSD ANALYST BRIDGE] Deinitialized. Reason code: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Check bar confirmations across all monitored timeframes
   CheckNewBar(PERIOD_M15, g_last_bar_m15, "M15");
   CheckNewBar(PERIOD_M30, g_last_bar_m30, "M30");
   CheckNewBar(PERIOD_H1,  g_last_bar_h1,  "H1");
   CheckNewBar(PERIOD_H4,  g_last_bar_h4,  "H4");
   CheckNewBar(PERIOD_D1,  g_last_bar_d1,  "D1");
   CheckNewBar(PERIOD_W1,  g_last_bar_w1,  "W1");
   CheckNewBar(PERIOD_MN1, g_last_bar_mn1, "MN1");
}

//+------------------------------------------------------------------+
//| Timer function (Runs every InpTimerIntervalSec)                  |
//+------------------------------------------------------------------+
void OnTimer()
{
   UpdateChartHUD();
   PrintAccountTelemetry();
   PrintOpenPositionsTelemetry();
}

//+------------------------------------------------------------------+
//| Inspect & Broadcast Broker Symbol Specifications                 |
//+------------------------------------------------------------------+
void PrintSymbolSpecifications()
{
   string sym = _Symbol;
   double point      = SymbolInfoDouble(sym, SYMBOL_POINT);
   int    digits     = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double tick_size  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double contract_sz= SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   double vol_min    = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vol_max    = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double vol_step   = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   string base_curr  = SymbolInfoString(sym, SYMBOL_CURRENCY_BASE);
   string profit_curr= SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT);
   string margin_curr= SymbolInfoString(sym, SYMBOL_CURRENCY_MARGIN);

   PrintFormat("[SPECS|%s] Digits: %d | Point: %.5f | TickSize: %.5f | TickVal: %.2f | ContractSize: %.1f",
               sym, digits, point, tick_size, tick_value, contract_sz);
   PrintFormat("[SPECS|%s] VolMin: %.2f | VolMax: %.2f | VolStep: %.2f | ProfitCurr: %s | MarginCurr: %s",
               sym, vol_min, vol_max, vol_step, profit_curr, margin_curr);
}

//+------------------------------------------------------------------+
//| Broadcast Account Financial State                                |
//+------------------------------------------------------------------+
void PrintAccountTelemetry()
{
   double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
   double margin      = AccountInfoDouble(ACCOUNT_MARGIN);
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double profit      = AccountInfoDouble(ACCOUNT_PROFIT);
   string currency    = AccountInfoString(ACCOUNT_CURRENCY);

   PrintFormat("[ACCOUNT|TELEMETRY] Balance: %.2f %s | Equity: %.2f | Margin: %.2f | FreeMargin: %.2f | PnL: %.2f",
               balance, currency, equity, margin, free_margin, profit);
}

//+------------------------------------------------------------------+
//| Broadcast Open Positions Telemetry                               |
//+------------------------------------------------------------------+
void PrintOpenPositionsTelemetry()
{
   int total = PositionsTotal();
   if(total == 0) return;

   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         string sym       = PositionGetString(POSITION_SYMBOL);
         double vol       = PositionGetDouble(POSITION_VOLUME);
         double price_open= PositionGetDouble(POSITION_PRICE_OPEN);
         double sl        = PositionGetDouble(POSITION_SL);
         double tp        = PositionGetDouble(POSITION_TP);
         double profit    = PositionGetDouble(POSITION_PROFIT);
         ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         string type_str  = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";

         PrintFormat("[POSITION|#%I64u] %s %s %.2f @ %.2f | SL: %.2f | TP: %.2f | Floating PnL: %.2f",
                     ticket, sym, type_str, vol, price_open, sl, tp, profit);
      }
   }
}

//+------------------------------------------------------------------+
//| Check if a new candle confirmed closed                           |
//+------------------------------------------------------------------+
void CheckNewBar(ENUM_TIMEFRAMES tf, datetime &last_bar_time, string tf_name)
{
   datetime current_bar = iTime(_Symbol, tf, 0);
   if(current_bar != last_bar_time)
   {
      // New bar opened -> prior bar confirmed closed!
      if(last_bar_time != 0)
      {
         double o = iOpen(_Symbol, tf, 1);
         double h = iHigh(_Symbol, tf, 1);
         double l = iLow(_Symbol, tf, 1);
         double c = iClose(_Symbol, tf, 1);
         long   v = iTickVolume(_Symbol, tf, 1);

         PrintFormat("[NEW_BAR|%s] Time: %s | O: %.2f | H: %.2f | L: %.2f | C: %.2f | TickVol: %I64d (CONFIRMED)",
                     tf_name, TimeToString(last_bar_time, TIME_DATE|TIME_MINUTES), o, h, l, c, v);
      }
      last_bar_time = current_bar;
   }
}

//+------------------------------------------------------------------+
//| Update Chart Visual HUD Overlay                                  |
//+------------------------------------------------------------------+
void UpdateChartHUD()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double pnl     = AccountInfoDouble(ACCOUNT_PROFIT);
   string curr    = AccountInfoString(ACCOUNT_CURRENCY);

   string hud = "========================================================\n"
              + StringFormat("  [UNIVERSAL AI ANALYST BRIDGE - %s] \n", _Symbol)
              + "  MODE: READ-ONLY TELEMETRY (NO AUTOMATED TRADING)\n"
              + "========================================================\n"
              + StringFormat("  Account Balance : $%.2f %s\n", balance, curr)
              + StringFormat("  Live Equity     : $%.2f %s\n", equity, curr)
              + StringFormat("  Floating P&L    : %s$%.2f\n", (pnl >= 0 ? "+" : ""), pnl)
              + StringFormat("  Active Positions: %d\n", PositionsTotal())
              + "========================================================\n"
              + "  Decisions & Executions must be made manually by trader.\n"
              + "========================================================";

   Comment(hud);
}
//+------------------------------------------------------------------+
