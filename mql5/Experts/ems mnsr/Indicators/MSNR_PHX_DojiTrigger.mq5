//+------------------------------------------------------------------+
//|                                           MSNR_PHX_DojiTrigger.mq5 |
//|              PHX Indicator 3: Doji-at-level trigger + SL ruler     |
//+------------------------------------------------------------------+
//| Rules (Phoenix Part 5 + PDF resistance/Doji entries):               |
//|                                                                    |
//|  Doji: body <= 15% of range (Part 5 §2.2), min-range dust filter.  |
//|  Context (both required to mark):                                  |
//|   - Doji extreme overlaps a 2-candle S/R or OCL zone within        |
//|     InpZonePips (I1/I3 parity, precise-line reaction);             |
//|   - correct E5 side: shorts only with body above PD50 of the       |
//|     last-BOS swing, longs only below (Part 5 §1.1).                |
//|  Pre-zone-LQ flag: nearest E3-style inducement on the approach     |
//|  path (IND hi below a short POI / IND lo above a long POI) swept  |
//|  before the Doji -> `LQ OK`, else `no LQ` (Part 5 §3).             |
//|  SL ruler (display only, EA enforces): SL = Doji extreme +         |
//|  buffer; label shows entry->SL pips, `SKIP` when > InpMaxSLPips    |
//|  (TS-tip SL placement lives in PHX1/PHX5 tooltips).                |
//|                                                                    |
//|  Rendering: pure marker - arrow + compact label at the Doji        |
//|  (`Doji SHT 8p`, gray `SKIP` when over budget). Full math in       |
//|  tooltips. Most-recent cap. Closed bars only. No rays.             |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (levels/swings)
input double InpDojiMaxPct    = 15.0;              // Max body % of range = Doji
input double InpMinRangePips  = 1.0;               // Min candle range (dust filter, pips)
input double InpZonePips      = 2.0;               // Level-zone tolerance (pips)
input double InpSLBufferPips  = 2.0;               // SL buffer past Doji extreme (pips)
input double InpMaxSLPips     = 15.0;              // SL budget: SKIP above this (pips)
input int    InpMaxTrig       = 30;                // Max triggers drawn (most recent)
input double InpArrowGapPips  = 3.0;               // Arrow gap from extreme (pips)
input color  InpShortColor    = clrTomato;         // Short trigger
input color  InpLongColor     = clrDodgerBlue;     // Long trigger
input color  InpSkipColor     = clrGray;           // Over-budget trigger
input string InpPrefix        = "MSNR_DT_";        // Object name prefix

struct SLevel
   {
    double   price;
    int      formed_idx;
    datetime formed_time;
    bool     is_support;
    bool     is_ocl;
   };

struct SBos
   {
    datetime time;
    int      dir;
   };

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;
   };

struct SLiq
   {
    double   price;
    datetime t1;
    datetime t2;         // 0 = un-swept
    bool     bull;       // true = IND lo, false = IND hi
   };

struct STrig
   {
    datetime time;
    double   hi;
    double   lo;
    double   entry;
    double   sl;
    double   slPips;
    bool     shortSide;
    bool     skip;
    bool     lqOK;
    double   lvl;
    bool     ocl;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Doji Trigger");
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason) { DeleteAllObjects(); }

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

    if(rates_total<2*InpPivotStrength+5) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    STrig tr[];
    FindTriggers(time,open,high,low,close,rates_total,tr);

    DrawTriggers(tr);
    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels + OCLs in one list (I1/I3 parity)
void DetectLevels(const datetime &t[],const double &o[],const double &c[],
                  int rates_total,SLevel &lv[])
   {
    ArrayResize(lv,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       if((bear1&&bull2)||(bull1&&bear2))
         {
          int n=ArraySize(lv);
          ArrayResize(lv,n+1);
          lv[n].price=c[i+1]; lv[n].formed_idx=i;
          lv[n].formed_time=t[i];
          lv[n].is_support=(bear1&&bull2); lv[n].is_ocl=false;
         }
       if((bull2&&bull1)||(bear2&&bear1))
         {
          int n2=ArraySize(lv);
          ArrayResize(lv,n2+1);
          lv[n2].price=c[i+1]; lv[n2].formed_idx=i;
          lv[n2].formed_time=t[i];
          lv[n2].is_support=bull2; lv[n2].is_ocl=true;
         }
      }
   }

//--- first close-through per 2-candle level, ascending (E5 parity)
void FindBOS(const datetime &t[],const double &o[],const double &c[],
             int rates_total,SBos &bos[])
   {
    ArrayResize(bos,0);
    SLevel lv[];
    DetectLevels(t,o,c,rates_total,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       if(lv[k].is_ocl) continue;
       for(int j=lv[k].formed_idx-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price)
            { int n=ArraySize(bos); ArrayResize(bos,n+1); bos[n].time=t[j]; bos[n].dir=-1; break; }
          if(!lv[k].is_support && c[j]>lv[k].price)
            { int n=ArraySize(bos); ArrayResize(bos,n+1); bos[n].time=t[j]; bos[n].dir=+1; break; }
         }
      }
    for(int i=1;i<ArraySize(bos);i++)
      {
       SBos v=bos[i]; int j=i-1;
       while(j>=0 && bos[j].time>v.time) { bos[j+1]=bos[j]; j--; }
       bos[j+1]=v;
      }
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

//--- E3-style pullback liquidity (higher low = IND lo, lower high = IND hi)
void BuildLiq(const SPivot &piv[],const double &c[],const datetime &t[],SLiq &lines[])
   {
    ArrayResize(lines,0);
    int m=ArraySize(piv);
    bool haveLow=false,haveHigh=false;
    double prevLow=0,prevHigh=0;
    for(int p=0;p<m;p++)
      {
       if(!piv[p].is_high)
         {
          if(haveLow && piv[p].price>prevLow)
            {
             SLiq x; x.price=piv[p].price; x.t1=piv[p].time; x.t2=0; x.bull=true;
             for(int j=piv[p].idx-1;j>=1;j--)
                if(c[j]<x.price) { x.t2=t[j]; break; }
             int n=ArraySize(lines);
             ArrayResize(lines,n+1); lines[n]=x;
            }
          haveLow=true; prevLow=piv[p].price;
         }
       else
         {
          if(haveHigh && piv[p].price<prevHigh)
            {
             SLiq x; x.price=piv[p].price; x.t1=piv[p].time; x.t2=0; x.bull=false;
             for(int j=piv[p].idx-1;j>=1;j--)
                if(c[j]>x.price) { x.t2=t[j]; break; }
             int n=ArraySize(lines);
             ArrayResize(lines,n+1); lines[n]=x;
            }
          haveHigh=true; prevHigh=piv[p].price;
         }
      }
   }

void FindTriggers(const datetime &t[],const double &o[],const double &h[],
                  const double &l[],const double &c[],int rates_total,STrig &tr[])
   {
    ArrayResize(tr,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double zoneTol=InpZonePips*pip;
    double minRange=InpMinRangePips*pip;
    double slBuf=InpSLBufferPips*pip;
    double dojiMax=InpDojiMaxPct/100.0;

    SLevel lv[];
    DetectLevels(t,o,c,rates_total,lv);

    //--- PD50 swing: last BOS -> now (E5 parity)
    SBos bos[];
    FindBOS(t,o,c,rates_total,bos);
    datetime legStart=t[MathMin(InpLookbackBars,rates_total-1)];
    if(ArraySize(bos)>0) legStart=bos[ArraySize(bos)-1].time;
    int startIdx=rates_total-1;
    for(int i=0;i<rates_total;i++)
       if(t[i]<=legStart) { startIdx=i; break; }
    if(startIdx<2) startIdx=2;
    double sh=h[1], sl=l[1];
    for(int j=1;j<=startIdx;j++)
      { if(h[j]>sh) sh=h[j]; if(l[j]<sl) sl=l[j]; }
    double mid=(sh+sl)/2.0;

    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);
    SLiq liq[];
    BuildLiq(piv,c,t,liq);

    int scan=MathMin(InpLookbackBars,rates_total-1);
    for(int i=scan;i>=1;i--)
      {
       double range=h[i]-l[i];
       if(range<minRange) continue;
       if(MathAbs(c[i]-o[i])>dojiMax*range) continue;   // not a Doji
       //--- nearest overlapping level at either extreme
       double lvlPx=0; bool lvlOCL=false; bool lvlShort=false;
       double best=DBL_MAX;
       for(int k=0;k<ArraySize(lv);k++)
         {
          if(lv[k].formed_time>=t[i]) continue;         // level must predate the Doji
          double dH=MathAbs(h[i]-lv[k].price);
          double dL=MathAbs(l[i]-lv[k].price);
          if(dH<=zoneTol && dH<best) { best=dH; lvlPx=lv[k].price; lvlOCL=lv[k].is_ocl; lvlShort=true; }
          if(dL<=zoneTol && dL<best) { best=dL; lvlPx=lv[k].price; lvlOCL=lv[k].is_ocl; lvlShort=false; }
         }
       if(best==DBL_MAX) continue;                  // no level touch
       bool wantShort=lvlShort;
       if(wantShort && !(c[i]>mid)) continue;           // wrong premium side
       if(!wantShort && !(c[i]<mid)) continue;
       //--- pre-zone-LQ: inducement on the approach path swept before the Doji
       bool lqOK=false;
       for(int q=0;q<ArraySize(liq);q++)
         {
          if(liq[q].t2==0 || liq[q].t2>=t[i]) continue;
          if(wantShort && !liq[q].bull && liq[q].price<lvlPx && liq[q].t1<t[i]) { lqOK=true; break; }
          if(!wantShort && liq[q].bull && liq[q].price>lvlPx && liq[q].t1<t[i]) { lqOK=true; break; }
         }
       STrig x;
       x.time=t[i]; x.hi=h[i]; x.lo=l[i];
       x.shortSide=wantShort;
       x.entry=c[i];
       x.sl=(wantShort?h[i]+slBuf:l[i]-slBuf);
       x.slPips=MathAbs(x.sl-x.entry)/pip;
       x.skip=(x.slPips>InpMaxSLPips);
       x.lqOK=lqOK; x.lvl=lvlPx; x.ocl=lvlOCL;
       int n=ArraySize(tr);
       ArrayResize(tr,n+1); tr[n]=x;
      }
   }

void DrawTriggers(const STrig &tr[])
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    DeleteAllObjects();
    int n=ArraySize(tr);
    int start=(n>InpMaxTrig)?n-InpMaxTrig:0;
    for(int k=start;k<n;k++)
      {
       string nm=InpPrefix+(tr[k].shortSide?"sht_":"lng_")+
                 TimeToString(tr[k].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(tr[k].skip?InpSkipColor:(tr[k].shortSide?InpShortColor:InpLongColor));
       double apx=(tr[k].shortSide?tr[k].hi+gap:tr[k].lo-gap);
       ObjectCreate(0,nm+"_arw",(tr[k].shortSide?OBJ_ARROW_DOWN:OBJ_ARROW_UP),0,
                    tr[k].time,apx);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_BACK,true);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_SELECTABLE,false);
       string lbl=StringFormat("Doji %s %.1fp%s%s",
          tr[k].shortSide?"SHT":"LNG",tr[k].slPips,
          tr[k].skip?" SKIP":"",(tr[k].lqOK?" LQ":" noLQ"));
       ObjectCreate(0,nm+"_lbl",OBJ_TEXT,0,tr[k].time,
                    (tr[k].shortSide?apx+2*gap:apx-2*gap));
       ObjectSetString(0,nm+"_lbl",OBJPROP_TEXT,lbl);
       ObjectSetInteger(0,nm+"_lbl",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_lbl",OBJPROP_FONTSIZE,8);
       ObjectSetInteger(0,nm+"_lbl",OBJPROP_ANCHOR,
          (tr[k].shortSide?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
       ObjectSetInteger(0,nm+"_lbl",OBJPROP_BACK,true);
       ObjectSetInteger(0,nm+"_lbl",OBJPROP_SELECTABLE,false);
       ObjectSetString(0,nm+"_arw",OBJPROP_TOOLTIP,
          StringFormat("Doji %s @ %s | %s %s | body %s PD50 | SL %s (%.1f pips)%s%s",
             tr[k].shortSide?"SHORT":"LONG",TimeToString(tr[k].time),
             tr[k].ocl?"OCL":"S/R",DoubleToString(tr[k].lvl,_Digits),
             tr[k].shortSide?"above":"below",
             DoubleToString(tr[k].sl,_Digits),tr[k].slPips,
             tr[k].skip?" | OVER BUDGET - EA must skip":" | within budget",
             tr[k].lqOK?" | pre-zone LQ swept":" | no pre-zone LQ"));
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
