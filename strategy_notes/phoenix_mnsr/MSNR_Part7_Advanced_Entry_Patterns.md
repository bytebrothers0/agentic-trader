# MSNR Trading Strategy - Part 7: Advanced Entry Patterns (OCL and RBS)

## 1. Expanding the Entry Arsenal

While a simple Doji at resistance provides a solid baseline, the MSNR strategy delves into more complex candlestick interaction patterns to fine-tune entries. The PDF specifically mentions looking for "OCL, Doji, and RBS."

Understanding and coding these specific structural interaction patterns is crucial for capturing the high-precision entries the strategy aims for.

### 1.1 OCL (Open/Close Level)

The "OCL" refers to the precise price level where a significant candle opened or closed. This is often the body high or low of a swing point, rather than the extreme wick.

**Visual Ambiguity & Coding Logic:**
- **Ambiguity:** Why prioritize the body (OCL) over the wick? In SMC, wicks represent liquidity sweeps, while candle bodies represent the true "agreed upon" value and the transfer of volume. Support/Resistance lines drawn on bodies (OCLs) are often more respected by institutional algorithms during pullbacks than lines drawn on wicks.
- **Bot Logic:**
    1.  **Defining the OCL:** When the bot identifies a significant swing high (e.g., the high before the MSS), it must store not just the `High` price, but also the `Max(Open, Close)` price of that specific peak candle. This `Max(Open, Close)` is the OCL.
    2.  **Using the OCL:** When price retraces back to the zone, the bot shouldn't just look at a broad area. It should draw a precise horizontal line at the OCL price. The entry trigger is significantly enhanced if the pullback candle (like a Doji) reacts *exactly* at this OCL price line. The bot logic checks: `if (MathAbs(PullbackCandle.High - OCL_Price) < Tight_Tolerance)`.

### 1.2 RBS (Resistance Becomes Support) and SBR (Support Becomes Resistance)

The concepts of RBS and SBR are classic price action staples, heavily utilized in MSNR.

The PDF highlights finding areas that previously acted as resistance and are now being tested as support (or vice-versa).

**Coding the RBS/SBR Flip:**
1.  **Historical Level Tracking:** The bot must maintain a rolling history of key broken support/resistance levels. Let's trace a short setup:
    - The chart is moving up. It creates a Resistance swing high (`Res1`), pulls back, and then breaks above it.
    - `Res1` is now theoretically a Support level (RBS).
    - Price continues up, does the Target Sweep (TS), and then executes the Market Structure Shift (MSS) downward.
    - The price drops significantly.
2.  **The Flip as an Entry Zone:** As price retraces back *up* after the MSS, the bot looks at its historical levels. If the old `Res1` level (now technically resistance again after being broken downwards during the MSS) lines up with the current Premium retracement zone, it becomes a high-probability POI.
3.  **Bot Logic Sequence:**
    - Detect breakout above Resistance -> Store Resistance as Potential Support.
    - Detect MSS back below that level -> Level flips back to Potential Resistance (SBR).
    - During pullback, check if `CurrentPrice` approaches `SBR_Level`. If so, activate Doji/OCL entry trigger detection at this exact level.

## 2. Combining the Patterns: The "OCL DOJI RBS" Setup

The PDF explicitly mentions looking for a combination: "OCL DOJI RBS". This is the holy grail setup of this section.

**Decoding the Combination for the Bot:**
This means the bot is searching for a very specific, multi-layered confluence:
1.  **The Location (RBS/SBR):** The price has pulled back into a zone that was previously a major structural support and is now acting as resistance (SBR).
2.  **The Specific Level (OCL):** Within that broader SBR zone, there is a specific Open/Close Level from a key past candle that defines the exact mathematical ceiling.
3.  **The Trigger (Doji):** Right as the price taps that precise OCL line within the SBR zone, it forms a Doji candle, indicating instant rejection.

**Coding the "Perfect Storm" Condition:**
The boolean logic for the entry trigger becomes highly restrictive, ensuring the bot only takes the highest quality setups:

```cpp
bool isPerfectSetup = false;

// 1. Is price near a historical flipped level?
if (MathAbs(CurrentPrice - historical_SBR_Level) <= ZoneTolerance) {
    
    // 2. Is there a specific OCL lining up?
    if (MathAbs(CurrentPrice - specific_OCL_Price) <= PreciseTolerance) {
        
        // 3. Did the current candle form a Doji upon tapping the OCL?
        if (IsCandleDoji(CurrentCandle) == true) {
            isPerfectSetup = true;
            // Execute Trade
        }
    }
}
```

## 3. The Psychology of the Precision

Why be so precise? The MSNR strategy relies on 10 pip stop losses. You cannot afford to enter "roughly" in a zone. If you enter early in a wide resistance block, your 10 pip stop will be tagged before the real move happens.

By programming the bot to identify the OCL and wait for the precise Doji reaction at that micro-level (often confirming the RBS/SBR flip), you ensure that the entry is taken at the exact moment the institutional order flow changes direction, minimizing drawdown and keeping that tight stop loss secure.
