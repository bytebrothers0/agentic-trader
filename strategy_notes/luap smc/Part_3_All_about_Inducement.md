# Part 3: All about Inducement (IDM) - True SMC (Luap)

## Strategy Overview
Inducement (IDM) is the most critical concept in True SMC. It is a liquidity "trap" designed to lure early sellers/buyers before the actual institutional move. In this framework, a Higher High or Lower Low is **NEVER** confirmed until the IDM is taken.

---

## Visual Setup & Chart Layout
*   **Visual Marker:** Labeled with "IDM" and often a small "x" on the chart.
*   **Location:** The **First Valid Pullback** in the current impulsive leg.
*   **Spatial Relationship:**
    *   **Bullish:** The IDM is the low of the first valid pullback below the current temporary high.
    *   **Bearish:** The IDM is the high of the first valid pullback above the current temporary low.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Identifying the IDM
*   **IF** Price makes a new temporary extreme (High in Bullish, Low in Bearish):
    *   **THEN** Look backwards for the **most recent valid pullback** (refer to Part 1 rules).
    *   **THEN** Mark the extreme of that pullback (Low for Bullish, High for Bearish) as **IDM**.

### 2. Confirming Swing Points via IDM Sweep
*   **IF** Price sweeps the IDM (Wick or Body):
    *   **THEN** The previous extreme is now **Confirmed**.
    *   **THEN** A "Trading Range" is established between this Confirmed Extreme and the Protected Swing Point.
*   **IF** Price creates a new extreme *without* taking IDM:
    *   **THEN** The IDM **shifts** to the new most recent valid pullback. This is "IDM Shifting".

### 3. SMT (Smart Money Trap) Awareness
*   **IF** Price reacts from a zone *before* taking IDM:
    *   **THEN** This reaction is likely an SMT.
    *   **ACTION:** Do not enter here. Wait for the IDM sweep.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (IDM Shifting):**
    *   *Visual:* Price moves up, pulls back (Pullback A), moves up again, pulls back (Pullback B), then makes a new high.
    *   *Logic:* Initially, Pullback A was IDM. Once the new high was made, IDM shifted to Pullback B.
    *   *Observation:* Price must sweep Pullback B to confirm the high.
*   **Scene 2 (The Clean Sweep):**
    *   *Visual:* A sharp move down that punctures the IDM low, followed by an immediate rejection.
    *   *Logic:* This "Sweep" provides the fuel (liquidity) for the institutional move.

---

## Structural Logic Gates for LLM
1. `SCAN` backwards from the current price extreme.
2. `FIND` the first candle-level pullback.
3. `IF` no pullback exists `THEN` the leg is "Impulsive" (No IDM yet).
4. `IF` pullback exists `LABEL` its extreme as IDM.
5. `MONITOR` for price to cross the IDM level.
6. `IF` IDM is taken `THEN` lock the Swing High/Low.
7. `IF` price breaks the temporary extreme without taking IDM `THEN` move IDM to the next pullback.
