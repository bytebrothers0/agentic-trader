//+------------------------------------------------------------------+
//|                                                MSNR_PHX_MSS.mq5  |
//|              PHX Indicator 2: TS -> MSS sequence detector         |
//+------------------------------------------------------------------+
//| Rules (Phoenix Parts 2, 4 + PDF BOS/TS/MSS):                       |
//|                                                                    |
//|  1) Continuous BOS gate: >= InpMinBOS consecutive same-direction   |
//|     body-close breakouts of fractal swings before the sweep        |
//|     (Part 2 §1.3 - no trading early unstable structure).           |
//|  2) Target Sweep of BSL/SSL (PHX1 parity: wick rejection with      |
//|     pierce tolerance, or marginal-close + close-back within        |
//|     2 bars). EQ-cluster extremes count as pools.                   |
//|  3) MSS trigger = most recent fractal swing low before the TS      |
//|     (bull->bear; mirror). MSS = first close beyond the trigger.    |
//|     A close beyond the TS extreme first invalidates the sequence   |
//|     (continuation, not a trap). Lone BOS is never MSS.             |
//|  4) Displacement tag: MSS-bar body >= InpDispMult x ATR = DISP,    |
//|     else weak (Part 4 §2.1 + false-MSS handling).                  |
//|                                                                    |
//|  Rendering: pure marker - trigger-level segment (TS bar -> MSS     |
//|  bar), MSS arrow + `MSS` label. BOS count + DISP/weak in tooltip.  |
//|  Most-recent cap honored. Closed bars only. No rays.               |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (bars each side)
input double InpEQHPips       = 2.5;               // EQ cluster tolerance (pips, PHX1 parity)
input double InpMinPiercePips = 0.5;               // Min wick pierce for TS (pips, E2 parity)
input double InpOverPips      = 2.0;               // Max marginal close-beyond for reversal TS (pips)
input int    InpMinBOS        = 2;                 // Min continuous BOS before the TS
input int    InpATRPeriod     = 14;                // ATR period (displacement)
input double InpDispMult      = 1.5;               // MSS body >= mult x ATR => DISP
input int    InpMaxSeq        = 30;                // Max sequences drawn (most recent)
input double InpArrowGapPips  = 3.0;               // Arrow gap from extreme (pips)
input color  InpBearColor     = clrTomato;         // Bearish MSS (short setup)
input color  InpBullColor     = clrDodgerBlue;     // Bullish MSS (long setup)
input string InpPrefix        = "MSNR_MS_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;
   };

struct SPool
   {
    double   price;
    int      idx;        // formation (newest member) series index
    bool     isBSL;
   };

struct SSeq
   {
    datetime tsTime;
    double   tip;        // TS extreme (invalidation level)
    double   trig;       // MSS trigger level
    datetime mssTime;
    double   mssPx;      // MSS bar extreme (arrow anchor base)
    bool     bear;       // true = short setup (bull trend -> MSS down)
    int      bos;        // continuous BOS count before TS
    bool     disp;       // displacement or weak
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR TS->MSS");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+3) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);

    SPivot piv[];
    FindPivots(high,low,time,rates_total,piv);
    SPool pools[];
    BuildPools(piv,InpEQHPips*pip,pools);

    SSeq seq[];
    FindSequences(pools,piv,open,high,low,close,time,atr,pip,seq);

    DrawSeq(seq,pip);
    ChartRedraw();
    return(rates_total);
   }

//--- fractal pivots, alternating, oldest -> newest (E3/PHX1 parity)
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

//--- one pool per pivot + EQ-cluster extremes (PHX1 parity, singles deduped)
void BuildPools(const SPivot &piv[],double eqTol,SPool &pools[])
   {
    ArrayResize(pools,0);
    int m=ArraySize(piv);
    bool used[];
    ArrayResize(used,m);
    ArrayInitialize(used,false);
    for(int p=0;p<m;p++)
      {
       if(used[p]) continue;
       used[p]=true;
       double extreme=piv[p].price;
       int newestIdx=piv[p].idx;
       int cnt=1;
       for(int q=p+1;q<m;q++)
         {
          if(used[q] || piv[q].is_high!=piv[p].is_high) continue;
          if(MathAbs(piv[q].price-extreme)<=eqTol)
            {
             used[q]=true; cnt++;
             if(piv[p].is_high) extreme=MathMax(extreme,piv[q].price);
             else                extreme=MathMin(extreme,piv[q].price);
             if(piv[q].idx<newestIdx) newestIdx=piv[q].idx;
            }
         }
       SPool x; x.price=extreme; x.idx=newestIdx; x.isBSL=piv[p].is_high;
       int n=ArraySize(pools);
       ArrayResize(pools,n+1); pools[n]=x;
      }
   }

//--- consecutive broken swings walking back from the TS bar (newest -> oldest)
int CountBOS(const SPivot &piv[],bool up,int s,const double &c[])
   {
    int cnt=0;
    for(int p=ArraySize(piv)-1;p>=0;p--)
      {
       if(piv[p].is_high!=up) continue;
       if(piv[p].idx<=s) continue;      // must predate the TS bar
       bool broken=false;
       for(int j=piv[p].idx-1;j>=s;j--)
         {
          if(up && c[j]>piv[p].price) { broken=true; break; }
          if(!up && c[j]<piv[p].price) { broken=true; break; }
         }
       if(!broken) break;
       cnt++;
      }
    return(cnt);
   }

//--- most recent opposite-side pivot older than bar s (the MSS trigger level)
bool TriggerLevel(const SPivot &piv[],bool wantHigh,int s,double &px)
   {
    for(int p=ArraySize(piv)-1;p>=0;p--)
      {
       if(piv[p].is_high!=wantHigh) continue;
       if(piv[p].idx<=s) continue;
       px=piv[p].price;
       return(true);
      }
    return(false);
   }

void AppendSeq(SSeq &s[],datetime tsT,double tip,double trig,datetime mssT,
               double mssPx,bool bear,int bos,bool disp)
   {
    int n=ArraySize(s);
    ArrayResize(s,n+1);
    s[n].tsTime=tsT; s[n].tip=tip; s[n].trig=trig; s[n].mssTime=mssT;
    s[n].mssPx=mssPx; s[n].bear=bear; s[n].bos=bos; s[n].disp=disp;
   }

void FindSequences(const SPool &pools[],const SPivot &piv[],
                   const double &o[],const double &h[],const double &l[],
                   const double &c[],const datetime &t[],const double &atr[],
                   double pip,SSeq &seq[])
   {
    ArrayResize(seq,0);
    double pierce=InpMinPiercePips*pip;
    double over  =InpOverPips*pip;
    for(int k=0;k<ArraySize(pools);k++)
      {
       //--- 1) first TS of this pool (oldest-first)
       int s=-1; double tip=0;
       for(int j=pools[k].idx-1;j>=1;j--)
         {
          if(pools[k].isBSL)
            {
             if(h[j]>pools[k].price+pierce && c[j]<pools[k].price)
               { s=j; tip=h[j]; break; }
             if(j>=3 && c[j]>pools[k].price && c[j]<=pools[k].price+over)
               {
                for(int k2=j-1;k2>=j-2;k2--)
                   if(c[k2]<pools[k].price) { s=k2; tip=MathMax(h[j],h[k2]); break; }
                if(s>0) break;
               }
            }
          else
            {
             if(l[j]<pools[k].price-pierce && c[j]>pools[k].price)
               { s=j; tip=l[j]; break; }
             if(j>=3 && c[j]<pools[k].price && c[j]>=pools[k].price-over)
               {
                for(int k2=j-1;k2>=j-2;k2--)
                   if(c[k2]>pools[k].price) { s=k2; tip=MathMin(l[j],l[k2]); break; }
                if(s>0) break;
               }
            }
         }
       if(s<0) continue;
       //--- 2) continuous BOS gate
       int bos=CountBOS(piv,pools[k].isBSL,s,c);
       if(bos<InpMinBOS) continue;
       //--- 3) MSS trigger + race: close through trigger vs through tip
       double trig=0;
       if(!TriggerLevel(piv,!pools[k].isBSL,s,trig)) continue;
       int mss=-1;
       for(int j=s-1;j>=1;j--)
         {
          if(pools[k].isBSL)
            {
             if(c[j]>tip) break;                    // continuation kills the trap
             if(c[j]<trig) { mss=j; break; }
            }
          else
            {
             if(c[j]<tip) break;
             if(c[j]>trig) { mss=j; break; }
            }
         }
       if(mss<0) continue;
       bool bear=pools[k].isBSL;                    // BSL sweep -> short setup
       double body=MathAbs(c[mss]-o[mss]);
       bool disp=(atr[mss]>0 && body>=InpDispMult*atr[mss]);
       double mpx=(bear?h[mss]:l[mss]);
       AppendSeq(seq,t[s],tip,trig,t[mss],mpx,bear,bos,disp);
      }
    //--- oldest -> newest by MSS time (N small)
    for(int i=1;i<ArraySize(seq);i++)
      {
       SSeq v=seq[i]; int j=i-1;
       while(j>=0 && seq[j].mssTime>v.mssTime) { seq[j+1]=seq[j]; j--; }
       seq[j+1]=v;
      }
   }

void DrawSeq(const SSeq &seq[],double pip)
   {
    DeleteAllObjects();
    double gap=InpArrowGapPips*pip;
    int n=ArraySize(seq);
    int start=(n>InpMaxSeq)?n-InpMaxSeq:0;
    for(int k=start;k<n;k++)
      {
       if(seq[k].mssTime<=seq[k].tsTime) continue;
       string nm=InpPrefix+(seq[k].bear?"bear_":"bull_")+
                 TimeToString(seq[k].mssTime,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(seq[k].bear?InpBearColor:InpBullColor);

       ObjectCreate(0,nm+"_trig",OBJ_TREND,0,seq[k].tsTime,seq[k].trig,seq[k].mssTime,seq[k].trig);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_BACK,true);
       ObjectSetInteger(0,nm+"_trig",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm+"_trig",OBJPROP_TOOLTIP,
          StringFormat("MSS trigger %s | TS %s (tip %s) -> MSS %s",
             DoubleToString(seq[k].trig,_Digits),TimeToString(seq[k].tsTime),
             DoubleToString(seq[k].tip,_Digits),TimeToString(seq[k].mssTime)));

       double apx=(seq[k].bear?seq[k].mssPx+gap:seq[k].mssPx-gap);
       ObjectCreate(0,nm+"_arw",(seq[k].bear?OBJ_ARROW_DOWN:OBJ_ARROW_UP),0,
                    seq[k].mssTime,apx);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_BACK,false);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm+"_arw",OBJPROP_TOOLTIP,
          StringFormat("MSS %s after %d BOS | %s | trigger %s, TS tip %s",
             seq[k].bear?"BEAR (short)":"BULL (long)",seq[k].bos,
             seq[k].disp?"DISP (impulsive)":"weak (grind - lower confidence)",
             DoubleToString(seq[k].trig,_Digits),DoubleToString(seq[k].tip,_Digits)));

       string lb=nm+"_lbl";
       ObjectCreate(0,lb,OBJ_TEXT,0,seq[k].mssTime,
                    (seq[k].bear?apx+2*gap:apx-2*gap));
       ObjectSetString(0,lb,OBJPROP_TEXT,("MSS"+(seq[k].disp?"":" weak")));
       ObjectSetInteger(0,lb,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,lb,OBJPROP_FONTSIZE,8);
       ObjectSetInteger(0,lb,OBJPROP_ANCHOR,
          (seq[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
       ObjectSetInteger(0,lb,OBJPROP_BACK,true);
       ObjectSetInteger(0,lb,OBJPROP_SELECTABLE,false);
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
