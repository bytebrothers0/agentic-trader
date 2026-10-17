# Part 12: Major vs Minor Inducement (IDM) - True SMC (Luap)

## Strategy Overview
Not all Inducements are equal. This module breaks down how to differentiate between high-probability "Major" IDM and lower-probability "Minor" IDM on a real chart.

---

## Visual Setup & Chart Layout
*   **Major IDM:** A large, clear pullback that occurs after a Break of Structure (BOS).
*   **Minor IDM:** A smaller, often "intra-candle" pullback that occurs before a BOS.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. The "BOS" Filter
*   **IF** a valid pullback is formed **BEFORE** price breaks the previous high/low (BOS):
    *   **THEN** This is **Minor IDM**.
*   **IF** a valid pullback is formed **AFTER** price breaks the high/low and creates a new leg:
    *   **THEN** This is **Major IDM**.

### 2. Probability Scaling
*   **IF** Price sweeps a **Major IDM**:
    *   **THEN** The reversal is high probability (approx. 70-80%).
*   **IF** Price sweeps a **Minor IDM**:
    *   **THEN** The reversal is moderate probability (approx. 50%). Price often sweeps Minor IDM only to go deeper.

### 3. The "Major Sweep" Rule
*   In a complex trading range, always look for the **Highest/Lowest Major IDM** as the ultimate liquidity target before the Extreme.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (Minor Trap):**
    *   *Visual:* Price is moving up, makes a tiny pullback, then BOS. That tiny pullback is Minor IDM.
    *   *Observation:* Price sweeps it, reacts for a few candles, then crashes through to the Major IDM.
*   **Scene 2 (Major Confirmation):**
    *   *Visual:* Price makes a massive impulsive leg and then a deep, clear pullback.
    *   *Luap's Logic:* "This is a Major Inducement. It is very visible to everyone. This is where we want to see the sweep."

---

## Structural Logic Gates for LLM
1. `SEQUENCE` the pullbacks in the leg.
2. `TAG` pullbacks before BOS as "Minor".
3. `TAG` pullbacks after BOS as "Major".
4. `PRIORITIZE` Major IDM sweeps for heavy risk (1%).
5. `LIMIT` Minor IDM sweeps to light risk or scalp only.
