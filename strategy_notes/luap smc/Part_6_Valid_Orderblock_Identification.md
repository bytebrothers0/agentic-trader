# Part 6: Valid Orderblock (OB) Identification - True SMC (Luap)

## Strategy Overview
A deep dive into the mechanical selection of OrderBlocks. In True SMC, not every opposite candle is an OB. A valid OB must possess specific qualities that prove institutional participation.

---

## Visual Setup & Chart Layout
*   **Visual Focus:** The candle immediately preceding a sharp, impulsive move.
*   **Essential Elements:**
    1.  **The "Sweep" Wick:** The OB candle's wick must be longer than the previous candle's wick/body (Liquidity Grab).
    2.  **The "Gap" (FVG):** A visible space between the OB's high/low and the 3rd candle's low/high.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. The Liquidity Grab Filter
*   **IF** a candle sweeps the high/low of the previous candle AND then causes an impulsive move:
    *   **THEN** This candle is a **Candidate OB**.
*   **IF** it does not sweep anything:
    *   **THEN** It is a "Weak OB" (Avoid).

### 2. The Imbalance (FVG) Filter
*   **IF** there is a Fair Value Gap (FVG) immediately following the Candidate OB:
    *   **THEN** The OB is **Valid**.
*   **IF** the move is slow and all candles are touching (Efficiency):
    *   **THEN** The OB is **Invalid**.

### 3. Mitigation & Refinement
*   **IF** a Valid OB is already touched by a subsequent candle's wick:
    *   **THEN** It is **Mitigated**. 
    *   **ACTION:** Move to the next unmitigated candle in the sequence (Refinement).

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (The Hidden OB):**
    *   *Visual:* A large green candle. The previous red candle is tiny.
    *   *Detail:* The tiny red candle's bottom wick is slightly lower than the green candle's bottom.
    *   *Logic:* This tiny red candle is our OB. We draw the zone from its High to its Low.
*   **Scene 2 (Refining to the Wick):**
    *   *Visual:* The body of the OB is already touched, but the long wick is not.
    *   *Luap's Advice:* "When the body is mitigated, the wick still holds the pending orders. Refine your entry to the 50% level of the wick."

---

## Structural Logic Gates for LLM
1. `SCAN` for the last opposite candle before a BOS.
2. `VERIFY` Liquidity Grab (Did it take the previous candle's extreme?).
3. `VERIFY` FVG (Is there a gap in the next 2 candles?).
4. `CHECK` Mitigation (Has price returned to this specific candle yet?).
5. `IF` all 3 pass `THEN` mark as a "High Probability POI".
