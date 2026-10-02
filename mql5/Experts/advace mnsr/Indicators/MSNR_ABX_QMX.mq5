//+------------------------------------------------------------------+
//|                                                MSNR_ABX_QMX.mq5  |
//|              ABAX Indicator B4: QM phases + QML-TL X-point         |
//+------------------------------------------------------------------+
//| Rules (ABAX P03-04, P06 §3-4):                                     |
//|  4-step QM on alternating fractal pivots: bear = HH -> HL -> LH   |
//|  (shoulder/QML) -> body break of HL -> retest of LH -> short.     |
//|  QMC when the second high takes out HH (fake continuation grab);  |
//|  else QMR. QMM = wick beyond QML + close back inside (fake-break  |
//|  ticks attached to the QM, trade the trap not the break).         |
//|  Quality gate: break body ≥0.8 ATR, retest delay ≥3 bars,          |
//|  confirmation at retest in {engulf, pin}, hesitation pre-break     |
//|  (range contraction or wick expansion) else derated. Never enter   |
//|  the fake leg: forming QMs marked WAIT until retest.               |
//|  QML-TL triple: wick TL near QML at retest; QMX: TL geometrically  |
//|  crosses QML inside the setup window + engulf -> top weight.      |
//|                                                                    |
//|  Rendering: shoulder lines/zones, phase labels, QMM ticks, TL     |
//|  stubs on triples. Most-recent caps. Closed bars only. No rays.    |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength
input int    InpATRPeriod     = 14;                // ATR period
input double InpMinBreakATR   = 0.8;               // Break body qualifier (x ATR)
input int    InpMinDelay      = 3;                 // Min retest delay (bars)
input double InpZonePips      = 2.0;               // QML zone half-width (pips)
input double InpTLTolPips     = 4.0;               // QML-TL proximity (pips)
input double InpPinMinPct     = 60.0;              // Pin wick % of range
input int    InpMaxQM         = 20;                // Max QMs drawn (most recent)
input int    InpMaxQMM        = 30;                // Max QMM ticks (most recent)
input double InpArrowGapPips  = 3.0;               // Arrow gap (pips)
input bool   InpShowLabels    = true;              // Show labels
input color  InpBearColor     = clrTomato;         // Bear QM
input color  InpBullColor     = clrDodgerBlue;     // Bull QM
input color  InpQMMColor      = clrOrange;         // QMM ticks (amber)
input color  InpTLColor       = clrGray;           // TL stubs
input string InpPrefix        = "MSNR_QX_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SPivot
   {
    double   price;
    datetime time;
    bool     is_high;
    int      idx;
   };

struct SQM
   {
    double   qml;        // shoulder level
    datetime tForm;      // shoulder bar time
    datetime tBreak;
    datetime tRetest;    // 0 = WAIT (forming)
    bool     bear;
    int      kind;       // 0 QMR, 1 QMC
    bool     lowQ;       // failed quality gate
    bool     noHes;      // no hesitation evidence
    bool     conf;       // engulf/pin confirmation at retest
    bool     triple;     // QML+TL proximity
    bool     qmx;        // geometric cross + engulf
    double   breakATR;   // break body in ATR
   };

struct STick
   {
    datetime time;
    double   px;
    bool     bear;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR QM-X");
    hATR=iATR(_Symbol,PERIOD_CURRENT,InpATRPeriod);
    if(hATR==INVALID_HANDLE) return(INIT_FAILED);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
   }

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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+5) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SQM qm[];
    STick ticks[];
    FindQMs(time,open,high,low,close,atr,rates_total,qm,ticks);

    DrawQM(qm,ticks,time[0]);
    ChartRedraw();
    return(rates_total);
   }

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

double TLAt(datetime t1,double p1,datetime t2,double p2,datetime t)
   {
    if(t2<=t1) return(p1);
    return(p1+(p2-p1)*((double)(t-t1))/((double)(t2-t1)));
   }

void FindQMs(const datetime &t[],const double &o[],const double &h[],
             const double &l[],const double &c[],const double &atr[],
             int rates_total,SQM &qm[],STick &ticks[])
   {
    ArrayResize(qm,0); ArrayResize(ticks,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double zoneTol=InpZonePips*pip;
    double tlTol  =InpTLTolPips*pip;
    double pierce =0.5*pip;

    SPivot piv[];
    FindPivots(h,l,t,rates_total,piv);
    int m=ArraySize(piv);

    //--- newest same-side pivot pair for TL proximity (wick TL, 1 pair/side)
    SPivot lastHi1,lastHi2,lastLo1,lastLo2;
    bool haveHi=false,haveLo=false;
    int hc=0,lc=0;
    for(int p=m-1;p>=0;p--)
      {
       if(piv[p].is_high && hc<2) { if(hc==0) lastHi2=piv[p]; else lastHi1=piv[p]; hc++; }
       if(!piv[p].is_high && lc<2) { if(lc==0) lastLo2=piv[p]; else lastLo1=piv[p]; lc++; }
      }
    haveHi=(hc==2); haveLo=(lc==2);

    for(int a=0;a+2<m;a++)
      {
       bool bearPat=(piv[a].is_high && !piv[a+1].is_high && piv[a+2].is_high);
       bool bullPat=(!piv[a].is_high && piv[a+1].is_high && !piv[a+2].is_high);
       if(!bearPat && !bullPat) continue;
       bool bear=bearPat;
       double HH=piv[a].price, HL=piv[a+1].price, LH=piv[a+2].price;
       int qmc=((bear && LH>HH) || (!bear && LH<HH))?1:0;   // fake extreme grab
       int lhIdx=piv[a+2].idx;
       if(lhIdx<3) continue;
       double aRef=atr[lhIdx];
       if(aRef<=0) aRef=pip*100.0;
       //--- break: first body close through HL/LH-pullback extreme
       int brk=-1;
       for(int j=lhIdx-1;j>=1;j--)
         {
          if(bear && c[j]<HL && c[j]<o[j]) { brk=j; break; }
          if(!bear && c[j]>HL && c[j]>o[j]) { brk=j; break; }
         }
       if(brk<0) continue;
       double body=MathAbs(c[brk]-o[brk]);
       double bATR=(atr[brk]>0?body/atr[brk]:0.0);
       //--- retest: first wick into QML zone after break
       int ret=-1;
       for(int j=brk-1;j>=1;j--)
         {
          if(bear && h[j]>=LH-zoneTol && l[j]<=LH+zoneTol) { ret=j; break; }
          if(!bear && l[j]<=LH+zoneTol && h[j]>=LH-zoneTol) { ret=j; break; }
         }
       //--- hesitation pre-break: contraction or wick expansion
       bool hes=false;
       if(brk+6<rates_total)
         {
          double r1=0,r2=0;
          int n1=0,n2=0;
          for(int j=brk+1;j<=MathMin(brk+3,rates_total-1);j++) { r1+=h[j]-l[j]; n1++; }
          for(int j=brk+4;j<=MathMin(brk+6,rates_total-1);j++) { r2+=h[j]-l[j]; n2++; }
          if(n1>0 && n2>0 && r1/n1<r2/n2) hes=true;
          double wmax=0, bavg=0;
          for(int j=brk+1;j<=MathMin(brk+3,rates_total-1);j++)
            {
             double uw=(bear?h[j]-MathMax(o[j],c[j]):MathMin(o[j],c[j])-l[j]);
             if(uw>wmax) wmax=uw;
             bavg+=MathAbs(c[j]-o[j]);
            }
          bavg/=3.0;
          if(wmax>bavg) hes=true;
         }
       //--- confirmation at retest: engulf or pin
       bool conf=false, engulf=false;
       if(ret>0 && ret+1<rates_total)
         {
          if(bear && IsBearC(o,c,ret) && IsBullC(o,c,ret+1) && c[ret]<o[ret+1]) engulf=true;
          if(!bear && IsBullC(o,c,ret) && IsBearC(o,c,ret+1) && c[ret]>o[ret+1]) engulf=true;
          double rg=h[ret]-l[ret];
          bool pin=false;
          if(rg>0)
            {
             if(bear && (h[ret]-MathMax(o[ret],c[ret]))>=InpPinMinPct/100.0*rg && c[ret]<LH) pin=true;
             if(!bear && (MathMin(o[ret],c[ret])-l[ret])>=InpPinMinPct/100.0*rg && c[ret]>LH) pin=true;
            }
          conf=(engulf||pin);
         }
       bool lowQ=(bATR<InpMinBreakATR);
       if(ret>0 && (brk-ret)<InpMinDelay) lowQ=true;
       if(ret>0 && !conf) lowQ=true;
       //--- QML-TL triple + QMX cross at retest (or break if still forming)
       bool triple=false, qmx=false;
       datetime refT=(ret>0?t[ret]:t[brk]);
       if((bear && haveHi) || (!bear && haveLo))
         {
          SPivot A=(bear?(hc==2?lastHi1:lastHi2):(lc==2?lastLo1:lastLo2));
          SPivot B=(bear?lastHi2:lastLo2);
          double lp=TLAt(A.time,A.price,B.time,B.price,refT);
          if(MathAbs(lp-LH)<=tlTol) triple=true;
          //--- geometric cross inside [shoulder, refT]
          double lpa=TLAt(A.time,A.price,B.time,B.price,A.time);
          double lpb=TLAt(A.time,A.price,B.time,B.price,refT);
          if((lpa-LH)*(lpb-LH)<=0) qmx=(triple && engulf);
         }
       SQM x;
       x.qml=LH; x.tForm=piv[a+2].time; x.tBreak=t[brk];
       x.tRetest=(ret>0?t[ret]:0); x.bear=bear; x.kind=qmc;
       x.lowQ=lowQ; x.noHes=!hes; x.conf=conf;
       x.triple=triple; x.qmx=qmx; x.breakATR=bATR;
       int n=ArraySize(qm);
       ArrayResize(qm,n+1); qm[n]=x;
       //--- QMM ticks: fake breaks of QML after the shoulder
       for(int j=lhIdx-1;j>=1 && ArraySize(ticks)<InpMaxQMM*3;j--)
         {
          if(bear && h[j]>LH+pierce && c[j]<LH)
            { int q=ArraySize(ticks); ArrayResize(ticks,q+1); ticks[q].time=t[j]; ticks[q].px=h[j]; ticks[q].bear=true; }
          if(!bear && l[j]<LH-pierce && c[j]>LH)
            { int q2=ArraySize(ticks); ArrayResize(ticks,q2+1); ticks[q2].time=t[j]; ticks[q2].px=l[j]; ticks[q2].bear=false; }
         }
      }
    //--- oldest -> newest by formation (N small)
    for(int i=1;i<ArraySize(qm);i++)
      {
       SQM v=qm[i]; int j=i-1;
       while(j>=0 && qm[j].tForm>v.tForm) { qm[j+1]=qm[j]; j--; }
       qm[j+1]=v;
      }
    for(int i=1;i<ArraySize(ticks);i++)
      {
       STick v=ticks[i]; int j=i-1;
       while(j>=0 && ticks[j].time>v.time) { ticks[j+1]=ticks[j]; j--; }
       ticks[j+1]=v;
      }
    int tn=ArraySize(ticks);
    if(tn>InpMaxQMM)
      {
       for(int a=0;a<InpMaxQMM;a++) ticks[a]=ticks[tn-InpMaxQMM+a];
       ArrayResize(ticks,InpMaxQMM);
      }
   }

string KindTag(const SQM &x)
   {
    string k=(x.kind==1?"QMC":"QMR");
    string d=(x.bear?"S":"B");
    if(x.tRetest==0) return("QM-WAIT");
    return(k+" "+d);
   }

void DrawQM(const SQM &qm[],const STick &ticks[],datetime now)
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double gap=InpArrowGapPips*pip;
    double zoneTol=InpZonePips*pip;
    DeleteAllObjects();
    int n=ArraySize(qm);
    int start=(n>InpMaxQM)?n-InpMaxQM:0;
    for(int k=start;k<n;k++)
      {
       bool waiting=(qm[k].tRetest==0);
       datetime t2=(waiting?now:qm[k].tRetest);
       if(t2<=qm[k].tForm) continue;
       string nm=InpPrefix+(qm[k].bear?"sell_":"buy_")+
                 TimeToString(qm[k].tForm,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color clr=(qm[k].bear?InpBearColor:InpBullColor);
       //--- shoulder zone
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,qm[k].tForm,qm[k].qml+zoneTol,t2,qm[k].qml-zoneTol);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,clr);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,(waiting?STYLE_DOT:STYLE_SOLID));
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,(qm[k].qmx?2:1));
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       string tags="";
       if(qm[k].lowQ) tags+=" LOWQ";
       if(qm[k].noHes) tags+=" noHES";
       if(qm[k].triple) tags+=" QML+TL";
       if(qm[k].qmx) tags+=" QMX";
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("%s QML %s | break %.1f ATR %s -> %s%s",
             KindTag(qm[k]),DoubleToString(qm[k].qml,_Digits),qm[k].breakATR,
             TimeToString(qm[k].tBreak),
             waiting?"WAIT retest":TimeToString(qm[k].tRetest),tags));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          double px=(qm[k].bear?qm[k].qml+zoneTol+gap:qm[k].qml-zoneTol-gap);
          ObjectCreate(0,ln,OBJ_TEXT,0,(waiting?now:qm[k].tRetest),px);
          ObjectSetString(0,ln,OBJPROP_TEXT,KindTag(qm[k])+tags);
          ObjectSetInteger(0,ln,OBJPROP_COLOR,clr);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (qm[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
      }
    for(int k=0;k<ArraySize(ticks);k++)
      {
       string nm=InpPrefix+"qmm_"+TimeToString(ticks[k].time,TIME_DATE|TIME_MINUTES)+
                 "_"+IntegerToString(k);
       ObjectCreate(0,nm,OBJ_TEXT,0,ticks[k].time,ticks[k].px);
       ObjectSetString(0,nm,OBJPROP_TEXT,"x");
       ObjectSetInteger(0,nm,OBJPROP_COLOR,InpQMMColor);
       ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,10);
       ObjectSetInteger(0,nm,OBJPROP_ANCHOR,
          (ticks[k].bear?ANCHOR_LEFT_LOWER:ANCHOR_LEFT_UPPER));
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,"QMM fake break of QML (trap, fade it)");
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
