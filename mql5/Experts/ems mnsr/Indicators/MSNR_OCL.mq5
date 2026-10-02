//+------------------------------------------------------------------+
//|                                                   MSNR_OCL.mq5   |
//|                         Advanced MSNR - Indicator 3              |
//|      OCL (Open Close Level) detection + classification           |
//+------------------------------------------------------------------+
//| Rules (Videos 1-2):                                               |
//|  OCL  : two CONSECUTIVE same-color candles -> line at the CLOSE   |
//|         of the FIRST candle. Engulfing OCLs are NOT traded.       |
//|                                                                   |
//|  Classification:                                                  |
//|   sOCL : bullish OCL formed right after a fresh Support level     |
//|   rOCL : bearish OCL formed right after a fresh Resistance level  |
//|   1LAB : the previous key level (in sequence) is ANOTHER OCL      |
//|          (not an S/R)                                             |
//|   LS   : an OCL that gets broken TWICE (acts as S, broke below,   |
//|          acts as R, broke back above - or mirror for bearish)     |
//|                                                                   |
//|  Lifecycle (close-through transitions, same style as Indicator 2):|
//|   Bullish OCL (acts as Support): close below -> acting R,         |
//|        close back above -> **LS OCL**, close below LS -> DEAD     |
//|   Bearish OCL: mirror.                                            |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars    = 500;               // Lookback bars
input int    InpMaxLevels       = 100;               // Max OCLs drawn (most recent)
input bool   InpSkipEngulfing   = false;              // Skip engulfing OCLs (body-engulf)
input bool   InpShowLabels      = true;              // Show classification labels
input bool   InpShowDead        = true;             // Keep drawing dead OCLs
input color  InpSuppSideColor   = clrDodgerBlue;     // Segment acting as support
input color  InpResSideColor    = clrTomato;         // Segment acting as resistance
input color  InpLSColor         = clrMediumPurple;   // LS OCL color
input color  InpDeadColor       = clrGray;           // Dead color
input int    InpLineWidth       = 1;                 // Line width
input string InpPrefix          = "MSNR_OCL_";       // Object name prefix

//+------------------------------------------------------------------+
//| types                                                            |
//+------------------------------------------------------------------+
enum ENUM_OCL_CLASS
  {
   OCL_PLAIN = 0,   // unclassified OCL
   OCL_SOCL  = 1,   // after Support        (bullish)
   OCL_ROCL  = 2,   // after Resistance     (bearish)
   OCL_1LAB  = 3    // previous key level was another OCL
  };

enum ENUM_OCL_BEHAVIOR
  {
   BEH_SUPPORT    = 0,  // currently acting as support
   BEH_RESISTANCE = 1,  // currently acting as resistance
   BEH_LS         = 2,  // broken twice -> LS OCL
   BEH_DEAD       = 3
  };

struct SSegment
  {
   ENUM_OCL_BEHAVIOR behavior;
   datetime          start_time;
   datetime          end_time;    // 0 = active
  };

struct SOclLevel
  {
   double          price;
   datetime        formed_time;   // time of the 2nd (same-color) candle
   long            formed_index;  // non-series bar index of 2nd candle
   bool            bullish;       // same-color pair direction
   ENUM_OCL_CLASS  cls;
   SSegment        segments[];
  };

SOclLevel g_ocls[];

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR OCL");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { DeleteAllObjects(); }

bool IsBull(const double &o[],const double &c[],int i) { return(c[i]>o[i]); }
bool IsBear(const double &o[],const double &c[],int i) { return(c[i]<o[i]); }

//+------------------------------------------------------------------+
//|                                                                  |
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
   ArraySetAsSeries(open,true);
   ArraySetAsSeries(high,true);
   ArraySetAsSeries(low,true);
   ArraySetAsSeries(close,true);
   ArraySetAsSeries(time,true);

   if(rates_total<3) return(0);

   static datetime last_bar_time=0;
   bool new_bar=(time[0]!=last_bar_time);
   if(prev_calculated!=0 && !new_bar) return(rates_total);
   last_bar_time=time[0];

//--- pass 1 (chronological): detect S/R pivots AND OCLs interleaved,
//--- keeping "last key level" for OCL classification
   ArrayResize(g_ocls,0);
   int scan=MathMin(InpLookbackBars,rates_total-2);

//--- last key level seen: 0 none, 1 support, 2 resistance, 3 OCL
   int  last_kl      = 0;
   bool last_kl_bull = false;

   for(int i=scan; i>=1; i--)
     {
      bool bull1=IsBull(open,close,i+1), bear1=IsBear(open,close,i+1);
      bool bull2=IsBull(open,close,i),   bear2=IsBear(open,close,i);

      bool is_support   =(bear1 && bull2);
      bool is_resistance=(bull1 && bear2);

      //--- OCL: two consecutive same-color candles. NOT engulfing.
      //--- Engulfing = candle2 BODY engulfs candle1 BODY (NOT wicks).
      //--- Wicks/gaps are irrelevant: level is always close of candle1.
      bool ocl_bull=(bull1 && bull2);
      bool ocl_bear=(bear1 && bear2);
      bool engulfing=false;
      if(ocl_bull)  engulfing=(open[i]<=open[i+1] && close[i]>=close[i+1]); // body2 covers body1
      if(ocl_bear)  engulfing=(open[i]>=open[i+1] && close[i]<=close[i+1]);
      if(!InpSkipEngulfing) engulfing=false;

      //--- an S/R pivot takes priority and updates "last key level"
      if(is_support)        { last_kl=1; last_kl_bull=true;  }
      else if(is_resistance){ last_kl=2; last_kl_bull=false; }
      else if((ocl_bull||ocl_bear) && !engulfing)
        {
         SOclLevel lv;
         lv.price       = close[i+1];       // close of FIRST candle
         lv.formed_time = time[i];
         lv.formed_index= rates_total-1-i;
         lv.bullish     = ocl_bull;
         lv.cls         = ClassifyOCL(ocl_bull,last_kl,last_kl_bull);
         ArrayResize(lv.segments,0);
         AddOCL(lv);

         last_kl      = 3;
         last_kl_bull = ocl_bull;
        }
      // engulfing same-color pairs: ignored entirely (not traded), and
      // they do NOT update the last key level.
     }

//--- pass 2: behavior segments (support side -> flip -> LS -> dead)
   int cnt=ArraySize(g_ocls);
   for(int k=0;k<cnt;k++)
      BuildSegments(g_ocls[k],time,close,rates_total);

//--- draw
   DrawLevels(time[0]+PeriodSeconds(PERIOD_CURRENT)*100);
   return(rates_total);
  }

//+------------------------------------------------------------------+
//| classification at birth                                          |
//+------------------------------------------------------------------+
ENUM_OCL_CLASS ClassifyOCL(bool bullish,int last_kl,bool last_kl_bull)
  {
   if(last_kl==3)                           return OCL_1LAB;  // prev key level was an OCL
   if(bullish && last_kl==1)                return OCL_SOCL;  // right after a Support
   if(!bullish && last_kl==2)               return OCL_ROCL;  // right after a Resistance
   return OCL_PLAIN;
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void AddOCL(const SOclLevel &lv)
  {
   int n=ArraySize(g_ocls);
   for(int i=0;i<n;i++)
      if(g_ocls[i].formed_time==lv.formed_time && g_ocls[i].price==lv.price)
         return;
   ArrayResize(g_ocls,n+1);
   g_ocls[n]=lv;
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void BuildSegments(SOclLevel &lv,const datetime &time[],const double &close[],int rates_total)
  {
   ENUM_OCL_BEHAVIOR beh = lv.bullish ? BEH_SUPPORT : BEH_RESISTANCE;
   PushSegment(lv,beh,lv.formed_time);
   int breaks=0;

   for(int i=(int)(rates_total-1-lv.formed_index)-1; i>=1; i--)
     {
      double c=close[i];
      bool   broke=false;

      switch(beh)
        {
         // acting as support: break = close below -> now acts as resistance
         case BEH_SUPPORT:    broke=(c<lv.price); if(broke) beh=BEH_RESISTANCE; break;
         // acting as resistance: break back above -> LS OCL
         case BEH_RESISTANCE: broke=(c>lv.price); if(broke) beh=(lv.bullish?BEH_LS:BEH_LS); break;
         // LS: one more break kills it
         case BEH_LS:
           if(lv.bullish)  { broke=(c<lv.price); }
           else            { broke=(c>lv.price); }
           if(broke) beh=BEH_DEAD;
           break;
         default: break;
        }

      if(broke)
        {
         breaks++;
         int last=ArraySize(lv.segments)-1;
         lv.segments[last].end_time=time[i];
         PushSegment(lv,beh,time[i]);
         if(beh==BEH_DEAD) break;
        }
     }
  }

void PushSegment(SOclLevel &lv,ENUM_OCL_BEHAVIOR beh,datetime start)
  {
   int n=ArraySize(lv.segments);
   ArrayResize(lv.segments,n+1);
   lv.segments[n].behavior=beh;
   lv.segments[n].start_time=start;
   lv.segments[n].end_time=0;
  }

//+------------------------------------------------------------------+
//| drawing                                                          |
//+------------------------------------------------------------------+
color BehColor(ENUM_OCL_BEHAVIOR b)
  {
   switch(b)
     {
      case BEH_SUPPORT:    return InpSuppSideColor;
      case BEH_RESISTANCE: return InpResSideColor;
      case BEH_LS:         return InpLSColor;
      default:             return InpDeadColor;
     }
  }

string ClassTag(ENUM_OCL_CLASS c)
  {
   switch(c)
     {
      case OCL_SOCL: return "sOCL";
      case OCL_ROCL: return "rOCL";
      case OCL_1LAB: return "1LAB";
      default:       return "OCL";
     }
  }

void DrawLevels(datetime future_time)
  {
   DeleteAllObjects();
   int cnt=ArraySize(g_ocls);
   int drawn=0;

   for(int k=cnt-1;k>=0 && drawn<InpMaxLevels;k--)
     {
      SOclLevel lv=g_ocls[k];
      int scount=ArraySize(lv.segments);
      if(scount==0) continue;
      if(lv.segments[scount-1].behavior==BEH_DEAD && !InpShowDead) continue;

      string base=InpPrefix+TimeToString(lv.formed_time,TIME_DATE)+"_"+DoubleToString(lv.price,_Digits);

      for(int s=0;s<scount;s++)
        {
         datetime t1=lv.segments[s].start_time;
         datetime t2=lv.segments[s].end_time;
         bool active=(t2==0);
         if(active) t2=future_time;
         if(t2<=t1) continue;

         ENUM_OCL_BEHAVIOR beh=lv.segments[s].behavior;
         string name=base+"_seg"+IntegerToString(s);
         color  clr=BehColor(beh);

         ObjectCreate(0,name,OBJ_TREND,0,t1,lv.price,t2,lv.price);
         ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
         ObjectSetInteger(0,name,OBJPROP_WIDTH,active?InpLineWidth+1:1);
         ObjectSetInteger(0,name,OBJPROP_STYLE,beh==BEH_DEAD?STYLE_DOT:STYLE_SOLID);
         ObjectSetInteger(0,name,OBJPROP_BACK,true);
         ObjectSetInteger(0,name,OBJPROP_SELECTABLE,true);
         ObjectSetString(0,name,OBJPROP_TOOLTIP,
            StringFormat("%s (%s) @ %s | %s -> %s",
               ClassTag(lv.cls),
               beh==BEH_SUPPORT?"acting S":beh==BEH_RESISTANCE?"acting R":beh==BEH_LS?"LS OCL":"dead",
               DoubleToString(lv.price,_Digits),
               TimeToString(t1),TimeToString(t2)));
        }

      if(InpShowLabels)
        {
         string lname=base+"_lbl";
         ObjectCreate(0,lname,OBJ_TEXT,0,lv.formed_time,lv.price);
         ObjectSetString(0,lname,OBJPROP_TEXT,ClassTag(lv.cls)+" "+DoubleToString(lv.price,_Digits));
         color lc=BehColor(lv.segments[ArraySize(lv.segments)-1].behavior);
         ObjectSetInteger(0,lname,OBJPROP_COLOR,lc);
         ObjectSetInteger(0,lname,OBJPROP_FONTSIZE,8);
         ObjectSetInteger(0,lname,OBJPROP_ANCHOR,lv.bullish?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0,lname,OBJPROP_BACK,true);
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
