//+------------------------------------------------------------------+
//|                                         MSNR_EMS_BOS_Sweep.mq5   |
//|              EMS Indicator E2: BOS vs Sweep splitter              |
//+------------------------------------------------------------------+
//| Rules (EMS #3:15-19, #7:34-36, indicatorplan E2):                 |
//|                                                                   |
//|  Levels: 2-candle S/R pivots, level = CLOSE of first candle       |
//|  (same engine as I1/I2/I7, so every BOS here matches an I7 BOS).  |
//|                                                                   |
//|  BOS  : candle BODY closes through the level:                     |
//|   resistance: close > level / support: close < level. First       |
//|   close-through per level only (same as I7 FindBreakouts).        |
//|  Sweep: wick pierces THROUGH the level (by >= InpMinPiercePips)   |
//|  but body closes back INSIDE:                                     |
//|   resistance: high > level+tol && close < level / support:        |
//|   low < level-tol && close > level. Only pre-break sweeps are     |
//|   marked (sweep -> BOS is the SMC sequence from #3:19).           |
//|                                                                   |
//|  Guarantee: a bar either closes through (BOS) or closes inside    |
//|  (sweep) - never both on the same bar/level. Closed bars only     |
//|  (j>=1) so markers never paint/vanish intraday.                   |
//|                                                                   |
//|  Rendering: pure marker (like E1 v1.50) - marks everything, no    |
//|  lifecycle, no rays. Sweep = THIN amber dashed line at the swept  |
//|  level (formation -> sweep bar), BOS = THIN solid full line at    |
//|  the broken level (formation -> BOS bar), green up / red down.    |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.50"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars = 500;               // Lookback bars
input int    InpMaxEvents    = 50;                // Max markers drawn per type (most recent)
input double InpMinPiercePips = 0.5;                // Min wick pierce past level for a valid sweep (pips)
input bool   InpShowSweeps   = true;              // Draw sweep (thin dashed) lines
input bool   InpShowBOS      = true;              // Draw BOS (thin solid) lines
input color  InpSweepColor   = clrOrange;         // Sweep line (amber)
input color  InpBOSBullColor = clrMediumSeaGreen; // BOS up tag
input color  InpBOSBearColor = clrTomato;         // BOS down tag
input string InpPrefix       = "MSNR_BS_";        // Object name prefix

struct SLevel
   {
    double   price;
    int      formed_idx;   // series index of confirming bar
    datetime formed_time;
    bool     is_support;
   };

struct SEvent
   {
    datetime time;
    double   anchor;      // arrow/tag anchor price
    double   ref_price;   // level price
    datetime lvl_time;    // level formation time
    int      dir;         // +1 bull, -1 bear
    bool     is_bos;      // true = BOS, false = sweep
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR BOS/Sweep");
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

    if(rates_total<3) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SEvent sweeps[], bosses[];
    FindEvents(time,open,high,low,close,sweeps,bosses);

    DrawEvents(sweeps,bosses,high,low,time);
    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels at close (same engine as I1/I2/I7)
void DetectLevels(const datetime &t[],const double &o[],const double &c[],int count,SLevel &lv[])
   {
    ArrayResize(lv,0);
    int scan=MathMin(count-2,ArraySize(t)-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       bool sup=(bear1&&bull2), res=(bull1&&bear2);
       if(!sup&&!res) continue;
       int n=ArraySize(lv);
       ArrayResize(lv,n+1);
       lv[n].price=c[i+1];
       lv[n].formed_idx=i;
       lv[n].formed_time=t[i];
       lv[n].is_support=sup;
      }
   }

void AppendEvent(SEvent &ev[],datetime t,double anchor,double ref,datetime lvlT,int dir,bool is_bos)
   {
    int n=ArraySize(ev);
    ArrayResize(ev,n+1);
    ev[n].time=t; ev[n].anchor=anchor; ev[n].ref_price=ref;
    ev[n].lvl_time=lvlT; ev[n].dir=dir; ev[n].is_bos=is_bos;
   }

//--- one pass per level: pre-break sweeps + first BOS. Closed bars only.
void FindEvents(const datetime &t[],const double &o[],const double &h[],
                const double &l[],const double &c[],SEvent &swp[],SEvent &bos[])
   {
    ArrayResize(swp,0); ArrayResize(bos,0);
    SLevel lv[];
    DetectLevels(t,o,c,ArraySize(t),lv);
    double pierce=InpMinPiercePips*((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    int LN=ArraySize(lv);

    for(int k=0;k<LN;k++)
      {
       // j walks newer in time (series index decreasing = forward in time)
       for(int j=lv[k].formed_idx-1;j>=1;j--)
         {
          if(lv[k].is_support)
            {
             // BOS down: full close below the level -> done with this level
             if(c[j]<lv[k].price)
               { AppendEvent(bos,t[j],c[j],lv[k].price,lv[k].formed_time,-1,true); break; }
             // sweep: wick actually pierces below the level, body back above
             if(l[j]<lv[k].price-pierce && c[j]>lv[k].price)
                AppendEvent(swp,t[j],l[j],lv[k].price,lv[k].formed_time,+1,false);
            }
          else
            {
             // BOS up: full close above the level -> done with this level
             if(c[j]>lv[k].price)
               { AppendEvent(bos,t[j],c[j],lv[k].price,lv[k].formed_time,+1,true); break; }
             // sweep: wick actually pierces above the level, body back below
             if(h[j]>lv[k].price+pierce && c[j]<lv[k].price)
                AppendEvent(swp,t[j],h[j],lv[k].price,lv[k].formed_time,-1,false);
            }
         }
      }
   }

void DrawEvents(const SEvent &swp[],const SEvent &bos[],
                const double &h[],const double &l[],const datetime &t[])
   {
    DeleteAllObjects();

     if(InpShowSweeps)
      {
       int n=ArraySize(swp);
       //--- arrays are newest-first (levels detected newest-first): take
       //--- the first InpMaxEvents entries = the most recent events
       int last=MathMin(n,InpMaxEvents);
       for(int i=0;i<last;i++)
          {
          datetime t1=swp[i].lvl_time;
          datetime t2=swp[i].time;
          double   px=swp[i].ref_price;
          if(t2<=t1) continue;
          string nm=InpPrefix+"swp_"+TimeToString(swp[i].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);
          bool bull=(swp[i].dir>0);
          //--- thin line at the swept level, formation -> sweep bar
          ObjectCreate(0,nm,OBJ_TREND,0,t1,px,t2,px);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,InpSweepColor);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DASH);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("Sweep %s lvl %s wicked %s, closed back inside @ %s (level formed %s)",
                bull?"up (support)":"down (resistance)",
                DoubleToString(swp[i].ref_price,_Digits),
                DoubleToString(swp[i].anchor,_Digits),
                TimeToString(swp[i].time),TimeToString(swp[i].lvl_time)));
         }
      }

     if(InpShowBOS)
      {
       int n=ArraySize(bos);
       //--- newest-first: take the first InpMaxEvents entries
       int last=MathMin(n,InpMaxEvents);
       for(int i=0;i<last;i++)
          {
          datetime t1=bos[i].lvl_time;
          datetime t2=bos[i].time;
          double   px=bos[i].ref_price;
          if(t2<=t1) continue;
          string nm=InpPrefix+"bos_"+TimeToString(bos[i].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);
          bool bull=(bos[i].dir>0);
          //--- THIN solid full line at the broken level, formation -> BOS bar
          ObjectCreate(0,nm,OBJ_TREND,0,t1,px,t2,px);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,bull?InpBOSBullColor:InpBOSBearColor);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("BOS %s: broke %s @ %s (level formed %s)",
                bull?"up":"down",DoubleToString(bos[i].ref_price,_Digits),
                TimeToString(bos[i].time),TimeToString(bos[i].lvl_time)));
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
