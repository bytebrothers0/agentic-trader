//+------------------------------------------------------------------+
//|                                             MSNR_ABX_CloseTL.mq5 |
//|              ABAX Indicator B7: respected close trendlines         |
//+------------------------------------------------------------------+
//| Rules (ABAX P06):                                                  |
//|  Anchored on closes (Close1->Close2), wick-confirmed. Valid only  |
//|  with ≥3 respected touches, R² > 0.85 on log-price, anchored to   |
//|  an HTF (H4) key zone (never force a line). Spacing: equal gaps   |
//|  strongest (maxGap/minGap < 1.5); shrinking gaps = exhaustion      |
//|  warning. Position vs SNR: line above SNR = bullish bias, below =  |
//|  bearish. Score = touches + spacing + wick-confirm + SNR side.    |
//|  (PHX4 stays the wick-fractal pair variant; this is the ABAX      |
//|  close-respected model.)                                           |
//|                                                                    |
//|  Rendering: segments anchor -> now, quality labels, exhaustion    |
//|  tags. Most-recent cap. Closed bars only. No rays.                |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 3;                // Pivot strength (close fractals)
input double InpTouchATR      = 0.15;              // Touch tolerance (x ATR)
input double InpWickATR       = 0.2;               // Wick-confirm tolerance (x ATR)
input double InpMinR2         = 0.85;              // Min R-squared (log price)
input double InpSpaceMax      = 1.5;               // maxGap/minGap for strong spacing
input double InpExhRatio      = 0.7;               // Last gap < first x this = exhaustion
input bool   InpRequireHTF    = true;              // Anchors must sit at H4 key zone
input double InpHTFTolATR     = 0.5;               // HTF anchor tolerance (x ATR)
input int    InpHTFBars       = 200;               // H4 bars for key zones
input ENUM_TIMEFRAMES InpHTF  = PERIOD_H4;         // Anchor timeframe
input int    InpMaxTLPerSide  = 2;                 // Max lines per side (newest)
input int    InpATRPeriod     = 14;                // ATR period
input bool   InpShowLabels    = true;              // Show labels
input color  InpSupColor      = clrDodgerBlue;     // Support TL (bullish)
input color  InpResColor      = clrTomato;         // Resistance TL (bearish)
input color  InpExhColor      = clrOrange;         // Exhaustion tag (amber)
input string InpPrefix        = "MSNR_CTL_";       // Object name prefix

int hATR=INVALID_HANDLE;

struct SPivot
   {
    double   price;
    datetime time;
    bool     is_high;
    int      idx;
   };

struct SCT
   {
    datetime t1;
    double   p1;
    double   slope;
    bool     support;     // line under price (bullish) vs above (bearish)
    int      touches;
    double   r2;
    int      spacing;     // 0 strong, 1 ok, 2 exhausting
    int      snrSide;     // +1 above SNR, -1 below
    int      score;
    double   proj;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR CloseTL");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+5) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SCT tls[];
    FindTLs(time,open,high,low,close,atr,rates_total,tls);

    DrawTLs(tls,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- close-fractals, alternating, oldest -> newest
void FindCPivots(const double &c[],const datetime &t[],int rates_total,SPivot &piv[])
   {
    ArrayResize(piv,0);
    int maxScan=MathMin(InpLookbackBars,rates_total-InpPivotStrength-1);
    for(int i=maxScan;i>=InpPivotStrength;i--)
      {
       bool isHigh=true,isLow=true;
       for(int k=1;k<=InpPivotStrength;k++)
         {
          if(c[i]<=c[i+k] || c[i]<=c[i-k]) isHigh=false;
          if(c[i]>=c[i+k] || c[i]>=c[i-k]) isLow=false;
          if(!isHigh && !isLow) break;
         }
       if(!isHigh && !isLow) continue;
       if(isHigh && isLow) isLow=false;
       int n=ArraySize(piv);
       ArrayResize(piv,n+1);
       piv[n].is_high=isHigh; piv[n].price=c[i];
       piv[n].time=t[i]; piv[n].idx=i;
      }
    int m=ArraySize(piv);
    for(int a=1;a<m;a++)
      {
       if(piv[a].is_high==piv[a-1].is_high)
         {
          bool keepA=piv[a].is_high ? (piv[a].price>=piv[a-1].price)
                                    : (piv[a].price<=piv[a-1].price);
          if(keepA) { piv[a-1]=piv[a]; }
          for(int b=a+1;b<m;b++) piv[b-1]=piv[b];
          m--; a--;
         }
      }
    ArrayResize(piv,m);
   }

//--- HTF 2-candle key closes (anchor check)
void HTFKeys(double &keys[])
   {
    ArrayResize(keys,0);
    MqlRates r[];
    int got=CopyRates(_Symbol,InpHTF,0,InpHTFBars,r);
    if(got<5) return;
    ArraySetAsSeries(r,true);
    for(int i=got-2;i>=1;i--)
      {
       bool bu1=(r[i+1].close>r[i+1].open), be1=(r[i+1].close<r[i+1].open);
       bool bu2=(r[i].close>r[i].open),     be2=(r[i].close<r[i].open);
       if((be1&&bu2)||(bu1&&be2))
         { int n=ArraySize(keys); ArrayResize(keys,n+1); keys[n]=r[i+1].close; }
      }
   }

bool NearKey(const double &keys[],double px,double tol)
   {
    for(int q=0;q<ArraySize(keys);q++)
       if(MathAbs(keys[q]-px)<=tol) return(true);
    return(false);
   }

//--- nearest chart-TF 2-candle level to px (0 = none) for SNR-side tag
double NearLevel(const double &o[],const double &c[],int rates_total,double px)
   {
    double best=0, bd=1e100;
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=(c[i+1]>o[i+1]), bear1=(c[i+1]<o[i+1]);
       bool bull2=(c[i]>o[i]),     bear2=(c[i]<o[i]);
       if((bear1&&bull2)||(bull1&&bear2))
         {
          double d=MathAbs(c[i+1]-px);
          if(d<bd) { bd=d; best=c[i+1]; }
         }
      }
    return(best);
   }

double LineAt(datetime t1,double p1,double slope,datetime t)
   {
    return(p1+slope*((double)(t-t1)));
   }

void FindTLs(const datetime &t[],const double &o[],const double &h[],
             const double &l[],const double &c[],const double &atr[],
             int rates_total,SCT &tls[])
   {
    ArrayResize(tls,0);
    double aRef=atr[1];
    if(aRef<=0) return;
    double touchTol=InpTouchATR*aRef;
    double wickTol =InpWickATR*aRef;
    double htfTol  =InpHTFTolATR*aRef;

    SPivot piv[];
    FindCPivots(c,t,rates_total,piv);
    double keys[];
    HTFKeys(keys);

    int scan=MathMin(InpLookbackBars,rates_total-1);
    for(int side=0;side<2;side++)
      {
       bool wantHigh=(side==0);
       int cnt=0;
       for(int p=0;p<ArraySize(piv);p++)
          if(piv[p].is_high==wantHigh) cnt++;
       if(cnt<2) continue;
       SPivot s[];
       ArrayResize(s,cnt);
       int w=0;
       for(int p=0;p<ArraySize(piv);p++)
          if(piv[p].is_high==wantHigh) { s[w]=piv[p]; w++; }
       int made=0;
       for(int e=cnt-1;e>=1 && made<InpMaxTLPerSide;e--)
         {
          datetime t1=s[e-1].time, t2=s[e].time;
          double p1=s[e-1].price, p2=s[e].price;
          if(t2<=t1) continue;
          double slope=(p2-p1)/((double)(t2-t1));
          //--- touches (closes within tol)
           int tj[];
           ArrayResize(tj,0);
           for(int j=1;j<=scan;j++)
             {
              if(j>s[e-1].idx) continue;   // line only exists from anchor 1 onward
              if(MathAbs(c[j]-LineAt(t1,p1,slope,t[j]))<=touchTol)
                { int n=ArraySize(tj); ArrayResize(tj,n+1); tj[n]=j; }
             }
          if(ArraySize(tj)<3) continue;   // never force
          //--- R² on log-price of touches
          double sx=0, sy=0, sxx=0, syy=0, sxy=0;
          int nn=ArraySize(tj);
          for(int q=0;q<nn;q++)
            {
             double x=(double)t[tj[q]], y=MathLog(c[tj[q]]);
             sx+=x; sy+=y; sxx+=x*x; syy+=y*y; sxy+=x*y;
            }
          double den=(nn*sxx-sx*sx);
          double r2=0;
          if(den!=0)
            {
             double d2=(nn*syy-sy*sy);
             if(d2>0)
               {
                double r=(nn*sxy-sx*sy)/MathSqrt(den*d2);
                r2=r*r;
               }
            }
          if(r2<InpMinR2) continue;
          //--- HTF anchor: both anchors at an H4 key zone
          if(InpRequireHTF && (!NearKey(keys,p1,htfTol) || !NearKey(keys,p2,htfTol)))
             continue;
          made++;
          //--- spacing quality: tj newest-first, ga[0] = oldest gap
          int spacing=1;
          if(nn>=3)
            {
             int ga[], gb=0;
             ArrayResize(ga,nn-1);
             for(int q=nn-1;q>=1;q--) { ga[gb]=tj[q-1]-tj[q]; gb++; }
             int mx=ga[0], mn=ga[0];
             for(int q=1;q<gb;q++) { if(ga[q]>mx) mx=ga[q]; if(ga[q]<mn) mn=ga[q]; }
             if(mn>0 && (double)mx/(double)mn<InpSpaceMax) spacing=0;
             else if(gb>=2 && ga[gb-1]<ga[0]*InpExhRatio) spacing=2;
            }
          //--- wick confirm at ≥2 touches
          int wickC=0;
          for(int q=0;q<nn;q++)
            {
             double lp=LineAt(t1,p1,slope,t[tj[q]]);
             double ex=(wantHigh?h[tj[q]]:l[tj[q]]);
             if(MathAbs(ex-lp)<=wickTol) wickC++;
            }
          //--- SNR side: line vs nearest level at now
          double proj=LineAt(t1,p1,slope,t[1]);
          double lv=NearLevel(o,c,rates_total,proj);
          int snrSide=(lv==0?0:(proj>=lv?+1:-1));
          bool support=(proj<c[1]);
          int score=ArraySize(tj)+(spacing==0?2:(spacing==1?1:0))+
                    (wickC>=2?1:0)+(snrSide==(support?+1:-1)?1:0);
          SCT x;
          x.t1=t1; x.p1=p1; x.slope=slope; x.support=support;
          x.touches=nn; x.r2=r2; x.spacing=spacing; x.snrSide=snrSide;
          x.score=score; x.proj=proj;
          int n2=ArraySize(tls);
          ArrayResize(tls,n2+1); tls[n2]=x;
         }
      }
   }

void DrawTLs(const SCT &tls[],datetime now)
   {
    DeleteAllObjects();
    for(int k=0;k<ArraySize(tls);k++)
      {
       string nm=InpPrefix+(tls[k].support?"sup_":"res_")+
                 TimeToString(tls[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(tls[k].spacing==2?InpExhColor:(tls[k].support?InpSupColor:InpResColor));
       double pNow=LineAt(tls[k].t1,tls[k].p1,tls[k].slope,now);
       ObjectCreate(0,nm,OBJ_TREND,0,tls[k].t1,tls[k].p1,now,pNow);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,(tls[k].score>=7?2:1));
       ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       string sp=(tls[k].spacing==0?"equal":(tls[k].spacing==2?"EXH":"ok"));
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("CloseTL %s | x%d touches R²=%.2f spacing %s | %s SNR | score %d",
             tls[k].support?"support":"resistance",tls[k].touches,tls[k].r2,sp,
             tls[k].snrSide>0?"above":(tls[k].snrSide<0?"below":"no"),
             tls[k].score));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,now,pNow);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             StringFormat("cTL-%s x%d%s",tls[k].support?"S":"R",
                tls[k].touches,(tls[k].spacing==2?" EXH":"")));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (tls[k].support?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
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
