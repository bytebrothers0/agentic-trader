#property strict

#include <Trade/Trade.mqh>

// ---------------------------------------------------------------------------
// MSNR Exact Backtest EA v7
// Native MT5 Expert Advisor that mirrors the current Python engine flow:
//   - Multi-timeframe storyline scan
//   - FTFL -> STFL -> TTFL cascade
//   - Model B and Model C confirmation entries
//   - Pending limit orders with spread buffer and fixed SL/TP + lot size inputs
//   - Partial close at obstacle and move SL to break-even
//   - W1/W1 branch toggle and configurable breakeven trigger
//   - Optional trendline and consolidation filters
//   - Optional account protection compounding based on realized profit
//
// This is a native MQL5 port for Strategy Tester use.
//
// ZONE-MAPPING PATCH (indicator logic port — trade flow / risk / management
// untouched). Every hand-rolled detector below now mirrors the exact math of
// the dev-supplied indicators in .\Indicators (object-drawing indicators carry
// no buffers, so their calculation cores are ported 1:1 instead of iCustom):
//   DetectBaseLevels  <- MSNR_Levels_SR v1.00 (2-candle close pivots, close-
//                        through breaks) + MSNR_RoleFlip v1.00 (S->SBR->QM->
//                        DEAD lifecycle) + MSNR_Freshness v1.00 (any wick
//                        straddle = UNFRESH, break re-freshes in new role)
//   DetectOCLLevels   <- MSNR_OCL v1.00 (body-engulf only skip, sequential
//                        last-key-level classes sOCL/rOCL/1LAB, S->R->LS->
//                        DEAD behavior) + MSNR_TFL_Zones v1.10 box geometry
//                        (candle2 wick only, level always contained)
//   DetectQMLevels    <- MSNR_QM_Taxonomy v1.00 (role-lifecycle QM birth,
//                        parent S/R box geometry, Apex-origin match 2.0 pips
//                        confirmed-before-birth, chronological FT/ST) + Apex
//                        engine of MSNR_Apex v1.00 (close pivots strength 3,
//                        alternation, trend BOS walk). Origin match runs on
//                        MN1/W1/D1 only (Apex is HTF-only per Video 3).
//   DetectApexLevels  <- MSNR_Apex v1.00 BOS-walk model (AR/AS external,
//                        iABR/iABS internal, pivot strength 3, D1+ only)
//   Trendline block   <- MSNR_PHX_Trendline v1.02 (wick-fractal pivots
//                        strength 2 alternating, newest 2 pairs/side, time-
//                        based projection, 3.0xATR(14) relevance, TLxLVL
//                        confluence within 3.0 pips of S/R|OCL level)
//   Storyline pair    <- MSNR_Storyline v1.30 (plain S/R only, 2.0 pip tol,
//                        close-only rejection, first-touch-only, close-
//                        through invalidation, every Y first-close BOS,
//                        20-bar lag pairing with persistence)
//   FTFL/STFL/TTFL    <- MSNR_TFL_Zones v1.10 geometry (S/R box = level..
//                        c1/c2 wick tip, QM = parent geometry re-armed at QM
//                        birth, strict A+ containment fresh-in-fresh)
// ---------------------------------------------------------------------------

input string InpSymbol = "";
input long   InpMagic = 888999;
input bool   InpVerbose = true;
input bool   InpTradeClosestOnly = false;
input bool   InpManagePartialProfits = true;
input bool   InpMoveToBreakeven = true;
input bool   InpEnableW1StoryW1Entry = false;
input double InpBreakevenRR = 0.75;
input int    InpBreakevenBufferPoints = 2;
input int    InpMaxDailyLosses = 3;
input bool   InpSkipAsiaSession = false;
input bool   InpUseTrendlineConfluence = true;
input bool   InpTrendlineAllEntries = false;
input int    InpTrendlineTolerancePoints = 40;
input int    InpTrendlineLookbackBars = 160;
input bool   InpUseConsolidationFilter = false;
input int    InpConsolidationLookbackBars = 20;
input double InpConsolidationMaxRangePips = 120.0;
input bool   InpUseAccountProtection = false;
input double InpAccountProtectionStepUsd = 50.0;
input double InpAccountProtectionMaxMultiplier = 5.0;
input bool   InpExportTradeHistory = true;
input bool   InpUseFixedSLTP = true;
input int    InpTimerSeconds = 1;
input int    InpStopLossPips = 300;
input int    InpTakeProfitPips = 1000;
input double InpLotSize = 0.10;
input string InpTradeHistoryFile = "MSNR_trade_history.csv";
// --- Indicator-parity inputs (defaults = indicator defaults) ---
// MSNR_Storyline v1.30
input double InpStoryTolerancePips = 2.0;   // Wick/close tolerance (pips)
input int    InpStoryLookbackX = 150;       // Lookback bars X (rejection leg)
input int    InpStoryLookbackY = 400;       // Lookback bars Y (breakout leg)
input int    InpStoryMaxBosLagBars = 20;    // Max Y bars between rejection and BOS
// MSNR_QM_Taxonomy v1.00
input double InpApexMatchTolerancePips = 2.0; // Apex<->QM match tolerance (pips)
input double InpQMZoneTolerancePips = 2.0;    // FT/ST same-zone tolerance (pips)
// MSNR_PHX_Trendline v1.02 (InpTrendlineLookbackBars reused as pivot scan window;
// InpTrendlineTolerancePoints superseded by Touch/Confl pips below, kept for .set compat)
input int    InpTLPivotStrength = 2;        // Fractal pivot strength (bars each side)
input double InpTLTouchPips = 2.0;          // Touch tolerance (pips)
input double InpTLConflPips = 3.0;          // TL x level confluence tolerance (pips)
input int    InpTLATRPeriod = 14;           // ATR period (relevance filter)
input double InpTLMaxDistATR = 3.0;         // Skip TLs projected farther than this x ATR

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

enum BiasDirection
{
   BIAS_NEUTRAL = 0,
   BIAS_BULLISH = 1,
   BIAS_BEARISH = -1
};

enum LevelType
{
   LT_SUPPORT = 0,
   LT_RESISTANCE = 1,
   LT_SBR = 2,
   LT_RBS = 3
};

enum LevelState
{
   LS_FRESH = 0,
   LS_UNFRESH = 1,
   LS_BROKEN = 2
};

enum OCLType
{
   OCL_STANDARD_BULLISH = 0,
   OCL_STANDARD_BEARISH = 1,
   OCL_SOCL = 2,
   OCL_ROCL = 3,
   OCL_ONE_LAP = 4,
   OCL_LS_OCL = 5
};

enum QMDirection
{
   QM_BULLISH = 0,
   QM_BEARISH = 1
};

enum QMType
{
   QM_ABQM = 0,
   QM_FTQM = 1,
   QM_STQM = 2,
   QM_IABQM = 3
};

enum ApexType
{
   APEX_SUPPORT = 0,
   APEX_RESISTANCE = 1,
   IAB_SUPPORT = 2,
   IAB_RESISTANCE = 3
};

enum TTFLEntryType
{
   ENTRY_KEY_LEVEL = 0,
   ENTRY_EQUILIBRIUM = 1
};

struct CandleLevel
{
   int      levelType;
   double   price;
   int      candleIndex;
   datetime candleTime;
   int      state;
   int      derivedFromIndex;
   int      firstTouchIndex;
   int      breakCandleIndex;
};

struct OCLLevel
{
   int      oclType;
   double   price;
   int      candleIndex1;
   int      candleIndex2;
   datetime candleTime;
   int      state;
   double   boxHigh;
   double   boxLow;
   int      firstTouchIndex;
   int      breakCount;
};

struct QMLevel
{
   int      qmType;
   int      direction;
   double   price;
   int      originIndex;
   int      flipIndex;
   int      breakIndex;
   datetime candleTime;
   int      state;
   double   boxHigh;
   double   boxLow;
   int      firstTouchIndex;
};

struct ApexLevel
{
   int      apexType;
   double   price;
   int      candleIndex;
   int      breakoutIndex;
   datetime candleTime;
   bool     isExternal;
   int      state;
};

struct TrendlineMatch
{
   bool     valid;
   string   timeframe;
   string   mode;
   int      firstIndex;
   int      secondIndex;
   double   firstPrice;
   double   secondPrice;
   double   lineValue;
};

struct StorylineEvent
{
   bool     valid;
   string   htf;
   string   ltf;
   int      bias;
   double   rejectionPrice;
   datetime rejectionTime;
   int      rejectionCandleIdx;
   datetime breakoutTime;
   int      breakoutCandleIdx;
   string   rejectionLevelDesc;
};

struct FTFLZone
{
   bool     valid;
   string   timeframe;
   int      direction;
   double   price;
   double   boxTop;
   double   boxBottom;
   datetime timeFormed;
   int      candleIndex;
   string   levelTypeDesc;
   int      priority;     // 2=A+, 1=STANDARD, 0=REDUCED
   bool     isFresh;
};

struct STFLZone
{
   bool     valid;
   string   timeframe;
   int      direction;
   double   price;
   double   boxTop;
   double   boxBottom;
   datetime timeFormed;
   int      candleIndex;
   string   levelTypeDesc;
   bool     isInsideFTFLBox;
   bool     isFresh;
};

struct TTFLRefinement
{
   bool     valid;
   string   timeframe;
   int      direction;
   double   entryPrice;
   double   slReference;
   int      entryType;    // 0=KEY_LEVEL, 1=EQUILIBRIUM
   string   description;
   bool     isFresh;
};

struct PositionPlan
{
   string   symbol;
   int      direction;
   double   rawEntry;
   double   bufferedEntry;
   double   stopLoss;
   double   slPoints;
   double   takeProfit;
   double   obstacleTp;
   double   riskAmountUsd;
   double   lotSize;
   double   riskPercent;
   string   modelName;
};

struct TradeSignal
{
   string         modelName;
   string         symbol;
   int            direction;
   string         storylineKey;
   string         storylineDesc;
   double         storylineRejection;
   string         ftflTf;
   string         stflTf;
   string         ttflTf;
   PositionPlan   primary;
   PositionPlan   secondary;
   bool           hasSecondary;
   string         confidence;
   string         rationale;
   datetime       formationTime;
   double         ftflBoxTop;
   double         ftflBoxBottom;
   double         stflBoxTop;
   double         stflBoxBottom;
   double         distanceToEntry;
   int            priorityRank;
};

struct DataSet
{
   MqlRates mn1[];
   MqlRates w1[];
   MqlRates d1[];
   MqlRates h4[];
   MqlRates h1[];
   int      mn1Count;
   int      w1Count;
   int      d1Count;
   int      h4Count;
   int      h1Count;
};

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

CTrade  g_trade;
string   g_symbol = "";
datetime g_lastH1BarTime = 0;
int      g_tradingDayKey = -1;
int      g_dailyLossCount = 0;
int      g_lastSignalPrint = 0;
double   g_accountProtectionStartBalance = 0.0;

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

bool IsGoldSymbol(const string symbol)
{
   return (StringFind(symbol, "XAU") >= 0 || StringFind(symbol, "GOLD") >= 0);
}

double ClampDouble(const double v, const double lo, const double hi)
{
   if(v < lo) return lo;
   if(v > hi) return hi;
   return v;
}

string TFNameFromPeriod(const ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_MN1) return "MN1";
   if(tf == PERIOD_W1)   return "W1";
   if(tf == PERIOD_D1)   return "D1";
   if(tf == PERIOD_H4)   return "H4";
   if(tf == PERIOD_H1)   return "H1";
   return "";
}

ENUM_TIMEFRAMES PeriodFromTFName(const string tf)
{
   if(tf == "MN1" || tf == "MN" || tf == "M1") return PERIOD_MN1;
   if(tf == "W1") return PERIOD_W1;
   if(tf == "D1") return PERIOD_D1;
   if(tf == "H4") return PERIOD_H4;
   if(tf == "H1") return PERIOD_H1;
   return PERIOD_CURRENT;
}

bool IsBullishBar(const MqlRates &bar)
{
   return (bar.close > bar.open);
}

bool IsBearishBar(const MqlRates &bar)
{
   return (bar.close < bar.open);
}

double BarBodyHigh(const MqlRates &bar)
{
   return MathMax(bar.open, bar.close);
}

double BarBodyLow(const MqlRates &bar)
{
   return MathMin(bar.open, bar.close);
}

double SymbolPointValue(const string symbol)
{
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = 0.0001;
   return point;
}

int SymbolDigitsValue(const string symbol);

double SymbolPipValue(const string symbol)
{
   const int digits = SymbolDigitsValue(symbol);
   const double point = SymbolPointValue(symbol);

   if(digits == 3 || digits == 5)
      return point * 10.0;

   return point;
}

double SymbolContractSize(const string symbol)
{
   double contract = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(contract <= 0.0)
      contract = 100.0;
   return contract;
}

int SymbolStopsLevelPoints(const string symbol)
{
   const int level = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   return (level > 0 ? level : 0);
}

double SymbolVolumeMin(const string symbol)
{
   double v = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   if(v <= 0.0)
      v = 0.01;
   return v;
}

double SymbolVolumeStep(const string symbol)
{
   double v = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(v <= 0.0)
      v = 0.01;
   return v;
}

double SymbolVolumeMax(const string symbol)
{
   double v = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   if(v <= 0.0)
      v = 100.0;
   return v;
}

int SymbolDigitsValue(const string symbol)
{
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(digits <= 0)
      digits = 2;
   return digits;
}

double NormalizeVolumeByStep(const string symbol, double volume)
{
   const double minVol  = SymbolVolumeMin(symbol);
   const double stepVol = SymbolVolumeStep(symbol);
   const double maxVol  = SymbolVolumeMax(symbol);

   if(volume < minVol)
      volume = minVol;

   volume = MathRound(volume / stepVol) * stepVol;
   if(volume < minVol)
      volume = minVol;
   if(volume > maxVol)
      volume = maxVol;

   return NormalizeDouble(volume, 2);
}

double NormalizePriceByDigits(const string symbol, const double price)
{
   return NormalizeDouble(price, SymbolDigitsValue(symbol));
}

void AddCandleLevel(CandleLevel &levels[], int &count, const int levelType, const double price, const int candleIndex, const datetime candleTime, const int state, const int derivedFromIndex)
{
   ArrayResize(levels, count + 1);
   levels[count].levelType = levelType;
   levels[count].price = price;
   levels[count].candleIndex = candleIndex;
   levels[count].candleTime = candleTime;
   levels[count].state = state;
   levels[count].derivedFromIndex = derivedFromIndex;
   levels[count].firstTouchIndex = -1;
   levels[count].breakCandleIndex = -1;
   count++;
}

void AddOCLLevel(OCLLevel &levels[], int &count, const int oclType, const double price, const int idx1, const int idx2, const datetime candleTime, const double boxHigh, const double boxLow)
{
   ArrayResize(levels, count + 1);
   levels[count].oclType = oclType;
   levels[count].price = price;
   levels[count].candleIndex1 = idx1;
   levels[count].candleIndex2 = idx2;
   levels[count].candleTime = candleTime;
   levels[count].state = LS_FRESH;
   levels[count].boxHigh = boxHigh;
   levels[count].boxLow = boxLow;
   levels[count].firstTouchIndex = -1;
   levels[count].breakCount = 0;
   count++;
}

void AddQMLevel(QMLevel &levels[], int &count, const int qmType, const int direction, const double price, const int originIndex, const int flipIndex, const int breakIndex, const datetime candleTime, const double boxHigh, const double boxLow)
{
   ArrayResize(levels, count + 1);
   levels[count].qmType = qmType;
   levels[count].direction = direction;
   levels[count].price = price;
   levels[count].originIndex = originIndex;
   levels[count].flipIndex = flipIndex;
   levels[count].breakIndex = breakIndex;
   levels[count].candleTime = candleTime;
   levels[count].state = LS_FRESH;
   levels[count].boxHigh = boxHigh;
   levels[count].boxLow = boxLow;
   levels[count].firstTouchIndex = -1;
   count++;
}

void AddApexLevel(ApexLevel &levels[], int &count, const int apexType, const double price, const int candleIndex, const int breakoutIndex, const datetime candleTime, const bool isExternal)
{
   ArrayResize(levels, count + 1);
   levels[count].apexType = apexType;
   levels[count].price = price;
   levels[count].candleIndex = candleIndex;
   levels[count].breakoutIndex = breakoutIndex;
   levels[count].candleTime = candleTime;
   levels[count].isExternal = isExternal;
   levels[count].state = LS_FRESH;
   count++;
}

// ---------------------------------------------------------------------------
// Indicator-parity shared helpers (ported from .\Indicators cores)
// NOTE: EA bars[] arrays are CHRONOLOGICAL (0 = oldest, count-1 = forming).
// All scans below use CLOSED bars only (up to count-2), mirroring the
// indicators' "series j>=1" rule so backtest state is day-end final.
// ---------------------------------------------------------------------------

double ActivePipValue()
{
   const string sym = (g_symbol != "" ? g_symbol : _Symbol);
   return SymbolPipValue(sym);
}

// Wilder ATR ending at the last CLOSED bar (parity with iATR for the PHX
// trendline 3.0xATR relevance filter; seeded on 3xperiod window).
double ManualATR(const MqlRates &bars[], const int count, const int period)
{
   const int per = MathMax(1, period);
   const int lastClosed = count - 2;
   if(lastClosed < 2 || count < per + 2)
      return 0.0;

   const int winBars = MathMin(lastClosed, 3 * per + 1);
   const int winFirst = lastClosed - winBars + 1;
   if(winFirst < 1)
      return 0.0;

   double tr[];
   ArrayResize(tr, winBars);
   for(int k = 0; k < winBars; ++k)
   {
      const int i = winFirst + k;
      const double hL = bars[i].high - bars[i].low;
      const double hPc = MathAbs(bars[i].high - bars[i - 1].close);
      const double lPc = MathAbs(bars[i].low - bars[i - 1].close);
      tr[k] = MathMax(hL, MathMax(hPc, lPc));
   }

   const int seedN = MathMin(per, winBars);
   double atr = 0.0;
   for(int k = 0; k < seedN; ++k)
      atr += tr[k];
   atr /= (double)seedN;

   for(int k = seedN; k < winBars; ++k)
      atr = (atr * (per - 1) + tr[k]) / per;

   return atr;
}

// Body-engulf only (MSNR_OCL / MSNR_TFL_Zones parity: wicks and gaps are
// irrelevant; range-engulf does NOT disqualify an OCL).
bool IsBodyEngulfPair(const bool b1Bull, const bool b1Bear, const double o1, const double c1,
                      const bool b2Bull, const bool b2Bear, const double o2, const double c2)
{
   if(b1Bull && b2Bull)
      return (o2 <= o1 && c2 >= c1);
   if(b1Bear && b2Bear)
      return (o2 >= o1 && c2 <= c1);
   return false;
}

// S/R + OCL level prices (MSNR_PHX_Trendline LevelPrices parity: close of
// candle1 for every directed pair — S/R flip or same-color — dojis skipped).
void CollectLevelPrices(const MqlRates &bars[], const int count, double &lv[])
{
   ArrayResize(lv, 0);
   const int lastClosed = count - 2;
   for(int i = 0; i < lastClosed; ++i)
   {
      const bool b1Bull = IsBullishBar(bars[i]);
      const bool b1Bear = IsBearishBar(bars[i]);
      const bool b2Bull = IsBullishBar(bars[i + 1]);
      const bool b2Bear = IsBearishBar(bars[i + 1]);
      if((b1Bear && b2Bull) || (b1Bull && b2Bear) || (b1Bull && b2Bull) || (b1Bear && b2Bear))
      {
         ArrayResize(lv, ArraySize(lv) + 1);
         lv[ArraySize(lv) - 1] = bars[i].close;
      }
   }
}

// Apex/iAB structure engine (MSNR_Apex v1.00 parity, chrono arrays):
// strict close pivots (strength 3) -> alternation (keep most extreme) ->
// chronological BOS walk with trend + leg origins. Tags: "AR","AS","iABR","iABS".
void BuildApexStructure(const MqlRates &bars[], const int count, string &tags[], double &px[],
                        datetime &tm[], datetime &conf[], int &apexCount)
{
   ArrayResize(tags, 0);
   ArrayResize(px, 0);
   ArrayResize(tm, 0);
   ArrayResize(conf, 0);
   apexCount = 0;
   if(count < 2 * 3 + 3)
      return;

   const int strength = 3;
   const int lastClosed = count - 2;

   // 1) raw strict pivots on closes, oldest -> newest
   int pType[];
   double pPrice[];
   int pIdx[];
   ArrayResize(pType, 0);
   ArrayResize(pPrice, 0);
   ArrayResize(pIdx, 0);
   for(int p = strength; p <= lastClosed - strength; ++p)
   {
      bool isHigh = true, isLow = true;
      for(int k = 1; k <= strength; ++k)
      {
         if(bars[p].close <= bars[p + k].close || bars[p].close <= bars[p - k].close)
            isHigh = false;
         if(bars[p].close >= bars[p + k].close || bars[p].close >= bars[p - k].close)
            isLow = false;
         if(!isHigh && !isLow)
            break;
      }
      if(!isHigh && !isLow)
         continue;
      ArrayResize(pType, ArraySize(pType) + 1);
      ArrayResize(pPrice, ArraySize(pPrice) + 1);
      ArrayResize(pIdx, ArraySize(pIdx) + 1);
      const int n = ArraySize(pType) - 1;
      pType[n] = (isHigh ? 1 : -1);
      pPrice[n] = bars[p].close;
      pIdx[n] = p;
   }

   // 2) alternation: same type twice -> keep most extreme
   int m = ArraySize(pType);
   for(int a = 1; a < m; ++a)
   {
      if(pType[a] == pType[a - 1])
      {
         const bool keepA = (pType[a] == 1 ? (pPrice[a] >= pPrice[a - 1]) : (pPrice[a] <= pPrice[a - 1]));
         if(keepA)
         {
            pPrice[a - 1] = pPrice[a];
            pIdx[a - 1] = pIdx[a];
         }
         for(int b = a + 1; b < m; ++b)
         {
            pType[b - 1] = pType[b];
            pPrice[b - 1] = pPrice[b];
            pIdx[b - 1] = pIdx[b];
         }
         --m;
         --a;
      }
   }
   ArrayResize(pType, m);
   ArrayResize(pPrice, m);
   ArrayResize(pIdx, m);

   // 3) chronological BOS walk (pivots confirm `strength` bars after extreme)
   int trend = 0;
   bool hasPH = false, hasPL = false;
   double phPrice = 0.0, plPrice = 0.0;
   datetime phTime = 0, plTime = 0;
   double legLow = 0.0, legHigh = 0.0;
   datetime legLowTime = 0, legHighTime = 0;
   bool hasLegLow = false, hasLegHigh = false;
   int pNext = 0;

   for(int j = 0; j <= lastClosed; ++j)
   {
      while(pNext < m && pIdx[pNext] + strength <= j)
      {
         if(pType[pNext] == 1)
         {
            hasPH = true;
            phPrice = pPrice[pNext];
            phTime = bars[pIdx[pNext]].time;
            hasLegHigh = true;
            legHigh = pPrice[pNext];
            legHighTime = bars[pIdx[pNext]].time;
         }
         else
         {
            hasPL = true;
            plPrice = pPrice[pNext];
            plTime = bars[pIdx[pNext]].time;
            hasLegLow = true;
            legLow = pPrice[pNext];
            legLowTime = bars[pIdx[pNext]].time;
         }
         ++pNext;
      }

      if(hasPH && bars[j].close > phPrice)
      {
         ArrayResize(tags, apexCount + 1);
         ArrayResize(px, apexCount + 1);
         ArrayResize(tm, apexCount + 1);
         ArrayResize(conf, apexCount + 1);
         tags[apexCount] = "AR";
         px[apexCount] = phPrice;
         tm[apexCount] = phTime;
         conf[apexCount] = bars[j].time;
         ++apexCount;
         if(hasLegLow)
         {
            ArrayResize(tags, apexCount + 1);
            ArrayResize(px, apexCount + 1);
            ArrayResize(tm, apexCount + 1);
            ArrayResize(conf, apexCount + 1);
            tags[apexCount] = (trend == 1 ? "iABS" : "AS");
            px[apexCount] = legLow;
            tm[apexCount] = legLowTime;
            conf[apexCount] = bars[j].time;
            ++apexCount;
         }
         trend = 1;
         hasPH = false;
         hasLegLow = false;
      }
      else if(hasPL && bars[j].close < plPrice)
      {
         ArrayResize(tags, apexCount + 1);
         ArrayResize(px, apexCount + 1);
         ArrayResize(tm, apexCount + 1);
         ArrayResize(conf, apexCount + 1);
         tags[apexCount] = "AS";
         px[apexCount] = plPrice;
         tm[apexCount] = plTime;
         conf[apexCount] = bars[j].time;
         ++apexCount;
         if(hasLegHigh)
         {
            ArrayResize(tags, apexCount + 1);
            ArrayResize(px, apexCount + 1);
            ArrayResize(tm, apexCount + 1);
            ArrayResize(conf, apexCount + 1);
            tags[apexCount] = (trend == -1 ? "iABR" : "AR");
            px[apexCount] = legHigh;
            tm[apexCount] = legHighTime;
            conf[apexCount] = bars[j].time;
            ++apexCount;
         }
         trend = -1;
         hasPL = false;
         hasLegHigh = false;
      }
   }
}

// HTF gate helper (Apex engine is D1/W1/MN1 only per Video 3).
bool IsHTFForApex(const string timeframe)
{
   return (timeframe == "MN1" || timeframe == "MN" || timeframe == "M1" || timeframe == "W1" || timeframe == "D1");
}

void AddTradeSignal(TradeSignal &signals[], int &count, const TradeSignal &signal)
{
   ArrayResize(signals, count + 1);
   signals[count] = signal;
   count++;
}

void SwapSignals(TradeSignal &a, TradeSignal &b)
{
   TradeSignal tmp = a;
   a = b;
   b = tmp;
}

void SortSignalsByDistance(TradeSignal &signals[], const int count)
{
   for(int i = 0; i < count - 1; ++i)
   {
      for(int j = i + 1; j < count; ++j)
      {
         if(signals[j].distanceToEntry < signals[i].distanceToEntry)
            SwapSignals(signals[i], signals[j]);
      }
   }
   for(int k = 0; k < count; ++k)
      signals[k].priorityRank = k + 1;
}

bool CopyRatesChrono(const string symbol, const ENUM_TIMEFRAMES tf, const int count, MqlRates &outRates[])
{
   if(count <= 0)
      return false;

   MqlRates tmp[];
   ArraySetAsSeries(tmp, true);
   int copied = CopyRates(symbol, tf, 0, count, tmp);
   if(copied <= 0)
      return false;

   ArrayResize(outRates, copied);
   for(int i = 0; i < copied; ++i)
      outRates[i] = tmp[copied - 1 - i];

   return true;
}

bool LoadDataSet(const string symbol, DataSet &ds)
{
   // History depths sized for the indicator lookbacks (Storyline
   // LookbackX/Y = 150/400, TFL tiers 150/300/300).
   const bool mnOk = CopyRatesChrono(symbol, PERIOD_MN1, 160, ds.mn1);
   const bool w1Ok = CopyRatesChrono(symbol, PERIOD_W1, 400, ds.w1);
   const bool d1Ok = CopyRatesChrono(symbol, PERIOD_D1, 400, ds.d1);
   const bool h4Ok = CopyRatesChrono(symbol, PERIOD_H4, 500, ds.h4);
   const bool h1Ok = CopyRatesChrono(symbol, PERIOD_H1, 500, ds.h1);

   ds.mn1Count = ArraySize(ds.mn1);
   ds.w1Count = ArraySize(ds.w1);
   ds.d1Count = ArraySize(ds.d1);
   ds.h4Count = ArraySize(ds.h4);
   ds.h1Count = ArraySize(ds.h1);

   return (mnOk || w1Ok || d1Ok || h4Ok || h1Ok);
}

double GetCurrentClose(const DataSet &ds)
{
   if(ds.h1Count > 0)
      return ds.h1[ds.h1Count - 1].close;
   if(ds.h4Count > 0)
      return ds.h4[ds.h4Count - 1].close;
   if(ds.d1Count > 0)
      return ds.d1[ds.d1Count - 1].close;
   return 0.0;
}

int DayKey(const datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return dt.year * 10000 + dt.mon * 100 + dt.day;
}

bool IsSameDay(const datetime a, const datetime b)
{
   return (DayKey(a) == DayKey(b));
}

int FindLongValue(const long &values[], const int count, const long needle)
{
   for(int i = 0; i < count; ++i)
   {
      if(values[i] == needle)
         return i;
   }
   return -1;
}

bool SummarizePositionHistory(const long positionId, double &entryVolume, double &exitVolume, double &netProfit, datetime &lastExitTime)
{
   entryVolume = 0.0;
   exitVolume = 0.0;
   netProfit = 0.0;
   lastExitTime = 0;

   if(!HistorySelect(0, TimeCurrent() + 60))
      return false;

   const int total = HistoryDealsTotal();
   for(int i = 0; i < total; ++i)
   {
      const ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket == 0)
         continue;
      if((long)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagic)
         continue;
      if((long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID) != positionId)
         continue;

      const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
      const double volume = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
      const double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT) + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION) + HistoryDealGetDouble(dealTicket, DEAL_SWAP);
      const datetime dealTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);

      if(entry == DEAL_ENTRY_IN)
         entryVolume += volume;
      else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
      {
         exitVolume += volume;
         netProfit += profit;
         if(dealTime > lastExitTime)
            lastExitTime = dealTime;
      }
   }

   return (entryVolume > 0.0 || exitVolume > 0.0);
}

void RebuildDailyLossCount()
{
   g_dailyLossCount = 0;

   const datetime now = TimeCurrent();
   if(!HistorySelect(0, now + 60))
      return;

   long positionIds[];
   int positionCount = 0;

   const int total = HistoryDealsTotal();
   for(int i = 0; i < total; ++i)
   {
      const ulong dealTicket = HistoryDealGetTicket(i);
      if(dealTicket == 0)
         continue;
      if((long)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagic)
         continue;

      const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;

      const datetime dealTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
      if(!IsSameDay(dealTime, now))
         continue;

      const long positionId = (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
      if(positionId <= 0)
         continue;
      if(FindLongValue(positionIds, positionCount, positionId) >= 0)
         continue;

      ArrayResize(positionIds, positionCount + 1);
      positionIds[positionCount++] = positionId;
   }

   for(int p = 0; p < positionCount; ++p)
   {
      double entryVolume = 0.0;
      double exitVolume = 0.0;
      double netProfit = 0.0;
      datetime lastExitTime = 0;
      if(!SummarizePositionHistory(positionIds[p], entryVolume, exitVolume, netProfit, lastExitTime))
         continue;

      if(entryVolume > 0.0 && exitVolume >= entryVolume - 1e-8 && netProfit < 0.0 && IsSameDay(lastExitTime, now))
      {
         g_dailyLossCount++;
         GlobalVariableSet(StringFormat("MSNR_LOSS_%d_%I64d", g_tradingDayKey, positionIds[p]), 1.0);
      }
   }
}

void SyncTradingDayState()
{
   const int dayKey = DayKey(TimeCurrent());
   if(dayKey == g_tradingDayKey)
      return;

   g_tradingDayKey = dayKey;
   RebuildDailyLossCount();
}

bool IsAsiaSessionBlocked()
{
   if(!InpSkipAsiaSession)
      return false;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.hour >= 0 && dt.hour < 7);
}

bool IsDailyLossLimitHit()
{
   return (g_dailyLossCount >= MathMax(1, InpMaxDailyLosses));
}

void UpdateDailyLossFromDeal(const ulong dealTicket)
{
   if(dealTicket == 0)
      return;
   if(!HistoryDealSelect(dealTicket))
      return;
   if((long)HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagic)
      return;

   const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;

   SyncTradingDayState();

   const long positionId = (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);
   if(positionId <= 0)
      return;

   const string marker = StringFormat("MSNR_LOSS_%d_%I64d", g_tradingDayKey, positionId);
   if(GlobalVariableCheck(marker))
      return;

   double entryVolume = 0.0;
   double exitVolume = 0.0;
   double netProfit = 0.0;
   datetime lastExitTime = 0;
   if(!SummarizePositionHistory(positionId, entryVolume, exitVolume, netProfit, lastExitTime))
      return;

   if(entryVolume > 0.0 && exitVolume >= entryVolume - 1e-8 && netProfit < 0.0)
   {
      g_dailyLossCount++;
      GlobalVariableSet(marker, 1.0);
   }
}

// ---------------------------------------------------------------------------
// Candle analyzer and freshness
// ---------------------------------------------------------------------------

void DetectBaseLevels(const MqlRates &bars[], const int count, CandleLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;

   // Base S/R (MSNR_Levels_SR parity: closed bars only — the formation bar
   // i+1 must be a closed bar so levels never paint/vanish on the forming bar)
   for(int i = 0; i < count - 2; ++i)
   {
      const bool c0Bear = IsBearishBar(bars[i]);
      const bool c0Bull = IsBullishBar(bars[i]);
      const bool c1Bear = IsBearishBar(bars[i + 1]);
      const bool c1Bull = IsBullishBar(bars[i + 1]);

      if(c0Bear && c1Bull)
      {
         AddCandleLevel(levels, levelCount, LT_SUPPORT, bars[i].close, i, bars[i].time, LS_FRESH, -1);
      }
      else if(c0Bull && c1Bear)
      {
         AddCandleLevel(levels, levelCount, LT_RESISTANCE, bars[i].close, i, bars[i].time, LS_FRESH, -1);
      }
   }

   // Role reversals and freshness (MSNR_RoleFlip + MSNR_Freshness parity):
   // breaks flip on candle CLOSE through the level only; any wick straddle
   // (high>=price && low<=price, tol 0) marks UNFRESH; a break re-freshes the
   // level in its new role. Derived SBR/RBS levels are walked too so their
   // SBR->QM->DEAD second flips and touches track the indicator lifecycle.
   const int baseCount = levelCount;
   for(int n = 0; n < baseCount; ++n)
   {
      const int startI = levels[n].candleIndex + 2;

      for(int i = startI; i < count - 1; ++i)
      {
         if(levels[n].levelType == LT_SUPPORT)
         {
            if(bars[i].close < levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               AddCandleLevel(levels, levelCount, LT_SBR, levels[n].price, i, bars[i].time, LS_FRESH, levels[n].candleIndex);
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].price && bars[i].low <= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
         else if(levels[n].levelType == LT_RESISTANCE)
         {
            if(bars[i].close > levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               AddCandleLevel(levels, levelCount, LT_RBS, levels[n].price, i, bars[i].time, LS_FRESH, levels[n].candleIndex);
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].price && bars[i].low <= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
      }
   }

   // Second-lifecycle walk on derived SBR/RBS (RoleFlip SBR->QM / RBS->QM).
   for(int n = baseCount; n < levelCount; ++n)
   {
      if(levels[n].levelType != LT_SBR && levels[n].levelType != LT_RBS)
         continue;
      const int startI = levels[n].candleIndex + 1;

      for(int i = startI; i < count - 1; ++i)
      {
         if(levels[n].levelType == LT_SBR)
         {
            if(bars[i].close > levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].price && bars[i].low <= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
         else if(levels[n].levelType == LT_RBS)
         {
            if(bars[i].close < levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].price && bars[i].low <= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
      }
   }
}

// ---------------------------------------------------------------------------
// OCL detection
// ---------------------------------------------------------------------------

void DetectOCLLevels(const MqlRates &bars[], const int count, const string timeframe, OCLLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;

   if(!IsHTFForApex(timeframe))
      return;

   // Pass 1 (MSNR_OCL v1.00 parity): chronological scan with S/R pivots and
   // OCLs interleaved. An S/R pivot takes priority and updates the "last key
   // level" used for classification at birth:
   //   bullish pair right after Support    -> sOCL
   //   bearish pair right after Resistance -> rOCL
   //   previous key level was another OCL  -> 1LAB (OCL_ONE_LAP)
   //   otherwise                          -> plain STANDARD OCL
   // Engulfing = candle2 BODY covers candle1 BODY (wicks/gaps irrelevant);
   // engulfing same-color pairs are ignored AND do not update lastKL.
   // Closed bars only: the formation bar (i+1) must be <= count-2.
   int lastKL = 0;       // 0 none, 1 support, 2 resistance, 3 OCL
   bool lastKLBull = false;

   for(int i = 0; i < count - 2; ++i)
   {
      const bool c1Bull = IsBullishBar(bars[i]);
      const bool c1Bear = IsBearishBar(bars[i]);
      const bool c2Bull = IsBullishBar(bars[i + 1]);
      const bool c2Bear = IsBearishBar(bars[i + 1]);

      const bool isSupport = (c1Bear && c2Bull);
      const bool isResistance = (c1Bull && c2Bear);
      if(isSupport)
      {
         lastKL = 1;
         lastKLBull = true;
         continue;
      }
      if(isResistance)
      {
         lastKL = 2;
         lastKLBull = false;
         continue;
      }

      const bool oclBull = (c1Bull && c2Bull);
      const bool oclBear = (c1Bear && c2Bear);
      if(!(oclBull || oclBear))
         continue;

      if(IsBodyEngulfPair(c1Bull, c1Bear, bars[i].open, bars[i].close, c2Bull, c2Bear, bars[i + 1].open, bars[i + 1].close))
         continue;

      int type;
      if(oclBull && lastKL == 1)
         type = OCL_SOCL;
      else if(oclBear && lastKL == 2)
         type = OCL_ROCL;
      else if(lastKL == 3)
         type = OCL_ONE_LAP;
      else
         type = (oclBull ? OCL_STANDARD_BULLISH : OCL_STANDARD_BEARISH);

      // MSNR_TFL_Zones v1.10 box (Video-10 correction): the box caps at
      // candle2's BODY EDGE but always contains the OCL level line itself.
      // Bull: [candle2 low .. max(candle2 body bottom, level)]; bear: mirror.
      double oclBoxHigh, oclBoxLow;
      if(oclBull)
      {
         const double c2BodyLow = MathMin(bars[i + 1].open, bars[i + 1].close);
         oclBoxHigh = MathMax(c2BodyLow, bars[i].close);
         oclBoxLow = bars[i + 1].low;
      }
      else
      {
         const double c2BodyHigh = MathMax(bars[i + 1].open, bars[i + 1].close);
         oclBoxHigh = bars[i + 1].high;
         oclBoxLow = MathMin(c2BodyHigh, bars[i].close);
      }

      AddOCLLevel(levels, levelCount, type, bars[i].close, i, i + 1, bars[i].time,
                  oclBoxHigh, oclBoxLow);

      lastKL = 3;
      lastKLBull = oclBull;
   }

   // Pass 2 (MSNR_OCL behavior parity): acting-support -> flip -> LS -> dead,
   // every transition on candle CLOSE through the level (closed bars only).
   // Bullish OCL: close below -> acts Resistance; close back above -> LS OCL;
   // one more close below -> DEAD (BROKEN). Bearish mirror.
   // Freshness (TFL FirstTouchAfter parity): first wick straddle after
   // formation -> UNFRESH.
   const int lastClosed = count - 2;
   for(int n = 0; n < levelCount; ++n)
   {
      const bool bullish = IsBullishBar(bars[levels[n].candleIndex1]);
      int beh = (bullish ? 0 : 1);   // 0 acting support, 1 acting resistance, 2 LS, 3 dead
      int breaks = 0;
      bool touched = false;

      for(int i = levels[n].candleIndex2 + 1; i <= lastClosed; ++i)
      {
         const double c = bars[i].close;
         bool broke = false;

         if(beh == 0 && c < levels[n].price)
         {
            beh = 1;
            broke = true;
         }
         else if(beh == 1 && c > levels[n].price)
         {
            beh = 2;
            broke = true;
         }
         else if(beh == 2)
         {
            if((bullish && c < levels[n].price) || (!bullish && c > levels[n].price))
            {
               beh = 3;
               broke = true;
            }
         }

         if(broke)
         {
            ++breaks;
            if(beh == 3)
               break;
            continue;
         }

         if(!touched && bars[i].high >= levels[n].price && bars[i].low <= levels[n].price)
         {
            touched = true;
            levels[n].firstTouchIndex = i;
         }
      }

      levels[n].breakCount = breaks;
      if(beh == 2)
         levels[n].oclType = OCL_LS_OCL;
      if(beh == 3)
         levels[n].state = LS_BROKEN;
      else if(touched)
         levels[n].state = LS_UNFRESH;
      else
         levels[n].state = LS_FRESH;
   }
}

// ---------------------------------------------------------------------------
// QM detection
// ---------------------------------------------------------------------------

void DetectQMLevels(const MqlRates &bars[], const int count, const string timeframe, const CandleLevel &baseLevels[], const int baseCount, QMLevel &levels[], int &levelCount)
{
   // MSNR_QM_Taxonomy v1.00 parity:
   //  - QM birth from the role lifecycle S->SBR->QM->DEAD (R->RBS->QM->DEAD)
   //    walked on closes; the birth bar is the SBR->QM (RBS->QM) close.
   //  - QM box = parent S/R geometry (TFL parity): from-Support keeps
   //    [min(c1/c2 lows) .. level], from-Resistance [level .. max(c1/c2 highs)].
   //  - Freshness re-arms at QM birth (first wick straddle after birth,
   //    birth bar excluded, -> UNFRESH; later break -> BROKEN).
   //  - Taxonomy: abQM = price matches a BOS-confirmed Apex (AR/AS) level
   //    (2.0 pips, confirmed at/before QM birth); iabQM = matches iAB only;
   //    else ftQM first time / stQM second time in the zone (2.0 pips,
   //    chronological by QM birth). Priority ab > iab > ft > st.
   //  - Apex origin matching runs on MN1/W1/D1 only (Apex is HTF-only per
   //    Video 3); lower TFs still get lifecycle QM with ft/st taxonomy.
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;

   const int lastClosed = count - 2;
   const double pip = ActivePipValue();
   const bool useApexOrigin = IsHTFForApex(timeframe);

   // Pass 1: lifecycle births (plain S/R parents only — derived SBR/RBS rows
   // in baseLevels are lifecycle states, not new parents).
   int qmBase[];      // index into baseLevels
   int qmSbr[];       // S->SBR (R->RBS) break bar
   int qmBirth[];     // SBR->QM (RBS->QM) birth bar
   bool qmSup[];      // true: S->SBR->QM (bullish), false: R->RBS->QM (bearish)
   bool qmDead[];
   bool qmTouched[];
   int qmTouchIdx[];
   ArrayResize(qmBase, 0);
   ArrayResize(qmSbr, 0);
   ArrayResize(qmBirth, 0);
   ArrayResize(qmSup, 0);
   ArrayResize(qmDead, 0);
   ArrayResize(qmTouched, 0);
   ArrayResize(qmTouchIdx, 0);

   for(int n = 0; n < baseCount; ++n)
   {
      if(baseLevels[n].levelType != LT_SUPPORT && baseLevels[n].levelType != LT_RESISTANCE)
         continue;

      const bool startsSup = (baseLevels[n].levelType == LT_SUPPORT);
      const double lp = baseLevels[n].price;
      int role = (startsSup ? 0 : 3);   // 0=S,1=SBR,2=QM,3=R,4=RBS,5=QM,6=dead
      int sbrBirth = -1, birth = -1;
      bool dead = false;

      for(int i = baseLevels[n].candleIndex + 2; i <= lastClosed; ++i)
      {
         const double c = bars[i].close;
         bool broke = false;

         if(role == 0)      { broke = (c < lp); if(broke) { role = 1; sbrBirth = i; } }
         else if(role == 1) { broke = (c > lp); if(broke) { role = 2; birth = i; } }
         else if(role == 2) { broke = (c < lp); if(broke) { role = 6; dead = true; } }
         else if(role == 3) { broke = (c > lp); if(broke) { role = 4; sbrBirth = i; } }
         else if(role == 4) { broke = (c < lp); if(broke) { role = 5; birth = i; } }
         else if(role == 5) { broke = (c > lp); if(broke) { role = 6; dead = true; } }

         if(role == 6)
            break;
      }

      if(birth < 0)
         continue;

      // Freshness since QM birth (birth bar excluded).
      bool touched = false;
      int touchIdx = -1;
      for(int i = birth + 1; i <= lastClosed; ++i)
      {
         if(bars[i].high >= lp && bars[i].low <= lp)
         {
            touched = true;
            touchIdx = i;
            break;
         }
      }

      const int q = ArraySize(qmBirth);
      ArrayResize(qmBase, q + 1);
      ArrayResize(qmSbr, q + 1);
      ArrayResize(qmBirth, q + 1);
      ArrayResize(qmSup, q + 1);
      ArrayResize(qmDead, q + 1);
      ArrayResize(qmTouched, q + 1);
      ArrayResize(qmTouchIdx, q + 1);
      qmBase[q] = n;
      qmSbr[q] = sbrBirth;
      qmBirth[q] = birth;
      qmSup[q] = startsSup;
      qmDead[q] = dead;
      qmTouched[q] = touched;
      qmTouchIdx[q] = touchIdx;
   }

   const int qn = ArraySize(qmBirth);
   if(qn <= 0)
      return;

   // Pass 2: Apex origin levels (MSNR_Apex engine shared helper).
   string apxTag[];
   double apxPrice[];
   datetime apxTime[];
   datetime apxConf[];
   int apxCount = 0;
   if(useApexOrigin)
      BuildApexStructure(bars, count, apxTag, apxPrice, apxTime, apxConf, apxCount);

   const double matchTol = InpApexMatchTolerancePips * pip;
   const double zoneTol = InpQMZoneTolerancePips * pip;

   // Chronological order by QM birth (for FT/ST counting).
   int order[];
   ArrayResize(order, qn);
   for(int i = 0; i < qn; ++i)
      order[i] = i;
   for(int a = 0; a < qn; ++a)
      for(int b = a + 1; b < qn; ++b)
         if(bars[qmBirth[order[b]]].time < bars[qmBirth[order[a]]].time)
         {
            const int tmp = order[a];
            order[a] = order[b];
            order[b] = tmp;
         }

   for(int oi = 0; oi < qn; ++oi)
   {
      const int q = order[oi];
      const int bn = qmBase[q];
      const double lp = baseLevels[bn].price;
      const datetime birthT = bars[qmBirth[q]].time;

      bool foundAB = false, foundIAB = false;
      for(int a = 0; a < apxCount; ++a)
      {
         if(apxConf[a] > birthT)
            continue;
         if(MathAbs(lp - apxPrice[a]) > matchTol)
            continue;
         if(apxTag[a] == "AR" || apxTag[a] == "AS")
         {
            foundAB = true;
            break;
         }
         if(apxTag[a] == "iABR" || apxTag[a] == "iABS")
            foundIAB = true;
      }

      int prior = 0;
      for(int pj = 0; pj < oi; ++pj)
      {
         const int p = order[pj];
         if(MathAbs(lp - baseLevels[qmBase[p]].price) <= zoneTol)
            ++prior;
      }

      int qmType;
      if(foundAB)
         qmType = QM_ABQM;
      else if(foundIAB)
         qmType = QM_IABQM;
      else if(prior == 0)
         qmType = QM_FTQM;
      else
         qmType = QM_STQM;

      // Parent S/R box geometry (TFL parity) from the parent's c1/c2.
      const int c1 = baseLevels[bn].candleIndex;
      const int c2 = (c1 + 1 < count ? c1 + 1 : c1);
      double boxHigh, boxLow;
      if(qmSup[q])
      {
         boxHigh = lp;
         boxLow = MathMin(bars[c1].low, bars[c2].low);
      }
      else
      {
         boxHigh = MathMax(bars[c1].high, bars[c2].high);
         boxLow = lp;
      }

      const int originIdx = (baseLevels[bn].derivedFromIndex >= 0 ? baseLevels[bn].derivedFromIndex : baseLevels[bn].candleIndex);
      AddQMLevel(levels, levelCount, qmType, (qmSup[q] ? QM_BULLISH : QM_BEARISH), lp,
                 originIdx, qmSbr[q], qmBirth[q], birthT, boxHigh, boxLow);

      levels[levelCount - 1].firstTouchIndex = qmTouchIdx[q];
      if(qmDead[q])
         levels[levelCount - 1].state = LS_BROKEN;
      else if(qmTouched[q])
         levels[levelCount - 1].state = LS_UNFRESH;
      else
         levels[levelCount - 1].state = LS_FRESH;
   }
}

// ---------------------------------------------------------------------------
// Apex / IAB detection
// ---------------------------------------------------------------------------

bool IsLocalPeak(const MqlRates &bars[], const int count, const int idx, const int distance)
{
   if(idx - distance < 0 || idx + distance >= count)
      return false;
   const double price = bars[idx].close;
   for(int i = idx - distance; i <= idx + distance; ++i)
   {
      if(i == idx)
         continue;
      if(bars[i].close >= price)
         return false;
   }
   return true;
}

bool IsLocalValley(const MqlRates &bars[], const int count, const int idx, const int distance)
{
   if(idx - distance < 0 || idx + distance >= count)
      return false;
   const double price = bars[idx].close;
   for(int i = idx - distance; i <= idx + distance; ++i)
   {
      if(i == idx)
         continue;
      if(bars[i].close <= price)
         return false;
   }
   return true;
}

bool FindConfirmedSwingTarget(const MqlRates &bars[], const int count, const int searchEndExclusive, const bool bullish, double &targetPrice, int &targetIdx)
{
   targetPrice = 0.0;
   targetIdx = -1;
   if(count < 5)
      return false;

   const int swingDistance = 2;
   int lastCandidate = searchEndExclusive - swingDistance - 1;
   if(lastCandidate > count - swingDistance - 1)
      lastCandidate = count - swingDistance - 1;
   if(lastCandidate < swingDistance)
      return false;

   for(int i = lastCandidate; i >= swingDistance; --i)
   {
      if(bullish)
      {
         if(IsLocalPeak(bars, count, i, swingDistance))
         {
            targetIdx = i;
            targetPrice = bars[i].close;
            return true;
         }
      }
      else
      {
         if(IsLocalValley(bars, count, i, swingDistance))
         {
            targetIdx = i;
            targetPrice = bars[i].close;
            return true;
         }
      }
   }

   return false;
}

bool IsSingleCandleMitigation(const MqlRates &bar, const double level, const bool bullish)
{
   if(bullish)
      return (bar.low <= level && bar.open > level && bar.close > level);

   return (bar.high >= level && bar.open < level && bar.close < level);
}

// ---------------------------------------------------------------------------
// PHX trendline core (MSNR_PHX_Trendline v1.02 parity)
// Anchors: newest 2 same-side WICK-fractal swing heads (alternating, most
// extreme kept); projection in TIME at the last closed bar; relevance gate
// |proj - close| <= InpTLMaxDistATR x ATR(InpTLATRPeriod); master confluence
// TLxLVL = projection within InpTLConflPips of a 2-candle S/R or OCL level.
// Touches within InpTLTouchPips are counted (indicator parity) but not gated.
// ---------------------------------------------------------------------------

void CollectWickPivots(const MqlRates &bars[], const int count, const int strength, const int lookbackBars, int &pivIdx[], double &pivPrice[], bool &pivHigh[], int &pivCount)
{
   ArrayResize(pivIdx, 0);
   ArrayResize(pivPrice, 0);
   ArrayResize(pivHigh, 0);
   pivCount = 0;

   const int str = MathMax(1, strength);
   if(count < 2 * str + 3)
      return;

   const int lastClosed = count - 2;
   const int first = MathMax(str, lastClosed - MathMax(lookbackBars, str + 1) + 1);
   const int last = lastClosed - str;
   if(last < first)
      return;

   int rawIdx[];
   double rawPrice[];
   bool rawHigh[];
   ArrayResize(rawIdx, 0);
   ArrayResize(rawPrice, 0);
   ArrayResize(rawHigh, 0);

   for(int p = first; p <= last; ++p)
   {
      bool isHigh = true, isLow = true;
      for(int k = 1; k <= str; ++k)
      {
         if(bars[p].high <= bars[p + k].high || bars[p].high <= bars[p - k].high)
            isHigh = false;
         if(bars[p].low >= bars[p + k].low || bars[p].low >= bars[p - k].low)
            isLow = false;
         if(!isHigh && !isLow)
            break;
      }
      if(!isHigh && !isLow)
         continue;
      if(isHigh && isLow)
         isLow = false;

      ArrayResize(rawIdx, ArraySize(rawIdx) + 1);
      ArrayResize(rawPrice, ArraySize(rawPrice) + 1);
      ArrayResize(rawHigh, ArraySize(rawHigh) + 1);
      const int n = ArraySize(rawIdx) - 1;
      rawIdx[n] = p;
      rawPrice[n] = (isHigh ? bars[p].high : bars[p].low);
      rawHigh[n] = isHigh;
   }

   // Alternation: same side twice in a row -> keep the most extreme.
   int m = ArraySize(rawIdx);
   for(int a = 1; a < m; ++a)
   {
      if(rawHigh[a] == rawHigh[a - 1])
      {
         const bool keepA = (rawHigh[a] ? (rawPrice[a] >= rawPrice[a - 1]) : (rawPrice[a] <= rawPrice[a - 1]));
         if(keepA)
         {
            rawPrice[a - 1] = rawPrice[a];
            rawIdx[a - 1] = rawIdx[a];
         }
         for(int b = a + 1; b < m; ++b)
         {
            rawHigh[b - 1] = rawHigh[b];
            rawPrice[b - 1] = rawPrice[b];
            rawIdx[b - 1] = rawIdx[b];
         }
         --m;
         --a;
      }
   }

   ArrayResize(pivIdx, m);
   ArrayResize(pivPrice, m);
   ArrayResize(pivHigh, m);
   for(int i = 0; i < m; ++i)
   {
      pivIdx[i] = rawIdx[i];
      pivPrice[i] = rawPrice[i];
      pivHigh[i] = rawHigh[i];
   }
   pivCount = m;
}

double TLProjectAt(const datetime t1, const double p1, const datetime t2, const double p2, const datetime t)
{
   if(t2 <= t1)
      return p1;
   const double slope = (p2 - p1) / (double)(t2 - t1);
   return p1 + slope * (double)(t - t1);
}

bool CheckTrendlineConfluenceOnTF(const MqlRates &bars[], const int count, const string timeframe, const bool bullish, const int lookbackBars, TrendlineMatch &match)
{
   match.valid = false;
   match.timeframe = timeframe;
   match.mode = "";
   match.firstIndex = -1;
   match.secondIndex = -1;
   match.firstPrice = 0.0;
   match.secondPrice = 0.0;
   match.lineValue = 0.0;

   const int lastClosed = count - 2;
   if(lastClosed < 5)
      return false;

   int pivIdx[];
   double pivPrice[];
   bool pivHigh[];
   int pivCount = 0;
   CollectWickPivots(bars, count, InpTLPivotStrength, lookbackBars, pivIdx, pivPrice, pivHigh, pivCount);

   // Same-side pivots, oldest -> newest (bullish -> support lows).
   const bool wantHigh = !bullish;
   int sIdx[];
   double sPrice[];
   ArrayResize(sIdx, 0);
   ArrayResize(sPrice, 0);
   for(int p = 0; p < pivCount; ++p)
   {
      if(pivHigh[p] != wantHigh)
         continue;
      ArrayResize(sIdx, ArraySize(sIdx) + 1);
      ArrayResize(sPrice, ArraySize(sPrice) + 1);
      sIdx[ArraySize(sIdx) - 1] = pivIdx[p];
      sPrice[ArraySize(sPrice) - 1] = pivPrice[p];
   }

   const int sc = ArraySize(sIdx);
   if(sc < 2)
      return false;

   const double pip = ActivePipValue();
   const double touchTol = InpTLTouchPips * pip;
   const double conflTol = InpTLConflPips * pip;
   const double atr = ManualATR(bars, count, InpTLATRPeriod);
   const double maxDist = (atr > 0.0 ? InpTLMaxDistATR * atr : 0.0);

   double lv[];
   CollectLevelPrices(bars, count, lv);

   const datetime refT = bars[lastClosed].time;
   const double refC = bars[lastClosed].close;
   const int minGapBars = 4;

   int made = 0;
   for(int e = sc - 1; e >= 1 && made < 2; --e)
   {
      if(sIdx[e] - sIdx[e - 1] < minGapBars)
         continue;

      const datetime t1 = bars[sIdx[e - 1]].time;
      const datetime t2 = bars[sIdx[e]].time;
      const double p1 = sPrice[e - 1];
      const double p2 = sPrice[e];
      const double proj = TLProjectAt(t1, p1, t2, p2, refT);

      if(maxDist > 0.0 && MathAbs(proj - refC) > maxDist)
         continue;   // irrelevant TL (too far from price)
      ++made;

      int touches = 0;
      for(int j = 0; j <= lastClosed; ++j)
      {
         if(bars[j].time < t2)
            continue;   // only touches on the formed line
         const double lp = TLProjectAt(t1, p1, t2, p2, bars[j].time);
         const double ex = (wantHigh ? bars[j].high : bars[j].low);
         if(MathAbs(ex - lp) <= touchTol)
            ++touches;
      }

      bool confl = false;
      for(int q = 0; q < ArraySize(lv); ++q)
      {
         if(MathAbs(lv[q] - proj) <= conflTol)
         {
            confl = true;
            break;
         }
      }
      if(!confl)
         continue;

      match.valid = true;
      match.timeframe = timeframe;
      match.mode = (bullish ? "support_tlxlvl" : "resistance_tlxlvl");
      match.firstIndex = sIdx[e - 1];
      match.secondIndex = sIdx[e];
      match.firstPrice = p1;
      match.secondPrice = p2;
      match.lineValue = proj;
      return true;
   }

   return false;
}

bool TrendlineConfluenceApplies(const string modelName)
{
   if(!InpUseTrendlineConfluence)
      return false;
   if(InpTrendlineAllEntries)
      return true;
   return (modelName == "MODEL_C_D1W4" || modelName == "D1_STORY_H4_ENTRY");
}

bool TrendlineConfluenceOK(const DataSet &ds, const TradeSignal &signal, TrendlineMatch &match)
{
   match.valid = false;
   if(!TrendlineConfluenceApplies(signal.modelName))
      return true;

   const bool bullish = (signal.direction == BIAS_BULLISH);
   const int lookbackBars = MathMax(20, InpTrendlineLookbackBars);

   if(bullish)
   {
      if(ds.h4Count > 0 && CheckTrendlineConfluenceOnTF(ds.h4, ds.h4Count, "H4", true, lookbackBars, match))
         return true;
      if(ds.h1Count > 0 && CheckTrendlineConfluenceOnTF(ds.h1, ds.h1Count, "H1", true, lookbackBars, match))
         return true;
   }
   else
   {
      if(ds.h4Count > 0 && CheckTrendlineConfluenceOnTF(ds.h4, ds.h4Count, "H4", false, lookbackBars, match))
         return true;
      if(ds.h1Count > 0 && CheckTrendlineConfluenceOnTF(ds.h1, ds.h1Count, "H1", false, lookbackBars, match))
         return true;
   }

   return false;
}

bool AddTrendlineFilteredSignal(const DataSet &ds, TradeSignal &signals[], int &signalCount, const TradeSignal &signal)
{
   TradeSignal filtered = signal;
   TrendlineMatch tl;

   if(TrendlineConfluenceOK(ds, filtered, tl))
   {
      if(TrendlineConfluenceApplies(filtered.modelName) && tl.valid)
         filtered.confidence = StringFormat("%s+TL", filtered.confidence);
      AddTradeSignal(signals, signalCount, filtered);
      return true;
   }

   if(InpVerbose)
      PrintFormat("MSNR trendline filter skipped %s", filtered.modelName);

   return false;
}

bool IsConsolidatingMarket(const DataSet &ds, string &reason)
{
   reason = "";

   if(!InpUseConsolidationFilter)
      return false;

   if(ds.h1Count < 6)
      return false;

   const int lastClosed = ds.h1Count - 2;
   if(lastClosed < 1)
      return false;

   const int lookback = MathMin(MathMax(5, InpConsolidationLookbackBars), lastClosed + 1);
   const int first = MathMax(0, lastClosed - lookback + 1);
   const double pipValue = SymbolPipValue(g_symbol);
   if(pipValue <= 0.0)
      return false;

   double highest = ds.h1[first].high;
   double lowest = ds.h1[first].low;

   for(int i = first + 1; i <= lastClosed; ++i)
   {
      highest = MathMax(highest, ds.h1[i].high);
      lowest = MathMin(lowest, ds.h1[i].low);
   }

   const double rangePips = (highest - lowest) / pipValue;
   if(rangePips <= MathMax(1.0, InpConsolidationMaxRangePips))
   {
      reason = StringFormat("range %.1f pips <= %.1f", rangePips, InpConsolidationMaxRangePips);
      return true;
   }

   return false;
}

double AccountProtectionMultiplier()
{
   if(!InpUseAccountProtection)
      return 1.0;

   const double baseBalance = MathMax(1.0, g_accountProtectionStartBalance);
   const double currentBalance = MathMax(baseBalance, AccountInfoDouble(ACCOUNT_BALANCE));
   const double profitAboveBase = MathMax(0.0, currentBalance - baseBalance);
   const double step = MathMax(1.0, InpAccountProtectionStepUsd);
   const double rawMultiplier = 1.0 + (profitAboveBase / step);
   return ClampDouble(rawMultiplier, 1.0, MathMax(1.0, InpAccountProtectionMaxMultiplier));
}

void DetectApexLevels(const MqlRates &bars[], const int count, const string timeframe, ApexLevel &levels[], int &levelCount)
{
   // MSNR_Apex v1.00 parity (Video 3, closes-only line-chart logic): strict
   // close pivots (strength 3, alternating keeping the most extreme) feed a
   // chronological BOS walk with trend + leg origins. A BOS up through the
   // active pivot high tags it Apex Resistance (AR); the pivot low that
   // launched the leg tags Apex Support (AS) on trend flip, iAB Support on
   // continuation (internal retrace causing the break). Mirror for BOS down.
   // D1/W1/MN1 only. Levels carry no freshness (indicator draws rays).
   ArrayResize(levels, 0);
   levelCount = 0;
   if(!IsHTFForApex(timeframe))
      return;
   if(count < 10)
      return;

   string tags[];
   double px[];
   datetime tm[];
   datetime conf[];
   int apexCount = 0;
   BuildApexStructure(bars, count, tags, px, tm, conf, apexCount);

   for(int k = 0; k < apexCount; ++k)
   {
      int atype;
      bool ext;
      if(tags[k] == "AR")
      {
         atype = APEX_RESISTANCE;
         ext = true;
      }
      else if(tags[k] == "AS")
      {
         atype = APEX_SUPPORT;
         ext = true;
      }
      else if(tags[k] == "iABR")
      {
         atype = IAB_RESISTANCE;
         ext = false;
      }
      else
      {
         atype = IAB_SUPPORT;
         ext = false;
      }

      int pIdx = -1, bIdx = -1;
      for(int i = 0; i < count; ++i)
      {
         if(bars[i].time == tm[k])
            pIdx = i;
         if(bars[i].time == conf[k])
            bIdx = i;
      }
      if(pIdx < 0)
         continue;
      AddApexLevel(levels, levelCount, atype, px[k], pIdx, bIdx, tm[k], ext);
   }
}

// ---------------------------------------------------------------------------
// Storyline detection
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Storyline detection (MSNR_Storyline v1.30 parity)
// ---------------------------------------------------------------------------

struct StoryPairEv
{
   datetime t;
   int dir;        // +1 bull, -1 bear
   double price;   // rejection: level price / breakout: broken level price
   int idx;        // chrono bar index of the event
   string desc;    // rejection level description
};

void AppendStoryPairEv(StoryPairEv &ev[], const datetime t, const int dir, const double price, const int idx, const string desc)
{
   ArrayResize(ev, ArraySize(ev) + 1);
   const int n = ArraySize(ev) - 1;
   ev[n].t = t;
   ev[n].dir = dir;
   ev[n].price = price;
   ev[n].idx = idx;
   ev[n].desc = desc;
}

bool EvaluateStorylinePair(const string htfName, const string ltfName, const MqlRates &htfBars[], const int htfCount, const MqlRates &ltfBars[], const int ltfCount, StorylineEvent &outEvent)
{
   // MSNR_Storyline v1.30 parity (X rejects X fresh + Y breakout):
   //  - Rejections on PLAIN S/R only (RBS/SBR excluded — v1 scope is S/R).
   //  - Zone + rejection carry InpStoryTolerancePips; rejection is
   //    CLOSE-only (no open-side requirement): support = wick in zone +
   //    close above; resistance = wick in zone + close below.
   //  - First touch only (one rejection per level max); a later candle that
   //    CLOSES THROUGH the level voids that rejection and stops tracking.
   //  - Y breakouts: EVERY Y plain S/R level's first close-through (either
   //    direction) is a BOS event. Same-direction first BOS after the
   //    rejection and within InpStoryMaxBosLagBars Y-bars confirms it.
   //  - A confirmed bias PERSISTS (a newer same-direction rejection pends as
   //    continuation, not a flip); a newer opposite rejection after the
   //    confirmation degrades that side to WAIT. WAIT/none -> invalid event.
   //  - Closed bars only; X levels formed within InpStoryLookbackX bars, Y
   //    levels within InpStoryLookbackY bars.
   outEvent.valid = false;
   if(htfCount < 10 || ltfCount < 20)
      return false;

   const double tol = InpStoryTolerancePips * ActivePipValue();
   const int lastClosedX = htfCount - 2;
   const int lastClosedY = ltfCount - 2;
   if(lastClosedX < 3 || lastClosedY < 3)
      return false;

   CandleLevel htfLevels[];
   int htfLevelCount = 0;
   DetectBaseLevels(htfBars, htfCount, htfLevels, htfLevelCount);

   CandleLevel ltfLevels[];
   int ltfLevelCount = 0;
   DetectBaseLevels(ltfBars, ltfCount, ltfLevels, ltfLevelCount);

   const int xFormedMin = htfCount - 1 - MathMax(10, InpStoryLookbackX);
   const int yFormedMin = ltfCount - 1 - MathMax(20, InpStoryLookbackY);

   // X rejections (fresh only).
   StoryPairEv rejs[];
   ArrayResize(rejs, 0);
   for(int n = 0; n < htfLevelCount; ++n)
   {
      if(htfLevels[n].levelType != LT_SUPPORT && htfLevels[n].levelType != LT_RESISTANCE)
         continue;
      const int formedBar = htfLevels[n].candleIndex + 1;
      if(formedBar < xFormedMin || formedBar > lastClosedX)
         continue;

      const bool isSup = (htfLevels[n].levelType == LT_SUPPORT);
      const double lp = htfLevels[n].price;
      const string desc = htfName + " " + (isSup ? "SUPPORT" : "RESISTANCE");

      bool touched = false;
      int rejPos = -1;
      for(int i = formedBar + 1; i <= lastClosedX; ++i)
      {
         const bool inZone = (htfBars[i].high >= lp - tol && htfBars[i].low <= lp + tol);
         const bool closedThrough = (isSup ? (htfBars[i].close < lp) : (htfBars[i].close > lp));

         // Invalidation: a close-through voids the rejection (the touch bar
         // itself can also close through -> no rejection at all).
         if(closedThrough)
         {
            if(rejPos >= 0)
            {
               for(int r = rejPos; r < ArraySize(rejs) - 1; ++r)
                  rejs[r] = rejs[r + 1];
               ArrayResize(rejs, ArraySize(rejs) - 1);
               rejPos = -1;
            }
            break;
         }

         if(!inZone || touched)
            continue;
         touched = true;   // first touch consumes freshness

         if(isSup && htfBars[i].low <= lp + tol && htfBars[i].close > lp)
         {
            rejPos = ArraySize(rejs);
            AppendStoryPairEv(rejs, htfBars[i].time, +1, lp, i, desc);
         }
         else if(!isSup && htfBars[i].high >= lp - tol && htfBars[i].close < lp)
         {
            rejPos = ArraySize(rejs);
            AppendStoryPairEv(rejs, htfBars[i].time, -1, lp, i, desc);
         }
      }
   }

   // Y breakouts: first close-through per plain Y level (closed bars only).
   StoryPairEv brks[];
   ArrayResize(brks, 0);
   for(int n = 0; n < ltfLevelCount; ++n)
   {
      if(ltfLevels[n].levelType != LT_SUPPORT && ltfLevels[n].levelType != LT_RESISTANCE)
         continue;
      const int formedBar = ltfLevels[n].candleIndex + 1;
      if(formedBar < yFormedMin || formedBar > lastClosedY)
         continue;

      const bool isSup = (ltfLevels[n].levelType == LT_SUPPORT);
      const double lp = ltfLevels[n].price;
      for(int i = formedBar + 1; i <= lastClosedY; ++i)
      {
         if(isSup && ltfBars[i].close < lp)
         {
            AppendStoryPairEv(brks, ltfBars[i].time, -1, lp, i, "");
            break;
         }
         if(!isSup && ltfBars[i].close > lp)
         {
            AppendStoryPairEv(brks, ltfBars[i].time, +1, lp, i, "");
            break;
         }
      }
   }

   // Sort breakouts oldest -> newest (required for the lag-window break).
   for(int a = 1; a < ArraySize(brks); ++a)
   {
      const StoryPairEv v = brks[a];
      int b = a - 1;
      while(b >= 0 && brks[b].t > v.t)
      {
         brks[b + 1] = brks[b];
         --b;
      }
      brks[b + 1] = v;
   }

   const ENUM_TIMEFRAMES ltfPeriod = PeriodFromTFName(ltfName);
   const int maxLagSec = MathMax(1, InpStoryMaxBosLagBars) * (int)PeriodSeconds(ltfPeriod);

   int lastBullRejK = -1, lastBearRejK = -1;
   for(int k = 0; k < ArraySize(rejs); ++k)
   {
      if(rejs[k].dir > 0 && (lastBullRejK < 0 || rejs[k].t > rejs[lastBullRejK].t))
         lastBullRejK = k;
      if(rejs[k].dir < 0 && (lastBearRejK < 0 || rejs[k].t > rejs[lastBearRejK].t))
         lastBearRejK = k;
   }

   datetime lastBullBO = 0, lastBearBO = 0;
   int bullBOK = -1, bearBOK = -1;
   for(int k = 0; k < ArraySize(rejs); ++k)
   {
      for(int b = 0; b < ArraySize(brks); ++b)
      {
         if(brks[b].dir != rejs[k].dir || brks[b].t <= rejs[k].t)
            continue;
         if((long)(brks[b].t - rejs[k].t) > maxLagSec)
            break;
         if(rejs[k].dir > 0 && brks[b].t > lastBullBO)
         {
            lastBullBO = brks[b].t;
            bullBOK = b;
         }
         if(rejs[k].dir < 0 && brks[b].t > lastBearBO)
         {
            lastBearBO = brks[b].t;
            bearBOK = b;
         }
         break;   // first BOS per rejection only
      }
   }

   const datetime lastBullRejT = (lastBullRejK >= 0 ? rejs[lastBullRejK].t : 0);
   const datetime lastBearRejT = (lastBearRejK >= 0 ? rejs[lastBearRejK].t : 0);
   const datetime bullConf = (lastBullRejK >= 0 && lastBullBO > lastBullRejT ? lastBullBO : 0);
   const datetime bearConf = (lastBearRejK >= 0 && lastBearBO > lastBearRejT ? lastBearBO : 0);

   if(bullConf > 0 && bullConf > bearConf)
   {
      if(lastBearRejT > bullConf)
         return false;   // BEAR WAIT
      outEvent.valid = true;
      outEvent.htf = htfName;
      outEvent.ltf = ltfName;
      outEvent.bias = BIAS_BULLISH;
      outEvent.rejectionPrice = rejs[lastBullRejK].price;
      outEvent.rejectionTime = rejs[lastBullRejK].t;
      outEvent.rejectionCandleIdx = rejs[lastBullRejK].idx;
      outEvent.breakoutTime = brks[bullBOK].t;
      outEvent.breakoutCandleIdx = brks[bullBOK].idx;
      outEvent.rejectionLevelDesc = rejs[lastBullRejK].desc;
      return true;
   }
   if(bearConf > 0 && bearConf > bullConf)
   {
      if(lastBullRejT > bearConf)
         return false;   // BULL WAIT
      outEvent.valid = true;
      outEvent.htf = htfName;
      outEvent.ltf = ltfName;
      outEvent.bias = BIAS_BEARISH;
      outEvent.rejectionPrice = rejs[lastBearRejK].price;
      outEvent.rejectionTime = rejs[lastBearRejK].t;
      outEvent.rejectionCandleIdx = rejs[lastBearRejK].idx;
      outEvent.breakoutTime = brks[bearBOK].t;
      outEvent.breakoutCandleIdx = brks[bearBOK].idx;
      outEvent.rejectionLevelDesc = rejs[lastBearRejK].desc;
      return true;
   }

   return false;   // WAIT / NONE
}

// ---------------------------------------------------------------------------
// FTFL / STFL / TTFL / Obstacles
// ---------------------------------------------------------------------------

double LevelSpanTop(const MqlRates &bars[], const int count, const int idx)
{
   // MSNR_TFL_Zones v1.10 parity: an S/R box spans the level price (close of
   // candle1 = body edge) to the c1/c2 extreme wick tip — candle1 + candle2
   // only (no candle3 extension).
   const int nextIdx = (idx + 1 < count ? idx + 1 : idx);
   return MathMax(bars[idx].high, bars[nextIdx].high);
}

double LevelSpanBottom(const MqlRates &bars[], const int count, const int idx)
{
   // MSNR_TFL_Zones v1.10 parity: candle1 + candle2 only (no candle3).
   const int nextIdx = (idx + 1 < count ? idx + 1 : idx);
   return MathMin(bars[idx].low, bars[nextIdx].low);
}

bool FindFTFL(const string tfName, const MqlRates &bars[], const int count, const StorylineEvent &story, FTFLZone &zone)
{
   zone.valid = false;
   zone.timeframe = tfName;
   zone.direction = story.bias;
   zone.isFresh = true;
   zone.priority = 1;

   if(count < 5 || story.bias == BIAS_NEUTRAL)
      return false;

   CandleLevel srLevels[];
   int srCount = 0;
   DetectBaseLevels(bars, count, srLevels, srCount);

   OCLLevel ocls[];
   int oclCount = 0;
   DetectOCLLevels(bars, count, tfName, ocls, oclCount);

   QMLevel qms[];
   int qmCount = 0;
   DetectQMLevels(bars, count, tfName, srLevels, srCount, qms, qmCount);

   ApexLevel apexes[];
   int apexCount = 0;
   DetectApexLevels(bars, count, tfName, apexes, apexCount);

   const int targetSrType = (story.bias == BIAS_BULLISH ? LT_SUPPORT : LT_RESISTANCE);
   const int targetQmDir  = (story.bias == BIAS_BULLISH ? QM_BULLISH : QM_BEARISH);
   const int targetIabType = (story.bias == BIAS_BULLISH ? IAB_SUPPORT : IAB_RESISTANCE);
   const int targetOclType = (story.bias == BIAS_BULLISH ? OCL_SOCL : OCL_ROCL);

   // 1. Fresh S/R
   for(int i = srCount - 1; i >= 0; --i)
   {
      if(srLevels[i].levelType == targetSrType && srLevels[i].state == LS_FRESH)
      {
         zone.valid = true;
         zone.price = srLevels[i].price;
         zone.boxTop = LevelSpanTop(bars, count, srLevels[i].candleIndex);
         zone.boxBottom = LevelSpanBottom(bars, count, srLevels[i].candleIndex);
         zone.timeFormed = srLevels[i].candleTime;
         zone.candleIndex = srLevels[i].candleIndex;
         zone.levelTypeDesc = (story.bias == BIAS_BULLISH ? "Fresh Support" : "Fresh Resistance");
         zone.priority = 2;
         return true;
      }
   }

   // 2a. Fresh QM (MSNR_QM_Taxonomy priority: abQM > iabQM > ftQM > stQM)
   int bestQm = -1;
   int bestQmRank = 99;
   for(int i = 0; i < qmCount; ++i)
   {
      if(qms[i].direction == targetQmDir && qms[i].state == LS_FRESH)
      {
         int rank = 3;
         if(qms[i].qmType == QM_ABQM)
            rank = 0;
         else if(qms[i].qmType == QM_IABQM)
            rank = 1;
         else if(qms[i].qmType == QM_FTQM)
            rank = 2;
         if(bestQm < 0 || rank < bestQmRank || (rank == bestQmRank && qms[i].breakIndex > qms[bestQm].breakIndex))
         {
            bestQm = i;
            bestQmRank = rank;
         }
      }
   }
   if(bestQm >= 0)
   {
      zone.valid = true;
      zone.price = qms[bestQm].price;
      zone.boxTop = qms[bestQm].boxHigh;
      zone.boxBottom = qms[bestQm].boxLow;
      zone.timeFormed = qms[bestQm].candleTime;
      zone.candleIndex = qms[bestQm].breakIndex;
      string qmTag = "FT";
      if(qms[bestQm].qmType == QM_ABQM)
         qmTag = "AB";
      else if(qms[bestQm].qmType == QM_IABQM)
         qmTag = "IAB";
      else if(qms[bestQm].qmType == QM_STQM)
         qmTag = "ST";
      zone.levelTypeDesc = StringFormat("%s QM", qmTag);
      zone.priority = (qms[bestQm].qmType == QM_ABQM ? 2 : 1);
      return true;
   }

   // 2b. LS OCL
   int bestLs = -1;
   for(int i = 0; i < oclCount; ++i)
   {
      if(ocls[i].oclType == OCL_LS_OCL && ocls[i].state == LS_FRESH)
      {
         if(bestLs < 0 || ocls[i].candleIndex2 > ocls[bestLs].candleIndex2)
            bestLs = i;
      }
   }
   if(bestLs >= 0)
   {
      zone.valid = true;
      zone.price = ocls[bestLs].price;
      zone.boxTop = ocls[bestLs].boxHigh;
      zone.boxBottom = ocls[bestLs].boxLow;
      zone.timeFormed = ocls[bestLs].candleTime;
      zone.candleIndex = ocls[bestLs].candleIndex2;
      zone.levelTypeDesc = "LS OCL";
      zone.priority = 1;
      return true;
   }

   // 2c. iAB
   int bestIab = -1;
   for(int i = 0; i < apexCount; ++i)
   {
      if(apexes[i].apexType == targetIabType && apexes[i].state == LS_FRESH)
      {
         if(bestIab < 0 || apexes[i].candleIndex > apexes[bestIab].candleIndex)
            bestIab = i;
      }
   }
   if(bestIab >= 0)
   {
      zone.valid = true;
      zone.price = apexes[bestIab].price;
      zone.boxTop = LevelSpanTop(bars, count, apexes[bestIab].candleIndex);
      zone.boxBottom = LevelSpanBottom(bars, count, apexes[bestIab].candleIndex);
      zone.timeFormed = apexes[bestIab].candleTime;
      zone.candleIndex = apexes[bestIab].candleIndex;
      zone.levelTypeDesc = "iAB";
      zone.priority = 1;
      return true;
   }

   // 3. 1-Lap OCL / sOCL / rOCL
   int bestOcl = -1;
   for(int i = 0; i < oclCount; ++i)
   {
      if((ocls[i].oclType == targetOclType || ocls[i].oclType == OCL_ONE_LAP) && ocls[i].state == LS_FRESH)
      {
         if(bestOcl < 0 || ocls[i].candleIndex2 > ocls[bestOcl].candleIndex2)
            bestOcl = i;
      }
   }
   if(bestOcl >= 0)
   {
      zone.valid = true;
      zone.price = ocls[bestOcl].price;
      zone.boxTop = ocls[bestOcl].boxHigh;
      zone.boxBottom = ocls[bestOcl].boxLow;
      zone.timeFormed = ocls[bestOcl].candleTime;
      zone.candleIndex = ocls[bestOcl].candleIndex2;
      zone.levelTypeDesc = "OCL";
      zone.priority = 1;
      return true;
   }

   return false;
}

bool FindSTFL(const string tfName, const MqlRates &bars[], const int count, const FTFLZone &ftfl, STFLZone &zone)
{
   zone.valid = false;
   zone.timeframe = tfName;
   zone.direction = ftfl.direction;
   zone.isInsideFTFLBox = true;
   zone.isFresh = true;

   if(count < 5)
      return false;

   CandleLevel srLevels[];
   int srCount = 0;
   DetectBaseLevels(bars, count, srLevels, srCount);

   OCLLevel ocls[];
   int oclCount = 0;
   DetectOCLLevels(bars, count, tfName, ocls, oclCount);

   QMLevel qms[];
   int qmCount = 0;
   DetectQMLevels(bars, count, tfName, srLevels, srCount, qms, qmCount);

   ApexLevel apexes[];
   int apexCount = 0;
   DetectApexLevels(bars, count, tfName, apexes, apexCount);

   const int targetSrType = (ftfl.direction == BIAS_BULLISH ? LT_SUPPORT : LT_RESISTANCE);
   const int targetQmDir  = (ftfl.direction == BIAS_BULLISH ? QM_BULLISH : QM_BEARISH);
   const int targetIabType = (ftfl.direction == BIAS_BULLISH ? IAB_SUPPORT : IAB_RESISTANCE);

   bool found = false;
   int bestRankFresh = 99;
   int bestStructRank = 99;
   int bestBoxRank = 99;   // TFL A+ parity: 0 = candidate box fully inside a
                           // fresh FTFL box (and candidate fresh), 1 = else
   int bestIdx = -1;
   string bestDesc = "";
   double bestPrice = 0.0;
   double bestTop = 0.0;
   double bestBottom = 0.0;
   datetime bestTime = 0;
   bool bestFresh = true;

   // SR inside box (strict price containment, TFL A+ parity)
   for(int i = 0; i < srCount; ++i)
   {
      if(srLevels[i].levelType == targetSrType)
      {
         if(srLevels[i].price >= ftfl.boxBottom && srLevels[i].price <= ftfl.boxTop)
         {
            const int freshRank = (srLevels[i].state == LS_FRESH ? 0 : 1);
            const int structRank = 1;
            const double candTop = LevelSpanTop(bars, count, srLevels[i].candleIndex);
            const double candBottom = LevelSpanBottom(bars, count, srLevels[i].candleIndex);
            const int boxRank = (srLevels[i].state == LS_FRESH && ftfl.isFresh && candBottom >= ftfl.boxBottom && candTop <= ftfl.boxTop ? 0 : 1);
            if(!found || freshRank < bestRankFresh || (freshRank == bestRankFresh && structRank < bestStructRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank < bestBoxRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank == bestBoxRank && srLevels[i].candleIndex > bestIdx))
            {
               found = true;
               bestRankFresh = freshRank;
               bestStructRank = structRank;
               bestBoxRank = boxRank;
               bestIdx = srLevels[i].candleIndex;
               bestPrice = srLevels[i].price;
               bestTop = candTop;
               bestBottom = candBottom;
               bestTime = srLevels[i].candleTime;
               bestDesc = (ftfl.direction == BIAS_BULLISH ? "STFL Support" : "STFL Resistance");
               bestFresh = (srLevels[i].state == LS_FRESH);
            }
         }
      }
   }

   // QM inside box (taxonomy rank ab > iab > ft > st, strict containment)
   for(int i = 0; i < qmCount; ++i)
   {
      if(qms[i].direction == targetQmDir)
      {
         if(qms[i].price >= ftfl.boxBottom && qms[i].price <= ftfl.boxTop)
         {
            const int freshRank = (qms[i].state == LS_FRESH ? 0 : 1);
            int structRank = 4;
            if(qms[i].qmType == QM_ABQM) structRank = 2;
            else if(qms[i].qmType == QM_IABQM) structRank = 3;
            const int boxRank = (qms[i].state == LS_FRESH && ftfl.isFresh && qms[i].boxLow >= ftfl.boxBottom && qms[i].boxHigh <= ftfl.boxTop ? 0 : 1);
            if(!found || freshRank < bestRankFresh || (freshRank == bestRankFresh && structRank < bestStructRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank < bestBoxRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank == bestBoxRank && qms[i].breakIndex > bestIdx))
            {
               found = true;
               bestRankFresh = freshRank;
               bestStructRank = structRank;
               bestBoxRank = boxRank;
               bestIdx = qms[i].breakIndex;
               bestPrice = qms[i].price;
               bestTop = qms[i].boxHigh;
               bestBottom = qms[i].boxLow;
               bestTime = qms[i].candleTime;
               bestDesc = "STFL QM";
               bestFresh = (qms[i].state == LS_FRESH);
            }
         }
      }
   }

   // iAB inside box (strict containment)
   for(int i = 0; i < apexCount; ++i)
   {
      if(apexes[i].apexType == targetIabType)
      {
         if(apexes[i].price >= ftfl.boxBottom && apexes[i].price <= ftfl.boxTop)
         {
            const int freshRank = (apexes[i].state == LS_FRESH ? 0 : 1);
            const int structRank = 5;
            const double candTop = LevelSpanTop(bars, count, apexes[i].candleIndex);
            const double candBottom = LevelSpanBottom(bars, count, apexes[i].candleIndex);
            const int boxRank = (apexes[i].state == LS_FRESH && ftfl.isFresh && candBottom >= ftfl.boxBottom && candTop <= ftfl.boxTop ? 0 : 1);
            if(!found || freshRank < bestRankFresh || (freshRank == bestRankFresh && structRank < bestStructRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank < bestBoxRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank == bestBoxRank && apexes[i].candleIndex > bestIdx))
            {
               found = true;
               bestRankFresh = freshRank;
               bestStructRank = structRank;
               bestBoxRank = boxRank;
               bestIdx = apexes[i].candleIndex;
               bestPrice = apexes[i].price;
               bestTop = candTop;
               bestBottom = candBottom;
               bestTime = apexes[i].candleTime;
               bestDesc = "STFL iAB";
               bestFresh = (apexes[i].state == LS_FRESH);
            }
         }
      }
   }

   for(int i = 0; i < oclCount; ++i)
   {
      if(ocls[i].oclType == OCL_LS_OCL)
      {
         if(ocls[i].price >= ftfl.boxBottom && ocls[i].price <= ftfl.boxTop)
         {
            const int freshRank = (ocls[i].state == LS_FRESH ? 0 : 1);
            const int structRank = 6;
            const int boxRank = (ocls[i].state == LS_FRESH && ftfl.isFresh && ocls[i].boxLow >= ftfl.boxBottom && ocls[i].boxHigh <= ftfl.boxTop ? 0 : 1);
            if(!found || freshRank < bestRankFresh || (freshRank == bestRankFresh && structRank < bestStructRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank < bestBoxRank) || (freshRank == bestRankFresh && structRank == bestStructRank && boxRank == bestBoxRank && ocls[i].candleIndex2 > bestIdx))
            {
               found = true;
               bestRankFresh = freshRank;
               bestStructRank = structRank;
               bestBoxRank = boxRank;
               bestIdx = ocls[i].candleIndex2;
               bestPrice = ocls[i].price;
               bestTop = ocls[i].boxHigh;
               bestBottom = ocls[i].boxLow;
               bestTime = ocls[i].candleTime;
               bestDesc = "STFL LS OCL";
               bestFresh = true;
            }
         }
      }
   }

   if(found)
   {
      zone.valid = true;
      zone.price = bestPrice;
      zone.boxTop = bestTop;
      zone.boxBottom = bestBottom;
      zone.timeFormed = bestTime;
      zone.candleIndex = bestIdx;
      zone.levelTypeDesc = bestDesc;
      zone.isFresh = bestFresh;
      return true;
   }

   // Fallback SR
   for(int i = srCount - 1; i >= 0; --i)
   {
      if(srLevels[i].levelType == targetSrType && srLevels[i].state == LS_FRESH)
      {
         zone.valid = true;
         zone.price = srLevels[i].price;
         zone.boxTop = LevelSpanTop(bars, count, srLevels[i].candleIndex);
         zone.boxBottom = LevelSpanBottom(bars, count, srLevels[i].candleIndex);
         zone.timeFormed = srLevels[i].candleTime;
         zone.candleIndex = srLevels[i].candleIndex;
         zone.levelTypeDesc = "STFL Fallback S/R";
         zone.isInsideFTFLBox = false;
         zone.isFresh = true;
         return true;
      }
   }

   // Ultimate fallback
   zone.valid = true;
   zone.price = ftfl.price;
   zone.boxTop = ftfl.boxTop;
   zone.boxBottom = ftfl.boxBottom;
   zone.timeFormed = ftfl.timeFormed;
   zone.candleIndex = ftfl.candleIndex;
   zone.levelTypeDesc = "STFL Direct Zone";
   zone.isInsideFTFLBox = true;
   zone.isFresh = true;
   return true;
}

bool FindTTFL(const string tfName, const MqlRates &bars[], const int count, const STFLZone &stfl, TTFLRefinement &ref)
{
   ref.valid = false;
   ref.timeframe = tfName;
   ref.direction = stfl.direction;
   ref.isFresh = true;

   if(count < 5)
   {
      ref.valid = true;
      ref.entryPrice = (stfl.boxTop + stfl.boxBottom) / 2.0;
      ref.slReference = (stfl.direction == BIAS_BULLISH ? stfl.boxBottom : stfl.boxTop);
      ref.entryType = ENTRY_EQUILIBRIUM;
      ref.description = "STFL Equilibrium Fallback";
      return true;
   }

   CandleLevel srLevels[];
   int srCount = 0;
   DetectBaseLevels(bars, count, srLevels, srCount);

   QMLevel qms[];
   int qmCount = 0;
   DetectQMLevels(bars, count, tfName, srLevels, srCount, qms, qmCount);

   const int targetSrType = (stfl.direction == BIAS_BULLISH ? LT_SUPPORT : LT_RESISTANCE);
   const int targetQmDir  = (stfl.direction == BIAS_BULLISH ? QM_BULLISH : QM_BEARISH);

   for(int i = 0; i < srCount; ++i)
   {
      if(srLevels[i].levelType == targetSrType)
      {
         if(srLevels[i].price >= stfl.boxBottom && srLevels[i].price <= stfl.boxTop)
         {
            ref.valid = true;
            ref.entryPrice = srLevels[i].price;
            ref.slReference = (stfl.direction == BIAS_BULLISH ? stfl.boxBottom : stfl.boxTop);
            ref.entryType = ENTRY_KEY_LEVEL;
            ref.description = "TTFL SR";
            return true;
         }
      }
   }

   for(int i = 0; i < qmCount; ++i)
   {
      if(qms[i].direction == targetQmDir)
      {
         if(qms[i].price >= stfl.boxBottom && qms[i].price <= stfl.boxTop)
         {
            ref.valid = true;
            ref.entryPrice = qms[i].price;
            ref.slReference = (stfl.direction == BIAS_BULLISH ? stfl.boxBottom : stfl.boxTop);
            ref.entryType = ENTRY_KEY_LEVEL;
            ref.description = "TTFL QM";
            return true;
         }
      }
   }

   ref.valid = true;
   ref.entryPrice = (stfl.boxTop + stfl.boxBottom) / 2.0;
   ref.slReference = (stfl.direction == BIAS_BULLISH ? stfl.boxBottom : stfl.boxTop);
   ref.entryType = ENTRY_EQUILIBRIUM;
   ref.description = "STFL Equilibrium (50% Midpoint)";
   return true;
}

void ScanObstacles(const string tfName, const MqlRates &bars[], const int count, const double entryPrice, const int direction, double &targets[], int &targetCount)
{
   ArrayResize(targets, 0);
   targetCount = 0;
   if(count < 10)
      return;

   CandleLevel srLevels[];
   int srCount = 0;
   DetectBaseLevels(bars, count, srLevels, srCount);

   ApexLevel apexes[];
   int apexCount = 0;
   DetectApexLevels(bars, count, tfName, apexes, apexCount);

   if(direction == BIAS_BULLISH)
   {
      for(int i = 0; i < srCount; ++i)
      {
         if((srLevels[i].levelType == LT_RESISTANCE || srLevels[i].levelType == LT_SBR) && srLevels[i].price > entryPrice)
         {
            ArrayResize(targets, targetCount + 1);
            targets[targetCount++] = srLevels[i].price;
         }
      }

      for(int i = 0; i < apexCount; ++i)
      {
         if(apexes[i].price > entryPrice)
         {
            if(apexes[i].apexType == APEX_RESISTANCE || apexes[i].apexType == IAB_RESISTANCE)
            {
               ArrayResize(targets, targetCount + 1);
               targets[targetCount++] = apexes[i].price;
            }
         }
      }

      const int tail = MathMax(0, count - 50);
      double recentHigh = bars[tail].high;
      for(int i = tail; i < count; ++i)
         recentHigh = MathMax(recentHigh, bars[i].high);
      if(recentHigh > entryPrice)
      {
         ArrayResize(targets, targetCount + 1);
         targets[targetCount++] = recentHigh;
      }

      for(int i = 0; i < targetCount - 1; ++i)
      {
         for(int j = i + 1; j < targetCount; ++j)
         {
            if(targets[j] < targets[i])
            {
               double tmp = targets[i];
               targets[i] = targets[j];
               targets[j] = tmp;
            }
         }
      }
   }
   else
   {
      for(int i = 0; i < srCount; ++i)
      {
         if((srLevels[i].levelType == LT_SUPPORT || srLevels[i].levelType == LT_RBS) && srLevels[i].price < entryPrice)
         {
            ArrayResize(targets, targetCount + 1);
            targets[targetCount++] = srLevels[i].price;
         }
      }

      for(int i = 0; i < apexCount; ++i)
      {
         if(apexes[i].price < entryPrice)
         {
            if(apexes[i].apexType == APEX_SUPPORT || apexes[i].apexType == IAB_SUPPORT)
            {
               ArrayResize(targets, targetCount + 1);
               targets[targetCount++] = apexes[i].price;
            }
         }
      }

      const int tail = MathMax(0, count - 50);
      double recentLow = bars[tail].low;
      for(int i = tail; i < count; ++i)
         recentLow = MathMin(recentLow, bars[i].low);
      if(recentLow < entryPrice)
      {
         ArrayResize(targets, targetCount + 1);
         targets[targetCount++] = recentLow;
      }

      for(int i = 0; i < targetCount - 1; ++i)
      {
         for(int j = i + 1; j < targetCount; ++j)
         {
            if(targets[j] > targets[i])
            {
               double tmp = targets[i];
               targets[i] = targets[j];
               targets[j] = tmp;
            }
         }
      }
   }
}

// ---------------------------------------------------------------------------
// Risk sizing and order placement
// ---------------------------------------------------------------------------

void BuildPositionPlan(const string symbol, const int direction, const double entryPrice, const double slReference, const double finalTp, const double obstacleTp, const double riskMultiplier, const string modelName, PositionPlan &plan)
{
   const bool isBullish = (direction == BIAS_BULLISH);
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const double pipVal = SymbolPipValue(symbol);
   double bufferPts = 10.0;
   const double slPoints = MathMax(1.0, (double)InpStopLossPips);
   const double tpPoints = MathMax(1.0, (double)InpTakeProfitPips);

   if(IsGoldSymbol(symbol))
   {
      bufferPts = 30.0;
   }

   const double bufferOffset = bufferPts * pipVal;
   const double bufferedEntry = (isBullish ? entryPrice + bufferOffset : entryPrice - bufferOffset);

   const double stopLoss = (isBullish ? bufferedEntry - (slPoints * pipVal) : bufferedEntry + (slPoints * pipVal));
   double takeProfit = 0.0;

   if(InpUseFixedSLTP)
   {
      takeProfit = (isBullish ? bufferedEntry + (tpPoints * pipVal) : bufferedEntry - (tpPoints * pipVal));
   }
   else
   {
      const double dynamicTpRef = (obstacleTp > 0.0 ? obstacleTp : finalTp);

      if(isBullish && dynamicTpRef > 0.0)
         takeProfit = dynamicTpRef;
      else if(!isBullish && dynamicTpRef > 0.0)
         takeProfit = dynamicTpRef;
      else
         takeProfit = (isBullish ? bufferedEntry + (tpPoints * pipVal) : bufferedEntry - (tpPoints * pipVal));
   }

   const double contractSize = SymbolContractSize(symbol);
   const double riskPerLot = slPoints * pipVal * contractSize;
   const double protectionMult = AccountProtectionMultiplier();
   const double lots = NormalizeVolumeByStep(symbol, MathMax(0.0, InpLotSize) * MathMax(0.0, riskMultiplier) * protectionMult);
   const double actualRiskUsd = lots * riskPerLot;
   const double actualRiskPercent = (equity > 0.0 ? (actualRiskUsd / equity) * 100.0 : 0.0);

   plan.symbol = symbol;
   plan.direction = direction;
   plan.rawEntry = NormalizePriceByDigits(symbol, entryPrice);
   plan.bufferedEntry = NormalizePriceByDigits(symbol, bufferedEntry);
   plan.stopLoss = NormalizePriceByDigits(symbol, stopLoss);
   plan.slPoints = slPoints;
   plan.takeProfit = NormalizePriceByDigits(symbol, takeProfit);
   plan.obstacleTp = (obstacleTp > 0.0 ? NormalizePriceByDigits(symbol, obstacleTp) : 0.0);
   plan.riskAmountUsd = NormalizeDouble(actualRiskUsd, 2);
   plan.lotSize = lots;
   plan.riskPercent = NormalizeDouble(actualRiskPercent, 2);
   plan.modelName = modelName;
}

string MakeOrderComment(const string modelName, const string leg, const double obstacleTp)
{
   if(obstacleTp > 0.0)
      return StringFormat("MSNR|%s|%s|O:%.1f", modelName, leg, obstacleTp);
   return StringFormat("MSNR|%s|%s", modelName, leg);
}

string DealEntryToString(const ENUM_DEAL_ENTRY entry)
{
   switch(entry)
   {
      case DEAL_ENTRY_IN: return "IN";
      case DEAL_ENTRY_OUT: return "OUT";
      case DEAL_ENTRY_INOUT: return "INOUT";
      case DEAL_ENTRY_OUT_BY: return "OUT_BY";
      default: return "UNKNOWN";
   }
}

string DealTypeToString(const ENUM_DEAL_TYPE type)
{
   switch(type)
   {
      case DEAL_TYPE_BUY: return "BUY";
      case DEAL_TYPE_SELL: return "SELL";
      case DEAL_TYPE_BALANCE: return "BALANCE";
      case DEAL_TYPE_CREDIT: return "CREDIT";
      case DEAL_TYPE_CHARGE: return "CHARGE";
      case DEAL_TYPE_CORRECTION: return "CORRECTION";
      case DEAL_TYPE_BONUS: return "BONUS";
      case DEAL_TYPE_COMMISSION: return "COMMISSION";
      case DEAL_TYPE_COMMISSION_DAILY: return "COMMISSION_DAILY";
      case DEAL_TYPE_COMMISSION_MONTHLY: return "COMMISSION_MONTHLY";
      case DEAL_TYPE_COMMISSION_AGENT_DAILY: return "COMMISSION_AGENT_DAILY";
      case DEAL_TYPE_COMMISSION_AGENT_MONTHLY: return "COMMISSION_AGENT_MONTHLY";
      case DEAL_TYPE_INTEREST: return "INTEREST";
      case DEAL_TYPE_BUY_CANCELED: return "BUY_CANCELED";
      case DEAL_TYPE_SELL_CANCELED: return "SELL_CANCELED";
      default: return "UNKNOWN";
   }
}

void AppendTradeHistoryRow(const ulong dealTicket)
{
   if(!InpExportTradeHistory || dealTicket == 0)
      return;

   if(!HistorySelect(0, TimeCurrent() + 60))
      return;

   const long dealMagic = (long)HistoryDealGetInteger(dealTicket, DEAL_MAGIC);
   if(dealMagic != InpMagic)
      return;

   const string symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
   const datetime dealTime = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
   const ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   const ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(dealTicket, DEAL_TYPE);
   const double volume = HistoryDealGetDouble(dealTicket, DEAL_VOLUME);
   const double price = HistoryDealGetDouble(dealTicket, DEAL_PRICE);
   const double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
   const double commission = HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
   const double swap = HistoryDealGetDouble(dealTicket, DEAL_SWAP);
   const double sl = HistoryDealGetDouble(dealTicket, DEAL_SL);
   const double tp = HistoryDealGetDouble(dealTicket, DEAL_TP);
   const string comment = HistoryDealGetString(dealTicket, DEAL_COMMENT);
   const long positionId = (long)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);

   int fh = FileOpen(InpTradeHistoryFile, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(fh == INVALID_HANDLE)
      return;

   if(FileSize(fh) == 0)
   {
      FileWrite(fh, "time", "symbol", "deal_ticket", "position_id", "entry", "type", "volume", "price", "sl", "tp", "profit", "commission", "swap", "magic", "comment");
   }

   FileSeek(fh, 0, SEEK_END);
   FileWrite(fh,
             TimeToString(dealTime, TIME_DATE | TIME_SECONDS),
             symbol,
             (string)dealTicket,
             (string)positionId,
             DealEntryToString(entry),
             DealTypeToString(type),
             DoubleToString(volume, 2),
             DoubleToString(price, (int)SymbolDigitsValue(symbol)),
             DoubleToString(sl, (int)SymbolDigitsValue(symbol)),
             DoubleToString(tp, (int)SymbolDigitsValue(symbol)),
             DoubleToString(profit, 2),
             DoubleToString(commission, 2),
             DoubleToString(swap, 2),
             (string)dealMagic,
             comment);
   FileClose(fh);
}

bool SendPendingOrder(const PositionPlan &plan, const string leg)
{
   const bool isBuy = (plan.direction == BIAS_BULLISH);
   const string comment = MakeOrderComment(plan.modelName, leg, plan.obstacleTp);
   const double bid = SymbolInfoDouble(plan.symbol, SYMBOL_BID);
   const double ask = SymbolInfoDouble(plan.symbol, SYMBOL_ASK);
   const double point = SymbolPointValue(plan.symbol);
   const double minDist = (double)SymbolStopsLevelPoints(plan.symbol) * point;
   const bool useStopOrder = (isBuy ? (plan.bufferedEntry >= ask + minDist) : (plan.bufferedEntry <= bid - minDist));

   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFillingBySymbol(plan.symbol);

   bool ok = false;
   if(isBuy)
   {
      if(useStopOrder)
         ok = g_trade.BuyStop(plan.lotSize, plan.bufferedEntry, plan.symbol, plan.stopLoss, plan.takeProfit, ORDER_TIME_GTC, 0, comment);
      else
         ok = g_trade.BuyLimit(plan.lotSize, plan.bufferedEntry, plan.symbol, plan.stopLoss, plan.takeProfit, ORDER_TIME_GTC, 0, comment);
   }
   else
   {
      if(useStopOrder)
         ok = g_trade.SellStop(plan.lotSize, plan.bufferedEntry, plan.symbol, plan.stopLoss, plan.takeProfit, ORDER_TIME_GTC, 0, comment);
      else
         ok = g_trade.SellLimit(plan.lotSize, plan.bufferedEntry, plan.symbol, plan.stopLoss, plan.takeProfit, ORDER_TIME_GTC, 0, comment);
   }

   if(!ok && InpVerbose)
      PrintFormat("MSNR order failed: %s | %s | type=%s", plan.modelName, g_trade.ResultRetcodeDescription(), (useStopOrder ? (isBuy ? "BUY_STOP" : "SELL_STOP") : (isBuy ? "BUY_LIMIT" : "SELL_LIMIT")));

   return ok;
}

bool HasOpenPosition(const string symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   }

   return false;
}

bool CancelPendingOrders(const string symbol)
{
   for(int i = OrdersTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(!OrderSelect(ticket))
         continue;
      if(OrderGetString(ORDER_SYMBOL) != symbol)
         continue;
      if((long)OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;

      const ENUM_ORDER_TYPE orderType = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      switch(orderType)
      {
         case ORDER_TYPE_BUY_LIMIT:
         case ORDER_TYPE_SELL_LIMIT:
         case ORDER_TYPE_BUY_STOP:
         case ORDER_TYPE_SELL_STOP:
         case ORDER_TYPE_BUY_STOP_LIMIT:
         case ORDER_TYPE_SELL_STOP_LIMIT:
         {
            MqlTradeRequest req;
            MqlTradeResult  res;
            ZeroMemory(req);
            ZeroMemory(res);

            req.action = TRADE_ACTION_REMOVE;
            req.order = ticket;
            req.symbol = symbol;
            req.magic = (ulong)InpMagic;

            if(!OrderSend(req, res) && InpVerbose)
               PrintFormat("MSNR pending cancel failed ticket=%I64u", ticket);
            break;
         }
         default:
            break;
      }
   }

   return true;
}

double ParseObstacleFromComment(const string comment)
{
   const int pos = StringFind(comment, "O:");
   if(pos < 0)
      return 0.0;
   string tail = StringSubstr(comment, pos + 2);
   const int end = StringFind(tail, "|");
   if(end >= 0)
      tail = StringSubstr(tail, 0, end);
   return StringToDouble(tail);
}

bool ModifyPositionSLTP(const ulong ticket, const double sl, const double tp)
{
   if(!PositionSelectByTicket(ticket))
      return false;

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action = TRADE_ACTION_SLTP;
   req.position = ticket;
   req.symbol = PositionGetString(POSITION_SYMBOL);
   req.sl = sl;
   req.tp = tp;
   req.magic = (ulong)InpMagic;

   if(!OrderSend(req, res))
      return false;

   return (res.retcode == TRADE_RETCODE_DONE);
}

bool ClosePartialPositionByTicket(const ulong ticket, const double volume)
{
   if(!PositionSelectByTicket(ticket))
      return false;

   const string symbol = PositionGetString(POSITION_SYMBOL);
   const int type = (int)PositionGetInteger(POSITION_TYPE);
   const bool isBuy = (type == POSITION_TYPE_BUY);
   const double currentVol = PositionGetDouble(POSITION_VOLUME);

   const double minVol = SymbolVolumeMin(symbol);
   const double closeVol = NormalizeVolumeByStep(symbol, volume);
   if(closeVol < minVol || closeVol >= currentVol)
      return false;

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   req.action = TRADE_ACTION_DEAL;
   req.position = ticket;
   req.symbol = symbol;
   req.volume = closeVol;
   req.type = (isBuy ? ORDER_TYPE_SELL : ORDER_TYPE_BUY);
   req.price = (isBuy ? SymbolInfoDouble(symbol, SYMBOL_BID) : SymbolInfoDouble(symbol, SYMBOL_ASK));
   req.deviation = 20;
   req.magic = (ulong)InpMagic;
   req.comment = "MSNR_PARTIAL";

   if(!OrderSend(req, res))
      return false;

   return (res.retcode == TRADE_RETCODE_DONE);
}

void ManageOpenPositions()
{
   if(!InpManagePartialProfits && !InpMoveToBreakeven)
      return;

   const double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   const double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   const double point = SymbolPointValue(g_symbol);

   for(int i = PositionsTotal() - 1; i >= 0; --i)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;

      const int posType = (int)PositionGetInteger(POSITION_TYPE);
      const bool isBuy = (posType == POSITION_TYPE_BUY);
      const string comment = PositionGetString(POSITION_COMMENT);
      const double obstacleTp = ParseObstacleFromComment(comment);

      const string partialGvName = StringFormat("MSNR_PARTIAL_%I64u", ticket);
      const string beGvName = StringFormat("MSNR_BE_%I64u", ticket);
      const double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      const double currentSl = PositionGetDouble(POSITION_SL);
      const double riskDistance = MathAbs(openPrice - currentSl);
      const double favorableMove = (isBuy ? (bid - openPrice) : (openPrice - ask));
      const bool obstacleHit = (obstacleTp > 0.0 && (isBuy ? (bid >= obstacleTp) : (ask <= obstacleTp)));
      const double beRR = MathMax(0.1, InpBreakevenRR);
      const double beTrigger = riskDistance * beRR;
      const int beBufferPts = MathMax(0, InpBreakevenBufferPoints);
      const bool beFallback = (riskDistance > 0.0 && favorableMove >= beTrigger);

      bool partialDone = GlobalVariableCheck(partialGvName);
      bool beDone = GlobalVariableCheck(beGvName);

      if(InpManagePartialProfits && obstacleHit && !partialDone)
      {
         const double currentVol = PositionGetDouble(POSITION_VOLUME);
         const double partialVol = NormalizeVolumeByStep(g_symbol, currentVol * 0.8);
         if(partialVol >= SymbolVolumeMin(g_symbol) && partialVol < currentVol)
         {
            if(ClosePartialPositionByTicket(ticket, partialVol))
            {
               GlobalVariableSet(partialGvName, 1.0);
               partialDone = true;

               if(InpVerbose)
                  PrintFormat("MSNR partial close ticket=%I64u at %.5f", ticket, obstacleTp);
            }
         }
      }

      if(InpMoveToBreakeven && !beDone && beFallback)
      {
         const double beBuffer = (double)beBufferPts * point;
         const double beSl = (isBuy ? openPrice + beBuffer : openPrice - beBuffer);
         const double currentTp = PositionGetDouble(POSITION_TP);
         if(ModifyPositionSLTP(ticket, NormalizePriceByDigits(g_symbol, beSl), currentTp))
         {
            GlobalVariableSet(beGvName, 1.0);
            if(InpVerbose)
               PrintFormat("MSNR breakeven set ticket=%I64u at %.5f", ticket, beSl);
         }
      }
   }
}

// ---------------------------------------------------------------------------
// Signal engine
// ---------------------------------------------------------------------------

int BarsSinceStorylineOnBars(const StorylineEvent &story, const MqlRates &bars[], const int count)
{
   if(count <= 0)
      return 0;

   int breakoutIdx = -1;
   for(int i = 0; i < count; ++i)
   {
      if(bars[i].time >= story.breakoutTime)
      {
         breakoutIdx = i;
         break;
      }
   }
   if(breakoutIdx < 0)
      return 0;
   return MathMax(0, count - 1 - breakoutIdx);
}

int BarsSinceStoryline(const StorylineEvent &story, const string ftflTf, const DataSet &ds)
{
   if(ftflTf == "MN1" || ftflTf == "MN" || ftflTf == "M1")
      return BarsSinceStorylineOnBars(story, ds.mn1, ds.mn1Count);
   if(ftflTf == "W1")
      return BarsSinceStorylineOnBars(story, ds.w1, ds.w1Count);
   if(ftflTf == "D1")
      return BarsSinceStorylineOnBars(story, ds.d1, ds.d1Count);
   if(ftflTf == "H4")
      return BarsSinceStorylineOnBars(story, ds.h4, ds.h4Count);
   if(ftflTf == "H1")
      return BarsSinceStorylineOnBars(story, ds.h1, ds.h1Count);
   return 0;
}

bool BuildCascadeSignal(const StorylineEvent &story, const string symbol, const string modelName, const string ftflTf, const string stflTf, const string ttflTf, const string obsTf, const DataSet &ds, const double riskMult, string confidence, TradeSignal &outSignal)
{
   FTFLZone ftfl;
   bool ftflOk = false;
   if(ftflTf == "MN1" || ftflTf == "MN" || ftflTf == "M1")
      ftflOk = FindFTFL(ftflTf, ds.mn1, ds.mn1Count, story, ftfl);
   else if(ftflTf == "W1")
      ftflOk = FindFTFL(ftflTf, ds.w1, ds.w1Count, story, ftfl);
   else if(ftflTf == "D1")
      ftflOk = FindFTFL(ftflTf, ds.d1, ds.d1Count, story, ftfl);
   else if(ftflTf == "H4")
      ftflOk = FindFTFL(ftflTf, ds.h4, ds.h4Count, story, ftfl);
   else if(ftflTf == "H1")
      ftflOk = FindFTFL(ftflTf, ds.h1, ds.h1Count, story, ftfl);
   if(!ftflOk)
      return false;

   if(ftfl.priority != 2)
      confidence = "B";

   int barsSince = BarsSinceStoryline(story, ftflTf, ds);
   double adjustedRiskMult = riskMult;
   if(barsSince > 1)
   {
      adjustedRiskMult = MathMin(adjustedRiskMult, 0.2);
      confidence = "B-";
   }

   STFLZone stfl;
   bool stflOk = false;
   if(stflTf == "MN1" || stflTf == "MN" || stflTf == "M1")
      stflOk = FindSTFL(stflTf, ds.mn1, ds.mn1Count, ftfl, stfl);
   else if(stflTf == "W1")
      stflOk = FindSTFL(stflTf, ds.w1, ds.w1Count, ftfl, stfl);
   else if(stflTf == "D1")
      stflOk = FindSTFL(stflTf, ds.d1, ds.d1Count, ftfl, stfl);
   else if(stflTf == "H4")
      stflOk = FindSTFL(stflTf, ds.h4, ds.h4Count, ftfl, stfl);
   else if(stflTf == "H1")
      stflOk = FindSTFL(stflTf, ds.h1, ds.h1Count, ftfl, stfl);
   if(!stflOk)
      return false;

   TTFLRefinement ttfl;
   bool ttflOk = false;
   if(ttflTf == "MN1" || ttflTf == "MN" || ttflTf == "M1")
      ttflOk = FindTTFL(ttflTf, ds.mn1, ds.mn1Count, stfl, ttfl);
   else if(ttflTf == "W1")
      ttflOk = FindTTFL(ttflTf, ds.w1, ds.w1Count, stfl, ttfl);
   else if(ttflTf == "D1")
      ttflOk = FindTTFL(ttflTf, ds.d1, ds.d1Count, stfl, ttfl);
   else if(ttflTf == "H4")
      ttflOk = FindTTFL(ttflTf, ds.h4, ds.h4Count, stfl, ttfl);
   else if(ttflTf == "H1")
      ttflOk = FindTTFL(ttflTf, ds.h1, ds.h1Count, stfl, ttfl);
   if(!ttflOk)
      return false;

   double obstacleTargets[];
   int obstacleCount = 0;
   if(obsTf == "MN1" || obsTf == "MN" || obsTf == "M1")
      ScanObstacles(obsTf, ds.mn1, ds.mn1Count, ttfl.entryPrice, ttfl.direction, obstacleTargets, obstacleCount);
   else if(obsTf == "W1")
      ScanObstacles(obsTf, ds.w1, ds.w1Count, ttfl.entryPrice, ttfl.direction, obstacleTargets, obstacleCount);
   else if(obsTf == "D1")
      ScanObstacles(obsTf, ds.d1, ds.d1Count, ttfl.entryPrice, ttfl.direction, obstacleTargets, obstacleCount);
   else if(obsTf == "H4")
      ScanObstacles(obsTf, ds.h4, ds.h4Count, ttfl.entryPrice, ttfl.direction, obstacleTargets, obstacleCount);
   else if(obsTf == "H1")
      ScanObstacles(obsTf, ds.h1, ds.h1Count, ttfl.entryPrice, ttfl.direction, obstacleTargets, obstacleCount);

   const bool isContinuation = (ttfl.direction == story.bias);
   double finalTp = 0.0;
   double obstacleTp = 0.0;

   if(obstacleCount > 0)
   {
      if(isContinuation)
      {
         finalTp = obstacleTargets[obstacleCount - 1];
         if(obstacleCount > 1)
            obstacleTp = obstacleTargets[0];
      }
      else
      {
         finalTp = obstacleTargets[0];
      }
   }
   else
   {
      finalTp = (story.rejectionPrice > 0.0 ? story.rejectionPrice : (ttfl.direction == BIAS_BULLISH ? ttfl.entryPrice + 30.0 : ttfl.entryPrice - 30.0));
   }

   PositionPlan primary;
   BuildPositionPlan(symbol, ttfl.direction, ttfl.entryPrice, ttfl.slReference, finalTp, obstacleTp, adjustedRiskMult, modelName + "_primary", primary);

   PositionPlan secondary;
   bool hasSecondary = false;
   if(ttfl.entryType == ENTRY_EQUILIBRIUM)
   {
      const double bodyPrice = stfl.price;
      if(MathAbs(bodyPrice - ttfl.entryPrice) > 0.5)
      {
         BuildPositionPlan(symbol, ttfl.direction, bodyPrice, ttfl.slReference, finalTp, obstacleTp, adjustedRiskMult * 0.3, modelName + "_body30", secondary);
         BuildPositionPlan(symbol, ttfl.direction, ttfl.entryPrice, ttfl.slReference, finalTp, obstacleTp, adjustedRiskMult * 0.7, modelName + "_eq70", primary);
         hasSecondary = true;
      }
   }

   outSignal.modelName = modelName;
   outSignal.symbol = symbol;
   outSignal.direction = ttfl.direction;
   outSignal.storylineKey = story.htf + "_" + story.ltf;
   outSignal.storylineDesc = story.htf + "/" + story.ltf + " " + (story.bias == BIAS_BULLISH ? "BULLISH" : "BEARISH");
   outSignal.storylineRejection = story.rejectionPrice;
   outSignal.ftflTf = ftflTf;
   outSignal.stflTf = stflTf;
   outSignal.ttflTf = ttflTf;
   outSignal.primary = primary;
   outSignal.secondary = secondary;
   outSignal.hasSecondary = hasSecondary;
   outSignal.confidence = confidence;
   outSignal.rationale = ftflTf + " -> " + stflTf + " -> " + ttflTf;
   outSignal.formationTime = ftfl.timeFormed;
   outSignal.ftflBoxTop = ftfl.boxTop;
   outSignal.ftflBoxBottom = ftfl.boxBottom;
   outSignal.stflBoxTop = stfl.boxTop;
   outSignal.stflBoxBottom = stfl.boxBottom;
   outSignal.distanceToEntry = MathAbs(primary.bufferedEntry - GetCurrentClose(ds));
   outSignal.priorityRank = 0;
   return true;
}

bool EvaluateModelB(const string symbol, const DataSet &ds, const int direction, TradeSignal &outSignal)
{
   if(ds.h1Count < 20)
      return false;

   CandleLevel levels[];
   int levelCount = 0;
   DetectBaseLevels(ds.h1, ds.h1Count, levels, levelCount);

   const int scanStart = MathMax(0, ds.h1Count - 12);
   for(int i = scanStart; i < ds.h1Count - 1; ++i)
   {
      const bool bullish = (direction == BIAS_BULLISH);

      for(int n = 0; n < levelCount; ++n)
      {
         if(levels[n].candleIndex >= i)
            continue;
         if(levels[n].state == LS_BROKEN)
            continue;

         if(bullish)
         {
            if(levels[n].levelType != LT_SUPPORT && levels[n].levelType != LT_RBS)
               continue;
            if(!(ds.h1[i].low <= levels[n].price && ds.h1[i].close > levels[n].price))
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h1, ds.h1Count, i, true, swingTarget, swingIdx))
               continue;

            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h1Count, i + 20); ++k)
            {
               if(ds.h1[k].close > swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = MathMax(ds.h1[i].high, ds.h1[i].open);
            const double boxBottom = MathMin(ds.h1[i].low, ds.h1[i].close);
            const double eqPrice = (boxTop + boxBottom) / 2.0;
            PositionPlan p70, p30;
            BuildPositionPlan(symbol, BIAS_BULLISH, eqPrice, boxBottom, eqPrice + 30.0, 0.0, 0.7, "MODEL_B_14B", p70);
            BuildPositionPlan(symbol, BIAS_BULLISH, ds.h1[i].close, boxBottom, ds.h1[i].close + 30.0, 0.0, 0.3, "MODEL_B_14B", p30);

            outSignal.modelName = "MODEL_B_14B";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BULLISH;
            outSignal.storylineKey = "CONFIRMATION";
            outSignal.storylineDesc = "1H reject 1H SUPPORT + breakout";
            outSignal.storylineRejection = levels[n].price;
            outSignal.ftflTf = "H1";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p70;
            outSignal.secondary = p30;
            outSignal.hasSecondary = true;
            outSignal.confidence = "A";
            outSignal.rationale = "Model B bullish";
            outSignal.distanceToEntry = MathAbs(p70.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
         else
         {
            if(levels[n].levelType != LT_RESISTANCE && levels[n].levelType != LT_SBR)
               continue;
            if(!(ds.h1[i].high >= levels[n].price && ds.h1[i].close < levels[n].price))
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h1, ds.h1Count, i, false, swingTarget, swingIdx))
               continue;

            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h1Count, i + 20); ++k)
            {
               if(ds.h1[k].close < swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = MathMax(ds.h1[i].high, ds.h1[i].close);
            const double boxBottom = MathMin(ds.h1[i].low, ds.h1[i].open);
            const double eqPrice = (boxTop + boxBottom) / 2.0;
            PositionPlan p70, p30;
            BuildPositionPlan(symbol, BIAS_BEARISH, eqPrice, boxTop, eqPrice - 30.0, 0.0, 0.7, "MODEL_B_14B", p70);
            BuildPositionPlan(symbol, BIAS_BEARISH, ds.h1[i].close, boxTop, ds.h1[i].close - 30.0, 0.0, 0.3, "MODEL_B_14B", p30);

            outSignal.modelName = "MODEL_B_14B";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BEARISH;
            outSignal.storylineKey = "CONFIRMATION";
            outSignal.storylineDesc = "1H reject 1H RESISTANCE + breakout";
            outSignal.storylineRejection = levels[n].price;
            outSignal.ftflTf = "H1";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p70;
            outSignal.secondary = p30;
            outSignal.hasSecondary = true;
            outSignal.confidence = "A";
            outSignal.rationale = "Model B bearish";
            outSignal.distanceToEntry = MathAbs(p70.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
      }
   }

   return false;
}

bool EvaluateModelC_D1W4(const string symbol, const DataSet &ds, TradeSignal &outSignal)
{
   if(ds.d1Count < 10 || ds.h1Count < 10)
      return false;

   BiasDirection overallBias = BIAS_NEUTRAL;
   // Use whichever active storyline exists first; this mirrors Python's first non-neutral bias.
   StorylineEvent story;
   if(EvaluateStorylinePair("MN1", "W1", ds.mn1, ds.mn1Count, ds.w1, ds.w1Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   else if(EvaluateStorylinePair("W1", "D1", ds.w1, ds.w1Count, ds.d1, ds.d1Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   else if(EvaluateStorylinePair("D1", "H4", ds.d1, ds.d1Count, ds.h4, ds.h4Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   if(overallBias == BIAS_NEUTRAL)
      return false;

   CandleLevel d1Levels[];
   int d1Count = 0;
   DetectBaseLevels(ds.d1, ds.d1Count, d1Levels, d1Count);

   const int scanStart = MathMax(0, ds.h1Count - 8);
   for(int i = scanStart; i < ds.h1Count; ++i)
   {
      const bool bullish = (overallBias == BIAS_BULLISH);
      for(int n = 0; n < d1Count; ++n)
      {
         if(bullish)
         {
            if(d1Levels[n].levelType != LT_SUPPORT && d1Levels[n].levelType != LT_RBS)
               continue;
            if(!IsSingleCandleMitigation(ds.h1[i], d1Levels[n].price, true))
               continue;
            if(i < 5)
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h1, ds.h1Count, i, true, swingTarget, swingIdx))
               continue;
            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h1Count, i + 15); ++k)
            {
               if(ds.h1[k].close > swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = ds.h1[i].high;
            const double boxBottom = d1Levels[n].price;
            const double eqEntry = (boxTop + boxBottom) / 2.0;
            PositionPlan p;
            BuildPositionPlan(symbol, BIAS_BULLISH, eqEntry, boxBottom - 0.5, eqEntry + 30.0, 0.0, 1.0, "MODEL_C_D1W4", p);
            outSignal.modelName = "MODEL_C_D1W4";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BULLISH;
            outSignal.storylineKey = "D1W4_RETRACEMENT";
            outSignal.storylineDesc = "1H mitigates D1 support";
            outSignal.storylineRejection = d1Levels[n].price;
            outSignal.ftflTf = "D1";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p;
            outSignal.hasSecondary = false;
            outSignal.confidence = "A";
            outSignal.rationale = "Model C D1W4 bullish";
            outSignal.distanceToEntry = MathAbs(p.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
         else
         {
            if(d1Levels[n].levelType != LT_RESISTANCE && d1Levels[n].levelType != LT_SBR)
               continue;
            if(!IsSingleCandleMitigation(ds.h1[i], d1Levels[n].price, false))
               continue;
            if(i < 5)
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h1, ds.h1Count, i, false, swingTarget, swingIdx))
               continue;
            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h1Count, i + 15); ++k)
            {
               if(ds.h1[k].close < swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = d1Levels[n].price;
            const double boxBottom = ds.h1[i].low;
            const double eqEntry = (boxTop + boxBottom) / 2.0;
            PositionPlan p;
            BuildPositionPlan(symbol, BIAS_BEARISH, eqEntry, boxTop + 0.5, eqEntry - 30.0, 0.0, 1.0, "MODEL_C_D1W4", p);
            outSignal.modelName = "MODEL_C_D1W4";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BEARISH;
            outSignal.storylineKey = "D1W4_RETRACEMENT";
            outSignal.storylineDesc = "1H mitigates D1 resistance";
            outSignal.storylineRejection = d1Levels[n].price;
            outSignal.ftflTf = "D1";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p;
            outSignal.hasSecondary = false;
            outSignal.confidence = "A";
            outSignal.rationale = "Model C D1W4 bearish";
            outSignal.distanceToEntry = MathAbs(p.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
      }
   }

   return false;
}

bool EvaluateModelC_W4(const string symbol, const DataSet &ds, TradeSignal &outSignal)
{
   if(ds.w1Count < 10 || ds.h4Count < 10 || ds.h1Count < 10)
      return false;

   BiasDirection overallBias = BIAS_NEUTRAL;
   StorylineEvent story;
   if(EvaluateStorylinePair("MN1", "W1", ds.mn1, ds.mn1Count, ds.w1, ds.w1Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   else if(EvaluateStorylinePair("W1", "D1", ds.w1, ds.w1Count, ds.d1, ds.d1Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   else if(EvaluateStorylinePair("D1", "H4", ds.d1, ds.d1Count, ds.h4, ds.h4Count, story) && story.valid)
      overallBias = (BiasDirection)story.bias;
   if(overallBias == BIAS_NEUTRAL)
      return false;

   CandleLevel w1Levels[];
   int w1Count = 0;
   DetectBaseLevels(ds.w1, ds.w1Count, w1Levels, w1Count);

   const int scanStart = MathMax(0, ds.h4Count - 8);
   for(int i = scanStart; i < ds.h4Count; ++i)
   {
      const bool bullish = (overallBias == BIAS_BULLISH);
      for(int n = 0; n < w1Count; ++n)
      {
         if(bullish)
         {
            if(w1Levels[n].levelType != LT_SUPPORT && w1Levels[n].levelType != LT_RBS)
               continue;
            if(!IsSingleCandleMitigation(ds.h4[i], w1Levels[n].price, true))
               continue;
            if(i < 5)
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h4, ds.h4Count, i, true, swingTarget, swingIdx))
               continue;
            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h4Count, i + 15); ++k)
            {
               if(ds.h4[k].close > swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = ds.h4[i].high;
            const double boxBottom = w1Levels[n].price;
            const double eqEntry = (boxTop + boxBottom) / 2.0;
            PositionPlan p;
            BuildPositionPlan(symbol, BIAS_BULLISH, eqEntry, boxBottom - 0.5, eqEntry + 50.0, 0.0, 1.0, "MODEL_C_W4", p);
            outSignal.modelName = "MODEL_C_W4";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BULLISH;
            outSignal.storylineKey = "W4_RETRACEMENT";
            outSignal.storylineDesc = "4H mitigates W1 support";
            outSignal.storylineRejection = w1Levels[n].price;
            outSignal.ftflTf = "H4";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p;
            outSignal.hasSecondary = false;
            outSignal.confidence = "A";
            outSignal.rationale = "Model C W4 bullish";
            outSignal.distanceToEntry = MathAbs(p.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
         else
         {
            if(w1Levels[n].levelType != LT_RESISTANCE && w1Levels[n].levelType != LT_SBR)
               continue;
            if(!IsSingleCandleMitigation(ds.h4[i], w1Levels[n].price, false))
               continue;
            if(i < 5)
               continue;

            double swingTarget = 0.0;
            int swingIdx = -1;
            if(!FindConfirmedSwingTarget(ds.h4, ds.h4Count, i, false, swingTarget, swingIdx))
               continue;
            bool breakout = false;
            for(int k = i + 1; k < MathMin(ds.h4Count, i + 15); ++k)
            {
               if(ds.h4[k].close < swingTarget)
               {
                  breakout = true;
                  break;
               }
            }
            if(!breakout)
               continue;

            const double boxTop = w1Levels[n].price;
            const double boxBottom = ds.h4[i].low;
            const double eqEntry = (boxTop + boxBottom) / 2.0;
            PositionPlan p;
            BuildPositionPlan(symbol, BIAS_BEARISH, eqEntry, boxTop + 0.5, eqEntry - 50.0, 0.0, 1.0, "MODEL_C_W4", p);
            outSignal.modelName = "MODEL_C_W4";
            outSignal.symbol = symbol;
            outSignal.direction = BIAS_BEARISH;
            outSignal.storylineKey = "W4_RETRACEMENT";
            outSignal.storylineDesc = "4H mitigates W1 resistance";
            outSignal.storylineRejection = w1Levels[n].price;
            outSignal.ftflTf = "H4";
            outSignal.stflTf = "H1";
            outSignal.ttflTf = "H1";
            outSignal.primary = p;
            outSignal.hasSecondary = false;
            outSignal.confidence = "A";
            outSignal.rationale = "Model C W4 bearish";
            outSignal.distanceToEntry = MathAbs(p.bufferedEntry - GetCurrentClose(ds));
            return true;
         }
      }
   }

   return false;
}

int BuildSignals(const DataSet &ds, TradeSignal &signals[])
{
   ArrayResize(signals, 0);
   int signalCount = 0;

   StorylineEvent mnSl;
   StorylineEvent w1Sl;
   StorylineEvent d1Sl;
   bool hasMn = false;
   bool hasW1 = false;
   bool hasD1 = false;

   if(ds.mn1Count > 0 && ds.w1Count > 0)
      hasMn = EvaluateStorylinePair("MN1", "W1", ds.mn1, ds.mn1Count, ds.w1, ds.w1Count, mnSl);
   if(ds.w1Count > 0 && ds.d1Count > 0)
      hasW1 = EvaluateStorylinePair("W1", "D1", ds.w1, ds.w1Count, ds.d1, ds.d1Count, w1Sl);
   if(ds.d1Count > 0 && ds.h4Count > 0)
      hasD1 = EvaluateStorylinePair("D1", "H4", ds.d1, ds.d1Count, ds.h4, ds.h4Count, d1Sl);

   if(hasMn && mnSl.valid)
   {
      TradeSignal s;
      if(BuildCascadeSignal(mnSl, g_symbol, "MN_STORY_W1_ENTRY", "W1", "D1", "H4", "W1", ds, 1.0, "A+", s))
         AddTrendlineFilteredSignal(ds, signals, signalCount, s);
      if(BuildCascadeSignal(mnSl, g_symbol, "MN_STORY_MN_ENTRY", "MN1", "W1", "D1", "MN1", ds, 0.5, "A", s))
         AddTrendlineFilteredSignal(ds, signals, signalCount, s);
   }

   if(hasW1 && w1Sl.valid)
   {
      TradeSignal s;
      if(BuildCascadeSignal(w1Sl, g_symbol, "W1_STORY_D1_ENTRY", "D1", "H4", "H1", "D1", ds, 1.0, "A+", s))
         AddTrendlineFilteredSignal(ds, signals, signalCount, s);
      if(InpEnableW1StoryW1Entry)
      {
         if(BuildCascadeSignal(w1Sl, g_symbol, "W1_STORY_W1_ENTRY", "W1", "D1", "H4", "W1", ds, 0.7, "A", s))
            AddTrendlineFilteredSignal(ds, signals, signalCount, s);
      }
   }

   if(hasD1 && d1Sl.valid)
   {
      TradeSignal s;
      if(BuildCascadeSignal(d1Sl, g_symbol, "D1_STORY_H4_ENTRY", "H4", "H1", "H1", "H4", ds, 1.0, "A+", s))
         AddTrendlineFilteredSignal(ds, signals, signalCount, s);
      if(BuildCascadeSignal(d1Sl, g_symbol, "D1_STORY_D1_ENTRY", "D1", "H4", "H1", "D1", ds, 0.7, "A", s))
         AddTrendlineFilteredSignal(ds, signals, signalCount, s);
   }

   // Model B
   TradeSignal bSig;
   if((hasMn && mnSl.bias == BIAS_BULLISH) || (hasW1 && w1Sl.bias == BIAS_BULLISH) || (hasD1 && d1Sl.bias == BIAS_BULLISH))
   {
      if(EvaluateModelB(g_symbol, ds, BIAS_BULLISH, bSig))
         AddTrendlineFilteredSignal(ds, signals, signalCount, bSig);
   }
   if((hasMn && mnSl.bias == BIAS_BEARISH) || (hasW1 && w1Sl.bias == BIAS_BEARISH) || (hasD1 && d1Sl.bias == BIAS_BEARISH))
   {
      if(EvaluateModelB(g_symbol, ds, BIAS_BEARISH, bSig))
         AddTrendlineFilteredSignal(ds, signals, signalCount, bSig);
   }

   // Model C / W4
   TradeSignal cSig;
   if(EvaluateModelC_D1W4(g_symbol, ds, cSig))
      AddTrendlineFilteredSignal(ds, signals, signalCount, cSig);
   if(EvaluateModelC_W4(g_symbol, ds, cSig))
      AddTrendlineFilteredSignal(ds, signals, signalCount, cSig);

   if(signalCount > 1)
      SortSignalsByDistance(signals, signalCount);
   else if(signalCount == 1)
      signals[0].priorityRank = 1;

   return signalCount;
}

void PlaceBestSignal(const TradeSignal &signal)
{
   if(signal.primary.lotSize <= 0.0 || signal.primary.bufferedEntry <= 0.0)
      return;

   if(signal.hasSecondary)
   {
      SendPendingOrder(signal.primary, "EQ70");
      SendPendingOrder(signal.secondary, "BD30");
   }
   else
   {
      SendPendingOrder(signal.primary, "P1");
   }
}

void RunScanAndTrade()
{
   DataSet ds;
   if(!LoadDataSet(g_symbol, ds))
      return;

   string consolidationReason = "";
   if(IsConsolidatingMarket(ds, consolidationReason))
   {
      if(InpVerbose)
         PrintFormat("MSNR consolidation filter blocked trading: %s", consolidationReason);
      CancelPendingOrders(g_symbol);
      return;
   }

   TradeSignal signals[];
   int signalCount = BuildSignals(ds, signals);

   if(HasOpenPosition(g_symbol))
      return;

   if(signalCount <= 0)
   {
      CancelPendingOrders(g_symbol);
      if(InpVerbose && g_lastSignalPrint != 0)
      {
         Print("MSNR: no active signal");
         g_lastSignalPrint = 0;
      }
      return;
   }

   if(InpVerbose)
   {
      PrintFormat("MSNR: %d signals, top=%s %s entry=%.2f SL=%.2f TP=%.2f conf=%s",
                  signalCount,
                  signals[0].modelName,
                  (signals[0].direction == BIAS_BULLISH ? "BUY" : "SELL"),
                  signals[0].primary.bufferedEntry,
                  signals[0].primary.stopLoss,
                  signals[0].primary.takeProfit,
                  signals[0].confidence);
   }

   CancelPendingOrders(g_symbol);

   if(InpTradeClosestOnly)
   {
      PlaceBestSignal(signals[0]);
   }
   else
   {
      for(int i = 0; i < signalCount; ++i)
         PlaceBestSignal(signals[i]);
   }
}

bool UpdateOnNewH1Bar()
{
   DataSet ds;
   if(!CopyRatesChrono(g_symbol, PERIOD_H1, 3, ds.h1))
      return false;

   ds.h1Count = ArraySize(ds.h1);
   if(ds.h1Count <= 0)
      return false;

   const datetime currentH1BarTime = ds.h1[ds.h1Count - 1].time;
   if(currentH1BarTime == g_lastH1BarTime)
      return false;

   g_lastH1BarTime = currentH1BarTime;
   return true;
}

void ProcessMarket()
{
   ManageOpenPositions();
   SyncTradingDayState();

   if(IsDailyLossLimitHit() || IsAsiaSessionBlocked())
   {
      CancelPendingOrders(g_symbol);
      return;
   }

   if(!UpdateOnNewH1Bar())
      return;

   if(InpVerbose)
   {
      PrintFormat("MSNR scan: symbol=%s balance=%.2f equity=%.2f",
                  g_symbol,
                  AccountInfoDouble(ACCOUNT_BALANCE),
                  AccountInfoDouble(ACCOUNT_EQUITY));
   }

   Comment(StringFormat("MSNR scan | %s | balance %.2f | equity %.2f",
                        g_symbol,
                        AccountInfoDouble(ACCOUNT_BALANCE),
                        AccountInfoDouble(ACCOUNT_EQUITY)));

   RunScanAndTrade();
}

// ---------------------------------------------------------------------------
// MT5 events
// ---------------------------------------------------------------------------

int OnInit()
{
   g_symbol = (StringLen(InpSymbol) > 0 ? InpSymbol : _Symbol);
   SymbolSelect(g_symbol, true);

   g_accountProtectionStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);

   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints(20);
   g_trade.SetTypeFillingBySymbol(g_symbol);

   EventSetTimer(InpTimerSeconds);
   if(InpVerbose)
      PrintFormat("MSNR EA initialized on %s", g_symbol);
   ProcessMarket();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   ProcessMarket();
}

void OnTick()
{
   ProcessMarket();
}

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   AppendTradeHistoryRow(trans.deal);
   UpdateDailyLossFromDeal(trans.deal);
}
