# Part 5: OrderBlocks (OB) - True SMC (Luap)

## Strategy Overview
OrderBlocks are specific candles within an OrderFlow where the actual institutional "Block" of orders is placed. They are the refined version of OrderFlow and provide the tightest stop-loss levels.

---

## Visual Setup & Chart Layout
*   **Visual Marker:** A smaller rectangle covering a single candle.
*   **Color:** Usually the last opposite colored candle (e.g., last Red candle before a Green move).

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. The Valid OB Checklist
To be considered for entry, an OB **MUST** pass three tests:
1.  **Imbalance (FVG):** There must be a gap between the OB candle and the 3rd candle in the move.
2.  **Unmitigated:** Price has not touched the OB since it was created.
3.  **Liquidity Sweep:** (Bonus/High Prob) The OB candle itself swept the high/low of a previous candle.

### 2. The Decision Point
*   **IF** an OB is located right at the start of the move:
    *   **THEN** It is the **Extreme OB**.
*   **IF** an OB is located near the Inducement (IDM):
    *   **THEN** It is the **Decisional OB**.

### 3. Invalid OBs
*   **IF** an OB has no FVG above/below it:
    *   **THEN** It is an "Engineered OB" or SMT. **IGNORE**.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (The FVG Filter):**
    *   *Visual:* A red candle followed by a massive green candle.
    *   *Detail:* The green candle is so big that its body doesn't overlap with the next candle.
    *   *Logic:* This "gap" proves that there were no sell orders left, only buy orders. The red candle is a valid OB.
*   **Scene 2 (The Sweep OB):**
    *   *Visual:* A red candle wicks below the previous red candle's low before price shoots up.
    *   *Luap's Commentary:* "This is the best kind of OB. It took the internal liquidity first before the move."

---

## Structural Logic Gates for LLM
1. `FIND` candles within the unmitigated OrderFlow.
2. `APPLY` the FVG filter (Is there a gap?).
3. `APPLY` the Mitigation filter (Is it fresh?).
4. `IF` passes `THEN` label as Valid OrderBlock.
5. `RESULT:` A precise entry coordinate.
