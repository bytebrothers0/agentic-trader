# APA Strategy: Part 3 - Areas of Liquidity (Engulfing Types)

## 1. Defining the Zones
In the APA strategy, an Area of Liquidity (AOL) is often defined by specific candlestick formations, primarily engulfing patterns. However, standard engulfing definitions are insufficient. The APA strategy categorizes these into 4 distinct Types, each with precise wick and body requirements.

For a trading bot, calculating the bounding box `[Top, Bottom]` of these zones accurately is critical, as it dictates entries, invalidation points, and trend phase tracking.

## 2. TYPE 1: The "Sweep" Engulfing
Type 1 is characterized by a significant liquidity sweep before the engulfing occurs.

### 2.1 Bearish Engulfing Type 1
**Conditions:**
1. **Both Candles Bearish**: Candle 1 (the engulfed) and Candle 2 (the engulfing) must both be bearish (`Close < Open`).
2. **Large Wick (The Sweep)**: Candle 2 must have a significant upper wick that sweeps the high of Candle 1.
3. **Complete Engulfing**: The close of Candle 2 must be below the close of Candle 1. Ideally, it engulfs the entire body and lower wick of Candle 1.

**Bot Zone Marking Logic (Bearish Type 1):**
- **Box Top (Invalidation)**: `Candle2.High` (The FMD of the sweep).
- **Box Bottom**: `Candle1.Close` (or the body low of Candle 1).
- *Visual Rule Check*: The bot must verify `Candle2.High > Candle1.High` AND `Candle2.Close < Candle1.Close`.

### 2.2 Bullish Engulfing Type 1
**Conditions:**
1. **Both Candles Bullish**: Candle 1 and Candle 2 must be bullish (`Close > Open`).
2. **Large Wick (The Sweep)**: Candle 2 must have a significant lower wick that sweeps the low of Candle 1.
3. **Complete Engulfing**: The close of Candle 2 must be above the close of Candle 1.

**Bot Zone Marking Logic (Bullish Type 1):**
- **Box Bottom (Invalidation)**: `Candle2.Low` (The FMD of the sweep).
- **Box Top**: `Candle1.Close` (or the body high of Candle 1).
- *Visual Rule Check*: The bot must verify `Candle2.Low < Candle1.Low` AND `Candle2.Close > Candle1.Close`.

## 3. TYPE 2: The "Standard/Inside" Engulfing
Type 2 occurs when the engulfing candle does not necessarily sweep the previous candle's wick, but solidly engulfs the body.

### 3.1 Characteristics
- Candle 1 is engulfed by Candle 2.
- Unlike Type 1, the sweep by Candle 2 is either non-existent or occurs strictly within standard bounds (e.g., an opposite color engulfing).
- **Validation**: Validation occurs when a subsequent candle closes above the high of Candle 1 (for bullish) or below the low of Candle 1 (for bearish).
- **Invalidation**: The absolute extreme of the pattern.

**Bot Zone Marking Logic (Bullish Type 2 Example):**
- Let Candle 1 be Bearish, Candle 2 be Bullish.
- `Candle2.Close > Candle1.Open` (Body engulfing).
- **Box Top**: `Candle1.High`.
- **Box Bottom**: `Candle2.Low` (or `Candle1.Low`, whichever is lower. Usually `Candle2.Low` if it swept).

## 4. TYPE 3: The "Minor/No Wick" Engulfing
Type 3 is defined by a lack of significant wicks on the engulfed candle.

### 4.1 Characteristics
- Candle 1 has very small or non-existent wicks (a momentum body).
- Candle 2 engulfs it.
- Because there is no sweep by Candle 2, the zone is drawn based on the body of Candle 1.

**Bot Zone Marking Logic:**
- If `(Candle1.High - Candle1.Open) < Threshold` AND `(Candle1.Close - Candle1.Low) < Threshold` (it's a near-marubozu).
- Box is drawn entirely around the body of Candle 1.
- Invalidation remains the absolute extreme of the two-candle formation.

## 5. TYPE 4: Weekly/Monthly Structure Overlap (WOL)
Type 4 is a higher-timeframe specific pattern, specifically looking at the interaction between Monthly and Weekly charts.

### 5.1 Characteristics
- It must be spotted on the Weekly timeframe and above.
- It involves an overlap of wicks/bodies between a Monthly level and a Weekly structure.
- **Rule**: If there is a Monthly formation, you MUST expect the Weekly chart to give a corresponding formation inside that Monthly zone. If the Weekly fails to form structure inside the Monthly zone, the setup is **INVALID**.

**Bot Implementation Logic (Type 4 Validation):**
```cpp
bool ValidateType4Overlap() {
    // 1. Get Monthly AOL
    AreaOfLiquidity monthlyAOL = GetMonthlyAOL();
    
    // 2. Scan Weekly candles within the time span of the Monthly AOL
    bool weeklyFormationFound = false;
    for (int i = weeklyStartIndex; i <= weeklyEndIndex; i++) {
        if (IsWeeklyEngulfingFormation(i)) {
            // Check if Weekly formation is INSIDE the Monthly AOL
            if (WeeklyCandle[i].High <= monthlyAOL.topPrice && 
                WeeklyCandle[i].Low >= monthlyAOL.bottomPrice) {
                weeklyFormationFound = true;
                break;
            }
        }
    }
    
    // If no weekly structure validates the monthly level, discard the zone.
    return weeklyFormationFound;
}
```

## 6. Summary for Bot Developers
When scanning for Areas of Liquidity, the bot must run a classification switch:
1. Is it a Type 1? (Check for same color + extreme wick sweep).
2. Is it a Type 2? (Check for opposite color body engulfing).
3. Is it a Type 3? (Check for wickless Candle 1).
4. For HTF analysis, enforce Type 4 overlap rules.

Once classified, the `Box_Top` and `Box_Bottom` variables are rigidly set, defining the exact coordinates for the entry modules and shift calculations.
