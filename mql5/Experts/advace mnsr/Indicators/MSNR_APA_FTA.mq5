//+------------------------------------------------------------------+
//|                                                MSNR_APA_FTA.mq5  |
//|              APA Indicator 4: opposing HTF trouble areas           |
//+------------------------------------------------------------------+
//| Rules (APA Part 5 §2):                                             |
//|  Higher TFs carry more powerful liquidity - never trade a setup    |
//|  blindly into an opposing HTF zone. This indicator projects the   |
//|  nearest HTF 2-candle S/R levels (I1 parity, read via CopyRates)   |
//|  above (supply FTA) and below (demand FTA) current price as        |
//|  shaded bands, each with a live RR readout vs the APA risk unit.   |
//|  The EA consumes these for partials / breakeven / skip decisions;  |
//|  a price-inside-band tag marks immediate caution.                  |
//|                                                                    |
//|  Rendering: pure marker - shaded bands (E5 premium/discount hues:  |
//|  supply = sells-side rose, demand = buys-side mint), TF tags with  |
//|  distance + R-multiple. Closed bars only. No rays.                 |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.10"
#property indicator_chart_window
#property indicator_plots 0

//--- inputs
input ENUM_TIMEFRAMES InpHTF1     = PERIOD_H4;         // Higher TF 1
input ENUM_TIMEFRAMES InpHTF2     = PERIOD_D1;         // Higher TF 2
input int    InpHTFBars           = 200;               // Bars copied per HTF
input int    InpPerSide           = 3;                 // Nearest bands per side per TF
input double InpBandPips          = 5.0;               // Band half-width (pips)
input double InpMinDistPips       = 5.0;               // Ignore levels closer than this (pips)
input double InpRiskPips          = 10.0;              // APA risk unit for R-multiple
input bool   InpShowLabels        = true;              // Show FTA tags
input color  InpSupplyColor       = clrMistyRose;      // Supply FTA shade (rose)
input color  InpDemandColor       = clrHoneydew;       // Demand FTA shade (mint)
input color  InpSupplyTxt         = clrTomato;         // Supply label
input color  InpDemandTxt         = clrSeaGreen;       // Demand label
input string InpPrefix            = "MSNR_FTA_";       // Object name prefix

struct SFTA
   {
    double   price;
    datetime t1;
    string   tf;
    bool     supply;      // true = above price (trouble for longs)
    double   distPips;
    double   rMult;
    bool     inside;
   };

struct STmpLvl
   {
    double   px;
    datetime tm;
   };

//+------------------------------------------------------------------+
int OnInit()
   {
    IndicatorSetString(INDICATOR_SHORTNAME,"MSNR FTA");
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

    if(rates_total<5) return(0);

    static datetime last_bar_time=0;
    bool new_bar=(time[0]!=last_bar_time);
    if(prev_calculated!=0 && !new_bar) return(rates_total);
    last_bar_time=time[0];

    SFTA fta[];
    FindFTA(close[1],fta);

    DrawFTA(fta,time[0]);
    ChartRedraw();
    return(rates_total);
   }

string TFName(ENUM_TIMEFRAMES tf)
   {
    switch(tf)
      {
       case PERIOD_M1:  return("M1");
       case PERIOD_M2:  return("M2");
       case PERIOD_M3:  return("M3");
       case PERIOD_M4:  return("M4");
       case PERIOD_M5:  return("M5");
       case PERIOD_M6:  return("M6");
       case PERIOD_M10: return("M10");
       case PERIOD_M12: return("M12");
       case PERIOD_M15: return("M15");
       case PERIOD_M20: return("M20");
       case PERIOD_M30: return("M30");
       case PERIOD_H1:  return("H1");
       case PERIOD_H2:  return("H2");
       case PERIOD_H3:  return("H3");
       case PERIOD_H4:  return("H4");
       case PERIOD_H6:  return("H6");
       case PERIOD_H8:  return("H8");
       case PERIOD_H12: return("H12");
       case PERIOD_D1:  return("D1");
       case PERIOD_W1:  return("W1");
       case PERIOD_MN1: return("MN1");
       default:         return(EnumToString(tf));
      }
   }

//--- 2-candle levels on one HTF (I1 parity on HTF closes)
//    (pip = symbol pip size; distances compared in pips)
void ScanTF(ENUM_TIMEFRAMES tf,double ref,double pip,SFTA &fta[])
   {
    MqlRates r[];
    int got=CopyRates(_Symbol,tf,0,InpHTFBars,r);
    if(got<5) return;
    ArraySetAsSeries(r,true);
    string tag=TFName(tf);
    STmpLvl lv[];
    for(int i=got-2;i>=1;i--)
      {
       bool bu1=(r[i+1].close>r[i+1].open), be1=(r[i+1].close<r[i+1].open);
       bool bu2=(r[i].close>r[i].open),     be2=(r[i].close<r[i].open);
       if((be1&&bu2)||(bu1&&be2))
         {
          int n=ArraySize(lv);
          ArrayResize(lv,n+1);
          lv[n].px=r[i+1].close; lv[n].tm=r[i].time;
         }
      }
    //--- nearest above / below ref
    for(int side=0;side<2;side++)
      {
       bool wantAbove=(side==0);
       int took=0;
       //--- simple selection: walk levels, keep closest-first via insertion
       int order[];
       ArrayResize(order,ArraySize(lv));
       for(int i=0;i<ArraySize(lv);i++) order[i]=i;
       for(int a=1;a<ArraySize(order);a++)
         {
          int v=order[a], j=a-1;
          while(j>=0 && MathAbs(lv[order[j]].px-ref)>MathAbs(lv[v].px-ref))
            { order[j+1]=order[j]; j--; }
          order[j+1]=v;
         }
       for(int a=0;a<ArraySize(order) && took<InpPerSide;a++)
         {
          double px=lv[order[a]].px;
          bool above=(px>ref);
          if(above!=wantAbove) continue;
           double dist=MathAbs(px-ref)/pip;
           if(dist<InpMinDistPips) continue;   // both in pips
          SFTA x;
          x.price=px; x.t1=lv[order[a]].tm; x.tf=tag;
          x.supply=above; x.distPips=dist;
           x.rMult=(InpRiskPips>0?dist/InpRiskPips:0.0);
           x.inside=(dist<=InpBandPips);   // both in pips
          int n=ArraySize(fta);
          ArrayResize(fta,n+1); fta[n]=x;
          took++;
         }
      }
   }

void FindFTA(double ref,SFTA &fta[])
   {
    ArrayResize(fta,0);
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    ScanTF(InpHTF1,ref,pip,fta);
    if(InpHTF2!=InpHTF1)
        ScanTF(InpHTF2,ref,pip,fta);
   }

void DrawFTA(const SFTA &fta[],datetime now)
   {
    double pip=((_Digits==3||_Digits==5)?10.0*_Point:_Point);
    double band=InpBandPips*pip;
    DeleteAllObjects();
    for(int k=0;k<ArraySize(fta);k++)
      {
       if(now<=fta[k].t1) continue;
       string nm=InpPrefix+fta[k].tf+"_"+(fta[k].supply?"sup_":"dem_")+
                 DoubleToString(fta[k].price,_Digits);
       color shade=(fta[k].supply?InpSupplyColor:InpDemandColor);
       color txt=(fta[k].supply?InpSupplyTxt:InpDemandTxt);
       ObjectCreate(0,nm,OBJ_RECTANGLE,0,fta[k].t1,fta[k].price+band,now,fta[k].price-band);
       ObjectSetInteger(0,nm,OBJPROP_COLOR,shade);
       ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_SOLID);
       ObjectSetInteger(0,nm,OBJPROP_WIDTH,1);
       ObjectSetInteger(0,nm,OBJPROP_FILL,true);
       ObjectSetInteger(0,nm,OBJPROP_BACK,true);
       ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,true);
       ObjectSetString(0,nm,OBJPROP_TOOLTIP,
          StringFormat("FTA %s %s %s | band [%s..%s] | %.1f pips = %.1fR%s",
             fta[k].tf,(fta[k].supply?"SUPPLY (trouble for longs)":"DEMAND (trouble for shorts)"),
             DoubleToString(fta[k].price,_Digits),
             DoubleToString(fta[k].price+band,_Digits),
             DoubleToString(fta[k].price-band,_Digits),
             fta[k].distPips,fta[k].rMult,
             fta[k].inside?" | PRICE INSIDE - caution":""));
       if(InpShowLabels)
         {
          string ln=nm+"_lbl";
          ObjectCreate(0,ln,OBJ_TEXT,0,fta[k].t1,fta[k].price+band);
          ObjectSetString(0,ln,OBJPROP_TEXT,
             StringFormat("FTA %s-%s %.0fp %.1fR%s",fta[k].tf,
                (fta[k].supply?"SUP":"DEM"),fta[k].distPips,fta[k].rMult,
                (fta[k].inside?" IN":"")));
          ObjectSetInteger(0,ln,OBJPROP_COLOR,txt);
          ObjectSetInteger(0,ln,OBJPROP_FONTSIZE,8);
          ObjectSetInteger(0,ln,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
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
