//+------------------------------------------------------------------+
//|                                                  MSNR_Apex.mq5   |
//|                         Advanced MSNR - Indicator 5              |
//|         Apex / iAB structure mapping (closes only = line chart)  |
//+------------------------------------------------------------------+
//| Rules (Video 3):                                                  |
//|  Line-chart logic: ALL structure is computed on CLOSES only.      |
//|   Apex  : EXTERNAL swing point that led to a breakout of the      |
//|           previous structure (BOS on closes).                     |
//|   iAB   : INTERNAL swing (pullback inside the current trend leg)  |
//|           that leads to a breakout of an external Apex.           |
//|           iAB levels are valid strong S/R.                        |
//|  Internal swings that never cause a breakout = weak, ignored.     |
//|                                                                   |
//|  TF discipline: Apex/iAB are identified on D1 / W1 / MN only.     |
//|                                                                   |
//|  Mechanical model used here:                                      |
//|   - pivots on closes (strength bars each side), alternating       |
//|   - a BOS up = close above the active unbroken pivot high  ->     |
//|     that pivot high is "Apex Resistance" (AR); the pivot low      |
//|     that launched the breaking leg is "Apex Support" (AS) if the  |
//|     trend just flipped, or "iAB Support" (iABS) if we were        |
//|     already in an uptrend (internal retrace causing the break).   |
//|   - mirror for BOS down.                                          |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpPivotStrength  = 3;                  // Pivot strength (bars each side, closes)
input int    InpLookbackBars   = 2000;               // Lookback bars
input bool   InpHTFOnly        = true;               // Warn if attached below D1
input bool   InpShowPivots     = false;              // Debug: mark raw pivots
input int    InpMaxLevels      = 60;                 // Max structure levels drawn
input color  InpApexSupColor   = clrDodgerBlue;      // Apex Support
input color  InpApexResColor   = clrTomato;          // Apex Resistance
input color  InpIABSupColor    = clrMediumSeaGreen;  // iAB Support
input color  InpIABResColor    = clrDarkOrange;      // iAB Resistance
input int    InpLineWidth      = 2;                  // Line width
input string InpPrefix         = "MSNR_APX_";        // Object name prefix

//+------------------------------------------------------------------+
//| pivot record (chronological arrays)                              |
//+------------------------------------------------------------------+
struct SStructLevel
  {
   datetime time;
   double   price;
   string   tag;     // "AR","AS","iABR","iABS"
  };
SStructLevel g_struct[];

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Apex/iAB");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   Comment("");
   DeleteAllObjects();
  }

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
   if(rates_total < 2*InpPivotStrength+3) return(0);

   if(InpHTFOnly && Period()<PERIOD_D1)
     {
      Comment("MSNR Apex/iAB: attach to D1 / W1 / MN (Video 3: no Apex/OCL mapping below Daily).");
      DeleteAllObjects();
      return(rates_total);
     }
   Comment("");

   ArraySetAsSeries(close,true);
   ArraySetAsSeries(time,true);

   static datetime last_bar_time=0;
   bool new_bar=(time[0]!=last_bar_time);
   if(prev_calculated!=0 && !new_bar) return(rates_total);
   last_bar_time=time[0];

   int maxScan=MathMin(InpLookbackBars,rates_total-InpPivotStrength-1);

//--- 1) raw pivots on closes (series index i: pivot if strict extreme
//---    over InpPivotStrength bars each side)
   int    pType[];      // +1 high, -1 low
   double pPrice[];
   int    pIdx[];       // series index
   datetime pTime[];

   for(int i=maxScan; i>=InpPivotStrength; i--)
     {
      bool isHigh=true,isLow=true;
      for(int k=1;k<=InpPivotStrength;k++)
        {
         if(close[i]<=close[i+k] || close[i]<=close[i-k]) isHigh=false;
         if(close[i]>=close[i+k] || close[i]>=close[i-k]) isLow=false;
         if(!isHigh && !isLow) break;
        }
      if(!isHigh && !isLow) continue;

      int n=ArraySize(pType);
      ArrayResize(pType,n+1); ArrayResize(pPrice,n+1);
      ArrayResize(pIdx,n+1);  ArrayResize(pTime,n+1);
      pType[n]=isHigh?1:-1; pPrice[n]=close[i]; pIdx[n]=i; pTime[n]=time[i];
     }

//--- 2) enforce alternation (pIdx desc = chronological order built above;
//---    list built from old -> new already because i desc)
   int m=ArraySize(pType);
   for(int a=1;a<m;a++)
     {
      if(pType[a]==pType[a-1])
        {
         // same type twice in a row: keep the more extreme
         bool keepA=(pType[a]==1) ? (pPrice[a]>=pPrice[a-1]) : (pPrice[a]<=pPrice[a-1]);
         if(keepA) // replace previous with current
           {
            pPrice[a-1]=pPrice[a]; pIdx[a-1]=pIdx[a]; pTime[a-1]=pTime[a];
           }
         // delete current
         for(int b=a+1;b<m;b++)
           { pType[b-1]=pType[b]; pPrice[b-1]=pPrice[b]; pIdx[b-1]=pIdx[b]; pTime[b-1]=pTime[b]; }
         m--;
         a--;
        }
     }
   // resize to m
   ArrayResize(pType,m); ArrayResize(pPrice,m); ArrayResize(pIdx,m); ArrayResize(pTime,m);

//--- 3) chronological BOS walk (bar-by-bar, oldest -> newest)
   ArrayResize(g_struct,0);
   int trend=0;                          // +1 up, -1 down, 0 none
   bool   hasPH=false, hasPL=false;      // active unbroken pivot high/low known
   double phPrice=0,  plPrice=0;
   datetime phTime=0, plTime=0;
   double legOriginLow=0, legOriginHigh=0;  // last active opposite pivot (leg origin)
   datetime legOriginLowTime=0, legOriginHighTime=0;
   bool   hasOriginLow=false, hasOriginHigh=false;

   int    pNext=0;                       // next pivot to "confirm"
   for(int j=maxScan; j>=1; j--)
     {
      // pivots become confirmed InpPivotStrength bars after their extreme
      while(pNext<m && pIdx[pNext]-InpPivotStrength>=j)
        {
         if(pType[pNext]==1)
           { hasPH=true; phPrice=pPrice[pNext]; phTime=pTime[pNext];
             // this pivot high is also the potential origin of a future down-leg
             hasOriginHigh=true; legOriginHigh=pPrice[pNext]; legOriginHighTime=pTime[pNext];
           }
         else
           { hasPL=true; plPrice=pPrice[pNext]; plTime=pTime[pNext];
             hasOriginLow=true; legOriginLow=pPrice[pNext]; legOriginLowTime=pTime[pNext];
           }
         pNext++;
        }

      // BOS up: close breaks active pivot high
      if(hasPH && close[j]>phPrice)
        {
         AddStruct(phTime,phPrice,"AR");            // broken high = Apex Resistance
         if(hasOriginLow)
            AddStruct(legOriginLowTime,legOriginLow,(trend==1)?"iABS":"AS");
         trend=1;
         hasPH=false; hasOriginLow=false;  // consumed; wait for next pivot low
        }
      // BOS down
      else if(hasPL && close[j]<plPrice)
        {
         AddStruct(plTime,plPrice,"AS");            // broken low = Apex Support
         if(hasOriginHigh)
            AddStruct(legOriginHighTime,legOriginHigh,(trend==-1)?"iABR":"AR");
         trend=-1;
         hasPL=false; hasOriginHigh=false;
        }
     }

//--- 4) draw
   DrawAll(time[0]+PeriodSeconds(PERIOD_CURRENT)*100);

   if(InpShowPivots)
     {
      for(int a=0;a<m;a++)
        {
         string nm=InpPrefix+"pvt_"+IntegerToString(a);
         ObjectCreate(0,nm,OBJ_ARROW,0,pTime[a],pPrice[a]);
         ObjectSetInteger(0,nm,OBJPROP_ARROWCODE,pType[a]==1?108:108);
         ObjectSetInteger(0,nm,OBJPROP_COLOR,clrSilver);
         ObjectSetInteger(0,nm,OBJPROP_ANCHOR,pType[a]==1?ANCHOR_TOP:ANCHOR_BOTTOM);
        }
     }
   return(rates_total);
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void AddStruct(datetime t,double price,const string tag)
  {
//--- dedupe: same tag+time
   int n=ArraySize(g_struct);
   for(int i=0;i<n;i++)
      if(g_struct[i].time==t && g_struct[i].tag==tag) return;
   ArrayResize(g_struct,n+1);
   g_struct[n].time=t; g_struct[n].price=price; g_struct[n].tag=tag;
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
color TagColor(const string tag)
  {
   if(tag=="AS")   return InpApexSupColor;
   if(tag=="AR")   return InpApexResColor;
   if(tag=="iABS") return InpIABSupColor;
   if(tag=="iABR") return InpIABResColor;
   return clrGray;
  }

void DrawAll(datetime future_time)
  {
   DeleteAllObjects();
   int cnt=ArraySize(g_struct);
   int drawn=0;
   for(int k=cnt-1;k>=0 && drawn<InpMaxLevels;k--)
     {
      string tag=g_struct[k].tag;
      datetime t1=g_struct[k].time;
      double   pr=g_struct[k].price;
      color    clr=TagColor(tag);
      string   nm=InpPrefix+tag+"_"+TimeToString(t1,TIME_DATE);

      ObjectCreate(0,nm,OBJ_TREND,0,t1,pr,future_time,pr);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,InpLineWidth);
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("MSNR %s @ %s | formed %s",tag,DoubleToString(pr,_Digits),TimeToString(t1)));

      string lname=nm+"_lbl";
      ObjectCreate(0,lname,OBJ_TEXT,0,t1,pr);
      ObjectSetString(0,lname,OBJPROP_TEXT,tag+" "+DoubleToString(pr,_Digits));
      ObjectSetInteger(0,lname,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,lname,OBJPROP_FONTSIZE,8);
      bool upper=(tag=="AR"||tag=="iABR");
      ObjectSetInteger(0,lname,OBJPROP_ANCHOR,upper?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER);
      drawn++;
     }
   ChartRedraw();
  }

void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
