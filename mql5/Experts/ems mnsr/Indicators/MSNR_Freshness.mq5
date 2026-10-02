//+------------------------------------------------------------------+
//|                                              MSNR_Freshness.mq5  |
//|                         Advanced MSNR - Indicator 4              |
//|   Fresh vs Unfresh (mitigation) state on S/R role-flip levels    |
//+------------------------------------------------------------------+
//| Rules (Video 4):                                                  |
//|  FRESH   : level has NOT been touched since it was created.       |
//|            No subsequent candle has wicked into / tested it.      |
//|  UNFRESH : the first time price returns and touches the level     |
//|            (even just a wick) it becomes mitigated = unfresh.     |
//|  RE-FRESH: when an unfresh level is BROKEN (body close through)   |
//|            it flips role (S->SBR, SBR->QM, ...) and becomes FRESH |
//|            again in its new role.                                 |
//|                                                                   |
//|  Rendering: SOLID segment = fresh, DASHED segment = unfresh.      |
//|  Colors follow the role (same convention as MSNR_RoleFlip).       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars    = 500;               // Lookback bars
input int    InpMaxLevels       = 40;                // Max levels drawn (most recent)
input bool   InpShowLabels      = true;              // Show role labels
input bool   InpShowDead        = false;             // Keep drawing dead levels
input int    InpTouchTolerancePoints = 0;            // Touch tolerance (points)
input color  InpSupportColor    = clrDodgerBlue;     // Support
input color  InpResistanceColor = clrTomato;         // Resistance
input color  InpSBRColor        = clrDarkOrange;     // SBR
input color  InpRBSColor        = clrMediumSeaGreen; // RBS
input color  InpQMColor         = clrMediumPurple;   // QM
input color  InpDeadColor       = clrGray;           // Dead
input int    InpLineWidth       = 2;                 // Fresh segment width
input string InpPrefix          = "MSNR_FR_";        // Object name prefix

//+------------------------------------------------------------------+
//| roles (same as Indicator 2)                                      |
//+------------------------------------------------------------------+
enum ENUM_MSNR_ROLE
  {
   ROLE_SUPPORT    = 0,
   ROLE_SBR        = 1,
   ROLE_QM_FROM_S  = 2,
   ROLE_RESISTANCE = 3,
   ROLE_RBS        = 4,
   ROLE_QM_FROM_R  = 5,
   ROLE_DEAD       = 6
  };

struct SSegment
  {
   ENUM_MSNR_ROLE role;
   datetime       start_time;
   datetime       end_time;       // 0 = still active
   datetime       unfresh_since;  // 0 = still fresh
  };

struct SLevel
  {
   double   price;
   datetime formed_time;
   long     formed_index;
   bool     starts_support;
   SSegment segments[];
  };

SLevel g_levels[];

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Freshness");
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

//--- 1) detect base levels (same engine as Indicators 1-2)
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

//--- 2) walk forward: track touches (freshness) + breaks (role flips)
   int cnt=ArraySize(g_levels);
   for(int k=0;k<cnt;k++)
      AnalyzeLevel(g_levels[k],time,high,low,close,rates_total);

//--- 3) draw
   DrawLevels(time[0]+PeriodSeconds(PERIOD_CURRENT)*100);
   return(rates_total);
  }

//+------------------------------------------------------------------+
//|                                                                  |
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
//| freshness + role flip analysis for one level                     |
//+------------------------------------------------------------------+
void AnalyzeLevel(SLevel &lv,const datetime &time[],const double &high[],
                  const double &low[],const double &close[],int rates_total)
  {
   ENUM_MSNR_ROLE role = lv.starts_support ? ROLE_SUPPORT : ROLE_RESISTANCE;
   PushSegment(lv,role,lv.formed_time);

   double tol=InpTouchTolerancePoints*_Point;

   for(int i=(int)(rates_total-1-lv.formed_index)-1; i>=1; i--)
     {
      double c=close[i];
      int last=ArraySize(lv.segments)-1;

      //--- closed through? -> role flip, NEW segment is fresh again
      bool broke=false;
      switch(role)
        {
         case ROLE_SUPPORT:    broke=(c<lv.price); if(broke) role=ROLE_SBR;       break;
         case ROLE_SBR:        broke=(c>lv.price); if(broke) role=ROLE_QM_FROM_S; break;
         case ROLE_QM_FROM_S:  broke=(c<lv.price); if(broke) role=ROLE_DEAD;      break;
         case ROLE_RESISTANCE: broke=(c>lv.price); if(broke) role=ROLE_RBS;       break;
         case ROLE_RBS:        broke=(c<lv.price); if(broke) role=ROLE_QM_FROM_R; break;
         case ROLE_QM_FROM_R:  broke=(c>lv.price); if(broke) role=ROLE_DEAD;      break;
         default: break;
        }

      if(broke)
        {
         lv.segments[last].end_time=time[i];
         PushSegment(lv,role,time[i]);   // fresh again in new role
         if(role==ROLE_DEAD) break;
         continue;
        }

      //--- not broken: did this candle TOUCH the level? (wick counts)
      bool touched=(high[i]>=lv.price-tol && low[i]<=lv.price+tol);
      if(touched && lv.segments[last].unfresh_since==0 && role!=ROLE_DEAD)
         lv.segments[last].unfresh_since=time[i];   // first touch -> unfresh
     }
  }

void PushSegment(SLevel &lv,ENUM_MSNR_ROLE role,datetime start)
  {
   int n=ArraySize(lv.segments);
   ArrayResize(lv.segments,n+1);
   lv.segments[n].role=role;
   lv.segments[n].start_time=start;
   lv.segments[n].end_time=0;
   lv.segments[n].unfresh_since=0;
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

void DrawSegment(const string name,double price,datetime t1,datetime t2,
                 color clr,bool fresh,ENUM_MSNR_ROLE role)
  {
   if(t2<=t1) return;
   ObjectCreate(0,name,OBJ_TREND,0,t1,price,t2,price);
   ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,fresh?InpLineWidth:1);
   ObjectSetInteger(0,name,OBJPROP_STYLE,fresh?STYLE_SOLID:STYLE_DASH);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,true);
   ObjectSetString(0,name,OBJPROP_TOOLTIP,
      StringFormat("MSNR %s @ %s [%s] | %s -> %s",
         RoleTag(role),DoubleToString(price,_Digits),
         fresh?"FRESH":"UNFRESH",TimeToString(t1),TimeToString(t2)));
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
      if(lv.segments[scount-1].role==ROLE_DEAD && !InpShowDead) continue;

      string base=InpPrefix+TimeToString(lv.formed_time,TIME_DATE)+"_"+DoubleToString(lv.price,_Digits);

      for(int s=0;s<scount;s++)
        {
         ENUM_MSNR_ROLE role=lv.segments[s].role;
         color  clr=RoleColor(role);
         datetime seg_start=lv.segments[s].start_time;
         datetime seg_end  =lv.segments[s].end_time;
         if(seg_end==0) seg_end=future_time;
         datetime unfr=lv.segments[s].unfresh_since;

         //--- fresh portion: [seg_start, unfr or seg_end]
         datetime fresh_end=(unfr>0 && unfr<seg_end) ? unfr : seg_end;
         DrawSegment(base+"_s"+IntegerToString(s)+"f",lv.price,seg_start,fresh_end,clr,true,role);

         //--- unfresh portion: [unfr, seg_end]
         if(unfr>0 && unfr<seg_end)
            DrawSegment(base+"_s"+IntegerToString(s)+"u",lv.price,unfr,seg_end,clr,false,role);

         //--- label at segment start
         if(InpShowLabels)
           {
            bool is_fresh_now=(unfr==0 || unfr>=seg_end);
            string lname=base+"_s"+IntegerToString(s)+"_lbl";
            ObjectCreate(0,lname,OBJ_TEXT,0,seg_start,lv.price);
            ObjectSetString(0,lname,OBJPROP_TEXT,
               RoleTag(role)+(is_fresh_now?" (F)":" (U)"));
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

void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
