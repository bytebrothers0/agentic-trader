//+------------------------------------------------------------------+
//|                                                MSNR_APA_AOL.mq5  |
//|              APA Indicator 1: AOL boxes + phase + consumption      |
//+------------------------------------------------------------------+
//| Rules (APA Parts 1, 5 §1):                                         |
//|                                                                    |
//|  Formation: BOS breakout bar = first body-close through a          |
//|  2-candle S/R level (E2 parity). Bullish AOL = [leg low            |
//|  (invalidation) .. broken resistance (validation/top)]; leg start  |
//|  = most recent opposite fractal swing (Apex AS logic). Mirror      |
//|  bear.                                                             |
//|  Phase from deepest pullback extreme since BOS (wicks): never      |
//|  re-enters the box -> PURE (momentum, no deep entry expected);     |
//|  enters but body never closes through invalidation -> DIFFERENT    |
//|  (entry modules arm only here); body close through invalidation    |
//|  -> INVALIDATED (box dies at that bar).                            |
//|  Consumption (P5 §1): penetration >= 50% of box depth ->            |
//|  CONSUMED suffix (reacted once, unreliable after).                 |
//|                                                                    |
//|  Rendering: box BOS -> now (or invalidation bar); solid            |
//|  validation line, dotted invalidation line, dotted 50% line;       |
//|  phase label. Most-recent cap. Closed bars only. No rays.          |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (levels/swings)
input int    InpMaxAOL        = 20;                // Max AOL boxes drawn (most recent)
input bool   InpShowBox       = true;              // Draw AOL boxes
input bool   InpShowLines     = true;              // Draw validation/invalidation/50% lines
input bool   InpShowLabels    = true;              // Show phase labels
input color  InpBullColor     = clrLightSkyBlue;   // Bull AOL shade
input color  InpBearColor     = clrMistyRose;      // Bear AOL shade
input color  InpBullTxt       = clrDodgerBlue;     // Bull label/validation
input color  InpBearTxt       = clrTomato;         // Bear label/validation
input color  InpInvalidColor  = clrGray;           // Invalidated box/label
input color  InpMidColor      = clrDimGray;        // 50% consumption line
input string InpPrefix        = "MSNR_AOL_";       // Object name prefix

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

struct SAOL
   {
    double   top;        // validation (broken level)
    double   bottom;     // invalidation (leg extreme)
    double   mid;        // 50% consumption line
    datetime t1;         // BOS bar time
    datetime t2;         // invalidation bar, 0 = active
    bool     bull;
    int      phase;      // 0 PURE, 1 DIFFERENT, 2 INVALIDATED
    bool     consumed;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR AOL");
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

    SAOL aols[];
    FindAOLs(time,open,high,low,close,rates_total,aols);

    DrawAOLs(aols,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- 2-candle S/R levels at close (I1/I2/E2 parity)
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

void FindAOLs(const datetime &t[],const double &o[],const double &h[],
              const double &l[],const double &c[],int rates_total,SAOL &aols[])
   {
    ArrayResize(aols,0);
    int maxScan=MathMin(InpLookbackBars,rates_total-3);

    SLevel lv[];
    DetectLevels(t,o,c,rates_total,lv);
    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);

    //--- first-break map: oldest close-through per bar per direction
    bool bosUp[];
    bool bosDn[];
    double bosPx[];
    ArrayResize(bosUp,maxScan+1); ArrayInitialize(bosUp,false);
    ArrayResize(bosDn,maxScan+1); ArrayInitialize(bosDn,false);
    ArrayResize(bosPx,maxScan+1); ArrayInitialize(bosPx,0.0);
    for(int k=0;k<ArraySize(lv);k++)
      {
       int F=lv[k].formed_idx;
       for(int j=F-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price)
            { if(j<=maxScan && !bosDn[j]) { bosDn[j]=true; bosPx[j]=lv[k].price; } break; }
          if(!lv[k].is_support && c[j]>lv[k].price)
            { if(j<=maxScan && !bosUp[j]) { bosUp[j]=true; bosPx[j]=lv[k].price; } break; }
         }
      }

    //--- one AOL per BOS bar (oldest -> newest)
    for(int b=maxScan;b>=1;b--)
      {
       bool bull=bosUp[b], bear=bosDn[b];
       if(!bull && !bear) continue;
       if(bull && bear) bear=false;   // body direction decides ties
       if(bull && !IsBullC(o,c,b)) continue;
       if(bear && !IsBearC(o,c,b)) continue;
       double val=bosPx[b];
       //--- leg extreme: most recent opposite fractal swing, else window extreme
       double inv=0;
       for(int p=ArraySize(piv)-1;p>=0;p--)
         {
          if(piv[p].idx<=b) continue;
          if(bull && !piv[p].is_high) { inv=piv[p].price; break; }
          if(bear && piv[p].is_high) { inv=piv[p].price; break; }
         }
       if(inv==0)
         {
          inv=(bull?l[b]:h[b]);
          for(int j=b;j<=MathMin(b+50,rates_total-1);j++)
            { if(bull && l[j]<inv) inv=l[j]; if(bear && h[j]>inv) inv=h[j]; }
         }
       double top=(bull?val:inv), bot=(bull?inv:val);
       if(top-bot<_Point) continue;
       double mid=(top+bot)/2.0;
       //--- walk newer bars: deepest pullback (wicks) + invalidation (close)
       int phase=0;              // PURE until proven otherwise
       bool consumed=false;
       datetime t2=0;
       for(int j=b-1;j>=1;j--)
         {
          if(bull)
            {
             if(c[j]<bot) { phase=2; t2=t[j]; break; }
             if(l[j]<=top) phase=1;
             if(l[j]<=mid) consumed=true;
            }
          else
            {
             if(c[j]>top) { phase=2; t2=t[j]; break; }
             if(h[j]>=bot) phase=1;
             if(h[j]>=mid) consumed=true;
            }
         }
       SAOL x;
       x.top=top; x.bottom=bot; x.mid=mid;
       x.t1=t[b]; x.t2=t2; x.bull=bull;
       x.phase=phase; x.consumed=(consumed && phase!=2);
       int n=ArraySize(aols);
       ArrayResize(aols,n+1); aols[n]=x;
      }
   }

string PhaseName(const SAOL &x)
   {
    if(x.phase==2) return("INVALID");
    if(x.phase==1) return(x.consumed?"DIFF CONSUMED":"DIFFERENT");
    return("PURE");
   }

void DrawAOLs(const SAOL &aols[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(aols);
    int start=(n>InpMaxAOL)?n-InpMaxAOL:0;
    for(int k=start;k<n;k++)
      {
       datetime t2=(aols[k].t2==0?now:aols[k].t2);
       if(t2<=aols[k].t1) continue;
       bool dead=(aols[k].phase==2);
       string nm=InpPrefix+(aols[k].bull?"bull_":"bear_")+
                 TimeToString(aols[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color shade=(dead?InpInvalidColor:(aols[k].bull?InpBullColor:InpBearColor));
       color lineC=(dead?InpInvalidColor:(aols[k].bull?InpBullTxt:InpBearTxt));

       if(InpShowBox)
         {
          ObjectCreate(0,nm,OBJ_RECTANGLE,0,aols[k].t1,aols[k].top,t2,aols[k].bottom);
          ObjectSetInteger(0,nm,OBJPROP_COLOR,shade);
          ObjectSetInteger(0,nm,OBJPROP_STYLE,(dead?STYLE_DOT:STYLE_SOLID));
          ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm,OBJPROP_FILL,true);
          ObjectSetInteger(0,nm,OBJPROP_BACK,true);
          ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm,OBJPROP_TOOLTIP,
             StringFormat("%s AOL [%s..%s] | validation %s | invalidation %s | %s | formed %s -> %s",
                aols[k].bull?"Bullish":"Bearish",
                DoubleToString(aols[k].top,_Digits),DoubleToString(aols[k].bottom,_Digits),
                DoubleToString(aols[k].top,_Digits),DoubleToString(aols[k].bottom,_Digits),
                PhaseName(aols[k]),TimeToString(aols[k].t1),TimeToString(t2)));
         }

       if(InpShowLines)
         {
          string nv=nm+"_v", ni=nm+"_i", nc=nm+"_50";
          ObjectCreate(0,nv,OBJ_TREND,0,aols[k].t1,aols[k].top,t2,aols[k].top);
          ObjectSetInteger(0,nv,OBJPROP_COLOR,lineC);
          ObjectSetInteger(0,nv,OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,nv,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nv,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nv,OBJPROP_BACK,false);
          ObjectSetInteger(0,nv,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nv,OBJPROP_TOOLTIP,
             StringFormat("AOL validation %s",DoubleToString(aols[k].top,_Digits)));
          ObjectCreate(0,ni,OBJ_TREND,0,aols[k].t1,aols[k].bottom,t2,aols[k].bottom);
          ObjectSetInteger(0,ni,OBJPROP_COLOR,lineC);
          ObjectSetInteger(0,ni,OBJPROP_STYLE,STYLE_DOT);
          ObjectSetInteger(0,ni,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,ni,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,ni,OBJPROP_BACK,false);
          ObjectSetInteger(0,ni,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,ni,OBJPROP_TOOLTIP,
             StringFormat("AOL invalidation %s",DoubleToString(aols[k].bottom,_Digits)));
          ObjectCreate(0,nc,OBJ_TREND,0,aols[k].t1,aols[k].mid,t2,aols[k].mid);
          ObjectSetInteger(0,nc,OBJPROP_COLOR,InpMidColor);
          ObjectSetInteger(0,nc,OBJPROP_STYLE,STYLE_DOT);
          ObjectSetInteger(0,nc,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nc,OBJPROP_RAY_RIGHT,false);
          ObjectSetInteger(0,nc,OBJPROP_BACK,true);
          ObjectSetInteger(0,nc,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,nc,OBJPROP_TOOLTIP,"AOL 50% consumption line");
         }

       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(aols[k].bull?aols[k].top:aols[k].bottom);
          ObjectCreate(0,ln,OBJ_TEXT,0,aols[k].t1,px);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             StringFormat("AOL %s %s",aols[k].bull?"BULL":"BEAR",PhaseName(aols[k])));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,lineC);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (aols[k].bull?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
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
