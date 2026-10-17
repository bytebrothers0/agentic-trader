# Part 8: Inducement (IDM) Sweep Entry Module - True SMC (Luap)

## Strategy Overview
This is **Entry Module No.1**. It allows for direct execution on the current timeframe immediately after an Inducement sweep. It is a "Liquidity Grab" entry that does not require waiting for a lower timeframe CHoCH if the visual signals are strong.

---

## Visual Setup & Chart Layout
*   **The Trigger Zone:** The area immediately above/below the IDM line.
*   **The Trigger Candle:** A candle that sweeps the IDM and then rejects it.
*   **Indicators:** None (Pure Price Action).

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. The Sweep Condition
*   **IF** Price touches the IDM level:
    *   **THEN** Monitor the candle behavior.
*   **IF** the candle wicks through the IDM but **CLOSES** back inside the previous range:
    *   **THEN** A "Sweep" has occurred.

### 2. The Execution Trigger (The "Engulfing" Rule)
*   **IF** a sweep occurs:
    *   **THEN** Wait for a **Reversal Candle**.
    *   **TRIGGER:** Enter the trade when a subsequent candle breaks the High/Low of the "Sweeping Candle" (Displacement).
    *   **Visual Patterns:** Bullish/Bearish Engulfing or a Pin Bar with a long wick.

### 3. Trade Parameters
*   **Stop Loss (SL):** 2-3 pips above/below the highest/lowest point of the sweep wick.
*   **Take Profit (TP):** The External Liquidity (The current swing target of the leg).

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (The Perfect Entry):**
    *   *Visual:* Price is in a downtrend. It pulls up to the IDM high.
    *   *Action:* A green candle wicks above the IDM line, then a red candle completely engulfs it.
    *   *Trigger:* As soon as the red candle closes, or as soon as price breaks the low of the green wick.
*   **Scene 2 (Failed Sweep):**
    *   *Visual:* A candle closes with its **Body** above the IDM line.
    *   *Luap's Warning:* "This is not a sweep. This is a potential trend change. Do not use Module 1 here. Wait for deeper mitigation."

---

## Structural Logic Gates for LLM
1. `SET` alert at IDM level.
2. `IF` price crosses IDM `CHECK` candle closure.
3. `IF` closure is a wick (Sweep) `THEN` look for reversal pattern.
4. `IF` body close occurs `THEN` cancel Module 1 setup.
5. `IF` reversal candle forms `THEN` execute at market.
6. `PLACE` SL at sweep extreme + buffer.
