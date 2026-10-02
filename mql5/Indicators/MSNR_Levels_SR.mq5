//+------------------------------------------------------------------+
//|                                              MSNR_Levels_SR.mq5  |
//|                         Advanced MSNR - Indicator 1              |
//|         Support/Resistance levels from 2-candle pivots (close)   |
//+------------------------------------------------------------------+
//| Rules (Video 1):                                                  |
//|  Support    : bearish candle followed by bullish candle ("V").    |
//|               Line drawn at the CLOSE of the bearish candle.      |
//|  Resistance : bullish candle followed by bearish candle ("^").    |
//|               Line drawn at the CLOSE of the bullish candle.      |
//|  Gaps are ignored - always use the close of the first candle.     |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars     = 500;              // Lookback bars (level detection)
input int    InpMaxLevels        = 60;               // Max levels drawn (most recent)
input bool   InpShowLabels       = true;             // Show S/R text labels
input bool   InpShowBroken       = true;             // Show broken (closed-through) levels
input color  InpSupportColor     = clrDodgerBlue;    // Support color
input color  InpResistanceColor  = clrTomato;        // Resistance color
input color  InpBrokenColor      = clrGray;          // Broken level color
input int    InpLineWidth        = 1;                // Line width
input string InpPrefix           = "MSNR_SR_";       // Object name prefix

//--- level record
struct SLevel
  {
   double            price;        // level price (close of 1st candle)
   datetime          formed_time;  // time of the 2nd candle (when level confirms)
   datetime          broken_time;  // 0 = active
   bool              is_support;
   long              formed_index; // bar index (non-series) of 2nd candle
  };

SLevel g_levels[];

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR S/R Levels");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   DeleteAllObjects();
  }

//+------------------------------------------------------------------+
//|  candle color helpers (true series-indexed arrays)               |
//+------------------------------------------------------------------+
bool IsBull(const double &o[],const double &c[],int i) { return(c[i]>o[i]); }
bool IsBear(const double &o[],const double &c[],int i) { return(c[i]<o[i]); }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
//--- work in series indexing for clarity
   ArraySetAsSeries(open,true);
   ArraySetAsSeries(close,true);
   ArraySetAsSeries(time,true);

   static datetime last_bar_time=0;
   bool new_bar = (time[0]!=last_bar_time);
   if(rates_total<3) return(0);

//--- full rebuild only on new bar or first run (levels depend on history up to now)
   bool need_rebuild = (prev_calculated==0 || new_bar);
   if(!need_rebuild)
     {
      // still extend break check on every tick? Breaks confirmed on close only,
      // so nothing to do intra-bar. Just redraw timestamps.
      return(rates_total);
     }
   last_bar_time=time[0];

//--- scan candles: pair (i+1 = first candle, i = second/newer candle)
   ArrayResize(g_levels,0);
   int scan = MathMin(InpLookbackBars, rates_total-2);
   for(int i=scan; i>=1; i--)
     {
      bool bull1=IsBull(open,close,i+1), bear1=IsBear(open,close,i+1);
      bool bull2=IsBull(open,close,i),   bear2=IsBear(open,close,i);

      bool is_support    = (bear1 && bull2); // "V" dip
      bool is_resistance = (bull1 && bear2); // "^" peak
      if(!is_support && !is_resistance) continue;

      SLevel lv;
      lv.price        = close[i+1];           // close of the FIRST candle
      lv.formed_time  = time[i];              // confirmed when 2nd candle closes
      lv.formed_index = rates_total-1-i;      // non-series index
      lv.is_support   = is_support;
      lv.broken_time  = 0;
      AddLevel(lv);
     }

//--- determine broken status: a level is broken when a later candle CLOSES
//--- through it (body close), checked in chronological order
   int cnt=ArraySize(g_levels);
   for(int k=0;k<cnt;k++)
     {
      // walk forward in time from formation
      for(int i=(int)(rates_total-1-g_levels[k].formed_index)-1; i>=1; i--)
        {
         if(g_levels[k].is_support && close[i]<g_levels[k].price) // closed below support
           { g_levels[k].broken_time=time[i]; break; }
         if(!g_levels[k].is_support && close[i]>g_levels[k].price) // closed above resistance
           { g_levels[k].broken_time=time[i]; break; }
        }
     }

//--- draw
   DrawLevels();
   return(rates_total);
  }

//+------------------------------------------------------------------+
//| add level, keep list capped (most recent N)                      |
//+------------------------------------------------------------------+
void AddLevel(const SLevel &lv)
  {
   int n=ArraySize(g_levels);
//--- avoid duplicates (same price & type within a tiny tolerance = same level spam)
   for(int i=0;i<n;i++)
      if(g_levels[i].formed_time==lv.formed_time && g_levels[i].is_support==lv.is_support)
         return;
   ArrayResize(g_levels,n+1);
   g_levels[n]=lv;
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void DrawLevels()
  {
   DeleteAllObjects();

//--- most recent first for drawing cap
   int cnt=ArraySize(g_levels);
   int drawn=0;
   for(int k=cnt-1; k>=0 && drawn<InpMaxLevels; k--)
     {
      SLevel lv=g_levels[k];
      bool broken=(lv.broken_time>0);
      if(broken && !InpShowBroken) continue;

      color  clr   = broken ? InpBrokenColor : (lv.is_support ? InpSupportColor : InpResistanceColor);
      string tag   = lv.is_support ? "S" : "R";
      string name  = InpPrefix + tag + "_" + TimeToString(lv.formed_time,TIME_DATE|TIME_MINUTES);

      datetime t1  = lv.formed_time;
      datetime t2  = broken ? lv.broken_time : (TimeCurrent()+PeriodSeconds(PERIOD_CURRENT)*100); // ray into future

      ObjectCreate(0,name,OBJ_TREND,0,t1,lv.price,t2,lv.price);
      ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,name,OBJPROP_WIDTH,broken?1:InpLineWidth);
      ObjectSetInteger(0,name,OBJPROP_STYLE,broken?STYLE_DOT:STYLE_SOLID);
      ObjectSetInteger(0,name,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,name,OBJPROP_BACK,true);
      ObjectSetInteger(0,name,OBJPROP_SELECTABLE,true);
      ObjectSetString(0,name,OBJPROP_TOOLTIP,
         StringFormat("MSNR %s @ %s | formed %s%s",
            lv.is_support?"Support":"Resistance",
            DoubleToString(lv.price,_Digits),
            TimeToString(lv.formed_time),
            broken?" | broken "+TimeToString(lv.broken_time):""));

      if(InpShowLabels)
        {
         string lname=name+"_lbl";
         ObjectCreate(0,lname,OBJ_TEXT,0,t1,lv.price);
         ObjectSetString(0,lname,OBJPROP_TEXT,(broken?"x":"")+tag+" "+DoubleToString(lv.price,_Digits));
         ObjectSetInteger(0,lname,OBJPROP_COLOR,clr);
         ObjectSetInteger(0,lname,OBJPROP_FONTSIZE,8);
         ObjectSetInteger(0,lname,OBJPROP_ANCHOR,lv.is_support?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0,lname,OBJPROP_BACK,true);
        }
      drawn++;
     }
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,0,OBJ_TREND);
   ObjectsDeleteAll(0,InpPrefix+"*",0,OBJ_TEXT);
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
