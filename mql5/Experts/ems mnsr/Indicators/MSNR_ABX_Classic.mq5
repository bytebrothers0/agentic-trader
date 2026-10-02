//+------------------------------------------------------------------+
//|                                             MSNR_ABX_Classic.mq5 |
//|              ABAX Indicator B2: Classic V/A + reaction taxonomy    |
//+------------------------------------------------------------------+
//| Rules (ABAX P02 p18-22):                                           |
//|  ClassicV buy: c1 closes below S, next opens back at S (±tol)      |
//|  and closes up; wick pierce deeper than 0.3 ATR = sweep, not       |
//|  classic. ClassicA mirror. No-retest: single touch + displacement  |
//|  away (body > ATR within 3 bars) + no return in N bars.            |
//|  Type1: ≥2 rejections at the zone + mid-rally to a key level       |
//|  between. Type2: zero rejections but a swing sweep before the      |
//|  hold (liquidity-backed). MicroSweep: prior-candle H/L pierce +    |
//|  close-back at the touch bar. Touch counter per level: >3 touches  |
//|  with no displacement -> WEAK. ZoneStrength = sweep + hold.        |
//|                                                                    |
//|  Rendering: pure marker - CV/CA arrows, Type/WEAK/strength tags    |
//|  at first touch, micro-sweep ticks. Most-recent cap. Closed bars   |
//|  only. No rays. (Levels themselves come from I1.)                 |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (levels/swings)
input int    InpATRPeriod     = 14;                // ATR period
input double InpTolPips       = 2.0;               // Level touch tolerance (pips)
input double InpMaxPierceATR  = 0.3;               // Pierce deeper = sweep, not classic
input int    InpNoReturnBars  = 20;                // No-return window for no-retest
input double InpRallyATR      = 1.0;               // Mid-rally size for Type1 (x ATR)
input int    InpSweepBack     = 30;                // Bars back to find pre-sweep (Type2)
input int    InpMaxWeakTouch  = 3;                 // Touches before WEAK
input int    InpMaxMarks      = 50;                // Max marks drawn (most recent)
input double InpArrowGapPips  = 3.0;               // Arrow gap (pips)
input bool   InpShowLabels    = true;              // Show tags
input color  InpBullColor     = clrDodgerBlue;     // Bull marks
input color  InpBearColor     = clrTomato;         // Bear marks
input color  InpWeakColor     = clrGray;           // WEAK tag
input string InpPrefix        = "MSNR_AC_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SLevel
   {
    double   price;
    int      formed_idx;
    bool     is_support;
   };

struct SPivot
   {
    double   price;
    bool     is_high;
    int      idx;
   };

struct SMark
   {
    datetime time;
    double   px;
    int      kind;       // 0 CV, 1 CA, 2 Type1, 3 Type2, 4 WEAK, 5 micro
    bool     bull;
    string   text;
    string   tip;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Classic");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+5) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SMark mk[];
    FindMarks(time,open,high,low,close,atr,rates_total,mk);

    DrawMarks(mk);
    ChartRedraw();
    return(rates_total);
   }

void DetectLevels(const datetime &t[],const double &o[],const double &c[],
                  int rates_total,SLevel &lv[])
   {
    ArrayResize(lv,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       bool sup=(bear1&&bull2), res=(bull1&&bear2);
       if(!sup&&!res) continue;
       int n=ArraySize(lv);
       ArrayResize(lv,n+1);
       lv[n].price=c[i+1]; lv[n].formed_idx=i; lv[n].is_support=sup;
      }
   }

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

void AddMark(SMark &mk[],datetime tm,double px,int kind,bool bull,
             const string text,const string tip)
   {
    int n=ArraySize(mk);
    ArrayResize(mk,n+1);
    mk[n].time=tm; mk[n].px=px; mk[n].kind=kind; mk[n].bull=bull;
    mk[n].text=text; mk[n].tip=tip;
   }

//--- swing sweep before bar j (same side extreme pierced + closed back)
bool SweepBefore(const SPivot &piv[],const double &h[],const double &l[],
                 const double &c[],int j,bool bullSide,double pierce)
   {
    for(int b=j+1;b<=MathMin(j+InpSweepBack,ArraySize(c)-1);b++)
      {
       for(int p=ArraySize(piv)-1;p>=0;p--)
         {
          if(piv[p].idx<=b) continue;
          if(bullSide && !piv[p].is_high &&
             l[b]<piv[p].price-pierce && c[b]>piv[p].price) return(true);
          if(!bullSide && piv[p].is_high &&
             h[b]>piv[p].price+pierce && c[b]<piv[p].price) return(true);
         }
      }
    return(false);
   }

void FindMarks(const datetime &t[],const double &o[],const double &h[],
               const double &l[],const double &c[],const double &atr[],
               int rates_total,SMark &mk[])
   {
    ArrayResize(mk,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double tol=InpTolPips*pip;
    double pierce=0.5*pip;

    SLevel lv[];
    DetectLevels(t,o,c,rates_total,lv);
    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);

    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       double L=lv[k].price;
       //--- touch bars (newer than formation)
       int tj[];
       ArrayResize(tj,0);
       for(int j=F-1;j>=1;j--)
         {
          bool touch=(lv[k].is_support ? l[j]<=L+tol : h[j]>=L-tol);
          if(touch) { int n=ArraySize(tj); ArrayResize(tj,n+1); tj[n]=j; }
         }
        if(ArraySize(tj)==0) continue;
        //--- tj built j=F-1 -> 1 iterating forward in time: oldest = FIRST element
        int first=tj[0];
       double a=atr[first];
       if(a<=0) a=pip*10.0;
       //--- Classic V/A two-bar shape at first touch
       if(first+1<rates_total)
         {
          if(lv[k].is_support && c[first+1]<L && o[first]>=L-tol && c[first]>o[first])
            {
             if(L-l[first+1]<=InpMaxPierceATR*a)
                AddMark(mk,t[first],l[first],0,true,"CV",
                   StringFormat("ClassicV buy @ %s (close-back at support)",
                      DoubleToString(L,_Digits)));
            }
          if(!lv[k].is_support && c[first+1]>L && o[first]<=L+tol && c[first]<o[first])
            {
             if(h[first+1]-L<=InpMaxPierceATR*a)
                AddMark(mk,t[first],h[first],1,false,"CA",
                   StringFormat("ClassicA sell @ %s (close-back at resistance)",
                      DoubleToString(L,_Digits)));
            }
         }
       //--- MicroSweep at first touch (prior-candle extreme + close back)
       if(first+1<rates_total)
         {
          if(lv[k].is_support && l[first]<l[first+1] && c[first]>l[first+1])
             AddMark(mk,t[first],l[first],5,true,"mS",
                "MicroSweep of prior low + close back");
          if(!lv[k].is_support && h[first]>h[first+1] && c[first]<h[first+1])
             AddMark(mk,t[first],h[first],5,false,"mS",
                "MicroSweep of prior high + close back");
         }
       //--- rejections + displacement + rally/type logic
       int rej=0, rejBars=0;
       bool displaced=false;
       double rallyEx=0;
       for(int q=ArraySize(tj)-1;q>=0;q--)
         {
          int j=tj[q];
          bool closedBack=(lv[k].is_support ? c[j]>L : c[j]<L);
          if(closedBack) { rej++; rejBars=j; }
          for(int d=j-1;d>=MathMax(j-3,1);d--)
             if(MathAbs(c[d]-o[d])>atr[d] && atr[d]>0) displaced=true;
          double ex=(lv[k].is_support?h[j]:l[j]);
          if(q<ArraySize(tj)-1)
            {
             // rally between this touch and the previous (older) one tracked below
            }
         }
       //--- mid-rally: extreme between oldest two touches
        double rally=0;
        if(ArraySize(tj)>=2)
          {
           int o1=tj[0], o2=tj[1];   // oldest two touches (tj[0] oldest)
           for(int j=o1;j>=o2;j--)
            {
             double ex=(lv[k].is_support?h[j]:l[j]);
             if(lv[k].is_support && ex>rally) rally=ex;
             if(!lv[k].is_support && (rally==0 || ex<rally)) rally=ex;
            }
         }
       bool rallyOK=(ArraySize(tj)>=2 &&
          (lv[k].is_support ? rally>=L+InpRallyATR*a : rally<=L-InpRallyATR*a));
       int nTouch=ArraySize(tj);
       bool sweepB=SweepBefore(piv,h,l,c,first,lv[k].is_support,pierce);
       //--- hold after first touch (no body close through within window)?
       bool hold=true;
       for(int j=first-1;j>=MathMax(first-InpNoReturnBars,1);j--)
         {
          if(lv[k].is_support && c[j]<L) { hold=false; break; }
          if(!lv[k].is_support && c[j]>L) { hold=false; break; }
         }
       int strength=(sweepB?1:0)+(hold?1:0);
       if(rej>=2 && rallyOK)
          AddMark(mk,t[first],(lv[k].is_support?l[first]:h[first]),2,lv[k].is_support,
             "Type1",StringFormat("Type1 %dx rejection + rally @ %s",
                rej,DoubleToString(L,_Digits)));
       else if(rej==0 && sweepB)
          AddMark(mk,t[first],(lv[k].is_support?l[first]:h[first]),3,lv[k].is_support,
             "Type2",StringFormat("Type2 liquidity-backed hold @ %s",
                DoubleToString(L,_Digits)));
       if(nTouch>InpMaxWeakTouch && !displaced)
          AddMark(mk,t[first],(lv[k].is_support?l[first]:h[first]),4,lv[k].is_support,
             "WEAK",StringFormat("WEAK: %d touches, no displacement @ %s",
                nTouch,DoubleToString(L,_Digits)));
       //--- no-retest: single touch + displacement + no return
       if(nTouch==1 && displaced && hold)
          AddMark(mk,t[first],(lv[k].is_support?l[first]:h[first]),
             (lv[k].is_support?0:1),lv[k].is_support,
             (lv[k].is_support?"CV-nr":"CA-nr"),
             StringFormat("No-retest %s @ %s",
                lv[k].is_support?"drop-away buy":"drop-away sell",
                DoubleToString(L,_Digits)));
       //--- strength tag (always, at first touch)
       AddMark(mk,t[first],(lv[k].is_support?l[first]:h[first]),6,lv[k].is_support,
          StringFormat("S%d",strength),
          StringFormat("ZoneStrength %d/2 (sweep=%d hold=%d) @ %s",
             strength,(sweepB?1:0),(hold?1:0),DoubleToString(L,_Digits)));
      }
    //--- oldest -> newest by time (N small)
    for(int i=1;i<ArraySize(mk);i++)
      {
       SMark v=mk[i]; int j=i-1;
       while(j>=0 && mk[j].time>v.time) { mk[j+1]=mk[j]; j--; }
       mk[j+1]=v;
      }
   }

void DrawMarks(const SMark &mk[])
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    DeleteAllObjects();
    int n=ArraySize(mk);
    int start=(n>InpMaxMarks)?n-InpMaxMarks:0;
    for(int k=start;k<n;k++)
      {
       string nm=InpPrefix+mk[k].text+"_"+TimeToString(mk[k].time,TIME_DATE|TIME_MINUTES)+
                 "_"+IntegerToString(k);
       color clr=(mk[k].kind==4?InpWeakColor:(mk[k].bull?InpBullColor:InpBearColor));
       bool arrow=(mk[k].kind==0||mk[k].kind==1||mk[k].kind==5);
       if(arrow)
         {
          double apx=(mk[k].bull?mk[k].px-gap:mk[k].px+gap);
          ObjectCreate(0,nm,(mk[k].bull?OBJ_ARROW_UP:OBJ_ARROW_DOWN),0,mk[k].time,apx);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,mk[k].tip);
          continue;
         }
       if(!InpShowLabels) continue;
       ObjectCreate(0,nm,OBJ_TEXT,0,mk[k].time,
                    (mk[k].bull?mk[k].px-gap*3:mk[k].px+gap*3));
       ObjectSetString(0,nm,OBJPROP_TEXT,mk[k].text);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8);
       ObjectSetInteger(0,nm,OBJPROP_ANCHOR,
          (mk[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,mk[k].tip);
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
