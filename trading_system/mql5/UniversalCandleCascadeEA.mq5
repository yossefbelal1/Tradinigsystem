//+------------------------------------------------------------------+
//|                                     UniversalCandleCascadeEA.mq5 |
//|                                  Copyright 2026, Antigravity AI  |
//|               Universal Top-Down Candle Anticipation Cascade EA  |
//|        (MN1 Macro -> W1 Bias -> D1 Expansion -> Intraday Sniping)|
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://github.com/yossefbelal1/Tradinigsystem"
#property version   "2.00"
#property description "Professional Top-Down Multi-Timeframe Candle Momentum & S/R Cascade Expert Advisor"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Enums
enum ENUM_EXECUTION_MODE
{
   MODE_MANUAL_SEMI_AUTO = 0, // Semi-Automatic (One-Click Chart Execution Button)
   MODE_FULL_AUTOMATIC   = 1  // Fully Automatic (Executes immediately upon Bar Confirmation)
};

enum ENUM_RISK_MODE
{
   RISK_PERCENT_EQUITY = 0,   // Risk % of Current Equity (Institutional / Prop Firm)
   RISK_FIXED_LOT      = 1    // Fixed Lot Size
};

//--- Input Parameters
input group "=== 1. Execution Mode & Magic Number ==="
input ulong                InpMagicNumber        = 888999;               // Magic Number
input ENUM_EXECUTION_MODE  InpExecutionMode      = MODE_MANUAL_SEMI_AUTO;// Initial Execution Mode
input bool                 InpEnableSound        = true;                 // Enable Alert Sound on Setup
input int                  InpMaxTradesPerDay    = 2;                    // Max Allowed Trades per Day
input double               InpMaxSpreadPoints    = 500.0;                // Max Allowed Spread (Points)

input group "=== 2. Top-Down Cascade Alignment (MN1 -> W1 -> D1) ==="
input bool                 InpRequireMN1Filter   = true;                 // Check Monthly (MN1) Macro Structure & POI
input bool                 InpRequireW1Candle    = true;                 // Require Weekly (W1) Expected Candle Confluence
input bool                 InpRequireD1Candle    = true;                 // Require Daily (D1) Yesterday PA & Today Expansion
input int                  InpSwingLookbackBars  = 50;                   // Swing High/Low Lookback Bars

input group "=== 3. Intraday Execution Scanning (H4 -> H1 -> M30 -> M15) ==="
input bool                 InpScanH4             = true;                 // Scan H4 for Entry Confluence
input bool                 InpScanH1             = true;                 // Scan H1 for Entry Confluence
input bool                 InpScanM30            = true;                 // Scan M30 for Entry Confluence
input bool                 InpScanM15            = true;                 // Scan M15 for Entry Confluence
input double               InpMinWickPercent     = 55.0;                 // Minimum Rejection Wick % for Pin Bar
input double               InpMaxBodyPercent     = 40.0;                 // Maximum Body % for Pin Bar
input double               InpZoneProximityATR   = 0.50;                 // Max Distance to Key S/R Zone (x ATR)

input group "=== 4. Risk & Target Management (Prop Firm Certified) ==="
input ENUM_RISK_MODE       InpRiskMode           = RISK_PERCENT_EQUITY;  // Risk Sizing Mode
input double               InpRiskPercent        = 1.0;                  // Risk Percent per Trade (%)
input double               InpFixedLotSize       = 0.01;                 // Fixed Lot Size (if Fixed mode)
input double               InpRR_TP1             = 1.5;                  // Target Risk-Reward TP1 (Partial Close 50%)
input double               InpRR_TP2             = 2.5;                  // Target Risk-Reward TP2 (Runner Target)
input double               InpSLBufferPoints     = 50.0;                 // Stop Loss Buffer Beyond Zone / Swing (Points)
input bool                 InpMoveToBreakEven    = true;                 // Move Stop-Loss to Break-Even upon TP1
input double               InpMaxDailyLossPct    = 4.5;                  // Daily Drawdown Circuit Breaker (% of Starting Equity)

input group "=== 5. Visual Levels & Clean Chart Settings ==="
input bool                 InpDrawCleanLevels    = true;                 // Draw Only Nearest 3 Active Levels Above/Below
input color                InpResistanceColor    = clrTomato;            // Resistance / Flipped Resistance Color
input color                InpSupportColor       = clrDodgerBlue;        // Support / Flipped Support Color
input color                InpEntryLineColor     = clrGold;              // Planned Entry Color
input color                InpSLLineColor        = clrCrimson;           // Planned Stop Loss Color
input color                InpTPLineColor        = clrLimeGreen;         // Planned Take Profit Color

//--- GUI Button Names & Prefixes
#define AGY_PREFIX          "AGY_CC_"
#define BTN_ANALYZE_ID      "AGY_CC_BTN_ANALYZE"
#define BTN_MODE_ID         "AGY_CC_BTN_MODE"
#define BTN_EXECUTE_ID      "AGY_CC_BTN_EXEC"
#define BTN_CLOSE_ID        "AGY_CC_BTN_CLOSE"

//--- Global Engine Variables
CTrade         m_trade;
CPositionInfo  m_position;
COrderInfo     m_order;
CAccountInfo   m_account;

ENUM_EXECUTION_MODE g_currentMode;
int                 g_currentDayOfYear   = -1;
int                 g_tradesTodayCount   = 0;
double              g_dayStartEquity     = 0.0;
bool                g_circuitBreaker     = false;
datetime            g_lastProcessedBar   = 0;

// Planned Setup Structure
struct ActiveTradePlan
{
   bool              is_valid;
   string            direction;         // "BUY", "SELL", "WAIT"
   ENUM_TIMEFRAMES   trigger_tf;        // The intraday TF that triggered
   string            trigger_reason;    // Description of confluence
   double            entry_price;
   double            stop_loss;
   double            take_profit_1;
   double            take_profit_2;
   double            calculated_lot;
   double            monetary_risk_usd;
   double            risk_reward_ratio;
};

ActiveTradePlan g_activePlan;

// Cascade State Structure
struct CascadeState
{
   int    mn1_bias;         // 1 = Bullish, -1 = Bearish, 0 = Neutral
   string mn1_desc;
   int    w1_bias;          // 1 = Bullish, -1 = Bearish, 0 = Neutral
   string w1_desc;
   int    d1_bias;          // 1 = Bullish, -1 = Bearish, 0 = Neutral
   string d1_desc;
   string macro_verdict;    // "STRICT SELL ONLY", "STRICT BUY ONLY", "WAIT CONFLUENCE"
   string status_message;
};

CascadeState g_cascade;

// Forward Declarations
void RunFullTopDownCascade();
void AnalyzeTimeframe(ENUM_TIMEFRAMES tf, int &bias, string &desc, double &swingHigh, double &swingLow);
bool CheckIntradayTrigger(ENUM_TIMEFRAMES tf, int macroBias, double &entry, double &sl, double &tp1, double &tp2, string &reason);
double CalculateDynamicLot(double slDistancePoints);
void ManageOpenTrades();
void CreateChartUI();
void DestroyChartUI();
void UpdateUIButtons();
void UpdateChartHUD();
void ExecutePlannedOrder();
void CloseAllPositions();
void DrawCleanRays(double &nearestRes[], double &nearestSup[]);
void ClearVisualDrawings();
void DrawRay(string name, double price, color clr, ENUM_LINE_STYLE style, int width, string desc);

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(20);
   m_trade.SetTypeFillingBySymbol(_Symbol);

   g_currentMode        = InpExecutionMode;
   g_currentDayOfYear   = -1;
   g_tradesTodayCount   = 0;
   g_dayStartEquity     = AccountInfoDouble(ACCOUNT_EQUITY);
   g_circuitBreaker     = false;
   g_lastProcessedBar   = 0;

   ZeroMemory(g_activePlan);
   g_activePlan.direction = "WAIT";

   // Build UI buttons on chart
   CreateChartUI();

   // Run initial top-down analysis
   RunFullTopDownCascade();

   // Set fast timer for responsive UI and position trailing
   EventSetTimer(1);

   PrintFormat("==================================================================");
   PrintFormat(" [UNIVERSAL CANDLE CASCADE EA] Initialized on %s", _Symbol);
   PrintFormat(" Mode: %s | Magic: %d | Risk: %.1f%% | Max Daily Loss: %.1f%%",
               (g_currentMode == MODE_FULL_AUTOMATIC ? "FULL AUTOMATIC" : "MANUAL / SEMI-AUTO"),
               InpMagicNumber, InpRiskPercent, InpMaxDailyLossPct);
   PrintFormat("==================================================================");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DestroyChartUI();
   ClearVisualDrawings();
   Comment("");
}

//+------------------------------------------------------------------+
//| OnTick function                                                  |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Manage Active Open Trades (Partial TP at 1:1.5 + Breakeven move)
   ManageOpenTrades();

   // 2. Check if a new bar formed on execution timeframe (M15)
   datetime currentBarTime = iTime(_Symbol, PERIOD_M15, 0);
   if(currentBarTime != g_lastProcessedBar)
   {
      g_lastProcessedBar = currentBarTime;

      // Run full top-down cascade analysis on bar close
      RunFullTopDownCascade();

      // If full auto-trade mode is active and we have a valid setup
      if(g_currentMode == MODE_FULL_AUTOMATIC && g_activePlan.is_valid && !g_circuitBreaker)
      {
         if(g_tradesTodayCount < InpMaxTradesPerDay)
         {
            ExecutePlannedOrder();
         }
      }
   }
}

//+------------------------------------------------------------------+
//| OnTimer function (Periodic UI refresh & Breakeven checks)        |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Check Daily Circuit Breaker
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_year != g_currentDayOfYear)
   {
      g_currentDayOfYear = dt.day_of_year;
      g_tradesTodayCount = 0;
      g_dayStartEquity   = AccountInfoDouble(ACCOUNT_EQUITY);
      g_circuitBreaker   = false;
   }

   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_dayStartEquity > 0.0)
   {
      double lossPct = (g_dayStartEquity - currentEquity) / g_dayStartEquity * 100.0;
      if(lossPct >= InpMaxDailyLossPct)
      {
         if(!g_circuitBreaker)
         {
            PrintFormat("PROPFIRM CIRCUIT BREAKER ACTIVATED! Loss: %.2f%% >= Limit: %.2f%%",
                        lossPct, InpMaxDailyLossPct);
            g_circuitBreaker = true;
         }
      }
   }

   // Manage open positions continuously
   ManageOpenTrades();

   // Update HUD & Buttons
   UpdateUIButtons();
   UpdateChartHUD();
}

//+------------------------------------------------------------------+
//| Chart Event Handler (Interactive Button Clicks)                  |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   if(id == CHARTEVENT_OBJECT_CLICK)
   {
      // 1. Analyze Button
      if(sparam == BTN_ANALYZE_ID)
      {
         ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_STATE, false);
         RunFullTopDownCascade();
         ChartRedraw(0);
      }
      // 2. Mode Toggle Button (Semi-Auto vs Full-Auto)
      else if(sparam == BTN_MODE_ID)
      {
         ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_STATE, false);
         g_currentMode = (g_currentMode == MODE_MANUAL_SEMI_AUTO) ? MODE_FULL_AUTOMATIC : MODE_MANUAL_SEMI_AUTO;
         UpdateUIButtons();
         ChartRedraw(0);
      }
      // 3. Execute Setup Button (One-Click Execution)
      else if(sparam == BTN_EXECUTE_ID)
      {
         ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_STATE, false);
         if(g_activePlan.is_valid)
         {
            ExecutePlannedOrder();
         }
         else
         {
            Alert("No Grade-A Confluence setup currently active to execute!");
         }
         ChartRedraw(0);
      }
      // 4. Close All Button
      else if(sparam == BTN_CLOSE_ID)
      {
         ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_STATE, false);
         CloseAllPositions();
         ChartRedraw(0);
      }
   }
}

//+------------------------------------------------------------------+
//| CORE TOP-DOWN CASCADE ENGINE                                     |
//+------------------------------------------------------------------+
void RunFullTopDownCascade()
{
   // Reset Plan
   ZeroMemory(g_activePlan);
   g_activePlan.direction = "WAIT";

   // ---------------------------------------------------------------
   // STEP 1: MONTHLY (MN1) MACRO ANALYSIS
   // ---------------------------------------------------------------
   double mnHigh = 0.0, mnLow = 0.0;
   AnalyzeTimeframe(PERIOD_MN1, g_cascade.mn1_bias, g_cascade.mn1_desc, mnHigh, mnLow);

   // ---------------------------------------------------------------
   // STEP 2: WEEKLY (W1) CANDLE BIAS & EXPECTATION
   // ---------------------------------------------------------------
   double wHigh = 0.0, wLow = 0.0;
   AnalyzeTimeframe(PERIOD_W1, g_cascade.w1_bias, g_cascade.w1_desc, wHigh, wLow);

   // ---------------------------------------------------------------
   // STEP 3: DAILY (D1) YESTERDAY'S CANDLE & TODAY'S EXPANSION BIAS
   // ---------------------------------------------------------------
   double dHigh = 0.0, dLow = 0.0;
   AnalyzeTimeframe(PERIOD_D1, g_cascade.d1_bias, g_cascade.d1_desc, dHigh, dLow);

   // ---------------------------------------------------------------
   // STEP 4: CASCADE ALIGNMENT VERDICT (The Trader's Core Law)
   // ---------------------------------------------------------------
   int macroDirection = 0; // 1 = Buy Only, -1 = Sell Only, 0 = Wait

   // --- Case A: Bearish Cascade (SELL ONLY) ---
   // "لو الاسبوعي هابط (مثلاً شمعة ابتلاعية هابطة) فا المتوقع شمعة الاسبوع الجاية هابطة
   // فا بالتالي علي الفريم اليومي هدور علي فرص بيع فقط علشان تخلقلنا شمعة الاسبوع اللي متوقعينها"
   if(g_cascade.w1_bias == -1 && g_cascade.d1_bias == -1 && (g_cascade.mn1_bias != 1 || !InpRequireMN1Filter))
   {
      macroDirection = -1;
      g_cascade.macro_verdict = "STRICT SELL ONLY (W1 + D1 Aligned Bearish)";
   }
   // --- Case B: Bullish Cascade (BUY ONLY) ---
   else if(g_cascade.w1_bias == 1 && g_cascade.d1_bias == 1 && (g_cascade.mn1_bias != -1 || !InpRequireMN1Filter))
   {
      macroDirection = 1;
      g_cascade.macro_verdict = "STRICT BUY ONLY (W1 + D1 Aligned Bullish)";
   }
   else
   {
      macroDirection = 0;
      g_cascade.macro_verdict = "WAIT (Conflict Between Weekly & Daily Expectations)";
   }

   // ---------------------------------------------------------------
   // STEP 5: INTRADAY SCANNING (H4 -> H1 -> M30 -> M15)
   // "لو عمل برايس اكشن هابط علي اليومي، انزل علي الـ 4 ساعات و الساعة و النص ساعة
   // ادور علي فرصة بيع وادخل بيع علي حسب ظهور الفرصة"
   // ---------------------------------------------------------------
   if(macroDirection != 0 && !g_circuitBreaker)
   {
      ENUM_TIMEFRAMES scanList[4] = { PERIOD_H4, PERIOD_H1, PERIOD_M30, PERIOD_M15 };
      bool scanEnables[4]         = { InpScanH4, InpScanH1, InpScanM30, InpScanM15 };

      for(int i = 0; i < 4; i++)
      {
         if(!scanEnables[i]) continue;

         double entry = 0.0, sl = 0.0, tp1 = 0.0, tp2 = 0.0;
         string reason = "";

         if(CheckIntradayTrigger(scanList[i], macroDirection, entry, sl, tp1, tp2, reason))
         {
            g_activePlan.is_valid          = true;
            g_activePlan.direction         = (macroDirection == 1) ? "BUY" : "SELL";
            g_activePlan.trigger_tf        = scanList[i];
            g_activePlan.trigger_reason    = reason;
            g_activePlan.entry_price       = entry;
            g_activePlan.stop_loss         = sl;
            g_activePlan.take_profit_1     = tp1;
            g_activePlan.take_profit_2     = tp2;
            g_activePlan.risk_reward_ratio = InpRR_TP1;

            double slPoints = MathAbs(entry - sl) / _Point;
            g_activePlan.calculated_lot    = CalculateDynamicLot(slPoints);
            g_activePlan.monetary_risk_usd = AccountInfoDouble(ACCOUNT_EQUITY) * (InpRiskPercent / 100.0);

            if(InpEnableSound) PlaySound("expert.wav");
            break; // Stop at highest confirming timeframe
         }
      }
   }

   // ---------------------------------------------------------------
   // STEP 6: DRAW CLEAN LEVELS & TRADE BLUEPRINT ON CHART
   // ---------------------------------------------------------------
   if(InpDrawCleanLevels)
   {
      ClearVisualDrawings();

      double resLevels[3] = {0,0,0};
      double supLevels[3] = {0,0,0};
      // Populate nearest D1/H4 levels
      resLevels[0] = dHigh;
      resLevels[1] = wHigh;
      supLevels[0] = dLow;
      supLevels[1] = wLow;

      DrawCleanRays(resLevels, supLevels);

      // If active plan exists, draw Blueprint
      if(g_activePlan.is_valid)
      {
         DrawRay(AGY_PREFIX + "BP_ENTRY", g_activePlan.entry_price, InpEntryLineColor, STYLE_SOLID, 2, 
                 StringFormat("ENTRY (%s @ %.5f)", g_activePlan.direction, g_activePlan.entry_price));
         DrawRay(AGY_PREFIX + "BP_SL", g_activePlan.stop_loss, InpSLLineColor, STYLE_SOLID, 2, 
                 StringFormat("STOP LOSS (%.5f)", g_activePlan.stop_loss));
         DrawRay(AGY_PREFIX + "BP_TP1", g_activePlan.take_profit_1, InpTPLineColor, STYLE_SOLID, 2, 
                 StringFormat("TP 1 (1:%.1f | %.5f)", InpRR_TP1, g_activePlan.take_profit_1));
         DrawRay(AGY_PREFIX + "BP_TP2", g_activePlan.take_profit_2, clrMediumSeaGreen, STYLE_DOT, 1, 
                 StringFormat("TP 2 (1:%.1f | %.5f)", InpRR_TP2, g_activePlan.take_profit_2));
      }
   }
}

//+------------------------------------------------------------------+
//| Analyze Timeframe Candle & Geometry                              |
//+------------------------------------------------------------------+
void AnalyzeTimeframe(ENUM_TIMEFRAMES tf, int &bias, string &desc, double &swingHigh, double &swingLow)
{
   bias = 0;
   desc = "Neutral";
   swingHigh = 0.0;
   swingLow  = 0.0;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, tf, 0, MathMax(InpSwingLookbackBars, 15), rates);
   if(copied < 5) return;

   // Swings over lookback
   swingHigh = rates[1].high;
   swingLow  = rates[1].low;
   for(int i = 1; i < copied; i++)
   {
      if(rates[i].high > swingHigh) swingHigh = rates[i].high;
      if(rates[i].low < swingLow)   swingLow  = rates[i].low;
   }

   // Candle [1] geometry
   double range     = rates[1].high - rates[1].low;
   double body      = MathAbs(rates[1].close - rates[1].open);
   double upperWick = rates[1].high - MathMax(rates[1].open, rates[1].close);
   double lowerWick = MathMin(rates[1].open, rates[1].close) - rates[1].low;

   bool isBearish = rates[1].close < rates[1].open;
   bool isBullish = rates[1].close > rates[1].open;

   // 1. Engulfing Detection
   bool bearEngulf = isBearish && (rates[2].close > rates[2].open) && 
                     (rates[1].open >= rates[2].close) && (rates[1].close <= rates[2].open);

   bool bullEngulf = isBullish && (rates[2].close < rates[2].open) && 
                     (rates[1].open <= rates[2].close) && (rates[1].close >= rates[2].open);

   // 2. Pin Bar Detection
   bool bearPin = (range > 0) && ((upperWick / range) >= (InpMinWickPercent / 100.0)) && 
                  ((body / range) <= (InpMaxBodyPercent / 100.0)) && (rates[1].close <= rates[1].low + (range * 0.45));

   bool bullPin = (range > 0) && ((lowerWick / range) >= (InpMinWickPercent / 100.0)) && 
                  ((body / range) <= (InpMaxBodyPercent / 100.0)) && (rates[1].close >= rates[1].low + (range * 0.55));

   // Synthesize Expectation
   if(bearEngulf)
   {
      bias = -1;
      desc = "Bearish Engulfing (Reversal / Continuation Down)";
   }
   else if(bearPin)
   {
      bias = -1;
      desc = "Bearish Pin Bar (Strong Rejection of Highs)";
   }
   else if(bullEngulf)
   {
      bias = 1;
      desc = "Bullish Engulfing (Reversal / Continuation Up)";
   }
   else if(bullPin)
   {
      bias = 1;
      desc = "Bullish Pin Bar (Strong Rejection of Lows)";
   }
   else if(isBearish && body >= (range * 0.55))
   {
      bias = -1;
      desc = "Bearish Momentum Expansion";
   }
   else if(isBullish && body >= (range * 0.55))
   {
      bias = 1;
      desc = "Bullish Momentum Expansion";
   }
   else
   {
      bias = 0;
      desc = "Consolidation / Indecision";
   }
}

//+------------------------------------------------------------------+
//| Check Intraday Trigger on Given Timeframe                        |
//+------------------------------------------------------------------+
bool CheckIntradayTrigger(ENUM_TIMEFRAMES tf, int macroBias, double &entry, double &sl, double &tp1, double &tp2, string &reason)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, tf, 0, 10, rates) < 5) return false;

   double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   long   stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minStopDist = (stopsLevel + 5) * _Point;

   // Intraday candle [1] geometry
   double range     = rates[1].high - rates[1].low;
   double body      = MathAbs(rates[1].close - rates[1].open);
   double upperWick = rates[1].high - MathMax(rates[1].open, rates[1].close);
   double lowerWick = MathMin(rates[1].open, rates[1].close) - rates[1].low;

   bool isBearish = rates[1].close < rates[1].open;
   bool isBullish = rates[1].close > rates[1].open;

   bool bearPin = (range > 0) && ((upperWick / range) >= (InpMinWickPercent / 100.0)) && 
                  ((body / range) <= (InpMaxBodyPercent / 100.0));
   bool bullPin = (range > 0) && ((lowerWick / range) >= (InpMinWickPercent / 100.0)) && 
                  ((body / range) <= (InpMaxBodyPercent / 100.0));

   bool bearEngulf = isBearish && (rates[2].close > rates[2].open) && (rates[1].close < rates[2].low);
   bool bullEngulf = isBullish && (rates[2].close < rates[2].open) && (rates[1].close > rates[2].high);

   // --- SELL TRIGGER ---
   if(macroBias == -1)
   {
      if(bearPin || bearEngulf || (isBearish && rates[0].close < rates[1].low))
      {
         entry = currentBid;
         sl    = rates[1].high + (InpSLBufferPoints * _Point);
         if(sl - entry < minStopDist) sl = entry + minStopDist;

         double riskDist = sl - entry;
         tp1   = entry - (riskDist * InpRR_TP1);
         tp2   = entry - (riskDist * InpRR_TP2);
         reason = StringFormat("%s Trigger: %s", EnumToString(tf), bearPin ? "Pin Bar" : (bearEngulf ? "Engulfing" : "Breakdown"));
         return true;
      }
   }
   // --- BUY TRIGGER ---
   else if(macroBias == 1)
   {
      if(bullPin || bullEngulf || (isBullish && rates[0].close > rates[1].high))
      {
         entry = currentAsk;
         sl    = rates[1].low - (InpSLBufferPoints * _Point);
         if(entry - sl < minStopDist) sl = entry - minStopDist;

         double riskDist = entry - sl;
         tp1   = entry + (riskDist * InpRR_TP1);
         tp2   = entry + (riskDist * InpRR_TP2);
         reason = StringFormat("%s Trigger: %s", EnumToString(tf), bullPin ? "Pin Bar" : (bullEngulf ? "Engulfing" : "Breakout"));
         return true;
      }
   }

   return false;
}

//+------------------------------------------------------------------+
//| Calculate Dynamic Institutional Lot Size                         |
//+------------------------------------------------------------------+
double CalculateDynamicLot(double slDistancePoints)
{
   if(InpRiskMode == RISK_FIXED_LOT)
      return InpFixedLotSize;

   if(slDistancePoints <= 0) return InpFixedLotSize;

   double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount = equity * (InpRiskPercent / 100.0);

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double point     = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   if(tickSize <= 0 || point <= 0 || tickValue <= 0)
      return InpFixedLotSize;

   double pointValue = tickValue * (point / tickSize);
   double rawLots    = riskAmount / (slDistancePoints * pointValue);

   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(stepLot > 0)
      rawLots = MathFloor(rawLots / stepLot) * stepLot;

   rawLots = MathMax(minLot, MathMin(maxLot, rawLots));
   return NormalizeDouble(rawLots, 2);
}

//+------------------------------------------------------------------+
//| Execute Planned Order (Market Entry)                             |
//+------------------------------------------------------------------+
void ExecutePlannedOrder()
{
   if(!g_activePlan.is_valid) return;

   // Check spread
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
   {
      PrintFormat("Trade Rejected: Spread (%d pts) exceeds max allowed (%d pts)", spread, (int)InpMaxSpreadPoints);
      return;
   }

   if(g_activePlan.direction == "BUY")
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(m_trade.Buy(g_activePlan.calculated_lot, _Symbol, ask, g_activePlan.stop_loss, g_activePlan.take_profit_2, "Cascade BUY"))
      {
         g_tradesTodayCount++;
         PrintFormat("EXECUTION SUCCESS: Opened BUY %.2f Lots @ %.5f | SL: %.5f | TP: %.5f",
                     g_activePlan.calculated_lot, ask, g_activePlan.stop_loss, g_activePlan.take_profit_2);
      }
   }
   else if(g_activePlan.direction == "SELL")
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(m_trade.Sell(g_activePlan.calculated_lot, _Symbol, bid, g_activePlan.stop_loss, g_activePlan.take_profit_2, "Cascade SELL"))
      {
         g_tradesTodayCount++;
         PrintFormat("EXECUTION SUCCESS: Opened SELL %.2f Lots @ %.5f | SL: %.5f | TP: %.5f",
                     g_activePlan.calculated_lot, bid, g_activePlan.stop_loss, g_activePlan.take_profit_2);
      }
   }
}

//+------------------------------------------------------------------+
//| Manage Open Positions (Partial TP at 1:1.5 + Breakeven Move)     |
//+------------------------------------------------------------------+
void ManageOpenTrades()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
         {
            double openPrice = m_position.PriceOpen();
            double slPrice   = m_position.StopLoss();
            double volume    = m_position.Volume();
            long posType     = m_position.PositionType();
            ulong ticket     = m_position.Ticket();

            if(openPrice <= 0 || slPrice <= 0) continue;
            double riskDist = MathAbs(openPrice - slPrice);
            if(riskDist <= 0) continue;

            // --- BUY POSITION ---
            if(posType == POSITION_TYPE_BUY)
            {
               double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
               double targetTP1  = openPrice + (riskDist * InpRR_TP1);

               // When price reaches TP1: move SL to BE and close 50%
               if(currentBid >= targetTP1 && slPrice < openPrice)
               {
                  if(InpMoveToBreakEven)
                  {
                     m_trade.PositionModify(ticket, openPrice, m_position.TakeProfit());
                     PrintFormat("Position #%d moved to BREAK-EVEN at %.5f", ticket, openPrice);
                  }

                  // Partial close 50%
                  double halfLot = NormalizeDouble(volume * 0.5, 2);
                  double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                  double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                  if(stepLot > 0) halfLot = MathFloor(halfLot / stepLot) * stepLot;

                  if(halfLot >= minLot && volume > halfLot)
                  {
                     m_trade.PositionClosePartial(ticket, halfLot);
                     PrintFormat("Position #%d: Partial Close 50% (%.2f lots) at TP1", ticket, halfLot);
                  }
               }
            }
            // --- SELL POSITION ---
            else if(posType == POSITION_TYPE_SELL)
            {
               double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
               double targetTP1  = openPrice - (riskDist * InpRR_TP1);

               if(currentAsk <= targetTP1 && slPrice > openPrice)
               {
                  if(InpMoveToBreakEven)
                  {
                     m_trade.PositionModify(ticket, openPrice, m_position.TakeProfit());
                     PrintFormat("Position #%d moved to BREAK-EVEN at %.5f", ticket, openPrice);
                  }

                  double halfLot = NormalizeDouble(volume * 0.5, 2);
                  double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                  double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                  if(stepLot > 0) halfLot = MathFloor(halfLot / stepLot) * stepLot;

                  if(halfLot >= minLot && volume > halfLot)
                  {
                     m_trade.PositionClosePartial(ticket, halfLot);
                     PrintFormat("Position #%d: Partial Close 50% (%.2f lots) at TP1", ticket, halfLot);
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Close All Positions for this Symbol & Magic                      |
//+------------------------------------------------------------------+
void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
         {
            m_trade.PositionClose(m_position.Ticket());
         }
      }
   }
   Print("All open positions closed.");
}

//+------------------------------------------------------------------+
//| GUI: Create Interactive On-Chart Controls                        |
//+------------------------------------------------------------------+
void CreateChartUI()
{
   int x = 20;
   int y = 30;

   // 1. Analyze Button
   ObjectDelete(0, BTN_ANALYZE_ID);
   ObjectCreate(0, BTN_ANALYZE_ID, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_XSIZE, 130);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_YSIZE, 26);
   ObjectSetString(0, BTN_ANALYZE_ID, OBJPROP_TEXT, "🚀 ANALYZE MTF");
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, BTN_ANALYZE_ID, OBJPROP_BGCOLOR, C'20,80,120');

   // 2. Mode Toggle Button
   ObjectDelete(0, BTN_MODE_ID);
   ObjectCreate(0, BTN_MODE_ID, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_XDISTANCE, x + 138);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_XSIZE, 130);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_YSIZE, 26);
   ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_COLOR, clrWhite);

   // 3. Execute Setup Button
   ObjectDelete(0, BTN_EXECUTE_ID);
   ObjectCreate(0, BTN_EXECUTE_ID, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_XDISTANCE, x + 276);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_XSIZE, 140);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_YSIZE, 26);
   ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_COLOR, clrWhite);

   // 4. Close All Button
   ObjectDelete(0, BTN_CLOSE_ID);
   ObjectCreate(0, BTN_CLOSE_ID, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_XDISTANCE, x + 424);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_XSIZE, 100);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_YSIZE, 26);
   ObjectSetString(0, BTN_CLOSE_ID, OBJPROP_TEXT, "🛑 CLOSE ALL");
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, BTN_CLOSE_ID, OBJPROP_BGCOLOR, C'100,30,30');

   UpdateUIButtons();
   ChartRedraw(0);
}

void DestroyChartUI()
{
   ObjectDelete(0, BTN_ANALYZE_ID);
   ObjectDelete(0, BTN_MODE_ID);
   ObjectDelete(0, BTN_EXECUTE_ID);
   ObjectDelete(0, BTN_CLOSE_ID);
}

void UpdateUIButtons()
{
   // Update Mode button text & color
   if(g_currentMode == MODE_FULL_AUTOMATIC)
   {
      ObjectSetString(0, BTN_MODE_ID, OBJPROP_TEXT, "🤖 AUTO: ON");
      ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_BGCOLOR, C'20,110,50');
   }
   else
   {
      ObjectSetString(0, BTN_MODE_ID, OBJPROP_TEXT, "✋ SEMI-AUTO");
      ObjectSetInteger(0, BTN_MODE_ID, OBJPROP_BGCOLOR, C'90,70,20');
   }

   // Update Execute button text & color
   if(g_activePlan.is_valid)
   {
      ObjectSetString(0, BTN_EXECUTE_ID, OBJPROP_TEXT, StringFormat("⚡ EXECUTE %s", g_activePlan.direction));
      ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_BGCOLOR, (g_activePlan.direction == "BUY") ? C'0,120,60' : C'140,20,20');
   }
   else
   {
      ObjectSetString(0, BTN_EXECUTE_ID, OBJPROP_TEXT, "⏳ WAITING SETUP");
      ObjectSetInteger(0, BTN_EXECUTE_ID, OBJPROP_BGCOLOR, C'50,50,50');
   }
}

//+------------------------------------------------------------------+
//| GUI: Comprehensive On-Chart Comment HUD                          |
//+------------------------------------------------------------------+
void UpdateChartHUD()
{
   string hud = "\n\n\n\n"
              + "====================================================================\n"
              + StringFormat("  [CANDLE CASCADE AI EXPERT - %s (%s)]\n", _Symbol, EnumToString(_Period))
              + "====================================================================\n"
              + StringFormat("  1. MONTHLY (MN1)  : %s [%s]\n", 
                             (g_cascade.mn1_bias == 1 ? "BULLISH" : (g_cascade.mn1_bias == -1 ? "BEARISH" : "NEUTRAL")), g_cascade.mn1_desc)
              + StringFormat("  2. WEEKLY  (W1)   : %s [%s]\n", 
                             (g_cascade.w1_bias == 1 ? "BULLISH" : (g_cascade.w1_bias == -1 ? "BEARISH" : "NEUTRAL")), g_cascade.w1_desc)
              + StringFormat("  3. DAILY   (D1)   : %s [%s]\n", 
                             (g_cascade.d1_bias == 1 ? "BULLISH" : (g_cascade.d1_bias == -1 ? "BEARISH" : "NEUTRAL")), g_cascade.d1_desc)
              + "--------------------------------------------------------------------\n"
              + StringFormat("  CASCADE VERDICT   : %s\n", g_cascade.macro_verdict)
              + "--------------------------------------------------------------------\n";

   if(g_activePlan.is_valid)
   {
      hud += StringFormat("  ACTIVE SETUP      : %s TRIGGERED ON %s\n", g_activePlan.direction, EnumToString(g_activePlan.trigger_tf))
           + StringFormat("  TRIGGER REASON    : %s\n", g_activePlan.trigger_reason)
           + StringFormat("  PLANNED ENTRY     : %.5f\n", g_activePlan.entry_price)
           + StringFormat("  STOP LOSS         : %.5f\n", g_activePlan.stop_loss)
           + StringFormat("  TARGET 1 (1:%.1f)  : %.5f (Close 50%% + Move to BE)\n", InpRR_TP1, g_activePlan.take_profit_1)
           + StringFormat("  TARGET 2 (1:%.1f)  : %.5f (Runner)\n", InpRR_TP2, g_activePlan.take_profit_2)
           + StringFormat("  RECOMMENDED LOTS  : %.2f Lots (Risk: $%.2f | 1.0%%)\n", g_activePlan.calculated_lot, g_activePlan.monetary_risk_usd);
   }
   else
   {
      hud += "  ACTIVE SETUP      : NO GRADE-A CONFLUENCE (SCANNING INTRADAY TF)...\n";
   }

   hud += "--------------------------------------------------------------------\n"
        + StringFormat("  PROP FIRM GUARD   : Daily Loss: %.2f%% / Limit: %.2f%% | Trades Today: %d/%d\n",
                       (g_dayStartEquity > 0 ? (g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY))/g_dayStartEquity * 100.0 : 0.0),
                       InpMaxDailyLossPct, g_tradesTodayCount, InpMaxTradesPerDay)
        + StringFormat("  EXECUTION STATUS  : %s%s\n", 
                       (g_currentMode == MODE_FULL_AUTOMATIC ? "AUTO-TRADING ACTIVE" : "SEMI-AUTO (Use Click Button)"),
                       (g_circuitBreaker ? " [CIRCUIT BREAKER LOCKOUT]" : ""))
        + "====================================================================";

   Comment(hud);
}

//+------------------------------------------------------------------+
//| Chart Visuals: Draw Clean Rays                                   |
//+------------------------------------------------------------------+
void DrawCleanRays(double &nearestRes[], double &nearestSup[])
{
   for(int i = 0; i < 2; i++)
   {
      if(nearestRes[i] > 0)
      {
         string name = StringFormat("%sRES_%d", AGY_PREFIX, i);
         DrawRay(name, nearestRes[i], InpResistanceColor, STYLE_DASH, 1, StringFormat("Macro Resistance %.5f", nearestRes[i]));
      }
      if(nearestSup[i] > 0)
      {
         string name = StringFormat("%sSUP_%d", AGY_PREFIX, i);
         DrawRay(name, nearestSup[i], InpSupportColor, STYLE_DASH, 1, StringFormat("Macro Support %.5f", nearestSup[i]));
      }
   }
}

void DrawRay(string name, double price, color clr, ENUM_LINE_STYLE style, int width, string desc)
{
   ObjectDelete(0, name);
   datetime t_start = iTime(_Symbol, _Period, MathMin(iBars(_Symbol, _Period) - 1, 35));
   datetime t_end   = TimeCurrent() + (PeriodSeconds(_Period) * 15);

   if(ObjectCreate(0, name, OBJ_TREND, 0, t_start, price, t_end, price))
   {
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, style);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, true);
      ObjectSetString(0, name, OBJPROP_TEXT, desc);
      ObjectSetString(0, name, OBJPROP_TOOLTIP, desc);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
   }
}

void ClearVisualDrawings()
{
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, AGY_PREFIX) == 0 && StringFind(name, "BTN_") < 0)
      {
         ObjectDelete(0, name);
      }
   }
}
//+------------------------------------------------------------------+
