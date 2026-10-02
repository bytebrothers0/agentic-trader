//+------------------------------------------------------------------+
//|                                           MSNR_ABX_HiddenBase.mq5 |
//|              ABAX Indicator B6: HTF twins + LTF hidden-base probe  |
//+------------------------------------------------------------------+
//| Rules (ABAX P04-05):                                               |
//|  Twins: two same-color candles with clustered opens/closes        |
//|  (|Δclose|,|Δopen| < 0.3 ATR, bodies within 20%) - the HTF pause   |
//|  that hides LTF content. On birth, CopyRates-drill the twin       |
//|  window on the probe TF for: OB (displacement origin), V-shape    |
//|  reclaim, accumulation compression, sweep, FVG gap, volume spike.  |
//|  SubScore = flag count; ≥2 -> tradable base box [twin low..high]; |
//|  else HOLLOW watch-only label. Never enter on twins alone.        |
//|                                                                    |
//|  Rendering: twin boxes + BASE/HOLLOW labels, flag list in         |
//|  tooltips. Most-recent cap. Closed bars only. No rays.            |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 200;               // Twin-scan bars (chart TF)
input ENUM_TIMEFRAMES InpProbeTF = PERIOD_M15;     // LTF probe timeframe
input int    InpATRPeriod     = 14;                // ATR period
input double InpTwinTolATR    = 0.3;               // Twin open/close cluster (x ATR)
input double InpBodyTolPct    = 20.0;              // Twin body similarity (%)
input double InpDispMult      = 1.5;               // Probe displacement (x probe ATR)
input int    InpMinBase       = 6;                 // Min probe bars = accumulation
input int    InpMinScore      = 2;                 // SubScore to trade
input int    InpMaxBases      = 20;                // Max bases drawn (most recent)
input bool   InpShowLabels    = true;              // Show labels
input color  InpBaseColor     = clrLightSkyBlue;   // Tradable base box
input color  InpBaseTxt       = clrDodgerBlue;     // Base label
input color  InpHollowColor   = clrGray;           // Hollow twin label
input string InpPrefix        = "MSNR_HB_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SBase
   {
    datetime t1;
    datetime t2;
    double   top;
    double   bottom;
    bool     tradable;
    int      score;
    string   flags;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR HiddenBase");
    hATR=iATR(_Symbol,PERIOD_CURRENT,InpATRPeriod);
    if(hATR==INVALID_HANDLE) return(INIT_FAILED);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
   }

bool IsBullC(const double &o[],const double &c[],int i) { return(c[i]>o[i]); }
bool IsBearC(const double &o[],const double &c[],int i) { return(c[i]<o[i]); }

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
    ArraySetAsSeries(open,true); ArraySetAsSeries(high,true);
    ArraySetAsSeries(low,true);  ArraySetAsSeries(close,true);
    ArraySetAsSeries(time,true);

    if(rates_total<InpLookbackBars+InpATRPeriod+3) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SBase bb[];
    FindBases(time,open,high,low,close,atr,rates_total,bb);

    DrawBases(bb,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- probe the twin window on the LTF; returns flag string + score
int ProbeWindow(datetime w1,datetime w2,string &flags)
   {
    flags="";
    MqlRates r[];
    int got=CopyRates(_Symbol,InpProbeTF,w1,w2,r);
    if(got<InpMinBase) return(-1);   // no sync / too few bars
    int n=got;
    double pa=0;
    for(int i=0;i<n;i++) pa+=r[i].high-r[i].low;
    pa/=(double)n;
    if(pa<=0) return(-1);
    int score=0;
    //--- OB: displacement bar with opposite-color predecessor
    bool hasOB=false;
    for(int i=1;i<n;i++)
      {
       double b1=r[i-1].close-r[i-1].open, b0=r[i].close-r[i].open;
       if(MathAbs(b1)>=InpDispMult*pa && ((b1>0 && b0<0)||(b1<0 && b0>0)))
         { hasOB=true; break; }
      }
    if(hasOB) { score++; flags+="OB "; }
    //--- V-shape: probe low pivot + reclaim close above within 5 bars
    bool hasV=false;
    for(int i=2;i<n-2 && !hasV;i++)
      {
       if(r[i].low<r[i-1].low && r[i].low<r[i-2].low &&
          r[i].low<r[i+1].low && r[i].low<r[i+2].low)
         {
          for(int k=i-1;k>=MathMax(i-5,0);k--)
             if(r[k].close>r[i].high) { hasV=true; break; }
         }
      }
    if(hasV) { score++; flags+="V "; }
    //--- accumulation: window range < 0.5 chart-ATR-equivalent (probe ATR)
    double wh=0, wl=0;
    for(int i=0;i<n;i++)
      { if(i==0||r[i].high>wh) wh=r[i].high; if(i==0||r[i].low<wl) wl=r[i].low; }
    if(wh-wl<2.0*pa && n>=InpMinBase) { score++; flags+="ACC "; }
    //--- sweep: probe swing pierced + closed back
    bool hasSw=false;
    for(int i=3;i<n && !hasSw;i++)
      {
       if(r[i].high>r[i-1].high && r[i].high>r[i-2].high && r[i].high>r[i-3].high &&
          r[i].close<r[i-1].high) hasSw=true;
       if(r[i].low<r[i-1].low && r[i].low<r[i-2].low && r[i].low<r[i-3].low &&
          r[i].close>r[i-1].low) hasSw=true;
      }
    if(hasSw) { score++; flags+="SW "; }
    //--- FVG gap on probe bars
    bool hasFVG=false;
    for(int i=2;i<n && !hasFVG;i++)
      {
       if(r[i].low>r[i-2].high || r[i].high<r[i-2].low) hasFVG=true;
      }
    if(hasFVG) { score++; flags+="FVG "; }
    //--- volume spike: max tick_volume > 1.5x mean
    double vm=0, vx=0;
    for(int i=0;i<n;i++) { vm+=(double)r[i].tick_volume; if(r[i].tick_volume>vx) vx=(double)r[i].tick_volume; }
    vm/=(double)n;
    if(vm>0 && vx>1.5*vm) { score++; flags+="VOL "; }
    return(score);
   }

void FindBases(const datetime &t[],const double &o[],const double &h[],
               const double &l[],const double &c[],const double &atr[],
               int rates_total,SBase &bb[])
   {
    ArrayResize(bb,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bu=IsBullC(o,c,i)&&IsBullC(o,c,i+1);
       bool be=IsBearC(o,c,i)&&IsBearC(o,c,i+1);
       if(!bu && !be) continue;
       if(atr[i]<=0) continue;
       double tol=InpTwinTolATR*atr[i];
       if(MathAbs(c[i]-c[i+1])>tol) continue;
       if(MathAbs(o[i]-o[i+1])>tol) continue;
       double b0=MathAbs(c[i]-o[i]), b1=MathAbs(c[i+1]-o[i+1]);
       double mx=MathMax(b0,b1);
       if(mx>0 && MathAbs(b0-b1)/mx*100.0>InpBodyTolPct) continue;
       string flags="";
       int score=ProbeWindow(t[i+1],t[i]+PeriodSeconds(PERIOD_CURRENT),flags);
       if(score<0) continue;   // no LTF sync
       SBase x;
       x.t1=t[i+1]; x.t2=t[i]+PeriodSeconds(PERIOD_CURRENT);
       x.top=MathMax(h[i],h[i+1]); x.bottom=MathMin(l[i],l[i+1]);
       x.score=score; x.flags=flags;
       x.tradable=(score>=InpMinScore);
       int n=ArraySize(bb);
       ArrayResize(bb,n+1); bb[n]=x;
      }
   }

void DrawBases(const SBase &bb[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(bb);
    int start=(n>InpMaxBases)?n-InpMaxBases:0;
    for(int k=start;k<n;k++)
      {
       string nm=InpPrefix+(bb[k].tradable?"base_":"hollow_")+
                 TimeToString(bb[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       if(bb[k].tradable)
         {
          ObjectCreate(0,nm,OBJ_RECTANGLE,0,bb[k].t1,bb[k].top,now,bb[k].bottom);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,InpBaseColor);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_FILL,true);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
         }
       else
         {
          if(!InpShowLabels) continue;
          nm+="_t";
          ObjectCreate(0,nm,OBJ_TEXT,0,bb[k].t1,bb[k].top);
          ObjectSetString(0,nm,OBJPROP_TEXT,"HOLLOW");
          ObjectSetInteger(0,nm,OBJPROP_COLOR,InpHollowColor);
          ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,nm,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
         }
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("Hidden base %s | twin %s -> %s | LTF[%s] score %d/6 [%s]",
             bb[k].tradable?"TRADABLE":"HOLLOW",
             TimeToString(bb[k].t1),TimeToString(bb[k].t2),
             EnumToString(InpProbeTF),bb[k].score,bb[k].flags));
       if(InpShowLabels && bb[k].tradable)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,bb[k].t1,bb[k].bottom);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             StringFormat("BASE S%d",bb[k].score));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,InpBaseTxt);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,ANCHOR_LEFT_UPPER);
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
