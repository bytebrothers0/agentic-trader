//+------------------------------------------------------------------+
//|                                                   MSNR_EMS_FVG.mq5 |
//|              EMS Indicator E6: FVG 3-candle imbalance              |
//+------------------------------------------------------------------+
//| Rules (EMS Part 1 §4A, indicatorplan E6):                          |
//|                                                                    |
//|  Bull FVG: low[i] > high[i+2] - gap between the wicks of candle 1  |
//|  (i+2, oldest) and candle 3 (i, newest) of the triplet, carved by  |
//|  the middle displacement candle.                                   |
//|  Bear FVG: high[i] < low[i+2]. Strict inequalities, wick-based.    |
//|  Zone = [gap bottom .. gap top]; midline (CE) marked dashed.       |
//|                                                                    |
//|  Mitigation = first CLOSE that fills through the gap: a bull FVG   |
//|  is filled when close < gap bottom, a bear FVG when close > gap    |
//|  top (same close-through philosophy as E1 EF / E2 BOS - wicks      |
//|  alone do NOT fill). Box spans formation -> fill bar, or -> now    |
//|  while active. Filled boxes turn dotted gray (or hidden).          |
//|                                                                    |
//|  Rendering: pure marker, no rays. Most-recent cap honored.         |
//|  Closed bars only.                                                 |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpMaxBoxes      = 50;                // Max boxes drawn (most recent)
input double InpMinGapPips    = 0.5;               // Min gap size for a valid FVG (pips)
input bool   InpShowMidline   = true;              // Draw CE midline (dashed)
input bool   InpShowMitigated = true;              // Show filled (mitigated) boxes
input bool   InpShowLabels    = true;              // Show FVG+ / FVG- labels
input color  InpBullColor     = clrLightSkyBlue;   // Bull FVG shade
input color  InpBearColor     = clrMistyRose;      // Bear FVG shade
input color  InpBullTxt       = clrDodgerBlue;     // Bull FVG label
input color  InpBearTxt       = clrTomato;         // Bear FVG label
input color  InpMitColor      = clrGray;           // Filled box color
input color  InpMidColor      = clrDimGray;        // CE midline color
input string InpPrefix        = "MSNR_FVG_";       // Object name prefix

struct SFvg
   {
    double   top;
    double   bottom;
    double   mid;
    datetime t1;         // formation bar (newest candle of the triplet)
    datetime t2;         // fill bar, 0 = active (unfilled)
    bool     bull;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR FVG (imbalance)");
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason) { DeleteAllObjects(); }

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

    if(rates_total<5) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SFvg fvg[];
    FindFVGs(high,low,close,time,rates_total,fvg);

    DrawFVGs(fvg,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- detect triplets oldest -> newest; fill = first close through the gap
void FindFVGs(const double &h[],const double &l[],const double &c[],
              const datetime &t[],int rates_total,SFvg &f[])
   {
    ArrayResize(f,0);
    double minGap=InpMinGapPips*((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    int maxScan=MathMin(InpLookbackBars,rates_total-3);
    for(int i=maxScan;i>=1;i--)
      {
       bool bull=(l[i]>h[i+2]);
       bool bear=(!bull && h[i]<l[i+2]);
       if(!bull && !bear) continue;
       double top=(bull?l[i]:l[i+2]);
       double bot=(bull?h[i+2]:h[i]);
       if(top-bot<minGap) continue;
       SFvg x;
       x.top=top; x.bottom=bot; x.mid=(top+bot)/2.0;
       x.t1=t[i]; x.t2=0; x.bull=bull;
       for(int j=i-1;j>=1;j--)
         {
          if(bull && c[j]<bot) { x.t2=t[j]; break; }
          if(!bull && c[j]>top) { x.t2=t[j]; break; }
         }
       int n=ArraySize(f);
       ArrayResize(f,n+1); f[n]=x;
      }
   }

void DrawFVGs(const SFvg &f[],datetime now)
   {
    DeleteAllObjects();
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    int n=ArraySize(f);
    int start=(n>InpMaxBoxes)?n-InpMaxBoxes:0;
    for(int k=start;k<n;k++)
      {
       bool filled=(f[k].t2!=0);
       if(filled && !InpShowMitigated) continue;
       datetime t1=f[k].t1;
       datetime t2=(filled?f[k].t2:now);
       if(t2<=t1) continue;

       string nm=InpPrefix+(f[k].bull?"bull_":"bear_")+
                 TimeToString(t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(filled?InpMitColor:(f[k].bull?InpBullColor:InpBearColor));

       ObjectCreate(0,nm,OBJ_RECTANGLE,0,t1,f[k].top,t2,f[k].bottom);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,filled?STYLE_DOT:STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("%s FVG gap %.1f pips [%s..%s] CE %s | formed %s -> %s%s",
             f[k].bull?"Bull":"Bear",(f[k].top-f[k].bottom)/pip,
             DoubleToString(f[k].top,_Digits),DoubleToString(f[k].bottom,_Digits),
             DoubleToString(f[k].mid,_Digits),TimeToString(t1),TimeToString(t2),
             filled?" | FILLED":" | ACTIVE"));

       if(InpShowMidline)
         {
          string ce=nm+"_ce";
          ObjectCreate(0,ce,OBJ_TREND,0,t1,f[k].mid,t2,f[k].mid);
          ObjectSetInteger(0,ce,OBJPROP_COLOR,InpMidColor);
          ObjectSetInteger(0,ce,OBJPROP_STYLE,STYLE_DASH);
          ObjectSetInteger(0,ce,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,ce,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,ce,OBJPROP_BACK,true);
          ObjectSetInteger(0,ce,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,ce,OBJPROP_TOOLTIP,
             StringFormat("FVG CE %s (%s)",DoubleToString(f[k].mid,_Digits),
                f[k].bull?"bull":"bear"));
         }

       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(f[k].bull?f[k].bottom:f[k].top);
          ObjectCreate(0,ln,OBJ_TEXT,0,t1,px);
          ObjectSetString(0,ln,OBJPROP_TEXT,(f[k].bull?"FVG+":"FVG-"));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,
             (filled?InpMitColor:(f[k].bull?InpBullTxt:InpBearTxt)));
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (f[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
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
