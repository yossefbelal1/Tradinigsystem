//+------------------------------------------------------------------+
//|                                           PRO_CANDLE_CASCADE.mq5 |
//|                                  Copyright 2026, Antigravity AI  |
//|               Multi-Timeframe Candle Momentum & S/R Cascade EA   |
//|             (W1+D1 Supply/Demand Bias -> Today Open -> M15 Entry)|
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://github.com/Antigravity-AI"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- Enums
enum ENUM_ENTRY_TYPE
{
   ENTRY_MARKET_INSTANT = 0, // Market Execution
   ENTRY_PENDING_STOP   = 1  // Pending Stop Order (Breakout)
};

enum ENUM_RISK_TYPE
{
   RISK_PERCENT = 0,         // Risk % of Equity
   RISK_FIXED   = 1          // Fixed Lot Size
};

//--- Input Parameters
input group "=== 1. Execution & Timing Window ==="
input ulong             InpMagicNumber        = 777999;              // Magic Number
input ENUM_TIMEFRAMES   InpExecTF             = PERIOD_M15;          // Intraday Execution Timeframe (M15 or M30)
input ENUM_ENTRY_TYPE   InpEntryType          = ENTRY_MARKET_INSTANT;// Entry Order Type
input int               InpStartHour          = 13;                  // Session Start Hour (13:00 NY Open Expansion)
input int               InpEndHour            = 21;                  // Session End Hour (21:00 NY Close)
input int               InpMaxTradesPerDay    = 2;                   // Max Trades per Day
input int               InpMaxDailyLosses     = 1;                   // Max Losses per Day (1 = Stop trading if 1 trade loses)

input group "=== 2. Multi-Timeframe Alignment & Supply/Demand Bias ==="
input bool              InpRequireW1Confluence= true;                // Require W1 Weekly Candle / Zone Agreement
input bool              InpRequireD1Confluence= true;                // Require D1 Yesterday Confirmation
input bool              InpRequireTodayExp    = true;                // Require Today Expansion (Above/Below Today Open)
input bool              InpUseSupplyDemandBias= true;                // Use W1 & D1 Supply/Demand Zones for Daily Bias
input int               InpW1LookbackBars     = 26;                  // Weekly S/D Lookback Bars
input int               InpD1LookbackBars     = 35;                  // Daily S/D Lookback Bars

input group "=== 3. Volatility & Support/Resistance Filter ==="
input bool              InpUseATRFilter       = true;                // Filter Out Low Volatility Dead Markets
input int               InpATRPeriod          = 14;                  // ATR Period
input int               InpATRSMAPeriod       = 50;                  // ATR Baseline SMA Period
input double            InpMinATRFactor       = 0.70;                // Min ATR Factor (ATR14 >= 0.70 * SMA50)
input bool              InpUseSRFilter        = true;                // Enable H4 S/R Clearance Filter
input ENUM_TIMEFRAMES   InpSRTimeframe        = PERIOD_H4;           // Support/Resistance Timeframe (H4)
input int               InpSRLookbackBars     = 80;                  // S/R Fractal Lookback Bars
input double            InpMinDistanceSRDollars = 4.0;               // Min Distance to Opposing S/R (in Dollars, e.g. $4 on Gold)

input group "=== 4. Risk & Target Management (R:R 1:1.5 - 1:2.0) ==="
input ENUM_RISK_TYPE    InpRiskMode           = RISK_PERCENT;        // Risk Sizing Mode
input double            InpRiskPercent        = 1.0;                 // Risk Percent per Trade (1.0%)
input double            InpFixedLot           = 0.01;                // Fixed Lot Size
input double            InpRR_Ratio           = 1.5;                 // Target Risk-to-Reward Ratio (1:1.5)
input int               InpSL_LookbackBars    = 6;                   // Intraday SL Lookback Bars (Recent Extreme)
input double            InpSLBufferDollars    = 1.5;                 // Stop Loss Buffer in Dollars ($1.5)
input double            InpMinRiskDollars     = 3.5;                 // Min Risk Distance in Dollars ($3.5 on Gold)
input double            InpMaxRiskDollars     = 18.0;                // Max Risk Distance in Dollars ($18.0 on Gold)
input bool              InpEnablePartialTP    = true;                // Close 50% at 1:1.5 and Move to Breakeven
input double            InpRunnerTP_RR        = 2.0;                 // Runner Target (1:2.0)
input double            InpMaxSpreadPoints    = 500.0;               // Max Allowed Spread (Points)

input group "=== 5. Prop Firm Guardian ==="
input double            InpMaxDailyLossPct    = 2.5;                 // Max Daily Drawdown Circuit Breaker (%)
input bool              InpShowDashboard      = false;               // Show Visual Dashboard
input bool              InpDebugLog           = false;               // Enable Verbose Diagnostics

//--- Global Objects
CTrade         m_trade;
CPositionInfo  m_position;
COrderInfo     m_order;
CAccountInfo   m_account;

int            h_fractals_sr = INVALID_HANDLE;
int            h_atr_m15     = INVALID_HANDLE;
int            h_ema20       = INVALID_HANDLE;
datetime       g_lastExecBarTime = 0;
int            g_tradesTodayCount = 0;
int            g_currentDayOfYear = -1;
double         g_dayStartEquity   = 0.0;
bool           g_dailyCircuitBreaker = false;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(25);
   m_trade.SetTypeFillingBySymbol(_Symbol);

   g_dayStartEquity   = AccountInfoDouble(ACCOUNT_EQUITY);
   g_currentDayOfYear = -1;
   g_tradesTodayCount = 0;
   g_dailyCircuitBreaker = false;

   // Initialize Fractals for H4 S/R clearance
   if(InpUseSRFilter)
   {
      h_fractals_sr = iFractals(_Symbol, InpSRTimeframe);
      if(h_fractals_sr == INVALID_HANDLE)
         Print("Warning: Failed to create iFractals handle on ", EnumToString(InpSRTimeframe));
   }

   // Initialize ATR
   if(InpUseATRFilter)
   {
      h_atr_m15 = iATR(_Symbol, InpExecTF, InpATRPeriod);
      if(h_atr_m15 == INVALID_HANDLE)
         Print("Warning: Failed to create iATR handle on ", EnumToString(InpExecTF));
   }

   // Initialize EMA20 for Dynamic Value & Pullback Filter
   h_ema20 = iMA(_Symbol, InpExecTF, 20, 0, MODE_EMA, PRICE_CLOSE);
   if(h_ema20 == INVALID_HANDLE)
      Print("Warning: Failed to create iMA handle on ", EnumToString(InpExecTF));

   PrintFormat("PRO CANDLE CASCADE v3.0 Initialized | Symbol: %s | ExecTF: %s | Hours: %d-%d | R:R: %.1f",
               _Symbol, EnumToString(InpExecTF), InpStartHour, InpEndHour, InpRR_Ratio);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(h_fractals_sr != INVALID_HANDLE) IndicatorRelease(h_fractals_sr);
   if(h_atr_m15 != INVALID_HANDLE) IndicatorRelease(h_atr_m15);
   if(h_ema20 != INVALID_HANDLE) IndicatorRelease(h_ema20);
}

//+------------------------------------------------------------------+
//| Daily Session & Loss Circuit Breaker                             |
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
//| Real-time Deal History Loss Counter (Prop Firm Trade Guardian)   |
//+------------------------------------------------------------------+
int GetDailyRealizedLosses()
{
   datetime dayStart = iTime(_Symbol, PERIOD_D1, 0);
   if(dayStart <= 0) return 0;

   if(!HistorySelect(dayStart, TimeCurrent()))
      return 0;

   int totalDeals = HistoryDealsTotal();
   int losses = 0;

   for(int i = 0; i < totalDeals; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket > 0)
      {
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);
         string sym = HistoryDealGetString(ticket, DEAL_SYMBOL);

         if(entry == DEAL_ENTRY_OUT && magic == InpMagicNumber && sym == _Symbol)
         {
            double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
            if(profit < -0.01)
               losses++;
         }
      }
   }
   return losses;
}

//+------------------------------------------------------------------+
//| Check ATR Volatility Filter                                      |
//+------------------------------------------------------------------+
bool IsVolatilitySufficient()
{
   if(!InpUseATRFilter || h_atr_m15 == INVALID_HANDLE) return true;

   double atrBuf[];
   ArraySetAsSeries(atrBuf, true);
   int copied = CopyBuffer(h_atr_m15, 0, 1, InpATRSMAPeriod + 5, atrBuf);
   if(copied < InpATRSMAPeriod) return true;

   double currentATR = atrBuf[0];
   double sumATR = 0.0;
   for(int i = 0; i < InpATRSMAPeriod; i++)
      sumATR += atrBuf[i];
   double smaATR = sumATR / (double)InpATRSMAPeriod;

   if(smaATR > 0.0 && currentATR < (smaATR * InpMinATRFactor))
      return false; // Dead volatility / Low momentum compression

   return true;
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

   // 1 standard lot moves (slDistanceDollars / tickSize) * tickValue
   double dollarPerLot = (slDistanceDollars / tickSize) * tickValue;
   if(dollarPerLot <= 0) return InpFixedLot;

   double rawLots = riskAmount / dollarPerLot;

   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(stepLot > 0)
      rawLots = MathFloor(rawLots / stepLot) * stepLot;

   rawLots = MathMax(minLot, MathMin(maxLot, rawLots));
   return rawLots;
}

//+------------------------------------------------------------------+
//| Detect Supply and Demand Zones on High Timeframe (W1 or D1)     |
//+------------------------------------------------------------------+
void GetHTFSupplyDemandZones(ENUM_TIMEFRAMES tf, int lookback, 
                             double &recentSupplyTop, double &recentSupplyBot,
                             double &recentDemandTop, double &recentDemandBot)
{
   recentSupplyTop = 99999999.0;
   recentSupplyBot = 99999999.0;
   recentDemandTop = 0.0;
   recentDemandBot = 0.0;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, tf, 1, lookback, rates);
   if(copied < 5) return;

   double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // Find nearest swing high above current price (Supply Zone)
   for(int i = 2; i < copied - 2; i++)
   {
      if(rates[i].high > rates[i-1].high && rates[i].high > rates[i+1].high &&
         rates[i].high > rates[i-2].high && rates[i].high > rates[i+2].high)
      {
         if(rates[i].high > currentBid && rates[i].high < recentSupplyTop)
         {
            recentSupplyTop = rates[i].high;
            recentSupplyBot = MathMin(rates[i].open, rates[i].close);
         }
      }
   }

   // Find nearest swing low below current price (Demand Zone)
   for(int i = 2; i < copied - 2; i++)
   {
      if(rates[i].low < rates[i-1].low && rates[i].low < rates[i+1].low &&
         rates[i].low < rates[i-2].low && rates[i].low < rates[i+2].low)
      {
         if(rates[i].low < currentBid && rates[i].low > recentDemandBot)
         {
            recentDemandBot = rates[i].low;
            recentDemandTop = MathMax(rates[i].open, rates[i].close);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Evaluate Weekly (W1) Bias using Supply/Demand + Price Action     |
//+------------------------------------------------------------------+
void EvaluateWeeklyBias(bool &w1_bull, bool &w1_bear)
{
   w1_bull = false;
   w1_bear = false;

   MqlRates w_rates[];
   ArraySetAsSeries(w_rates, true);
   int copied = CopyRates(_Symbol, PERIOD_W1, 1, 10, w_rates);
   if(copied < 2) return;

   double w_close = w_rates[0].close;
   double w_open  = w_rates[0].open;
   double w_high  = w_rates[0].high;
   double w_low   = w_rates[0].low;
   double w_rng   = w_high - w_low;

   double w_sup_top, w_sup_bot, w_dem_top, w_dem_bot;
   GetHTFSupplyDemandZones(PERIOD_W1, InpW1LookbackBars, w_sup_top, w_sup_bot, w_dem_top, w_dem_bot);

   bool testedSupply = (w_high >= w_sup_bot && w_close < w_sup_top);
   bool testedDemand = (w_low <= w_dem_top && w_close > w_dem_bot);

   bool w_bull_close  = (w_close > w_open);
   bool w_bear_close  = (w_close < w_open);
   bool w_bull_engulf = (w_close > w_open && w_close > w_rates[1].high);
   bool w_bear_engulf = (w_close < w_open && w_close < w_rates[1].low);

   bool w_shooting_star = (w_rng > 0 && (w_high - MathMax(w_open, w_close)) >= (0.45 * w_rng));
   bool w_hammer        = (w_rng > 0 && (MathMin(w_open, w_close) - w_low) >= (0.45 * w_rng));

   if(InpUseSupplyDemandBias && testedSupply && (w_bear_close || w_shooting_star))
   {
      w1_bear = true; // Weekly rejected Supply Zone
   }
   else if(InpUseSupplyDemandBias && testedDemand && (w_bull_close || w_hammer))
   {
      w1_bull = true; // Weekly bounced from Demand Zone
   }
   else
   {
      // Trend continuation & Candlestick Price Action
      if(w_bull_engulf || (w_bull_close && !w_shooting_star))
         w1_bull = true;
      if(w_bear_engulf || (w_bear_close && !w_hammer))
         w1_bear = true;
   }
}

//+------------------------------------------------------------------+
//| Evaluate Daily (D1) Confirmation using S/D + Price Action        |
//+------------------------------------------------------------------+
void EvaluateDailyBias(bool &d1_bull, bool &d1_bear)
{
   d1_bull = false;
   d1_bear = false;

   MqlRates d_rates[];
   ArraySetAsSeries(d_rates, true);
   int copied = CopyRates(_Symbol, PERIOD_D1, 1, 15, d_rates);
   if(copied < 3) return;

   double d_close = d_rates[0].close;
   double d_open  = d_rates[0].open;
   double d_high  = d_rates[0].high;
   double d_low   = d_rates[0].low;
   double d_rng   = d_high - d_low;

   double p_high  = d_rates[1].high;
   double p_low   = d_rates[1].low;

   double d_sup_top, d_sup_bot, d_dem_top, d_dem_bot;
   GetHTFSupplyDemandZones(PERIOD_D1, InpD1LookbackBars, d_sup_top, d_sup_bot, d_dem_top, d_dem_bot);

   bool testedDailySupply = (d_high >= d_sup_bot && d_close < d_sup_top);
   bool testedDailyDemand = (d_low <= d_dem_top && d_close > d_dem_bot);

   bool d_bull_close  = (d_close > d_open);
   bool d_bear_close  = (d_close < d_open);
   bool d_bull_engulf = (d_close > d_open && d_close > p_high);
   bool d_bear_engulf = (d_close < d_open && d_close < p_low);

   bool d_shooting_star = (d_rng > 0 && (d_high - MathMax(d_open, d_close)) >= (0.45 * d_rng));
   bool d_hammer        = (d_rng > 0 && (MathMin(d_open, d_close) - d_low) >= (0.45 * d_rng));

   if(InpUseSupplyDemandBias && testedDailySupply && (d_bear_close || d_shooting_star))
   {
      d1_bear = true;
   }
   else if(InpUseSupplyDemandBias && testedDailyDemand && (d_bull_close || d_hammer))
   {
      d1_bull = true;
   }
   else
   {
      if(d_bull_engulf || (d_bull_close && !d_shooting_star))
         d1_bull = true;
      if(d_bear_engulf || (d_bear_close && !d_hammer))
         d1_bear = true;
   }
}

//+------------------------------------------------------------------+
//| Find Nearest H4 Fractal Support and Resistance Levels            |
//+------------------------------------------------------------------+
void GetNearestSR(double &nearestResistance, double &nearestSupport)
{
   nearestResistance = 99999999.0;
   nearestSupport    = 0.0;

   if(h_fractals_sr == INVALID_HANDLE) return;

   double upBuf[], lowBuf[];
   ArraySetAsSeries(upBuf, true);
   ArraySetAsSeries(lowBuf, true);

   int copiedUp  = CopyBuffer(h_fractals_sr, 0, 1, InpSRLookbackBars, upBuf);
   int copiedLow = CopyBuffer(h_fractals_sr, 1, 1, InpSRLookbackBars, lowBuf);

   double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(copiedUp > 0)
   {
      for(int i = 0; i < copiedUp; i++)
      {
         if(upBuf[i] != EMPTY_VALUE && upBuf[i] > currentPrice)
         {
            if(upBuf[i] < nearestResistance)
               nearestResistance = upBuf[i];
         }
      }
   }

   if(copiedLow > 0)
   {
      for(int i = 0; i < copiedLow; i++)
      {
         if(lowBuf[i] != EMPTY_VALUE && lowBuf[i] < currentPrice)
         {
            if(lowBuf[i] > nearestSupport)
               nearestSupport = lowBuf[i];
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Manage Open Positions (Partial TP at 1:1.5 + Move to Breakeven)  |
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

               // Partial TP trigger: price reached TP1 (1:1.5) and SL not yet at breakeven
               if(InpEnablePartialTP && currentBid >= targetTP1 && slPrice < openPrice)
               {
                  double halfLot = NormalizeDouble(volume * 0.5, 2);
                  double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                  double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                  if(stepLot > 0) halfLot = MathFloor(halfLot / stepLot) * stepLot;

                  if(halfLot >= minLot && (volume - halfLot) >= minLot)
                  {
                     m_trade.PositionClosePartial(ticket, halfLot);
                     PrintFormat("PRO CANDLE CASCADE: Partial Close 50% (%.2f lots) at TP1 (%.2f) on #%d",
                                 halfLot, targetTP1, ticket);
                  }

                  // Move SL to Breakeven + 20 points
                  double beSL = openPrice + (20.0 * _Point);
                  double runnerTP = openPrice + (riskDist * InpRunnerTP_RR);
                  m_trade.PositionModify(ticket, beSL, runnerTP);
                  PrintFormat("PRO CANDLE CASCADE: Moved SL to Breakeven (%.2f) on #%d", beSL, ticket);
               }
            }
            // Check SELL position
            else if(posType == POSITION_TYPE_SELL)
            {
               double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
               double targetTP1  = openPrice - (riskDist * InpRR_Ratio);

               // Partial TP trigger: price reached TP1 (1:1.5) and SL not yet at breakeven
               if(InpEnablePartialTP && currentAsk <= targetTP1 && slPrice > openPrice)
               {
                  double halfLot = NormalizeDouble(volume * 0.5, 2);
                  double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
                  double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
                  if(stepLot > 0) halfLot = MathFloor(halfLot / stepLot) * stepLot;

                  if(halfLot >= minLot && (volume - halfLot) >= minLot)
                  {
                     m_trade.PositionClosePartial(ticket, halfLot);
                     PrintFormat("PRO CANDLE CASCADE: Partial Close 50% (%.2f lots) at TP1 (%.2f) on #%d",
                                 halfLot, targetTP1, ticket);
                  }

                  // Move SL to Breakeven - 20 points
                  double beSL = openPrice - (20.0 * _Point);
                  double runnerTP = openPrice - (riskDist * InpRunnerTP_RR);
                  m_trade.PositionModify(ticket, beSL, runnerTP);
                  PrintFormat("PRO CANDLE CASCADE: Moved SL to Breakeven (%.2f) on #%d", beSL, ticket);
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
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(m_order.SelectByIndex(i))
      {
         if(m_order.Symbol() == _Symbol && m_order.Magic() == InpMagicNumber)
            count++;
      }
   }
   return count;
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

   // 3. New Bar Check on Execution TF
   datetime currentExecTime = iTime(_Symbol, InpExecTF, 0);
   if(currentExecTime == g_lastExecBarTime) return;
   g_lastExecBarTime = currentExecTime;

   // 4. Session Timing Filter (NY Open to late afternoon 13:00 - 21:00)
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour || dt.hour == 12) return;
   if(dt.day_of_week == 5 && dt.hour >= 20) return; // Friday gap protection

   // Max daily trades limit
   if(g_tradesTodayCount >= InpMaxTradesPerDay) return;

   // Prop Firm Trade Guardian: Stop trading today if realized loss >= limit
   if(InpMaxDailyLosses > 0 && GetDailyRealizedLosses() >= InpMaxDailyLosses)
      return;

   // If already in an active position, do not open another
   if(CountTotalPositions() > 0) return;

   // Volatility regime filter
   if(!IsVolatilitySufficient()) return;

   // Spread Protection
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(InpMaxSpreadPoints > 0 && spread > InpMaxSpreadPoints) return;

   // 5. Gather Multi-Timeframe Alignment & Daily Bias
   bool w1_bull = false, w1_bear = false;
   bool d1_bull = false, d1_bear = false;
   EvaluateWeeklyBias(w1_bull, w1_bear);
   EvaluateDailyBias(d1_bull, d1_bear);

   bool bias_buy  = (!InpRequireW1Confluence || w1_bull) && (!InpRequireD1Confluence || d1_bull);
   bool bias_sell = (!InpRequireW1Confluence || w1_bear) && (!InpRequireD1Confluence || d1_bear);

   // Today's Open Price
   MqlRates rates_d1_curr[];
   ArraySetAsSeries(rates_d1_curr, true);
   if(CopyRates(_Symbol, PERIOD_D1, 0, 1, rates_d1_curr) < 1) return;
   double today_open = rates_d1_curr[0].open;

   // Intraday Execution Bar (Last completed M15 bar)
   int checkBars = InpSL_LookbackBars + 2;
   MqlRates rates_exec[];
   ArraySetAsSeries(rates_exec, true);
   int c_exec = CopyRates(_Symbol, InpExecTF, 1, checkBars, rates_exec);
   if(c_exec < checkBars) return;

   double c_sig = rates_exec[0].close;
   double o_sig = rates_exec[0].open;

   // Intraday recent extreme (last N bars)
   double rec_high = rates_exec[0].high;
   double rec_low  = rates_exec[0].low;
   for(int k = 1; k < InpSL_LookbackBars; k++)
   {
      if(rates_exec[k].high > rec_high) rec_high = rates_exec[k].high;
      if(rates_exec[k].low < rec_low)   rec_low  = rates_exec[k].low;
   }

   double currentBid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double currentAsk = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // Confluence Assessment (System & Entry conditions are identical!)
   bool today_exp_buy  = (!InpRequireTodayExp) || (currentAsk > today_open);
   bool today_exp_sell = (!InpRequireTodayExp) || (currentBid < today_open);

   // Dynamic Value EMA20 Filter (Must pull back to near value, not chase extended tops)
   double emaBuf[];
   ArraySetAsSeries(emaBuf, true);
   double emaVal = 0.0;
   if(h_ema20 != INVALID_HANDLE && CopyBuffer(h_ema20, 0, 1, 1, emaBuf) > 0)
      emaVal = emaBuf[0];

   bool pullBackBuy  = (emaVal > 0.0) ? (c_sig > emaVal && rec_low <= (emaVal + 4.5)) : true;
   bool pullBackSell = (emaVal > 0.0) ? (c_sig < emaVal && rec_high >= (emaVal - 4.5)) : true;

   bool setup_buy  = bias_buy  && today_exp_buy  && (c_sig > o_sig) && pullBackBuy;
   bool setup_sell = bias_sell && today_exp_sell && (c_sig < o_sig) && pullBackSell;

   // 6. Major Support and Resistance Clearance Filter
   double nearestRes = 0.0, nearestSup = 0.0;
   if(InpUseSRFilter)
   {
      GetNearestSR(nearestRes, nearestSup);
      if(setup_buy && (nearestRes - currentAsk) < InpMinDistanceSRDollars)
         setup_buy = false;
      if(setup_sell && (currentBid - nearestSup) < InpMinDistanceSRDollars)
         setup_sell = false;
   }

   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minStopDist = (stopsLevel + 5) * _Point;

   // 7. Execute Orders with Precise Intraday Structural SL
   // --- BUY SETUP ---
   if(setup_buy && !setup_sell)
   {
      double slPrice = rec_low - InpSLBufferDollars;
      if(currentAsk - slPrice < minStopDist) slPrice = currentAsk - minStopDist;

      double riskDistDollars = currentAsk - slPrice;
      if(riskDistDollars < InpMinRiskDollars || riskDistDollars > InpMaxRiskDollars)
         return;

      double targetRR = InpEnablePartialTP ? InpRunnerTP_RR : InpRR_Ratio;
      double tpPrice  = currentAsk + (riskDistDollars * targetRR);

      double lot = CalculateLotSize(riskDistDollars);
      if(m_trade.Buy(lot, _Symbol, currentAsk, slPrice, tpPrice, "CASCADE Buy"))
      {
         g_tradesTodayCount++;
         PrintFormat("PRO CANDLE CASCADE: Executed BUY at %.2f | SL: %.2f (Risk: $%.2f) | TP: %.2f | Lots: %.2f",
                     currentAsk, slPrice, riskDistDollars, tpPrice, lot);
      }
   }
   // --- SELL SETUP ---
   else if(setup_sell && !setup_buy)
   {
      double slPrice = rec_high + InpSLBufferDollars;
      if(slPrice - currentBid < minStopDist) slPrice = currentBid + minStopDist;

      double riskDistDollars = slPrice - currentBid;
      if(riskDistDollars < InpMinRiskDollars || riskDistDollars > InpMaxRiskDollars)
         return;

      double targetRR = InpEnablePartialTP ? InpRunnerTP_RR : InpRR_Ratio;
      double tpPrice  = currentBid - (riskDistDollars * targetRR);

      double lot = CalculateLotSize(riskDistDollars);
      if(m_trade.Sell(lot, _Symbol, currentBid, slPrice, tpPrice, "CASCADE Sell"))
      {
         g_tradesTodayCount++;
         PrintFormat("PRO CANDLE CASCADE: Executed SELL at %.2f | SL: %.2f (Risk: $%.2f) | TP: %.2f | Lots: %.2f",
                     currentBid, slPrice, riskDistDollars, tpPrice, lot);
      }
   }
}
//+------------------------------------------------------------------+