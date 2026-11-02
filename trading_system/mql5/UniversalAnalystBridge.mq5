//+------------------------------------------------------------------+
//|                                     UniversalAnalystBridge.mq5   |
//|                    Copyright 2026, Trading Intelligence Systems  |
//|                                       https://www.tradingai.com  |
//+------------------------------------------------------------------+
#property copyright   "Trading Intelligence Systems"
#property link        "https://www.tradingai.com"
#property version     "2.00"
#property description "Interactive Universal Decision-Support Analyst Bridge for MT5."
#property description "STRICTLY READ-ONLY DECISION SUPPORT. NO AUTOMATED TRADE EXECUTION."

// STRICT SAFETY DIRECTIVE:
// This EA is compiled without any trade permissions or execution functions.
// Any execution function call will cause a compiler failure.
#define STRICT_READ_ONLY_MODE 1

//+------------------------------------------------------------------+
//| Input Parameters                                                 |
//+------------------------------------------------------------------+
input group "=== TELEMETRY & SYNC SETTINGS ==="
input int      InpTimerIntervalSec = 1;        // Bridge check interval (seconds)
input bool     InpAutoSync         = true;     // Auto-sync on symbol/timeframe change
input bool     InpDrawLevels       = true;     // Draw S/R Levels on chart
input bool     InpDrawZones        = true;     // Draw Supply/Demand zones on chart
input bool     InpDrawBlueprint    = true;     // Draw Trade Plan Blueprint lines
input color    InpDemandColor      = C'10,50,20'; // Demand zone background
input color    InpSupplyColor      = C'50,15,15'; // Supply zone background
input color    InpSupportColor     = clrDodgerBlue; // Support line color
input color    InpResistanceColor  = clrCoral;      // Resistance line color
input color    InpEntryColor       = clrGold;       // Blueprint Entry line color
input color    InpSLColor          = clrCrimson;    // Blueprint Stop Loss color
input color    InpTPColor          = clrLimeGreen;  // Blueprint Take Profit color

//+------------------------------------------------------------------+
//| Constants & Prefixes                                             |
//+------------------------------------------------------------------+
#define AGY_PREFIX       "AGY_UI_"
#define AGY_DRAW_PREFIX  "AGY_DRAW_"
#define BTN_ANALYZE      "AGY_UI_BTN_ANALYZE"
#define BTN_CLEAR        "AGY_UI_BTN_CLEAR"
#define BTN_SYNC         "AGY_UI_BTN_SYNC"
#define LBL_STATUS       "AGY_UI_LBL_STATUS"

//+------------------------------------------------------------------+
//| Global Variables                                                 |
//+------------------------------------------------------------------+
string   g_last_symbol    = "";
ENUM_TIMEFRAMES g_last_period = PERIOD_CURRENT;
bool     g_auto_sync      = true;
string   g_status_msg     = "Ready. Click [ANALYZE MTF] or press 'A'.";
color    g_status_color   = clrLightGray;
datetime g_last_req_time  = 0;

//+------------------------------------------------------------------+
//| Helper: Get Timeframe String Name                                |
//+------------------------------------------------------------------+
string GetTimeframeName(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
      default:         return "H1";
   }
}

//+------------------------------------------------------------------+
//| Helper: Get Period Minutes                                       |
//+------------------------------------------------------------------+
int GetPeriodMinutes(ENUM_TIMEFRAMES tf)
{
   return PeriodSeconds(tf) / 60;
}

//+------------------------------------------------------------------+
//| Simple JSON field extractor for primitive strings                |
//+------------------------------------------------------------------+
string ExtractJsonString(const string &json, const string &key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   
   // Skip whitespace
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '\t'))
      pos++;
      
   if(pos >= StringLen(json)) return "";
   
   if(StringGetCharacter(json, pos) == '\"')
   {
      pos++;
      int end_pos = StringFind(json, "\"", pos);
      if(end_pos < 0) return "";
      return StringSubstr(json, pos, end_pos - pos);
   }
   else
   {
      // Value without quotes (e.g. number, boolean, null)
      int end_pos = pos;
      while(end_pos < StringLen(json))
      {
         ushort c = StringGetCharacter(json, end_pos);
         if(c == ',' || c == '}' || c == ']' || c == '\n' || c == '\r')
            break;
         end_pos++;
      }
      string val = StringSubstr(json, pos, end_pos - pos);
      StringTrimLeft(val);
      StringTrimRight(val);
      return val;
   }
}

//+------------------------------------------------------------------+
//| Simple JSON field extractor for double numbers                   |
//+------------------------------------------------------------------+
double ExtractJsonDouble(const string &json, const string &key)
{
   string val = ExtractJsonString(json, key);
   if(val == "" || val == "null") return 0.0;
   return StringToDouble(val);
}

//+------------------------------------------------------------------+
//| Simple JSON field extractor for booleans                         |
//+------------------------------------------------------------------+
bool ExtractJsonBool(const string &json, const string &key)
{
   string val = ExtractJsonString(json, key);
   return (val == "true" || val == "1");
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("==================================================================");
   PrintFormat(" [UNIVERSAL ANALYST BRIDGE] Initializing Active Chart Bridge on %s (%s)", 
               _Symbol, GetTimeframeName(_Period));
   Print(" [SAFETY DIRECTIVE] Automated trade execution is strictly disabled. ");
   Print("==================================================================");

   g_last_symbol = _Symbol;
   g_last_period = _Period;
   g_auto_sync   = InpAutoSync;

   // Create on-chart UI buttons
   CreateUIControls();

   // Set timer for bridge inbox/outbox checking
   EventSetTimer(InpTimerIntervalSec);

   // Send initial sync telemetry
   SendChartRequest("CHART_SYNC");

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DestroyUIControls();
   ClearVisualAnalysis();
   Comment("");
   Print("[UNIVERSAL ANALYST BRIDGE] Deinitialized. Reason code: ", reason);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // No high-frequency processing required on tick; bridge operates via timer & chart events
}

//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Check for incoming analytical responses from Python engine
   CheckAnalysisResponse();
}

//+------------------------------------------------------------------+
//| Chart Event handler                                              |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   // 1. Button click events
   if(id == CHARTEVENT_OBJECT_CLICK)
   {
      if(sparam == BTN_ANALYZE)
      {
         // Reset button press state
         ObjectSetInteger(0, BTN_ANALYZE, OBJPROP_STATE, false);
         SendChartRequest("REQUEST_ANALYSIS");
         g_status_msg = "Requesting Full MTF Analysis from Python Engine...";
         g_status_color = clrGold;
         UpdateStatusLabel();
         ChartRedraw(0);
      }
      else if(sparam == BTN_CLEAR)
      {
         ObjectSetInteger(0, BTN_CLEAR, OBJPROP_STATE, false);
         ClearVisualAnalysis();
         Comment("");
         g_status_msg = "Chart visual layers cleared.";
         g_status_color = clrLightGray;
         UpdateStatusLabel();
         ChartRedraw(0);
      }
      else if(sparam == BTN_SYNC)
      {
         ObjectSetInteger(0, BTN_SYNC, OBJPROP_STATE, false);
         g_auto_sync = !g_auto_sync;
         UpdateSyncButton();
         g_status_msg = g_auto_sync ? "Auto-Sync Enabled." : "Auto-Sync Disabled.";
         g_status_color = g_auto_sync ? clrLimeGreen : clrTomato;
         UpdateStatusLabel();
         ChartRedraw(0);
      }
   }
   // 2. Keyboard shortcut events ('A' for analyze, 'C' for clear)
   else if(id == CHARTEVENT_KEYDOWN)
   {
      if(lparam == 'A' || lparam == 'a')
      {
         SendChartRequest("REQUEST_ANALYSIS");
         g_status_msg = "Hotkey [A]: Requesting MTF Analysis...";
         g_status_color = clrGold;
         UpdateStatusLabel();
         ChartRedraw(0);
      }
      else if(lparam == 'C' || lparam == 'c')
      {
         ClearVisualAnalysis();
         Comment("");
         g_status_msg = "Hotkey [C]: Visual layers cleared.";
         g_status_color = clrLightGray;
         UpdateStatusLabel();
         ChartRedraw(0);
      }
   }
   // 3. Timeframe or symbol change detection
   else if(id == CHARTEVENT_CHART_CHANGE)
   {
      if(_Symbol != g_last_symbol || _Period != g_last_period)
      {
         PrintFormat("[BRIDGE] Chart context changed: %s %s -> %s %s",
                     g_last_symbol, GetTimeframeName(g_last_period),
                     _Symbol, GetTimeframeName(_Period));
         g_last_symbol = _Symbol;
         g_last_period = _Period;

         if(g_auto_sync)
         {
            SendChartRequest("CHART_SYNC");
            g_status_msg = StringFormat("Auto-synced: %s %s", _Symbol, GetTimeframeName(_Period));
            g_status_color = clrSkyBlue;
            UpdateStatusLabel();
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Create on-chart UI buttons                                       |
//+------------------------------------------------------------------+
void CreateUIControls()
{
   int x = 20;
   int y = 30;

   // Button 1: Analyze
   CreateButton(BTN_ANALYZE, "🚀 ANALYZE MTF (A)", x, y, 160, 26, C'20,80,120', clrWhite);
   
   // Button 2: Clear
   CreateButton(BTN_CLEAR, "🧹 CLEAR (C)", x + 168, y, 110, 26, C'70,30,30', clrWhite);

   // Button 3: Auto-Sync
   CreateButton(BTN_SYNC, g_auto_sync ? "🔄 SYNC: ON" : "🔄 SYNC: OFF", x + 286, y, 120, 26, 
                g_auto_sync ? C'20,100,50' : C'90,40,40', clrWhite);

   // Status label
   CreateLabel(LBL_STATUS, g_status_msg, x, y + 32, g_status_color, 9);

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Destroy UI Controls                                              |
//+------------------------------------------------------------------+
void DestroyUIControls()
{
   ObjectDelete(0, BTN_ANALYZE);
   ObjectDelete(0, BTN_CLEAR);
   ObjectDelete(0, BTN_SYNC);
   ObjectDelete(0, LBL_STATUS);
}

//+------------------------------------------------------------------+
//| Create a single button object                                    |
//+------------------------------------------------------------------+
void CreateButton(string name, string text, int x, int y, int width, int height, color bg, color fg)
{
   ObjectDelete(0, name);
   if(ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0))
   {
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
      ObjectSetInteger(0, name, OBJPROP_XSIZE, width);
      ObjectSetInteger(0, name, OBJPROP_YSIZE, height);
      ObjectSetString(0, name, OBJPROP_TEXT, text);
      ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
      ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
      ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, clrDarkSlateGray);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
      ObjectSetString(0, name, OBJPROP_FONT, "Segoe UI");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
}

//+------------------------------------------------------------------+
//| Create a text label object                                       |
//+------------------------------------------------------------------+
void CreateLabel(string name, string text, int x, int y, color clr, int font_size)
{
   ObjectDelete(0, name);
   if(ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0))
   {
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
      ObjectSetString(0, name, OBJPROP_TEXT, text);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, font_size);
      ObjectSetString(0, name, OBJPROP_FONT, "Segoe UI");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
}

//+------------------------------------------------------------------+
//| Update Sync Button Appearance                                    |
//+------------------------------------------------------------------+
void UpdateSyncButton()
{
   ObjectSetString(0, BTN_SYNC, OBJPROP_TEXT, g_auto_sync ? "🔄 SYNC: ON" : "🔄 SYNC: OFF");
   ObjectSetInteger(0, BTN_SYNC, OBJPROP_BGCOLOR, g_auto_sync ? C'20,100,50' : C'90,40,40');
}

//+------------------------------------------------------------------+
//| Update Status Label text                                         |
//+------------------------------------------------------------------+
void UpdateStatusLabel()
{
   ObjectSetString(0, LBL_STATUS, OBJPROP_TEXT, g_status_msg);
   ObjectSetInteger(0, LBL_STATUS, OBJPROP_COLOR, g_status_color);
}

//+------------------------------------------------------------------+
//| Send Chart Request to Python Bridge via FILE_COMMON              |
//+------------------------------------------------------------------+
void SendChartRequest(string action)
{
   MqlTick last_tick;
   SymbolInfoTick(_Symbol, last_tick);

   int spread = (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   long chart_id = ChartID();

   string json = StringFormat(
      "{\n"
      "  \"chart_id\": %I64d,\n"
      "  \"symbol\": \"%s\",\n"
      "  \"period\": \"%s\",\n"
      "  \"period_minutes\": %d,\n"
      "  \"bid\": %.5f,\n"
      "  \"ask\": %.5f,\n"
      "  \"spread_points\": %d,\n"
      "  \"digits\": %d,\n"
      "  \"timestamp\": \"%s\",\n"
      "  \"action\": \"%s\",\n"
      "  \"auto_sync\": %s\n"
      "}",
      chart_id,
      _Symbol,
      GetTimeframeName(_Period),
      GetPeriodMinutes(_Period),
      last_tick.bid,
      last_tick.ask,
      spread,
      digits,
      TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
      action,
      g_auto_sync ? "true" : "false"
   );

   string file_name = StringFormat("agy_bridge\\inbox\\req_%I64d.json", chart_id);
   int handle = FileOpen(file_name, FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(handle != INVALID_HANDLE)
   {
      FileWriteString(handle, json);
      FileClose(handle);
      g_last_req_time = TimeCurrent();
      PrintFormat("[BRIDGE] Sent request [%s] for %s %s (Chart %I64d)",
                  action, _Symbol, GetTimeframeName(_Period), chart_id);
   }
   else
   {
      PrintFormat("[BRIDGE] Error writing request file: %d", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Check for incoming analytical responses                          |
//+------------------------------------------------------------------+
void CheckAnalysisResponse()
{
   long chart_id = ChartID();
   string specific_file = StringFormat("agy_bridge\\outbox\\analysis_%s_%I64d.json", _Symbol, chart_id);
   string generic_file  = StringFormat("agy_bridge\\outbox\\analysis_%s.json", _Symbol);

   string target_file = "";
   if(FileIsExist(specific_file, FILE_COMMON))
      target_file = specific_file;
   else if(FileIsExist(generic_file, FILE_COMMON))
      target_file = generic_file;

   if(target_file == "") return;

   int handle = FileOpen(target_file, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(handle == INVALID_HANDLE) return;

   string content = "";
   while(!FileIsEnding(handle))
   {
      content += FileReadString(handle) + "\n";
   }
   FileClose(handle);

   // Delete response file after consuming to prevent stale loops
   FileDelete(target_file, FILE_COMMON);

   if(StringLen(content) < 10) return;

   // Process response content
   ProcessAnalysisJson(content);
}

//+------------------------------------------------------------------+
//| Process and render analysis JSON payload                         |
//+------------------------------------------------------------------+
void ProcessAnalysisJson(const string &json)
{
   string overall_bias     = ExtractJsonString(json, "overall_bias");
   double bias_strength    = ExtractJsonDouble(json, "bias_strength");
   string candle_expect    = ExtractJsonString(json, "candle_expectation");

   // Parse Trade Plan sub-object
   int tp_pos = StringFind(json, "\"trade_plan\":");
   string plan_json = "";
   if(tp_pos >= 0)
   {
      int start_brace = StringFind(json, "{", tp_pos);
      int end_brace   = StringFind(json, "}", start_brace);
      if(start_brace >= 0 && end_brace > start_brace)
         plan_json = StringSubstr(json, start_brace, end_brace - start_brace + 1);
   }

   string dir      = ExtractJsonString(plan_json, "direction");
   string quality  = ExtractJsonString(plan_json, "setup_quality");
   double entry    = ExtractJsonDouble(plan_json, "entry_price");
   double sl       = ExtractJsonDouble(plan_json, "stop_loss");
   double tp1      = ExtractJsonDouble(plan_json, "take_profit_1");
   double tp2      = ExtractJsonDouble(plan_json, "take_profit_2");
   double lots     = ExtractJsonDouble(plan_json, "position_size_lots");
   double risk_usd = ExtractJsonDouble(plan_json, "monetary_risk_usd");
   double rr       = ExtractJsonDouble(plan_json, "risk_reward_tp1");
   bool   is_valid = ExtractJsonBool(plan_json, "is_valid");

   // Update HUD Status
   g_status_msg = StringFormat("Analysis Loaded: Bias %s (%.0f%%) | Quality: %s",
                               overall_bias, bias_strength * 100.0, (quality != "" ? quality : "N/A"));
   g_status_color = (overall_bias == "BULLISH") ? clrLimeGreen : 
                    ((overall_bias == "BEARISH") ? clrTomato : clrGold);
   UpdateStatusLabel();

   // Clear old visuals
   ClearVisualAnalysis();

   // Draw S/R levels
   if(InpDrawLevels)
      RenderLevelsFromJson(json);

   // Draw Supply/Demand zones
   if(InpDrawZones)
      RenderZonesFromJson(json);

   // Draw Trade Plan Blueprint lines
   if(InpDrawBlueprint && is_valid && dir != "NEUTRAL" && dir != "" && entry > 0.0)
   {
      DrawHLine(AGY_DRAW_PREFIX + "BP_ENTRY", entry, InpEntryColor, STYLE_SOLID, 2, 
                StringFormat("ENTRY (%s @ %.5f)", dir, entry));
      DrawHLine(AGY_DRAW_PREFIX + "BP_SL", sl, InpSLColor, STYLE_SOLID, 2, 
                StringFormat("STOP LOSS (%.5f)", sl));
      DrawHLine(AGY_DRAW_PREFIX + "BP_TP1", tp1, InpTPColor, STYLE_SOLID, 2, 
                StringFormat("TAKE PROFIT 1 (1:%.1f | %.5f)", rr, tp1));
      if(tp2 > 0.0)
      {
         DrawHLine(AGY_DRAW_PREFIX + "BP_TP2", tp2, clrMediumSeaGreen, STYLE_DOT, 1, 
                   StringFormat("TAKE PROFIT 2 (%.5f)", tp2));
      }
   }

   // Format Comprehensive On-Chart Comment HUD
   string hud = "====================================================================\n"
              + StringFormat("  [UNIVERSAL AI TRADING ANALYST - %s (%s)]\n", _Symbol, GetTimeframeName(_Period))
              + "====================================================================\n"
              + StringFormat("  OVERALL MTF BIAS : %s (Strength: %.0f%%)\n", overall_bias, bias_strength * 100.0)
              + StringFormat("  SETUP QUALITY    : %s\n", (quality != "" ? quality : "NO ACTIVE BLUEPRINT"))
              + StringFormat("  CANDLE EXP       : %s\n", candle_expect)
              + "--------------------------------------------------------------------\n";

   if(is_valid && dir != "NEUTRAL" && dir != "")
   {
      hud += StringFormat("  RECOMMENDED ACTION: [MANUAL] %s @ %.5f\n", dir, entry)
           + StringFormat("  STOP LOSS         : %.5f\n", sl)
           + StringFormat("  TAKE PROFIT 1     : %.5f (1:%.1f R:R)\n", tp1, rr)
           + StringFormat("  RECOMMENDED SIZE  : %.2f Lots (Risk: $%.2f)\n", lots, risk_usd);
   }
   else
   {
      hud += "  TRADE SETUP       : NO HIGH-PROBABILITY OPPORTUNITY (WAIT PATIENTLY)\n";
   }

   hud += "====================================================================\n"
        + "  [STRICT SAFETY NOTICE]\n"
        + "  The AI Analyst does NOT execute trades automatically.\n"
        + "  Trader retains 100% manual control over order entry and sizing in MT5.\n"
        + "====================================================================";

   Comment(hud);
   ChartRedraw(0);
   PlaySound("expert.wav");
}

//+------------------------------------------------------------------+
//| Extract and Render Support/Resistance Levels                     |
//+------------------------------------------------------------------+
void RenderLevelsFromJson(const string &json)
{
   int levels_pos = StringFind(json, "\"levels\":");
   if(levels_pos < 0) return;

   int array_start = StringFind(json, "[", levels_pos);
   int array_end   = StringFind(json, "]", array_start);
   if(array_start < 0 || array_end <= array_start) return;

   string array_str = StringSubstr(json, array_start, array_end - array_start + 1);

   int pos = 0;
   int idx = 0;
   while(pos < StringLen(array_str) && idx < 20)
   {
      int item_start = StringFind(array_str, "{", pos);
      if(item_start < 0) break;
      int item_end = StringFind(array_str, "}", item_start);
      if(item_end < 0) break;

      string item = StringSubstr(array_str, item_start, item_end - item_start + 1);
      double price = ExtractJsonDouble(item, "price");
      string type  = ExtractJsonString(item, "type");
      string tf    = ExtractJsonString(item, "timeframe");

      if(price > 0.0)
      {
         string name = StringFormat("%sSR_%d_%s", AGY_DRAW_PREFIX, idx, tf);
         color clr   = (type == "RESISTANCE") ? InpResistanceColor : InpSupportColor;
         string desc = StringFormat("%s %s @ %.5f", tf, type, price);
         DrawHLine(name, price, clr, STYLE_DASH, 1, desc);
         idx++;
      }
      pos = item_end + 1;
   }
}

//+------------------------------------------------------------------+
//| Extract and Render Supply/Demand Zones                           |
//+------------------------------------------------------------------+
void RenderZonesFromJson(const string &json)
{
   int zones_pos = StringFind(json, "\"zones\":");
   if(zones_pos < 0) return;

   int array_start = StringFind(json, "[", zones_pos);
   int array_end   = StringFind(json, "]", array_start);
   if(array_start < 0 || array_end <= array_start) return;

   string array_str = StringSubstr(json, array_start, array_end - array_start + 1);

   int pos = 0;
   int idx = 0;
   while(pos < StringLen(array_str) && idx < 15)
   {
      int item_start = StringFind(array_str, "{", pos);
      if(item_start < 0) break;
      int item_end = StringFind(array_str, "}", item_start);
      if(item_end < 0) break;

      string item  = StringSubstr(array_str, item_start, item_end - item_start + 1);
      string type  = ExtractJsonString(item, "type");
      double top   = ExtractJsonDouble(item, "top");
      double bot   = ExtractJsonDouble(item, "bottom");
      string tf    = ExtractJsonString(item, "timeframe");
      string state = ExtractJsonString(item, "state");

      if(top > bot && bot > 0.0)
      {
         string name = StringFormat("%sZONE_%d_%s", AGY_DRAW_PREFIX, idx, tf);
         color clr   = (type == "DEMAND") ? InpDemandColor : InpSupplyColor;
         DrawRectangleZone(name, top, bot, clr, StringFormat("%s %s (%s)", tf, type, state));
         idx++;
      }
      pos = item_end + 1;
   }
}

//+------------------------------------------------------------------+
//| Helper: Draw Horizontal Line on Chart                            |
//+------------------------------------------------------------------+
void DrawHLine(string name, double price, color clr, ENUM_LINE_STYLE style, int width, string desc)
{
   ObjectDelete(0, name);
   if(ObjectCreate(0, name, OBJ_HLINE, 0, 0, price))
   {
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, style);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
      ObjectSetString(0, name, OBJPROP_TEXT, desc);
      ObjectSetString(0, name, OBJPROP_TOOLTIP, desc);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
   }
}

//+------------------------------------------------------------------+
//| Helper: Draw Zone Rectangle on Chart                             |
//+------------------------------------------------------------------+
void DrawRectangleZone(string name, double top, double bot, color clr, string desc)
{
   ObjectDelete(0, name);
   datetime t_start = iTime(_Symbol, _Period, MathMin(iBars(_Symbol, _Period) - 1, 60));
   datetime t_end   = TimeCurrent() + (PeriodSeconds(_Period) * 30);

   if(ObjectCreate(0, name, OBJ_RECTANGLE, 0, t_start, top, t_end, bot))
   {
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_BGCOLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetString(0, name, OBJPROP_TEXT, desc);
      ObjectSetString(0, name, OBJPROP_TOOLTIP, desc);
   }
}

//+------------------------------------------------------------------+
//| Clear All Analysis Drawing Objects                               |
//+------------------------------------------------------------------+
void ClearVisualAnalysis()
{
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, AGY_DRAW_PREFIX) == 0)
      {
         ObjectDelete(0, name);
      }
   }
}
//+------------------------------------------------------------------+
