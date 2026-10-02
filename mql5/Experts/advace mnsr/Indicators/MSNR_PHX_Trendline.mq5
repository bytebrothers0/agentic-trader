//+------------------------------------------------------------------+
//|                                            MSNR_PHX_Trendline.mq5 |
//|              PHX Indicator 4: auto trendlines + confluence         |
//+------------------------------------------------------------------+
//| Rules (Phoenix Part 6 + PDF trendline confirmation):                |
//|                                                                    |
//|  Anchors: point-to-point across same-side fractal swing heads      |
//|  (Part 6 §2.1, PDF "through 2-3 points where price reacted").      |
//|  Per side, up to InpMaxTLPerSide newest pairs; pairs whose         |
//|  projection sits farther than InpMaxDistATR x ATR(14) from price   |
//|  are irrelevant and skipped (ATR adapts to any symbol). Extra      |
//|  touches within InpTouchPips count.                                |
//|  TL x LVL: projected TL price within InpConflPips (±3, Part 6 §3)  |
//|  of a 2-candle S/R or OCL level at the last closed bar -> the     |
//|  master-confluence flag.                                           |
//|  TL sweep (Part 6 §4 retail-trap): wick pierces the TL by >=       |
//|  pierce but body closes back (E2 shape) -> `TLS` mark.             |
//|                                                                    |
//|  Rendering: pure marker - thin TL segments (anchor -> now, width   |
//|  2 + label when confluent), touch counts + projection in           |
//|  tooltips, `TLS` sweep labels. Closed bars only. No rays.          |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.02"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (bars each side)
input double InpTouchPips     = 2.0;               // Touch tolerance (pips)
input double InpConflPips     = 3.0;               // TL x level confluence tol (pips, Part 6)
input int    InpATRPeriod     = 14;                // ATR period (relevance filter)
input double InpMaxDistATR    = 3.0;               // Skip TLs projected farther than this (x ATR)
input int    InpMaxTLPerSide  = 2;                 // Max TL pairs per side (newest)
input double InpMinPiercePips = 0.5;               // Min TL pierce for sweep (pips, E2 parity)
input int    InpMaxSweeps     = 20;                // Max TL-sweep marks (most recent)
input bool   InpShowTL        = true;              // Draw trendlines
input bool   InpShowSweeps    = true;              // Draw TL-sweep marks
input bool   InpShowLabels    = true;              // Show TL / TLS labels
input color  InpResColor      = clrTomato;         // Resistance TL
input color  InpSupColor      = clrDodgerBlue;     // Support TL
input color  InpConflColor    = clrOrange;         // Confluent TL (amber)
input string InpPrefix        = "MSNR_TL_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;
   };

struct STL
   {
    datetime t1;
    double   p1;
    datetime t2;          // second anchor (line exists from here on)
    double   slope;       // price per second from the anchor pair
    bool     isRes;
    int      touches;
    bool     confl;
    double   lvlPx;       // confluent level price
    double   proj;        // projection at last closed bar
   };

struct SSweep
   {
    datetime time;
    double   px;
    bool     isRes;       // which TL family was swept
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Trendlines");
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
    double atrRef[];
    ArraySetAsSeries(atrRef,true);
    if(CopyBuffer(hATR,0,0,rates_total,atrRef)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    STL tls[];
    SSweep sw[];
    FindTLs(time,open,high,low,close,rates_total,atrRef[1],tls,sw);

    DrawAll(tls,sw,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- fractal pivots, alternating, oldest -> newest (E3 parity)
void FindPivots(const double &h[],const double &l[],const datetime &t[],
                int rates_total,SPivot &piv[])
   {
    ArrayResize(piv,0);
    int maxScan=MathMin(InpLookbackBars,rates_total-InpPivotStrength-1);
    for(int i=maxScan;i>=InpPivotStrength;i--)
      {
       bool isHigh=true,isLow=true;
       for(int k=1;k<=InpPivotStrength;k++)
         {
          if(h[i]<=h[i+k] || h[i]<=h[i-k]) isHigh=false;
          if(l[i]>=l[i+k] || l[i]>=l[i-k]) isLow=false;
          if(!isHigh && !isLow) break;
         }
       if(!isHigh && !isLow) continue;
       if(isHigh && isLow) isLow=false;
       int n=ArraySize(piv);
       ArrayResize(piv,n+1);
       piv[n].is_high=isHigh;
       piv[n].price=isHigh?h[i]:l[i];
       piv[n].time=t[i];
       piv[n].idx=i;
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

//--- horizontal levels: 2-candle S/R closes + OCLs (I1/I3 parity, price only)
void LevelPrices(const double &o[],const double &c[],int rates_total,double &lv[])
   {
    ArrayResize(lv,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       if((bear1&&bull2)||(bull1&&bear2)||(bull1&&bull2)||(bear1&&bear2))
         {
          int n=ArraySize(lv);
          ArrayResize(lv,n+1); lv[n]=c[i+1];
         }
      }
   }

double LinePx(datetime t1,double p1,datetime t2,double p2,datetime t)
   {
    if(t2<=t1) return(p1);
    double m=(p2-p1)/((double)(t2-t1));
    return(p1+m*((double)(t-t1)));
   }

void FindTLs(const datetime &t[],const double &o[],const double &h[],
             const double &l[],const double &c[],int rates_total,double atr,
             STL &tls[],SSweep &sw[])
   {
    ArrayResize(tls,0); ArrayResize(sw,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double touchTol=InpTouchPips*pip;
    double conflTol=InpConflPips*pip;
    double maxDist =(atr>0?InpMaxDistATR*atr:0.0);   // 0 = ATR unknown, no filter
    double pierce  =InpMinPiercePips*pip;

    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);
    double lv[];
    LevelPrices(o,c,rates_total,lv);

    int scan=MathMin(InpLookbackBars,rates_total-1);
    datetime refT=t[1];   // confluence evaluated at the last closed bar

    for(int side=0;side<2;side++)
      {
       bool wantHigh=(side==0);
       //--- same-side pivots, newest last
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
          double proj=LinePx(t1,p1,t2,p2,refT);
          if(maxDist>0 && MathAbs(proj-c[1])>maxDist) continue;   // irrelevant TL
          made++;   // quota counts accepted pairs only
           int touches=0;
           for(int j=1;j<=scan;j++)
             {
              if(t[j]<t2) continue;   // only count touches on the formed line
              double lp=LinePx(t1,p1,t2,p2,t[j]);
              double ex=(wantHigh?h[j]:l[j]);
              if(MathAbs(ex-lp)<=touchTol) touches++;
             }
          bool confl=false; double lvlPx=0;
          for(int q=0;q<ArraySize(lv);q++)
             if(MathAbs(lv[q]-proj)<=conflTol) { confl=true; lvlPx=lv[q]; break; }
           STL x;
           x.t1=t1; x.p1=p1; x.t2=t2; x.isRes=wantHigh;
          x.slope=((double)(t2-t1)>0?(p2-p1)/((double)(t2-t1)):0.0);
          x.touches=touches; x.confl=confl; x.lvlPx=lvlPx; x.proj=proj;
          int n=ArraySize(tls);
          ArrayResize(tls,n+1); tls[n]=x;
         }
      }

    //--- TL sweeps: wick through the projected line, body back (E2 shape)
    for(int j=scan;j>=1;j--)
      {
       if(ArraySize(sw)>=InpMaxSweeps) break;
        for(int k=0;k<ArraySize(tls);k++)
          {
           if(t[j]<tls[k].t2) continue;   // TL didn't exist yet before anchor 2
           double lp=ProjAt(tls[k],t[j]);
          if(tls[k].isRes)
            {
             if(h[j]>lp+pierce && c[j]<lp)
               { AddSweep(sw,t[j],h[j],true); break; }
            }
          else
            {
             if(l[j]<lp-pierce && c[j]>lp)
               { AddSweep(sw,t[j],l[j],false); break; }
            }
         }
      }
    //--- sweeps came out newest-first; flip to oldest -> newest
    for(int a=0,b=ArraySize(sw)-1;a<b;a++,b--)
      { SSweep v=sw[a]; sw[a]=sw[b]; sw[b]=v; }
    //--- cap keeps the most recent
    int sn=ArraySize(sw);
    if(sn>InpMaxSweeps)
      {
       for(int a=0;a<InpMaxSweeps;a++) sw[a]=sw[sn-InpMaxSweeps+a];
       ArrayResize(sw,InpMaxSweeps);
      }
   }

//--- projection of a stored TL at any bar time
double ProjAt(const STL &x,datetime t)
   {
    return(x.p1+x.slope*((double)(t-x.t1)));
   }

void AddSweep(SSweep &sw[],datetime tt,double px,bool isRes)
   {
    int n=ArraySize(sw);
    ArrayResize(sw,n+1);
    sw[n].time=tt; sw[n].px=px; sw[n].isRes=isRes;
   }

void DrawAll(const STL &tls[],const SSweep &sw[],datetime now)
   {
    DeleteAllObjects();
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=3.0*pip;
    if(InpShowTL)
      {
       for(int k=0;k<ArraySize(tls);k++)
         {
          string nm=InpPrefix+(tls[k].isRes?"res_":"sup_")+
                    TimeToString(tls[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
          color clr=(tls[k].confl?InpConflColor:(tls[k].isRes?InpResColor:InpSupColor));
          double pNow=ProjAt(tls[k],now);
          ObjectCreate(0,nm,OBJ_TREND,0,tls[k].t1,tls[k].p1,now,pNow);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,(tls[k].confl?2:1));
          ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("Trendline %s | anchors %s %s | touches x%d | proj now %s%s",
                tls[k].isRes?"resistance":"support",
                TimeToString(tls[k].t1),DoubleToString(tls[k].p1,_Digits),
                tls[k].touches,DoubleToString(pNow,_Digits),
                tls[k].confl?StringFormat(" | TL x LVL @ %s",DoubleToString(tls[k].lvlPx,_Digits)):""));
          if(InpShowLabels)
            {
             string ln=nm+"_lbl";
             ObjectCreate(0,ln,OBJ_TEXT,0,now,pNow);
             string txt=StringFormat("TL-%s x%d%s",tls[k].isRes?"R":"S",
                            tls[k].touches,(tls[k].confl?" TLxLVL":""));
             ObjectSetString(0,ln,OBJPROP_TEXT,txt);
             ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
             ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
             ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
                (tls[k].isRes?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
             ObjectSetInteger(0,ln,OBJPROP_BACK,true);
             ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
            }
         }
      }
    if(InpShowSweeps)
      {
       for(int k=0;k<ArraySize(sw);k++)
         {
          string nm=InpPrefix+"tls_"+TimeToString(sw[k].time,TIME_DATE|TIME_MINUTES)+
                    "_"+IntegerToString(k);
          color clr=(sw[k].isRes?InpResColor:InpSupColor);
          double apx=(sw[k].isRes?sw[k].px+gap:sw[k].px-gap);
          ObjectCreate(0,nm,(sw[k].isRes?OBJ_ARROW_DOWN:OBJ_ARROW_UP),0,sw[k].time,apx);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
          if(InpShowLabels)
            {
             string ln=nm+"_lbl";
             ObjectCreate(0,ln,OBJ_TEXT,0,sw[k].time,(sw[k].isRes?apx+2*gap:apx-2*gap));
             ObjectSetString(0,ln,OBJPROP_TEXT,"TLS");
             ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
             ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
             ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
                (sw[k].isRes?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
             ObjectSetInteger(0,ln,OBJPROP_BACK,true);
             ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
            }
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
