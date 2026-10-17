# Part 4: OrderFlows (OF) - True SMC (Luap)

## Strategy Overview
OrderFlow is the highest-level Point of Interest (POI) in True SMC. It represents the entire last buying or selling move before a structural break. Understanding OrderFlow is essential because OrderBlocks (OBs) only work if they are inside a valid, unmitigated OrderFlow.

---

## Visual Setup & Chart Layout
*   **Visual Marker:** A large rectangle covering the entire move from the start of the impulsive push to its extreme.
*   **Spatial Relationship:** The OrderFlow is the "Container" for OrderBlocks.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Identifying Bullish OrderFlow
*   **IF** Price creates a Bullish BOS:
    *   **THEN** Identify the entire last bearish move (series of red candles) that occurred before the break.
    *   **ACTION:** Draw a zone from the High of the first red candle to the Low of the last red candle in that sequence.

### 2. Identifying Bearish OrderFlow
*   **IF** Price creates a Bearish BOS:
    *   **THEN** Identify the entire last bullish move (series of green candles) that occurred before the break.
    *   **ACTION:** Draw a zone from the Low of the first green candle to the High of the last green candle in that sequence.

### 3. The Mitigation Filter
*   **IF** Price has already returned to the OrderFlow zone:
    *   **THEN** It is **Mitigated**. 
    *   **ACTION:** Look for the next unmitigated OrderFlow in the leg or refine to the Extreme.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (Drawing the OF):**
    *   *Visual:* Price drops with 3 big red candles, then shoots up and breaks the previous high.
    *   *Observation:* Luap draws a box around those 3 red candles.
    *   *Logic:* "This is the source of the move. This is where institutional orders are sitting."
*   **Scene 2 (Mitigation check):**
    *   *Visual:* Price comes back down and taps the very top of the box before moving up again.
    *   *Note:* "This OrderFlow is now mitigated. It is no longer high probability for a fresh entry."

---

## Structural Logic Gates for LLM
1. `LOCATE` the last opposite move before BOS.
2. `MARK` the entire range as OrderFlow.
3. `CHECK` for mitigation (body or wick tap).
4. `IF` unmitigated `SET` as primary POI.
5. `RESULT:` A high-level zone for trade consideration.
