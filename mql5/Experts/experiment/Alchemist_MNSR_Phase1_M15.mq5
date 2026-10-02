//+------------------------------------------------------------------+
//|                                    Alchemist_MNSR_Phase1_M15.mq5  |
//|              Phase 1: M15 BOS bias + TS + QMR + IDM/Liquidity      |
//+------------------------------------------------------------------+
//| LOGIC (from user spec + images):                                   |
//|  TF: M15 + H1 both calculated internally (works on any chart TF).     |
//|  H1: classic A/V levels built internally for dynamic TP (next H1     |
//|      resistance for buys / next H1 support for sells).                |
//|  1. Classic A (resistance: bull->bear, line at close[1st])         |
//|     Classic V (support: bear->bull, line at close[1st])            |
//|  2. TS: candle2 wick sweeps candle1 wick but closes back inside:   |
//|     Bearish TS: R-pair, High[2nd] > High[1st] && Close[2nd] < High |
//|     Bullish TS: S-pair, Low[2nd]  < Low[1st]  && Close[2nd] > Low  |
//|  3. BOS: full-body CLOSE through a classic level (no wick break).  |
//|     Continuous BOS up = bullish bias, down = bearish.              |
//|     Strong = TS leads to BOS.                                      |
//|  4. QMR: S->SBR->QM (buy) / R->RBS->QM (sell) on close-through.    |
//|     Use recently formed QM closest to TS. Any QM qualifies.        |
//|     Buy: QM above TS. Sell: QM below TS.                           |
//|  5. IDM/Liquidity: any ACTIVE (unswept/unbroken) classic level     |
//|     beyond QMR. Above QMR for buys, below for sells. Valid until   |
//|     swept or broken. No bar-count.                                 |
//|  6. Entry: Buy/Sell Limit at QM + 2 pip buffer.                    |
//|     TP: next H1 classic level (A for buys, V for sells) OR fixed   |
//|     via UseFixedTP. SL: fixed. Lot: fixed.                         |
//+------------------------------------------------------------------+
#property copyright "Alchemist MNSR Phase1+Phase2"
#property version   "1.03"
#include <Trade\Trade.mqh>
CTrade trade;

//--- inputs
input double InpLot            = 0.01;   // Fixed lot
input double InpFixedSL_Pips   = 350.0;  // Fixed SL (pips, both phases)
input double InpFixedTP_Pips   = 200.0;  // Fixed TP (pips, fallback)
input bool   InpUseFixedTP     = false;  // Use fixed TP? (false = HTF classic level TP)
input double InpLimitBufferPips= 2.0;    // Limit buffer for spread (pips)
input int    InpM15Lookback    = 500;    // M15 lookback bars
input int    InpM5Lookback     = 500;    // M5 lookback bars (Phase1 on M5)
input bool   InpUsePhase1M5    = true;   // Run Phase1 logic on M5 as well
input int    InpH1Lookback     = 300;    // H1 lookback bars
input int    InpH4Lookback     = 200;    // H4 lookback bars (Phase2 FVG + TP)
input int    InpMaxTSAgeBars   = 60;     // Max M15 bars since TS (Phase1 recency)
input int    InpFvgMaxAgeBars  = 50;     // Max HTF bars since FVG (Phase2 recency)
input bool   InpUsePhase1      = true;   // Use Phase1 (M15 TS->BOS->QMR->IDM)
input bool   InpUsePhase2      = true;   // Use Phase2 (H4/H1 FVG + LTF classic+TS)
input bool   InpP2StrictInside = false;  // P2: full 2-candle inside FVG? (false = level+TS extreme inside)
input long   InpMagic          = 20260930; // Magic
input int    InpSlippage       = 20;     // Slippage (points)
input bool   InpAllowBuy       = true;   // Allow buys
input bool   InpAllowSell      = true;   // Allow sells

//--- structs
struct ClassicLevel
  {
   double   price;
   datetime formed_time;
   int      shift_second;   // M15 shift of 2nd (confirming) candle
   int      shift_first;    // shift of 1st candle
   bool     is_support;     // true=V/support, false=A/resistance
   datetime broken_time;
   bool     broken;
  };

struct TSEvent
  {
   bool     bullish;        // true = low sweep (buy side), false = high sweep
   double   sweep_ref;      // wick of candle1 (H1st or L1st)
   double   level_price;    // classic close-price (not used for entry, for info)
   datetime time;
   int      shift_second;
  };

struct BOSEvent
  {
   bool     bullish;
   double   level_price;
   datetime time;
   int      shift_break;
  };

struct QMLevel
  {
   double   price;
   datetime base_formed;
   datetime qm_time;
   bool     is_buy;         // true: S->SBR->QM, false: R->RBS->QM
   bool     dead;
   datetime dead_time;
  };

struct FVGZone
  {
   bool     bullish;        // true = bullish imbalance (buy), false = bearish
   double   top;
   double   bottom;
   double   mid50;
   datetime formed_time;    // time of 3rd (confirming) candle
   int      shift_third;    // series shift of 3rd candle
   bool     mitigated;
  };

//+------------------------------------------------------------------+
double PipsToPrice(double pips)
  {
   double factor = (_Digits==3 || _Digits==5) ? 10.0 : 1.0;
   return(pips * factor * _Point);
  }
bool IsBull(double o,double c) { return(c>o); }
bool IsBear(double o,double c) { return(c<o); }

//--- fetch M15 / H1 arrays (series, 0 = current forming)
bool GetTFData(ENUM_TIMEFRAMES tf,int count,
               datetime &t[],double &o[],double &h[],double &l[],double &c[])
  {
   ArraySetAsSeries(t,true); ArraySetAsSeries(o,true);
   ArraySetAsSeries(h,true); ArraySetAsSeries(l,true); ArraySetAsSeries(c,true);
   if(CopyTime(_Symbol,tf,0,count,t)<count) return(false);
   if(CopyOpen(_Symbol,tf,0,count,o)<count) return(false);
   if(CopyHigh(_Symbol,tf,0,count,h)<count) return(false);
   if(CopyLow(_Symbol,tf,0,count,l)<count) return(false);
   if(CopyClose(_Symbol,tf,0,count,c)<count) return(false);
   return(true);
  }

//--- build classic A/V levels on given arrays (skip shift 0 forming bar)
int BuildClassic(const datetime &t[],const double &o[],const double &c[],
                 int lookback,ClassicLevel &out[])
  {
   ArrayResize(out,0);
   int total = ArraySize(c);
   int scan = MathMin(lookback,total-3);
   for(int i=scan; i>=1; i--)
     {
      bool bull1=IsBull(o[i+1],c[i+1]), bear1=IsBear(o[i+1],c[i+1]);
      bool bull2=IsBull(o[i],c[i]),     bear2=IsBear(o[i],c[i]);
      bool sup = (bear1 && bull2);
      bool res = (bull1 && bear2);
      if(!sup && !res) continue;
      ClassicLevel lv;
      lv.price        = c[i+1];
      lv.formed_time  = t[i];
      lv.shift_second = i;
      lv.shift_first  = i+1;
      lv.is_support   = sup;
      lv.broken       = false;
      lv.broken_time  = 0;
      int n=ArraySize(out);
      ArrayResize(out,n+1); out[n]=lv;
     }
   // mark broken (close-through) in chronological order
   int cnt=ArraySize(out);
   for(int k=0;k<cnt;k++)
     {
      for(int s=out[k].shift_second-1; s>=1; s--)
        {
         if(out[k].is_support && c[s]<out[k].price) { out[k].broken=true; out[k].broken_time=t[s]; break; }
         if(!out[k].is_support && c[s]>out[k].price){ out[k].broken=true; out[k].broken_time=t[s]; break; }
        }
     }
   return(cnt);
  }

//--- detect TS events (wick sweep + close back inside) on same pairs
int BuildTS(const datetime &t[],const double &o[],const double &h[],
            const double &l[],const double &c[],int lookback,TSEvent &out[])
  {
   ArrayResize(out,0);
   int total=ArraySize(c);
   int scan=MathMin(lookback,total-3);
   for(int i=scan;i>=1;i--)
     {
      bool bull1=IsBull(o[i+1],c[i+1]), bear1=IsBear(o[i+1],c[i+1]);
      bool bull2=IsBull(o[i],c[i]),     bear2=IsBear(o[i],c[i]);
      // resistance pair -> bearish TS candidate
      if(bull1 && bear2)
        {
         if(h[i]>h[i+1] && c[i]<h[i+1])
           {
            TSEvent e; e.bullish=false; e.sweep_ref=h[i+1];
            e.level_price=c[i+1]; e.time=t[i]; e.shift_second=i;
            int n=ArraySize(out); ArrayResize(out,n+1); out[n]=e;
           }
        }
      // support pair -> bullish TS candidate
      if(bear1 && bull2)
        {
         if(l[i]<l[i+1] && c[i]>l[i+1])
           {
            TSEvent e; e.bullish=true; e.sweep_ref=l[i+1];
            e.level_price=c[i+1]; e.time=t[i]; e.shift_second=i;
            int n=ArraySize(out); ArrayResize(out,n+1); out[n]=e;
           }
        }
     }
   return(ArraySize(out));
  }

//--- BOS: full-body close through a classic level. Return events sorted old->new.
int BuildBOS(const ClassicLevel &lvls[],const datetime &t[],
             const double &o[],const double &c[],BOSEvent &out[])
  {
   ArrayResize(out,0);
   int nl=ArraySize(lvls);
   for(int k=0;k<nl;k++)
     {
      for(int s=lvls[k].shift_second-1; s>=1; s--)
        {
         bool upBreak   = (!lvls[k].is_support && c[s]>lvls[k].price);
         bool downBreak = ( lvls[k].is_support && c[s]<lvls[k].price);
         if(!upBreak && !downBreak) continue;
         // full-body: body must close through (doji excluded)
         if(c[s]==o[s]) continue;
         BOSEvent e;
         e.bullish     = upBreak;
         e.level_price = lvls[k].price;
         e.time        = t[s];
         e.shift_break = s;
         int n=ArraySize(out); ArrayResize(out,n+1); out[n]=e;
         break; // first break only per level
        }
     }
   // sort by time old->new (bubble, small N)
   int n=ArraySize(out);
   for(int a=0;a<n;a++)
      for(int b=a+1;b<n;b++)
         if(out[b].time<out[a].time){ BOSEvent tmp=out[a]; out[a]=out[b]; out[b]=tmp; }
   return(n);
  }

//--- QM via role-flip on close-through
int BuildQM(const ClassicLevel &lvls[],const datetime &t[],
            const double &c[],QMLevel &out[])
  {
   ArrayResize(out,0);
   int nl=ArraySize(lvls);
   for(int k=0;k<nl;k++)
     {
      double p=lvls[k].price;
      datetime tSBR=0,tQM=0,tRBS=0,tQM2=0,tDead=0;
      bool dead=false;
      if(lvls[k].is_support)
        {
         // S -> close below -> SBR -> close above -> QM -> close below -> DEAD
         for(int s=lvls[k].shift_second-1;s>=1;s--)
           {
            if(tSBR==0 && c[s]<p){ tSBR=t[s]; continue; }
            if(tSBR>0 && tQM==0 && c[s]>p){ tQM=t[s]; continue; }
            if(tQM>0 && c[s]<p){ tDead=t[s]; dead=true; break; }
           }
         if(tQM>0)
           {
            QMLevel q; q.price=p; q.base_formed=lvls[k].formed_time;
            q.qm_time=tQM; q.is_buy=true; q.dead=dead; q.dead_time=tDead;
            int n=ArraySize(out); ArrayResize(out,n+1); out[n]=q;
           }
        }
      else
        {
         for(int s=lvls[k].shift_second-1;s>=1;s--)
           {
            if(tRBS==0 && c[s]>p){ tRBS=t[s]; continue; }
            if(tRBS>0 && tQM2==0 && c[s]<p){ tQM2=t[s]; continue; }
            if(tQM2>0 && c[s]>p){ tDead=t[s]; dead=true; break; }
           }
         if(tQM2>0)
           {
            QMLevel q; q.price=p; q.base_formed=lvls[k].formed_time;
            q.qm_time=tQM2; q.is_buy=false; q.dead=dead; q.dead_time=tDead;
            int n=ArraySize(out); ArrayResize(out,n+1); out[n]=q;
           }
        }
     }
   return(ArraySize(out));
  }

//--- next H1 classic level for TP
bool H1_Target(bool isBuy,double entry,datetime &t[],double &o[],
               double &h[],double &l[],double &c[],double &target)
  {
   ClassicLevel hl[]; BuildClassic(t,o,c,InpH1Lookback,hl);
   double best=0; bool found=false;
   int n=ArraySize(hl);
   for(int k=0;k<n;k++)
     {
      if(hl[k].broken) continue; // only active levels
      if(isBuy && !hl[k].is_support && hl[k].price>entry)
        { if(!found||hl[k].price<best){best=hl[k].price;found=true;} }
      if(!isBuy && hl[k].is_support && hl[k].price<entry)
        { if(!found||hl[k].price>best){best=hl[k].price;found=true;} }
     }
   if(found){ target=best; return(true); }
   return(false);
  }

//--- generic HTF classic target (used by Phase2: H4 or H1 depending on FVG source)
bool HTF_Target(ENUM_TIMEFRAMES tf,bool isBuy,double entry,int lookback,double &target)
  {
   datetime t[]; double o[],h[],l[],c[];
   if(!GetTFData(tf,lookback+10,t,o,h,l,c)) return(false);
   ClassicLevel hl[]; BuildClassic(t,o,c,lookback,hl);
   double best=0; bool found=false;
   int n=ArraySize(hl);
   for(int k=0;k<n;k++)
     {
      if(hl[k].broken) continue;
      if(isBuy && !hl[k].is_support && hl[k].price>entry)
        { if(!found||hl[k].price<best){best=hl[k].price;found=true;} }
      if(!isBuy && hl[k].is_support && hl[k].price<entry)
        { if(!found||hl[k].price>best){best=hl[k].price;found=true;} }
     }
   if(found){ target=best; return(true); }
   return(false);
  }

//--- FVG builder on given arrays (series, skip shift 0). Unmitigated only if requested.
int BuildFVG(const datetime &t[],const double &h[],const double &l[],
             int lookback,bool unmitigatedOnly,FVGZone &out[])
  {
   ArrayResize(out,0);
   int total=ArraySize(l);
   int scan=MathMin(lookback,total-4);
   for(int i=scan;i>=1;i--)
     {
      // triplet: first=i+2, mid=i+1, third=i (series: i=newest of the 3)
      double h1=h[i+2], l3=l[i];
      double l1=l[i+2], h3=h[i];
      // bullish FVG: high[first] < low[third]
      if(h1<l3)
        {
         FVGZone z; z.bullish=true; z.bottom=h1; z.top=l3;
         z.mid50=(z.top+z.bottom)*0.5; z.formed_time=t[i]; z.shift_third=i;
         z.mitigated=false;
         for(int s=i-1;s>=1;s--){ if(l[s]<=z.top){z.mitigated=true; break;} }
         if(unmitigatedOnly && z.mitigated) continue;
         int n=ArraySize(out); ArrayResize(out,n+1); out[n]=z;
        }
      // bearish FVG: low[first] > high[third]
      else if(l1>h3)
        {
         FVGZone z; z.bullish=false; z.bottom=h3; z.top=l1;
         z.mid50=(z.top+z.bottom)*0.5; z.formed_time=t[i]; z.shift_third=i;
         z.mitigated=false;
         for(int s=i-1;s>=1;s--){ if(h[s]>=z.bottom){z.mitigated=true; break;} }
         if(unmitigatedOnly && z.mitigated) continue;
         int n=ArraySize(out); ArrayResize(out,n+1); out[n]=z;
        }
     }
   return(ArraySize(out));
  }

//--- find most-recent classic+TS fully inside FVG with level on correct side of 50%
//--- returns true + classic price if found
bool FindClassicTSInside(const datetime &t[],const double &o[],const double &h[],
                         const double &l[],const double &c[],int lookback,
                         const FVGZone &fvg,bool wantBuy,double &classicPrice,datetime &classicTime)
  {
   int total=ArraySize(c);
   int scan=MathMin(lookback,total-3);
   for(int i=1;i<=scan;i++) // newest first -> most recent wins
     {
      bool bull1=IsBull(o[i+1],c[i+1]), bear1=IsBear(o[i+1],c[i+1]);
      bool bull2=IsBull(o[i],c[i]),     bear2=IsBear(o[i],c[i]);
      bool sup=(bear1 && bull2), res=(bull1 && bear2);
      if(wantBuy && !sup) continue;
      if(!wantBuy && !res) continue;
      // TS condition on same pair
      if(wantBuy){ if(!(l[i]<l[i+1] && c[i]>l[i+1])) continue; }
      else       { if(!(h[i]>h[i+1] && c[i]<h[i+1])) continue; }
      double lvl=c[i+1];
      // inside rule: strict = full 2-candle wicks inside FVG;
      // loose = level price + TS extreme inside FVG
      if(InpP2StrictInside)
        {
         double top2=MathMax(h[i],h[i+1]), bot2=MathMin(l[i],l[i+1]);
         if(top2>fvg.top || bot2<fvg.bottom) continue;
        }
      else
        {
         if(wantBuy && (l[i]<fvg.bottom || l[i]>fvg.top)) continue;
         if(!wantBuy && (h[i]<fvg.bottom || h[i]>fvg.top)) continue;
        }
      if(lvl>fvg.top || lvl<fvg.bottom) continue;
      // 50% rule: buys below 50%, sells above 50%
      if(wantBuy && lvl>=fvg.mid50) continue;
      if(!wantBuy && lvl<=fvg.mid50) continue;
      classicPrice=lvl; classicTime=t[i];
      return(true);
     }
   return(false);
  }

bool HasPositionOrOrder()
  {
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i);
      if(tk>0 && PositionGetInteger(POSITION_MAGIC)==InpMagic
         && PositionGetString(POSITION_SYMBOL)==_Symbol) return(true);
     }
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong tk=OrderGetTicket(i);
      if(tk>0 && OrderGetInteger(ORDER_MAGIC)==InpMagic
         && OrderGetString(ORDER_SYMBOL)==_Symbol) return(true);
     }
   return(false);
  }

datetime lastM3Bar=0;

//--- Phase1 engine on any TF (bias via BOS, TS must lead to BOS,
//--- most-recent QM on correct side of TS, IDM/liquidity beyond, limit at QM).
//--- Returns true when an order was placed.
bool TryPhase1TF(ENUM_TIMEFRAMES tf,int lookback,string tag,
                 double ask,double bid,double buf,double slDist,double tpDist)
  {
   int N=lookback+10;
   datetime t[]; double o[],h[],l[],c[];
   if(!GetTFData(tf,N,t,o,h,l,c)) return(false);

   ClassicLevel lvls[]; BuildClassic(t,o,c,lookback,lvls);
   TSEvent ts[];        BuildTS(t,o,h,l,c,lookback,ts);
   BOSEvent bos[];      BuildBOS(lvls,t,o,c,bos);
   QMLevel qms[];       BuildQM(lvls,t,c,qms);
   if(ArraySize(ts)==0 || ArraySize(bos)==0 || ArraySize(qms)==0) return(false);

   bool biasBull=bos[ArraySize(bos)-1].bullish;

   if(InpAllowBuy && biasBull)
     {
      for(int i=ArraySize(ts)-1;i>=0;i--)
        {
         if(!ts[i].bullish) continue;
         if(ts[i].shift_second-1>InpMaxTSAgeBars) continue;
         bool leadsBOS=false;
         for(int b=0;b<ArraySize(bos);b++)
            if(bos[b].bullish && bos[b].time>ts[i].time){ leadsBOS=true; break; }
         if(!leadsBOS) continue;
         int bestQ=-1; datetime bestT=0; double bestD=1e18;
         for(int q=0;q<ArraySize(qms);q++)
           {
            if(!qms[q].is_buy || qms[q].dead) continue;
            if(qms[q].qm_time<ts[i].time) continue;
            if(qms[q].price<=ts[i].sweep_ref) continue;
            double d=MathAbs(qms[q].price-ts[i].sweep_ref);
            if(qms[q].qm_time>bestT || (qms[q].qm_time==bestT && d<bestD)){bestT=qms[q].qm_time; bestD=d; bestQ=q;}
           }
         if(bestQ<0) continue;
         double qmPrice=qms[bestQ].price;
         bool hasLiq=false;
         for(int k=0;k<ArraySize(lvls);k++)
           {
            if(lvls[k].is_support) continue;
            if(lvls[k].broken) continue;
            if(lvls[k].price>qmPrice){ hasLiq=true; break; }
           }
         if(!hasLiq) continue;
         double limitPx=qmPrice+buf;
         if(ask<=limitPx+_Point) continue;
         double sl=limitPx-slDist, tp=limitPx+tpDist;
         if(!InpUseFixedTP)
           {
            double ht2=0;
            if(HTF_Target(PERIOD_H1,true,limitPx,InpH1Lookback,ht2)) tp=ht2;
           }
         if(tp<=limitPx || sl>=limitPx) continue;
         trade.BuyLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                        NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                        ORDER_TIME_GTC,0,
                        StringFormat("%s BUY TS %.5f QM %.5f",tag,ts[i].sweep_ref,qmPrice));
         return(true);
        }
     }

   if(InpAllowSell && !biasBull)
     {
      for(int i=ArraySize(ts)-1;i>=0;i--)
        {
         if(ts[i].bullish) continue;
         if(ts[i].shift_second-1>InpMaxTSAgeBars) continue;
         bool leadsBOS=false;
         for(int b=0;b<ArraySize(bos);b++)
            if(!bos[b].bullish && bos[b].time>ts[i].time){ leadsBOS=true; break; }
         if(!leadsBOS) continue;
         int bestQ=-1; datetime bestT=0; double bestD=1e18;
         for(int q=0;q<ArraySize(qms);q++)
           {
            if(qms[q].is_buy || qms[q].dead) continue;
            if(qms[q].qm_time<ts[i].time) continue;
            if(qms[q].price>=ts[i].sweep_ref) continue;
            double d=MathAbs(qms[q].price-ts[i].sweep_ref);
            if(qms[q].qm_time>bestT || (qms[q].qm_time==bestT && d<bestD)){bestT=qms[q].qm_time; bestD=d; bestQ=q;}
           }
         if(bestQ<0) continue;
         double qmPrice=qms[bestQ].price;
         bool hasLiq=false;
         for(int k=0;k<ArraySize(lvls);k++)
           {
            if(!lvls[k].is_support) continue;
            if(lvls[k].broken) continue;
            if(lvls[k].price<qmPrice){ hasLiq=true; break; }
           }
         if(!hasLiq) continue;
         double limitPx=qmPrice-buf;
         if(bid>=limitPx-_Point) continue;
         double sl=limitPx+slDist, tp=limitPx-tpDist;
         if(!InpUseFixedTP)
           {
            double ht2=0;
            if(HTF_Target(PERIOD_H1,false,limitPx,InpH1Lookback,ht2)) tp=ht2;
           }
         if(tp>=limitPx || sl<=limitPx) continue;
         trade.SellLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                         NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                         ORDER_TIME_GTC,0,
                         StringFormat("%s SELL TS %.5f QM %.5f",tag,ts[i].sweep_ref,qmPrice));
         return(true);
        }
     }
   return(false);
  }
//+------------------------------------------------------------------+
void OnTick()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);

   //--- evaluate on new M3 bar (fastest TF; all logic internal)
   datetime mt3[2];
   if(CopyTime(_Symbol,PERIOD_M3,0,2,mt3)<2) return;
   if(mt3[0]==lastM3Bar) return;
   lastM3Bar=mt3[0];

   if(HasPositionOrOrder()) return;

   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double buf=PipsToPrice(InpLimitBufferPips);
   double slDist=PipsToPrice(InpFixedSL_Pips);
   double tpDist=PipsToPrice(InpFixedTP_Pips);

   //==================== PHASE 1 (TS->BOS->QMR->IDM on M15 + M5) ============
   if(InpUsePhase1)
     {
      if(TryPhase1TF(PERIOD_M15,InpM15Lookback,"P1-M15",ask,bid,buf,slDist,tpDist)) return;
      if(InpUsePhase1M5)
        { if(TryPhase1TF(PERIOD_M5,InpM5Lookback,"P1-M5",ask,bid,buf,slDist,tpDist)) return; }
     }

   //==================== PHASE 2 (H4/H1 FVG + LTF classic+TS inside) ============
   if(InpUsePhase2 && !HasPositionOrOrder())
     {
      //--- H4 FVGs first (higher priority), then H1 FVGs
      datetime t4[]; double o4[],h4[],l4[],c4[];
      datetime t1[]; double o1[],h1[],l1[],c1[];
      bool hasH4=GetTFData(PERIOD_H4,InpH4Lookback+10,t4,o4,h4,l4,c4);
      bool hasH1=GetTFData(PERIOD_H1,InpH1Lookback+10,t1,o1,h1,l1,c1);
      // build FVG lists (unmitigated only), newest last -> iterate reverse
      FVGZone f4[]; int n4=0;
      FVGZone f1[]; int n1=0;
      if(hasH4) n4=BuildFVG(t4,h4,l4,InpH4Lookback,true,f4);
      if(hasH1) n1=BuildFVG(t1,h1,l1,InpH1Lookback,true,f1);

      // helper scan order per source
      ENUM_TIMEFRAMES h4scan[5]={PERIOD_H2,PERIOD_H1,PERIOD_M15,PERIOD_M5,PERIOD_M3};
      ENUM_TIMEFRAMES h1scan[3]={PERIOD_M15,PERIOD_M5,PERIOD_M3};

      //--- try H4 FVGs (newest first)
      for(int fi=n4-1; fi>=0 && !HasPositionOrOrder(); fi--)
        {
         if(f4[fi].shift_third-1>InpFvgMaxAgeBars) continue; // recency on HTF bars
         bool wantBuy=f4[fi].bullish;
         if(wantBuy && !InpAllowBuy) continue;
         if(!wantBuy && !InpAllowSell) continue;
         for(int si=0; si<5; si++)
           {
            datetime lt[]; double lo[],lh[],ll[],lc[];
            if(!GetTFData(h4scan[si],500,lt,lo,lh,ll,lc)) continue;
            double clvl=0; datetime ctl=0;
            if(!FindClassicTSInside(lt,lo,lh,ll,lc,400,f4[fi],wantBuy,clvl,ctl)) continue;
            double limitPx=wantBuy ? clvl+buf : clvl-buf;
            if(wantBuy && ask<=limitPx+_Point) continue;
            if(!wantBuy && bid>=limitPx-_Point) continue;
            double sl =wantBuy ? limitPx-slDist : limitPx+slDist;
            double tp =wantBuy ? limitPx+tpDist : limitPx-tpDist;
            if(!InpUseFixedTP)
              {
               double ht2=0;
               if(HTF_Target(PERIOD_H4,wantBuy,limitPx,InpH4Lookback,ht2)) tp=ht2;
              }
            if(wantBuy && (tp<=limitPx || sl>=limitPx)) continue;
            if(!wantBuy && (tp>=limitPx || sl<=limitPx)) continue;
            if(wantBuy) trade.BuyLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                              NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                              ORDER_TIME_GTC,0,
                              StringFormat("P2 BUY H4FVG %.5f-%.5f LTF %s %.5f",
                                 f4[fi].bottom,f4[fi].top,EnumToString(h4scan[si]),clvl));
            else trade.SellLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                              NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                              ORDER_TIME_GTC,0,
                              StringFormat("P2 SELL H4FVG %.5f-%.5f LTF %s %.5f",
                                 f4[fi].bottom,f4[fi].top,EnumToString(h4scan[si]),clvl));
            return;
           }
        }
      //--- then H1 FVGs (newest first)
      for(int fi=n1-1; fi>=0 && !HasPositionOrOrder(); fi--)
        {
         if(f1[fi].shift_third-1>InpFvgMaxAgeBars) continue;
         bool wantBuy=f1[fi].bullish;
         if(wantBuy && !InpAllowBuy) continue;
         if(!wantBuy && !InpAllowSell) continue;
         for(int si=0; si<3; si++)
           {
            datetime lt[]; double lo[],lh[],ll[],lc[];
            if(!GetTFData(h1scan[si],500,lt,lo,lh,ll,lc)) continue;
            double clvl=0; datetime ctl=0;
            if(!FindClassicTSInside(lt,lo,lh,ll,lc,400,f1[fi],wantBuy,clvl,ctl)) continue;
            double limitPx=wantBuy ? clvl+buf : clvl-buf;
            if(wantBuy && ask<=limitPx+_Point) continue;
            if(!wantBuy && bid>=limitPx-_Point) continue;
            double sl =wantBuy ? limitPx-slDist : limitPx+slDist;
            double tp =wantBuy ? limitPx+tpDist : limitPx-tpDist;
            if(!InpUseFixedTP)
              {
               double ht2=0;
               if(HTF_Target(PERIOD_H1,wantBuy,limitPx,InpH1Lookback,ht2)) tp=ht2;
              }
            if(wantBuy && (tp<=limitPx || sl>=limitPx)) continue;
            if(!wantBuy && (tp>=limitPx || sl<=limitPx)) continue;
            if(wantBuy) trade.BuyLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                              NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                              ORDER_TIME_GTC,0,
                              StringFormat("P2 BUY H1FVG %.5f-%.5f LTF %s %.5f",
                                 f1[fi].bottom,f1[fi].top,EnumToString(h1scan[si]),clvl));
            else trade.SellLimit(InpLot,NormalizeDouble(limitPx,_Digits),_Symbol,
                              NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),
                              ORDER_TIME_GTC,0,
                              StringFormat("P2 SELL H1FVG %.5f-%.5f LTF %s %.5f",
                                 f1[fi].bottom,f1[fi].top,EnumToString(h1scan[si]),clvl));
            return;
           }
        }
     }

   Comment(StringFormat("Alchemist P1+P2 | P1=%s P2=%s",
           InpUsePhase1?"on":"off",InpUsePhase2?"on":"off"));
  }
//+------------------------------------------------------------------+
