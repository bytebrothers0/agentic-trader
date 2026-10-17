# Part 11: Extreme POI Mitigation - True SMC (Luap)

## Strategy Overview
The Extreme POI is the "Origin" of the entire move. It is the last line of defense. If this fails, the trend changes. This module provides the mechanical hierarchy for selecting the exact candle or flow to use at the extreme.

---

## Visual Setup & Chart Layout
*   **Primary Zone:** The Extreme OrderFlow (OF).
*   **Secondary Zone:** The Extreme OrderBlock (OB).
*   **Refinement:** The Shadow (Wick) or a Lower Timeframe zone.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. The OrderFlow Priority
*   **ALWAYS** check the **OrderFlow** first.
*   **IF** the Extreme OrderFlow is **Unmitigated**:
    *   **THEN** This is your primary zone. Mark the whole range of the OF.

### 2. Shifting to the OrderBlock
*   **IF** the Extreme OrderFlow has already been touched (Mitigated):
    *   **THEN** Look inside that OF for a specific **Unmitigated OrderBlock** (candle with FVG).
*   **IF** the OB is also mitigated:
    *   **THEN** Refine to the **unmitigated wick** of the OB.

### 3. The "Last Candle" Rule
*   If everything else is mitigated, the very last candle (the extreme wick) that took the highest/lowest point remains the final POI.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (Mitigated Flow):**
    *   *Visual:* A large bearish move. The first half of the move has already been visited by price.
    *   *Refinement:* Luap zooms into the very top. There is one small candle that price never touched.
    *   *Logic:* "The big box is mitigated. We refine to this small unmitigated candle at the tip."
*   **Scene 2 (The Power of the Wick):**
    *   *Visual:* Price taps the very edge of an OB's wick and flies.
    *   *Commentary:* "Institutions leave their final orders at the extreme wick to ensure maximum liquidity before the move."

---

## Structural Logic Gates for LLM
1. `CHECK` Extreme OrderFlow (OF) unmitigated? If YES, use OF.
2. `IF NO` check Extreme OrderBlock (OB) unmitigated? If YES, use OB.
3. `IF NO` check Extreme Shadow/Wick unmitigated? If YES, use Wick.
4. `IF ALL MITIGATED` the current leg is likely "Fully Mitigated" (High risk).
5. `RESULT:` Precise coordinate for entry.
