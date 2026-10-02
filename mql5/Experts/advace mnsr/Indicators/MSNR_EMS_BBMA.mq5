//+------------------------------------------------------------------+
//|                                                MSNR_EMS_BBMA.mq5 |
//|              EMS Indicator E8: BBMA overlay + re-entry            |
//+------------------------------------------------------------------+
//| Settings straight from EMS#ENGULFING #MSNR#SMC#_8:19-26:           |
//|  BB(20, 2.0, Close) + EMA 50 (Close) + LWMA 5 High/Low + LWMA 10  |
//|  High/Low. All shift 0, drawn as overlay lines (plot buffers).    |
//|                                                                    |
//|  Momentum candle (_8:28, #4:22-25, _6:33-35): a strong-body candle |
//|  piercing OUT of the MA5/10 band - open at/inside the band, bull   |
//|  close above band top (max of MA5H/MA10H), bear close below band   |
//|  bottom. Marked with a small triangle.                             |
//|                                                                    |
//|  BBMA re-entry: within InpMaxWaitBars after a momentum candle, a   |
//|  rejection bar that dips back INTO the band but closes back out    |
//|  in the momentum direction (bull: low < bandTop, close > bandTop;  |
//|  bear mirror). Drawn with a big arrow + "BBMA re-entry" label -    |
//|  the LTF confirmation trigger from _6:33-35.                       |
//|                                                                    |
//|  Closed bars only for signals. Lines update live, markers per bar. |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_buffers 8
#property indicator_plots 8

//--- plot declarations (colors overridden from inputs in OnInit)
#property indicator_label1 "BB Up"
#property indicator_type1  DRAW_LINE
#property indicator_style1 STYLE_SOLID
#property indicator_width1 1
#property indicator_label2 "BB Mid"
#property indicator_type2  DRAW_LINE
#property indicator_style2 STYLE_DOT
#property indicator_width2 1
#property indicator_label3 "BB Low"
#property indicator_type3  DRAW_LINE
#property indicator_style3 STYLE_SOLID
#property indicator_width3 1
#property indicator_label4 "EMA 50"
#property indicator_type4  DRAW_LINE
#property indicator_style4 STYLE_SOLID
#property indicator_width4 2
#property indicator_label5 "MA 5 H"
#property indicator_type5  DRAW_LINE
#property indicator_style5 STYLE_SOLID
#property indicator_width5 1
#property indicator_label6 "MA 5 L"
#property indicator_type6  DRAW_LINE
#property indicator_style6 STYLE_SOLID
#property indicator_width6 1
#property indicator_label7 "MA 10 H"
#property indicator_type7  DRAW_LINE
#property indicator_style7 STYLE_DASH
#property indicator_width7 1
#property indicator_label8 "MA 10 L"
#property indicator_type8  DRAW_LINE
#property indicator_style8 STYLE_DASH
#property indicator_width8 1

//--- inputs (BBMA settings per _8.md - change only to experiment)
input int    InpBBPeriod     = 20;                // BB period
input double InpBBDev        = 2.0;               // BB deviation
input int    InpEMA50Period  = 50;                // EMA period
input int    InpMA5Period    = 5;                 // MA5 period (LWMA H/L)
input int    InpMA10Period   = 10;                // MA10 period (LWMA H/L)
//--- inputs (signals)
input int    InpLookbackBars = 500;               // Lookback bars (signals)
input int    InpMaxMarks     = 50;                // Max momentum marks (most recent)
input int    InpMaxReentry   = 50;                // Max re-entry arrows (most recent)
input double InpMinBodyPct   = 50.0;              // Min body % of range for momentum
input int    InpMaxWaitBars  = 20;                // Bars momentum stays valid for re-entry
input double InpArrowGapPips = 3.0;               // Arrow gap from candle extreme (pips)
input bool   InpShowMomentum = true;              // Mark momentum candles
input bool   InpShowReentry  = true;              // Draw re-entry arrows + labels
//--- inputs (colors)
input color  InpColBB        = clrSilver;         // BB upper/lower
input color  InpColBBMid     = clrDarkGray;       // BB basis
input color  InpColEMA50     = clrGoldenrod;      // EMA 50
input color  InpColMA5       = clrDodgerBlue;     // MA 5 H/L
input color  InpColMA10      = clrMediumVioletRed;// MA 10 H/L
input color  InpBullColor    = clrDodgerBlue;     // Bull signal
input color  InpBearColor    = clrTomato;         // Bear signal
input string InpPrefix       = "MSNR_BBMA_";      // Object name prefix

//--- line buffers
double BufBBUp[], BufBBMid[], BufBBLo[], BufEMA50[];
double Buf5H[], Buf5L[], Buf10H[], Buf10L[];

//--- handles
int hBB=INVALID_HANDLE, hEMA50=INVALID_HANDLE;
int h5H=INVALID_HANDLE, h5L=INVALID_HANDLE;
int h10H=INVALID_HANDLE, h10L=INVALID_HANDLE;

struct SSig
   {
    datetime time;
    double   px;      // anchor price (extreme +/- gap)
    bool     bull;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR BBMA");
    hBB   =iBands(_Symbol,PERIOD_CURRENT,InpBBPeriod,0,InpBBDev,PRICE_CLOSE);
    hEMA50=iMA(_Symbol,PERIOD_CURRENT,InpEMA50Period,0,MODE_EMA,PRICE_CLOSE);
    h5H   =iMA(_Symbol,PERIOD_CURRENT,InpMA5Period,0,MODE_LWMA,PRICE_HIGH);
    h5L   =iMA(_Symbol,PERIOD_CURRENT,InpMA5Period,0,MODE_LWMA,PRICE_LOW);
    h10H  =iMA(_Symbol,PERIOD_CURRENT,InpMA10Period,0,MODE_LWMA,PRICE_HIGH);
    h10L  =iMA(_Symbol,PERIOD_CURRENT,InpMA10Period,0,MODE_LWMA,PRICE_LOW);
    if(hBB==INVALID_HANDLE||hEMA50==INVALID_HANDLE||h5H==INVALID_HANDLE||
       h5L==INVALID_HANDLE||h10H==INVALID_HANDLE||h10L==INVALID_HANDLE)
       return(INIT_FAILED);

    SetIndexBuffer(0,BufBBUp,INDICATOR_DATA);  ArraySetAsSeries(BufBBUp,true);
    SetIndexBuffer(1,BufBBMid,INDICATOR_DATA); ArraySetAsSeries(BufBBMid,true);
    SetIndexBuffer(2,BufBBLo,INDICATOR_DATA);  ArraySetAsSeries(BufBBLo,true);
    SetIndexBuffer(3,BufEMA50,INDICATOR_DATA); ArraySetAsSeries(BufEMA50,true);
    SetIndexBuffer(4,Buf5H,INDICATOR_DATA);    ArraySetAsSeries(Buf5H,true);
    SetIndexBuffer(5,Buf5L,INDICATOR_DATA);    ArraySetAsSeries(Buf5L,true);
    SetIndexBuffer(6,Buf10H,INDICATOR_DATA);   ArraySetAsSeries(Buf10H,true);
    SetIndexBuffer(7,Buf10L,INDICATOR_DATA);   ArraySetAsSeries(Buf10L,true);

    PlotIndexSetInteger(0,PLOT_LINE_COLOR,InpColBB);
    PlotIndexSetInteger(1,PLOT_LINE_COLOR,InpColBBMid);
    PlotIndexSetInteger(2,PLOT_LINE_COLOR,InpColBB);
    PlotIndexSetInteger(3,PLOT_LINE_COLOR,InpColEMA50);
    PlotIndexSetInteger(4,PLOT_LINE_COLOR,InpColMA5);
    PlotIndexSetInteger(5,PLOT_LINE_COLOR,InpColMA5);
    PlotIndexSetInteger(6,PLOT_LINE_COLOR,InpColMA10);
    PlotIndexSetInteger(7,PLOT_LINE_COLOR,InpColMA10);
    PlotIndexSetInteger(0,PLOT_DRAW_BEGIN,InpBBPeriod);
    PlotIndexSetInteger(1,PLOT_DRAW_BEGIN,InpBBPeriod);
    PlotIndexSetInteger(2,PLOT_DRAW_BEGIN,InpBBPeriod);
    PlotIndexSetInteger(3,PLOT_DRAW_BEGIN,InpEMA50Period);
    PlotIndexSetInteger(4,PLOT_DRAW_BEGIN,InpMA5Period);
    PlotIndexSetInteger(5,PLOT_DRAW_BEGIN,InpMA5Period);
    PlotIndexSetInteger(6,PLOT_DRAW_BEGIN,InpMA10Period);
    PlotIndexSetInteger(7,PLOT_DRAW_BEGIN,InpMA10Period);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hBB!=INVALID_HANDLE)    IndicatorRelease(hBB);
    if(hEMA50!=INVALID_HANDLE) IndicatorRelease(hEMA50);
    if(h5H!=INVALID_HANDLE)    IndicatorRelease(h5H);
    if(h5L!=INVALID_HANDLE)    IndicatorRelease(h5L);
    if(h10H!=INVALID_HANDLE)   IndicatorRelease(h10H);
    if(h10L!=INVALID_HANDLE)   IndicatorRelease(h10L);
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
    if(rates_total<InpMA10Period+2) return(0);

    //--- lines update live every tick
    if(BarsCalculated(hBB)<rates_total||BarsCalculated(hEMA50)<rates_total||
       BarsCalculated(h5H)<rates_total||BarsCalculated(h5L)<rates_total||
       BarsCalculated(h10H)<rates_total||BarsCalculated(h10L)<rates_total)
       return(0);
    if(CopyBuffer(hBB,1,0,rates_total,BufBBUp)!=rates_total)   return(0);
    if(CopyBuffer(hBB,0,0,rates_total,BufBBMid)!=rates_total)  return(0);
    if(CopyBuffer(hBB,2,0,rates_total,BufBBLo)!=rates_total)   return(0);
    if(CopyBuffer(hEMA50,0,0,rates_total,BufEMA50)!=rates_total) return(0);
    if(CopyBuffer(h5H,0,0,rates_total,Buf5H)!=rates_total)     return(0);
    if(CopyBuffer(h5L,0,0,rates_total,Buf5L)!=rates_total)     return(0);
    if(CopyBuffer(h10H,0,0,rates_total,Buf10H)!=rates_total)   return(0);
    if(CopyBuffer(h10L,0,0,rates_total,Buf10L)!=rates_total)   return(0);

    //--- markers only on new bar (closed bars only)
    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SSig mom[], re[];
    FindSignals(open,high,low,close,time,rates_total,mom,re);
    DrawSignals(mom,re);
    ChartRedraw();
    return(rates_total);
   }

double BandTop(int i) { return(MathMax(Buf5H[i],Buf10H[i])); }
double BandBot(int i) { return(MathMin(Buf5L[i],Buf10L[i])); }

void AppendSig(SSig &a[],datetime t,double px,bool bull)
   {
    int n=ArraySize(a);
    ArrayResize(a,n+1);
    a[n].time=t; a[n].px=px; a[n].bull=bull;
   }

//--- momentum per bar, then re-entry = rejection back out within the wait window
void FindSignals(const double &o[],const double &h[],const double &l[],
                 const double &c[],const datetime &t[],int rates_total,
                 SSig &mom[],SSig &re[])
   {
    ArrayResize(mom,0); ArrayResize(re,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    double minBody=InpMinBodyPct/100.0;
    int scan=MathMin(InpLookbackBars,rates_total-InpMA10Period-1);
    if(scan<2) return;

    int dir[];
    ArrayResize(dir,scan+1);
    ArrayInitialize(dir,0);
    for(int i=scan;i>=1;i--)
      {
        double range=h[i]-l[i];
        if(range<=0) continue;
        double body=c[i]-o[i];
        if(MathAbs(body)<minBody*range) continue;   // not a directional candle
        //--- must PIERCE the band: open at/inside it, close beyond it
        if(body>0 && o[i]<=BandTop(i) && c[i]>BandTop(i))
           { dir[i]=+1; AppendSig(mom,t[i],l[i]-gap,true); }
        else if(body<0 && o[i]>=BandBot(i) && c[i]<BandBot(i))
           { dir[i]=-1; AppendSig(mom,t[i],h[i]+gap,false); }
      }
    //--- both lists come out oldest -> newest (loop runs old -> new)

    for(int r=scan;r>=1;r--)
      {
       double top=BandTop(r), bot=BandBot(r);
       bool bullShape=(l[r]<top && c[r]>top && c[r]>o[r]);
       bool bearShape=(h[r]>bot && c[r]<bot && c[r]<o[r]);
       if(!bullShape && !bearShape) continue;
       int want=(bullShape?+1:-1);
       for(int m=r+1;m<=MathMin(r+InpMaxWaitBars,scan);m++)
         {
          if(dir[m]==want)
            {
             AppendSig(re,t[r],(want>0?l[r]-gap:h[r]+gap),(want>0));
             break;
            }
         }
      }
   }

void DrawSignals(const SSig &mom[],const SSig &re[])
   {
    DeleteAllObjects();
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;

    if(InpShowMomentum)
      {
       int n=ArraySize(mom);
       int start=(n>InpMaxMarks)?n-InpMaxMarks:0;
       for(int k=start;k<n;k++)
         {
          string nm=InpPrefix+"mom_"+TimeToString(mom[k].time,TIME_DATE|TIME_MINUTES)+
                    "_"+IntegerToString(k);
          ObjectCreate(0,nm,(mom[k].bull?OBJ_ARROW_UP:OBJ_ARROW_DOWN),0,
                       mom[k].time,mom[k].px);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,(mom[k].bull?InpBullColor:InpBearColor));
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("BBMA momentum %s @ %s",
                mom[k].bull?"bull (close above MA band)":"bear (close below MA band)",
                TimeToString(mom[k].time)));
         }
      }

    if(InpShowReentry)
      {
       int n=ArraySize(re);
       int start=(n>InpMaxReentry)?n-InpMaxReentry:0;
       for(int k=start;k<n;k++)
         {
          string nm=InpPrefix+"re_"+TimeToString(re[k].time,TIME_DATE|TIME_MINUTES)+
                    "_"+IntegerToString(k);
          ObjectCreate(0,nm,(re[k].bull?OBJ_ARROW_BUY:OBJ_ARROW_SELL),0,
                       re[k].time,re[k].px);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,(re[k].bull?InpBullColor:InpBearColor));
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,2);
          ObjectSetInteger(0,nm,OBJPROP_BACK,false);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("BBMA re-entry %s @ %s",
                re[k].bull?"BUY (rejected back above band)":"SELL (rejected back below band)",
                TimeToString(re[k].time)));
          string lb=nm+"_lbl";
          double lpx=(re[k].bull?re[k].px-3*gap:re[k].px+3*gap);
          ObjectCreate(0,lb,OBJ_TEXT,0,re[k].time,lpx);
          ObjectSetString(0,lb,OBJPROP_TEXT,"BBMA re-entry");
          ObjectSetInteger(0,lb,OBJPROP_COLOR,(re[k].bull?InpBullColor:InpBearColor));
          ObjectSetInteger(0,lb,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,lb,OBJPROP_ANCHOR,
             (re[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
          ObjectSetInteger(0,lb,OBJPROP_BACK,true);
          ObjectSetInteger(0,lb,OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
