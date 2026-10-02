//+------------------------------------------------------------------+
//|                                                  MSNR_EMS_CRT.mq5 |
//|              EMS Indicator E7: CRT 3-candle setup                 |
//+------------------------------------------------------------------+
//| Rules (EMS _EMS#ENGULFING #MSNR#SMC:15-25, EMS.md §3, plan E7):    |
//|                                                                    |
//|  For each FRESH 2-candle S/R level (I1/I2 parity; QM levels plug   |
//|  in via the future MSNR_SwingStore include):                       |
//|   1) Tap candle A touches the level (wick into the level zone).    |
//|   2) Indecision candle B: body <= InpBodyMaxPct of its range       |
//|      (30% default = Doji / spinning top); its range H/L overlaps   |
//|      the level zone, so the sequence sits on/into the level.       |
//|   3) Candle C sweeps the range edge by >= InpMinSweepPips and      |
//|      closes back past it (bull: low[C] < rangeLo, close[C] >       |
//|      rangeLo; bear mirror). Wicks alone do not count.              |
//|                                                                    |
//|  Side-consistent only: support levels -> CRT Bull (sweep of range  |
//|  low = sell-side grab at a V-shape), resistance -> CRT Bear.       |
//|  Fresh = no body-close through the level between formation and C   |
//|  (E2/E5 parity). Later breaks do not erase the marker.             |
//|                                                                    |
//|  Rendering: pure marker, no rays - highlight box over A->C at the  |
//|  range, range H/L lines (swept edge thick), CRT Bull/Bear label.   |
//|  Most-recent cap honored. Closed bars only.                        |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpMaxSetups     = 50;                // Max setups drawn (most recent)
input double InpBodyMaxPct    = 30.0;              // Max body % of range for indecision
input double InpTouchPips     = 2.0;               // Level zone half-width (pips)
input double InpMinSweepPips  = 0.5;               // Min sweep past range edge (pips, E2 parity)
input bool   InpShowHighlight = true;              // Draw triplet highlight box
input bool   InpShowRange     = true;              // Draw range H/L lines
input bool   InpShowLabels    = true;              // Show CRT Bull/Bear labels
input color  InpBullColor     = clrDodgerBlue;     // Bull CRT line/label
input color  InpBearColor     = clrTomato;         // Bear CRT line/label
input color  InpBullFill      = clrLightSkyBlue;   // Bull highlight shade
input color  InpBearFill      = clrMistyRose;      // Bear highlight shade
input string InpPrefix        = "MSNR_CRT_";       // Object name prefix

struct SLevel
   {
    double   price;
    int      formed_idx;
    datetime formed_time;
    bool     is_support;
   };

struct SCrt
   {
    datetime tA;         // tap candle time
    datetime tC;         // sweep/confirmation candle time
    double   rangeHi;
    double   rangeLo;
    double   lvlPrice;
    bool     bull;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR CRT");
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

    if(rates_total<5) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SCrt setups[];
    FindCRTs(time,open,high,low,close,rates_total,setups);

    DrawCRTs(setups);
    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels at close (I1/I2/I7 engine, E2/E4/E5 parity)
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

void AppendCRT(SCrt &s[],datetime tA,datetime tC,double rHi,double rLo,
               double lvl,bool bull)
   {
    int n=ArraySize(s);
    ArrayResize(s,n+1);
    s[n].tA=tA; s[n].tC=tC; s[n].rangeHi=rHi; s[n].rangeLo=rLo;
    s[n].lvlPrice=lvl; s[n].bull=bull;
   }

//--- per fresh level: tap -> indecision -> sweep & close-back
void FindCRTs(const datetime &t[],const double &o[],const double &h[],
              const double &l[],const double &c[],int rates_total,SCrt &s[])
   {
    ArrayResize(s,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double tol=InpTouchPips*pip;
    double sw =InpMinSweepPips*pip;
    double bodyMax=InpBodyMaxPct/100.0;

    SLevel lv[];
    DetectLevels(t,o,c,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       if(F<3) continue;   // no room for a triplet after formation
       //--- oldest close-through since formation (freshness boundary)
       int B=-1;
       for(int j=F-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price) { B=j; break; }
          if(!lv[k].is_support && c[j]>lv[k].price) { B=j; break; }
         }
       int cMax=MathMin(F-2,rates_total-3);
       for(int ci=cMax;ci>=1;ci--)
         {
          // older setups only get staler: once C is at/before the break, stop
          if(B!=-1 && B>=ci) break;
          int a=ci+2, b=ci+1;
          double rHi=h[b], rLo=l[b], total=rHi-rLo;
          if(total<=0) continue;
          if(MathAbs(c[b]-o[b])>bodyMax*total) continue;   // not indecision
          //--- range must sit on/into the level zone
          if(!(rLo<=lv[k].price+tol && rHi>=lv[k].price-tol)) continue;
          if(lv[k].is_support)
            {
             if(l[a]>lv[k].price+tol) continue;            // A never tapped
             if(!(l[ci]<rLo-sw && c[ci]>rLo)) continue;    // sweep low + close back
             AppendCRT(s,t[a],t[ci],rHi,rLo,lv[k].price,true);
            }
          else
            {
             if(h[a]<lv[k].price-tol) continue;            // A never tapped
             if(!(h[ci]>rHi+sw && c[ci]<rHi)) continue;    // sweep high + close back
             AppendCRT(s,t[a],t[ci],rHi,rLo,lv[k].price,false);
            }
         }
      }
    //--- sort ascending by confirmation time (N small)
    for(int i=1;i<ArraySize(s);i++)
      {
       SCrt v=s[i]; int j=i-1;
       while(j>=0 && s[j].tC>v.tC) { s[j+1]=s[j]; j--; }
       s[j+1]=v;
      }
   }

void DrawCRTs(const SCrt &s[])
   {
    DeleteAllObjects();
    int n=ArraySize(s);
    int start=(n>InpMaxSetups)?n-InpMaxSetups:0;
    for(int k=start;k<n;k++)
      {
       datetime t1=s[k].tA, t2=s[k].tC;
       if(t2<=t1) continue;
       string nm=InpPrefix+(s[k].bull?"bull_":"bear_")+
                 TimeToString(t2,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color ln=(s[k].bull?InpBullColor:InpBearColor);

       if(InpShowHighlight)
         {
          string bx=nm+"_box";
          ObjectCreate(0,bx,OBJ_RECTANGLE,0,t1,s[k].rangeHi,t2,s[k].rangeLo);
          ObjectSetInteger(0,bx,OBJPROP_COLOR,(s[k].bull?InpBullFill:InpBearFill));
          ObjectSetInteger(0,bx,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,bx,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,bx,OBJPROP_FILL,true);
          ObjectSetInteger(0,bx,OBJPROP_BACK,true);
          ObjectSetInteger(0,bx,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,bx,OBJPROP_TOOLTIP,
             StringFormat("CRT %s triplet %s -> %s | range [%s..%s] at level %s",
                s[k].bull?"Bull":"Bear",TimeToString(t1),TimeToString(t2),
                DoubleToString(s[k].rangeHi,_Digits),
                DoubleToString(s[k].rangeLo,_Digits),
                DoubleToString(s[k].lvlPrice,_Digits)));
         }

       if(InpShowRange)
         {
          //--- swept edge thick, opposite edge thin
          string hi=nm+"_rh", lo=nm+"_rl";
          ObjectCreate(0,hi,OBJ_TREND,0,t1,s[k].rangeHi,t2,s[k].rangeHi);
          ObjectSetInteger(0,hi,OBJPROP_COLOR,ln);
          ObjectSetInteger(0,hi,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,hi,OBJPROP_WIDTH,(s[k].bull?1:2));
          ObjectSetInteger(0,hi,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,hi,OBJPROP_BACK,false);
          ObjectSetInteger(0,hi,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,hi,OBJPROP_TOOLTIP,
             StringFormat("CRT range high %s",DoubleToString(s[k].rangeHi,_Digits)));
          ObjectCreate(0,lo,OBJ_TREND,0,t1,s[k].rangeLo,t2,s[k].rangeLo);
          ObjectSetInteger(0,lo,OBJPROP_COLOR,ln);
          ObjectSetInteger(0,lo,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,lo,OBJPROP_WIDTH,(s[k].bull?2:1));
          ObjectSetInteger(0,lo,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,lo,OBJPROP_BACK,false);
          ObjectSetInteger(0,lo,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,lo,OBJPROP_TOOLTIP,
             StringFormat("CRT range low %s",DoubleToString(s[k].rangeLo,_Digits)));
         }

       if(InpShowLabels)
         {
          string lb=nm+"_lbl";
          double px=(s[k].bull?s[k].rangeLo:s[k].rangeHi);
          ObjectCreate(0,lb,OBJ_TEXT,0,t2,px);
          ObjectSetString(0,lb,OBJPROP_TEXT,(s[k].bull?"CRT Bull":"CRT Bear"));
          ObjectSetInteger(0,lb,OBJPROP_COLOR,ln);
          ObjectSetInteger(0,lb,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,lb,OBJPROP_ANCHOR,
             (s[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
          ObjectSetInteger(0,lb,OBJPROP_BACK,true);
          ObjectSetInteger(0,lb,OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
