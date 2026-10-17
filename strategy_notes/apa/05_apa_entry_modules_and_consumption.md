# APA Strategy: Part 5 - Entry Modules and Consumption

## 1. Liquidity Consumption
Before entering a trade, the bot must assess whether an Area of Liquidity (AOL) is "fresh" or "consumed."
- **Definition of Consumption**: If price enters an AOL and utilizes **50% or more** of the zone's depth, that AOL is considered consumed.
- **Implication**: A consumed AOL is less reliable for future reactions. The market is likely to break through it next time.

**Bot Implementation for Consumption:**
```cpp
bool IsAOLConsumed(AreaOfLiquidity aol) {
    double aolHeight = MathAbs(aol.topPrice - aol.bottomPrice);
    double threshold50 = aol.bottomPrice + (aolHeight * 0.5); // For Bullish AOL
    
    // Scan price action since AOL formation
    for (int i = aol.formationIndex; i >= 0; i--) {
        if (Low[i] <= threshold50) {
            return true; // 50% penetrated, zone is consumed
        }
    }
    return false;
}
```

## 2. FTAs (First Trouble Areas)
When trading a situational timeframe (e.g., H1), higher timeframes (e.g., H4 or Daily) act as powerful opposing forces. These are called FTAs.
- **The Rule**: The higher the timeframe, the more powerful the liquidity. You cannot blindly trade a 15-minute setup into an H4 AOL.
- **Management**: If a trade approaches an FTA, the bot must either take partial profits, move stop-loss to breakeven, or avoid the trade entirely if the Reward-to-Risk ratio to the FTA is poor.

## 3. The Entry Modules
The APA strategy defines 5 specific modules for execution.

### 3.1 Shift Entry Module
This is the standard cascade entry.
1. **Identify** AOL on Constant TF.
2. Price enters AOL.
3. **Shift** occurs on Situational TF 1 (e.g., Daily). Mark the new Daily AOL.
4. Price enters Daily AOL.
5. **Shift** occurs on Situational TF 2 (e.g., H1). Mark H1 AOL.
6. Execute limit order at H1 AOL, Stop Loss at H1 Invalidation point.

### 3.2 Flip Entry Module Type 1
Uses support/resistance flips combined with single-candle structures.
1. **Spot Flip Level**: Find a swing point with >2 touches on H4 or above.
2. **Break**: Price breaks the level aggressively.
3. **Single Candle Check**: Look for a specific single candle structure (a Type 3 AOL) formed *just before* the break.
4. **Execution**: Set limit order at that single candle structure when price returns.

### 3.3 Flip Entry Module Type 2
Uses flip levels combined with multiple-candle structures and requires HTF Wick Overlap.
1. **Spot Flip Level + Multi-Candle**: Identify flip level + a consolidation block (multi-candle) on H4.
2. **HTF Confirmation**: Step up one TF (to Daily).
3. **Wick Overlap Check**: Look for overlapping wicks in the Daily timeframe corresponding to that H4 consolidation block.
   - *Bot Logic*: `if (DailyCandle[i].UpperWick overlaps DailyCandle[i-1].LowerWick) { Valid = true; }`
4. **Execution**: If wick overlap exists, place entry at the flip zone. If NO wick overlap, **abort trade**.

### 3.4 Liquidity Engineering Entry Module
Combines L.E. with the Shift cascade.
1. **Spot Constant TF AOL**.
2. **Move to Situational TF 1**: Wait for L.E. (Sweep + CHoCH) near the invalidation zone of the Constant AOL.
3. **Tap**: Wait for price to tap the newly engineered Situational TF 1 liquidity.
4. **Move to Situational TF 2**: Look for a second phase of L.E. (another sweep + CHoCH) in the lower timeframe.
5. **Execution**: Enter on the confirmed double-L.E. structure. This offers extreme precision and tight stop losses.

### 3.5 FTA Entry Module
Trading reversals off Trouble Areas.
1. **Identify Shift**: Spot a shift in a trading cycle (e.g., H1).
2. **Coordinate with HTF**: Check the H4 timeframe.
3. **FTA Validation**: Did the H4 also shift, or is it just transitioning? 
   - If H4 shifted -> High probability entry on H1 formation.
   - If H4 did not shift (just reacting to an FTA) -> Caution, reduce risk or skip.

## 4. Final Bot Architecture Summary
To bring all 5 parts together, the MQL5 bot must possess:
- A `TimeframeCoordinator` to pull data strictly along the Weekly or Monthly chain.
- A `LiquidityScanner` to detect Type 1-4 Engulfing patterns and mark AOL bounding boxes.
- A `MarketStructureTracker` to identify Shifts, Reclaims, Transitions, and L.E. (Overthrow/Thrust/FMD/CHoCH).
- A `RiskManager` to calculate 50% Consumption thresholds and scan for impending FTAs.
- An `ExecutionEngine` that maps precisely to one of the 5 Entry Modules based on current market state.
