# Part 1: Valid Pullback Identification - True SMC (Luap)

## Strategy Overview
The foundation of the True SMC mechanical framework. A "Valid Pullback" is not merely price moving against the trend; it is a mathematically defined event based on candlestick range breaches. This identification is the prerequisite for marking Inducement (IDM) and subsequent Market Structure (BOS/CHoCH).

---

## Visual Setup & Chart Layout
*   **Timeframe:** Works on all timeframes (Fractal Nature), typically shown on 15m or 1H for structure.
*   **Indicators:** None. This is pure price action (Candlestick analysis).
*   **Candle Colors:** 
    *   **Bullish:** Typically Green/White.
    *   **Bearish:** Typically Red/Black.
*   **Key Focus:** The High and Low of the "High Candle" (in an uptrend) or "Low Candle" (in a downtrend).

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Bullish Pullback Identification (Uptrend)
*   **IF** Price creates a new "Highest High" (HH) in the current leg:
    *   **THEN** Identify the candle that created this HH. This is the **Target Candle**.
*   **IF** a subsequent candle's **Wick or Body** breaks the **LOW** of the Target Candle:
    *   **THEN** A **Valid Pullback** is confirmed.
*   **IF** the subsequent candles fail to break the Low of the Target Candle and instead break its High:
    *   **THEN** The Target Candle shifts to the new candle that made the Higher High. Reset the check.

### 2. Bearish Pullback Identification (Downtrend)
*   **IF** Price creates a new "Lowest Low" (LL) in the current leg:
    *   **THEN** Identify the candle that created this LL. This is the **Target Candle**.
*   **IF** a subsequent candle's **Wick or Body** breaks the **HIGH** of the Target Candle:
    *   **THEN** A **Valid Pullback** is confirmed.
*   **IF** the subsequent candles fail to break the High of the Target Candle and instead break its Low:
    *   **THEN** The Target Candle shifts to the new candle that made the Lower Low. Reset the check.

### 3. The Inside Bar Rule (The "Non-Event")
*   **IF** a candle's entire range (High and Low) is contained within the range of the previous candle:
    *   **THEN** This is an **Inside Bar**.
    *   **ACTION:** Ignore this candle. The "Target Candle" remains the previous candle (The Mother Candle).
    *   **LOGIC:** A pullback is only valid if the **Mother Candle's** High/Low is broken, not the Inside Bar's.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (Bullish Example):** 
    *   *Visual:* A series of 3 bullish candles. The 2nd candle is the highest.
    *   *Observation:* The 3rd candle is small and stays within the 2nd candle's range.
    *   *Logic:* This is an Inside Bar. No pullback yet.
    *   *Action:* Wait for the 4th candle. If the 4th candle breaks the Low of the 2nd candle, the pullback is valid.
*   **Scene 2 (The Trap):**
    *   *Visual:* A large impulsive move where many small candles move "downwards" but never break the low of the candle that made the high.
    *   *Luap's Commentary:* "Most traders think this is a pullback because price is moving down. In True SMC, this is just a single leg. No previous candle low was taken."

---

## Structural Logic Gates for LLM
1. `CHECK` current trend (Bullish/Bearish).
2. `IDENTIFY` the candle with the current extreme (Highest High or Lowest Low).
3. `MONITOR` subsequent candles for a break of the Target Candle's opposite extreme (Low for Bullish, High for Bearish).
4. `FILTER` out all Inside Bars.
5. `CONFIRM` Pullback only when the breach occurs.
6. `RESULT:` This confirmed pullback now becomes the potential **Inducement (IDM)** for the next structural step.
