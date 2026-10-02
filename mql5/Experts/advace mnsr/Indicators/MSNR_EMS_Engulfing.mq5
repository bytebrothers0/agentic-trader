//+------------------------------------------------------------------+
//|                                       MSNR_EMS_Engulfing.mq5     |
//|              EMS Indicator E1: Engulfing (EG) + Engulfing Fail    |
//+------------------------------------------------------------------+
//| Rules (correction rule for all.md):                                 |
//|                                                                   |
//|  Detection: body-engulfing (candle2 body covers candle1 body).    |
//|   Bull EG: close2 > open1 && open2 <= close1 (tie allowed).       |
//|   Bear EG: mirror. Opposite-color only by default; doji c1 counts |
//|   as either polarity, c2 must be a real body. Relaxed mode        |
//|   (InpAllowInsideOpen): c2 may open INSIDE c1's body provided it  |
//|   still closes beyond c1's far edge AND its body is >= c1's body  |
//|   x InpMinBodyRatio - catches the obvious Aug/Sep daily bears     |
//|   that open inside and still clearly engulf.                      |
//|                                                                   |
//|  Zone price rule (per-side wick exception + bias-side max):       |
//|   upW = high-max(open,close), loW = min(open,close)-low.          |
//|   Buys: if candle1 UPPER wick > candle2 upper wick OR > body2,    |
//|    it is an outlier -> clamp to BODY + lower wick: top =          |
//|    max(open1,close1). Else the whole candle1 counts: top = high1. |
//|   Sells: mirror on the lower wick (clamp -> bot = min(open1,      |
//|    close1), else bot = low1). Bias side always takes the highest  |
//|   wick of EITHER candle: buys bot = min(low1,low2), sells top =   |
//|   max(high1,high2). The opposite side never uses candle2.         |
//|  Time rule: box starts at candle1 open and covers exactly 3 slots |
//|  (candle1, candle2, empty candle3 pullback slot) => right edge =  |
//|  time(candle2) + 2*PeriodSeconds. Box NEVER rays to the future.   |
//|                                                                   |
//|  Lifecycle / EF (OFF by default): this is a pure EG marker.      |
//|  InpMarkEGOnly=true draws EVERY detected zone in its birth color  |
//|  (solid blue bull / red bear) no matter what price does later.    |
//|  Set false to re-enable EG -> EF -> DEAD recoloring.              |
//|  EF triggers (plan sec.37): price closes beyond the zone, OR an  |
//|  opposite-direction EG forms overlapping the zone. A "touched"    |
//|  flag marks zones price has tapped (tooltip + label suffix).      |
//|                                                                   |
//|  Rendering: ONE fixed 3-step border box per zone (no rays), solid |
//|  EG / dashed EF / dotted DEAD, 50% midline, EG/EF tag at box      |
//|  start; tooltips carry the full state.                            |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.60"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars    = 500;               // Lookback bars
input int    InpMaxZones        = 100;               // Max zones drawn (most recent)
input bool   InpMarkEGOnly      = true;             // Pure EG marker: draw every zone, ignore later price (no EF/DEAD)
input bool   InpOppositeColorOnly = true;           // EG must be opposite-color (correction rule sec.24 strict rule; false = mark ALL body engulfs)
input bool   InpAllowInsideOpen = true;              // Allow c2 open inside c1 body if close is beyond + body bigger
input double InpMinBodyRatio   = 1.0;                // Relaxed mode: body2 >= body1 x ratio
input bool   InpDeadUseEgColor = true;               // Dead zones keep original EG color (dotted) instead of gray
input bool   InpShowLabels      = true;              // Show EG/EF labels
input bool   InpShowDead        = true;              // Keep drawing dead zones (else old EGs look "missed")
input bool   InpFillZones       = false;             // Fill zones (TFL uses border-only)
input bool   InpShowEquilibrium = true;              // Draw 50% midlines (TFL-style)
input color  InpEqColor         = clrGray;           // Equilibrium midline
input color  InpBullColor       = clrDodgerBlue;     // Bullish EG (support)
input color  InpBearColor       = clrTomato;         // Bearish EG (resistance)
input color  InpEFBearColor     = clrRed;            // EF (failed bull -> resistance)
input color  InpEFBullColor     = clrMediumSeaGreen; // EF (failed bear -> support)
input color  InpDeadColor       = clrGray;           // Dead
input string InpPrefix          = "MSNR_EG_";        // Object name prefix

enum ENUM_EG_ROLE { EG_BULL=0, EG_BEAR=1, EF_BEAR=2, EF_BULL=3, DEAD=4 };

struct SZone
   {
    double    top;
    double    bot;
    datetime  t1;
    datetime  base_end;      // fixed 3-slot right edge (never extended)
    long      formed_idx;    // non-series index of candle1 (engulfed)
     bool      bull_;         // original direction
     ENUM_EG_ROLE cur_role;   // current role after forward walk
     bool      touched;       // price has tapped inside the zone (pullback slot used)
   };

SZone g_zones[];

//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR EMS Engulfing (EG/EF)");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { DeleteAllObjects(); }

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

   int stepSec=(int)PeriodSeconds(Period());

//--- detect EG zones at closed bars: candle2=series i, candle1=i+1
   ArrayResize(g_zones,0);
   int scan=MathMin(InpLookbackBars,rates_total-2);
   for(int i=scan;i>=1;i--)
      {
       bool bull=false, bear=false;
       ClassifyEG(open,close,i,bull,bear);
       if(!bull && !bear) continue;
       double o1=open[i+1], c1=close[i+1], o2=open[i], c2=close[i];
       double h1=high[i+1], l1=low[i+1], h2=high[i], l2=low[i];

       double top,bot;
       //--- per-side wick exception: only the OUTLIER opposite wick is cut.
       //--- Buys: upper wick1 vs (upper wick2 OR body2); sells: mirror.
       //--- Bias side always max of either candle; opposite side is c1 only.
       double body2=MathAbs(c2-o2);
       if(bull)
         {
          double upW1=h1-MathMax(o1,c1), upW2=h2-MathMax(o2,c2);
          bool clamp=(upW1>upW2 || upW1>body2);
          top=clamp?MathMax(o1,c1):h1;
          bot=MathMin(l1,l2);
         }
       else
         {
          double loW1=MathMin(o1,c1)-l1, loW2=MathMin(o2,c2)-l2;
          bool clamp=(loW1>loW2 || loW1>body2);
          bot=clamp?MathMin(o1,c1):l1;
          top=MathMax(h1,h2);
         }
       //--- hard guarantee a visible box: never allow zero height
       if(top-bot<_Point) top=bot+_Point;

       SZone z;
       z.top=top; z.bot=bot;
       z.t1=time[i+1];               // candle1 open: left edge
       z.base_end=time[i]+2*stepSec; // candle2 open + 2 steps = covers c1/c2/c3
       if(z.base_end<=z.t1) z.base_end=z.t1+3*stepSec; // weekend-gap guard
       z.formed_idx=rates_total-1-(i+1);   // non-series idx of candle1
       z.bull_=bull;
       z.cur_role=bull?EG_BULL:EG_BEAR;
       AddZone(z);
      }

//--- 2) lifecycle: touched flag always tracked; EF/DEAD only when asked
   int cnt=ArraySize(g_zones);
   for(int k=0;k<cnt;k++)
      {
       bool touched=false;
       ENUM_EG_ROLE role=CurrentRole(g_zones[k],time,open,high,low,close,rates_total,touched);
       g_zones[k].touched=touched;
       if(InpMarkEGOnly)
          g_zones[k].cur_role=g_zones[k].bull_?EG_BULL:EG_BEAR;
       else
          g_zones[k].cur_role=role;
      }

//--- 3) draw single fixed boxes
   DrawZones();
   return(rates_total);
  }

//--- single source of truth for EG classification (series arrays,
//--- candle2 = i, candle1 = i+1). Strict = full body cover, ties allowed
//--- on the near edge. Relaxed = inside-open with close beyond c1's far
//--- edge + clearly bigger body (catches Aug/Sep daily bears). Opposite-
//--- color filter is doji-tolerant on candle1 (open==close = either
//--- polarity) but candle2 must be a real body.
void ClassifyEG(const double &open[],const double &close[],int i,bool &bull,bool &bear)
   {
    double o1=open[i+1], c1=close[i+1], o2=open[i], c2=close[i];
    double body1=MathAbs(c1-o1), body2=MathAbs(c2-o2);
    bool strictBull=(c2>o1 && o2<=c1);
    bool strictBear=(c2<o1 && o2>=c1);
    bool relaxedBull=(InpAllowInsideOpen && c2>o1 && c2>o2 &&
                      body2>=body1*InpMinBodyRatio && body2>_Point);
    bool relaxedBear=(InpAllowInsideOpen && c2<o1 && c2<o2 &&
                      body2>=body1*InpMinBodyRatio && body2>_Point);
    bool bear1=(c1<=o1), bull1=(c1>=o1);
    bool bear2=(c2<o2),  bull2=(c2>o2);
    bull=(strictBull||relaxedBull) && (!InpOppositeColorOnly || (bear1 && bull2));
    bear=(strictBear||relaxedBear) && (!InpOppositeColorOnly || (bull1 && bear2));
   }

//+------------------------------------------------------------------+
void AddZone(const SZone &z)
  {
   int n=ArraySize(g_zones);
   for(int k=0;k<n;k++)
      if(g_zones[k].t1==z.t1 && g_zones[k].top==z.top && g_zones[k].bot==z.bot)
         return;
   ArrayResize(g_zones,n+1);
   g_zones[n]=z;
  }

//--- role walk on closes. Bull EG: breaks on close < bot (after candle2),
//--- OR when a bear EG forms overlapping the zone (plan sec.37). EF_BEAR
//--- broken back above top -> DEAD. Bear mirror. "touched" = any bar whose
//--- range enters the zone after candle2 (pullback slot used). Returns the
//--- CURRENT role; the box coordinates never move.
ENUM_EG_ROLE CurrentRole(const SZone &z,const datetime &time[],const double &open[],
                         const double &high[],const double &low[],
                         const double &close[],int rates_total,bool &touched)
   {
    ENUM_EG_ROLE role=z.bull_?EG_BULL:EG_BEAR;
    touched=false;
    // bars strictly AFTER the engulfing pair so candle2 never instant-fails
    for(int i=(int)(rates_total-1-z.formed_idx)-2; i>=1; i--)
      {
       double c=close[i];
       if(!touched && low[i]<=z.top && high[i]>=z.bot) touched=true;
       switch(role)
         {
          case EG_BULL: if(c<z.bot) role=EF_BEAR; break;
          case EF_BEAR: if(c>z.top) role=DEAD;    break;
          case EG_BEAR: if(c>z.top) role=EF_BULL; break;
          case EF_BULL: if(c<z.bot) role=DEAD;    break;
          default: break;
         }
       if(role==DEAD) break;
       //--- EF on opposite EG forming at the zone: engulfed candle c1body
       //--- must overlap the zone (plan sec.37 second trigger)
       bool b2bull=false,b2bear=false;
       if(i>=1)
         {
          ClassifyEG(open,close,i,b2bull,b2bear);
          double c1hi=MathMax(open[i+1],close[i+1]);
          double c1lo=MathMin(open[i+1],close[i+1]);
          bool overlaps=(c1lo<=z.top && c1hi>=z.bot);
          if(overlaps)
            {
             if(role==EG_BULL && b2bear) role=EF_BEAR;
             else if(role==EF_BEAR && b2bull) role=DEAD;
             else if(role==EG_BEAR && b2bull) role=EF_BULL;
             else if(role==EF_BULL && b2bear) role=DEAD;
            }
          if(role==DEAD) break;
         }
      }
    return(role);
   }

//+------------------------------------------------------------------+
color RoleColor(ENUM_EG_ROLE r)
  {
   switch(r)
     {
      case EG_BULL: return(InpBullColor);
      case EG_BEAR: return(InpBearColor);
      case EF_BEAR: return(InpEFBearColor);
      case EF_BULL: return(InpEFBullColor);
      default:      return(InpDeadColor);
     }
  }

string RoleTag(ENUM_EG_ROLE r)
  {
   switch(r)
     {
      case EG_BULL: return("EG Bull");
      case EG_BEAR: return("EG Bear");
      case EF_BEAR: return("EF Bear");
      case EF_BULL: return("EF Bull");
      default:      return("Dead");
     }
  }

ENUM_LINE_STYLE RoleStyle(ENUM_EG_ROLE r)
  {
   if(r==EF_BEAR || r==EF_BULL) return(STYLE_DASH);
   if(r==DEAD)                  return(STYLE_DOT);
   return(STYLE_SOLID);
  }

void DrawZones()
   {
    DeleteAllObjects();
    int cnt=ArraySize(g_zones);
    int drawn=0;

    for(int k=cnt-1;k>=0 && drawn<InpMaxZones;k--)
      {
       ENUM_EG_ROLE r=g_zones[k].cur_role;
       if(r==DEAD && !InpShowDead) continue;

       datetime t1=g_zones[k].t1;
       datetime t2=g_zones[k].base_end;
       if(t2<=t1) continue;

       color clr=RoleColor(r);
       //--- dead zones keep their birth color so old bears still read red
       //--- like your manual boxes (dotted style still marks them dead)
       if(r==DEAD && InpDeadUseEgColor)
          clr=g_zones[k].bull_?InpBullColor:InpBearColor;
       string base=InpPrefix+(g_zones[k].bull_?"B":"S")+"_"+
                   TimeToString(g_zones[k].t1,TIME_DATE|TIME_MINUTES)+"_"+
                   DoubleToString(g_zones[k].bot,_Digits);
       string nm=base;

       //--- ONE fixed 3-step box, recolored by current role (no rays)
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,t1,g_zones[k].top,t2,g_zones[k].bot);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,RoleStyle(r));
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm,OBJPROP_FILL,InpFillZones);
       ObjectSetInteger(0,nm,OBJPROP_BACK,false);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("EG %s zone [%s..%s] | %s -> %s | role %s%s",
             g_zones[k].bull_?"bull":"bear",
             DoubleToString(g_zones[k].top,_Digits),
             DoubleToString(g_zones[k].bot,_Digits),
             TimeToString(t1),TimeToString(t2),RoleTag(r),
             g_zones[k].touched?" | touched (pullback tapped)":""));

       //--- 50% equilibrium midline (same c1-c3 span)
       if(InpShowEquilibrium)
         {
          double mid=(g_zones[k].top+g_zones[k].bot)/2.0;
          string en=nm+"_eq";
          ObjectCreate(0,en,OBJ_TREND,0,t1,mid,t2,mid);
          ObjectSetInteger(0,en,OBJPROP_COLOR,InpEqColor);
          ObjectSetInteger(0,en,OBJPROP_STYLE,STYLE_DOT);
          ObjectSetInteger(0,en,OBJPROP_WIDTH,1);
          ObjectSetInteger(0,en,OBJPROP_BACK,false);
          ObjectSetInteger(0,en,OBJPROP_SELECTABLE,false);
          ObjectSetString(0,en,OBJPROP_TOOLTIP,
             StringFormat("EG equilibrium %s (50%%)",DoubleToString(mid,_Digits)));
         }

       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,t1,g_zones[k].top);
          ObjectSetString(0,ln,OBJPROP_TEXT,RoleTag(r)+(g_zones[k].touched?"*":""));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          bool upper=(r==EG_BEAR||r==EF_BEAR);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,upper?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER);
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
       drawn++;
      }
   ChartRedraw();
  }

void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
