//+------------------------------------------------------------------+
//|                                        MSNR_EMS_Liquidity.mq5    |
//|              EMS Indicator E3: Pullback Liquidity (Inducement)    |
//+------------------------------------------------------------------+
//| Rules (EMS #4:10-13, correction line 13, indicatorplan E3):       |
//|                                                                   |
//|  Pullback liquidity = the extreme of each pullback inside a leg:  |
//|   bull leg: lowest low of the pullback  = IND lo (sell-side liq)  |
//|   bear leg: highest high of the pullback = IND hi (buy-side liq)  |
//|  Pullbacks are read from pivots: a HIGHER pivot low = bull-leg    |
//|  pullback, a LOWER pivot high = bear-leg pullback.                |
//|                                                                   |
//|  Sweep = first FULL close beyond the line (wicks alone do NOT     |
//|  sweep, same close-through philosophy as E1/E2). Line runs from   |
//|  the pullback bar until its sweep bar, or until now if un-swept.  |
//|                                                                   |
//|  Inducement = the nearest UN-SWEPT line on the current leg: bull  |
//|  leg -> closest IND lo below price, bear leg -> closest IND hi    |
//|  above price. That is the "sweep this first" level for the EA.    |
//|                                                                   |
//|  Rendering: pure marker - one amber line per pullback, thin solid |
//|  while active, dotted once swept; inducement is thick + labelled  |
//|  INDUCT. Closed bars only.                                        |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (bars each side, highs/lows)
input int    InpMaxLines      = 50;               // Max lines drawn (most recent)
input bool   InpShowLabels    = true;              // Show IND / INDUCT labels
input color  InpLiqColor      = clrOrange;         // Pullback liquidity line (amber)
input color  InpSweptColor    = clrGray;           // Swept line color
input string InpPrefix        = "MSNR_LQ_";        // Object name prefix

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;        // series index
   };

struct SLiq
   {
    double   price;
    datetime t1;         // pullback bar time (line start)
    datetime t2;         // sweep bar time, 0 = un-swept (extends to now)
    bool     bull;       // true = IND lo (bull leg), false = IND hi
    bool     inducement;  // nearest un-swept on current leg
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Liquidity (IND/Inducement)");
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

    if(rates_total<2*InpPivotStrength+3) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SPivot piv[];
    FindPivots(high,low,time,rates_total,piv);

    SLiq lines[];
    BuildLines(piv,close,time,rates_total,lines);

    FlagInducement(lines,close);

    DrawLines(lines,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- fractal pivots on wick highs/lows, alternating, oldest -> newest
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
       // prefer the stronger extreme if a bar is both (rare)
       if(isHigh && isLow)
         {
          double hiRange=h[i]-l[i];
          if(hiRange<=0) continue;
          // keep both would break alternation; keep the higher-side by body dir
          // (simple: keep high, low comes from neighbours)
          isLow=false;
         }
       int n=ArraySize(piv);
       ArrayResize(piv,n+1);
       piv[n].is_high=isHigh;
       piv[n].price=isHigh?h[i]:l[i];
       piv[n].time=t[i];
       piv[n].idx=i;
      }

    //--- enforce alternation: same type twice -> keep most extreme
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

//--- higher low -> IND lo, lower high -> IND hi; sweep on first close beyond
void BuildLines(const SPivot &piv[],const double &close[],const datetime &time[],
                int rates_total,SLiq &lines[])
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
             SLiq x;
             x.price=piv[p].price; x.t1=piv[p].time; x.t2=0;
             x.bull=true; x.inducement=false;
             // sweep: first close below (bars after the pivot, closed only)
             for(int j=piv[p].idx-1;j>=1;j--)
                if(close[j]<x.price) { x.t2=time[j]; break; }
             int n=ArraySize(lines);
             ArrayResize(lines,n+1); lines[n]=x;
            }
          haveLow=true; prevLow=piv[p].price;
         }
       else
         {
          if(haveHigh && piv[p].price<prevHigh)
            {
             SLiq x;
             x.price=piv[p].price; x.t1=piv[p].time; x.t2=0;
             x.bull=false; x.inducement=false;
             for(int j=piv[p].idx-1;j>=1;j--)
                if(close[j]>x.price) { x.t2=time[j]; break; }
             int n=ArraySize(lines);
             ArrayResize(lines,n+1); lines[n]=x;
            }
          haveHigh=true; prevHigh=piv[p].price;
         }
      }
   }

//--- current leg = type of most recent pullback; inducement = nearest
//--- un-swept line on that leg (below price for bull, above for bear)
void FlagInducement(SLiq &lines[],const double &close[])
   {
    int n=ArraySize(lines);
    if(n==0) return;
    bool legBull=lines[n-1].bull;
    double ref=close[1];
    int best=-1;
    for(int k=0;k<n;k++)
      {
       if(lines[k].t2!=0) continue;              // swept
       if(lines[k].bull!=legBull) continue;      // wrong leg
       if(legBull)
         {
          if(lines[k].price>=ref) continue;      // must sit below price
          if(best<0 || lines[k].price>lines[best].price) best=k;
         }
       else
         {
          if(lines[k].price<=ref) continue;      // must sit above price
          if(best<0 || lines[k].price<lines[best].price) best=k;
         }
      }
    if(best>=0) lines[best].inducement=true;
   }

void DrawLines(const SLiq &lines[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(lines);
    int start=(n>InpMaxLines)?n-InpMaxLines:0;
    for(int k=start;k<n;k++)
      {
       datetime t1=lines[k].t1;
       datetime t2=(lines[k].t2==0)?now:lines[k].t2;
       if(t2<=t1) continue;
       bool swept=(lines[k].t2!=0);

       string nm=InpPrefix+(lines[k].bull?"lo_":"hi_")+
                 TimeToString(t1,TIME_DATE|TIME_MINUTES)+"_"+
                 DoubleToString(lines[k].price,_Digits);

       color clr=swept?InpSweptColor:InpLiqColor;
       ObjectCreate(0,nm,OBJ_TREND,0,t1,lines[k].price,t2,lines[k].price);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,swept?STYLE_DOT:STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,lines[k].inducement?2:1);
       ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("%s %.5f | %s -> %s%s%s",
             lines[k].bull?"IND lo (bull pullback)":"IND hi (bear pullback)",
             lines[k].price,TimeToString(t1),TimeToString(t2),
             swept?" | swept":" | UN-SWEPT",
             lines[k].inducement?" | INDUCT: sweep this first":""));

       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,t1,lines[k].price);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             (lines[k].bull?"IND lo":"IND hi")+(lines[k].inducement?" INDUCT":""));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             lines[k].bull?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER);
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
