//+------------------------------------------------------------------+
//|                                            MSNR_PHX_OrderBlock.mq5 |
//|              PHX Indicator 6: Order Blocks (displacement origin)   |
//+------------------------------------------------------------------+
//| Rules (Phoenix Part 9 §2.1 + PDF M15 OB / SW):                     |
//|                                                                    |
//|  Displacement: body >= InpDispMult x ATR(14) AND the candle IS      |
//|  the first body-close breakout of a 2-candle S/R level (E2/I1      |
//|  parity) - only OBs tied to structural damage qualify (Part 9      |
//|  §2.1 refinement).                                                 |
//|  OB = last opposite-color candle before displacement (dojis        |
//|  transparent, searched within InpOBLookback bars); zone = its      |
//|  high/low.                                                         |
//|  SW tag: displacement wick pierced the OB liquidity-side extreme   |
//|  by >= pierce and closed back inside (PDF "OB with strong SW" /    |
//|  "SW clearing the wick before the reversal candle").               |
//|  Mitigation = first close through the far edge (bull OB filled     |
//|  when close < OB low, E6-fill parity). Box spans OB bar -> fill    |
//|  bar, or -> now while active.                                      |
//|                                                                    |
//|  Rendering: pure marker - shaded zone, dashed CE midline,          |
//|  `OB+` / `OB-` labels (`SW` suffix when tagged). Filled boxes      |
//|  dotted gray (or hidden). Most-recent cap. Closed bars only.       |
//|  No rays.                                                          |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength for S/R levels
input int    InpATRPeriod     = 14;                // ATR period
input double InpDispMult      = 2.0;               // Displacement body >= mult x ATR
input int    InpOBLookback    = 5;                 // Bars back to find origin candle
input double InpMinPiercePips = 0.5;               // Min sweep pierce for SW tag (pips)
input int    InpMaxBoxes      = 50;                // Max boxes drawn (most recent)
input bool   InpShowMidline   = true;              // Draw CE midline (dashed)
input bool   InpShowMitigated = true;              // Show filled (mitigated) boxes
input bool   InpShowLabels    = true;              // Show OB labels
input color  InpBullColor     = clrLightSkyBlue;   // Bull OB shade
input color  InpBearColor     = clrMistyRose;      // Bear OB shade
input color  InpBullTxt       = clrDodgerBlue;     // Bull OB label
input color  InpBearTxt       = clrTomato;         // Bear OB label
input color  InpMitColor      = clrGray;           // Filled box color
input color  InpMidColor      = clrDimGray;        // CE midline color
input string InpPrefix        = "MSNR_OB_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SLevel
   {
    double   price;
    int      formed_idx;
    datetime formed_time;
    bool     is_support;
   };

struct SOB
   {
    double   top;
    double   bottom;
    double   mid;
    datetime t1;         // origin (OB) bar time
    datetime t2;         // fill bar, 0 = active
    bool     bull;
    bool     sw;         // strong-swap tag
    double   dispMult;   // displacement body in ATR units
    double   bosPx;      // broken level price
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Order Blocks");
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

    SOB obs[];
    FindOBs(time,open,high,low,close,atr,rates_total,obs);

    DrawOBs(obs,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels at close (I1/I2/E2 parity)
void DetectLevels(const datetime &t[],const double &o[],const double &c[],SLevel &lv[])
   {
    ArrayResize(lv,0);
    int scan=MathMin(InpLookbackBars,ArraySize(t)-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       bool sup=(bear1&&bull2), res=(bull1&&bear2);
       if(!sup&&!res) continue;
       int n=ArraySize(lv);
       ArrayResize(lv,n+1);
       lv[n].price=c[i+1]; lv[n].formed_idx=i;
       lv[n].formed_time=t[i]; lv[n].is_support=sup;
      }
   }

void FindOBs(const datetime &t[],const double &o[],const double &h[],
              const double &l[],const double &c[],const double &atr[],
              int rates_total,SOB &obs[])
   {
    ArrayResize(obs,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double pierce=InpMinPiercePips*pip;

    //--- 1) first-break bar per direction (oldest break = structural damage)
    int maxScan=MathMin(InpLookbackBars,rates_total-3);
    bool bosUp[];
    bool bosDn[];
    double bosPxUp[];
    double bosPxDn[];
    ArrayResize(bosUp,maxScan+1); ArrayInitialize(bosUp,false);
    ArrayResize(bosDn,maxScan+1); ArrayInitialize(bosDn,false);
    ArrayResize(bosPxUp,maxScan+1); ArrayInitialize(bosPxUp,0.0);
    ArrayResize(bosPxDn,maxScan+1); ArrayInitialize(bosPxDn,0.0);
    SLevel lv[];
    DetectLevels(t,o,c,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       for(int j=F-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price)
            { if(j<=maxScan && !bosDn[j]) { bosDn[j]=true; bosPxDn[j]=lv[k].price; } break; }
          if(!lv[k].is_support && c[j]>lv[k].price)
            { if(j<=maxScan && !bosUp[j]) { bosUp[j]=true; bosPxUp[j]=lv[k].price; } break; }
         }
      }

    //--- 2) displacement + origin, oldest -> newest
    for(int d=maxScan;d>=1;d--)
      {
       double body=c[d]-o[d];
       if(atr[d]<=0) continue;
       bool bull=(body>0 && bosUp[d]);
       bool bear=(body<0 && bosDn[d]);
       if(!bull && !bear) continue;
       if(MathAbs(body)<InpDispMult*atr[d]) continue;
       //--- last opposite-color candle (dojis transparent)
       int b=-1;
       for(int q=d+1;q<=MathMin(d+InpOBLookback,rates_total-1);q++)
         {
          if(bull && IsBearC(o,c,q)) { b=q; break; }
          if(bear && IsBullC(o,c,q)) { b=q; break; }
         }
       if(b<0) continue;
       double top=h[b], bot=l[b];
       if(top-bot<_Point) continue;
       //--- SW: displacement wicked through the liquidity-side extreme
       bool sw=(bull ? (l[d]<bot-pierce && c[d]>bot)
                     : (h[d]>top+pierce && c[d]<top));
       SOB x;
       x.top=top; x.bottom=bot; x.mid=(top+bot)/2.0;
       x.t1=t[b]; x.t2=0; x.bull=bull; x.sw=sw;
       x.dispMult=MathAbs(body)/atr[d];
       x.bosPx=(bull?bosPxUp[d]:bosPxDn[d]);
       for(int j=d-1;j>=1;j--)
         {
          if(bull && c[j]<bot) { x.t2=t[j]; break; }
          if(!bull && c[j]>top) { x.t2=t[j]; break; }
         }
       int n=ArraySize(obs);
       ArrayResize(obs,n+1); obs[n]=x;
      }
   }

void DrawOBs(const SOB &obs[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(obs);
    int start=(n>InpMaxBoxes)?n-InpMaxBoxes:0;
    for(int k=start;k<n;k++)
      {
       bool filled=(obs[k].t2!=0);
       if(filled && !InpShowMitigated) continue;
       datetime t1=obs[k].t1;
       datetime t2=(filled?obs[k].t2:now);
       if(t2<=t1) continue;

       string nm=InpPrefix+(obs[k].bull?"bull_":"bear_")+
                 TimeToString(t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(filled?InpMitColor:(obs[k].bull?InpBullColor:InpBearColor));

       ObjectCreate(0,nm,OBJ_RECTANGLE,0,t1,obs[k].top,t2,obs[k].bottom);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,filled?STYLE_DOT:STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,(obs[k].sw && !filled?2:1));
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("%s OB [%s..%s] CE %s | broke %s with %.1f ATR body%s | formed %s -> %s%s",
             obs[k].bull?"Bull":"Bear",
             DoubleToString(obs[k].top,_Digits),DoubleToString(obs[k].bottom,_Digits),
             DoubleToString(obs[k].mid,_Digits),DoubleToString(obs[k].bosPx,_Digits),
             obs[k].dispMult,(obs[k].sw?" | STRONG SW":""),
             TimeToString(t1),TimeToString(t2),filled?" | FILLED":" | ACTIVE"));

       if(InpShowMidline)
         {
          string ce=nm+"_ce";
          ObjectCreate(0,ce,OBJ_TREND,0,t1,obs[k].mid,t2,obs[k].mid);
          ObjectSetInteger(0,ce,OBJPROP_COLOR,InpMidColor);
          ObjectSetInteger(0,ce,OBJPROP_STYLE,STYLE_DASH);
          ObjectSetInteger(0,ce,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,ce,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,ce,OBJPROP_BACK,true);
          ObjectSetInteger(0,ce,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,ce,OBJPROP_TOOLTIP,
             StringFormat("OB CE %s",DoubleToString(obs[k].mid,_Digits)));
         }

       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(obs[k].bull?obs[k].bottom:obs[k].top);
          ObjectCreate(0,ln,OBJ_TEXT,0,t1,px);
          string txt=(obs[k].bull?"OB+":"OB-");
          if(obs[k].sw) txt+=" SW";
          ObjectSetString(0,ln,OBJPROP_TEXT,txt);
          ObjectSetInteger(0,ln,OBJPROP_COLOR,
             (filled?InpMitColor:(obs[k].bull?InpBullTxt:InpBearTxt)));
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (obs[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
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
