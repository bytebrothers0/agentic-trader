//+------------------------------------------------------------------+
//|                                               MSNR_ABX_Fibo.mq5  |
//|              ABAX Indicator B11: Abay Fibo ruler + shelf anchor    |
//+------------------------------------------------------------------+
//| Rules (ABAX P10):                                                  |
//|  Fibo is the ruler, not the reason. Anchor low to an H4 key       |
//|  overlapping a chart displacement origin within tolerance          |
//|  (pragmatic 2-of-6 shelf; full 6-vote scoring at EA). High =       |
//|  opposite impulse extreme since the origin. Exact Abay level set:  |
//|  entry shelf 1.0-1.55, SL shelf -0.72/-0.75/-0.78 (beyond =        |
//|  invalidation, not deeper entry), TP shelves 2.235 -> 4.733       |
//|  toward buyside. Fibo never gates (+0.5 score). Bearish mirrors    |
//|  with inverted anchor. Newest bull + bear shelves kept.            |
//|                                                                    |
//|  Rendering: OBJ_FIBO with colored/labeled levels. Closed bars.     |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input ENUM_TIMEFRAMES InpHTF      = PERIOD_H4;         // Shelf timeframe
input int    InpHTFBars           = 200;               // HTF bars scanned
input int    InpATRPeriod         = 14;                // ATR period
input double InpDispMult          = 1.5;               // Displacement origin (x ATR)
input double InpAnchorTolATR      = 0.5;               // Origin-to-key tolerance (x ATR)
input int    InpAnchorBars        = 300;               // Origin search window (chart bars)
input int    InpLookbackBars      = 500;               // Chart bars scanned
input bool   InpShowLabels        = true;              // Level texts on (else tooltips only)
input color  InpEntryColor        = clrGoldenrod;      // Entry-shelf levels (gold)
input color  InpSLColor           = clrTomato;         // SL-shelf levels (red)
input color  InpTPColor           = clrSeaGreen;       // TP-shelf levels (green)
input color  InpBaseColor         = clrDimGray;        // 0/1 base levels
input string InpPrefix            = "MSNR_FB_";        // Object name prefix

int hATR=INVALID_HANDLE;

struct SShelf
   {
    datetime t1;      // anchor (origin) time
    double   p1;      // anchor extreme (0 level)
    datetime t2;      // impulse extreme time
    double   p2;      // impulse extreme (1 level)
    bool     bull;
   };

// Abay level set: value, role (0 base, 1 entry, 2 SL, 3 TP), label
void AbaySet(double &v[],int &role[],string &txt[])
   {
    double vv[]={0,1.0,1.47,1.55,-0.72,-0.75,-0.78,2.235,2.6,2.82,2.85,2.88,3.27,4.0,4.609,4.677,4.733};
    int rr[]={0,0,1,1,2,2,2,3,3,3,3,3,3,3,3,3,3};
    string tt[]={"0 anchor","1.0 extreme","1.47 entry","1.55 entry","-0.72 SL","-0.75 SL","-0.78 SL max",
       "2.235 TP1","2.6 TP2","2.82 TP2","2.85 TP2","2.88 TP2","3.27 TP3","4.0 TP3","4.609 TP3","4.677 TP3","4.733 buyside"};
    ArrayResize(v,ArraySize(vv)); ArrayResize(role,ArraySize(rr)); ArrayResize(txt,ArraySize(tt));
    for(int i=0;i<ArraySize(vv);i++) { v[i]=vv[i]; role[i]=rr[i]; txt[i]=tt[i]; }
   }

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR FiboAbay");
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

    if(rates_total<InpATRPeriod+10) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SShelf sh[];
    FindShelves(time,open,high,low,close,atr,rates_total,sh);

    DrawFibos(sh,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- HTF 2-candle key closes + times (I1 parity on HTF)
int HTFKeys(double &px[],datetime &tm[],bool wantSupport)
   {
    ArrayResize(px,0); ArrayResize(tm,0);
    MqlRates r[];
    int got=CopyRates(_Symbol,InpHTF,0,InpHTFBars,r);
    if(got<5) return(0);
    ArraySetAsSeries(r,true);
    for(int i=got-2;i>=1;i--)
      {
       bool bu1=(r[i+1].close>r[i+1].open), be1=(r[i+1].close<r[i+1].open);
       bool bu2=(r[i].close>r[i].open),     be2=(r[i].close<r[i].open);
       bool sup=(be1&&bu2), res=(bu1&&be2);
       if((wantSupport&&sup)||(!wantSupport&&res))
         {
          int n=ArraySize(px);
          ArrayResize(px,n+1); ArrayResize(tm,n+1);
          px[n]=r[i+1].close; tm[n]=r[i].time;
         }
      }
    return(ArraySize(px));
   }

void FindShelves(const datetime &t[],const double &o[],const double &h[],
                 const double &l[],const double &c[],const double &atr[],
                 int rates_total,SShelf &sh[])
   {
    ArrayResize(sh,0);
    double aRef=atr[1];
    if(aRef<=0) return;
    double tol=InpAnchorTolATR*aRef;
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int dir=0;dir<2;dir++)
      {
       bool bull=(dir==0);
       double tmp[];
       datetime tmt[];
       HTFKeys(tmp,tmt,bull);
       //--- newest HTF key first; one shelf per direction
       for(int q=ArraySize(tmp)-1;q>=0;q--)
         {
          bool done=false;
          //--- chart displacement origin near the key, within window
          for(int j=1;j<=MathMin(scan,InpAnchorBars);j++)
            {
             if(atr[j]<=0) continue;
             double body=MathAbs(c[j]-o[j]);
             if(body<InpDispMult*atr[j]) continue;
             if(bull && !IsBullC(o,c,j)) continue;
             if(!bull && !IsBearC(o,c,j)) continue;
             double org=(bull?l[j]:h[j]);
             if(MathAbs(org-tmp[q])>tol) continue;
             SShelf x;
             x.bull=bull;
             x.t1=t[j]; x.p1=tmp[q];
             //--- opposite impulse extreme since origin
             double ex=(bull?h[j]:l[j]);
             datetime et=t[j];
             for(int b=j-1;b>=1;b--)
               {
                if(bull && h[b]>ex) { ex=h[b]; et=t[b]; }
                if(!bull && l[b]<ex) { ex=l[b]; et=t[b]; }
               }
             if(MathAbs(ex-x.p1)<_Point*10) continue;
             x.t2=et; x.p2=ex;
             int n=ArraySize(sh);
             ArrayResize(sh,n+1); sh[n]=x;
             done=true;
             break;
            }
          if(done) break;
         }
      }
   }

void DrawFibos(const SShelf &sh[],datetime now)
   {
    DeleteAllObjects();
    double v[];
    int role[];
    string txt[];
    AbaySet(v,role,txt);
    int nv=ArraySize(v);
    for(int k=0;k<ArraySize(sh);k++)
      {
       if(sh[k].t2<=sh[k].t1) continue;
       string nm=InpPrefix+(sh[k].bull?"bull_":"bear_")+
                 TimeToString(sh[k].t1,TIME_DATE|TIME_MINUTES);
       ObjectCreate(0,nm,OBJ_FIBO,0,sh[k].t1,sh[k].p1,now,sh[k].p2);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,InpBaseColor);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetInteger(0,nm,OBJPROP_LEVELS,nv);
       for(int i=0;i<nv;i++)
         {
          color lc=(role[i]==1?InpEntryColor:(role[i]==2?InpSLColor:(role[i]==3?InpTPColor:InpBaseColor)));
          ObjectSetDouble(0,nm,OBJPROP_LEVELVALUE,i,v[i]);
          ObjectSetInteger(0,nm,OBJPROP_LEVELCOLOR,i,lc);
          ObjectSetInteger(0,nm,OBJPROP_LEVELSTYLE,i,
             (role[i]==2?STYLE_DASH:(role[i]==3?STYLE_DOT:STYLE_SOLID)));
          ObjectSetInteger(0,nm,OBJPROP_LEVELWIDTH,i,(role[i]==0?2:1));
          ObjectSetString(0,nm,OBJPROP_LEVELTEXT,i,(InpShowLabels?txt[i]:""));
         }
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("Abay Fibo %s | anchor %s -> extreme %s | entry 1.0-1.55, SL past -0.78, TP to buyside | ruler only (+0.5)",
             sh[k].bull?"bull":"bear",DoubleToString(sh[k].p1,_Digits),
             DoubleToString(sh[k].p2,_Digits)));
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
