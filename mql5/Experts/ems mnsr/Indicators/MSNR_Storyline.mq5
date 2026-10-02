//+------------------------------------------------------------------+
//|                                             MSNR_Storyline.mq5   |
//|                         Advanced MSNR - Indicator 7              |
//|         Storyline: X rejects X (fresh) + Y breakout              |
//+------------------------------------------------------------------+
//| Rules (Video 4 + Video 8 variant):                                |
//|  Bull: X wicks into a FRESH X Support (low touches, close above)  |
//|        then Y closes above a Y Resistance (BOS up).               |
//|  Bear: X wicks into a FRESH X Resistance (high touches, close     |
//|        below) then Y closes below a Y Support (BOS down).         |
//|                                                                   |
//|  Pairs (standard ladder): MN rejects MN + W1 breakout,            |
//|  W1 rejects W1 + D1 breakout, D1 rejects D1 + H4 breakout.        |
//|  Video 8 variant (X rejects X + X breakout) is visible when the   |
//|  user attaches this to X itself: rejection + breakout markers     |
//|  on the same TF still paint.                                      |
//|                                                                   |
//|  v1.10 drawing: thin zone-lines replace arrow clutter (optional).   |
//|  Rejection line: horizontal thin segment at the rejected X level,    |
//|  from level formation -> rejection wick bar. BOS line: horizontal    |
//|  thin segment at the broken Y level, from Y-level formation ->       |
//|  body-break bar. One price, one start, one end per event.            |
//|                                                                   |
//|  Modes: InpFollowChart=true -> pair tracks the chart TF             |
//|  (X=chart, Y=one step lower), so switching TFs walks the ladder    |
//|  and each leg is inspected where its candles align.                 |
//|  false -> classic 3-row MN/W1 + W1/D1 + D1/H4 panel.                 |
//|                                                                   |
//|  v1 scope: rejections only on S/R (2-candle pivots at close).     |
//|  QM rejections (Video 9: S/R/RBS/SBR/QM all valid, QM slightly    |
//|  weaker) are I7-v2 — see tooltip "level=S/R".                     |
//|  Freshness: no wick touch between formation and rejection bar.    |
//|  Recalc semantics (v1.30): rebuild on chart new bar, chart TF      |
//|  change, OR any X/Y leg printing a new bar (tier clocks) — e.g.    |
//|  the H4 BOS leg keeps progressing intraday on a D1 chart instead   |
//|  of waiting for the next daily bar. Scans use CLOSED bars only,    |
//|  so the day-end state is final: nothing paints or vanishes on the  |
//|  forming bar. A confirmed bias persists when a newer same-direction|
//|  rejection pends (new setup ≠ bias flip); only an opposite-side    |
//|  confirmation or newer opposite rejection changes the board.       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.30"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input bool   InpFollowChart        = true;               // Follow chart TF (X=chart, Y=one step lower)
input int    InpLookbackX          = 150;               // Lookback bars per X TF (rejection leg)
input int    InpLookbackY          = 400;               // Lookback bars per Y TF (breakout leg)
input double InpTolerancePips      = 2.0;               // Wick/close tolerance (pips)
input int    InpMaxEvents          = 50;                // Max rejection/breakout markers per pair
input int    InpMaxBosLagBars      = 20;                // Max Y bars allowed between rejection and BOS
input bool   InpShowZoneLines      = true;              // Draw thin level->event zone lines (clean)
input int    InpZoneLineWidth      = 1;                 // Zone line width
input bool   InpShowRejections     = false;             // Draw rejection arrows (legacy, cluttered)
input bool   InpShowBreakouts      = false;             // Draw BOS labels (legacy, cluttered)
input bool   InpShowDashboard      = true;              // Show MN/W1/D1 panel
input color  InpBullColor          = clrMediumSeaGreen; // Bullish
input color  InpBearColor          = clrTomato;         // Bearish
input color  InpWaitColor          = clrDarkOrange;     // Rejected, waiting breakout
input color  InpNoneColor          = clrGray;           // No storyline
input int    InpDashX              = 10;                // Dashboard X distance
input int    InpDashY              = 20;                // Dashboard Y distance
input string InpPrefix             = "MSNR_ST_";        // Object name prefix

enum ENUM_ST_STATE { ST_NONE=0, ST_BULL_WAIT=1, ST_BEAR_WAIT=2, ST_BULL=3, ST_BEAR=4 };

struct SLevel
  {
   double   price;
   int      formed_idx;   // series index (0=newest) of confirming bar
   datetime formed_time;
   bool     is_support;
  };

struct SEvent
  {
   datetime time;
   double   price;
   int      dir;          // +1 bull, -1 bear
   double   ref_price;    // rejection: level price / breakout: broken level price
   datetime lvl_time;     // when the level was formed (line start)
  };

//--- tier clocks: latest bar-open time seen per pair row (follow=row 0)
datetime g_seenX[3];
datetime g_seenY[3];

//--- cheapest freshness probe: current (forming) bar's open time changes
//--- exactly when the TF prints a new bar
datetime TierClock(ENUM_TIMEFRAMES tf)
  {
   datetime t[1];
   if(CopyTime(_Symbol,tf,0,1,t)<1) return(0);
   return(t[0]);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Storyline (X reject + Y BOS)");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   DeleteAllObjects();
   Comment("");
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
   ArraySetAsSeries(time,true);
   if(rates_total<3) return(0);

   static datetime last_bar_time=0;
   static ENUM_TIMEFRAMES last_tf=PERIOD_CURRENT;
   bool new_bar=(time[0]!=last_bar_time);
   bool tf_changed=(Period()!=last_tf);

   //--- collect pairs first so tier clocks can be probed cheaply
   ENUM_TIMEFRAMES pX[3], pY[3];
   string pName[3];
   int pairs=0;
   if(InpFollowChart)
     {
      //--- pair tracks the chart: X=chart TF, Y=one step lower, so each
      //--- leg is inspected on the chart where its candles align
      pX[0]=Period(); pY[0]=LowerTF(Period());
      pName[0]=TFName(pX[0])+"/"+TFName(pY[0]);
      pairs=1;
     }
   else
     {
      //--- classic fixed 3-row panel
      pX[0]=PERIOD_MN1; pY[0]=PERIOD_W1; pName[0]="MN/W1";
      pX[1]=PERIOD_W1;  pY[1]=PERIOD_D1; pName[1]="W1/D1";
      pX[2]=PERIOD_D1;  pY[2]=PERIOD_H4; pName[2]="D1/H4";
      pairs=3;
     }

   //--- tier-aware rebuild: a new bar on ANY leg (e.g. H4 BOS leg moving
   //--- intraday on a D1 chart) recalculates the forming storyline now
   bool tier_new=false;
   datetime cx[3], cy[3];
   for(int r=0;r<pairs;r++)
     {
      cx[r]=TierClock(pX[r]); cy[r]=TierClock(pY[r]);
      if(cx[r]==0 || cy[r]==0) continue;   // no data; GetBars shows NO DATA
      if(cx[r]!=g_seenX[r] || cy[r]!=g_seenY[r]) tier_new=true;
     }

   if(prev_calculated!=0 && !new_bar && !tf_changed && !tier_new) return(rates_total);
   last_bar_time=time[0];
   last_tf=Period();

   DeleteAllObjects();

   for(int r=0;r<pairs;r++)
      if(DrawPair(pX[r],pY[r],pName[r],r))
        { g_seenX[r]=cx[r]; g_seenY[r]=cy[r]; }  // commit only on clean draw

   ChartRedraw();
   return(rates_total);
  }

//+------------------------------------------------------------------+
//--- returns true when both legs drew from clean data (clocks committable)
bool DrawPair(ENUM_TIMEFRAMES tfX,ENUM_TIMEFRAMES tfY,const string pairName,int row)
  {
   datetime tx[]; double ox[],hx[],lx[],cx[];
   datetime ty[]; double oy[],hy[],ly[],cy[];
   bool okX=GetBars(tfX,InpLookbackX,tx,ox,hx,lx,cx);
   bool okY=GetBars(tfY,InpLookbackY,ty,oy,hy,ly,cy);

   ENUM_ST_STATE st=ST_NONE;
   datetime rejT=0, boT=0;
   int dir=0;

   if(okX && okY)
     {
      SEvent rejs[];  // X rejections (fresh only)
      SEvent breaks[];// Y breakouts (all BOS)
      FindRejections(tx,ox,hx,lx,cx,rejs);
      FindBreakouts(ty,oy,cy,breaks);
       int maxLagSec=InpMaxBosLagBars*PeriodSeconds(tfY);
       st=ResolveState(rejs,breaks,maxLagSec,rejT,boT,dir);

      if(InpShowZoneLines)
        {
         DrawZoneLines(pairName,"REJ",rejs,true);
         DrawZoneLines(pairName,"BOS",breaks,false);
        }
      if(InpShowRejections) DrawRejections(pairName,tx,hx,lx,rejs);
      if(InpShowBreakouts)  DrawBreakouts(pairName,ty,hy,ly,breaks);
     }

   if(InpShowDashboard) DrawDashRow(row,pairName,st,rejT,boT,dir,okX&&okY);
   return(okX && okY);
  }

//--- pull OHLC for a TF; arrays end up series-indexed (0=newest)
//--- FIX: refuse unsynchronized MTF history so the dashboard shows
//--- NO DATA instead of a storyline computed on hole-y data.
bool GetBars(ENUM_TIMEFRAMES tf,int want,datetime &t[],double &o[],double &h[],double &l[],double &c[])
  {
   long sync=0;
   if(!SeriesInfoInteger(_Symbol,tf,SERIES_SYNCHRONIZED,sync) || sync==0)
      return(false);
   int avail=Bars(_Symbol,tf);
   if(avail<15) return(false);
   int n=MathMin(want,avail);
   if(CopyTime(_Symbol,tf,0,n,t)<n)  return(false);
   if(CopyOpen(_Symbol,tf,0,n,o)<n)  return(false);
   if(CopyHigh(_Symbol,tf,0,n,h)<n)  return(false);
   if(CopyLow(_Symbol,tf,0,n,l)<n)   return(false);
   if(CopyClose(_Symbol,tf,0,n,c)<n) return(false);
   ArraySetAsSeries(t,true);
   ArraySetAsSeries(o,true); ArraySetAsSeries(h,true);
   ArraySetAsSeries(l,true); ArraySetAsSeries(c,true);
   return(true);
  }

//--- 2-candle S/R levels at close (same engine as I1/I2)
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
      lv[n].price      =c[i+1];
      lv[n].formed_idx =i;
      lv[n].formed_time=t[i];
      lv[n].is_support =sup;
     }
  }

//--- fresh rejections: first wick-touch that also rejects (close back inside)
void FindRejections(const datetime &t[],const double &o[],const double &h[],
                    const double &l[],const double &c[],SEvent &ev[])
  {
   ArrayResize(ev,0);
   SLevel lv[];
   DetectLevels(t,o,c,ArraySize(t),lv);
   double tol=InpTolerancePips*((_Digits==3||_Digits==5)?10.0*_Point:_Point);
   int LN=ArraySize(lv);

   for(int k=0;k<LN;k++)
      {
       bool touched=false;
       int  rej_idx=-1;                      // index of THIS level's rejection event (-1 = none)
       // j walks newer in time (series index decreasing = forward in time).
       // CLOSED bars only (j>=1): the forming bar is excluded so rejections
       // never paint/vanish intraday — day-end state is final.
       for(int j=lv[k].formed_idx-1;j>=1;j--)
         {
          bool inZone=(h[j]>=lv[k].price-tol && l[j]<=lv[k].price+tol);

          //--- INVALIDATION: after a rejection, a candle that CLOSES THROUGH
          //--- the level voids that rejection (level would flip role). The
          //--- touch bar itself can also close through -> no rejection at all.
          bool closed_through=(lv[k].is_support  && c[j]<lv[k].price) ||
                              (!lv[k].is_support && c[j]>lv[k].price);
          if(closed_through)
            {
             if(rej_idx>=0) { ArrayRemove(ev,rej_idx,1); rej_idx=-1; }
             break;  // level is broken for storyline purposes; stop tracking
            }

          if(!inZone) continue;
          if(touched) continue;              // unfresh: only first touch counts
          touched=true;                       // this touch consumes freshness
          if(lv[k].is_support && l[j]<=lv[k].price+tol && c[j]>lv[k].price)
            { rej_idx=ArraySize(ev); AppendEvent(ev,t[j],l[j],+1,lv[k].price,lv[k].formed_time); }
          else if(!lv[k].is_support && h[j]>=lv[k].price-tol && c[j]<lv[k].price)
            { rej_idx=ArraySize(ev); AppendEvent(ev,t[j],h[j],-1,lv[k].price,lv[k].formed_time); }
          // one rejection per level max (freshness consumed)
         }
      }
   SortEvents(ev);
   }

//--- every Y close-through is a BOS breakout (closed bars only, same
//--- day-end-final guarantee as rejections)
void FindBreakouts(const datetime &t[],const double &o[],const double &c[],SEvent &ev[])
  {
   ArrayResize(ev,0);
   SLevel lv[];
   DetectLevels(t,o,c,ArraySize(t),lv);
   int LN=ArraySize(lv);
   for(int k=0;k<LN;k++)
     {
      for(int j=lv[k].formed_idx-1;j>=1;j--)
        {
         if(lv[k].is_support && c[j]<lv[k].price)
           { AppendEvent(ev,t[j],c[j],-1,lv[k].price,lv[k].formed_time); break; } // first break only
         if(!lv[k].is_support && c[j]>lv[k].price)
           { AppendEvent(ev,t[j],c[j],+1,lv[k].price,lv[k].formed_time); break; }
        }
     }
   SortEvents(ev);
  }

void AppendEvent(SEvent &ev[],datetime t,double px,int dir,double ref,datetime lvlT)
  {
   int n=ArraySize(ev);
   ArrayResize(ev,n+1);
   ev[n].time=t; ev[n].price=px; ev[n].dir=dir; ev[n].ref_price=ref; ev[n].lvl_time=lvlT;
  }

//--- insertion sort by time ascending (old->new); N is small
void SortEvents(SEvent &ev[])
  {
   int n=ArraySize(ev);
   for(int i=1;i<n;i++)
     {
      SEvent v=ev[i];
      int j=i-1;
      while(j>=0 && ev[j].time>v.time) { ev[j+1]=ev[j]; j--; }
      ev[j+1]=v;
     }
   // trim to most recent InpMaxEvents*2 to bound objects
   if(n>InpMaxEvents*2)
     {
      int cut=n-InpMaxEvents*2;
      for(int i=0;i<InpMaxEvents*2;i++) ev[i]=ev[i+cut];
      ArrayResize(ev,InpMaxEvents*2);
     }
  }

//--- latest-only resolution: breakout must come after its rejection,
//--- and within InpMaxBosLagBars Y-bars (fix 2: reject stale pairings)
ENUM_ST_STATE ResolveState(const SEvent &rejs[],const SEvent &brks[],int maxLagSec,
                           datetime &rejT,datetime &boT,int &dir)
  {
   datetime lastBullRej=0,lastBearRej=0;
   for(int i=0;i<ArraySize(rejs);i++)
     {
      if(rejs[i].dir>0 && rejs[i].time>lastBullRej) lastBullRej=rejs[i].time;
      if(rejs[i].dir<0 && rejs[i].time>lastBearRej) lastBearRej=rejs[i].time;
     }
   datetime lastBullBO=0,lastBearBO=0;
   //--- pair EVERY rejection with its first in-window BOS (brks ascend in
   //--- time, so break at window end). An already-confirmed bias therefore
   //--- persists when a newer same-direction rejection pends: the new setup
   //--- is a continuation entry, not a bias flip.
   for(int i=0;i<ArraySize(rejs);i++)
     {
      for(int b=0;b<ArraySize(brks);b++)
        {
         if(brks[b].dir!=rejs[i].dir || brks[b].time<=rejs[i].time) continue;
         if(brks[b].time-rejs[i].time>maxLagSec) break;
         if(rejs[i].dir>0 && brks[b].time>lastBullBO) lastBullBO=brks[b].time;
         if(rejs[i].dir<0 && brks[b].time>lastBearBO) lastBearBO=brks[b].time;
         break; // first BOS per rejection only
        }
     }

   datetime bullConf=(lastBullRej>0 && lastBullBO>lastBullRej)?lastBullBO:0;
   datetime bearConf=(lastBearRej>0 && lastBearBO>lastBearRej)?lastBearBO:0;

//--- A confirmed storyline PERSISTS: a newer same-direction rejection does
//--- not downgrade an already-confirmed storyline back to WAIT.
   if(bullConf>0 && bullConf>bearConf)
     {
      // newer bear rejection pending? only wait if it arrives after confirm
      if(lastBearRej>bullConf) { rejT=lastBearRej; boT=0; dir=-1; return(ST_BEAR_WAIT); }
      rejT=lastBullRej; boT=bullConf; dir=+1; return(ST_BULL);
     }
   if(bearConf>0 && bearConf>bullConf)
     {
      if(lastBullRej>bearConf) { rejT=lastBullRej; boT=0; dir=+1; return(ST_BULL_WAIT); }
      rejT=lastBearRej; boT=bearConf; dir=-1; return(ST_BEAR);
     }
   if(lastBullRej>lastBearRej && lastBullRej>0) { rejT=lastBullRej; boT=0; dir=+1; return(ST_BULL_WAIT); }
   if(lastBearRej>0) { rejT=lastBearRej; boT=0; dir=-1; return(ST_BEAR_WAIT); }
   rejT=0; boT=0; dir=0;
   return(ST_NONE);
  }

//+------------------------------------------------------------------+
string StateTag(ENUM_ST_STATE s)
  {
   switch(s)
     {
      case ST_BULL:      return("BULL");
      case ST_BEAR:      return("BEAR");
      case ST_BULL_WAIT: return("BULL WAIT");
      case ST_BEAR_WAIT: return("BEAR WAIT");
      default:           return("NONE");
     }
  }

color StateColor(ENUM_ST_STATE s)
  {
   switch(s)
     {
      case ST_BULL:      return(InpBullColor);
      case ST_BEAR:      return(InpBearColor);
      case ST_BULL_WAIT:
      case ST_BEAR_WAIT: return(InpWaitColor);
      default:           return(InpNoneColor);
     }
  }

void DrawDashRow(int row,const string pair,ENUM_ST_STATE st,datetime rejT,datetime boT,int dir,bool ok)
  {
   string nm=InpPrefix+"dash_"+IntegerToString(row);
   string txt;
   if(!ok)
      txt=StringFormat("%s: NO DATA",pair);
   else if(st==ST_BULL || st==ST_BEAR)
      txt=StringFormat("%s: %s  rej %s  BOS %s",pair,StateTag(st),
         TimeToString(rejT,TIME_DATE),TimeToString(boT,TIME_DATE));
   else if(st==ST_BULL_WAIT || st==ST_BEAR_WAIT)
      txt=StringFormat("%s: %s  rej %s  wait BOS",pair,StateTag(st),
         TimeToString(rejT,TIME_DATE));
   else
      txt=StringFormat("%s: NONE",pair);

   ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,InpDashX);
   ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,InpDashY+row*18);
   ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,9);
   ObjectSetInteger(0,nm,OBJPROP_COLOR,ok?StateColor(st):InpNoneColor);
   ObjectSetString(0,nm,OBJPROP_TEXT,txt);
   ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
   if(row==0)
     {
      string hd=InpPrefix+"dash_head";
      ObjectCreate(0,hd,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,hd,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,hd,OBJPROP_XDISTANCE,InpDashX);
      ObjectSetInteger(0,hd,OBJPROP_YDISTANCE,InpDashY-18);
      ObjectSetInteger(0,hd,OBJPROP_FONTSIZE,9);
      ObjectSetInteger(0,hd,OBJPROP_COLOR,InpNoneColor);
      ObjectSetString(0,hd,OBJPROP_TEXT,InpFollowChart?"MSNR Storyline (follow chart, S/R v1)":"MSNR Storyline (S/R v1)");
      ObjectSetInteger(0,hd,OBJPROP_SELECTABLE,false);
     }
   // expose direction for screen readers / tooltip
   ObjectSetString(0,nm,OBJPROP_TOOLTIP,
      StringFormat("%s storyline=%s dir=%d",pair,StateTag(st),dir));
  }

//--- short TF name for pair labels
string TFName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_MN1: return("MN");
      case PERIOD_W1:  return("W1");
      case PERIOD_D1:  return("D1");
      case PERIOD_H4:  return("H4");
      case PERIOD_H1:  return("H1");
      case PERIOD_M30: return("M30");
      case PERIOD_M15: return("M15");
      case PERIOD_M5:  return("M5");
      case PERIOD_M1:  return("M1");
      default:         return(EnumToString(tf));
     }
  }

//--- one step down the MSNR ladder; M1 maps to itself (Video 8 X+X variant)
ENUM_TIMEFRAMES LowerTF(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_MN1: return(PERIOD_W1);
      case PERIOD_W1:  return(PERIOD_D1);
      case PERIOD_D1:  return(PERIOD_H4);
      case PERIOD_H4:  return(PERIOD_H1);
      case PERIOD_H1:  return(PERIOD_M30);
      case PERIOD_M30: return(PERIOD_M15);
      case PERIOD_M15: return(PERIOD_M5);
      case PERIOD_M5:  return(PERIOD_M1);
      default:         return(tf);
     }
  }

//--- thin horizontal zone lines: level formation -> event bar, one price each
void DrawZoneLines(const string pair,const string kind,const SEvent &ev[],bool isReject)
  {
   int n=ArraySize(ev);
   int start=(n>InpMaxEvents)?n-InpMaxEvents:0;
   for(int i=start;i<n;i++)
     {
      datetime t1=ev[i].lvl_time;
      datetime t2=ev[i].time;
      double   px=ev[i].ref_price;
      if(t2<=t1) continue;
      bool bull=(ev[i].dir>0);
      string nm=InpPrefix+(isReject?"rl_":"bl_")+pair+"_"+kind+"_"+
                TimeToString(t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);
      ObjectCreate(0,nm,OBJ_TREND,0,t1,px,t2,px);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,bull?InpBullColor:InpBearColor);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,InpZoneLineWidth);
      ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
      ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,nm,OBJPROP_BACK,true);
      ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("%s %s lvl %s formed %s -> %s %s @ %s (fresh S/R v1)",
            pair,isReject?"rejected":"BOS",
            DoubleToString(px,_Digits),TimeToString(t1),
            isReject?"wick reject":"body break",TimeToString(t2)));
     }
  }

void DrawRejections(const string pair,const datetime &t[],const double &h[],const double &l[],const SEvent &ev[])
  {
   int n=ArraySize(ev);
   int start=(n>InpMaxEvents)?n-InpMaxEvents:0;
   for(int i=start;i<n;i++)
     {
      string nm=InpPrefix+"rej_"+pair+"_"+TimeToString(ev[i].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);
      bool bull=(ev[i].dir>0);
      // locate bar for anchoring
      int bi=FindBar(t,ev[i].time);
      double anchor=(bi>=0)?(bull?l[bi]:h[bi]):ev[i].price;
      ObjectCreate(0,nm,bull?OBJ_ARROW_UP:OBJ_ARROW_DOWN,0,ev[i].time,anchor);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,bull?InpBullColor:InpBearColor);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("%s %s rejection lvl %s @ %s (fresh S/R v1)",
            pair,bull?"Bull":"Bear",
            DoubleToString(ev[i].ref_price,_Digits),TimeToString(ev[i].time)));
     }
  }

void DrawBreakouts(const string pair,const datetime &t[],const double &h[],const double &l[],const SEvent &ev[])
  {
   int n=ArraySize(ev);
   int start=(n>InpMaxEvents)?n-InpMaxEvents:0;
   for(int i=start;i<n;i++)
     {
      string nm=InpPrefix+"bos_"+pair+"_"+TimeToString(ev[i].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);
      int bi=FindBar(t,ev[i].time);
      double anchor=ev[i].price;
      if(bi>=0) anchor=(ev[i].dir>0)?h[bi]+100*_Point:l[bi]-100*_Point;
      ObjectCreate(0,nm,OBJ_TEXT,0,ev[i].time,anchor);
      ObjectSetString(0,nm,OBJPROP_TEXT,(ev[i].dir>0)?"BOS+":"BOS-");
      ObjectSetInteger(0,nm,OBJPROP_COLOR,(ev[i].dir>0)?InpBullColor:InpBearColor);
      ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8);
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("%s Y-BOS %s broke %s @ %s",
            pair,(ev[i].dir>0)?"up":"down",
            DoubleToString(ev[i].ref_price,_Digits),TimeToString(ev[i].time)));
     }
  }

int FindBar(const datetime &t[],datetime need)
  {
   int n=ArraySize(t);
   for(int i=0;i<n;i++)
      if(t[i]==need) return(i);
   return(-1);
  }

void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
