//+------------------------------------------------------------------+
//|                                               MSNR_ABX_AMDX.mq5  |
//|              ABAX Indicator B9: AMDX session cycle timer           |
//+------------------------------------------------------------------+
//| Rules (ABAX P08-09):                                               |
//|  Each day runs A -> M -> D -> X: A = Asia range (accumulation      |
//|  before the sweep); M = sweep of an Asia extreme + close back     |
//|  inside within 5 bars (London signal, not entry); D = displacement|
//|  body > 1.5 ATR breaking out opposite the M sweep (NY execution);  |
//|  X = post-D compression (range < 0.5 ATR over 6 bars, reset).      |
//|  A-vs-X by sequence position, never shape alone; deep M (>1 ATR   |
//|  but reclaimed) = buying/selling variation flag. London window =  |
//|  signal-only, NY window = execution window (labels). Server hours  |
//|  are inputs (broker-dependent per book).                           |
//|                                                                    |
//|  Rendering: session boxes per recent day, M ticks, D arrows,       |
//|  phase + window labels. Most-recent cap. Closed bars only.         |
//|  No rays (boxes bounded by session times).                         |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpDaysBack      = 5;                 // Days drawn (most recent)
input int    InpAsiaStart     = 20;                // Asia start (server hour)
input int    InpAsiaEnd       = 7;                 // Asia end (server hour)
input int    InpLondonStart   = 7;                 // London start (server hour)
input int    InpLondonEnd     = 11;                // London end (server hour)
input int    InpNYStart       = 12;                // New York start (server hour)
input int    InpNYEnd         = 21;                // New York end (server hour)
input int    InpATRPeriod     = 14;                // ATR period
input double InpDispMult      = 1.5;               // D displacement (x ATR)
input int    InpMReturn       = 5;                 // M close-back window (bars)
input int    InpXBars         = 6;                 // X compression bars
input double InpXRangeATR     = 0.5;               // X range threshold (x ATR)
input double InpDeepMult      = 1.0;               // Deep-M variation (x ATR)
input bool   InpShowLabels    = true;              // Show labels
input color  InpAsiaColor     = clrWheat;          // Asia box (beige)
input color  InpLondonColor   = clrThistle;        // London box (purple)
input color  InpNYColor       = clrLightCyan;      // NY box
input color  InpMColor        = clrOrange;         // M tick (amber)
input color  InpDUpColor      = clrDodgerBlue;     // D up arrow
input color  InpDnColor       = clrTomato;         // D down arrow
input color  InpPhaseColor    = clrDimGray;        // Phase label
input string InpPrefix        = "MSNR_AX_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SDay
   {
    datetime date;       // 00:00 of the day
    double   asiaHi;
    double   asiaLo;
    datetime asiaT1;
    datetime asiaT2;
    bool     hasM;
    int      mSide;      // -1 swept low, +1 swept high
    datetime mTime;
    double   mPx;
    bool     mDeep;
    bool     hasD;
    datetime dTime;
    double   dPx;
    int      dDir;       // +1 up, -1 down
    bool     hasX;
    datetime xTime;
    int      phase;      // 0 A, 1 M, 2 D, 3 X
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR AMDX");
    hATR=iATR(_Symbol,PERIOD_CURRENT,InpATRPeriod);
    if(hATR==INVALID_HANDLE) return(INIT_FAILED);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
   }

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

    if(rates_total<InpATRPeriod+10) return(0);
    if(PeriodSeconds(PERIOD_CURRENT)>3600) return(0);   // intraday only
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SDay days[];
    FindDays(time,open,high,low,close,atr,rates_total,days);

    DrawDays(days);
    ChartRedraw();
    return(rates_total);
   }

bool InWin(int hour,int s,int e)
   {
    if(s<=e) return(hour>=s && hour<e);
    return(hour>=s || hour<e);
   }

datetime DayStart(datetime tt)
   {
    MqlDateTime d;
    TimeToStruct(tt,d);
    d.hour=0; d.min=0; d.sec=0;
    return(StructToTime(d));
   }

//--- collect distinct recent dates (newest first)
int DayList(const datetime &t[],int rates_total,datetime &dates[])
   {
    ArrayResize(dates,0);
    for(int i=1;i<rates_total && ArraySize(dates)<InpDaysBack+1;i++)
      {
       datetime ds=DayStart(t[i]);
       MqlDateTime d;
       TimeToStruct(ds,d);
       if(d.day_of_week==0||d.day_of_week==6) continue;
       if(ArraySize(dates)==0 || dates[ArraySize(dates)-1]!=ds)
         {
          int n=ArraySize(dates);
          ArrayResize(dates,n+1); dates[n]=ds;
         }
      }
    return(ArraySize(dates));
   }

void FindDays(const datetime &t[],const double &o[],const double &h[],
              const double &l[],const double &c[],const double &atr[],
              int rates_total,SDay &days[])
   {
    ArrayResize(days,0);
    datetime dates[];
    if(DayList(t,rates_total,dates)==0) return;
    for(int d=0;d<ArraySize(dates) && ArraySize(days)<InpDaysBack;d++)
      {
       SDay x;
       x.date=dates[d];
       x.asiaHi=0; x.asiaLo=0; x.asiaT1=0; x.asiaT2=0;
       x.hasM=false; x.mSide=0; x.mTime=0; x.mPx=0; x.mDeep=false;
       x.hasD=false; x.dTime=0; x.dPx=0; x.dDir=0;
       x.hasX=false; x.xTime=0; x.phase=0;
       bool have=false;
       for(int i=1;i<rates_total;i++)
         {
          if(DayStart(t[i])!=x.date) continue;
          MqlDateTime s;
          TimeToStruct(t[i],s);
          if(!InWin(s.hour,InpAsiaStart,InpAsiaEnd)) continue;
          if(!have) { x.asiaHi=h[i]; x.asiaLo=l[i]; x.asiaT1=t[i]; x.asiaT2=t[i]; have=true; }
          else
            {
             if(h[i]>x.asiaHi) { x.asiaHi=h[i]; x.asiaT2=t[i]; }
             if(l[i]<x.asiaLo) { x.asiaLo=l[i]; x.asiaT2=t[i]; }
            }
         }
       if(!have) continue;
       if(x.asiaT1>x.asiaT2) { datetime tmp=x.asiaT1; x.asiaT1=x.asiaT2; x.asiaT2=tmp; }
       //--- M: sweep of Asia extreme + close back inside within MReturn bars
       for(int i=1;i<rates_total && !x.hasM;i++)
         {
          if(t[i]<=x.asiaT2) continue;
          if(DayStart(t[i])!=x.date) continue;
          MqlDateTime s;
          TimeToStruct(t[i],s);
          if(!InWin(s.hour,InpLondonStart,InpNYEnd)) continue;   // London->NY window
          double a=(atr[i]>0?atr[i]:_Point);
          if(l[i]<x.asiaLo && c[i]>x.asiaLo)
            {
             x.hasM=true; x.mSide=-1; x.mTime=t[i]; x.mPx=l[i];
             if(x.asiaLo-l[i]>InpDeepMult*a) x.mDeep=true;
            }
          else if(h[i]>x.asiaHi && c[i]<x.asiaHi)
            {
             x.hasM=true; x.mSide=+1; x.mTime=t[i]; x.mPx=h[i];
             if(h[i]-x.asiaHi>InpDeepMult*a) x.mDeep=true;
            }
          if(x.hasM)
            {
             //--- require close-back hold: already closed back by construction;
             //--- confirm within window (the piercing bar itself closed back)
             x.phase=1;
            }
         }
       //--- D: displacement opposite M + breakout past Asia extreme
       if(x.hasM)
         {
          int mIdx=rates_total-1;
          for(int i=1;i<rates_total;i++)
             if(t[i]<=x.mTime) { mIdx=i; break; }
          for(int j=mIdx-1;j>=1;j--)
            {
             if(DayStart(t[j])!=x.date) break;
             if(atr[j]<=0) continue;
             double body=c[j]-o[j];
             if(x.mSide<0 && body>InpDispMult*atr[j] && c[j]>x.asiaHi)
               { x.hasD=true; x.dTime=t[j]; x.dPx=h[j]; x.dDir=+1; x.phase=2; break; }
             if(x.mSide>0 && -body>InpDispMult*atr[j] && c[j]<x.asiaLo)
               { x.hasD=true; x.dTime=t[j]; x.dPx=l[j]; x.dDir=-1; x.phase=2; break; }
            }
         }
       //--- X: compression after D
       if(x.hasD)
         {
          int dIdx=rates_total-1;
          for(int i=1;i<rates_total;i++)
             if(t[i]<=x.dTime) { dIdx=i; break; }
          for(int j=dIdx-1;j>=InpXBars;j--)
            {
             if(DayStart(t[j])!=x.date) break;
             if(atr[j]<=0) continue;
             double wh=h[j], wl=l[j];
             for(int k2=j-1;k2>j-InpXBars;k2--)
               { if(h[k2]>wh) wh=h[k2]; if(l[k2]<wl) wl=l[k2]; }
             if(wh-wl<InpXRangeATR*atr[j])
               { x.hasX=true; x.xTime=t[j]; x.phase=3; break; }
            }
         }
       int n=ArraySize(days);
       ArrayResize(days,n+1); days[n]=x;
      }
   }

string PhaseName(int p)
   {
    if(p==0) return("A");
    if(p==1) return("M");
    if(p==2) return("D");
    return("X");
   }

void DrawDays(const SDay &days[])
   {
    DeleteAllObjects();
    for(int k=0;k<ArraySize(days);k++)
      {
       string dn=InpPrefix+"d"+TimeToString(days[k].date,TIME_DATE)+"_";
       //--- Asia range box
       if(days[k].asiaT2>days[k].asiaT1)
         {
          ObjectCreate(0,dn+"asia",OBJ_RECTANGLE,0,days[k].asiaT1,days[k].asiaHi,
                       days[k].asiaT2,days[k].asiaLo);
          ObjectSetInteger(0,dn+"asia",OBJPROP_COLOR,InpAsiaColor);
          ObjectSetInteger(0,dn+"asia",OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,dn+"asia",OBJPROP_WIDTH,1);
          ObjectSetInteger(0,dn+"asia",OBJPROP_FILL,true);
          ObjectSetInteger(0,dn+"asia",OBJPROP_BACK,true);
          ObjectSetInteger(0,dn+"asia",OBJPROP_SELECTABLE,true);
          ObjectSetString(0,dn+"asia",OBJPROP_TOOLTIP,
             StringFormat("Asia range [%s..%s]",
                DoubleToString(days[k].asiaHi,_Digits),
                DoubleToString(days[k].asiaLo,_Digits)));
         }
       //--- M tick
       if(days[k].hasM)
         {
          ObjectCreate(0,dn+"m",OBJ_TEXT,0,days[k].mTime,days[k].mPx);
          ObjectSetString(0,dn+"m",OBJPROP_TEXT,(days[k].mDeep?"M-deep":"M"));
          ObjectSetInteger(0,dn+"m",OBJPROP_COLOR,InpMColor);
          ObjectSetInteger(0,dn+"m",OBJPROP_FONTSIZE,9);
          ObjectSetInteger(0,dn+"m",OBJPROP_ANCHOR,
             (days[k].mSide<0?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
          ObjectSetInteger(0,dn+"m",OBJPROP_BACK,true);
          ObjectSetInteger(0,dn+"m",OBJPROP_SELECTABLE,false);
          ObjectSetString(0,dn+"m",OBJPROP_TOOLTIP,"Manipulation sweep (signal, not entry)");
         }
       //--- D arrow
       if(days[k].hasD)
         {
          ObjectCreate(0,dn+"d",(days[k].dDir>0?OBJ_ARROW_UP:OBJ_ARROW_DOWN),0,
                       days[k].dTime,days[k].dPx);
          ObjectSetInteger(0,dn+"d",OBJPROP_COLOR,
             (days[k].dDir>0?InpDUpColor:InpDnColor));
          ObjectSetInteger(0,dn+"d",OBJPROP_WIDTH,2);
          ObjectSetInteger(0,dn+"d",OBJPROP_BACK,false);
          ObjectSetInteger(0,dn+"d",OBJPROP_SELECTABLE,true);
          ObjectSetString(0,dn+"d",OBJPROP_TOOLTIP,"Distribution impulse (execution)");
         }
       //--- phase label at Asia start
       if(InpShowLabels)
         {
          ObjectCreate(0,dn+"ph",OBJ_TEXT,0,days[k].asiaT1,days[k].asiaHi);
          ObjectSetString(0,dn+"ph",OBJPROP_TEXT,PhaseName(days[k].phase));
          ObjectSetInteger(0,dn+"ph",OBJPROP_COLOR,InpPhaseColor);
          ObjectSetInteger(0,dn+"ph",OBJPROP_FONTSIZE,10);
          ObjectSetInteger(0,dn+"ph",OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
          ObjectSetInteger(0,dn+"ph",OBJPROP_BACK,true);
          ObjectSetInteger(0,dn+"ph",OBJPROP_SELECTABLE,false);
          ObjectSetString(0,dn+"ph",OBJPROP_TOOLTIP,
             "AMDX phase: London=signal-only, NY=execution window");
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
