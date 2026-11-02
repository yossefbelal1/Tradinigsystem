//+------------------------------------------------------------------+
//|                                           PRO_CANDLE_CASCADE.mq5 |
//|                                  Copyright 2026, Antigravity AI  |
//|    Professional Multi-Timeframe Break & Retest Cascade Engine   |
//|  (W1+D1 Context -> Key Broken S/R in Dealing Range -> H1 Entry)  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://github.com/Antigravity-AI"
#property version   "6.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Enums
enum ENUM_ZONE_TYPE
{
   ZONE_BROKEN_SUPPORT_SELL = 0, // Broken support flipped to Resistance (SELL on retest in Premium)
   ZONE_BROKEN_RESIST_BUY   = 1  // Broken resistance flipped to Support (BUY on retest in Discount)
};

enum ENUM_RISK_TYPE
{
   RISK_PERCENT = 0,             // Risk % of Equity
   RISK_FIXED   = 1              // Fixed Lot Size
};

//--- Struct for Active Broken Levels
struct SBrokenZone
{
   ulong             id;
   ENUM_ZONE_TYPE    type;
   double            level;           // Broken price level
   double            swing_extreme;   // Originating swing high (for sell) or low (for buy)
   double            impulse_extreme; // Lowest low reached (for sell) or highest high (for buy)
   datetime          break_time;      // Time bar closed beyond level
   bool              active;          // Still valid and waiting for retest
   bool              tested;          // Already tested
};

//--- Inputs
input group "=== 1. Execution & Timing Window (Cairo Time) ==="
input ulong             InpMagicNumber        = 777999;              // Magic Number
input ENUM_TIMEFRAMES   InpExecTF             = PERIOD_H1;           // Retest Execution Timeframe (H1)
input ENUM_TIMEFRAMES   InpStructureTF        = PERIOD_D1;           // Structure Key Level Timeframe (D1 or H4)
input bool              InpUseCairoSession    = true;                // Use Cairo Trading Hours
input int               InpCairoStartHour     = 15;                  // Cairo Session Start Hour (15:00 = 3:00 PM)
input int               InpCairoEndHour       = 23;                  // Cairo Session End Hour (23:00 = Market Close)
input int               InpMaxTradesPerDay    = 1;                   // Max Trades per Day (A+ Setups Only)

input group "=== 2. Multi-Timeframe Structure & EMA 100 Rule ==="
input bool              InpUseEMA100Filter    = true;                // Enforce Strict EMA 100 Rule ("مافيش بيع فوق 100 و العكس")
input int               InpEMA100Period       = 100;                 // EMA Period (100)
input ENUM_TIMEFRAMES   InpEMA100TF           = PERIOD_H4;           // EMA Timeframe (H4 or D1)
input bool              InpRequireCandleColor = true;                // Require Rejection Candle (Red for Sell, Green for Buy)
input int               InpStructureSwingBars = 2;                   // Structure Swing Fractal Radius (2 = 5-bar swing)
input int               InpStructureLookback  = 80;                  // Lookback Bars for Structure Swings
input double            InpRetestTolerancePoints = 250.0;            // Retest Tolerance Points (25 pts on Nas, 2.5 on Gold)
input int               InpMaxLossesPerDay    = 1;                   // Max Losses Per Day (Stop Trading on Bad Days)

input group "=== 3. Smart Money Dealing Range (Discount vs Premium) ==="
input bool              InpRequirePremiumDiscount = true;            // Require Retest in Premium (Sell) / Discount (Buy)
input double            InpEquilibriumPct     = 50.0;                // 50% Dealing Range Equilibrium Rule

input group "=== 4. Risk & Target Management (FundingPips Compliant) ==="
input ENUM_RISK_TYPE    InpRiskMode           = RISK_PERCENT;        // Risk Mode
input double            InpRiskPercent        = 1.5;                 // Risk Percent per Trade (1.5%)
input double            InpFixedLot           = 0.01;                // Fixed Lot Size
input double            InpSLBufferDollars    = 35.0;                // Stop Loss Buffer (35 pts on Nas, 2.5 on Gold)
input double            InpRR_Ratio           = 1.5;                 // Take Profit Risk-to-Reward Ratio (1:1.5)
input bool              InpCloseFullOnTP1     = false;               // Bank Full Profit at TP1
input double            InpPartialClosePct    = 50.0;                // Partial Close % at TP1
input bool              InpEnableRunnerTP     = true;                // Target Previous Swing Floor/Ceiling (Full Move)
input double            InpMaxSpreadPoints    = 500.0;               // Max Allowed Spread (Points)

input group "=== 5. Prop Firm Guardian ==="
input double            InpMaxDailyLossPct    = 4.0;                 // Max Daily Drawdown Circuit Breaker (4.0%)
input int               InpMaxWeeklyLosses    = 2;                   // Max Allowed Losses per Week (Circuit Breaker)
input double            InpMaxMonthlyLossPct  = 3.0;                 // Max Monthly Loss % before Pausing (FundingPips Shield)
input bool              InpShowDashboard      = false;               // Show Visual Dashboard
input bool              InpDebugLog           = false;               // Diagnostic Logging

//--- Global Objects & State
CTrade         m_trade;
CPositionInfo  m_position;
COrderInfo     m_order;
CAccountInfo   m_account;

SBrokenZone    g_zones[];
ulong          g_zoneIdCounter   = 1;
datetime       g_lastBarTime     = 0;
int            g_tradesTodayCount = 0;
int            g_currentDayOfYear = -1;
double         g_dayStartEquity   = 0.0;
bool           g_dailyCircuitBreaker = false;
int            g_hEMA100         = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Calculate Cairo Hour accounting for Egypt Daylight Saving Time   |
//+------------------------------------------------------------------+
int GetCairoHour(datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);

   bool isSummer = false;
   if(dt.mon > 4 && dt.mon < 10)
      isSummer = true;
   else if(dt.mon == 4 && dt.day >= 25)
      isSummer = true;
   else if(dt.mon == 10 && dt.day < 25)
      isSummer = true;

   int utcOffset = isSummer ? 3 : 2;
   int cairoHour = (dt.hour + utcOffset) % 24;
   return cairoHour;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(50);
   m_trade.SetTypeFilling(ORDER_FILLING_FOK);

   g_currentDayOfYear    = -1;
   g_tradesTodayCount    = 0;
   g_dayStartEquity      = AccountInfoDouble(ACCOUNT_EQUITY);
   g_dailyCircuitBreaker = false;

   ArrayResize(g_zones, 0);

   if(InpUseEMA100Filter)
   {
      g_hEMA100 = iMA(_Symbol, InpEMA100TF, InpEMA100Period, 0, MODE_EMA, PRICE_CLOSE);
      if(g_hEMA100 == INVALID_HANDLE)
         PrintFormat("WARNING: Failed to create EMA 100 indicator handle on %s!", EnumToString(InpEMA100TF));
      else
         PrintFormat("EMA 100 Handle successfully created on %s (%s)", _Symbol, EnumToString(InpEMA100TF));
   }

   PrintFormat("PRO CANDLE CASCADE V6.0 Initialized on %s | Structure TF: %s | Exec TF: %s",
               _Symbol, EnumToString(InpStructureTF), EnumToString(InpExecTF));

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_hEMA100 != INVALID_HANDLE)
   {
      IndicatorRelease(g_hEMA100);
      g_hEMA100 = INVALID_HANDLE;
   }
   ArrayResize(g_zones, 0);
}

//+------------------------------------------------------------------+
//| Check and reset daily statistics / Circuit Breakers              |
//+------------------------------------------------------------------+
void CheckDailyReset()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(dt.day_of_year != g_currentDayOfYear)
   {
      g_currentDayOfYear    = dt.day_of_year;
      g_tradesTodayCount    = 0;
      g_dayStartEquity      = AccountInfoDouble(ACCOUNT_EQUITY);
      g_dailyCircuitBreaker = false;
   }

   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_dayStartEquity > 0.0)
   {
      double lossPct = (g_dayStartEquity - currentEquity) / g_dayStartEquity * 100.0;
      if(lossPct >= InpMaxDailyLossPct)
      {
         if(!g_dailyCircuitBreaker)
         {
            PrintFormat("PRO CANDLE CASCADE: Daily Loss Circuit Breaker Triggered! Loss: %.2f%% >= Limit: %.2f%%",
                        lossPct, InpMaxDailyLossPct);
            g_dailyCircuitBreaker = true;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Scan Structure Timeframe for Broken Levels                       |
//+------------------------------------------------------------------+
void UpdateBrokenStructureZones()
{
   MqlRates s_rates[];
   ArraySetAsSeries(s_rates, true);
   int copied = CopyRates(_Symbol, InpStructureTF, 1, InpStructureLookback, s_rates);
   if(copied < 10) return;

   int radius = InpStructureSwingBars;

   for(int i = radius; i < copied - radius; i++)
   {
      // 1. Detect Swing Low
      bool isSwingLow = true;
      for(int r = 1; r <= radius; r++)
      {
         if(s_rates[i].low >= s_rates[i-r].low || s_rates[i].low >= s_rates[i+r].low)
         {
            isSwingLow = false;
            break;
         }
      }

      if(isSwingLow)
      {
         double swingLowPrice = s_rates[i].low;

         // Check if a subsequent bar closed below this swing low
         for(int k = i - 1; k >= 0; k--)
         {
            if(s_rates[k].close < swingLowPrice)
            {
               bool exists = false;
               int totalZones = ArraySize(g_zones);
               for(int z = 0; z < totalZones; z++)
               {
                  if(g_zones[z].active && MathAbs(g_zones[z].level - swingLowPrice) < (2.0 * _Point))
                  {
                     exists = true;
                     break;
                  }
               }

               if(!exists)
               {
                  double swingHigh = swingLowPrice;
                  for(int m = k; m <= i; m++)
                  {
                     if(s_rates[m].high > swingHigh) swingHigh = s_rates[m].high;
                  }

                  int newIdx = ArraySize(g_zones);
                  ArrayResize(g_zones, newIdx + 1);
                  g_zones[newIdx].id              = g_zoneIdCounter++;
                  g_zones[newIdx].type            = ZONE_BROKEN_SUPPORT_SELL;
                  g_zones[newIdx].level           = swingLowPrice;
                  g_zones[newIdx].swing_extreme   = swingHigh;
                  g_zones[newIdx].impulse_extreme = s_rates[k].low;
                  g_zones[newIdx].break_time      = s_rates[k].time;
                  g_zones[newIdx].active          = true;
                  g_zones[newIdx].tested          = false;

                  if(InpDebugLog)
                     PrintFormat("Identified Broken Support Zone #%d at %.2f (Swing High: %.2f)",
                                 g_zones[newIdx].id, swingLowPrice, swingHigh);
               }
               break;
            }
         }
      }

      // 2. Detect Swing High
      bool isSwingHigh = true;
      for(int r = 1; r <= radius; r++)
      {
         if(s_rates[i].high <= s_rates[i-r].high || s_rates[i].high <= s_rates[i+r].high)
         {
            isSwingHigh = false;
            break;
         }
      }

      if(isSwingHigh)
      {
         double swingHighPrice = s_rates[i].high;

         for(int k = i - 1; k >= 0; k--)
         {
            if(s_rates[k].close > swingHighPrice)
            {
               bool exists = false;
               int totalZones = ArraySize(g_zones);
               for(int z = 0; z < totalZones; z++)
               {
                  if(g_zones[z].active && MathAbs(g_zones[z].level - swingHighPrice) < (2.0 * _Point))
                  {
                     exists = true;
                     break;
                  }
               }

               if(!exists)
               {
                  double swingLow = swingHighPrice;
                  for(int m = k; m <= i; m++)
                  {
                     if(s_rates[m].low < swingLow) swingLow = s_rates[m].low;
                  }

                  int newIdx = ArraySize(g_zones);
                  ArrayResize(g_zones, newIdx + 1);
                  g_zones[newIdx].id              = g_zoneIdCounter++;
                  g_zones[newIdx].type            = ZONE_BROKEN_RESIST_BUY;
                  g_zones[newIdx].level           = swingHighPrice;
                  g_zones[newIdx].swing_extreme   = swingLow;
                  g_zones[newIdx].impulse_extreme = s_rates[k].high;
                  g_zones[newIdx].break_time      = s_rates[k].time;
                  g_zones[newIdx].active          = true;
                  g_zones[newIdx].tested          = false;

                  if(InpDebugLog)
                     PrintFormat("Identified Broken Resistance Zone #%d at %.2f (Swing Low: %.2f)",
                                 g_zones[newIdx].id, swingHighPrice, swingLow);
               }
               break;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Calculate Lot Size Based on Structural Stop Loss Risk            |
//+------------------------------------------------------------------+
double CalculateLotSize(double slDistanceDollars)
{
   if(InpRiskMode == RISK_FIXED)
      return InpFixedLot;

   if(slDistanceDollars <= 0) return InpFixedLot;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskAmount = equity * (InpRiskPercent / 100.0);

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);

   if(tickSize <= 0 || tickValue <= 0)
      return InpFixedLot;

   double dollarPerLot = (slDistanceDollars / tickSize) * tickValue;
   if(dollarPerLot <= 0) return InpFixedLot;

   double rawLots = riskAmount / dollarPerLot;

   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(stepLot > 0)
      rawLots = MathFloor(rawLots / stepLot) * stepLot;

   rawLots = MathMax(minLot, MathMin(MathMin(maxLot, 5.0), rawLots));
   return rawLots;
}

//+------------------------------------------------------------------+
//| Manage Open Positions (TP1 Banking + Move to Breakeven)          |
//+------------------------------------------------------------------+
void ManageOpenPositions()
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

            // Check BUY position
            if(posType == POSITION_TYPE_BUY)
            {
               double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
               double targetTP1  = openPrice + (riskDist * InpRR_Ratio);

               if(currentBid >= targetTP1 && slPrice < openPrice)
               {
                  if(InpCloseFullOnTP1)
                  {
                     m_trade.PositionClose(ticket);
                     PrintFormat("PRO CANDLE CASCADE V6.0: Full Position Closed at TP1 (+%.2fR) | Ticket: %d",
                                 InpRR_Ratio, ticket);
                  }
                  else
                  {
                     double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                     double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                     double partialLot = NormalizeDouble(volume * (InpPartialClosePct / 100.0), 2);
                     if(stepLot > 0) partialLot = MathFloor(partialLot / stepLot) * stepLot;

                     if(partialLot >= minLot && (volume - partialLot) >= minLot)
                        m_trade.PositionClosePartial(ticket, partialLot);
                     else if(volume - partialLot < minLot)
                        m_trade.PositionClose(ticket);

                     double spreadPts = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
                     double beBuffer = MathMax(spreadPts * 1.5 * _Point, (StringFind(_Symbol, "XAU") >= 0 ? 0.40 : 15.0 * _Point));
                     double beSL = openPrice + beBuffer;
                     m_trade.PositionModify(ticket, beSL, m_position.TakeProfit());
                  }
               }
            }
            // Check SELL position
            else if(posType == POSITION_TYPE_SELL)
            {
               double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
               double targetTP1  = openPrice - (riskDist * InpRR_Ratio);

               if(currentAsk <= targetTP1 && slPrice > openPrice)
               {
                  if(InpCloseFullOnTP1)
                  {
                     m_trade.PositionClose(ticket);
                     PrintFormat("PRO CANDLE CASCADE V6.0: Full Position Closed at TP1 (+%.2fR) | Ticket: %d",
                                 InpRR_Ratio, ticket);
                  }
                  else
                  {
                     double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                     double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                     double partialLot = NormalizeDouble(volume * (InpPartialClosePct / 100.0), 2);
                     if(stepLot > 0) partialLot = MathFloor(partialLot / stepLot) * stepLot;

                     if(partialLot >= minLot && (volume - partialLot) >= minLot)
                        m_trade.PositionClosePartial(ticket, partialLot);
                     else if(volume - partialLot < minLot)
                        m_trade.PositionClose(ticket);

                     double spreadPts = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
                     double beBuffer = MathMax(spreadPts * 1.5 * _Point, (StringFind(_Symbol, "XAU") >= 0 ? 0.40 : 15.0 * _Point));
                     double beSL = openPrice - beBuffer;
                     m_trade.PositionModify(ticket, beSL, m_position.TakeProfit());
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Count Open Positions and Pending Orders                          |
//+------------------------------------------------------------------+
int CountTotalPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Get EMA 100 Trend Rule strictly: "مافيش بيع فوق 100 و العكس"      |
//+------------------------------------------------------------------+
void GetEMA100Trend(bool &allow_buy, bool &allow_sell)
{
   allow_buy = true;
   allow_sell = true;
   if(!InpUseEMA100Filter) return;

   if(g_hEMA100 == INVALID_HANDLE)
   {
      g_hEMA100 = iMA(_Symbol, InpEMA100TF, InpEMA100Period, 0, MODE_EMA, PRICE_CLOSE);
      if(g_hEMA100 == INVALID_HANDLE) return;
   }

   double maVal[1];
   if(CopyBuffer(g_hEMA100, 0, 1, 1, maVal) >= 1)
   {
      MqlRates tfRates[1];
      if(CopyRates(_Symbol, InpEMA100TF, 1, 1, tfRates) >= 1)
      {
         if(tfRates[0].close > maVal[0])
         {
            // Price is ABOVE EMA 100: ONLY BUY! NO SELL!
            allow_buy  = true;
            allow_sell = false;
         }
         else if(tfRates[0].close < maVal[0])
         {
            // Price is BELOW EMA 100: ONLY SELL! NO BUY!
            allow_buy  = false;
            allow_sell = true;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Daily Reset & Circuit Breaker Check
   CheckDailyReset();

   // 2. Active Trade Management
   ManageOpenPositions();

   if(g_dailyCircuitBreaker) return;

   // 3. New Bar Check on Execution TF (H1)
   datetime currentBarTime = iTime(_Symbol, InpExecTF, 0);
   if(currentBarTime == g_lastBarTime) return;
   g_lastBarTime = currentBarTime;

   // 4. Session Timing Filter (Cairo Time)
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(InpUseCairoSession)
   {
      int cairoHour = GetCairoHour(TimeCurrent());
      if(cairoHour < InpCairoStartHour || cairoHour > InpCairoEndHour) return;
      if(dt.day_of_week == 5 && cairoHour >= 22) return; // Friday gap protection
   }

   // Daily Loss Cap Protection (FundingPips): Stop if daily losses reached
   if(InpMaxLossesPerDay > 0)
   {
      datetime dayStart = StringToTime(TimeToString(TimeCurrent(), TIME_DATE) + " 00:00:00");
      HistorySelect(dayStart, TimeCurrent());
      int closedDeals = HistoryDealsTotal();
      int lossesToday = 0;
      for(int i = 0; i < closedDeals; i++)
      {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket > 0)
         {
            long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
            long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
            string sym = HistoryDealGetString(ticket, DEAL_SYMBOL);
            double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
            if(sym == _Symbol && magic == InpMagicNumber && entry == DEAL_ENTRY_OUT)
            {
               if(profit < 0.0) lossesToday++;
            }
         }
      }
      if(lossesToday >= InpMaxLossesPerDay) return;
   }

   // Max daily trades limit (FundingPips: 1 high-quality trade per day)
   if(g_tradesTodayCount >= InpMaxTradesPerDay) return;
   if(CountTotalPositions() > 0) return;

   // Spread Protection
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(InpMaxSpreadPoints > 0 && spread > InpMaxSpreadPoints) return;

   // 5. Update Broken Structure Zones
   UpdateBrokenStructureZones();

   // 6. Trend Confluence: Strict EMA 100 Rule ("مافيش بيع طول ما هو فوق 100 و العكس")
   bool allow_buy = true, allow_sell = true;
   GetEMA100Trend(allow_buy, allow_sell);

   // Intraday Execution Bar (Last completed H1 bar)
   MqlRates h1_rates[];
   ArraySetAsSeries(h1_rates, true);
   if(CopyRates(_Symbol, InpExecTF, 1, 2, h1_rates) < 2) return;

   double b_high  = h1_rates[0].high;
   double b_low   = h1_rates[0].low;
   double b_close = h1_rates[0].close;
   double b_open  = h1_rates[0].open;

   double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   double tol = (StringFind(_Symbol, "XAU") >= 0) ? 2.50 : 25.0;
   double slBuffer = (StringFind(_Symbol, "XAU") >= 0) ? InpSLBufferDollars : MathMax(InpSLBufferDollars, 35.0);

   // 7. Check Active Zones for Break & Retest Setup
   int totalZones = ArraySize(g_zones);
   for(int z = 0; z < totalZones; z++)
   {
      if(!g_zones[z].active || g_zones[z].tested) continue;

      double level = g_zones[z].level;

      // --- SELL SETUP (Broken Support -> Resistance Retest in Premium) ---
      if(g_zones[z].type == ZONE_BROKEN_SUPPORT_SELL)
      {
         if(!allow_sell) continue;

         // Update lowest low reached by the move
         if(b_low < g_zones[z].impulse_extreme)
            g_zones[z].impulse_extreme = b_low;

         double dealingRange = g_zones[z].swing_extreme - g_zones[z].impulse_extreme;
         if(dealingRange <= 0) continue;
         double eq = g_zones[z].impulse_extreme + (dealingRange * (InpEquilibriumPct / 100.0));

         // Check if price pulled up into the broken floor in Premium
         bool inPremium = (!InpRequirePremiumDiscount) || (b_high >= eq);
         bool touchedLevel = (b_high >= (level - tol));

         if(inPremium && touchedLevel)
         {
            // Retest Rejection or Liquidity Sweep: candle closed back near/below the broken level
            if(b_close <= (level + tol) && (!InpRequireCandleColor || b_close < b_open))
            {
               double slPrice = b_high + slBuffer;
               double riskDist = slPrice - currentBid;

               if(riskDist > 1.0)
               {
                  double targetDist = currentBid - g_zones[z].impulse_extreme;
                  double tpPrice = (InpEnableRunnerTP && targetDist >= (riskDist * InpRR_Ratio)) ? 
                                   g_zones[z].impulse_extreme : 
                                   (currentBid - (riskDist * InpRR_Ratio));
                  double lot = CalculateLotSize(riskDist);

                  if(m_trade.Sell(lot, _Symbol, currentBid, slPrice, tpPrice, "CASCADE Retest SELL"))
                  {
                     g_tradesTodayCount++;
                     g_zones[z].tested = true;
                     g_zones[z].active = false;
                     PrintFormat("PRO CANDLE CASCADE V6.0: Executed SELL Retest at %.2f | SL: %.2f (Risk: $%.2f) | TP: %.2f | Lot: %.2f",
                                 currentBid, slPrice, riskDist, tpPrice, lot);
                     break;
                  }
               }
            }
            // Invalidation: if price closes decisively above the level, zone is blown and deleted
            else if(b_close > (level + 4.0 * tol))
            {
               g_zones[z].active = false;
            }
         }
      }
      // --- BUY SETUP (Broken Resistance -> Support Retest in Discount) ---
      else if(g_zones[z].type == ZONE_BROKEN_RESIST_BUY)
      {
         if(!allow_buy) continue;

         // Update highest high reached by the move
         if(b_high > g_zones[z].impulse_extreme)
            g_zones[z].impulse_extreme = b_high;

         double dealingRange = g_zones[z].impulse_extreme - g_zones[z].swing_extreme;
         if(dealingRange <= 0) continue;
         double eq = g_zones[z].swing_extreme + (dealingRange * (InpEquilibriumPct / 100.0));

         // Check if price pulled down into the broken ceiling in Discount
         bool inDiscount = (!InpRequirePremiumDiscount) || (b_low <= eq);
         bool touchedLevel = (b_low <= (level + tol));

         if(inDiscount && touchedLevel)
         {
            // Retest Bounce or Liquidity Sweep: candle closed back near/above the broken level
            if(b_close >= (level - tol) && (!InpRequireCandleColor || b_close > b_open))
            {
               double slPrice = b_low - slBuffer;
               double riskDist = currentAsk - slPrice;

               if(riskDist > 1.0)
               {
                  double targetDist = g_zones[z].impulse_extreme - currentAsk;
                  double tpPrice = (InpEnableRunnerTP && targetDist >= (riskDist * InpRR_Ratio)) ? 
                                   g_zones[z].impulse_extreme : 
                                   (currentAsk + (riskDist * InpRR_Ratio));
                  double lot = CalculateLotSize(riskDist);

                  if(m_trade.Buy(lot, _Symbol, currentAsk, slPrice, tpPrice, "CASCADE Retest BUY"))
                  {
                     g_tradesTodayCount++;
                     g_zones[z].tested = true;
                     g_zones[z].active = false;
                     PrintFormat("PRO CANDLE CASCADE V6.0: Executed BUY Retest at %.2f | SL: %.2f (Risk: $%.2f) | TP: %.2f | Lot: %.2f",
                                 currentAsk, slPrice, riskDist, tpPrice, lot);
                     break;
                  }
               }
            }
            // Invalidation: if price closes decisively below the level, zone is blown and deleted
            else if(b_close < (level - 4.0 * tol))
            {
               g_zones[z].active = false;
            }
         }
      }
   }
}
//+------------------------------------------------------------------+