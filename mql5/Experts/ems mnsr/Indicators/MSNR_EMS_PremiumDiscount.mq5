//+------------------------------------------------------------------+
//|                                     MSNR_EMS_PremiumDiscount.mq5 |
//|              EMS Indicator E5: Premium / Discount (PD50)          |
//+------------------------------------------------------------------+
//| Rules (EMS Part 1 §3, #10:19-22, indicatorplan E5):               |
//|                                                                   |
//|  Swing = latest BOS-validated range ("a swing is only validated   |
//|  when a subsequent BOS happens", #10:38). Window = last BOS ->    |
//|  now (same leg as E4); high = max high, low = min low. One fib-   |
//|  style overlay, auto-redrawn per new BOS.                         |
//|  Premium = above 50% (sells only), Discount = below 50% (buys     |
//|  only). validSetup per side: at least one UNBROKEN 2-candle S/R   |
//|  level of the MATCHING type (premium -> resistance/A-shape,       |
//|  discount -> support/V-shape) formed INSIDE the current leg        |
//|  window (no close-through since formation, I1 parity) on the       |
//|  correct side of PD50.                                             |
//|  Levels formed at/before legStart are outside the swing box and    |
//|  must not count (correction §15). Labels show POI / no-POI;        |
//|  tooltips carry the counts. Closed bars only. ONE range drawn,     |
//|  no rays.                                                          |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars = 500;               // Lookback bars
input bool   InpShowZones    = true;              // Draw premium/discount shades
input bool   InpShowLevels   = true;              // Draw 0 / 50 / 100 lines
input bool   InpShowLabels   = true;              // Show Premium / Discount / PD50 labels
input color  InpPremiumColor = clrMistyRose;      // Premium shade (sells)
input color  InpDiscountColor = clrHoneydew;      // Discount shade (buys)
input color  InpEdgeColor    = clrDarkGray;       // Swing high/low lines
input color  InpMidColor     = clrDimGray;        // PD50 midline
input color  InpValidColor   = clrSeaGreen;       // "POI" suffix when side is valid
input color  InpInvalidColor = clrGray;           // "no POI" suffix when side is empty
input string InpPrefix       = "MSNR_PD_";        // Object name prefix

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
    int      dir;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Premium/Discount");
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

    DeleteAllObjects();

    //--- 1) last BOS (E2/E4 parity) -> swing window
    SBos bosses[];
    FindBOS(time,open,close,bosses);
    datetime legStart=time[MathMin(InpLookbackBars,rates_total-1)];
    if(ArraySize(bosses)>0)
       legStart=bosses[ArraySize(bosses)-1].time;

    int startIdx=FindBar(time,legStart,rates_total);
    if(startIdx<2) startIdx=2;
    double sh=high[1], sl=low[1];
    for(int j=1;j<=startIdx;j++)
      {
       if(high[j]>sh) sh=high[j];
       if(low[j]<sl)  sl=low[j];
      }
    if(sh-sl<_Point) sh=sl+_Point;
    double mid=(sh+sl)/2.0;
    datetime now=time[0];

    //--- 2) validity: unbroken S/R levels per side of PD50
    int premN=0,discN=0;
    CountSidePOIs(time,open,close,rates_total,mid,sh,sl,legStart,premN,discN);
    bool sellOK=(premN>0), buyOK=(discN>0);

    //--- 3) shades
    if(InpShowZones)
      {
       DrawShade("prem",legStart,now,sh,mid,InpPremiumColor,
          StringFormat("Premium (sells) [%s..%s] | %d unbroken POI -> %s",
             DoubleToString(sh,_Digits),DoubleToString(mid,_Digits),
             premN,sellOK?"validSetup":"NO setup"));
       DrawShade("disc",legStart,now,mid,sl,InpDiscountColor,
          StringFormat("Discount (buys) [%s..%s] | %d unbroken POI -> %s",
             DoubleToString(mid,_Digits),DoubleToString(sl,_Digits),
             discN,buyOK?"validSetup":"NO setup"));
      }

    //--- 4) 0 / 50 / 100 lines
    if(InpShowLevels)
      {
       DrawLine("hi",legStart,now,sh,InpEdgeColor,STYLE_SOLID,1,
          StringFormat("Swing high %s (leg %s -> now)",
             DoubleToString(sh,_Digits),TimeToString(legStart)));
       DrawLine("lo",legStart,now,sl,InpEdgeColor,STYLE_SOLID,1,
          StringFormat("Swing low %s (leg %s -> now)",
             DoubleToString(sl,_Digits),TimeToString(legStart)));
       DrawLine("pd50",legStart,now,mid,InpMidColor,STYLE_DASH,2,
          StringFormat("PD50 %s",DoubleToString(mid,_Digits)));
      }

    //--- 5) labels
    if(InpShowLabels)
      {
       DrawLabel("prem_lbl",legStart,sh,
          "Premium (sells)"+(sellOK?" POI":" no POI"),
          sellOK?InpValidColor:InpInvalidColor,ANCHOR_LEFT_UPPER);
       DrawLabel("disc_lbl",legStart,sl,
          "Discount (buys)"+(buyOK?" POI":" no POI"),
          buyOK?InpValidColor:InpInvalidColor,ANCHOR_LEFT_LOWER);
       DrawLabel("pd50_lbl",legStart,mid,
          "PD50 "+DoubleToString(mid,_Digits),InpMidColor,ANCHOR_LEFT_UPPER);
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

//--- first close-through per level, ascending (E2/E4 parity)
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
    for(int i=1;i<ArraySize(bos);i++)
      {
       SBos v=bos[i]; int j=i-1;
       while(j>=0 && bos[j].time>v.time) { bos[j+1]=bos[j]; j--; }
       bos[j+1]=v;
      }
   }

//--- count levels that were never closed through and sit per side of mid
void CountSidePOIs(const datetime &t[],const double &o[],const double &c[],
                   int rates_total,double mid,double sh,double sl,datetime legStart,
                   int &premN,int &discN)
   {
    premN=0; discN=0;
    SLevel lv[];
    DetectLevels(t,o,c,lv);
    for(int k=0;k<ArraySize(lv);k++)
      {
       if(lv[k].formed_time<=legStart) continue;  // outside the current swing box
       bool broken=false;
       for(int j=lv[k].formed_idx-1;j>=1;j--)
         {
          if(lv[k].is_support && c[j]<lv[k].price) { broken=true; break; }
          if(!lv[k].is_support && c[j]>lv[k].price) { broken=true; break; }
         }
        if(broken) continue;
        // POI type must match the side (Part 1 / correction §15):
        // premium (sells) -> resistance (A-shape), discount (buys) -> support (V-shape)
        if(!lv[k].is_support && lv[k].price>=mid && lv[k].price<=sh) premN++;
        else if(lv[k].is_support && lv[k].price<mid && lv[k].price>=sl) discN++;
      }
   }

void DrawShade(const string kind,datetime t1,datetime t2,double top,double bot,
               color clr,const string tip)
   {
    if(t2<=t1 || top<=bot) return;
    string nm=InpPrefix+kind+"_"+TimeToString(t1,TIME_DATE|TIME_MINUTES);
    ObjectCreate(0,nm,OBJ_RECTANGLE,0,t1,top,t2,bot);
    ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
    ObjectSetInteger(0,nm,OBJPROP_FILL,true);
    ObjectSetInteger(0,nm,OBJPROP_BACK,true);
    ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
    ObjectSetString(0,nm,OBJPROP_TOOLTIP,tip);
   }

void DrawLine(const string kind,datetime t1,datetime t2,double px,
              color clr,ENUM_LINE_STYLE st,int w,const string tip)
   {
    if(t2<=t1) return;
    string nm=InpPrefix+kind+"_"+TimeToString(t1,TIME_DATE|TIME_MINUTES);
    ObjectCreate(0,nm,OBJ_TREND,0,t1,px,t2,px);
    ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
    ObjectSetInteger(0,nm,OBJPROP_STYLE,st);
    ObjectSetInteger(0,nm,OBJPROP_WIDTH,w);
    ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
    ObjectSetInteger(0,nm,OBJPROP_BACK,false);
    ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
    ObjectSetString(0,nm,OBJPROP_TOOLTIP,tip);
   }

void DrawLabel(const string kind,datetime t,double px,const string txt,
               color clr,ENUM_ANCHOR_POINT anchor)
   {
    string nm=InpPrefix+kind;
    ObjectCreate(0,nm,OBJ_TEXT,0,t,px);
    ObjectSetString(0,nm,OBJPROP_TEXT,txt);
    ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
    ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8);
    ObjectSetInteger(0,nm,OBJPROP_ANCHOR,anchor);
    ObjectSetInteger(0,nm,OBJPROP_BACK,true);
    ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
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
