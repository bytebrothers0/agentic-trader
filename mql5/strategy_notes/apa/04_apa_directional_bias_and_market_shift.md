# APA Strategy: Part 4 - Directional Bias and Market Shift

## 1. Timeframe Coordination
Directional bias is not derived from a single chart. It requires alignment across multiple timeframes. The APA strategy mandates that we only trade when at least **two timeframes speak the same language**.

### 1.1 The Two Trading Cycles
The strategy defines two rigid chains of timeframes. A bot must lock into one of these cycles and process data from left to right (Highest TF to Lowest TF).

1. **The Weekly Cycle**: 
   `Weekly (W1)` --> `4-Hour (H4)` --> `30-Minute (M30)` --> `5-Minute (M5)` --> `3-Minute (M3) / 1-Minute (M1)`
2. **The Monthly Cycle**: 
   `Monthly (MN)` --> `Daily (D1)` --> `1-Hour (H1)` --> `15-Minute (M15)` --> `3-Minute (M3)`

### 1.2 Constant vs Situational Timeframes
- **Constant Timeframe**: The anchor of the cycle (Weekly or Monthly). This establishes the primary Area of Liquidity (AOL) and the overarching Directional Bias.
- **Situational Timeframes**: The lower timeframes in the chain. These are used for refinement, identifying liquidity engineering, and executing entries.

**Bot Logic**: The bot must have an initialization parameter `ENUM_CYCLE_TYPE { CYCLE_WEEKLY, CYCLE_MONTHLY }`. Based on this, it hardcodes the array of timeframes it will poll.

## 2. Understanding Market Shift Conditions
A "Shift" is the mechanism by which the market changes direction or confirms a trend continuation. It is the algorithmic trigger that moves the bot from "waiting" to "active".

We track three distinct structural events: Shift Point, Reclaim Point, and Transition.

### 2.1 The Shift Point
- **Definition**: The point at which the previous market trend is invalidated.
- **Bullish Shift**: In a downtrend, price closes **ABOVE** the last significant lower high (resistance).
- **Bearish Shift**: In an uptrend, price closes **BELOW** the last significant higher low (support).
- **Implication**: A close beyond the shift point indicates a potential reversal.

**Bot Implementation**:
```cpp
double CalculateShiftPoint(bool isBullishTrend) {
    if (isBullishTrend) {
        // Find the lowest point of the current pullback, then find the swing high preceding it
        return GetLastSwingHigh(); // Bearish shift point
    } else {
        return GetLastSwingLow();  // Bullish shift point
    }
}
// Trigger: if (Close[0] < BearishShiftPoint) -> Trigger Bearish Shift
```

### 2.2 The Reclaim Point
- **Definition**: If a Shift occurs (e.g., price closes below support), but the market immediately reverses and takes out the absolute extreme that caused the shift, the trend is "Reclaimed".
- **Example**: Uptrend -> Price breaks below support (Bearish Shift) -> Price immediately rallies and breaks above the highest high before the shift -> **Bullish Trend Reclaimed**.
- **Implication**: The initial shift was a trap (Liquidity Engineering). The original trend resumes with extreme strength.

**Bot Implementation**:
```cpp
// If a Bearish Shift occurred at Index X
double reclaimPoint = HighestHighSince(Index_X - N, Index_X); 
if (Close[0] > reclaimPoint) {
    State = TREND_RECLAIMED_BULLISH;
    // Execute continuation buy protocols
}
```

### 2.3 Transition
- **Definition**: A Transition occurs when the market closes beyond the shift point, but fails to form a clear subsequent structure (inside or outside formation) before reversing again. 
- **Implication**: The market is in chop/uncertainty. The bot must stand down until a clear new AOL is formed.

## 3. Types of Shifts
When a shift occurs, it leaves behind an Area of Liquidity. The structure of this shift matters.

### 3.1 Shift with Inside Formation
- The shift occurs, and the price action creates a new AOL strictly *inside* the bounds of the previous structure.
- **Bot Logic**: The bounding box of the new `Situational_AOL` is `[Max(NewAOL.Top, PrevAOL.Top), Min(NewAOL.Bottom, PrevAOL.Bottom)]`.

### 3.2 Shift with Outside Formation
- The shift occurs, but before it invalidates the trend, it violates a previous AOL, creating a new structure *outside* the original bounds.
- **Bot Logic**: The bot must map the new `Situational_AOL` independent of the old bounding box, as the market has engineered liquidity outside the expected zone.

## 4. Execution Logic Flow
1. Determine Bias from **Constant TF** (e.g., Monthly Bullish).
2. Wait for price to enter the Monthly AOL.
3. Drop to **Situational TF 1** (Daily).
4. Monitor for a **Bullish Shift** in the Daily TF.
5. If Daily shifts bullish, identify the new Daily AOL (Inside or Outside formation).
6. Drop to **Situational TF 2** (H1) and await the Entry Module protocols.
