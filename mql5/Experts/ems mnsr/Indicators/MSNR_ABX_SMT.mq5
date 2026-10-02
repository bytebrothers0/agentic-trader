//+------------------------------------------------------------------+
//|                                                MSNR_ABX_SMT.mq5  |
//|              ABAX Indicator B8: SMT divergence lie detector        |
//+------------------------------------------------------------------+
//| Rules (ABAX P08):                                                  |
//|  On correlated pairs (whitelist XAU/XAG, EU/GU, UC/CHF, AU/NU),    |
//|  when one leg takes a deeper extreme while the other holds, the   |
//|  faker lies: follow the holder. LONG bias when either leg fakes    |
//|  a lower low while the other holds; SHORT bias on fake higher      |
//|  highs. Gate: Pearson corr > 0.70 on 60-bar returns (last 5 bars   |
//|  excluded); swing alignment ±2 bars; holder tolerance 0.3× faker   |
//|  tolerance (0.3 ATR). Filter only - never an entry signal. Fake    |
//|  extreme drawn as the SL-side line.                                |
//|                                                                    |
//|  Rendering: bias arrows + SMT LONG/SHORT labels, dotted fake-      |
//|  extreme lines, live correlation readout. Most-recent cap.         |
//|  Closed bars only. No rays.                                        |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input string InpPairSymbol   = "XAGUSD";           // Correlated pair symbol
input string InpWhitelist    = "XAUUSD|XAGUSD;EURUSD|GBPUSD;USDCAD|USDCHF;AUDUSD|NZDUSD";
input int    InpLookbackBars = 120;                // Swing scan bars
input int    InpPivotStrength = 3;                 // Pivot strength
input int    InpCorrBars     = 60;                 // Correlation window (returns)
input double InpCorrMin      = 0.70;               // Min correlation gate
input double InpTolATR       = 0.3;                // Faker tolerance (x ATR)
input int    InpAlignBars    = 2;                  // Swing time alignment (bars)
input int    InpATRPeriod    = 14;                 // ATR period
input int    InpMaxDiv       = 5;                  // Max divergences drawn (recent)
input double InpArrowGapPips = 5.0;                // Arrow gap (pips of traded)
input bool   InpShowLabels   = true;               // Show labels
input color  InpLongColor    = clrDodgerBlue;      // LONG bias (follow holder up)
input color  InpShortColor   = clrTomato;          // SHORT bias
input color  InpOffColor     = clrGray;            // Gate-off readout
input string InpPrefix       = "MSNR_SMT_";        // Object name prefix

int hATRt=INVALID_HANDLE, hATRp=INVALID_HANDLE;

struct SSwing
   {
    double   price;
    datetime time;
    bool     is_high;
   };

struct SDiv
   {
    datetime time;
    double   fakePx;      // faker extreme (SL side)
    bool     biasLong;
    double   corr;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR SMT");
    hATRt=iATR(_Symbol,PERIOD_CURRENT,InpATRPeriod);
    hATRp=iATR(InpPairSymbol,PERIOD_CURRENT,InpATRPeriod);
    if(hATRt==INVALID_HANDLE||hATRp==INVALID_HANDLE) return(INIT_FAILED);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hATRt!=INVALID_HANDLE) IndicatorRelease(hATRt);
    if(hATRp!=INVALID_HANDLE) IndicatorRelease(hATRp);
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
    ArraySetAsSeries(open,true); ArraySetAsSeries(high,true);
    ArraySetAsSeries(low,true);  ArraySetAsSeries(close,true);
    ArraySetAsSeries(time,true);

    if(rates_total<InpCorrBars+10) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SDiv divs[];
    double corr=0;
    bool allowed=false, ok=false;
    FindDivergences(divs,corr,allowed,ok);

    DrawAll(divs,corr,allowed,ok,time[0]);
    ChartRedraw();
    return(rates_total);
   }

string Base6(string s)
   {
    StringTrimLeft(s); StringTrimRight(s);
    if(StringLen(s)>=6) return(StringSubstr(s,0,6));
    return(s);
   }

bool PairAllowed()
   {
    string a=Base6(_Symbol), b=Base6(InpPairSymbol);
    string w=InpWhitelist;
    StringReplace(w," ","");
    string parts[];
    int n=StringSplit(w,';',parts);
    for(int i=0;i<n;i++)
      {
       string legs[];
       if(StringSplit(parts[i],'|',legs)!=2) continue;
       if((legs[0]==a && legs[1]==b)||(legs[0]==b && legs[1]==a)) return(true);
      }
    return(false);
   }

//--- fractal swings oldest -> newest on copied arrays (series)
void Swings(const double &h[],const double &l[],const datetime &t[],int n,
            SSwing &sw[])
   {
    ArrayResize(sw,0);
    int maxScan=MathMin(InpLookbackBars,n-InpPivotStrength-1);
    for(int i=maxScan;i>=InpPivotStrength;i--)
      {
       bool isH=true,isL=true;
       for(int k=1;k<=InpPivotStrength;k++)
         {
          if(h[i]<=h[i+k]||h[i]<=h[i-k]) isH=false;
          if(l[i]>=l[i+k]||l[i]>=l[i-k]) isL=false;
          if(!isH && !isL) break;
         }
       if(!isH && !isL) continue;
       int m=ArraySize(sw);
       ArrayResize(sw,m+1);
       sw[m].is_high=(isH&&!isL)?true:(isL&&!isH)?false:(isH?true:false);
       if(isH && isL) sw[m].is_high=true;
       sw[m].price=sw[m].is_high?h[i]:l[i];
       sw[m].time=t[i];
      }
    //--- alternate (keep most extreme of doubles)
    int m2=ArraySize(sw);
    for(int a=1;a<m2;a++)
      {
       if(sw[a].is_high==sw[a-1].is_high)
         {
          bool keepA=sw[a].is_high?(sw[a].price>=sw[a-1].price):(sw[a].price<=sw[a-1].price);
          if(keepA) sw[a-1]=sw[a];
          for(int b=a+1;b<m2;b++) sw[b-1]=sw[b];
          m2--; a--;
         }
      }
    ArrayResize(sw,m2);
   }

double Pearson(const double &x[],const double &y[],int from,int count)
   {
    double sx=0,sy=0,sxx=0,syy=0,sxy=0;
    for(int i=0;i<count;i++)
      {
       double a=x[from+i], b=y[from+i];
       sx+=a; sy+=b; sxx+=a*a; syy+=b*b; sxy+=a*b;
      }
    double dx=count*sxx-sx*sx, dy=count*syy-sy*sy;
    if(dx<=0||dy<=0) return(0.0);
    return((count*sxy-sx*sy)/MathSqrt(dx*dy));
   }

void SideLists(const SSwing &sw[],bool wantHigh,SSwing &out[])
   {
    ArrayResize(out,0);
    for(int i=0;i<ArraySize(sw);i++)
       if(sw[i].is_high==wantHigh)
         { int n=ArraySize(out); ArrayResize(out,n+1); out[n]=sw[i]; }
   }

void FindDivergences(SDiv &divs[],double &corr,bool &allowed,bool &ok)
   {
    ArrayResize(divs,0);
    corr=0; ok=false;
    allowed=PairAllowed();
    if(!allowed) return;
    int need=InpLookbackBars+10;
    double hc[],lc[],cc[];
    double hp[],lp[],cp[];
    datetime tc[],tp[];
    ArraySetAsSeries(hc,true); ArraySetAsSeries(lc,true);
    ArraySetAsSeries(cc,true); ArraySetAsSeries(tc,true);
    ArraySetAsSeries(hp,true); ArraySetAsSeries(lp,true);
    ArraySetAsSeries(cp,true); ArraySetAsSeries(tp,true);
    if(CopyHigh(_Symbol,PERIOD_CURRENT,0,need,hc)!=need) return;
    if(CopyLow(_Symbol,PERIOD_CURRENT,0,need,lc)!=need) return;
    if(CopyClose(_Symbol,PERIOD_CURRENT,0,need,cc)!=need) return;
    if(CopyTime(_Symbol,PERIOD_CURRENT,0,need,tc)!=need) return;
    if(CopyHigh(InpPairSymbol,PERIOD_CURRENT,0,need,hp)!=need) return;
    if(CopyLow(InpPairSymbol,PERIOD_CURRENT,0,need,lp)!=need) return;
    if(CopyClose(InpPairSymbol,PERIOD_CURRENT,0,need,cp)!=need) return;
    if(CopyTime(InpPairSymbol,PERIOD_CURRENT,0,need,tp)!=need) return;
    //--- ATRs (latest closed bar)
    double at[], ap[];
    ArraySetAsSeries(at,true); ArraySetAsSeries(ap,true);
    if(CopyBuffer(hATRt,0,0,3,at)!=3) return;
    if(CopyBuffer(hATRp,0,0,3,ap)!=3) return;
    if(at[1]<=0||ap[1]<=0) return;
    //--- correlation on log returns, excluding last 5 bars
    double rx[], ry[];
    ArrayResize(rx,need-1); ArrayResize(ry,need-1);
    for(int i=0;i<need-1;i++)
      {
       //--- series: i newer than i+1; returns oldest -> newest for Pearson order irrelevant
       rx[i]=(cc[i]>0&&cc[i+1]>0?MathLog(cc[i]/cc[i+1]):0.0);
       ry[i]=(cp[i]>0&&cp[i+1]>0?MathLog(cp[i]/cp[i+1]):0.0);
      }
    corr=Pearson(rx,ry,5,InpCorrBars);
    if(corr<InpCorrMin) return;
    ok=true;
    double tolT=InpTolATR*at[1], tolP=InpTolATR*ap[1];
    long alignSec=(long)(InpAlignBars*PeriodSeconds(PERIOD_CURRENT));
    SSwing swT[], swP[];
    Swings(hc,lc,tc,need,swT);
    Swings(hp,lp,tp,need,swP);
    //--- evaluate recent consecutive swing pairs (lows then highs)
    for(int side=0;side<2;side++)
      {
       bool wantHigh=(side==1);
       SSwing LT[], LP[];
       SideLists(swT,wantHigh,LT);
       SideLists(swP,wantHigh,LP);
       int nT=ArraySize(LT), nP=ArraySize(LP);
       for(int a=MathMax(nT-4,1);a<nT;a++)
         {
          for(int b=MathMax(nP-4,1);b<nP;b++)
            {
             //--- pair (a-1,a) vs (b-1,b): newest swings aligned?
             if(MathAbs((long)(LT[a].time-LP[b].time))>alignSec) continue;
             if(MathAbs((long)(LT[a-1].time-LP[b-1].time))>alignSec) continue;
             if(!wantHigh)
               {
                bool tFake=(LT[a].price<LT[a-1].price-tolT &&
                            LP[b].price>=LP[b-1].price-tolP*0.3);
                bool pFake=(LP[b].price<LP[b-1].price-tolP &&
                            LT[a].price>=LT[a-1].price-tolT*0.3);
                if(tFake||pFake)
                  {
                   SDiv x;
                   x.biasLong=true; x.corr=corr;
                   x.time=(LT[a].time>LP[b].time?LT[a].time:LP[b].time);
                   x.fakePx=MathMin(LT[a].price,LP[b].price);
                   int n=ArraySize(divs);
                   ArrayResize(divs,n+1); divs[n]=x;
                  }
               }
             else
               {
                bool tFake=(LT[a].price>LT[a-1].price+tolT &&
                            LP[b].price<=LP[b-1].price+tolP*0.3);
                bool pFake=(LP[b].price>LP[b-1].price+tolP &&
                            LT[a].price<=LT[a-1].price+tolT*0.3);
                if(tFake||pFake)
                  {
                   SDiv x;
                   x.biasLong=false; x.corr=corr;
                   x.time=(LT[a].time>LP[b].time?LT[a].time:LP[b].time);
                   x.fakePx=MathMax(LT[a].price,LP[b].price);
                   int m2=ArraySize(divs);
                   ArrayResize(divs,m2+1); divs[m2]=x;
                  }
               }
            }
         }
      }
    //--- sort oldest -> newest, cap recent, dedupe same-bar
    for(int i=1;i<ArraySize(divs);i++)
      {
       SDiv v=divs[i]; int j=i-1;
       while(j>=0 && divs[j].time>v.time) { divs[j+1]=divs[j]; j--; }
       divs[j+1]=v;
      }
    int tn=ArraySize(divs);
    if(tn>InpMaxDiv)
      {
       for(int a=0;a<InpMaxDiv;a++) divs[a]=divs[tn-InpMaxDiv+a];
       ArrayResize(divs,InpMaxDiv);
      }
   }

void DrawAll(const SDiv &divs[],double corr,bool allowed,bool ok,datetime now)
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    DeleteAllObjects();
    //--- status readout (top-right label)
    string st;
    color sc=InpOffColor;
    if(!allowed) st="SMT OFF (pair not whitelisted)";
    else if(!ok) st=StringFormat("SMT OFF (corr %.2f < %.2f)",corr,InpCorrMin);
    else { st=StringFormat("SMT corr %.2f",corr); sc=InpLongColor; }
    ObjectCreate(0,InpPrefix+"status",OBJ_LABEL,0,0,0);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_CORNER,CORNER_RIGHT_UPPER);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_XDISTANCE,10);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_YDISTANCE,20);
    ObjectSetString(0,InpPrefix+"status",OBJPROP_TEXT,st);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_COLOR,sc);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_FONTSIZE,9);
    ObjectSetInteger(0,InpPrefix+"status",OBJPROP_SELECTABLE,false);
    for(int k=0;k<ArraySize(divs);k++)
      {
       string nm=InpPrefix+(divs[k].biasLong?"long_":"short_")+
                 TimeToString(divs[k].time,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(divs[k].biasLong?InpLongColor:InpShortColor);
       double apx=(divs[k].biasLong?divs[k].fakePx-gap:divs[k].fakePx+gap);
       ObjectCreate(0,nm+"_arw",(divs[k].biasLong?OBJ_ARROW_UP:OBJ_ARROW_DOWN),0,
                    divs[k].time,apx);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_WIDTH,2);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_BACK,false);
       ObjectSetInteger(0,nm+"_arw",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm+"_arw",OBJPROP_TOOLTIP,
          StringFormat("SMT %s divergence (corr %.2f) | fake extreme %s | follow the holder",
             divs[k].biasLong?"BULLISH (fade the down-fake)":"BEARISH (fade the up-fake)",
             divs[k].corr,DoubleToString(divs[k].fakePx,_Digits)));
       ObjectCreate(0,nm+"_fake",OBJ_TREND,0,divs[k].time,divs[k].fakePx,now,divs[k].fakePx);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_STYLE,STYLE_DOT);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_BACK,true);
       ObjectSetInteger(0,nm+"_fake",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm+"_fake",OBJPROP_TOOLTIP,"SMT fake extreme (SL side)");
       if(InpShowLabels)
         {
          ObjectCreate(0,nm+"_lbl",OBJ_TEXT,0,divs[k].time,
                       (divs[k].biasLong?apx-gap*3:apx+gap*3));
          ObjectSetString(0,nm+"_lbl",OBJPROP_TEXT,
             (divs[k].biasLong?"SMT LONG":"SMT SHORT"));
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_COLOR,clr);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_ANCHOR,
             (divs[k].biasLong?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_BACK,true);
          ObjectSetInteger(0,nm+"_lbl",OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
