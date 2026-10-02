//+------------------------------------------------------------------+
//|                                           MSNR_APA_EngulfTypes.mq5 |
//|              APA Indicator 2: engulfing Types 1/2/3 + WOL          |
//+------------------------------------------------------------------+
//| Rules (APA Part 3):                                                |
//|  Pair scan (c1 older, c2 newer, closed bars, oldest -> newest):    |
//|  T1 "sweep" bear: both bear && h2 > h1 + sweep && c2 < c1.close;   |
//|   box top = h2 (invalidation/FMD), bottom = c1.close. Bull mirror.|
//|  T3 "marubozu origin": c1 near-marubozu (each wick <=              |
//|   InpMarubozuPct of range) + c2 opposite body-engulfs c1; box =    |
//|   c1 body. Checked before T2 (strict subset).                      |
//|  T2 "standard": opposite colors, c2.close past c1.open; box =      |
//|   [c1 extreme .. worst far wick].                                  |
//|  Lifecycle: ACTIVE -> INVALIDATED on body close through the        |
//|  absolute two-candle extreme. Labels T1B/T1S/T2B/T2S/T3B/T3S.      |
//|  WOL (Type 4, `InpCheckWOL`, W1+ charts): monthly Type1-3 zones    |
//|  via MN1 CopyRates; a weekly formation inside the monthly price    |
//|  bounds + time span -> `WOL OK`, else `WOL INVALID` (discard).     |
//|                                                                    |
//|  Rendering: pure marker - shaded boxes, type labels, dotted gray   |
//|  once invalidated; monthly zones in violet. Most-recent caps.      |
//|  Closed bars only. No rays.                                        |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars (chart TF)
input double InpMarubozuPct   = 10.0;              // Max c1 wick % of range = marubozu
input double InpMinSweepPips  = 0.5;               // Min T1 sweep past c1 extreme (pips)
input int    InpMaxBoxes      = 50;                // Max boxes drawn (most recent)
input bool   InpShowLabels    = true;              // Show type labels
input bool   InpCheckWOL      = true;              // Monthly-weekly overlap check (W1+)
input int    InpMonthsBack    = 36;                // Monthly bars for WOL scan
input int    InpMaxWOL        = 12;                // Max monthly zones drawn (most recent)
input color  InpBullColor     = clrLightSkyBlue;   // Bull shade
input color  InpBearColor     = clrMistyRose;      // Bear shade
input color  InpBullTxt       = clrDodgerBlue;     // Bull label
input color  InpBearTxt       = clrTomato;         // Bear label
input color  InpInvalidColor  = clrGray;           // Invalidated box/label
input color  InpWOLColor      = clrMediumVioletRed;// Monthly WOL zone
input string InpPrefix        = "MSNR_AET_";       // Object name prefix

struct SForm
   {
    datetime t1;         // c1 time
    datetime t2;         // c2 time
    double   top;
    double   bottom;
    double   inval;      // absolute extreme (invalidation level)
    bool     bull;
    int      type;       // 1, 2, 3
    datetime tEnd;       // invalidation bar, 0 = active
    bool     wol;        // WOL verdict exists
    bool     wolOK;      // weekly structure inside
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Engulf Types");
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

    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);

    SForm forms[];
    DetectForms(open,high,low,close,time,rates_total,1,InpLookbackBars,
                InpMarubozuPct/100.0,InpMinSweepPips*pip,forms);
    FinalizeForms(forms,close,time);

    //--- WOL on W1+ charts: monthly zones + weekly-inside verdict
    SForm wol[];
    if(InpCheckWOL && PeriodSeconds(PERIOD_CURRENT)>=PeriodSeconds(PERIOD_W1))
       BuildWOL(forms,pip,wol);

    DrawForms(forms,wol,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- generic pair classifier over any series arrays (i+1 = older c1, i = newer c2)
void DetectForms(const double &o[],const double &h[],const double &l[],
                 const double &c[],const datetime &t[],int total,
                 int iFrom,int iCount,double maruMax,double sweep,SForm &f[])
   {
    ArrayResize(f,0);
    int iMax=MathMin(iFrom+iCount,total-2);
    for(int i=iMax;i>=iFrom;i--)
      {
       double range1=h[i+1]-l[i+1];
       if(range1<=0) continue;
       bool b1=IsBullC(o,c,i+1), r1=IsBearC(o,c,i+1);
       bool b2=IsBullC(o,c,i),   r2=IsBearC(o,c,i);
       if(!b1 && !r1) continue;   // c1 doji: no type
       if(!b2 && !r2) continue;   // c2 doji: no type
       double maxOC1=MathMax(o[i+1],c[i+1]), minOC1=MathMin(o[i+1],c[i+1]);
       SForm x;
       x.t1=t[i+1]; x.t2=t[i]; x.tEnd=0; x.wol=false; x.wolOK=false;
       bool hit=false;
       //--- T1: same color + extreme sweep
       if(r1 && r2 && h[i]>h[i+1]+sweep && c[i]<c[i+1])
         { x.bull=false; x.type=1; x.top=h[i]; x.bottom=c[i+1]; x.inval=h[i]; hit=true; }
       else if(b1 && b2 && l[i]<l[i+1]-sweep && c[i]>c[i+1])
         { x.bull=true; x.type=1; x.top=c[i+1]; x.bottom=l[i]; x.inval=l[i]; hit=true; }
       //--- T3: marubozu c1 + opposite body engulf (before T2)
       if(!hit)
         {
          double upW=h[i+1]-maxOC1, loW=minOC1-l[i+1];
          bool maru=(upW<=maruMax*range1 && loW<=maruMax*range1);
          if(maru && r1 && b2 && c[i]>o[i+1])
            { x.bull=true; x.type=3; x.top=maxOC1; x.bottom=minOC1; x.inval=MathMin(l[i],l[i+1]); hit=true; }
          else if(maru && b1 && r2 && c[i]<o[i+1])
            { x.bull=false; x.type=3; x.top=maxOC1; x.bottom=minOC1; x.inval=MathMax(h[i],h[i+1]); hit=true; }
         }
       //--- T2: opposite colors, body engulf
       if(!hit)
         {
          if(r1 && b2 && c[i]>o[i+1])
            { x.bull=true; x.type=2; x.top=h[i+1]; x.bottom=MathMin(l[i],l[i+1]); x.inval=x.bottom; hit=true; }
          else if(b1 && r2 && c[i]<o[i+1])
            { x.bull=false; x.type=2; x.top=MathMax(h[i],h[i+1]); x.bottom=l[i+1]; x.inval=x.top; hit=true; }
         }
       if(!hit) continue;
       if(x.top-x.bottom<_Point) continue;
       int n=ArraySize(f);
       ArrayResize(f,n+1); f[n]=x;
      }
   }

//--- invalidation: first body close through the absolute extreme (newer than c2)
void FinalizeForms(SForm &f[],const double &c[],const datetime &t[])
   {
    for(int k=0;k<ArraySize(f);k++)
      {
       int c2idx=-1;
       for(int j=ArraySize(c)-1;j>=1;j--)
          if(t[j]==f[k].t2) { c2idx=j; break; }
       if(c2idx<0) continue;
       for(int j=c2idx-1;j>=1;j--)
         {
          if(f[k].bull && c[j]<f[k].inval) { f[k].tEnd=t[j]; break; }
          if(!f[k].bull && c[j]>f[k].inval) { f[k].tEnd=t[j]; break; }
         }
      }
   }

//--- monthly zones + weekly-inside verdict (Type 4)
void BuildWOL(const SForm &weekly[],double pip,SForm &wol[])
   {
    ArrayResize(wol,0);
    MqlRates mn[];
    int got=CopyRates(_Symbol,PERIOD_MN1,0,InpMonthsBack,mn);
    if(got<4) return;
    ArraySetAsSeries(mn,true);
    int n=ArraySize(mn);
    double o[],h[],l[],c[];
    datetime t[];
    ArrayResize(o,n); ArrayResize(h,n); ArrayResize(l,n);
    ArrayResize(c,n); ArrayResize(t,n);
    for(int i=0;i<n;i++)
      { o[i]=mn[i].open; h[i]=mn[i].high; l[i]=mn[i].low; c[i]=mn[i].close; t[i]=mn[i].time; }
    SForm mf[];
    DetectForms(o,h,l,c,t,n,1,n-2,InpMarubozuPct/100.0,InpMinSweepPips*pip,mf);
    FinalizeForms(mf,c,t);
    int start=(ArraySize(mf)>InpMaxWOL?ArraySize(mf)-InpMaxWOL:0);
    for(int k=start;k<ArraySize(mf);k++)
      {
        SForm x=mf[k];
        x.wol=true; x.wolOK=false;
        datetime spanEnd=(x.tEnd!=0?x.tEnd:(datetime)LONG_MAX); // zone alive until invalidated
        for(int q=0;q<ArraySize(weekly);q++)
          {
           if(weekly[q].t1<x.t1 || weekly[q].t1>spanEnd) continue; // overlaps zone lifetime
           if(weekly[q].top<=x.top && weekly[q].bottom>=x.bottom) // price bounds
             { x.wolOK=true; break; }
          }
       int m=ArraySize(wol);
       ArrayResize(wol,m+1); wol[m]=x;
      }
   }

string TypeTag(const SForm &x)
   {
    return(StringFormat("T%d%s",x.type,(x.bull?"B":"S")));
   }

void DrawOne(const SForm &x,datetime now,string nm,color bullC,color bearC,
             bool showLbl,string extra)
   {
    bool dead=(x.tEnd!=0);
    datetime t2=(dead?x.tEnd:now);
    if(t2<=x.t1) return;
    color clr=(dead?InpInvalidColor:(x.bull?bullC:bearC));
    ObjectCreate(0,nm,OBJ_RECTANGLE,0,x.t1,x.top,t2,x.bottom);
    ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
    ObjectSetInteger(0,nm,OBJPROP_STYLE,(dead?STYLE_DOT:STYLE_SOLID));
    ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
    ObjectSetInteger(0,nm,OBJPROP_FILL,true);
    ObjectSetInteger(0,nm,OBJPROP_BACK,true);
    ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
    ObjectSetString(0,nm,OBJPROP_TOOLTIP,
       StringFormat("%s%s [%s..%s] inval %s | %s -> %s%s",
          TypeTag(x),extra,
          DoubleToString(x.top,_Digits),DoubleToString(x.bottom,_Digits),
          DoubleToString(x.inval,_Digits),TimeToString(x.t1),TimeToString(t2),
          dead?" | INVALIDATED":" | ACTIVE"));
    if(showLbl)
      {
       string ln=nm+"_lbl";
       double px=(x.bull?x.bottom:x.top);
       ObjectCreate(0,ln,OBJ_TEXT,0,x.t1,px);
       ObjectSetString(0,ln,OBJPROP_TEXT,TypeTag(x)+extra);
       ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
       ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
          (x.bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
       ObjectSetInteger(0,ln,OBJPROP_BACK,true);
       ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
      }
   }

void DrawForms(const SForm &forms[],const SForm &wol[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(forms);
    int start=(n>InpMaxBoxes)?n-InpMaxBoxes:0;
    for(int k=start;k<n;k++)
      {
       string nm=InpPrefix+TypeTag(forms[k])+"_"+
                 TimeToString(forms[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       DrawOne(forms[k],now,nm,InpBullColor,InpBearColor,InpShowLabels,"");
      }
    for(int k=0;k<ArraySize(wol);k++)
      {
       string nm=InpPrefix+"wol_"+TimeToString(wol[k].t1,TIME_DATE)+"_"+IntegerToString(k);
       string verdict=(wol[k].wolOK?" WOL-OK":" WOL-INVALID");
       //--- monthly zones drawn thicker via width on a second outline box
       DrawOne(wol[k],now,nm,InpWOLColor,InpWOLColor,InpShowLabels,verdict);
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
