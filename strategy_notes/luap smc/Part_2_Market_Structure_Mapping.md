# Part 2: True SMC Market Structure Mapping - True SMC (Luap)

## Strategy Overview
Market Structure Mapping is the process of identifying the current trend (Bullish/Bearish) and defining the "Trading Range". In True SMC, structure is not marked simply when price breaks a high or low; it requires the prior "Inducement" (IDM) to be swept to confirm a swing point.

---

## Visual Setup & Chart Layout
*   **Timeframe:** Multi-timeframe analysis (HTF for direction, LTF for entries).
*   **Indicators:** None.
*   **Visual Elements:**
    *   **BOS (Break of Structure):** A line drawn across a previous Higher High or Lower Low, labeled only after a body close.
    *   **IDM (Inducement):** A small "x" or label placed at the first valid pullback low (in uptrend) or high (in downtrend).
    *   **Swing Points:** Large circles or dots marking confirmed HH/HL or LL/LH.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Confirming a Higher High (Bullish)
*   **IF** Price is in an uptrend and makes a new high:
    *   **THEN** This high is **TEMPORARY**.
*   **IF** Price pulls back and takes out the **FIRST VALID PULLBACK LOW (IDM)**:
    *   **THEN** The previous high is now **CONFIRMED** as a Higher High (HH).
*   **IF** Price breaks this confirmed HH with a **CANDLE BODY CLOSE**:
    *   **THEN** This is a **Valid BOS (Bullish)**.

### 2. Confirming a Lower Low (Bearish)
*   **IF** Price is in a downtrend and makes a new low:
    *   **THEN** This low is **TEMPORARY**.
*   **IF** Price pulls back and takes out the **FIRST VALID PULLBACK HIGH (IDM)**:
    *   **THEN** The previous low is now **CONFIRMED** as a Lower Low (LL).
*   **IF** Price breaks this confirmed LL with a **CANDLE BODY CLOSE**:
    *   **THEN** This is a **Valid BOS (Bearish)**.

### 3. Change of Character (CHoCH)
*   **IF** Price is in an uptrend and breaks the **LAST PROTECTED HIGHER LOW** (the low that caused the last BOS) with a **BODY CLOSE**:
    *   **THEN** This is a **CHoCH (Bearish Reversal)**.
*   **IF** Price is in a downtrend and breaks the **LAST PROTECTED LOWER HIGH** (the high that caused the last BOS) with a **BODY CLOSE**:
    *   **THEN** This is a **CHoCH (Bullish Reversal)**.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (The IDM Sweep):**
    *   *Visual:* Price moves up, creates a small zig-zag (pullback), then shoots up to a new high.
    *   *Identification:* The bottom of that zig-zag is the IDM.
    *   *Action:* Price comes back down, sweeps that low (wick is enough), then goes up.
    *   *Logic:* Only AFTER the low is swept do we mark the peak as "Confirmed HH".
*   **Scene 2 (The BOS):**
    *   *Visual:* Price pushes above the Confirmed HH. 
    *   *Constraint:* If price only wicks above, it is NOT a BOS. It is a "Liquidity Sweep" (potentially SMT).
    *   *Validation:* We wait for a full candle body to close above the line.

---

## Structural Logic Gates for LLM
1. `IDENTIFY` the first valid pullback (refer to Part 1 rules).
2. `MARK` this pullback as IDM.
3. `WAIT` for price to sweep IDM.
4. `CONFIRM` the swing high/low only after IDM is taken.
5. `IF` price breaks the confirmed swing point with a body close `THEN` label as BOS.
6. `IF` price breaks the protected swing point (opposite side) `THEN` label as CHoCH.
7. `RESULT:` A clear definition of the current "Trading Range" (between the confirmed HH and the protected HL).
