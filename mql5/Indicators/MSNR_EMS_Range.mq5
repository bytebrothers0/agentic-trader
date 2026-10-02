//+------------------------------------------------------------------+
//|                                           MSNR_EMS_Range.mq5     |
//|              EMS Indicator E4: IRL/ERL Range + TP reference       |
//+------------------------------------------------------------------+
//| Rules (EMS Part 1 §5, #7:49-53, indicatorplan E4):                |
//|                                                                   |
//|  External range (ERL) = extremum since the last BOS: highest high |
//|  and lowest low over the current leg (last BOS -> now). The leg   |
//|  direction is the direction of that BOS.                          |
//|  Internal range (IRL) = the swings in between: fractal pivots     |
//|  inside the leg window, drawn as short nested segments.           |
//|  TP = the ERL boundary opposite the entry side: bull leg (enter   |
//|  low) -> TP at ERL high; bear leg (enter high) -> TP at ERL low.  |
//|  Price moves IRL -> ERL (#7:49-53).                               |
//|                                                                   |
//|  BOS definition matches E2/I7 (first body close through a 2-candle|
//|  S/R level). Pivots match E3 (wick fractals). Closed bars only.   |
//|                                                                   |
//|  Rendering: ONE outer border box spanning the current leg, nested |
//|  inner swing segments, dashed TP line with TP label. No rays.     |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (bars each side)
input bool   InpShowOuter     = true;              // Draw outer ERL box
input bool   InpShowInner     = true;              // Draw inner IRL swing segments
input bool   InpShowTP        = true;              // Draw TP reference line
input bool   InpShowLabels    = true;              // Show ERL / TP labels
input color  InpBullColor     = clrDodgerBlue;     // Bull-leg box
input color  InpBearColor     = clrTomato;         // Bear-leg box
input color  InpNoneColor     = clrGray;           // No-BOS fallback box
input color  InpInnerColor    = clrOrange;         // Inner swing segments (amber)
input color  InpTPColor       = clrGold;           // TP reference line
input string InpPrefix        = "MSNR_RG_";        // Object name prefix

struct SLevel
   {
    double   price;
    int      formed_idx;
    datetime formed_time;
    bool     is_support;
   };

struct SBos
   {
    datetime time;
    int      dir;   // +1 up, -1 down
   };

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Range (IRL/ERL)");
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

    DeleteAllObjects();

    //--- 1) BOS list (E2 parity: first close-through per 2-candle level)
    SBos bosses[];
    FindBOS(time,open,close,bosses);

    //--- 2) current leg window
    datetime legStart=time[MathMin(InpLookbackBars,rates_total-1)];
    int legDir=0;
    if(ArraySize(bosses)>0)
      {
       legStart=bosses[ArraySize(bosses)-1].time;
       legDir=bosses[ArraySize(bosses)-1].dir;
      }

    //--- 3) external range over the leg window (series 1..startIdx)
    int startIdx=FindBar(time,legStart,rates_total);
    if(startIdx<2) startIdx=2;
    double erlHigh=high[1], erlLow=low[1];
    for(int j=1;j<=startIdx;j++)
      {
       if(high[j]>erlHigh) erlHigh=high[j];
       if(low[j]<erlLow)   erlLow=low[j];
      }
    if(erlHigh-erlLow<_Point) erlHigh=erlLow+_Point;

    datetime now=time[0];
    color boxClr=(legDir>0)?InpBullColor:(legDir<0?InpBearColor:InpNoneColor);

    if(InpShowOuter)
      {
       string nm=InpPrefix+"ERL_"+TimeToString(legStart,TIME_DATE|TIME_MINUTES);
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,legStart,erlHigh,now,erlLow);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,boxClr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm,OBJPROP_FILL,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("ERL %s [%s..%s] | leg %s -> now%s",
             legDir>0?"bull leg":legDir<0?"bear leg":"no BOS in lookback",
             DoubleToString(erlHigh,_Digits),DoubleToString(erlLow,_Digits),
             TimeToString(legStart),
             legDir==0?" | showing full window":""));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,legStart,erlHigh);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             legDir>0?"ERL bull":legDir<0?"ERL bear":"ERL");
          ObjectSetInteger(0,ln,OBJPROP_COLOR,boxClr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
      }

    //--- 4) inner swings: pivots strictly inside the leg window
    if(InpShowInner)
      {
       SPivot piv[];
       FindPivots(high,low,time,rates_total,piv);
       int stepSec=(int)PeriodSeconds(Period());
       for(int p=0;p<ArraySize(piv);p++)
         {
          if(piv[p].time<=legStart) continue;
          datetime s1=piv[p].time-2*stepSec, s2=piv[p].time+2*stepSec;
          if(s1<legStart) s1=legStart;
          if(s2>now) s2=now;
          if(s2<=s1) continue;
          string nm=InpPrefix+"IRL_"+TimeToString(piv[p].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(p);
          ObjectCreate(0,nm,OBJ_TREND,0,s1,piv[p].price,s2,piv[p].price);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,InpInnerColor);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DOT);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("IRL %s %s @ %s",
                piv[p].is_high?"swing high":"swing low",
                DoubleToString(piv[p].price,_Digits),TimeToString(piv[p].time)));
         }
      }

    //--- 5) TP: ERL boundary opposite the entry side
    if(InpShowTP && legDir!=0)
      {
       double tp=(legDir>0)?erlHigh:erlLow;
       string nm=InpPrefix+"TP_"+TimeToString(legStart,TIME_DATE|TIME_MINUTES);
       ObjectCreate(0,nm,OBJ_TREND,0,legStart,tp,now,tp);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,InpTPColor);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DASH);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,false);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("TP (%s leg): ERL %s @ %s",
             legDir>0?"bull":"bear",DoubleToString(tp,_Digits),TimeToString(legStart)));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,now,tp);
          ObjectSetString(0,ln,OBJPROP_TEXT,"TP "+DoubleToString(tp,_Digits));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,InpTPColor);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             legDir>0?ANCHOR_RIGHT_LOWER:ANCHOR_RIGHT_UPPER);
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
      }

    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels (I1/I2/I7 engine)
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

//--- first close-through per level, ascending by time (oldest -> newest)
void FindBOS(const datetime &t[],const double &o[],const double &c[],SBos &bos[])
   {
    ArrayResize(bos,0);
    SLevel lv[];
    DetectLevels(t,o,c,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       for(int j=lv[k].formed_idx-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price)
            { int n=ArraySize(bos); ArrayResize(bos,n+1); bos[n].time=t[j]; bos[n].dir=-1; break; }
          if(!lv[k].is_support && c[j]>lv[k].price)
            { int n=ArraySize(bos); ArrayResize(bos,n+1); bos[n].time=t[j]; bos[n].dir=+1; break; }
         }
      }
    // insertion sort ascending (N small)
    for(int i=1;i<ArraySize(bos);i++)
      {
       SBos v=bos[i]; int j=i-1;
       while(j>=0 && bos[j].time>v.time) { bos[j+1]=bos[j]; j--; }
       bos[j+1]=v;
      }
   }

//--- wick-fractal pivots with alternation (E3 parity)
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
       piv[n].time=t[i]; piv[n].idx=i;
      }
    int m=ArraySize(piv);
    for(int a=1;a<m;a++)
      {
       if(piv[a].is_high==piv[a-1].is_high)
         {
          bool keepA=piv[a].is_high ? (piv[a].price>=piv[a-1].price)
                                    : (piv[a].price<=piv[a-1].price);
          if(keepA) piv[a-1]=piv[a];
          for(int b=a+1;b<m;b++) piv[b-1]=piv[b];
          m--; a--;
         }
      }
    ArrayResize(piv,m);
   }

int FindBar(const datetime &t[],datetime need,int rates_total)
   {
    for(int i=0;i<rates_total;i++)
       if(t[i]<=need) return(i);
    return(rates_total-1);
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
