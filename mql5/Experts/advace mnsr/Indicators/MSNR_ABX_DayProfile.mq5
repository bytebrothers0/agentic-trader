//+------------------------------------------------------------------+
//|                                           MSNR_ABX_DayProfile.mq5 |
//|              ABAX Indicator B10: daily bias + session profiles     |
//+------------------------------------------------------------------+
//| Rules (ABAX P09):                                                  |
//|  Bias = HTF dealing-range PD position + ERL-swept flags: discount |
//|  -> LONG toward buy-side ERL; premium -> SHORT toward sell-side;   |
//|  equilibrium band -> NONE (wait for M). ERL-swept exception allows |
//|  the reversal side. Premium BOS without sweep = trap (labeled).    |
//|  Profiles on today (intraday): P1 trend (London displacement + NY  |
//|  continuation), P2 NY reversal, P3 Judas (spike 0.2 ATR + wick     |
//|  >60% + return ≤3 bars -> fade), P5 Seek&Destroy (day range < 0.7  |
//|  ATR_D1 + both sides swept + no displacement close -> EQ-only,     |
//|  half size). SMT confirmation layered from B8 at EA score time.    |
//|                                                                    |
//|  Rendering: bias + profile labels (top-left), target-pool line,    |
//|  Judas arrow. Closed bars only. No rays.                           |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input ENUM_TIMEFRAMES InpRangeTF   = PERIOD_H4;        // Dealing-range TF
input int    InpRangeBars     = 120;               // Dealing-range bars
input double InpEQBand        = 0.05;              // Equilibrium half-band (fraction)
input int    InpATRPeriod     = 14;                // ATR period
input int    InpAsiaStart     = 0;                 // Asia start (server hour)
input int    InpAsiaEnd       = 7;                 // Asia end (server hour)
input int    InpLondonStart   = 7;                 // London start (server hour)
input int    InpLondonEnd     = 11;                // London end (server hour)
input int    InpNYStart       = 12;                // New York start (server hour)
input int    InpNYEnd         = 21;                // New York end (server hour)
input double InpDispMult      = 1.5;               // Displacement (x ATR)
input double InpJudasATR      = 0.2;               // Judas spike beyond (x ATR)
input double InpJudasWickPct  = 60.0;              // Judas wick % of range
input int    InpJudasBack     = 3;                 // Judas return window (bars)
input double InpSDRangeATR    = 0.7;               // S&D day range (x ATR_D1)
input bool   InpShowTarget    = true;              // Draw target-pool line
input color  InpLongColor     = clrDodgerBlue;     // Long bias
input color  InpShortColor    = clrTomato;         // Short bias
input color  InpNoneColor     = clrGray;           // No bias
input color  InpTargetColor   = clrGoldenrod;      // Target line (gold)
input string InpPrefix        = "MSNR_DP_";        // Object name prefix

int hATR=INVALID_HANDLE, hATRD1=INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR DayProfile");
    hATR=iATR(_Symbol,PERIOD_CURRENT,InpATRPeriod);
    hATRD1=iATR(_Symbol,PERIOD_D1,InpATRPeriod);
    if(hATR==INVALID_HANDLE||hATRD1==INVALID_HANDLE) return(INIT_FAILED);
    return(INIT_SUCCEEDED);
   }

void OnDeinit(const int reason)
   {
    DeleteAllObjects();
    if(hATR!=INVALID_HANDLE) IndicatorRelease(hATR);
    if(hATRD1!=INVALID_HANDLE) IndicatorRelease(hATRD1);
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

    if(rates_total<InpATRPeriod+10) return(0);
    if(PeriodSeconds(PERIOD_CURRENT)>3600) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);
    double ad1[];
    ArraySetAsSeries(ad1,true);
    if(CopyBuffer(hATRD1,0,0,3,ad1)!=3) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    DrawDay(time,open,high,low,close,atr,ad1[1],rates_total);
    ChartRedraw();
    return(rates_total);
   }

bool InWin(int hour,int s,int e)
   {
    if(s<=e) return(hour>=s && hour<e);
    return(hour>=s || hour<e);
   }

datetime DayStart(datetime tt)
   {
    MqlDateTime d;
    TimeToStruct(tt,d);
    d.hour=0; d.min=0; d.sec=0;
    return(StructToTime(d));
   }

void DrawDay(const datetime &t[],const double &o[],const double &h[],
             const double &l[],const double &c[],const double &atr[],
             double atrD1,int rates_total)
   {
    DeleteAllObjects();
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    datetime today=DayStart(t[0]);
    double ref=c[1];

    //--- HTF dealing range
    double rh[], rl[];
    ArraySetAsSeries(rh,true); ArraySetAsSeries(rl,true);
    double rHi=0, rLo=0;
    bool haveRange=(CopyHigh(_Symbol,InpRangeTF,0,InpRangeBars,rh)==InpRangeBars &&
                    CopyLow(_Symbol,InpRangeTF,0,InpRangeBars,rl)==InpRangeBars);
    if(haveRange)
      {
       rHi=rh[0]; rLo=rl[0];
       for(int i=1;i<InpRangeBars;i++)
         { if(rh[i]>rHi) rHi=rh[i]; if(rl[i]<rLo) rLo=rl[i]; }
      }
    double pd=0.5, mid=ref;
    if(haveRange && rHi>rLo) { pd=(ref-rLo)/(rHi-rLo); mid=(rHi+rLo)/2.0; }

    //--- Asia range today
    double aHi=0, aLo=0;
    bool haveA=false;
    for(int i=1;i<rates_total;i++)
      {
       if(DayStart(t[i])!=today) break;
       MqlDateTime s;
       TimeToStruct(t[i],s);
       if(!InWin(s.hour,InpAsiaStart,InpAsiaEnd)) continue;
       if(!haveA) { aHi=h[i]; aLo=l[i]; haveA=true; }
       else { if(h[i]>aHi) aHi=h[i]; if(l[i]<aLo) aLo=l[i]; }
      }

    //--- sweeps / displacement / NY spike state for today
    bool swH=false, swL=false, dispUp=false, dispDn=false;
    bool lonDispUp=false, lonDispDn=false, lonSwH=false, lonSwL=false;
    bool nyUp=false, nyDn=false;
    int judasDir=0;
    datetime judasT=0;
    double judasPx=0;
    double a=atr[1];
    if(a<=0) a=pip*100.0;
    for(int i=rates_total-1;i>=1;i--)
      {
       if(DayStart(t[i])!=today) continue;
       MqlDateTime s;
       TimeToStruct(t[i],s);
       bool asia=InWin(s.hour,InpAsiaStart,InpAsiaEnd);
       bool lon =InWin(s.hour,InpLondonStart,InpLondonEnd);
       bool ny  =InWin(s.hour,InpNYStart,InpNYEnd);
       double body=MathAbs(c[i]-o[i]);
       bool disp=(atr[i]>0 && body>InpDispMult*atr[i]);
       if(haveA && !asia)
         {
          if(h[i]>aHi && c[i]<aHi) { swH=true; if(lon) lonSwH=true; }
          if(l[i]<aLo && c[i]>aLo) { swL=true; if(lon) lonSwL=true; }
          if(disp && c[i]>o[i] && c[i]>aHi) { dispUp=true; if(lon) lonDispUp=true; if(ny) nyUp=true; }
          if(disp && c[i]<o[i] && c[i]<aLo) { dispDn=true; if(lon) lonDispDn=true; if(ny) nyDn=true; }
         }
       //--- Judas: NY spike beyond Asia extreme, big wick, return <=3 bars
       if(haveA && ny && judasDir==0)
         {
          double rg=h[i]-l[i];
          if(rg>0 && h[i]>aHi+InpJudasATR*a &&
             (h[i]-MathMax(o[i],c[i]))>=InpJudasWickPct/100.0*rg)
            {
             for(int k2=i-1;k2>=MathMax(i-InpJudasBack,1);k2--)
                if(c[k2]<aHi) { judasDir=-1; judasT=t[i]; judasPx=h[i]; break; }
            }
          if(judasDir==0 && rg>0 && l[i]<aLo-InpJudasATR*a &&
             (MathMin(o[i],c[i])-l[i])>=InpJudasWickPct/100.0*rg)
            {
             for(int k3=i-1;k3>=MathMax(i-InpJudasBack,1);k3--)
                if(c[k3]>aLo) { judasDir=+1; judasT=t[i]; judasPx=l[i]; break; }
            }
         }
      }
    //--- day range for S&D
    double dHi=0, dLo=0;
    bool haveD=false;
    for(int i=1;i<rates_total;i++)
      {
       if(DayStart(t[i])!=today) break;
       if(!haveD) { dHi=h[i]; dLo=l[i]; haveD=true; }
       else { if(h[i]>dHi) dHi=h[i]; if(l[i]<dLo) dLo=l[i]; }
      }
    bool noDispClose=true;
    if(haveA)
      {
       for(int i=rates_total-1;i>=1;i--)
         {
          if(DayStart(t[i])!=today) continue;
          if(atr[i]<=0) continue;
          double body=MathAbs(c[i]-o[i]);
          if(body>InpDispMult*atr[i] && (c[i]>aHi || c[i]<aLo)) { noDispClose=false; break; }
         }
      }
    bool seekD=(haveD && atrD1>0 && (dHi-dLo)<InpSDRangeATR*atrD1 && swH && swL && noDispClose);

    //--- ERL swept flags (HTF extremes = range bounds)
    bool erlHighSwept=(haveRange && swH);
    bool erlLowSwept=(haveRange && swL);

    //--- bias
    int bias=0;   // +1 long, -1 short
    double target=0;
    string why="";
    if(haveRange)
      {
       bool prem=(pd>0.5+InpEQBand), disc=(pd<0.5-InpEQBand);
       if(disc) { bias=+1; target=rHi; why="discount->BSL"; }
       else if(prem) { bias=-1; target=rLo; why="premium->SSL"; }
       else { why="equilibrium-wait M"; }
       if(prem && erlHighSwept) { bias=+1; target=rHi; why="premium swept->reversal long"; }
       if(disc && erlLowSwept) { bias=-1; target=rLo; why="discount swept->reversal short"; }
      }
    //--- premium BOS trap label (informational via tooltip)
    bool trapShort=(haveRange && pd>0.5+InpEQBand && !erlHighSwept);

    //--- profile
    string prof="UNDEFINED";
    if(seekD) prof="P5 S&D (EQ-only half)";
    else if(judasDir!=0) prof=(judasDir<0?"P3 JUDAS fade SHORT":"P3 JUDAS fade LONG");
    else if((lonDispUp && nyUp)||(lonDispDn && nyDn)) prof="P1 TREND (London D + NY cont)";
    else if((lonSwH && nyDn)||(lonSwL && nyUp)) prof="P2 NY REVERSAL";

    color bc=(bias>0?InpLongColor:(bias<0?InpShortColor:InpNoneColor));
    string biasTx=(bias>0?StringFormat("BIAS LONG -> %s (%s)",DoubleToString(target,_Digits),why):
                   bias<0?StringFormat("BIAS SHORT -> %s (%s)",DoubleToString(target,_Digits),why):
                   StringFormat("BIAS NONE (%s)",why));
    ObjectCreate(0,InpPrefix+"bias",OBJ_LABEL,0,0,0);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_CORNER,CORNER_LEFT_UPPER);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_XDISTANCE,10);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_YDISTANCE,20);
    ObjectSetString(0,InpPrefix+"bias",OBJPROP_TEXT,biasTx);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_COLOR,bc);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_FONTSIZE,10);
    ObjectSetInteger(0,InpPrefix+"bias",OBJPROP_SELECTABLE,false);
    ObjectSetString(0,InpPrefix+"bias",OBJPROP_TOOLTIP,
       StringFormat("PD %.2f EQ %s | ERL swept H:%d L:%d%s",pd,
          DoubleToString(mid,_Digits),(erlHighSwept?1:0),(erlLowSwept?1:0),
          trapShort?" | premium BOS = trap unless swept":""));

    ObjectCreate(0,InpPrefix+"prof",OBJ_LABEL,0,0,0);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_CORNER,CORNER_LEFT_UPPER);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_XDISTANCE,10);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_YDISTANCE,40);
    ObjectSetString(0,InpPrefix+"prof",OBJPROP_TEXT,prof);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_COLOR,bc);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_FONTSIZE,10);
    ObjectSetInteger(0,InpPrefix+"prof",OBJPROP_SELECTABLE,false);

    if(InpShowTarget && bias!=0 && target>0)
      {
       ObjectCreate(0,InpPrefix+"tgt",OBJ_TREND,0,t[1],target,t[0],target);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_COLOR,InpTargetColor);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_STYLE,STYLE_DASH);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_WIDTH,2);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_BACK,true);
       ObjectSetInteger(0,InpPrefix+"tgt",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,InpPrefix+"tgt",OBJPROP_TOOLTIP,
          StringFormat("Bias target pool %s",DoubleToString(target,_Digits)));
      }
    if(judasDir!=0)
      {
       ObjectCreate(0,InpPrefix+"jud",(judasDir<0?OBJ_ARROW_DOWN:OBJ_ARROW_UP),0,
                    judasT,judasPx);
       ObjectSetInteger(0,InpPrefix+"jud",OBJPROP_COLOR,
          (judasDir<0?InpShortColor:InpLongColor));
       ObjectSetInteger(0,InpPrefix+"jud",OBJPROP_WIDTH,2);
       ObjectSetInteger(0,InpPrefix+"jud",OBJPROP_BACK,false);
       ObjectSetInteger(0,InpPrefix+"jud",OBJPROP_SELECTABLE,true);
       ObjectSetString(0,InpPrefix+"jud",OBJPROP_TOOLTIP,"Judas spike - fade it");
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
