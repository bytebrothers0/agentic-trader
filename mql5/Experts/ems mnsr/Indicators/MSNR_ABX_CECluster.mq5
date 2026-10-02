//+------------------------------------------------------------------+
//|                                            MSNR_ABX_CECluster.mq5 |
//|              ABAX Indicator B1: candle CE + mids magnet            |
//+------------------------------------------------------------------+
//| Rules (ABAX P07):                                                  |
//|  CE = (H+L)/2 with wicks on displacement/engulf/BOS candles only  |
//|  (range>0.8 ATR, body>0.6 range, body>0.6 ATR; Asia needs 2 ATR).  |
//|  OBmid = origin-candle BODY mid (P01 body rule). FVGmid from an    |
//|  E6-shape gap scan. Cluster = [min..max] of mids within 0.2 ATR   |
//|  -> MAGNET (preferred limit zone); single CE scores half.         |
//|  Control: bull CE holds while closes stay above; a displacement   |
//|  body close beyond = loss of control (line ends). Weak opposite   |
//|  closes count as crosses; 3 crosses in 20 bars = chopped -> fair   |
//|  value, dead. Wick pokes never break (hold + entry signal).       |
//|                                                                    |
//|  Rendering: CE lines + magnet boxes, MAGNET/CE/chopped labels.    |
//|  Most-recent cap. Closed bars only. No rays.                       |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input int    InpLookbackBars  = 500;               // Lookback bars
input int    InpPivotStrength = 2;                // Pivot strength (BOS check)
input int    InpATRPeriod     = 14;                // ATR period
input double InpBodyRangePct  = 60.0;              // Min body % of range
input double InpMinRangeATR   = 0.8;               // Min range (x ATR)
input double InpMinBodyATR    = 0.6;               // Min body (x ATR)
input double InpAsiaBodyATR   = 2.0;               // Asia qualifier (x ATR)
input double InpClusterATR    = 0.2;               // Cluster tolerance (x ATR)
input int    InpChopBars      = 20;                // Chop window (bars)
input int    InpMaxCross      = 3;                 // Crosses before chopped
input int    InpAsiaEnd       = 7;                 // Asia ends (server hour)
input int    InpMaxCE         = 30;                // Max CEs drawn (most recent)
input bool   InpShowLabels    = true;              // Show labels
input color  InpBullColor     = clrDodgerBlue;     // Bull CE
input color  InpBearColor     = clrTomato;         // Bear CE
input color  InpMagnetColor   = clrOrange;         // Magnet box (amber)
input color  InpDeadColor     = clrGray;           // Chopped/broken CE
input string InpPrefix        = "MSNR_CEC_";       // Object name prefix

int hATR=INVALID_HANDLE;

struct SCE
   {
    datetime t1;
    double   ce;
    bool     bull;
    datetime tEnd;       // loss-of-control bar, 0 = holding
    bool     chopped;
    double   cTop;       // cluster zone
    double   cBot;
    bool     magnet;
    int      sess;       // 0 Asia, 1 other
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR CE Cluster");
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

    if(rates_total<2*InpPivotStrength+InpATRPeriod+3) return(0);
    if(BarsCalculated(hATR)<rates_total) return(0);
    double atr[];
    ArraySetAsSeries(atr,true);
    if(CopyBuffer(hATR,0,0,rates_total,atr)!=rates_total) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SCE ce[];
    FindCEs(time,open,high,low,close,atr,rates_total,ce);

    DrawCEs(ce,time[0]);
    ChartRedraw();
    return(rates_total);
   }

//--- BOS-bar map (first break, either direction) for the displacement gate
void BOSMap(const datetime &t[],const double &o[],const double &c[],
            int rates_total,int maxScan,bool &bos[])
   {
    ArrayResize(bos,maxScan+1); ArrayInitialize(bos,false);
    int scan=MathMin(InpLookbackBars,rates_total-2);
    for(int i=scan;i>=1;i--)
      {
       bool bull1=IsBullC(o,c,i+1), bear1=IsBearC(o,c,i+1);
       bool bull2=IsBullC(o,c,i),   bear2=IsBearC(o,c,i);
       bool sup=(bear1&&bull2), res=(bull1&&bear2);
       if(!sup&&!res) continue;
       double px=c[i+1];
       for(int j=i-1;j>=1;j--)
         {
          if(sup && c[j]<px) { if(j<=maxScan) bos[j]=true; break; }
          if(!sup && c[j]>px) { if(j<=maxScan) bos[j]=true; break; }
         }
      }
   }

void FindCEs(const datetime &t[],const double &o[],const double &h[],
             const double &l[],const double &c[],const double &atr[],
             int rates_total,SCE &ce[])
   {
    ArrayResize(ce,0);
    int maxScan=MathMin(InpLookbackBars,rates_total-3);
    bool bos[];
    BOSMap(t,o,c,rates_total,maxScan,bos);

    //--- FVG mids (E6 shape)
    double fvgMid[];
    ArrayResize(fvgMid,0);
    for(int j=maxScan;j>=1;j--)
      {
       if(l[j]>h[j+2]) { int n=ArraySize(fvgMid); ArrayResize(fvgMid,n+1); fvgMid[n]=(l[j]+h[j+2])/2.0; }
       if(h[j]<l[j+2]) { int n2=ArraySize(fvgMid); ArrayResize(fvgMid,n2+1); fvgMid[n2]=(h[j]+l[j+2])/2.0; }
      }

    for(int i=maxScan;i>=1;i--)
      {
       if(atr[i]<=0) continue;
       double range=h[i]-l[i], body=MathAbs(c[i]-o[i]);
       if(range<InpMinRangeATR*atr[i]) continue;
       if(body<InpBodyRangePct/100.0*range) continue;
       if(body<InpMinBodyATR*atr[i]) continue;
       bool bull=IsBullC(o,c,i), bear=IsBearC(o,c,i);
       if(!bull && !bear) continue;
       //--- displacement / engulf / BOS gate
       bool disp=(body>=1.5*atr[i]);
       bool engulf=false;
       if(bull && IsBearC(o,c,i+1) && c[i]>o[i+1]) engulf=true;
       if(bear && IsBullC(o,c,i+1) && c[i]<o[i+1]) engulf=true;
       if(!disp && !engulf && !bos[i]) continue;
       //--- Asia derate: needs bigger body
       MqlDateTime dt;
       TimeToStruct(t[i],dt);
       int sess=(dt.hour<InpAsiaEnd?0:1);
       if(sess==0 && body<InpAsiaBodyATR*atr[i]) continue;
       double mid=(h[i]+l[i])/2.0;
       //--- OBmid: last opposite body mid within 5 bars
       double obmid=0;
       for(int q=i+1;q<=MathMin(i+5,rates_total-1);q++)
         {
          if(bull && IsBearC(o,c,q)) { obmid=(o[q]+c[q])/2.0; break; }
          if(bear && IsBullC(o,c,q)) { obmid=(o[q]+c[q])/2.0; break; }
         }
       double tol=InpClusterATR*atr[i];
       double cTop=mid, cBot=mid;
       int members=1;
       if(obmid>0 && MathAbs(obmid-mid)<=tol)
         { if(obmid>cTop) cTop=obmid; if(obmid<cBot) cBot=obmid; members++; }
       for(int q=0;q<ArraySize(fvgMid);q++)
          if(MathAbs(fvgMid[q]-mid)<=tol)
            { if(fvgMid[q]>cTop) cTop=fvgMid[q]; if(fvgMid[q]<cBot) cBot=fvgMid[q]; members++; }
       SCE x;
       x.t1=t[i]; x.ce=mid; x.bull=bull; x.tEnd=0; x.chopped=false;
       x.cTop=cTop; x.cBot=cBot; x.magnet=(members>=2); x.sess=sess;
       //--- control walk: displacement close beyond ends the line;
       //--- weak opposite closes inside the chop window count toward chop
       int crosses=0;
       int winEnd=MathMax(i-InpChopBars,1);
       for(int j=i-1;j>=1;j--)
         {
          bool beyond=(bull?c[j]<mid:c[j]>mid);
          if(!beyond) continue;
          if(MathAbs(c[j]-o[j])>=atr[j] && atr[j]>0) { x.tEnd=t[j]; break; }
          if(j>=winEnd)
            {
             crosses++;
             if(crosses>=InpMaxCross) { x.chopped=true; x.tEnd=t[j]; break; }
            }
         }
       int n=ArraySize(ce);
       ArrayResize(ce,n+1); ce[n]=x;
      }
   }

void DrawCEs(const SCE &ce[],datetime now)
   {
    DeleteAllObjects();
    int n=ArraySize(ce);
    int start=(n>InpMaxCE)?n-InpMaxCE:0;
    for(int k=start;k<n;k++)
      {
       bool dead=(ce[k].tEnd!=0);
       datetime t2=(dead?ce[k].tEnd:now);
       if(t2<=ce[k].t1) continue;
       string nm=InpPrefix+(ce[k].bull?"bull_":"bear_")+
                 TimeToString(ce[k].t1,TIME_DATE|TIME_MINUTES)+"_"+IntegerToString(k);
       color lc=(dead?InpDeadColor:(ce[k].bull?InpBullColor:InpBearColor));
       ObjectCreate(0,nm,OBJ_TREND,0,ce[k].t1,ce[k].ce,t2,ce[k].ce);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,lc);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,(dead?STYLE_DOT:STYLE_SOLID));
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_RAY_RIGHT,false);
       ObjectSetInteger(0,nm,OBJPROP_BACK,false);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("CE %s %s%s | formed %s -> %s%s",
             ce[k].bull?"bull":"bear",DoubleToString(ce[k].ce,_Digits),
             ce[k].sess==0?" (Asia-derated)":"",
             TimeToString(ce[k].t1),TimeToString(t2),
             dead?(ce[k].chopped?" | CHOPPED->fair":" | control lost"):" | HOLDING"));
       if(ce[k].magnet && ce[k].cTop>ce[k].cBot)
         {
          ObjectCreate(0,nm+"_mg",OBJ_RECTANGLE,0,ce[k].t1,ce[k].cTop,t2,ce[k].cBot);
          ObjectSetInteger(0,nm+"_mg",OBJPROP_COLOR,(dead?InpDeadColor:InpMagnetColor));
          ObjectSetInteger(0,nm+"_mg",OBJPROP_STYLE,STYLE_SOLID);
          ObjectSetInteger(0,nm+"_mg",OBJPROP_WIDTH,1);
          ObjectSetInteger(0,nm+"_mg",OBJPROP_FILL,true);
          ObjectSetInteger(0,nm+"_mg",OBJPROP_BACK,true);
          ObjectSetInteger(0,nm+"_mg",OBJPROP_SELECTABLE,true);
          ObjectSetString(0,nm+"_mg",OBJPROP_TOOLTIP,"CE magnet cluster (CE+OBmid+FVGmid)");
         }
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,ce[k].t1,ce[k].ce);
          string txt=(ce[k].magnet?"MAGNET":(dead&&ce[k].chopped?"chop":"CE"));
          ObjectSetString(0,ln,OBJPROP_TEXT,txt);
          ObjectSetInteger(0,ln,OBJPROP_COLOR,(ce[k].magnet&&!dead?InpMagnetColor:lc));
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,
             (ce[k].bull?ANCHOR_LEFT_UPPER:ANCHOR_LEFT_LOWER));
          ObjectSetInteger(0,ln,OBJPROP_BACK,true);
          ObjectSetInteger(0,ln,OBJPROP_SELECTABLE,false);
         }
      }
   }

void DeleteAllObjects()
   {
    ObjectsDeleteAll(0,InpPrefix,-1,-1);
   }
//+------------------------------------------------------------------+
