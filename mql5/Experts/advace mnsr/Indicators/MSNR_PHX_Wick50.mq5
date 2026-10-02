//+------------------------------------------------------------------+
//|                                             MSNR_PHX_Wick50.mq5  |
//|              PHX Indicator 5: institutional 50%-wick POIs          |
//+------------------------------------------------------------------+
//| Rules (Phoenix Part 8 + PDF wick-tip / 50% wick / OCL+50%):        |
//|                                                                    |
//|  Qualifier: single-side wick >= InpMinWickPips AND >=              |
//|  InpWickBodyMult x body, on a structural bar - a BOS bar (first   |
//|  body-close breakout of a 2-candle level, E2 parity) or a TS bar   |
//|  (wick rejection of a fractal swing, PHX1 parity). Part 8 §2.1     |
//|  filter: random long wicks without structure are ignored.          |
//|  Levels per Part 8 formula:                                        |
//|   bear rejection (long upper wick): mid = (High + MaxOC) / 2,      |
//|   bull rejection (long lower wick): mid = (Low + MinOC) / 2.       |
//|  Wick-tip line = SL reference (thesis dead past the tip).          |
//|  `OCL+50%` tag when mid aligns with an OCL (two consecutive        |
//|  same-color candles, line at first close - I3 parity).             |
//|  Mitigation: mid line ends at first close through mid; tip line    |
//|  at first close through tip; else both run to now.                 |
//|                                                                    |
//|  Rendering: pure marker - solid midlines (gold, width 2 when       |
//|  OCL-tagged), dotted tip ticks. Most-recent cap. Closed bars       |
//|  only. No rays.                                                    |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (swings + S/R)
input double InpMinWickPips   = 5.0;               // Min wick length (pips)
input double InpWickBodyMult  = 3.0;               // Wick >= mult x body
input double InpMinPiercePips = 0.5;               // Min pierce for TS check (pips)
input double InpOCLTolPips    = 2.0;               // OCL alignment tolerance (pips)
input int    InpMaxMids       = 30;                // Max midlines drawn (most recent)
input bool   InpShowTips      = true;              // Draw wick-tip SL lines
input bool   InpShowLabels    = true;              // Label OCL+50% confluences
input color  InpMidColor      = clrGoldenrod;      // 50% midline
input color  InpOCLColor      = clrMediumVioletRed;// OCL-tagged midline
input color  InpTipColor      = clrGray;           // Wick-tip line (dotted)
input string InpPrefix        = "MSNR_W50_";       // Object name prefix

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;
   };

struct SLevel
   {
    double   price;
    int      formed_idx;
    bool     is_support;
   };

struct SWick
   {
    datetime t1;         // signal bar time
    double   mid;        // 50% level
    double   tip;        // wick extreme (SL reference)
    datetime tMidEnd;    // first close through mid, 0 = active
    datetime tTipEnd;    // first close through tip, 0 = intact
    bool     bear;       // true = upper-wick rejection
    bool     ocl;        // OCL+50% confluence
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Wick50");
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

    if(rates_total<2*InpPivotStrength+3) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SWick w[];
    FindWicks(time,open,high,low,close,rates_total,w);

    DrawWicks(w,time[0]);
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

//--- 2-candle S/R levels (I1/I2/E2 parity)
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
       lv[n].is_support=sup;
      }
   }

//--- OCL levels: two consecutive same-color candles, line at first close (I3 parity)
void DetectOCLs(const double &o[],const double &c[],int rates_total,double &ocl[])
   {
    ArrayResize(ocl,0);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       if((IsBullC(o,c,i) && IsBullC(o,c,i+1)) ||
          (IsBearC(o,c,i) && IsBearC(o,c,i+1)))
         {
          int n=ArraySize(ocl);
          ArrayResize(ocl,n+1); ocl[n]=c[i+1];
         }
      }
   }

void FindWicks(const datetime &t[],const double &o[],const double &h[],
               const double &l[],const double &c[],int rates_total,SWick &w[])
   {
    ArrayResize(w,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double minWick=InpMinWickPips*pip;
    double pierce =InpMinPiercePips*pip;
    double oclTol =InpOCLTolPips*pip;

    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);

    //--- BOS-bar map (first break per bar, either direction)
    int maxScan=MathMin(InpLookbackBars,rates_total-3);
    bool bosBar[];
    ArrayResize(bosBar,maxScan+1); ArrayInitialize(bosBar,false);
    SLevel lv[];
    DetectLevels(t,o,c,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       for(int j=F-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price)
            { if(j<=maxScan) bosBar[j]=true; break; }
          if(!lv[k].is_support && c[j]>lv[k].price)
            { if(j<=maxScan) bosBar[j]=true; break; }
         }
      }

    double ocl[];
    DetectOCLs(o,c,rates_total,ocl);

    for(int i=maxScan;i>=1;i--)
      {
       double maxOC=MathMax(o[i],c[i]);
       double minOC=MathMin(o[i],c[i]);
       double upW=h[i]-maxOC, loW=minOC-l[i], body=maxOC-minOC;
       //--- structural? (BOS bar, or TS of a fractal swing)
       bool structBar=bosBar[i];
       if(!structBar)
         {
          for(int p=ArraySize(piv)-1;p>=0;p--)
            {
             if(piv[p].idx<=i) continue;
             if(piv[p].is_high && h[i]>piv[p].price+pierce && c[i]<piv[p].price)
               { structBar=true; break; }
             if(!piv[p].is_high && l[i]<piv[p].price-pierce && c[i]>piv[p].price)
               { structBar=true; break; }
            }
         }
       if(!structBar) continue;
       //--- bear rejection (upper wick)
       if(upW>=minWick && upW>=InpWickBodyMult*body)
          AddWick(w,t,h,l,c,ocl,i,(h[i]+maxOC)/2.0,h[i],true,oclTol);
       //--- bull rejection (lower wick)
       if(loW>=minWick && loW>=InpWickBodyMult*body)
          AddWick(w,t,h,l,c,ocl,i,(l[i]+minOC)/2.0,l[i],false,oclTol);
      }
   }

void AddWick(SWick &w[],const datetime &t[],const double &h[],const double &l[],
             const double &c[],const double &ocl[],int i,double mid,double tip,
             bool bear,double oclTol)
   {
    SWick x;
    x.t1=t[i]; x.mid=mid; x.tip=tip; x.bear=bear;
    x.tMidEnd=0; x.tTipEnd=0;
    x.ocl=false;
    for(int q=0;q<ArraySize(ocl);q++)
       if(MathAbs(ocl[q]-mid)<=oclTol) { x.ocl=true; break; }
    for(int j=i-1;j>=1;j--)
      {
       if(x.tMidEnd==0)
         {
          if(bear && c[j]>mid) x.tMidEnd=t[j];
          if(!bear && c[j]<mid) x.tMidEnd=t[j];
         }
       if(x.tTipEnd==0)
         {
          if(bear && c[j]>tip) x.tTipEnd=t[j];
          if(!bear && c[j]<tip) x.tTipEnd=t[j];
         }
       if(x.tMidEnd!=0 && x.tTipEnd!=0) break;
      }
    int n=ArraySize(w);
    ArrayResize(w,n+1); w[n]=x;
   }

void DrawWicks(const SWick &w[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(w);
    int start=(n>InpMaxMids)?n-InpMaxMids:0;
    for(int k=start;k<n;k++)
      {
       datetime mEnd=(w[k].tMidEnd==0?now:w[k].tMidEnd);
       if(mEnd<=w[k].t1) continue;
       string nm=InpPrefix+(w[k].bear?"bear_":"bull_")+
                 TimeToString(w[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color mc=(w[k].ocl?InpOCLColor:InpMidColor);

       ObjectCreate(0,nm+"_mid",OBJ_TREND,0,w[k].t1,w[k].mid,mEnd,w[k].mid);
       ObjectSetInteger(0,nm+"_mid",OBJPROP_COLOR,mc);
       ObjectSetInteger(0,nm+"_mid",OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm+"_mid",OBJPROP_WIDTH,(w[k].ocl?2:1));
       ObjectSetInteger(0,nm+"_mid",OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm+"_mid",OBJPROP_BACK,false);
       ObjectSetInteger(0,nm+"_mid",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm+"_mid",OBJPROP_TOOLTIP,
          StringFormat("50%% wick %s %s | tip %s | formed %s -> %s%s%s",
             w[k].bear?"bear":"bull",DoubleToString(w[k].mid,_Digits),
             DoubleToString(w[k].tip,_Digits),TimeToString(w[k].t1),TimeToString(mEnd),
             w[k].tMidEnd==0?" | ACTIVE":" | MITIGATED",
             w[k].ocl?" | OCL+50%":""));

       if(InpShowTips)
         {
          datetime pEnd=(w[k].tTipEnd==0?now:w[k].tTipEnd);
          if(pEnd>w[k].t1)
            {
             ObjectCreate(0,nm+"_tip",OBJ_TREND,0,w[k].t1,w[k].tip,pEnd,w[k].tip);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_COLOR,InpTipColor);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_STYLE,STYLE_DOT);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_WIDTH,1);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_RAY_RIGHT,false);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_BACK,true);
             ObjectSetInteger(0,nm+"_tip",OBJPROP_SELECTABLE,true);
             ObjectSetString(0,nm+"_tip",OBJPROP_TOOLTIP,
                StringFormat("Wick-tip SL ref %s (%s)%s",
                   DoubleToString(w[k].tip,_Digits),TimeToString(w[k].t1),
                   w[k].tTipEnd==0?" | INTACT":" | VIOLATED - thesis dead"));
            }
         }

       if(InpShowLabels && w[k].ocl)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,w[k].t1,w[k].mid);
          ObjectSetString(0,ln,OBJPROP_TEXT,"50%+OCL");
          ObjectSetInteger(0,ln,OBJPROP_COLOR,mc);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (w[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
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
