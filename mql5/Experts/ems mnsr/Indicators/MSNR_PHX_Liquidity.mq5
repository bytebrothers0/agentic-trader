//+------------------------------------------------------------------+
//|                                            MSNR_PHX_Liquidity.mq5 |
//|              PHX Indicator 1: Liquidity pools + Target Sweeps      |
//+------------------------------------------------------------------+
//| Rules (Phoenix Parts 1, 3 + PDF TS/BSL/SSL):                       |
//|                                                                    |
//|  Pools:                                                            |
//|   (a) fractal swing highs/lows (E3 pivot parity) = BSL / SSL;      |
//|   (b) EQH/EQL: >= 2 same-side extremes within InpEQHPips = strong  |
//|       pool at the extreme (stops stack above/below);               |
//|   (c) session levels: PDH/PDL, PWH/PWL, Asian-range H/L.           |
//|                                                                    |
//|  Target Sweep per pool, closed bars only:                          |
//|   - wick rejection: high > pool+pierce && close < pool (BSL,       |
//|     E2 shape; mirror SSL), wick-tip stored for PHX5/SL use;        |
//|   - rapid reversal: marginal close beyond (<= InpOverPips) then    |
//|     opposite close-back within 2 bars (Part 3 §2.1).               |
//|  Sustained breakouts (closes holding beyond) are never TS.         |
//|                                                                    |
//|  Lifecycle (E3 parity): swing-pool line runs formation -> first    |
//|  TS, or -> now while un-swept; session lines always span their     |
//|  session -> now and mark every TS (capped).                        |
//|                                                                    |
//|  Rendering: pure marker - EQ thick amber, singles thin gray,       |
//|  session dashed steel-blue; swept lines dotted. `TS` labels at      |
//|  sweep bars. Most-recent caps honored. No rays.                    |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars (swings)
input int    InpPivotStrength = 2;                // Pivot strength (bars each side)
input double InpEQHPips       = 2.5;               // EQ cluster tolerance (pips)
input double InpMinPiercePips = 0.5;               // Min wick pierce for TS (pips, E2 parity)
input double InpOverPips      = 2.0;               // Max marginal close-beyond for reversal TS (pips)
input int    InpMaxPools      = 30;                // Max single pools drawn (most recent)
input int    InpMaxEQ         = 20;                // Max EQ pools drawn (most recent)
input int    InpMaxTSLabels   = 5;                 // Max TS labels stored per pool
input bool   InpShowSession   = true;              // Show session levels (PDH/L, PWH/L, Asian)
input bool   InpShowEQ        = true;              // Show EQH/EQL pools
input bool   InpShowSingles   = true;              // Show single-swing pools
input bool   InpShowTS        = true;              // Show TS labels
input bool   InpShowLabels    = true;              // Show pool tags (EQ/session)
input int    InpAsianStartHour = 0;                // Asian session start (server hour)
input int    InpAsianEndHour   = 7;                // Asian session end (server hour)
input color  InpEQColor       = clrOrange;         // EQ pool line (amber)
input color  InpPoolColor     = clrGray;           // Single-swing pool line
input color  InpSweptColor    = clrGray;           // Swept swing-pool color (dotted)
input color  InpSessColor     = clrSteelBlue;      // Session level line
input color  InpTSColor       = clrOrange;         // TS label
input string InpPrefix        = "MSNR_PR_";        // Object name prefix (PR = pools)

struct SPivot
   {
    datetime time;
    double   price;
    bool     is_high;
    int      idx;        // series index
   };

struct SPool
   {
    double   price;
    datetime t1;         // formation (pool bar / session start) time
    int      idx;        // scan start series index (swing: formation bar)
    datetime t2;         // first TS bar, 0 = un-swept (swing pools terminate here)
    bool     isBSL;      // true = above (buy-side), false = below (sell-side)
    int      kind;       // 0 single, 1 EQ, 2 session
    string   tag;        // "EQH x3", "PDH", ...
    int      members;    // EQ cluster size (1 = single)
    datetime tsT[5];
    double   tsTip[5];
    int      tsN;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR Pools + TS");
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

    if(rates_total<2*InpPivotStrength+3) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double pierce=InpMinPiercePips*pip;
    double over  =InpOverPips*pip;
    double eqTol =InpEQHPips*pip;

    SPivot piv[];
    FindPivots(high,low,time,rates_total,piv);

    SPool pools[];
    BuildSwingPools(piv,eqTol,pools);

    //--- TS scan per swing pool (oldest-first termination, E3 parity)
    for(int k=0;k<ArraySize(pools);k++)
       ScanTS(pools[k],high,low,close,time,rates_total,pierce,over,true);

    //--- session pools (always span session -> now, mark every TS)
    if(InpShowSession)
       AddSessionPools(pools,high,low,close,time,rates_total,pierce,over);

    DrawPools(pools,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- fractal pivots on wick highs/lows, alternating, oldest -> newest (E3 parity)
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
       piv[n].time=t[i];
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

//--- greedy same-side clusters within eqTol; >=2 members = EQ pool
void BuildSwingPools(const SPivot &piv[],double eqTol,SPool &pools[])
   {
    ArrayResize(pools,0);
    int m=ArraySize(piv);
    bool used[];
    ArrayResize(used,m);
    ArrayInitialize(used,false);
    for(int p=0;p<m;p++)
      {
       if(used[p]) continue;
       used[p]=true;
       double extreme=piv[p].price;
       datetime newestT=piv[p].time;
       int newestIdx=piv[p].idx;
       int cnt=1;
       for(int q=p+1;q<m;q++)
         {
          if(used[q] || piv[q].is_high!=piv[p].is_high) continue;
          if(MathAbs(piv[q].price-extreme)<=eqTol)
            {
             used[q]=true; cnt++;
             if(piv[p].is_high) extreme=MathMax(extreme,piv[q].price);
             else                extreme=MathMin(extreme,piv[q].price);
             if(piv[q].time>newestT) { newestT=piv[q].time; newestIdx=piv[q].idx; }
            }
         }
       SPool x;
       x.price=extreme; x.t1=newestT; x.idx=newestIdx; x.t2=0;
       x.isBSL=piv[p].is_high;
       x.kind=(cnt>=2?1:0); x.members=cnt;
       x.tag=(cnt>=2?StringFormat("EQ%s x%d",(x.isBSL?"H":"L"),cnt):"");
       x.tsN=0;
       int n=ArraySize(pools);
       ArrayResize(pools,n+1); pools[n]=x;
      }
   }

void AddTS(SPool &p,datetime tt,double tip)
   {
    if(p.tsN>=5 || p.tsN>=InpMaxTSLabels) return;
    p.tsT[p.tsN]=tt; p.tsTip[p.tsN]=tip; p.tsN++;
   }

//--- record TS events; stopAtFirst=true terminates (swing pools, E3 parity)
void ScanTS(SPool &p,const double &h[],const double &l[],const double &c[],
            const datetime &t[],int rates_total,double pierce,double over,
            bool stopAtFirst)
   {
    p.tsN=0;
    int start=(p.kind==2?MathMin(InpLookbackBars,rates_total-1):p.idx-1);
    int tsCap=MathMin(InpMaxTSLabels,5);
     for(int j=start;j>=1;j--)
       {
        if(p.tsN>=tsCap) break;
        if(p.kind==2 && t[j]<p.t1) break;   // session levels: TS only from session start
        if(p.isBSL)
         {
          if(h[j]>p.price+pierce && c[j]<p.price)
            { AddTS(p,t[j],h[j]); if(stopAtFirst) break; continue; }
          if(j>=3 && c[j]>p.price && c[j]<=p.price+over)
            {
             for(int k2=j-1;k2>=j-2;k2--)
               {
                if(c[k2]<p.price)
                  { AddTS(p,t[k2],MathMax(h[j],h[k2])); j=k2; break; }
               }
             if(stopAtFirst && p.tsN>0) break;
            }
         }
       else
         {
          if(l[j]<p.price-pierce && c[j]>p.price)
            { AddTS(p,t[j],l[j]); if(stopAtFirst) break; continue; }
          if(j>=3 && c[j]<p.price && c[j]>=p.price-over)
            {
             for(int k2=j-1;k2>=j-2;k2--)
               {
                if(c[k2]>p.price)
                  { AddTS(p,t[k2],MathMin(l[j],l[k2])); j=k2; break; }
               }
             if(stopAtFirst && p.tsN>0) break;
            }
         }
      }
    if(p.kind!=2 && p.tsN>0) p.t2=p.tsT[0];   // swing pools terminate at first TS
   }

bool InWindow(int hour)
   {
    if(InpAsianStartHour<=InpAsianEndHour)
       return(hour>=InpAsianStartHour && hour<InpAsianEndHour);
    return(hour>=InpAsianStartHour || hour<InpAsianEndHour);
   }

void AddOneSess(SPool &pools[],string tag,double price,bool isBSL,datetime start,
                const double &h[],const double &l[],const double &c[],
                const datetime &t[],int rates_total,double pierce,double over)
   {
    if(price<=0 || start<=0) return;
    SPool x;
    x.price=price; x.t1=start; x.idx=0; x.t2=0;
    x.isBSL=isBSL; x.kind=2; x.tag=tag; x.members=1;
    x.tsN=0;
    ScanTS(x,h,l,c,t,rates_total,pierce,over,false);
    int n=ArraySize(pools);
    ArrayResize(pools,n+1); pools[n]=x;
   }

//--- PDH/PDL, PWH/PWL, Asian H/L
void AddSessionPools(SPool &pools[],const double &h[],const double &l[],
                     const double &c[],const datetime &t[],int rates_total,
                     double pierce,double over)
   {
    double hi[], lo[];
    datetime dt[];
    if(CopyHigh(_Symbol,PERIOD_D1,1,1,hi)==1 &&
       CopyLow(_Symbol,PERIOD_D1,1,1,lo)==1 &&
       CopyTime(_Symbol,PERIOD_D1,0,1,dt)==1)
      {
       AddOneSess(pools,"PDH",hi[0],true,dt[0],h,l,c,t,rates_total,pierce,over);
       AddOneSess(pools,"PDL",lo[0],false,dt[0],h,l,c,t,rates_total,pierce,over);
      }
    if(CopyHigh(_Symbol,PERIOD_W1,1,1,hi)==1 &&
       CopyLow(_Symbol,PERIOD_W1,1,1,lo)==1 &&
       CopyTime(_Symbol,PERIOD_W1,0,1,dt)==1)
      {
       AddOneSess(pools,"PWH",hi[0],true,dt[0],h,l,c,t,rates_total,pierce,over);
       AddOneSess(pools,"PWL",lo[0],false,dt[0],h,l,c,t,rates_total,pierce,over);
      }
    //--- Asian range on the most recent in-window date (intraday charts only)
    if(PeriodSeconds(PERIOD_CURRENT)<=3600)
      {
       int y=0, mo=0, d=0;
       bool found=false;
       int cap=MathMin(rates_total,5000);
       for(int i=1;i<cap;i++)
         {
          MqlDateTime s; TimeToStruct(t[i],s);
          if(s.day_of_week==0 || s.day_of_week==6) continue;
          if(InWindow(s.hour)) { y=s.year; mo=s.mon; d=s.day; found=true; break; }
         }
       if(found)
         {
          double ahi=0, alo=0;
          bool have=false;
          for(int i=1;i<cap;i++)
            {
             MqlDateTime s; TimeToStruct(t[i],s);
             if(s.year!=y || s.mon!=mo || s.day!=d) continue;
             if(!InWindow(s.hour)) continue;
             if(!have) { ahi=h[i]; alo=l[i]; have=true; }
             else { if(h[i]>ahi) ahi=h[i]; if(l[i]<alo) alo=l[i]; }
            }
          if(have)
            {
             datetime sStart=StringToTime(StringFormat("%04d.%02d.%02d %02d:00",
                             y,mo,d,InpAsianStartHour));
             AddOneSess(pools,"ASIA-H",ahi,true,sStart,h,l,c,t,rates_total,pierce,over);
             AddOneSess(pools,"ASIA-L",alo,false,sStart,h,l,c,t,rates_total,pierce,over);
            }
         }
      }
   }

void DrawPools(const SPool &pools[],datetime now)
   {
    DeleteAllObjects();
    //--- session first (always), then capped EQ, then capped singles (all newest-first)
    for(int k=0;k<ArraySize(pools);k++)
      {
       if(pools[k].kind!=2) continue;
       DrawOne(pools[k],now,true);
      }
    int eqN=0;
    for(int k=ArraySize(pools)-1;k>=0;k--)
      {
       if(pools[k].kind!=1 || !InpShowEQ) continue;
       if(eqN>=InpMaxEQ) break;
       DrawOne(pools[k],now,true); eqN++;
      }
    int sN=0;
    for(int k=ArraySize(pools)-1;k>=0;k--)
      {
       if(pools[k].kind!=0 || !InpShowSingles) continue;
       if(sN>=InpMaxPools) break;
       DrawOne(pools[k],now,false); sN++;
      }
   }

void DrawOne(const SPool &p,datetime now,bool withLabel)
   {
    datetime t2=(p.kind==2?now:(p.t2==0?now:p.t2));
    if(t2<=p.t1) return;
    string nm=InpPrefix+(p.kind==2?"sess_":(p.kind==1?(p.isBSL?"eqh_":"eql_"):(p.isBSL?"bsl_":"ssl_")))+
              (p.kind==2?p.tag:TimeToString(p.t1,TIME_DATE|TIME_MINUTES))+
              (p.kind==2?"":"_"+DoubleToString(p.price,_Digits));
    color clr=(p.kind==2?InpSessColor:(p.kind==1?InpEQColor:InpPoolColor));
    if(p.tsN>0 && p.kind!=2) clr=InpSweptColor;

    ObjectCreate(0,nm,OBJ_TREND,0,p.t1,p.price,t2,p.price);
    ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
    ObjectSetInteger(0,nm,OBJPROP_STYLE,(p.kind==2?STYLE_DASH:(p.tsN>0?STYLE_DOT:STYLE_SOLID)));
    ObjectSetInteger(0,nm,OBJPROP_WIDTH,(p.kind==1?2:1));
    ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
    ObjectSetInteger(0,nm,OBJPROP_BACK,true);
    ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
    ObjectSetString(0,nm,OBJPROP_TOOLTIP,
       StringFormat("%s %s pool %s | formed %s -> %s%s",
          p.tag==""?(p.isBSL?"BSL":"SSL"):p.tag,
          p.kind==2?"session":(p.kind==1?StringFormat("EQ x%d",p.members):"single"),
          DoubleToString(p.price,_Digits),TimeToString(p.t1),TimeToString(t2),
          p.tsN>0?StringFormat(" | TS x%d, last tip %s",p.tsN,DoubleToString(p.tsTip[p.tsN-1],_Digits)):" | UN-SWEPT"));

    if(withLabel && InpShowLabels && p.tag!="")
      {
       string ln=nm+"_lbl";
       ObjectCreate(0,ln,OBJ_TEXT,0,p.t1,p.price);
       ObjectSetString(0,ln,OBJPROP_TEXT,p.tag);
       ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
       ObjectSetInteger(0,ln,OBJPROP_ANCHOR,(p.isBSL?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
       ObjectSetInteger(0,ln,OBJPROP_BACK,true);
       ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
      }

    if(InpShowTS)
      {
       for(int q=0;q<p.tsN;q++)
         {
          string tn=nm+"_ts"+IntegerToString(q);
          ObjectCreate(0,tn,OBJ_TEXT,0,p.tsT[q],p.tsTip[q]);
          ObjectSetString(0,tn,OBJPROP_TEXT,"TS");
          ObjectSetInteger(0,tn,OBJPROP_COLOR,InpTSColor);
          ObjectSetInteger(0,tn,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,tn,OBJPROP_ANCHOR,(p.isBSL?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
          ObjectSetInteger(0,tn,OBJPROP_BACK,true);
          ObjectSetInteger(0,tn,OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
