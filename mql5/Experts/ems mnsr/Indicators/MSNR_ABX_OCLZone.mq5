//+------------------------------------------------------------------+
//|                                             MSNR_ABX_OCLZone.mq5 |
//|              ABAX Indicator B5: OCL acceptance zones + session     |
//+------------------------------------------------------------------+
//| Rules (ABAX P04-05):                                               |
//|  Zone = [min(close_k, open_next) .. max] on displacement candles   |
//|  only (body > 1.5 ATR; doji/small rejected). Birth session tagged  |
//|  Asia 0.5 / London-NY 1.0 / overlap 1.5 (server-hour inputs).      |
//|  States: virgin -> retested (wick touch + hold) -> broken (body    |
//|  close beyond far edge) -> flipped (touch from other side + close  |
//|  back). Stack score: +1 virgin/retest-reject, +1 SNR overlap       |
//|  (0.25 ATR), +1 London/NY session, +1 big displacement (2 ATR).    |
//|  FVG/TL overlap layered at EA score time (E6/PHX4, not duplicated).|
//|                                                                    |
//|  Rendering: shaded zone formation -> now (or break); state + score |
//|  labels; broken gray dotted, flipped amber. Most-recent cap.       |
//|  Closed bars only. No rays.                                        |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (SNR overlap)
input int    InpATRPeriod     = 14;                // ATR period
input double InpDispMult      = 1.5;               // Displacement body qualifier (x ATR)
input double InpBigDispMult   = 2.0;               // Big displacement for score (x ATR)
input int    InpAsiaEnd       = 7;                 // Asia session ends (server hour)
input int    InpLondonEnd     = 12;                // London session ends (server hour)
input int    InpOverlapEnd    = 16;                // LN overlap ends (server hour)
input int    InpMaxZones      = 30;                // Max zones drawn (most recent)
input bool   InpShowLabels    = true;              // Show labels
input color  InpBullColor     = clrLightSkyBlue;   // Bull OCL shade
input color  InpBearColor     = clrMistyRose;      // Bear OCL shade
input color  InpBullTxt       = clrDodgerBlue;     // Bull label
input color  InpBearTxt       = clrTomato;         // Bear label
input color  InpBrokenColor   = clrGray;           // Broken zone
input color  InpFlipColor     = clrOrange;         // Flipped zone (amber)
input string InpPrefix        = "MSNR_OZ_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SOCL
   {
    double   top;
    double   bottom;
    datetime t1;
    datetime tEnd;       // break bar, 0 = unbroken
    bool     bull;       // key candle direction (support/resistance side)
    int      sess;       // 0 Asia, 1 London, 2 Overlap, 3 NY
    int      state;      // 0 virgin, 1 retested, 2 broken, 3 flipped
    int      score;
    double   bodyATR;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR OCL Zones");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+3) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SOCL z[];
    FindOCLs(time,open,high,low,close,atr,rates_total,z);

    DrawOCLs(z,time[0]);
    ChartRedraw();
    return(rates_total);
   }

int BirthSession(datetime tt)
   {
    MqlDateTime d;
    TimeToStruct(tt,d);
    if(d.hour<InpAsiaEnd) return(0);
    if(d.hour<InpLondonEnd) return(1);
    if(d.hour<InpOverlapEnd) return(2);
    return(3);
   }

string SessName(int s)
   {
    if(s==0) return("ASIA");
    if(s==1) return("LON");
    if(s==2) return("OVL");
    return("NY");
   }

//--- 2-candle S/R closes for SNR-overlap scoring (I1 parity)
bool SNROverlap(const datetime &t[],const double &o[],const double &c[],
                int rates_total,double px,double tol)
   {
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       if((bear1&&bull2)||(bull1&&bear2))
          if(MathAbs(c[i+1]-px)<=tol) return(true);
      }
    return(false);
   }

void FindOCLs(const datetime &t[],const double &o[],const double &h[],
              const double &l[],const double &c[],const double &atr[],
              int rates_total,SOCL &z[])
   {
    ArrayResize(z,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       int k=i+1;   // key candle (older), next candle = i (newer)
       double body=MathAbs(c[k]-o[k]);
       if(atr[k]<=0 || body<InpDispMult*atr[k]) continue;   // qualifier
       bool bull=IsBullC(o,c,k);
       if(!bull && !IsBearC(o,c,k)) continue;
       double top=MathMax(c[k],o[i]), bot=MathMin(c[k],o[i]);
       if(top-bot<_Point) continue;
       SOCL x;
       x.top=top; x.bottom=bot; x.t1=t[i]; x.tEnd=0;
       x.bull=bull; x.sess=BirthSession(t[k]); x.state=0;
       x.bodyATR=body/atr[k];
       //--- lifecycle walk (newer bars)
       bool touched=false;
       for(int j=i-1;j>=1;j--)
         {
          bool inside=(l[j]<=top && h[j]>=bot);
          if(x.bull)
            {
             if(c[j]<bot) { x.state=2; x.tEnd=t[j]; break; }
             if(inside) touched=true;
            }
          else
            {
             if(c[j]>top) { x.state=2; x.tEnd=t[j]; break; }
             if(inside) touched=true;
            }
         }
       if(x.state==0 && touched) x.state=1;
       //--- flip: after break, touch from other side + close back
       if(x.state==2)
         {
          int bEnd=rates_total-1;
          for(int j=0;j<rates_total;j++)
             if(t[j]<=x.tEnd) { bEnd=j; break; }
          for(int j=bEnd-1;j>=1;j--)
            {
             bool inside=(l[j]<=top && h[j]>=bot);
             if(!inside) continue;
             if(x.bull && c[j]>top) { x.state=3; break; }
             if(!x.bull && c[j]<bot) { x.state=3; break; }
            }
         }
       //--- score
       int sc=0;
       if(x.state==1) sc+=1;
       else if(x.state==0) sc+=1;   // virgin watch
       if(SNROverlap(t,o,c,rates_total,(top+bot)/2.0,0.25*atr[k])) sc+=1;
       if(x.sess!=0) sc+=1;
       if(x.bodyATR>=InpBigDispMult) sc+=1;
       x.score=sc;
       int n=ArraySize(z);
       ArrayResize(z,n+1); z[n]=x;
      }
   }

string StateName(int s)
   {
    if(s==0) return("virgin");
    if(s==1) return("retest");
    if(s==2) return("broken");
    return("FLIP");
   }

void DrawOCLs(const SOCL &z[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(z);
    int start=(n>InpMaxZones)?n-InpMaxZones:0;
    for(int k=start;k<n;k++)
      {
       datetime t2=(z[k].tEnd==0?now:z[k].tEnd);
       if(t2<=z[k].t1) continue;
       string nm=InpPrefix+(z[k].bull?"bull_":"bear_")+
                 TimeToString(z[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr;
       int style=STYLE_SOLID;
       if(z[k].state==2) { clr=InpBrokenColor; style=STYLE_DOT; }
       else if(z[k].state==3) { clr=InpFlipColor; style=STYLE_SOLID; }
       else clr=(z[k].bull?InpBullColor:InpBearColor);
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,z[k].t1,z[k].top,t2,z[k].bottom);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,style);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("OCL %s [%s..%s] body %.1f ATR | %s %s | score S%d/4 | formed %s -> %s",
             z[k].bull?"bull":"bear",
             DoubleToString(z[k].top,_Digits),DoubleToString(z[k].bottom,_Digits),
             z[k].bodyATR,SessName(z[k].sess),StateName(z[k].state),z[k].score,
             TimeToString(z[k].t1),TimeToString(t2)));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(z[k].bull?z[k].bottom:z[k].top);
          ObjectCreate(0,ln,OBJ_TEXT,0,z[k].t1,px);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             StringFormat("OCL S%d %s",z[k].score,SessName(z[k].sess)));
          color lc=(z[k].state==2?InpBrokenColor:(z[k].state==3?InpFlipColor:
                     (z[k].bull?InpBullTxt:InpBearTxt)));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,lc);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (z[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
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
