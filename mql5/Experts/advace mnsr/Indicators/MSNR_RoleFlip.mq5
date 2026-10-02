//+------------------------------------------------------------------+
//|                                              MSNR_RoleFlip.mq5   |
//|                         Advanced MSNR - Indicator 2              |
//|        S/R levels with role flips: S->SBR->QM, R->RBS->QM        |
//+------------------------------------------------------------------+
//| Rules (Video 1 & 3):                                              |
//|  Base levels: 2-candle pivots, line at CLOSE of first candle      |
//|  (same engine as MSNR_Levels_SR, Indicator 1).                    |
//|                                                                   |
//|  Role lifecycle (transitions on candle CLOSE through the level):  |
//|   Support    --close below--> SBR (support becomes resistance)    |
//|   SBR        --close above--> QM  (failed SBR = Quasimodo)        |
//|   QM(from S) --close below--> DEAD (level no longer tracked)      |
//|   Resistance --close above--> RBS                                 |
//|   RBS        --close below--> QM                                  |
//|   QM(from R) --close above--> DEAD                                |
//|                                                                   |
//|  Each role is drawn as a separate colored segment so every        |
//|  transition can be visually verified against the chart.           |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars    = 500;              // Lookback bars (level detection)
input int    InpMaxLevels       = 40;               // Max levels drawn (most recent)
input bool   InpShowLabels      = true;             // Show role labels
input bool   InpShowDead        = false;            // Keep drawing dead levels (gray)
input color  InpSupportColor    = clrDodgerBlue;    // Support color
input color  InpResistanceColor = clrTomato;        // Resistance color
input color  InpSBRColor        = clrDarkOrange;    // SBR color
input color  InpRBSColor        = clrMediumSeaGreen;// RBS color
input color  InpQMColor         = clrMediumPurple;  // QM color
input color  InpDeadColor       = clrGray;          // Dead level color
input int    InpLineWidth       = 1;                // Line width
input string InpPrefix          = "MSNR_RF_";       // Object name prefix

//+------------------------------------------------------------------+
//| roles                                                            |
//+------------------------------------------------------------------+
enum ENUM_MSNR_ROLE
  {
   ROLE_SUPPORT = 0,
   ROLE_SBR     = 1,   // support broken -> resistance
   ROLE_QM_FROM_S = 2, // SBR broken -> quasimodo (acts as support)
   ROLE_RESISTANCE = 3,
   ROLE_RBS     = 4,   // resistance broken -> support
   ROLE_QM_FROM_R = 5, // RBS broken -> quasimodo (acts as resistance)
   ROLE_DEAD    = 6
  };

//--- a drawn segment of a level's life
struct SSegment
  {
   ENUM_MSNR_ROLE role;
   datetime       start_time;
   datetime       end_time;   // 0 => still active (extends to now)
  };

//--- level record
struct SLevel
  {
   double   price;
   datetime formed_time;
   long     formed_index;   // non-series bar index of 2nd (confirming) candle
   bool     starts_support; // true: starts as Support, false: starts as Resistance
   SSegment segments[];
  };

SLevel g_levels[];

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Role Flip (SBR/RBS/QM)");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { DeleteAllObjects(); }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
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
   ArraySetAsSeries(close,true);
   ArraySetAsSeries(time,true);

   if(rates_total<3) return(0);

   static datetime last_bar_time=0;
   bool new_bar=(time[0]!=last_bar_time);
   if(prev_calculated!=0 && !new_bar) return(rates_total);
   last_bar_time=time[0];

//--- 1) detect base levels (same engine as Indicator 1)
   ArrayResize(g_levels,0);
   int scan=MathMin(InpLookbackBars,rates_total-2);
   for(int i=scan; i>=1; i--)
     {
      bool bull1=IsBull(open,close,i+1), bear1=IsBear(open,close,i+1);
      bool bull2=IsBull(open,close,i),   bear2=IsBear(open,close,i);
      bool is_support=(bear1 && bull2), is_resistance=(bull1 && bear2);
      if(!is_support && !is_resistance) continue;

      SLevel lv;
      lv.price=close[i+1];
      lv.formed_time=time[i];
      lv.formed_index=rates_total-1-i;
      lv.starts_support=is_support;
      ArrayResize(lv.segments,0);
      AddLevel(lv);
     }

//--- 2) walk each level forward in time, building role segments
   int cnt=ArraySize(g_levels);
   for(int k=0;k<cnt;k++)
      BuildSegments(g_levels[k],time,close,rates_total);

//--- 3) draw
   DrawLevels(time[0]+PeriodSeconds(PERIOD_CURRENT)*100);
   return(rates_total);
  }

//+------------------------------------------------------------------+
//| add level (no duplicates by formed_time)                         |
//+------------------------------------------------------------------+
void AddLevel(const SLevel &lv)
  {
   int n=ArraySize(g_levels);
   for(int i=0;i<n;i++)
      if(g_levels[i].formed_time==lv.formed_time && g_levels[i].price==lv.price)
         return;
   ArrayResize(g_levels,n+1);
   g_levels[n]=lv;
  }

//+------------------------------------------------------------------+
//| build the role segments for one level                            |
//+------------------------------------------------------------------+
void BuildSegments(SLevel &lv,const datetime &time[],const double &close[],int rates_total)
  {
   ENUM_MSNR_ROLE role = lv.starts_support ? ROLE_SUPPORT : ROLE_RESISTANCE;
   datetime seg_start  = lv.formed_time;

   PushSegment(lv,role,seg_start);

//--- iterate bars AFTER formation, oldest -> newest (series: index decreasing)
   for(int i=(int)(rates_total-1-lv.formed_index)-1; i>=1; i--)
     {
      double c=close[i];
      bool   broke=false;

      switch(role)
        {
         case ROLE_SUPPORT:    broke=(c<lv.price); if(broke) role=ROLE_SBR;        break;
         case ROLE_SBR:        broke=(c>lv.price); if(broke) role=ROLE_QM_FROM_S;  break;
         case ROLE_QM_FROM_S:  broke=(c<lv.price); if(broke) role=ROLE_DEAD;       break;
         case ROLE_RESISTANCE: broke=(c>lv.price); if(broke) role=ROLE_RBS;        break;
         case ROLE_RBS:        broke=(c<lv.price); if(broke) role=ROLE_QM_FROM_R;  break;
         case ROLE_QM_FROM_R:  broke=(c>lv.price); if(broke) role=ROLE_DEAD;       break;
         default: break;
        }

      if(broke)
        {
         // close current segment at this bar, open the new role segment
         int last=ArraySize(lv.segments)-1;
         lv.segments[last].end_time=time[i];
         seg_start=time[i];
         PushSegment(lv,role,seg_start);
         if(role==ROLE_DEAD) break;
        }
     }
  }

void PushSegment(SLevel &lv,ENUM_MSNR_ROLE role,datetime start)
  {
   int n=ArraySize(lv.segments);
   ArrayResize(lv.segments,n+1);
   lv.segments[n].role=role;
   lv.segments[n].start_time=start;
   lv.segments[n].end_time=0;
  }

//+------------------------------------------------------------------+
//| drawing                                                          |
//+------------------------------------------------------------------+
color RoleColor(ENUM_MSNR_ROLE r)
  {
   switch(r)
     {
      case ROLE_SUPPORT:    return InpSupportColor;
      case ROLE_RESISTANCE: return InpResistanceColor;
      case ROLE_SBR:        return InpSBRColor;
      case ROLE_RBS:        return InpRBSColor;
      case ROLE_QM_FROM_S:
      case ROLE_QM_FROM_R:  return InpQMColor;
      default:              return InpDeadColor;
     }
  }

string RoleTag(ENUM_MSNR_ROLE r)
  {
   switch(r)
     {
      case ROLE_SUPPORT:    return "S";
      case ROLE_RESISTANCE: return "R";
      case ROLE_SBR:        return "SBR";
      case ROLE_RBS:        return "RBS";
      case ROLE_QM_FROM_S:
      case ROLE_QM_FROM_R:  return "QM";
      default:              return "X";
     }
  }

void DrawLevels(datetime future_time)
  {
   DeleteAllObjects();
   int cnt=ArraySize(g_levels);
   int drawn=0;

   for(int k=cnt-1;k>=0 && drawn<InpMaxLevels;k--)
     {
      SLevel lv=g_levels[k];
      int scount=ArraySize(lv.segments);
      if(scount==0) continue;

      ENUM_MSNR_ROLE final_role=lv.segments[scount-1].role;
      if(final_role==ROLE_DEAD && !InpShowDead) continue;

      string base_name=InpPrefix+TimeToString(lv.formed_time,TIME_DATE)+"_"+
                       DoubleToString(lv.price,_Digits);

      for(int s=0;s<scount;s++)
        {
         ENUM_MSNR_ROLE role=lv.segments[s].role;
         datetime t1=lv.segments[s].start_time;
         datetime t2=lv.segments[s].end_time;
         bool active=(t2==0);
         if(active) t2=future_time;

         // don't draw zero-length segments
         if(t2<=t1) continue;

         string name=base_name+"_seg"+IntegerToString(s);
         color  clr=RoleColor(role);

         ObjectCreate(0,name,OBJ_TREND,0,t1,lv.price,t2,lv.price);
         ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
         ObjectSetInteger(0,name,OBJPROP_WIDTH,active?InpLineWidth:1);
         ObjectSetInteger(0,name,OBJPROP_STYLE,ROLE_DEAD==role?STYLE_DOT:STYLE_SOLID);
         ObjectSetInteger(0,name,OBJPROP_RAY_RIGHT,false);
         ObjectSetInteger(0,name,OBJPROP_BACK,true);
         ObjectSetInteger(0,name,OBJPROP_SELECTABLE,true);
         ObjectSetString(0,name,OBJPROP_TOOLTIP,
            StringFormat("MSNR %s @ %s | %s -> %s",
               RoleTag(role),DoubleToString(lv.price,_Digits),
               TimeToString(t1),TimeToString(t2)));

         if(InpShowLabels)
           {
            string lname=name+"_lbl";
            ObjectCreate(0,lname,OBJ_TEXT,0,t1,lv.price);
            ObjectSetString(0,lname,OBJPROP_TEXT,RoleTag(role)+" "+DoubleToString(lv.price,_Digits));
            ObjectSetInteger(0,lname,OBJPROP_COLOR,clr);
            ObjectSetInteger(0,lname,OBJPROP_FONTSIZE,8);
            bool upper=(role==ROLE_RESISTANCE||role==ROLE_SBR||role==ROLE_QM_FROM_R);
            ObjectSetInteger(0,lname,OBJPROP_ANCHOR,upper?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER);
            ObjectSetInteger(0,lname,OBJPROP_BACK,true);
           }
        }
      drawn++;
     }
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
