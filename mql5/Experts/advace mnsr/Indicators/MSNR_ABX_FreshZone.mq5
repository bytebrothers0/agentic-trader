//+------------------------------------------------------------------+
//|                                            MSNR_ABX_FreshZone.mq5 |
//|              ABAX Indicator B3: 3-state freshness + LL/UL band     |
//+------------------------------------------------------------------+
//| Rules (ABAX P02-03, reconciling p23/24 vs p25):                    |
//|                                                                    |
//|  Band per 2-candle level (I1 parity): support = [wick-side low of  |
//|  the pair (LL) .. close line (UL)]; resistance mirror [close ..    |
//|  wick-side high (UH)].                                             |
//|  States: FRESH (never touched) -> WICK_TOUCHED (wick/body taps     |
//|  band but closes inside: still tradable derated, UseCount++) ->    |
//|  BODY-broken (body close beyond far edge: DEAD, flips role per     |
//|  I2) or EXHAUSTED (UseCount > InpMaxUses, default 2).              |
//|  DailyGap exception: chart gap > InpGapMult x ATR near formation   |
//|  + displacement reaction -> cap lifted (GAP-EXEMPT tag).            |
//|  Validity: buys need Close > LL (wick under OK), sells Close < UH. |
//|                                                                    |
//|  Rendering: band box formation -> now (or death bar); solid fresh, |
//|  dashed unfresh, dotted gray dead; state + use-count labels.       |
//|  Most-recent cap. Closed bars only. No rays.                       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (levels)
input int    InpMaxUses       = 2;                 // Max touches before exhaustion
input int    InpATRPeriod     = 14;                // ATR period (gap/displacement)
input double InpGapMult       = 1.0;               // Gap > mult x ATR = daily-gap candidate
input int    InpGapLookback   = 10;                // Bars back to find gap at formation
input int    InpMaxZones      = 40;                // Max zones drawn (most recent)
input bool   InpShowLabels    = true;              // Show state labels
input color  InpSupColor      = clrDodgerBlue;     // Support band
input color  InpResColor      = clrTomato;         // Resistance band
input color  InpDeadColor     = clrGray;           // Dead/exhausted zone
input string InpPrefix        = "MSNR_FZ_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SLevel
   {
    double   price;
    int      formed_idx;
    bool     is_support;
   };

struct SZone
   {
    double   top;
    double   bottom;
    datetime t1;
    datetime t2;         // death bar, 0 = alive
    bool     isSup;
    int      state;      // 0 fresh, 1 unfresh, 2 dead-broken, 3 dead-exhausted
    int      uses;
    bool     gapExempt;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR FreshZone");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+3) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SZone z[];
    FindZones(time,open,high,low,close,atr,rates_total,z);

    DrawZones(z,time[0]);
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

void FindZones(const datetime &t[],const double &o[],const double &h[],
               const double &l[],const double &c[],const double &atr[],
               int rates_total,SZone &z[])
   {
    ArrayResize(z,0);
    SLevel lv[];
    DetectLevels(t,o,c,rates_total,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       double top, bot;
       if(lv[k].is_support) { top=lv[k].price; bot=MathMin(l[F],l[F+1]); }
       else                 { bot=lv[k].price; top=MathMax(h[F],h[F+1]); }
       if(top-bot<_Point) continue;
       //--- daily-gap exception near formation?
       bool exempt=false;
       for(int g=F+1;g<=MathMin(F+InpGapLookback,rates_total-2) && !exempt;g++)
         {
          if(atr[g]<=0) continue;
          if(MathAbs(o[g]-c[g+1])>InpGapMult*atr[g])
            {
             for(int d=g-1;d>=MathMax(g-5,1);d--)
               {
                if(MathAbs(c[d]-o[d])>atr[d] && atr[d]>0) { exempt=true; break; }
               }
            }
         }
       SZone x;
       x.top=top; x.bottom=bot; x.t1=t[F]; x.t2=0;
       x.isSup=lv[k].is_support; x.state=0; x.uses=0; x.gapExempt=exempt;
       for(int j=F-1;j>=1;j--)
         {
          if(x.isSup)
            {
             if(c[j]<bot) { x.state=2; x.t2=t[j]; break; }      // body break
             if(l[j]<=top)
               {
                x.uses++; x.state=1;
                if(x.uses>InpMaxUses && !exempt) { x.state=3; x.t2=t[j]; break; }
               }
            }
          else
            {
             if(c[j]>top) { x.state=2; x.t2=t[j]; break; }
             if(h[j]>=bot)
               {
                x.uses++; x.state=1;
                if(x.uses>InpMaxUses && !exempt) { x.state=3; x.t2=t[j]; break; }
               }
            }
         }
       int n=ArraySize(z);
       ArrayResize(z,n+1); z[n]=x;
      }
   }

string StateName(const SZone &x)
   {
    if(x.state==0) return("FRESH");
    if(x.state==1) return(StringFormat("UNFRESH x%d%s",x.uses,
       (x.gapExempt?" GAP-X":"")));
    if(x.state==2) return("DEAD break");
    return("DEAD used-up");
   }

void DrawZones(const SZone &z[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(z);
    int start=(n>InpMaxZones)?n-InpMaxZones:0;
    for(int k=start;k<n;k++)
      {
       datetime t2=(z[k].t2==0?now:z[k].t2);
       if(t2<=z[k].t1) continue;
       bool dead=(z[k].state>=2);
       string nm=InpPrefix+(z[k].isSup?"sup_":"res_")+
                 TimeToString(z[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(dead?InpDeadColor:(z[k].isSup?InpSupColor:InpResColor));
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,z[k].t1,z[k].top,t2,z[k].bottom);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,(z[k].state==0?STYLE_SOLID:(dead?STYLE_DOT:STYLE_DASH)));
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("%s LL/UL band [%s..%s] | %s | formed %s -> %s",
             z[k].isSup?"Support":"Resistance",
             DoubleToString(z[k].top,_Digits),DoubleToString(z[k].bottom,_Digits),
             StateName(z[k]),TimeToString(z[k].t1),TimeToString(t2)));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(z[k].isSup?z[k].top:z[k].bottom);
          ObjectCreate(0,ln,OBJ_TEXT,0,z[k].t1,px);
          ObjectSetString(0,ln,OBJPROP_TEXT,StateName(z[k]));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (z[k].isSup?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
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
