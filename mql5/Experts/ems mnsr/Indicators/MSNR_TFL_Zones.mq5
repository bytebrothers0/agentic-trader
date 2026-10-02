//+------------------------------------------------------------------+
//|                                            MSNR_TFL_Zones.mq5    |
//|                         Advanced MSNR - Indicator 8              |
//|         FTFL / STFL / TTFL zone boxes + equilibrium + A+          |
//+------------------------------------------------------------------+
//| Rules (Videos 5-10, corrected notes in Video 10):                 |
//|                                                                   |
//|  Box geometry (time = bar slots on the box's own TF):             |
//|   S/R support (also QM-from-S): top = LEVEL price (close of       |
//|            candle1 = body), bottom = min(low1,low2) = wick tip.    |
//|            Body -> wick tip on the support side only.              |
//|   S/R resistance (also QM-from-R): mirror: bottom = LEVEL price,  |
//|            top = max(high1,high2).                                 |
//|   OCL bullish: bottom = candle2 low (wick tip), top = max(open    |
//|            of candle2, OCL level) = candle2's lower wick + body    |
//|            edge. OCL bearish: mirror (min(open2, level)..high2).   |
//|   Time (all kinds): candle1 open -> candle2 open + 2 steps, i.e.   |
//|            the box visibly covers the c1/c2/c3 slots (one step      |
//|            past candle2's close).                                  |
//|   QM: same side-geometry as its parent S/R box; freshness re-arms |
//|            at QM birth (SBR->QM / RBS->QM bar).                    |
//|                                                                   |
//|  Equilibrium: 50% midline of every box (dotted). Entry ref when   |
//|  no TTFL key level sits inside the STFL box (Video 8).            |
//|  A+ = STFL box fully inside (price) an FTFL box; TTFL fully       |
//|  inside an STFL box (Video 7). A+ boxes get an "A+" label suffix. |
//|  Fresh = level price untouched since birth (QM: since QM birth).  |
//|  Solid border = fresh, dashed = unfresh (mitigated).              |
//|                                                                   |
//|  Ladder: follow mode (default) X=chart, Y=one lower, Z=two lower, |
//|  so each tier is inspected where its candles align. Fixed mode:   |
//|  InpFixedFTFL/STFL/TTFL (default D1/H4/H1).                       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input bool   InpFollowChart        = true;               // Follow chart TF (X=chart, Y=lower, Z=2x lower)
input ENUM_TIMEFRAMES InpFixedFTFL = PERIOD_D1;          // Fixed mode: FTFL TF
input ENUM_TIMEFRAMES InpFixedSTFL = PERIOD_H4;          // Fixed mode: STFL TF
input ENUM_TIMEFRAMES InpFixedTTFL = PERIOD_H1;          // Fixed mode: TTFL TF
input int    InpLookbackX          = 150;               // Lookback bars FTFL tier
input int    InpLookbackY          = 300;               // Lookback bars STFL tier
input int    InpLookbackZ          = 300;               // Lookback bars TTFL tier
input int    InpMaxBoxes           = 8;                 // Max boxes drawn per tier (most recent)
input bool   InpFreshOnly          = false;             // Hide unfresh (mitigated) boxes
input bool   InpSkipEngulfingOCL   = true;              // Skip body-engulfing OCL pairs (not traded)
input bool   InpExtendUntilMitigated = true;            // Extend box right until mitigated/now
input bool   InpShowEquilibrium    = true;              // Draw 50% midlines
input bool   InpShowFTFL           = true;              // Draw FTFL tier boxes
input bool   InpShowSTFL           = true;              // Draw STFL tier boxes
input bool   InpShowTTFL           = true;              // Draw TTFL tier boxes
input bool   InpShowLabels         = true;              // Show box labels (+A+ suffix)
input bool   InpShowDashboard      = true;              // Show FTFL/STFL/TTFL panel
input color  InpSupColor           = clrDodgerBlue;     // S/R support-side box
input color  InpResColor           = clrTomato;         // S/R resistance-side box
input color  InpQMColor            = clrMediumPurple;   // QM box
input color  InpOCLBullColor       = clrSkyBlue;        // Bullish OCL box
input color  InpOCLBearColor       = clrOrange;         // Bearish OCL box
input color  InpEqColor            = clrGray;           // Equilibrium midline
input int    InpDashX              = 10;                // Dashboard X distance
input int    InpDashY              = 20;                // Dashboard Y distance
input string InpPrefix             = "MSNR_TFL_";       // Object name prefix

struct SBox
  {
   double   top;
   double   bot;
   double   lvl_price;    // key level price (freshness reference)
   datetime t1;
   datetime t2;
   datetime birth;       // level birth (QM: QM birth)
   string   kind;         // "S","R","QM","OCL"
   int      dir;          // +1 support-side, -1 resistance-side
   bool     fresh;
   bool     aplus;        // inside parent-tier box (STFL/TTFL only)
  };

//+------------------------------------------------------------------+
int OnInit()
  {
   IndicatorSetString(INDICATOR_SHORTNAME,"MSNR TFL Zones (FTFL/STFL/TTFL)");
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
   ArraySetAsSeries(time,true);
   if(rates_total<3) return(0);

   static datetime last_bar_time=0;
   static ENUM_TIMEFRAMES last_tf=PERIOD_CURRENT;
   bool new_bar=(time[0]!=last_bar_time);
   bool tf_changed=(Period()!=last_tf);
   if(prev_calculated!=0 && !new_bar && !tf_changed) return(rates_total);
   last_bar_time=time[0];
   last_tf=Period();

   DeleteAllObjects();

   ENUM_TIMEFRAMES tfF,tfS,tfT;
   if(InpFollowChart)
     { tfF=Period(); tfS=LowerTF(tfF); tfT=LowerTF(tfS); }
   else
     { tfF=InpFixedFTFL; tfS=InpFixedSTFL; tfT=InpFixedTTFL; }

   SBox ftfl[],stfl[],ttfl[];
   bool okF=BuildTier(tfF,InpLookbackX,ftfl);
   bool okS=BuildTier(tfS,InpLookbackY,stfl);
   bool okT=BuildTier(tfT,InpLookbackZ,ttfl);

   //--- A+ containment (price only, strict)
   if(okF && okS) FlagAPlus(stfl,ftfl);
   if(okS && okT) FlagAPlus(ttfl,stfl);

   if(okF && InpShowFTFL) DrawTier("FTFL",tfF,ftfl,true);
   if(okS && InpShowSTFL) DrawTier("STFL",tfS,stfl,false);
   if(okT && InpShowTTFL) DrawTier("TTFL",tfT,ttfl,false);

   if(InpShowDashboard) DrawDash(tfF,tfS,tfT,okF,okS,okT,ftfl,stfl,ttfl);

   ChartRedraw();
   return(rates_total);
  }

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES LowerTF(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_MN1: return(PERIOD_W1);
      case PERIOD_W1:  return(PERIOD_D1);
      case PERIOD_D1:  return(PERIOD_H4);
      case PERIOD_H4:  return(PERIOD_H1);
      case PERIOD_H1:  return(PERIOD_M30);
      case PERIOD_M30: return(PERIOD_M15);
      case PERIOD_M15: return(PERIOD_M5);
      case PERIOD_M5:  return(PERIOD_M1);
      default:         return(tf);
     }
  }

string TFName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_MN1: return("MN");
      case PERIOD_W1:  return("W1");
      case PERIOD_D1:  return("D1");
      case PERIOD_H4:  return("H4");
      case PERIOD_H1:  return("H1");
      case PERIOD_M30: return("M30");
      case PERIOD_M15: return("M15");
      case PERIOD_M5:  return("M5");
      case PERIOD_M1:  return("M1");
      default:         return(EnumToString(tf));
     }
  }

bool GetBars(ENUM_TIMEFRAMES tf,int want,datetime &t[],double &o[],double &h[],double &l[],double &c[])
  {
   //--- FIX: refuse unsynchronized MTF history (same guard as Storyline)
   long sync=0;
   if(!SeriesInfoInteger(_Symbol,tf,SERIES_SYNCHRONIZED,sync) || sync==0)
      return(false);
   int avail=Bars(_Symbol,tf);
   if(avail<15) return(false);
   int n=MathMin(want,avail);
   if(CopyTime(_Symbol,tf,0,n,t)<n)  return(false);
   if(CopyOpen(_Symbol,tf,0,n,o)<n)  return(false);
   if(CopyHigh(_Symbol,tf,0,n,h)<n)  return(false);
   if(CopyLow(_Symbol,tf,0,n,l)<n)   return(false);
   if(CopyClose(_Symbol,tf,0,n,c)<n) return(false);
   ArraySetAsSeries(t,true);
   ArraySetAsSeries(o,true); ArraySetAsSeries(h,true);
   ArraySetAsSeries(l,true); ArraySetAsSeries(c,true);
   return(true);
  }

//--- build all boxes (S/R + QM + OCL) for one tier TF, oldest->newest
bool BuildTier(ENUM_TIMEFRAMES tf,int lookback,SBox &bx[])
  {
   ArrayResize(bx,0);
   datetime t[]; double o[],h[],l[],c[];
   if(!GetBars(tf,lookback,t,o,h,l,c)) return(false);
   int n=ArraySize(t);
   int stepSec=(int)PeriodSeconds(tf);

   //--- pass 1: S/R boxes + remember levels for QM pass
   double lvlPrice[]; datetime lvlBirth[]; bool lvlSup[];
   int    lvlC1[];     int lvlC2[];
   int scan=MathMin(n-2,lookback);
   for(int i=scan;i>=1;i--)
     {
      bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
      bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
      bool sup=(bear1&&bull2), res=(bull1&&bear2);
      bool oclB=(bull1&&bull2), oclS=(bear1&&bear2);

       if(sup||res)
        {
         double lp=c[i+1];
         double top,bot;
         if(sup)      { top=lp; bot=MathMin(l[i+1],l[i]); }  // body -> low wick tip
         else         { bot=lp; top=MathMax(h[i+1],h[i]); }  // body -> high wick tip
         datetime t1=t[i+1];
         datetime mitig=FirstTouchAfter(t,h,l,n,i,lp);   // FIX: mitigation time
         bool fr=(mitig==0);
         datetime t2=t[i]+2*stepSec;    // one full step past candle2 close
         if(InpExtendUntilMitigated)
            t2=(fr? t[0]+2*stepSec : MathMax(t2,mitig));  // extend to touch/now
         AppendBox(bx,top,bot,lp,t1,t2,t[i],sup?"S":"R",sup?+1:-1,fr,false);
         int k=ArraySize(lvlPrice);
         ArrayResize(lvlPrice,k+1); ArrayResize(lvlBirth,k+1);
         ArrayResize(lvlSup,k+1);   ArrayResize(lvlC1,k+1); ArrayResize(lvlC2,k+1);
         lvlPrice[k]=lp; lvlBirth[k]=t[i]; lvlSup[k]=sup; lvlC1[k]=i+1; lvlC2[k]=i;
        }
       else if(oclB||oclS)
        {
         if(InpSkipEngulfingOCL && IsBodyEngulf(o,c,i+1,i)) continue;
         double lp=c[i+1];              // OCL line = close of candle1
         double top,bot;
         // FIX: box caps at candle2's BODY EDGE (per Video-10 correction),
         // but always wide enough to contain the OCL level line itself
         if(oclB)     { bot=l[i]; top=MathMax(MathMin(o[i],c[i]),lp); }  // candle2 lower wick
         else         { top=h[i]; bot=MathMin(MathMax(o[i],c[i]),lp); }  // candle2 upper wick
         datetime t1=t[i+1];            // one step left of candle2
         datetime mitig=FirstTouchAfter(t,h,l,n,i,lp);
         bool fr=(mitig==0);
         datetime t2=t[i]+2*stepSec;    // one full step past candle2 close
         if(InpExtendUntilMitigated)
            t2=(fr? t[0]+2*stepSec : MathMax(t2,mitig));
         AppendBox(bx,top,bot,lp,t1,t2,t[i],oclB?"OCL":"OCL",oclB?+1:-1,fr,false);
        }
     }

   //--- pass 2: QM boxes (same geometry as parent S/R, re-armed at QM birth)
   int LC=ArraySize(lvlPrice);
   for(int k=0;k<LC;k++)
     {
      bool dead=false;
      int qmIdx=FindQMBirthIdx(c,n,lvlC2[k],lvlPrice[k],lvlSup[k],dead);
      if(qmIdx<0) continue;
      datetime qmStart=t[qmIdx];
       double top,bot;
       if(lvlSup[k]) { top=lvlPrice[k]; bot=MathMin(l[lvlC1[k]],l[lvlC2[k]]); }
       else          { bot=lvlPrice[k]; top=MathMax(h[lvlC1[k]],h[lvlC2[k]]); }
       datetime t1=t[lvlC1[k]];
       datetime mitig=FirstTouchAfter(t,h,l,n,qmIdx,lvlPrice[k]); // fresh since QM birth
       bool fr=(mitig==0);
       datetime t2=t[lvlC2[k]]+2*stepSec;
       if(InpExtendUntilMitigated)
          t2=(fr? t[0]+2*stepSec : MathMax(t2,mitig));
       AppendBox(bx,top,bot,lvlPrice[k],t1,t2,qmStart,"QM",lvlSup[k]?+1:-1,fr,false);
     }

   SortBoxes(bx);
   return(true);
  }

bool IsBodyEngulf(const double &o[],const double &c[],int i1,int i2)
  {
   // i1=candle1 (older), i2=candle2 (newer); same-color body engulf
   if(IsBullC(o,c,i1) && IsBullC(o,c,i2))
      return(o[i2]<=o[i1] && c[i2]>=c[i1]);
   if(IsBearC(o,c,i1) && IsBearC(o,c,i2))
      return(o[i2]>=o[i1] && c[i2]<=c[i1]);
   return(false);
  }

//--- time of the first bar after 'fromIdx' (exclusive, series walk) whose
//--- wicks touch 'lp'; 0 = never touched (still fresh)
datetime FirstTouchAfter(const datetime &t[],const double &h[],const double &l[],
                         int n,int fromIdx,double lp)
  {
   for(int j=fromIdx-1;j>=0;j--)
      if(h[j]>=lp && l[j]<=lp) return(t[j]);
   return(0);
  }

//--- role walk on closes: S->SBR->QM / R->RBS->QM.
//--- Returns series index of QM birth bar (or -1); dead=true if QM later broke.
int FindQMBirthIdx(const double &c[],int n,int formedIdx,double lp,bool startsSup,bool &dead)
  {
   int role=startsSup?0:3; // 0=S,1=SBR,2=QM,3=R,4=RBS,5=QM,6=dead
   int birth=-1;
   dead=false;
   for(int j=formedIdx-1;j>=0;j--)
     {
      bool broke=false;
      switch(role)
        {
         case 0: broke=(c[j]<lp); if(broke) role=1; break;
         case 1: broke=(c[j]>lp); if(broke) { role=2; birth=j; } break;
         case 2: broke=(c[j]<lp); if(broke) { role=6; dead=true; } break;
         case 3: broke=(c[j]>lp); if(broke) role=4; break;
         case 4: broke=(c[j]<lp); if(broke) { role=5; birth=j; } break;
         case 5: broke=(c[j]>lp); if(broke) { role=6; dead=true; } break;
         default: break;
        }
      if(role==6) break;
     }
   return(birth);
  }

void AppendBox(SBox &bx[],double top,double bot,double lp,datetime t1,datetime t2,
               datetime birth,const string kind,int dir,bool fresh,bool ap)
  {
   if(t2<=t1 || top<=bot) return;
   int n=ArraySize(bx);
   ArrayResize(bx,n+1);
   bx[n].top=top; bx[n].bot=bot; bx[n].lvl_price=lp;
   bx[n].t1=t1;   bx[n].t2=t2;   bx[n].birth=birth;
   bx[n].kind=kind; bx[n].dir=dir; bx[n].fresh=fresh; bx[n].aplus=ap;
  }

//--- insertion sort by birth ascending (old->new)
void SortBoxes(SBox &bx[])
  {
   int n=ArraySize(bx);
   for(int i=1;i<n;i++)
     {
      SBox v=bx[i];
      int j=i-1;
      while(j>=0 && bx[j].birth>v.birth) { bx[j+1]=bx[j]; j--; }
      bx[j+1]=v;
     }
  }

//--- child fully inside (price) any FRESH parent box -> A+.
//--- Video 5: the parent (FTFL) must be fresh / unmitigated, otherwise
//--- the level is not valid and cannot make the child setup A+.
void FlagAPlus(SBox &child[],const SBox &parent[])
  {
   int cn=ArraySize(child), pn=ArraySize(parent);
   for(int i=0;i<cn;i++)
     {
      child[i].aplus=false;
      for(int p=0;p<pn;p++)
        {
         if(!parent[p].fresh) continue;   // FIX: fresh parents only
         // child must also be FRESH itself (Video 7: freshness universal)
         if(!child[i].fresh) break;
         if(child[i].bot>=parent[p].bot && child[i].top<=parent[p].top)
           { child[i].aplus=true; break; }
        }
     }
  }

color BoxColor(const SBox &b)
  {
   if(b.kind=="QM") return(InpQMColor);
   if(b.kind=="OCL") return(b.dir>0?InpOCLBullColor:InpOCLBearColor);
   return(b.dir>0?InpSupColor:InpResColor);
  }

void DrawTier(const string tier,ENUM_TIMEFRAMES tf,const SBox &bx[],bool isFTFL)
  {
   int n=ArraySize(bx);
   int start=(n>InpMaxBoxes)?n-InpMaxBoxes:0;
   for(int i=start;i<n;i++)
     {
      if(!bx[i].fresh && InpFreshOnly) continue;
      color clr=BoxColor(bx[i]);
      string nm=InpPrefix+tier+"_"+bx[i].kind+(bx[i].dir>0?"+":"-")+"_"+
                TimeToString(bx[i].birth,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(i);

      ObjectCreate(0,nm,OBJ_RECTANGLE,0,bx[i].t1,bx[i].top,bx[i].t2,bx[i].bot);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,nm,OBJPROP_STYLE,bx[i].fresh?STYLE_SOLID:STYLE_DASH);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
      ObjectSetInteger(0,nm,OBJPROP_FILL,false);
      ObjectSetInteger(0,nm,OBJPROP_BACK,true);
      ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
      string state=bx[i].fresh?"FRESH":"UNFRESH";
      string ap=isFTFL?"":(bx[i].aplus?" | A+ inside parent":" | not A+");
      ObjectSetString(0,nm,OBJPROP_TOOLTIP,
         StringFormat("%s %s%s box %s..%s | lvl %s | %s -> %s [%s]%s (%s)",
            tier,bx[i].kind,(bx[i].kind=="OCL"?(bx[i].dir>0?" bull":" bear"):(bx[i].dir>0?" sup":" res")),
            DoubleToString(bx[i].top,_Digits),DoubleToString(bx[i].bot,_Digits),
            DoubleToString(bx[i].lvl_price,_Digits),
            TimeToString(bx[i].t1),TimeToString(bx[i].t2),state,ap,TFName(tf)));

      if(InpShowEquilibrium)
        {
         double mid=(bx[i].top+bx[i].bot)/2.0;
         string en=nm+"_eq";
         ObjectCreate(0,en,OBJ_TREND,0,bx[i].t1,mid,bx[i].t2,mid);
         ObjectSetInteger(0,en,OBJPROP_COLOR,InpEqColor);
         ObjectSetInteger(0,en,OBJPROP_STYLE,STYLE_DOT);
         ObjectSetInteger(0,en,OBJPROP_WIDTH,1);
         ObjectSetInteger(0,en,OBJPROP_BACK,true);
         ObjectSetInteger(0,en,OBJPROP_SELECTABLE,false);
         ObjectSetString(0,en,OBJPROP_TOOLTIP,
            StringFormat("%s %s equilibrium %s (50%%)",tier,bx[i].kind,
               DoubleToString(mid,_Digits)));
        }

      if(InpShowLabels)
        {
         string ln=nm+"_lbl";
         ObjectCreate(0,ln,OBJ_TEXT,0,bx[i].t1,bx[i].top);
         string ap2=(!isFTFL && bx[i].aplus)?" A+":"";
         ObjectSetString(0,ln,OBJPROP_TEXT,
            StringFormat("%s %s%s",tier,bx[i].kind,ap2));
         ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
         ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
         ObjectSetInteger(0,ln,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0,ln,OBJPROP_BACK,true);
         ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
        }
     }
  }

void DrawDash(ENUM_TIMEFRAMES tfF,ENUM_TIMEFRAMES tfS,ENUM_TIMEFRAMES tfT,
              bool okF,bool okS,bool okT,
              const SBox &ftfl[],const SBox &stfl[],const SBox &ttfl[])
  {
   string rows[3];
   rows[0]=DashRow("FTFL",tfF,okF,ftfl,-1);
   rows[1]=DashRow("STFL",tfS,okS,stfl,CountAPlus(stfl));
   rows[2]=DashRow("TTFL",tfT,okT,ttfl,CountAPlus(ttfl));
   for(int r=0;r<3;r++)
     {
      string nm=InpPrefix+"dash_"+IntegerToString(r);
      ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,InpDashX);
      ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,InpDashY+r*18);
      ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,9);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,InpEqColor);
      ObjectSetString(0,nm,OBJPROP_TEXT,rows[r]);
      ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
      if(r==0)
        {
         string hd=InpPrefix+"dash_head";
         ObjectCreate(0,hd,OBJ_LABEL,0,0,0);
         ObjectSetInteger(0,hd,OBJPROP_CORNER,CORNER_LEFT_UPPER);
         ObjectSetInteger(0,hd,OBJPROP_XDISTANCE,InpDashX);
         ObjectSetInteger(0,hd,OBJPROP_YDISTANCE,InpDashY-18);
         ObjectSetInteger(0,hd,OBJPROP_FONTSIZE,9);
         ObjectSetInteger(0,hd,OBJPROP_COLOR,InpEqColor);
         ObjectSetString(0,hd,OBJPROP_TEXT,
            InpFollowChart?"MSNR TFL Zones (follow chart)":"MSNR TFL Zones (fixed)");
         ObjectSetInteger(0,hd,OBJPROP_SELECTABLE,false);
        }
     }
  }

string DashRow(const string tier,ENUM_TIMEFRAMES tf,bool ok,const SBox &bx[],int ap)
  {
   if(!ok) return(StringFormat("%s %s: NO DATA",tier,TFName(tf)));
   int f=0;
   for(int i=0;i<ArraySize(bx);i++) if(bx[i].fresh) f++;
   if(ap<0) return(StringFormat("%s %s: %d boxes (%d fresh)",tier,TFName(tf),ArraySize(bx),f));
   return(StringFormat("%s %s: %d boxes (%d fresh, %d A+)",tier,TFName(tf),ArraySize(bx),f,ap));
  }

int CountAPlus(const SBox &bx[])
  {
   int k=0;
   for(int i=0;i<ArraySize(bx);i++) if(bx[i].aplus) k++;
   return(k);
  }

void DeleteAllObjects()
  {
   ObjectsDeleteAll(0,InpPrefix,-1,-1);
  }
//+------------------------------------------------------------------+
