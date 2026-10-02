#property strict

// ---------------------------------------------------------------------------
// MSNR Alchemist Base v1
//
// Strategy foundation only:
//   - Candle-close Support / Resistance
//   - Role reversal: SBR / RBS
//   - Fresh / unfresh / broken level state
//   - OCL variants: sOCL, rOCL, 1-Lap OCL, LS OCL
//   - QM variants: AB QM, FT QM, ST QM, iAB QM
//   - Apex / iAB line-chart structure
//   - Storyline: HTF rejection + LTF breakout
//   - Trendline break-and-retest confluence helper
//
// No execution, no risk model, no pending orders, no position management, and
// no FTFL/STFL/TTFL cascade. Entry models belong to the developer using this.
// ---------------------------------------------------------------------------

input string InpSymbol = "";
input bool   InpVerbose = true;
input int    InpTimerSeconds = 1;
input bool   InpScanOnlyOnNewH1Bar = true;
input bool   InpPrintKeyLevelSummary = true;
input bool   InpPrintStorylineSummary = true;
input bool   InpPrintTrendlineSummary = true;
input int    InpTrendlineTolerancePoints = 40;
input int    InpTrendlineLookbackBars = 160;
input bool   InpPrintEGSummary = true;

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

string   g_symbol = "";
datetime g_lastH1BarTime = 0;

double SymbolPointValue(const string symbol)
{
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   return (point > 0.0 ? point : 0.0001);
}

int SymbolDigitsValue(const string symbol)
{
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   return (digits > 0 ? digits : 2);
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

string BiasToString(const int bias)
{
   if(bias == BIAS_BULLISH) return "BULLISH";
   if(bias == BIAS_BEARISH) return "BEARISH";
   return "NEUTRAL";
}

string LevelTypeToString(const int type)
{
   if(type == LT_SUPPORT) return "SUPPORT";
   if(type == LT_RESISTANCE) return "RESISTANCE";
   if(type == LT_SBR) return "SBR";
   if(type == LT_RBS) return "RBS";
   return "UNKNOWN";
}

string LevelStateToString(const int state)
{
   if(state == LS_FRESH) return "FRESH";
   if(state == LS_UNFRESH) return "UNFRESH";
   if(state == LS_BROKEN) return "BROKEN";
   return "UNKNOWN";
}

string OCLTypeToString(const int type)
{
   if(type == OCL_STANDARD_BULLISH) return "BULLISH_OCL";
   if(type == OCL_STANDARD_BEARISH) return "BEARISH_OCL";
   if(type == OCL_SOCL) return "sOCL";
   if(type == OCL_ROCL) return "rOCL";
   if(type == OCL_ONE_LAP) return "1_LAP_OCL";
   if(type == OCL_LS_OCL) return "LS_OCL";
   return "UNKNOWN";
}

string QMTypeToString(const int type)
{
   if(type == QM_ABQM) return "AB_QM";
   if(type == QM_FTQM) return "FT_QM";
   if(type == QM_STQM) return "ST_QM";
   if(type == QM_IABQM) return "iAB_QM";
   return "UNKNOWN";
}

string ApexTypeToString(const int type)
{
   if(type == APEX_SUPPORT) return "APEX_SUPPORT";
   if(type == APEX_RESISTANCE) return "APEX_RESISTANCE";
   if(type == IAB_SUPPORT) return "iAB_SUPPORT";
   if(type == IAB_RESISTANCE) return "iAB_RESISTANCE";
   return "UNKNOWN";
}

bool CopyRatesChrono(const string symbol, const ENUM_TIMEFRAMES tf, const int count, MqlRates &outRates[])
{
   MqlRates tmp[];
   ArraySetAsSeries(tmp, true);
   const int copied = CopyRates(symbol, tf, 0, count, tmp);
   if(copied <= 0)
      return false;

   ArrayResize(outRates, copied);
   for(int i = 0; i < copied; ++i)
      outRates[i] = tmp[copied - 1 - i];

   return true;
}

bool LoadDataSet(const string symbol, DataSet &ds)
{
   const bool mnOk = CopyRatesChrono(symbol, PERIOD_MN1, 24, ds.mn1);
   const bool w1Ok = CopyRatesChrono(symbol, PERIOD_W1, 104, ds.w1);
   const bool d1Ok = CopyRatesChrono(symbol, PERIOD_D1, 365, ds.d1);
   const bool h4Ok = CopyRatesChrono(symbol, PERIOD_H4, 500, ds.h4);
   const bool h1Ok = CopyRatesChrono(symbol, PERIOD_H1, 500, ds.h1);

   ds.mn1Count = ArraySize(ds.mn1);
   ds.w1Count = ArraySize(ds.w1);
   ds.d1Count = ArraySize(ds.d1);
   ds.h4Count = ArraySize(ds.h4);
   ds.h1Count = ArraySize(ds.h1);

   return (mnOk || w1Ok || d1Ok || h4Ok || h1Ok);
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

void DetectBaseLevels(const MqlRates &bars[], const int count, CandleLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;

   for(int i = 0; i < count - 1; ++i)
   {
      if(IsBearishBar(bars[i]) && IsBullishBar(bars[i + 1]))
         AddCandleLevel(levels, levelCount, LT_SUPPORT, bars[i].close, i, bars[i].time, LS_FRESH, -1);
      else if(IsBullishBar(bars[i]) && IsBearishBar(bars[i + 1]))
         AddCandleLevel(levels, levelCount, LT_RESISTANCE, bars[i].close, i, bars[i].time, LS_FRESH, -1);
   }

   const int baseCount = levelCount;
   for(int n = 0; n < baseCount; ++n)
   {
      for(int i = levels[n].candleIndex + 2; i < count; ++i)
      {
         const double bodyHigh = BarBodyHigh(bars[i]);
         const double bodyLow = BarBodyLow(bars[i]);

         if(levels[n].levelType == LT_SUPPORT)
         {
            if(bodyHigh < levels[n].price || bars[i].close < levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               AddCandleLevel(levels, levelCount, LT_SBR, levels[n].price, i, bars[i].time, LS_FRESH, levels[n].candleIndex);
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].low <= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
         else if(levels[n].levelType == LT_RESISTANCE)
         {
            if(bodyLow > levels[n].price || bars[i].close > levels[n].price)
            {
               levels[n].state = LS_BROKEN;
               levels[n].breakCandleIndex = i;
               AddCandleLevel(levels, levelCount, LT_RBS, levels[n].price, i, bars[i].time, LS_FRESH, levels[n].candleIndex);
               break;
            }
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].price)
            {
               levels[n].state = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
      }
   }
}

void DetectOCLLevels(const MqlRates &bars[], const int count, const string timeframe, OCLLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;
   if(!(timeframe == "MN1" || timeframe == "W1" || timeframe == "D1"))
      return;

   for(int i = 0; i < count - 1; ++i)
   {
      if(!((IsBullishBar(bars[i]) && IsBullishBar(bars[i + 1])) || (IsBearishBar(bars[i]) && IsBearishBar(bars[i + 1]))))
         continue;

      const bool isBodyEngulf = (BarBodyHigh(bars[i + 1]) >= BarBodyHigh(bars[i])) && (BarBodyLow(bars[i + 1]) <= BarBodyLow(bars[i]));
      const bool isRangeEngulf = (bars[i + 1].high >= bars[i].high) && (bars[i + 1].low <= bars[i].low);
      if(isBodyEngulf || isRangeEngulf)
         continue;

      AddOCLLevel(levels,
                  levelCount,
                  (IsBullishBar(bars[i]) ? OCL_STANDARD_BULLISH : OCL_STANDARD_BEARISH),
                  bars[i].close,
                  i,
                  i + 1,
                  bars[i].time,
                  MathMax(bars[i].high, bars[i + 1].high),
                  MathMin(bars[i].low, bars[i + 1].low));
   }

   CandleLevel srLevels[];
   int srCount = 0;
   DetectBaseLevels(bars, count, srLevels, srCount);

   for(int n = 0; n < levelCount; ++n)
   {
      bool nearSupport = false;
      bool nearResistance = false;
      for(int s = 0; s < srCount; ++s)
      {
         const int idx = srLevels[s].candleIndex;
         if(MathAbs(idx - levels[n].candleIndex1) <= 2 || MathAbs(idx - levels[n].candleIndex2) <= 2)
         {
            if(srLevels[s].levelType == LT_SUPPORT || srLevels[s].levelType == LT_RBS)
               nearSupport = true;
            if(srLevels[s].levelType == LT_RESISTANCE || srLevels[s].levelType == LT_SBR)
               nearResistance = true;
         }
      }

      const int idx3 = levels[n].candleIndex2 + 1;
      if(idx3 < count && nearSupport && levels[n].oclType == OCL_STANDARD_BEARISH && IsBullishBar(bars[idx3]))
         levels[n].oclType = OCL_SOCL;
      if(idx3 < count && nearResistance && levels[n].oclType == OCL_STANDARD_BULLISH && IsBearishBar(bars[idx3]))
         levels[n].oclType = OCL_ROCL;
   }

   for(int n = 0; n < levelCount; ++n)
   {
      int breaks = 0;
      string currentSide = IsBullishBar(bars[levels[n].candleIndex1]) ? "above" : "below";
      for(int i = levels[n].candleIndex2 + 1; i < count; ++i)
      {
         if(currentSide == "above" && bars[i].close < levels[n].price && BarBodyHigh(bars[i]) < levels[n].price)
         {
            breaks++;
            currentSide = "below";
         }
         else if(currentSide == "below" && bars[i].close > levels[n].price && BarBodyLow(bars[i]) > levels[n].price)
         {
            breaks++;
            currentSide = "above";
         }
      }
      levels[n].breakCount = breaks;
      if(breaks >= 2)
         levels[n].oclType = OCL_LS_OCL;
      else if((levels[n].oclType == OCL_STANDARD_BULLISH || levels[n].oclType == OCL_STANDARD_BEARISH) && breaks == 0)
         levels[n].oclType = OCL_ONE_LAP;
   }
}

void DetectQMLevels(const MqlRates &bars[], const int count, const CandleLevel &baseLevels[], const int baseCount, QMLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(count < 3)
      return;

   for(int n = 0; n < baseCount; ++n)
   {
      if(baseLevels[n].levelType != LT_SBR && baseLevels[n].levelType != LT_RBS)
         continue;

      for(int i = baseLevels[n].candleIndex + 1; i < count; ++i)
      {
         if(baseLevels[n].levelType == LT_SBR && BarBodyLow(bars[i]) > baseLevels[n].price && bars[i].close > baseLevels[n].price)
         {
            AddQMLevel(levels,
                       levelCount,
                       (baseLevels[n].derivedFromIndex >= 0 ? QM_ABQM : QM_FTQM),
                       QM_BULLISH,
                       baseLevels[n].price,
                       baseLevels[n].derivedFromIndex,
                       baseLevels[n].candleIndex,
                       i,
                       bars[i].time,
                       MathMax(bars[i].high, baseLevels[n].price),
                       MathMin(bars[i].low, baseLevels[n].price));
            break;
         }

         if(baseLevels[n].levelType == LT_RBS && BarBodyHigh(bars[i]) < baseLevels[n].price && bars[i].close < baseLevels[n].price)
         {
            AddQMLevel(levels,
                       levelCount,
                       (baseLevels[n].derivedFromIndex >= 0 ? QM_ABQM : QM_FTQM),
                       QM_BEARISH,
                       baseLevels[n].price,
                       baseLevels[n].derivedFromIndex,
                       baseLevels[n].candleIndex,
                       i,
                       bars[i].time,
                       MathMax(bars[i].high, baseLevels[n].price),
                       MathMin(bars[i].low, baseLevels[n].price));
            break;
         }
      }
   }
}

bool IsLocalPeak(const MqlRates &bars[], const int count, const int idx, const int distance)
{
   if(idx - distance < 0 || idx + distance >= count)
      return false;
   for(int i = idx - distance; i <= idx + distance; ++i)
   {
      if(i != idx && bars[i].close >= bars[idx].close)
         return false;
   }
   return true;
}

bool IsLocalValley(const MqlRates &bars[], const int count, const int idx, const int distance)
{
   if(idx - distance < 0 || idx + distance >= count)
      return false;
   for(int i = idx - distance; i <= idx + distance; ++i)
   {
      if(i != idx && bars[i].close <= bars[idx].close)
         return false;
   }
   return true;
}

void DetectApexLevels(const MqlRates &bars[], const int count, const string timeframe, ApexLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;
   if(!(timeframe == "MN1" || timeframe == "W1" || timeframe == "D1"))
      return;
   if(count < 10)
      return;

   const int distance = 3;
   for(int i = distance; i < count - distance; ++i)
   {
      if(IsLocalPeak(bars, count, i, distance))
      {
         bool hasPriorHigherPeak = false;
         for(int j = distance; j < i; ++j)
         {
            if(IsLocalPeak(bars, count, j, distance) && bars[j].close > bars[i].close)
            {
               hasPriorHigherPeak = true;
               break;
            }
         }

         for(int k = i + 1; k < count; ++k)
         {
            if(bars[k].close > bars[i].close)
            {
               const int apexType = (hasPriorHigherPeak ? IAB_RESISTANCE : APEX_RESISTANCE);
               AddApexLevel(levels, levelCount, apexType, bars[i].close, i, k, bars[i].time, !hasPriorHigherPeak);
               break;
            }
         }
      }

      if(IsLocalValley(bars, count, i, distance))
      {
         bool hasPriorLowerValley = false;
         for(int j = distance; j < i; ++j)
         {
            if(IsLocalValley(bars, count, j, distance) && bars[j].close < bars[i].close)
            {
               hasPriorLowerValley = true;
               break;
            }
         }

         for(int k = i + 1; k < count; ++k)
         {
            if(bars[k].close < bars[i].close)
            {
               const int apexType = (hasPriorLowerValley ? IAB_SUPPORT : APEX_SUPPORT);
               AddApexLevel(levels, levelCount, apexType, bars[i].close, i, k, bars[i].time, !hasPriorLowerValley);
               break;
            }
         }
      }
   }
}

bool FindConfirmedSwingTarget(const MqlRates &bars[], const int count, const int searchEndExclusive, const bool bullish, double &targetPrice, int &targetIdx)
{
   targetPrice = 0.0;
   targetIdx = -1;
   if(count < 5)
      return false;

   const int distance = 2;
   int lastCandidate = searchEndExclusive - distance - 1;
   if(lastCandidate > count - distance - 1)
      lastCandidate = count - distance - 1;
   if(lastCandidate < distance)
      return false;

   for(int i = lastCandidate; i >= distance; --i)
   {
      if(bullish && IsLocalPeak(bars, count, i, distance))
      {
         targetIdx = i;
         targetPrice = bars[i].close;
         return true;
      }
      if(!bullish && IsLocalValley(bars, count, i, distance))
      {
         targetIdx = i;
         targetPrice = bars[i].close;
         return true;
      }
   }
   return false;
}

bool CheckLTFBreakout(const datetime rejectionTime, const MqlRates &ltfBars[], const int ltfCount, const bool bullish, datetime &outBreakTime, int &outBreakIdx)
{
   outBreakTime = 0;
   outBreakIdx = -1;
   if(ltfCount < 5)
      return false;

   int rejIdx = -1;
   for(int i = 0; i < ltfCount; ++i)
   {
      if(ltfBars[i].time >= rejectionTime)
      {
         rejIdx = i;
         break;
      }
   }
   if(rejIdx < 5)
      return false;

   double target = 0.0;
   int swingIdx = -1;
   if(!FindConfirmedSwingTarget(ltfBars, ltfCount, rejIdx, bullish, target, swingIdx))
      return false;

   const int forwardEnd = MathMin(ltfCount, rejIdx + 60);
   for(int i = rejIdx + 1; i < forwardEnd; ++i)
   {
      if(bullish && ltfBars[i].close > target)
      {
         outBreakTime = ltfBars[i].time;
         outBreakIdx = i;
         return true;
      }
      if(!bullish && ltfBars[i].close < target)
      {
         outBreakTime = ltfBars[i].time;
         outBreakIdx = i;
         return true;
      }
   }
   return false;
}

bool EvaluateStorylinePair(const string htfName, const string ltfName, const MqlRates &htfBars[], const int htfCount, const MqlRates &ltfBars[], const int ltfCount, StorylineEvent &outEvent)
{
   outEvent.valid = false;
   if(htfCount < 10 || ltfCount < 20)
      return false;

   CandleLevel htfLevels[];
   int htfLevelCount = 0;
   DetectBaseLevels(htfBars, htfCount, htfLevels, htfLevelCount);

   const int startBar = MathMax(0, htfCount - 100);
   StorylineEvent latest;
   latest.valid = false;

   for(int i = startBar; i < htfCount; ++i)
   {
      for(int n = 0; n < htfLevelCount; ++n)
      {
         if(htfLevels[n].candleIndex >= i || htfLevels[n].state != LS_FRESH)
            continue;

         const bool bullishLevel = (htfLevels[n].levelType == LT_SUPPORT || htfLevels[n].levelType == LT_RBS);
         const bool bearishLevel = (htfLevels[n].levelType == LT_RESISTANCE || htfLevels[n].levelType == LT_SBR);
         datetime breakTime = 0;
         int breakIdx = -1;

         if(bullishLevel && htfBars[i].low <= htfLevels[n].price && htfBars[i].open > htfLevels[n].price && htfBars[i].close > htfLevels[n].price)
         {
            if(CheckLTFBreakout(htfBars[i].time, ltfBars, ltfCount, true, breakTime, breakIdx))
            {
               latest.valid = true;
               latest.htf = htfName;
               latest.ltf = ltfName;
               latest.bias = BIAS_BULLISH;
               latest.rejectionPrice = htfLevels[n].price;
               latest.rejectionTime = htfBars[i].time;
               latest.rejectionCandleIdx = i;
               latest.breakoutTime = breakTime;
               latest.breakoutCandleIdx = breakIdx;
               latest.rejectionLevelDesc = htfName + " " + LevelTypeToString(htfLevels[n].levelType);
            }
         }

         if(bearishLevel && htfBars[i].high >= htfLevels[n].price && htfBars[i].open < htfLevels[n].price && htfBars[i].close < htfLevels[n].price)
         {
            if(CheckLTFBreakout(htfBars[i].time, ltfBars, ltfCount, false, breakTime, breakIdx))
            {
               latest.valid = true;
               latest.htf = htfName;
               latest.ltf = ltfName;
               latest.bias = BIAS_BEARISH;
               latest.rejectionPrice = htfLevels[n].price;
               latest.rejectionTime = htfBars[i].time;
               latest.rejectionCandleIdx = i;
               latest.breakoutTime = breakTime;
               latest.breakoutCandleIdx = breakIdx;
               latest.rejectionLevelDesc = htfName + " " + LevelTypeToString(htfLevels[n].levelType);
            }
         }
      }
   }

   outEvent = latest;
   return latest.valid;
}

double TrendlineValueAt(const int firstIndex, const double firstPrice, const int secondIndex, const double secondPrice, const int queryIndex)
{
   if(secondIndex == firstIndex)
      return secondPrice;

   const double slope = (secondPrice - firstPrice) / (double)(secondIndex - firstIndex);
   return firstPrice + slope * (double)(queryIndex - firstIndex);
}

bool CollectConfirmedExtremes(const MqlRates &bars[], const int count, const bool usePeaks, const int lookbackBars, int &indices[], double &prices[], int &outCount)
{
   ArrayResize(indices, 0);
   ArrayResize(prices, 0);
   outCount = 0;
   if(count < 10)
      return false;

   const int distance = 3;
   const int start = MathMax(distance, count - MathMax(lookbackBars, distance + 1));
   const int end = count - distance - 1;
   for(int i = start; i <= end; ++i)
   {
      const bool isExtreme = (usePeaks ? IsLocalPeak(bars, count, i, distance) : IsLocalValley(bars, count, i, distance));
      if(!isExtreme)
         continue;

      ArrayResize(indices, outCount + 1);
      ArrayResize(prices, outCount + 1);
      indices[outCount] = i;
      prices[outCount] = bars[i].close;
      outCount++;
   }
   return (outCount >= 2);
}

bool ValidateBreakRetestTrendline(const MqlRates &bars[], const int count, const int firstIdx, const int secondIdx, const bool bearishLine, const double tolerance, TrendlineMatch &match, const string timeframe, const string mode)
{
   match.valid = false;
   if(firstIdx < 0 || secondIdx <= firstIdx || secondIdx >= count - 2)
      return false;

   const double firstPrice = bars[firstIdx].close;
   const double secondPrice = bars[secondIdx].close;
   bool hasBreakout = false;

   for(int i = secondIdx + 1; i < count; ++i)
   {
      const double lineValue = TrendlineValueAt(firstIdx, firstPrice, secondIdx, secondPrice, i);
      if(bearishLine && bars[i].close > lineValue)
         hasBreakout = true;
      if(!bearishLine && bars[i].close < lineValue)
         hasBreakout = true;
      if(hasBreakout && MathAbs(bars[i].close - lineValue) <= tolerance)
      {
         match.valid = true;
         match.timeframe = timeframe;
         match.mode = mode;
         match.firstIndex = firstIdx;
         match.secondIndex = secondIdx;
         match.firstPrice = firstPrice;
         match.secondPrice = secondPrice;
         match.lineValue = lineValue;
         return true;
      }
   }
   return false;
}

bool CheckTrendlineConfluenceOnTF(const MqlRates &bars[], const int count, const string timeframe, const bool bullish, const double tolerance, const int lookbackBars, TrendlineMatch &match)
{
   int peaks[];
   int valleys[];
   double peakPrices[];
   double valleyPrices[];
   int peakCount = 0;
   int valleyCount = 0;

   const bool havePeaks = CollectConfirmedExtremes(bars, count, true, lookbackBars, peaks, peakPrices, peakCount);
   const bool haveValleys = CollectConfirmedExtremes(bars, count, false, lookbackBars, valleys, valleyPrices, valleyCount);
   const int minGapBars = 6;

   if(bullish && havePeaks)
   {
      for(int second = peakCount - 1; second >= 1; --second)
      {
         for(int first = second - 1; first >= 0; --first)
         {
            if(peaks[second] - peaks[first] >= minGapBars && ValidateBreakRetestTrendline(bars, count, peaks[first], peaks[second], true, tolerance, match, timeframe, "break_retest_resistance"))
               return true;
         }
      }
   }

   if(!bullish && haveValleys)
   {
      for(int second = valleyCount - 1; second >= 1; --second)
      {
         for(int first = second - 1; first >= 0; --first)
         {
            if(valleys[second] - valleys[first] >= minGapBars && ValidateBreakRetestTrendline(bars, count, valleys[first], valleys[second], false, tolerance, match, timeframe, "break_retest_support"))
               return true;
         }
      }
   }

   return false;
}


// ---------------------------------------------------------------------------
// EMS: Engulfing (EG) and Engulfing Fail (EF) detection
// ---------------------------------------------------------------------------
// Rules (from strategy notes and correction rule doc):
//  - Zone is marked on the ENGULFED candle (candle1), using its full wick range
//  - Box extends 3 steps to the right: covers candle1, candle2, candle3 (pullback space)
//  - Only scan on W1, D1, H4 timeframes (bias zones)
//  - EF: when price closes beyond the engulfed candle zone, the setup has failed
//    and the failed zone becomes a reversal zone (RBS/SBR equivalent)
// ---------------------------------------------------------------------------

enum EGType
{
   EG_BULLISH = 0,   // Bearish candle engulfed by bullish candle -> expect bullish pullback entry
   EG_BEARISH = 1    // Bullish candle engulfed by bearish candle -> expect bearish pullback entry
};

struct EGLevel
{
   int      egType;           // EG_BULLISH or EG_BEARISH
   double   price;            // Midpoint of the engulfed candle body (reference price)
   int      engulfedIndex;    // candle1: the smaller candle that was engulfed
   int      engulfingIndex;   // candle2: the larger engulfing candle
   datetime candleTime;       // time of the engulfed candle
   int      state;            // LS_FRESH, LS_UNFRESH, LS_BROKEN
   double   boxHigh;          // Top of zone: max wick of candle1, candle2, candle3
   double   boxLow;           // Bottom of zone: min wick of candle1, candle2, candle3
   int      firstTouchIndex;  // First bar to touch the zone after formation
   bool     isFailed;         // True -> this is now an EF (Engulfing Fail) reversal zone
};

string EGTypeToString(const int type)
{
   if(type == EG_BULLISH) return "BULLISH_EG";
   if(type == EG_BEARISH) return "BEARISH_EG";
   return "UNKNOWN";
}

void AddEGLevel(EGLevel &levels[], int &count,
                const int egType, const double price,
                const int engulfedIndex, const int engulfingIndex,
                const datetime candleTime,
                const double boxHigh, const double boxLow)
{
   ArrayResize(levels, count + 1);
   levels[count].egType         = egType;
   levels[count].price          = price;
   levels[count].engulfedIndex  = engulfedIndex;
   levels[count].engulfingIndex = engulfingIndex;
   levels[count].candleTime     = candleTime;
   levels[count].state          = LS_FRESH;
   levels[count].boxHigh        = boxHigh;
   levels[count].boxLow         = boxLow;
   levels[count].firstTouchIndex = -1;
   levels[count].isFailed       = false;
   count++;
}

// Detects EG and EF zones.
// Only valid on W1, D1, H4 per the EMS correction rules.
void DetectEGLevels(const MqlRates &bars[], const int count, const string timeframe,
                    EGLevel &levels[], int &levelCount)
{
   ArrayResize(levels, 0);
   levelCount = 0;

   // EMS correction rule: only mark EG zones on Weekly, Daily, H4
   if(!(timeframe == "W1" || timeframe == "D1" || timeframe == "H4"))
      return;
   if(count < 4)
      return;

   for(int i = 0; i < count - 1; ++i)
   {
      const bool c1Bear = IsBearishBar(bars[i]);
      const bool c1Bull = IsBullishBar(bars[i]);
      const bool c2Bull = IsBullishBar(bars[i + 1]);
      const bool c2Bear = IsBearishBar(bars[i + 1]);

      const double c1BodyHigh = BarBodyHigh(bars[i]);
      const double c1BodyLow  = BarBodyLow(bars[i]);
      const double c2BodyHigh = BarBodyHigh(bars[i + 1]);
      const double c2BodyLow  = BarBodyLow(bars[i + 1]);

      // Bullish EG: bearish candle1 engulfed by larger bullish candle2
      // Bearish EG: bullish candle1 engulfed by larger bearish candle2
      const bool isBullishEG = (c1Bear && c2Bull && c2BodyHigh > c1BodyHigh && c2BodyLow < c1BodyLow);
      const bool isBearishEG = (c1Bull && c2Bear && c2BodyHigh > c1BodyHigh && c2BodyLow < c1BodyLow);

      if(!isBullishEG && !isBearishEG)
         continue;

      const int type = isBullishEG ? EG_BULLISH : EG_BEARISH;

      // --- Wick Exception Rule (correction rule + user note) ---
      // candle2's total range is the reference for judging if candle1's wick is "too long"
      const double c2Range = bars[i + 1].high - bars[i + 1].low;

      double c1BoxHigh, c1BoxLow;
      if(isBullishEG)
      {
         // For BUYS: the problematic wick is candle1's UPPER wick (it goes against the buy zone).
         // candle1 is bearish so BodyHigh = open.
         // Upper wick = high - open. If this is longer than candle2's full range,
         // cap boxHigh at candle1's body top and keep only the lower wick.
         const double c1UpperWick = bars[i].high - c1BodyHigh;
         if(c1UpperWick > c2Range)
         {
            c1BoxHigh = c1BodyHigh;    // body top (no upper wick)
            c1BoxLow  = bars[i].low;   // keep lower wick
         }
         else
         {
            c1BoxHigh = bars[i].high;
            c1BoxLow  = bars[i].low;
         }
      }
      else // isBearishEG
      {
         // For SELLS: the problematic wick is candle1's LOWER wick (it goes against the sell zone).
         // candle1 is bullish so BodyLow = open.
         // Lower wick = open - low. If this is longer than candle2's full range,
         // floor boxLow at candle1's body bottom and keep only the upper wick.
         const double c1LowerWick = c1BodyLow - bars[i].low;
         if(c1LowerWick > c2Range)
         {
            c1BoxHigh = bars[i].high;  // keep upper wick
            c1BoxLow  = c1BodyLow;     // body bottom (no lower wick)
         }
         else
         {
            c1BoxHigh = bars[i].high;
            c1BoxLow  = bars[i].low;
         }
      }

      // Per correction rule: zone covers candle1 (with clamped wicks if needed),
      // candle2, and candle3 (3 steps right) using the max/min wick of all three.
      const int candle3Idx = (i + 2 < count ? i + 2 : i + 1);
      const double boxHigh = MathMax(c1BoxHigh, MathMax(bars[i + 1].high, bars[candle3Idx].high));
      const double boxLow  = MathMin(c1BoxLow,  MathMin(bars[i + 1].low,  bars[candle3Idx].low));

      // Reference price: midpoint of the engulfed candle's body (candle1)
      const double price = (c1BodyHigh + c1BodyLow) / 2.0;

      AddEGLevel(levels, levelCount, type, price, i, i + 1, bars[i].time, boxHigh, boxLow);
   }

   // Phase 2: state tracking and EF (Engulfing Fail) detection
   // After the engulfing index, scan forward to track touches and failures
   for(int n = 0; n < levelCount; ++n)
   {
      for(int i = levels[n].engulfingIndex + 1; i < count; ++i)
      {
         if(levels[n].egType == EG_BULLISH)
         {
            // Bullish EG zone: price is expected to pull back into box and bounce up.
            // If price closes BELOW the boxLow, the setup has failed -> EF (now acts as resistance)
            if(bars[i].close < levels[n].boxLow)
            {
               levels[n].isFailed = true;
               levels[n].state    = LS_BROKEN;
               break;
            }
            // First touch: price dips into the zone from above
            if(levels[n].state == LS_FRESH && bars[i].low <= levels[n].boxHigh)
            {
               levels[n].state          = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
         else // EG_BEARISH
         {
            // Bearish EG zone: price is expected to pull back into box and fall.
            // If price closes ABOVE the boxHigh, the setup has failed -> EF (now acts as support)
            if(bars[i].close > levels[n].boxHigh)
            {
               levels[n].isFailed = true;
               levels[n].state    = LS_BROKEN;
               break;
            }
            // First touch: price rises into the zone from below
            if(levels[n].state == LS_FRESH && bars[i].high >= levels[n].boxLow)
            {
               levels[n].state          = LS_UNFRESH;
               levels[n].firstTouchIndex = i;
            }
         }
      }
   }
}

void PrintLatestEGLevels(const string tfName, const MqlRates &bars[], const int count)
{
   EGLevel eg[];
   int egCount = 0;
   DetectEGLevels(bars, count, tfName, eg, egCount);

   PrintFormat("MSNR BASE %s EG/EF zones: count=%d", tfName, egCount);

   for(int i = MathMax(0, egCount - 5); i < egCount; ++i)
   {
      PrintFormat("  %s %s price=%.5f boxH=%.5f boxL=%.5f state=%s %s",
                  tfName,
                  EGTypeToString(eg[i].egType),
                  eg[i].price,
                  eg[i].boxHigh,
                  eg[i].boxLow,
                  LevelStateToString(eg[i].state),
                  (eg[i].isFailed ? "[EF-FAILED]" : ""));
   }
}

void PrintLatestKeyLevels(const string tfName, const MqlRates &bars[], const int count)
{
   CandleLevel sr[];
   OCLLevel ocl[];
   QMLevel qm[];
   ApexLevel apex[];
   int srCount = 0;
   int oclCount = 0;
   int qmCount = 0;
   int apexCount = 0;

   DetectBaseLevels(bars, count, sr, srCount);
   DetectOCLLevels(bars, count, tfName, ocl, oclCount);
   DetectQMLevels(bars, count, sr, srCount, qm, qmCount);
   DetectApexLevels(bars, count, tfName, apex, apexCount);

   PrintFormat("MSNR BASE %s levels: SR=%d OCL=%d QM=%d Apex=%d", tfName, srCount, oclCount, qmCount, apexCount);

   for(int i = MathMax(0, srCount - 5); i < srCount; ++i)
      PrintFormat("  %s %s %.5f %s", tfName, LevelTypeToString(sr[i].levelType), sr[i].price, LevelStateToString(sr[i].state));
   for(int i = MathMax(0, oclCount - 3); i < oclCount; ++i)
      PrintFormat("  %s %s %.5f breaks=%d", tfName, OCLTypeToString(ocl[i].oclType), ocl[i].price, ocl[i].breakCount);
   for(int i = MathMax(0, qmCount - 3); i < qmCount; ++i)
      PrintFormat("  %s %s %s %.5f", tfName, QMTypeToString(qm[i].qmType), (qm[i].direction == QM_BULLISH ? "BULLISH" : "BEARISH"), qm[i].price);
   for(int i = MathMax(0, apexCount - 3); i < apexCount; ++i)
      PrintFormat("  %s %s %.5f", tfName, ApexTypeToString(apex[i].apexType), apex[i].price);
}

void PrintStoryline(const StorylineEvent &story)
{
   if(!story.valid)
      return;

   PrintFormat("MSNR BASE storyline %s/%s %s reject %.5f at %s, breakout at %s",
               story.htf,
               story.ltf,
               BiasToString(story.bias),
               story.rejectionPrice,
               TimeToString(story.rejectionTime, TIME_DATE | TIME_MINUTES),
               TimeToString(story.breakoutTime, TIME_DATE | TIME_MINUTES));
}

void ScanAlchemistBase()
{
   DataSet ds;
   if(!LoadDataSet(g_symbol, ds))
      return;

   if(InpPrintKeyLevelSummary)
   {
      PrintLatestKeyLevels("MN1", ds.mn1, ds.mn1Count);
      PrintLatestKeyLevels("W1", ds.w1, ds.w1Count);
      PrintLatestKeyLevels("D1", ds.d1, ds.d1Count);
      PrintLatestKeyLevels("H4", ds.h4, ds.h4Count);
      PrintLatestKeyLevels("H1", ds.h1, ds.h1Count);
   }

   if(InpPrintStorylineSummary)
   {
      StorylineEvent story;
      if(EvaluateStorylinePair("MN1", "W1", ds.mn1, ds.mn1Count, ds.w1, ds.w1Count, story))
         PrintStoryline(story);
      if(EvaluateStorylinePair("W1", "D1", ds.w1, ds.w1Count, ds.d1, ds.d1Count, story))
         PrintStoryline(story);
      if(EvaluateStorylinePair("D1", "H4", ds.d1, ds.d1Count, ds.h4, ds.h4Count, story))
         PrintStoryline(story);
   }

   if(InpPrintTrendlineSummary)
   {
      TrendlineMatch match;
      const double tolerance = (double)MathMax(1, InpTrendlineTolerancePoints) * SymbolPointValue(g_symbol);
      const int lookback = MathMax(20, InpTrendlineLookbackBars);

      if(CheckTrendlineConfluenceOnTF(ds.h4, ds.h4Count, "H4", true, tolerance, lookback, match))
         PrintFormat("MSNR BASE trendline H4 bullish %s line=%.5f", match.mode, match.lineValue);
      if(CheckTrendlineConfluenceOnTF(ds.h4, ds.h4Count, "H4", false, tolerance, lookback, match))
         PrintFormat("MSNR BASE trendline H4 bearish %s line=%.5f", match.mode, match.lineValue);
      if(CheckTrendlineConfluenceOnTF(ds.h1, ds.h1Count, "H1", true, tolerance, lookback, match))
         PrintFormat("MSNR BASE trendline H1 bullish %s line=%.5f", match.mode, match.lineValue);
      if(CheckTrendlineConfluenceOnTF(ds.h1, ds.h1Count, "H1", false, tolerance, lookback, match))
         PrintFormat("MSNR BASE trendline H1 bearish %s line=%.5f", match.mode, match.lineValue);
   }

   // EMS EG/EF zones: scan on W1, D1, H4 only (per correction rule)
   if(InpPrintEGSummary)
   {
      PrintLatestEGLevels("W1", ds.w1, ds.w1Count);
      PrintLatestEGLevels("D1", ds.d1, ds.d1Count);
      PrintLatestEGLevels("H4", ds.h4, ds.h4Count);
   }
}

bool IsNewH1Bar()
{
   MqlRates h1[];
   if(!CopyRatesChrono(g_symbol, PERIOD_H1, 3, h1))
      return false;

   const int count = ArraySize(h1);
   if(count <= 0)
      return false;

   const datetime currentH1BarTime = h1[count - 1].time;
   if(currentH1BarTime == g_lastH1BarTime)
      return false;

   g_lastH1BarTime = currentH1BarTime;
   return true;
}

void ProcessBaseScanner()
{
   if(InpScanOnlyOnNewH1Bar && !IsNewH1Bar())
      return;

   if(InpVerbose)
      PrintFormat("MSNR BASE scan: %s", g_symbol);

   Comment(StringFormat("MSNR Alchemist Base | %s | key levels + storylines + trendlines only", g_symbol));
   ScanAlchemistBase();
}

int OnInit()
{
   g_symbol = (StringLen(InpSymbol) > 0 ? InpSymbol : _Symbol);
   SymbolSelect(g_symbol, true);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   ProcessBaseScanner();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

void OnTimer()
{
   ProcessBaseScanner();
}

void OnTick()
{
   ProcessBaseScanner();
}
