//+------------------------------------------------------------------+
//|                                            MSNR_QM_Taxonomy.mq5  |
//|                         Advanced MSNR - Indicator 6              |
//|         QM taxonomy: abQM / iabQM / ftQM / stQM                  |
//+------------------------------------------------------------------+
//| Rules (Video 3 + Video 1):                                        |
//|  Base levels: 2-candle pivots, line at CLOSE of first candle      |
//|  (same engine as Indicators 1-2).                                |
//|                                                                   |
//|  Role lifecycle (close-through): S->SBR->QM->DEAD, R->RBS->QM->   |
//|  DEAD. Only the QM segment is drawn by this indicator.            |
//|                                                                   |
//|  Apex engine (same as Indicator 5, closes only):                  |
//|   AR/AS  = external swing that caused a BOS (breakout).           |
//|   iABR/iABS = internal swing that caused a BOS of an Apex.        |
//|                                                                   |
//|  Taxonomy per QM:                                                 |
//|   abQM : QM price matches a prior Apex (AR/AS) level.             |
//|   iabQM: QM price matches a prior iAB (iABR/iABS) level, but      |
//|          not an Apex level.                                       |
//|   ftQM : regular QM, first time this price zone becomes a QM.     |
//|   stQM : regular QM, this price zone already produced a QM        |
//|          before (second-time QM, less reliable).                  |
//|  Priority for the primary label: abQM > iabQM > ftQM > stQM.      |
//|  Full detail (origin + FT/ST) is kept in the tooltip, so the      |
//|  "AB QM + FT QM" combination from Video 6 is still visible.       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars       = 500;               // Lookback bars (S/R + QM detection)
input int    InpApexPivotStrength  = 3;                 // Apex pivot strength (bars each side, closes)
input int    InpApexLookbackBars   = 2000;              // Apex lookback bars
input double InpMatchTolerancePips   = 2.0;             // Apex<->QM match tolerance (pips)
input double InpZoneTolerancePips    = 2.0;             // FT/ST same-zone tolerance (pips)
input bool   InpHTFOnly              = true;            // Warn below D1 (Apex is D1/W1/MN only)
input int    InpMaxLevels          = 40;                // Max QMs drawn (most recent)
input bool   InpShowLabels         = true;              // Show taxonomy labels
input bool   InpShowDead           = false;             // Keep drawing dead (broken QM) levels
input color  InpAbQMColor          = clrMediumPurple;   // abQM (Apex origin)
input color  InpIabQMColor         = clrDodgerBlue;     // iabQM (iAB origin)
input color  InpFtQMColor          = clrDarkOrange;     // ftQM (first-time regular)
input color  InpStQMColor          = clrGray;           // stQM (second-time regular)
input color  InpDeadColor          = clrGray;           // Dead QM color
input int    InpLineWidth          = 2;                 // QM segment width
input string InpPrefix             = "MSNR_QM_";        // Object name prefix

//--- base S/R roles (same as Indicator 2)
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
   datetime       end_time;   // 0 = still active
  };

struct SLevel
  {
   double   price;
   datetime formed_time;
   long     formed_index;
   bool     starts_support;
   SSegment segments[];
  };

struct SQM
  {
   double   price;
   datetime base_formed;   // when the parent S/R was confirmed
   datetime qm_start;      // when SBR->QM / RBS->QM happened
   datetime qm_end;        // 0 = still active
   bool     dead;          // QM later broke to DEAD
   bool     from_support;  // true: S->SBR->QM, false: R->RBS->QM
   bool     is_ab;
   bool     is_iab;
   bool     is_ft;
   string   primary;       // "abQM" / "iABQM" / "ftQM" / "stQM"
   string   origin_tag;    // matched "AR"/"AS"/"iABR"/"iABS" or ""
   double   origin_price;
   datetime origin_time;
   int      prior_count;   // earlier QMs in same zone
  };

SLevel g_levels[];
SQM    g_qms[];

//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR QM Taxonomy (ab/iab/ft/st)");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { Comment(""); DeleteAllObjects(); }

bool IsBull(const double &o[],const double &c[],int i) { return(c[i]>o[i]); }
bool IsBear(const double &o[],const double &c[],int i) { return(c[i]<o[i]); }

bool PriceNear(double a,double b,double tol) { return(MathAbs(a-b)<=tol); }

//--- 1 pip = 10 points on 5/3-digit brokers, else 1 point
double PipsToPrice(double pips)
  {
   double factor=(_Digits==3 || _Digits==5) ? 10.0 : 1.0;
   return(pips*factor*_Point);
  }

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

//--- Video 3: Apex/iAB (and thus abQM/iabQM taxonomy) is HTF-only
   if(InpHTFOnly && Period()<PERIOD_D1)
     {
      Comment("MSNR QM Taxonomy: attach to D1 / W1 / MN (Apex mapping is HTF-only).");
      DeleteAllObjects();
      return(rates_total);
     }
   Comment("");

   static datetime last_bar_time=0;
   bool new_bar=(time[0]!=last_bar_time);
   if(prev_calculated!=0 && !new_bar) return(rates_total);
   last_bar_time=time[0];

//--- 1) base S/R levels (same engine as Indicators 1-2), chronological old->new
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

//--- 2) role segments -> extract QM windows
   int cnt=ArraySize(g_levels);
   for(int k=0;k<cnt;k++)
      BuildSegments(g_levels[k],time,close,rates_total);
   ExtractQMs();

//--- 3) Apex / iAB levels on this chart (same engine as Indicator 5)
   double   apxPrice[];
   datetime apxTime[];      // pivot formation time
   datetime apxConf[];      // BOS confirmation time (level becomes tradeable)
   string   apxTag[];
   BuildApex(close,time,rates_total,apxPrice,apxTime,apxConf,apxTag);

//--- 4) classify each QM by origin + FT/ST
   ClassifyQMs(apxPrice,apxTime,apxConf,apxTag);

//--- 5) draw
   DrawQMs(time[0]+PeriodSeconds(PERIOD_CURRENT)*100);
   return(rates_total);
  }

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

void PushSegment(SLevel &lv,ENUM_MSNR_ROLE role,datetime start)
  {
   int n=ArraySize(lv.segments);
   ArrayResize(lv.segments,n+1);
   lv.segments[n].role=role;
   lv.segments[n].start_time=start;
   lv.segments[n].end_time=0;
  }

void BuildSegments(SLevel &lv,const datetime &time[],const double &close[],int rates_total)
  {
   ENUM_MSNR_ROLE role = lv.starts_support ? ROLE_SUPPORT : ROLE_RESISTANCE;
   PushSegment(lv,role,lv.formed_time);

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
         int last=ArraySize(lv.segments)-1;
         lv.segments[last].end_time=time[i];
         PushSegment(lv,role,time[i]);
         if(role==ROLE_DEAD) break;
        }
     }
  }

//--- keep only the QM segment of each level that reached QM
void ExtractQMs()
  {
   ArrayResize(g_qms,0);
   int cnt=ArraySize(g_levels);
   for(int k=0;k<cnt;k++)
     {
      int sc=ArraySize(g_levels[k].segments);
      for(int s=0;s<sc;s++)
        {
         ENUM_MSNR_ROLE r=g_levels[k].segments[s].role;
         if(r!=ROLE_QM_FROM_S && r!=ROLE_QM_FROM_R) continue;

         int n=ArraySize(g_qms);
         ArrayResize(g_qms,n+1);
         g_qms[n].price       =g_levels[k].price;
         g_qms[n].base_formed =g_levels[k].formed_time;
         g_qms[n].qm_start    =g_levels[k].segments[s].start_time;
         g_qms[n].qm_end      =g_levels[k].segments[s].end_time;
         g_qms[n].dead        =(s+1<sc && g_levels[k].segments[s+1].role==ROLE_DEAD);
         // if QM is the last segment and end_time==0 it is still active
         g_qms[n].from_support=(r==ROLE_QM_FROM_S);
         g_qms[n].is_ab=false; g_qms[n].is_iab=false; g_qms[n].is_ft=true;
         g_qms[n].primary="ftQM";
         g_qms[n].origin_tag=""; g_qms[n].origin_price=0; g_qms[n].origin_time=0;
         g_qms[n].prior_count=0;
        }
     }
  }

//+------------------------------------------------------------------+
//| Apex / iAB builder (mirrors MSNR_Apex.mq5, fills flat arrays)    |
//+------------------------------------------------------------------+
void BuildApex(const double &close[],const datetime &time[],int rates_total,
               double &outPrice[],datetime &outTime[],datetime &outConf[],string &outTag[])
  {
   ArrayResize(outPrice,0); ArrayResize(outTime,0); ArrayResize(outConf,0); ArrayResize(outTag,0);
   if(rates_total < 2*InpApexPivotStrength+3) return;

   int maxScan=MathMin(InpApexLookbackBars,rates_total-InpApexPivotStrength-1);
   if(maxScan<InpApexPivotStrength+1) return;

   int    pType[];
   double pPrice[];
   int    pIdx[];
   datetime pTime[];

   for(int i=maxScan; i>=InpApexPivotStrength; i--)
     {
      bool isHigh=true,isLow=true;
      for(int k=1;k<=InpApexPivotStrength;k++)
        {
         if(close[i]<=close[i+k] || close[i]<=close[i-k]) isHigh=false;
         if(close[i]>=close[i+k] || close[i]>=close[i-k]) isLow=false;
         if(!isHigh && !isLow) break;
        }
      if(!isHigh && !isLow) continue;
      int n=ArraySize(pType);
      ArrayResize(pType,n+1); ArrayResize(pPrice,n+1);
      ArrayResize(pIdx,n+1);  ArrayResize(pTime,n+1);
      pType[n]=isHigh?1:-1; pPrice[n]=close[i]; pIdx[n]=i; pTime[n]=time[i];
     }

   int m=ArraySize(pType);
   for(int a=1;a<m;a++)
     {
      if(pType[a]==pType[a-1])
        {
         bool keepA=(pType[a]==1) ? (pPrice[a]>=pPrice[a-1]) : (pPrice[a]<=pPrice[a-1]);
         if(keepA) { pPrice[a-1]=pPrice[a]; pIdx[a-1]=pIdx[a]; pTime[a-1]=pTime[a]; }
         for(int b=a+1;b<m;b++)
           { pType[b-1]=pType[b]; pPrice[b-1]=pPrice[b]; pIdx[b-1]=pIdx[b]; pTime[b-1]=pTime[b]; }
         m--; a--;
        }
     }
   ArrayResize(pType,m); ArrayResize(pPrice,m); ArrayResize(pIdx,m); ArrayResize(pTime,m);

   int trend=0;
   bool hasPH=false, hasPL=false;
   double phPrice=0, plPrice=0;
   datetime phTime=0, plTime=0;
   double legOriginLow=0, legOriginHigh=0;
   datetime legOriginLowTime=0, legOriginHighTime=0;
   bool hasOriginLow=false, hasOriginHigh=false;
   int pNext=0;

   for(int j=maxScan; j>=1; j--)
     {
      while(pNext<m && pIdx[pNext]-InpApexPivotStrength>=j)
        {
         if(pType[pNext]==1)
           { hasPH=true; phPrice=pPrice[pNext]; phTime=pTime[pNext];
             hasOriginHigh=true; legOriginHigh=pPrice[pNext]; legOriginHighTime=pTime[pNext]; }
         else
           { hasPL=true; plPrice=pPrice[pNext]; plTime=pTime[pNext];
             hasOriginLow=true; legOriginLow=pPrice[pNext]; legOriginLowTime=pTime[pNext]; }
         pNext++;
        }
       if(hasPH && close[j]>phPrice)
         {
          AppendApex(outPrice,outTime,outConf,outTag,phPrice,phTime,time[j],"AR");
          if(hasOriginLow)
             AppendApex(outPrice,outTime,outConf,outTag,legOriginLow,legOriginLowTime,time[j],(trend==1)?"iABS":"AS");
          trend=1; hasPH=false; hasOriginLow=false;
         }
       else if(hasPL && close[j]<plPrice)
         {
          AppendApex(outPrice,outTime,outConf,outTag,plPrice,plTime,time[j],"AS");
          if(hasOriginHigh)
             AppendApex(outPrice,outTime,outConf,outTag,legOriginHigh,legOriginHighTime,time[j],(trend==-1)?"iABR":"AR");
          trend=-1; hasPL=false; hasOriginHigh=false;
         }
     }
  }

void AppendApex(double &pr[],datetime &tm[],datetime &cf[],string &tg[],
                double price,datetime t,datetime conf,const string tag)
  {
   int n=ArraySize(pr);
   for(int i=0;i<n;i++)
      if(tm[i]==t && tg[i]==tag) return;
   ArrayResize(pr,n+1); ArrayResize(tm,n+1); ArrayResize(cf,n+1); ArrayResize(tg,n+1);
   pr[n]=price; tm[n]=t; cf[n]=conf; tg[n]=tag;
  }

//+------------------------------------------------------------------+
void ClassifyQMs(const double &apxPrice[],const datetime &apxTime[],
                 const datetime &apxConf[],const string &apxTag[])
  {
   double matchTol=PipsToPrice(InpMatchTolerancePips);
   double zoneTol =PipsToPrice(InpZoneTolerancePips);
   int qn=ArraySize(g_qms);
   int an=ArraySize(apxPrice);

//--- FIX: order QMs by BIRTH time (qm_start), not base-level formation order,
//--- so FT/ST counting is chronological. Build sorted index map.
   int order[];
   ArrayResize(order,qn);
   for(int i=0;i<qn;i++) order[i]=i;
   for(int a=0;a<qn;a++)
      for(int b=a+1;b<qn;b++)
         if(g_qms[order[b]].qm_start < g_qms[order[a]].qm_start)
           { int tmp=order[a]; order[a]=order[b]; order[b]=tmp; }

   for(int oi=0; oi<qn; oi++)
     {
      int q=order[oi];
      //--- origin match: only Apex/iAB levels CONFIRMED (BOS) at/before QM birth
      bool foundAB=false, foundIAB=false;
      string otag=""; double oprice=0; datetime otime=0;
      for(int a=0;a<an;a++)
        {
         if(apxConf[a]>g_qms[q].qm_start) continue;   // FIX: use confirmation time
         if(!PriceNear(g_qms[q].price,apxPrice[a],matchTol)) continue;
         if(apxTag[a]=="AR" || apxTag[a]=="AS")
           { foundAB=true; otag=apxTag[a]; oprice=apxPrice[a]; otime=apxTime[a]; break; }
         if(!foundIAB && (apxTag[a]=="iABR" || apxTag[a]=="iABS"))
           { foundIAB=true; otag=apxTag[a]; oprice=apxPrice[a]; otime=apxTime[a]; }
        }
      if(foundAB)       { g_qms[q].is_ab=true;  g_qms[q].is_iab=false; }
      else if(foundIAB) { g_qms[q].is_ab=false; g_qms[q].is_iab=true;  }

      g_qms[q].origin_tag=otag; g_qms[q].origin_price=oprice; g_qms[q].origin_time=otime;

      //--- FT/ST: count QMs born EARLIER in the same price zone (chronological)
      int prior=0;
      for(int pj=0;pj<oi;pj++)
        {
         int p=order[pj];
         if(PriceNear(g_qms[q].price,g_qms[p].price,zoneTol)) prior++;
        }
      g_qms[q].prior_count=prior;
      g_qms[q].is_ft=(prior==0);

      if(g_qms[q].is_ab)            g_qms[q].primary="abQM";
      else if(g_qms[q].is_iab)      g_qms[q].primary="iabQM";
      else if(g_qms[q].is_ft)       g_qms[q].primary="ftQM";
      else                          g_qms[q].primary="stQM";
     }
  }

//+------------------------------------------------------------------+
color QmColor(const SQM &q)
  {
   if(q.dead) return InpDeadColor;
   if(q.primary=="abQM")  return InpAbQMColor;
   if(q.primary=="iabQM") return InpIabQMColor;
   if(q.primary=="ftQM")  return InpFtQMColor;
   return InpStQMColor;
  }

void DrawQMs(datetime future_time)
  {
   DeleteAllObjects();
   int qn=ArraySize(g_qms);
   int drawn=0;

   for(int q=qn-1; q>=0 && drawn<InpMaxLevels; q--)
     {
      if(g_qms[q].dead && !InpShowDead) continue;

      datetime t1=g_qms[q].qm_start;
      datetime t2=g_qms[q].qm_end;
      if(t2==0) t2=future_time;
      if(t2<=t1) continue;

      color clr=QmColor(g_qms[q]);
      string nm=InpPrefix+g_qms[q].primary+"_"+
                TimeToString(t1,TIME_DATE|TIME_MINUTES)+"_"+
                DoubleToString(g_qms[q].price,_Digits);

      ObjectCreate(0,nm,OBJ_TREND,0,t1,g_qms[q].price,t2,g_qms[q].price);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,g_qms[q].dead?1:InpLineWidth);
      ObjectSetInteger(0,nm,OBJPROP_STYLE,g_qms[q].dead?STYLE_DOT:STYLE_SOLID);
      ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,nm,OBJPROP_BACK,true);
      ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);

      string ftTag=g_qms[q].is_ft?"FT":"ST";
      string orgInfo=(g_qms[q].origin_tag=="" ? "regular S/R origin" :
         StringFormat("origin %s @ %s (%s)",g_qms[q].origin_tag,
            DoubleToString(g_qms[q].origin_price,_Digits),
            TimeToString(g_qms[q].origin_time)));
      string dirInfo=g_qms[q].from_support?"S->SBR->QM":"R->RBS->QM";
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("MSNR %s (%s) @ %s | %s | %s | base %s -> QM %s%s",
            g_qms[q].primary,ftTag,
            DoubleToString(g_qms[q].price,_Digits),
            dirInfo,orgInfo,
            TimeToString(g_qms[q].base_formed),
            TimeToString(g_qms[q].qm_start),
            g_qms[q].dead?(" | dead "+TimeToString(g_qms[q].qm_end)):""));

      if(InpShowLabels)
        {
         string lname=nm+"_lbl";
         ObjectCreate(0,lname,OBJ_TEXT,0,t1,g_qms[q].price);
         ObjectSetString(0,lname,OBJPROP_TEXT,
            StringFormat("%s(%s) %s",g_qms[q].primary,ftTag,
               DoubleToString(g_qms[q].price,_Digits)));
         ObjectSetInteger(0,lname,OBJPROP_COLOR,clr);
         ObjectSetInteger(0,lname,OBJPROP_FONTSIZE,8);
         ObjectSetInteger(0,lname,OBJPROP_ANCHOR,
            g_qms[q].from_support?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER);
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
