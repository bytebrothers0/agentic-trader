//+------------------------------------------------------------------+
//|                                               MSNR_APA_Shift.mq5 |
//|              APA Indicator 3: shift states + FMD lines             |
//+------------------------------------------------------------------+
//| Rules (APA Parts 2 §3, 4):                                         |
//|                                                                    |
//|  Single-pass structure tracker (oldest -> newest, closes only):    |
//|  break of the newest older fractal swing = BOS in-trend, or        |
//|  SHIFT when against the tracked trend (reversal).                  |
//|  Reclaim (P4 §2.2): after a shift, body close beyond the           |
//|  pre-shift extreme (highest high within InpReclaimBars before a    |
//|  bear shift, mirror) -> RECLAIMED, the shift was LE-trap.          |
//|  Transition/chop (P4 §2.3): opposite shift within InpChopBars      |
//|  with no continuation BOS between -> chop box + CHOP STAND DOWN.   |
//|  Inside/Outside (P4 §3): post-shift leg range vs prior leg range   |
//|  -> INSIDE / OUTSIDE tag on the shift.                             |
//|  FMD (P2 §3.1): thrust extreme between the broken swing and the    |
//|  shift bar; dotted segment shift -> reclaim/breach, else now.      |
//|                                                                    |
//|  Rendering: pure marker - shift arrows + labels, RECLAIMED tags,   |
//|  chop boxes, FMD lines. Most-recent cap. Closed bars only. No rays.|
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (bars each side)
input int    InpReclaimBars   = 30;                // Bars back/forward for reclaim extreme
input int    InpChopBars      = 20;                // Max bars between opposite shifts = chop
input int    InpMaxShifts     = 30;                // Max shifts drawn (most recent)
input double InpTouchPips     = 2.0;               // Inside/outside tolerance (pips)
input double InpArrowGapPips  = 3.0;               // Arrow gap from extreme (pips)
input bool   InpShowFMD       = true;              // Draw FMD lines
input bool   InpShowChop      = true;              // Draw chop boxes
input bool   InpShowLabels    = true;              // Show labels
input color  InpBearColor     = clrTomato;         // Bear shift
input color  InpBullColor     = clrDodgerBlue;     // Bull shift
input color  InpReclaimColor  = clrOrange;         // Reclaim tag (amber)
input color  InpChopColor     = clrGray;           // Chop box
input color  InpFMDColor      = clrGoldenrod;      // FMD line (gold)
input string InpPrefix        = "MSNR_AS_";        // Object name prefix

struct SPivot
   {
    double   price;
    bool     is_high;
    int      idx;
   };

struct SShift
   {
    int      bar;        // series index of shift bar
    datetime time;
    double   lvl;        // broken shift level
    double   ext;        // shift-bar extreme (arrow side)
    bool     bear;
    bool     reclaim;    // reclaimed later
    datetime reclaimTime;
    bool     inside;     // inside vs outside formation
    bool     chop;       // part of a chop pair (drawn via chop list)
    double   fmd;        // thrust extreme
    datetime fmdEnd;     // breach bar, 0 = extends to now
   };

struct SChop
   {
    datetime t1;         // older shift time
    datetime t2;         // newer shift time
    double   top;
    double   bot;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Shifts");
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

    SShift sh[];
    SChop chop[];
    FindShifts(time,open,high,low,close,rates_total,sh,chop);

    DrawAll(sh,chop,time[0]);
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

//--- newest pivot of a side strictly older than bar j (price only, 0 = none)
double NewestPivot(const SPivot &piv[],bool wantHigh,int j,int &pidx)
   {
    for(int p=ArraySize(piv)-1;p>=0;p--)
      {
       if(piv[p].is_high!=wantHigh) continue;
       if(piv[p].idx<=j) continue;
       pidx=p;
       return(piv[p].price);
      }
    pidx=-1;
    return(0.0);
   }

void FindShifts(const datetime &t[],const double &o[],const double &h[],
                const double &l[],const double &c[],int rates_total,
                SShift &sh[],SChop &chop[])
   {
    ArrayResize(sh,0); ArrayResize(chop,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double tol=InpTouchPips*pip;
    int maxScan=MathMin(InpLookbackBars,rates_total-2);

    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);

    //--- pass 1: shifts + continuation BOS times (oldest -> newest)
    int bosBar[];   // bars with continuation BOS (same-trend breaks)
    ArrayResize(bosBar,0);
    int trend=0;    // +1 bull, -1 bear
    for(int j=maxScan;j>=1;j--)
      {
       int ph, pl;
       double H=NewestPivot(piv,true,j,ph);
       double L=NewestPivot(piv,false,j,pl);
       bool bodyUp=(c[j]>o[j]), bodyDn=(c[j]<o[j]);
       bool upB=(H>0 && bodyUp && c[j]>H);
       bool dnB=(L>0 && bodyDn && c[j]<L);
       if(!upB && !dnB) continue;
       bool bear=dnB && !upB;
       if(upB && dnB) bear=!bodyUp;
       if(trend==0)
         { trend=(bear?-1:+1); AppendBOS(bosBar,j); continue; }
       if((bear && trend<0) || (!bear && trend>0))
         { AppendBOS(bosBar,j); continue; }   // continuation
       SShift x;
       x.bar=j; x.time=t[j]; x.bear=bear;
       x.lvl=(bear?L:H); x.ext=(bear?h[j]:l[j]);
       x.reclaim=false; x.reclaimTime=0;
       x.inside=false; x.chop=false; x.fmd=0; x.fmdEnd=0;
       int n=ArraySize(sh);
       ArrayResize(sh,n+1); sh[n]=x;
       trend=(bear?-1:+1);
      }

    //--- pass 2: reclaim, FMD, inside/outside, chop
    int ns=ArraySize(sh);
    for(int k=0;k<ns;k++)
      {
       int s=sh[k].bar;
       //--- reclaim extreme: highest high / lowest low within window before shift
       int back=MathMin(s+InpReclaimBars,rates_total-1);
       double E;
       if(sh[k].bear)
         { E=h[s]; for(int j=s+1;j<=back;j++) if(h[j]>E) E=h[j]; }
       else
         { E=l[s]; for(int j=s+1;j<=back;j++) if(l[j]<E) E=l[j]; }
       int fwd=MathMax(s-InpReclaimBars,1);
       for(int j=s-1;j>=fwd;j--)
         {
          if(sh[k].bear && c[j]>E) { sh[k].reclaim=true; sh[k].reclaimTime=t[j]; break; }
          if(!sh[k].bear && c[j]<E) { sh[k].reclaim=true; sh[k].reclaimTime=t[j]; break; }
         }
       //--- FMD: thrust extreme between broken swing and shift bar
       int pidx=-1;
       if(sh[k].bear)
         {
          double fmd=h[s];
          for(int j=s+1;j<=back;j++) if(h[j]>fmd) fmd=h[j];
          sh[k].fmd=fmd;
          for(int j=s-1;j>=1;j--)
            { if(c[j]>fmd) { sh[k].fmdEnd=t[j]; break; } }
         }
       else
         {
          double fmd=l[s];
          for(int j=s+1;j<=back;j++) if(l[j]<fmd) fmd=l[j];
          sh[k].fmd=fmd;
          for(int j=s-1;j>=1;j--)
            { if(c[j]<fmd) { sh[k].fmdEnd=t[j]; break; } }
         }
       //--- inside/outside: post-shift leg vs prior leg ranges
       int prevEv=(k+1<ns?sh[k+1].bar:back);       // older structural event
       int nextEv=(k-1>=0?sh[k-1].bar:1);          // newer structural event
       double prLo=l[s], prHi=h[s];
       for(int j=s+1;j<=prevEv && j<rates_total;j++)
         { if(l[j]<prLo) prLo=l[j]; if(h[j]>prHi) prHi=h[j]; }
       double poLo=l[s], poHi=h[s];
       for(int j=s-1;j>=nextEv;j--)
         { if(l[j]<poLo) poLo=l[j]; if(h[j]>poHi) poHi=h[j]; }
       sh[k].inside=(poLo>=prLo-tol && poHi<=prHi+tol);
      }
     //--- chop pairs: opposite shifts close together, no continuation between
     //    (sh[k] is older = LARGER bar index; sh[k+1] is newer = smaller)
     for(int k=0;k+1<ns;k++)
       {
        if(sh[k].bear==sh[k+1].bear) continue;
        if(sh[k].bar-sh[k+1].bar>InpChopBars) continue;
        bool cont=false;
        for(int b=0;b<ArraySize(bosBar);b++)
           if(bosBar[b]>sh[k+1].bar && bosBar[b]<sh[k].bar) { cont=true; break; }
        if(cont) continue;
        sh[k].chop=true; sh[k+1].chop=true;
        SChop z;
        z.t1=t[sh[k].bar]; z.t2=t[sh[k+1].bar];      // t1 older, t2 newer
        z.top=h[sh[k].bar]; z.bot=l[sh[k].bar];
        for(int j=sh[k].bar-1;j>=sh[k+1].bar;j--)
          { if(h[j]>z.top) z.top=h[j]; if(l[j]<z.bot) z.bot=l[j]; }
       int m=ArraySize(chop);
       ArrayResize(chop,m+1); chop[m]=z;
      }
   }

void AppendBOS(int &a[],int j)
   {
    int n=ArraySize(a);
    ArrayResize(a,n+1); a[n]=j;
   }

void DrawAll(const SShift &sh[],const SChop &chop[],datetime now)
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    DeleteAllObjects();
    int n=ArraySize(sh);
    int start=(n>InpMaxShifts)?n-InpMaxShifts:0;
    for(int k=start;k<n;k++)
      {
       string nm=InpPrefix+(sh[k].bear?"bear_":"bull_")+
                 TimeToString(sh[k].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(sh[k].reclaim?InpReclaimColor:(sh[k].bear?InpBearColor:InpBullColor));
       double apx=(sh[k].bear?sh[k].ext+gap:sh[k].ext-gap);
       ObjectCreate(0,nm+"_arw",(sh[k].bear?OBJ_ARROW_DOWN:OBJ_ARROW_UP),0,
                    sh[k].time,apx);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_BACK,false);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_SELECTABLE,true);
       string lbl=StringFormat("SHIFT %s %s%s%s",sh[k].bear?"BR":"BL",
          sh[k].inside?"IN":"OUT",
          sh[k].reclaim?" RECLAIMED":"",(sh[k].chop?" CHOP":""));
       ObjectSetString(0,nm+"_arw",OBJPROP_TOOLTIP,
          StringFormat("%s shift @ %s | broke %s | %s formation%s",
             sh[k].bear?"Bearish":"Bullish",TimeToString(sh[k].time),
             DoubleToString(sh[k].lvl,_Digits),
             sh[k].inside?"inside":"outside",
             sh[k].reclaim?StringFormat(" | RECLAIMED @ %s",TimeToString(sh[k].reclaimTime)):""));
       if(InpShowLabels)
         {
          ObjectCreate(0,nm+"_lbl",OBJ_TEXT,0,sh[k].time,
                       (sh[k].bear?apx+gap*2:apx-gap*2));
          ObjectSetString(0,nm+"_lbl",OBJPROP_TEXT,lbl);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_COLOR,clr);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_ANCHOR,
             (sh[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_BACK,true);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_SELECTABLE,false);
         }
       if(InpShowFMD && sh[k].fmd>0)
         {
          datetime fEnd=(sh[k].fmdEnd==0?now:sh[k].fmdEnd);
          if(fEnd>sh[k].time)
            {
             ObjectCreate(0,nm+"_fmd",OBJ_TREND,0,sh[k].time,sh[k].fmd,fEnd,sh[k].fmd);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_COLOR,InpFMDColor);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_STYLE,STYLE_DOT);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_WIDTH,1);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_RAY_RIGHT,false);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_BACK,true);
             ObjectSetInteger(0,nm+"_fmd",OBJPROP_SELECTABLE,true);
             ObjectSetString(0,nm+"_fmd",OBJPROP_TOOLTIP,
                StringFormat("FMD (thrust extreme) %s",DoubleToString(sh[k].fmd,_Digits)));
             if(InpShowLabels)
               {
                ObjectCreate(0,nm+"_fmdlbl",OBJ_TEXT,0,sh[k].time,sh[k].fmd);
                ObjectSetString(0,nm+"_fmdlbl",OBJPROP_TEXT,"FMD");
                ObjectSetInteger(0,nm+"_fmdlbl",OBJPROP_COLOR,InpFMDColor);
                ObjectSetInteger(0,nm+"_fmdlbl",OBJPROP_FONTSIZE,8);
                ObjectSetInteger(0,nm+"_fmdlbl",OBJPROP_ANCHOR,
                   (sh[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
                ObjectSetInteger(0,nm+"_fmdlbl",OBJPROP_BACK,true);
                ObjectSetInteger(0,nm+"_fmdlbl",OBJPROP_SELECTABLE,false);
               }
            }
         }
      }
    if(InpShowChop)
      {
       for(int k=0;k<ArraySize(chop);k++)
         {
          if(chop[k].t2<=chop[k].t1) continue;
          string nm=InpPrefix+"chop_"+TimeToString(chop[k].t1,TIME_DATE|TIME_MINUTES)+
                    "_"+IntegerToString(k);
          ObjectCreate(0,nm,OBJ_RECTANGLE,0,chop[k].t1,chop[k].top,chop[k].t2,chop[k].bot);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,InpChopColor);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DOT);
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_FILL,true);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,"Transition chop: STAND DOWN");
          ObjectCreate(0,nm+"_lbl",OBJ_TEXT,0,chop[k].t1,chop[k].top);
          ObjectSetString(0,nm+"_lbl",OBJPROP_TEXT,"CHOP - STAND DOWN");
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_COLOR,InpChopColor);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_BACK,true);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
