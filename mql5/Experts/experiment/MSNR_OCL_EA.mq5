//+------------------------------------------------------------------+
//|                                                 MSNR_OCL_EA.mq5  |
//|      EA around MSNR OCL: fresh-OCL dip-reclaim stop-limit         |
//+------------------------------------------------------------------+
//| Logic:                                                            |
//|  - Only trades new/recent OCLs (last N formed, priority newest).  |
//|  - OCL = two consecutive same-color candles, level = close of     |
//|    FIRST candle (copied from MSNR_OCL.mq5 indicator).             |
//|  - Bullish OCL -> BUY side, bearish OCL -> SELL side.              |
//|  - Entry modes: STOP_LIMIT_RECLAIM (stop above/below OCL) or       |
//|    LIMIT_EXACT (limit placed exactly at OCL level = buys the dip). |
//|  - SL/TP modes: FIXED pips or CANDLE2_WICK (trade candle 2 range:  |
//|    BUY: SL=c2 low-buffer, TP=c2 high | SELL: mirror).               |
//|  - Fixed SL/TP in pips from fill area, fixed lot size.            |
//|  - One pending per OCL (tracked by formed_time+price key).        |
//|  - Pending expires after X bars if not filled.                    |
//+------------------------------------------------------------------+
#property copyright "MSNR Project"
#property version   "1.01"

#include <Trade\Trade.mqh>
CTrade g_trade;

//--- SL/TP + entry modes
enum ENUM_OCL_SLTP
  {
   SLTP_FIXED_PIPS   = 0, // Fixed SL/TP in pips
   SLTP_CANDLE2_WICK = 1  // Auto: SL/TP at candle-2 wicks (trade candle 2 range)
  };
enum ENUM_OCL_ENTRY
  {
   ENTRY_STOP_LIMIT_RECLAIM = 0, // Stop-limit beyond OCL (dip + reclaim confirmation)
   ENTRY_LIMIT_EXACT        = 1  // Limit exactly at OCL level (buy/sell the dip)
  };

//--- inputs
input double InpLots              = 0.10;   // Lot size
input ENUM_OCL_SLTP InpSLTPMode   = SLTP_FIXED_PIPS; // SL/TP mode
input int    InpTP_Pips           = 50;     // Take profit (pips) - FIXED mode only
input int    InpSL_Pips           = 35;     // Stop loss (pips) - FIXED mode only
input double InpWickBufferPips    = 2.0;    // Wick buffer beyond SL wick (pips) - WICK mode
input ENUM_OCL_ENTRY InpEntryMode = ENTRY_STOP_LIMIT_RECLAIM; // Entry order type
input int    InpMaxRecentOCLs     = 3;      // How many recent OCLs to consider
input double InpTriggerOffsetPips = 2.0;    // Stop trigger beyond OCL (pips) - reclaim confirmation
input double InpLimitGapPips      = 3.0;    // Limit beyond stop (pips) - slippage cap
input int    InpPendingExpiryBars = 4;      // Delete pending if not filled after N bars (0=never)
input bool   InpSkipEngulfing     = true;   // Skip body-engulfing OCLs (per spec: NOT traded)
input bool   InpTradeBullish      = true;   // Trade bullish OCL (buy)
input bool   InpTradeBearish      = true;   // Trade bearish OCL (sell)
input bool   InpOnePositionOnly   = true;   // Only 1 position/pending at a time
input int    InpSlippagePoints    = 10;     // Slippage (points)
input int    InpMagic             = 20261013; // Magic number
input int    InpScanBars          = 30;     // Bars scanned to classify + find recent OCLs

//--- OCL candidate (candle1 = first of pair, candle2 = second/trigger bar)
struct SOCL
  {
   double   price;        // OCL level = close of candle 1
   datetime formed_time;  // time of candle 2
   bool     bullish;
   double   c2_high;      // candle-2 high wick
   double   c2_low;       // candle-2 low wick
  };

string g_traded_keys[]; // keys traded this session (formed_time+price)

//+------------------------------------------------------------------+
int OnInit()
  {
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetAsyncMode(false);

//--- validate lots
   double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double vstep=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(InpLots<vmin || InpLots>vmax)
     {
      PrintFormat("Invalid lots %.2f (min %.2f max %.2f). Fix input.",InpLots,vmin,vmax);
      return(INIT_PARAMETERS_INCORRECT);
     }
//--- filling mode: let CTrade auto-detect; force a safe default
   g_trade.SetTypeFillingBySymbol(_Symbol);
   PrintFormat("MSNR_OCL_EA started: lots=%.2f SLTPmode=%d EntryMode=%d TP=%d SL=%d trigger=%.1f limitGap=%.1f wickBuf=%.1f recent=%d",
               InpLots,InpSLTPMode,InpEntryMode,InpTP_Pips,InpSL_Pips,InpTriggerOffsetPips,InpLimitGapPips,InpWickBufferPips,InpMaxRecentOCLs);
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
double PipSize()
  {
//--- 3/5 digit forex: 1 pip = 10 points. 2/4 digit: 1 pip = 1 point.
//--- NOTE for XAUUSD (2 digits) 50 pips = 5.00 price move. Adjust inputs if needed.
   if(_Digits==3 || _Digits==5)
      return(_Point*10.0);
   return(_Point);
  }
//+------------------------------------------------------------------+
string OCLKey(datetime t,double p)
  {
   return(TimeToString(t,TIME_DATE|TIME_MINUTES)+"|"+DoubleToString(p,_Digits));
  }
//+------------------------------------------------------------------+
bool IsTradedThisSession(const string key)
  {
   for(int i=0;i<ArraySize(g_traded_keys);i++)
      if(g_traded_keys[i]==key)
         return(true);
   return(false);
  }
//+------------------------------------------------------------------+
void MarkTraded(const string key)
  {
   if(IsTradedThisSession(key))
      return;
   int n=ArraySize(g_traded_keys);
   ArrayResize(g_traded_keys,n+1);
   g_traded_keys[n]=key;
  }
//+------------------------------------------------------------------+
bool HasLiveOrderOrPosition(const string key)
  {
//--- pending orders
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0)
         continue;
      if(OrderGetString(ORDER_SYMBOL)!=_Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC)!=InpMagic)
         continue;
      string cmt=OrderGetString(ORDER_COMMENT);
      if(StringFind(cmt,key)>=0)
         return(true);
     }
//--- open positions
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic)
         continue;
      string cmt=PositionGetString(POSITION_COMMENT);
      if(StringFind(cmt,key)>=0)
         return(true);
     }
   return(false);
  }
//+------------------------------------------------------------------+
bool HasAnyOCLPositionOrPending()
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0)
         continue;
      if(OrderGetString(ORDER_SYMBOL)!=_Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC)!=InpMagic)
         continue;
      return(true);
     }
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic)
         continue;
      return(true);
     }
   return(false);
  }
//+------------------------------------------------------------------+
bool IsBullBody(const MqlRates &a) { return(a.close>a.open); }
bool IsBearBody(const MqlRates &a) { return(a.close<a.open); }

//+------------------------------------------------------------------+
//| Find recent OCLs, most-recent-first, up to InpMaxRecentOCLs.      |
//| Mirrors MSNR_OCL.mq5 pass-1 (S/R priority + engulfing rule).      |
//+------------------------------------------------------------------+
int FindRecentOCLs(SOCL &out[])
  {
   ArrayResize(out,0);
   MqlRates r[];
   ArraySetAsSeries(r,true);
   int need=InpScanBars+5;
   if(CopyRates(_Symbol,_Period,0,need,r)<need-2)
      return(0);
   int bars=ArraySize(r);
   int scan=MathMin(InpScanBars,bars-3);
   if(scan<3)
      return(0);

//--- chronological scan to respect last-key-level (like indicator)
   SOCL chrono[];
   ArrayResize(chrono,0);
   int last_kl=0; // 0 none, 1 supp, 2 res, 3 ocl

   for(int i=scan;i>=1;i--)
     {
      bool bull1=r[i+1].close>r[i+1].open, bear1=r[i+1].close<r[i+1].open;
      bool bull2=r[i].close>r[i].open,     bear2=r[i].close<r[i].open;

      bool is_support    =(bear1 && bull2);
      bool is_resistance =(bull1 && bear2);

      bool ocl_bull=(bull1 && bull2);
      bool ocl_bear=(bear1 && bear2);
      bool engulfing=false;
      if(ocl_bull)
         engulfing=(r[i].open<=r[i+1].open && r[i].close>=r[i+1].close);
      if(ocl_bear)
         engulfing=(r[i].open>=r[i+1].open && r[i].close<=r[i+1].close);
      if(!InpSkipEngulfing)
         engulfing=false;

      if(is_support)
         last_kl=1;
      else
         if(is_resistance)
            last_kl=2;
         else
            if((ocl_bull||ocl_bear) && !engulfing)
              {
               SOCL lv;
               lv.price       =r[i+1].close; // close of FIRST candle (candle 1)
               lv.formed_time =r[i].time;    // time of SECOND candle (candle 2)
               lv.bullish     =(ocl_bull?true:false);
               lv.c2_high     =r[i].high;    // candle-2 high wick
               lv.c2_low      =r[i].low;     // candle-2 low wick
               int n=ArraySize(chrono);
               ArrayResize(chrono,n+1);
               chrono[n]=lv;
               last_kl=3;
              }
     }

//--- reverse to most-recent-first, cap to MaxRecentOCLs
   int total=ArraySize(chrono);
   int take=MathMin(total,InpMaxRecentOCLs);
   ArrayResize(out,take);
   for(int k=0;k<take;k++)
      out[k]=chrono[total-1-k];
   return(take);
  }
//+------------------------------------------------------------------+
void ExpireOldPendings()
  {
   if(InpPendingExpiryBars<=0)
      return;
   datetime now=TimeTradeServer();
   if(now==0)
      now=TimeCurrent();
   long span=(long)InpPendingExpiryBars*PeriodSeconds(PERIOD_CURRENT);
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0)
         continue;
      if(OrderGetString(ORDER_SYMBOL)!=_Symbol)
         continue;
      if(OrderGetInteger(ORDER_MAGIC)!=InpMagic)
         continue;
      datetime setup=(datetime)OrderGetInteger(ORDER_TIME_SETUP);
      if(setup==0)
         continue;
      if(now-setup>span)
        {
         if(g_trade.OrderDelete(ticket))
            PrintFormat("Expired pending #%I64u deleted (age>%d bars).",ticket,InpPendingExpiryBars);
        }
     }
  }
//+------------------------------------------------------------------+
bool CalcSLTP(const SOCL &ocl,double refEntry,double &sl,double &tp)
  {
//--- FIXED mode: SL/TP measured from refEntry (pending price)
   double pip=PipSize();
   if(InpSLTPMode==SLTP_FIXED_PIPS)
     {
      double slDist=(double)InpSL_Pips*pip;
      double tpDist=(double)InpTP_Pips*pip;
      if(ocl.bullish)
        {
         sl=NormalizeDouble(refEntry-slDist,_Digits);
         tp=NormalizeDouble(refEntry+tpDist,_Digits);
        }
      else
        {
         sl=NormalizeDouble(refEntry+slDist,_Digits);
         tp=NormalizeDouble(refEntry-tpDist,_Digits);
        }
      return(true);
     }
//--- WICK mode: trade candle-2 range.
//--- BUY: SL = c2 low - buffer, TP = c2 high (exact wick).
//--- SELL: SL = c2 high + buffer, TP = c2 low (exact wick).
   double buf=InpWickBufferPips*pip;
   if(ocl.bullish)
     {
      sl=NormalizeDouble(ocl.c2_low-buf,_Digits);
      tp=NormalizeDouble(ocl.c2_high,_Digits);
      //--- sanity: SL below entry below TP, else candle-2 shape unusable
      if(!(sl<refEntry && refEntry<tp))
        {
         PrintFormat("Skip bullish OCL: wick SL/TP invalid (sl=%.5f entry=%.5f tp=%.5f c2H=%.5f c2L=%.5f).",
                     sl,refEntry,tp,ocl.c2_high,ocl.c2_low);
         return(false);
        }
     }
   else
     {
      sl=NormalizeDouble(ocl.c2_high+buf,_Digits);
      tp=NormalizeDouble(ocl.c2_low,_Digits);
      if(!(refEntry<sl && tp<refEntry))
        {
         PrintFormat("Skip bearish OCL: wick SL/TP invalid (tp=%.5f entry=%.5f sl=%.5f c2H=%.5f c2L=%.5f).",
                     tp,refEntry,sl,ocl.c2_high,ocl.c2_low);
         return(false);
        }
     }
   return(true);
  }
//+------------------------------------------------------------------+
bool PlaceOCLPending(const SOCL &ocl)
  {
   double pip=PipSize();
   double stopDist =InpTriggerOffsetPips*pip;
   double limitGap =InpLimitGapPips*pip;

   string key=OCLKey(ocl.formed_time,ocl.price);
   string cmt="OCL|"+key; // survives restart for dup-check

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol,tk))
      return(false);

   bool ok=false;
   double sl=0,tp=0;

// === ENTRY MODE 1: LIMIT placed EXACTLY at OCL level (buy/sell the dip) ===
   if(InpEntryMode==ENTRY_LIMIT_EXACT)
     {
      double entry=NormalizeDouble(ocl.price,_Digits);
      if(!CalcSLTP(ocl,entry,sl,tp))
         return(false);
      if(ocl.bullish)
        {
         //--- BuyLimit must sit below Ask (OCL below market after bullish close)
         if(entry>=tk.ask)
           {
            PrintFormat("Skip bullish OCL %s: exact entry %.5f >= ask %.5f.",key,entry,tk.ask);
            return(false);
           }
         ok=g_trade.BuyLimit(InpLots,entry,_Symbol,sl,tp,ORDER_TIME_GTC,0,cmt);
         if(ok)
            PrintFormat("BUY-LIMIT OCL %s entry=%.5f(exact) sl=%.5f tp=%.5f [c2H=%.5f c2L=%.5f mode=%d]",
                        key,entry,sl,tp,ocl.c2_high,ocl.c2_low,InpSLTPMode);
        }
      else
        {
         if(entry<=tk.bid)
           {
            PrintFormat("Skip bearish OCL %s: exact entry %.5f <= bid %.5f.",key,entry,tk.bid);
            return(false);
           }
         ok=g_trade.SellLimit(InpLots,entry,_Symbol,sl,tp,ORDER_TIME_GTC,0,cmt);
         if(ok)
            PrintFormat("SELL-LIMIT OCL %s entry=%.5f(exact) sl=%.5f tp=%.5f [c2H=%.5f c2L=%.5f mode=%d]",
                        key,entry,sl,tp,ocl.c2_high,ocl.c2_low,InpSLTPMode);
        }
     }
   else
// === ENTRY MODE 0 (default): STOP-LIMIT beyond OCL (dip + reclaim) ===
     {
      if(ocl.bullish)
        {
         //--- trigger above OCL, limit caps slippage above trigger.
         //--- NOTE: entry is NOT the exact OCL; it is OCL+offset by design.
         //--- Set InpTriggerOffsetPips=0 for near-exact, or use LIMIT_EXACT mode.
         double stopPrice =NormalizeDouble(ocl.price+stopDist,_Digits);
         double limitPrice=NormalizeDouble(stopPrice+limitGap,_Digits);
         if(!CalcSLTP(ocl,stopPrice,sl,tp))
            return(false);
         if(stopPrice<=tk.ask)
           {
            PrintFormat("Skip bullish OCL %s: stop %.5f <= ask %.5f (too late).",key,stopPrice,tk.ask);
            return(false);
           }
         ok=g_trade.OrderOpen(_Symbol,ORDER_TYPE_BUY_STOP_LIMIT,InpLots,limitPrice,stopPrice,sl,tp,ORDER_TIME_GTC,0,cmt);
         if(!ok)
           {
            //--- fallback for brokers without stop-limit support
            PrintFormat("BuyStopLimit failed (%d %s), trying BuyStop.",g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
            ok=g_trade.BuyStop(InpLots,stopPrice,_Symbol,sl,tp,ORDER_TIME_GTC,0,cmt);
           }
         if(ok)
            PrintFormat("BUY-STOPLMT OCL %s @%.5f stop=%.5f limit=%.5f sl=%.5f tp=%.5f [c2H=%.5f c2L=%.5f mode=%d]",
                        key,ocl.price,stopPrice,limitPrice,sl,tp,ocl.c2_high,ocl.c2_low,InpSLTPMode);
        }
      else
        {
         double stopPrice =NormalizeDouble(ocl.price-stopDist,_Digits);
         double limitPrice=NormalizeDouble(stopPrice-limitGap,_Digits);
         if(!CalcSLTP(ocl,stopPrice,sl,tp))
            return(false);
         if(stopPrice>=tk.bid)
           {
            PrintFormat("Skip bearish OCL %s: stop %.5f >= bid %.5f (too late).",key,stopPrice,tk.bid);
            return(false);
           }
         ok=g_trade.OrderOpen(_Symbol,ORDER_TYPE_SELL_STOP_LIMIT,InpLots,limitPrice,stopPrice,sl,tp,ORDER_TIME_GTC,0,cmt);
         if(!ok)
           {
            PrintFormat("SellStopLimit failed (%d %s), trying SellStop.",g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
            ok=g_trade.SellStop(InpLots,stopPrice,_Symbol,sl,tp,ORDER_TIME_GTC,0,cmt);
           }
         if(ok)
            PrintFormat("SELL-STOPLMT OCL %s @%.5f stop=%.5f limit=%.5f sl=%.5f tp=%.5f [c2H=%.5f c2L=%.5f mode=%d]",
                        key,ocl.price,stopPrice,limitPrice,sl,tp,ocl.c2_high,ocl.c2_low,InpSLTPMode);
        }
     }

   if(!ok)
      PrintFormat("Order FAILED for OCL %s: %d %s",key,g_trade.ResultRetcode(),g_trade.ResultRetcodeDescription());
   else
      MarkTraded(key);
   return(ok);
  }
//+------------------------------------------------------------------+
void OnTick()
  {
//--- act on new bar only
   static datetime last_bar=0;
   datetime cur_bar=iTime(_Symbol,_Period,0);
   if(cur_bar==last_bar)
      return;
   last_bar=cur_bar;

   ExpireOldPendings();

   if(InpOnePositionOnly && HasAnyOCLPositionOrPending())
      return;

   SOCL recent[];
   int n=FindRecentOCLs(recent);
   if(n==0)
      return;

//--- priority: recent[0] = just-closed OCL, then older within last 3
   for(int k=0;k<n;k++)
     {
      if(recent[k].bullish && !InpTradeBullish)
         continue;
      if(!recent[k].bullish && !InpTradeBearish)
         continue;
      string key=OCLKey(recent[k].formed_time,recent[k].price);
      if(IsTradedThisSession(key))
         continue;
      if(HasLiveOrderOrPosition(key))
        {
         MarkTraded(key);
         continue;
        }
      if(PlaceOCLPending(recent[k]))
         break; // one new pending per bar (keeps priority order)
     }
  }
//+------------------------------------------------------------------+
