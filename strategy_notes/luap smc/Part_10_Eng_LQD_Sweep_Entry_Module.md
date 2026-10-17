# Part 10: Engineering Liquidity (Eng LQD) Sweep Entry Module - True SMC (Luap)

## Strategy Overview
This is **Entry Module No.3**. It is considered the highest probability entry in the True SMC arsenal. It occurs when price sweeps the "engineered" liquidity resting just in front of the Extreme POI.

---

## Visual Setup & Chart Layout
*   **The Setup:** A clean pullback low/high (Eng LQD) positioned between the Decisional and the Extreme.
*   **The Trap:** It often looks like a strong support or a beautiful OB that "should" hold.
*   **The Reality:** We wait for price to "crash" through this level into the Extreme origin.

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Identifying the "Engineered" Zone
*   **IF** Price is heading towards the Extreme POI:
    *   **THEN** Identify the last valid pullback formed before reaching that POI.
    *   **THEN** Mark this as **Eng LQD**.

### 2. The Execution Trigger
*   **IF** Price wicks through the Eng LQD level:
    *   **THEN** It must immediately tap the **Extreme OrderFlow or OrderBlock**.
*   **TRIGGER:** Enter the trade when price shows a rejection from the Extreme (displacement back above the Eng LQD level).

### 3. Risk Management
*   **Stop Loss (SL):** Placed exactly below the Extreme POI (the absolute bottom/top of the range).
*   **Take Profit (TP):** The External Liquidity (The current swing target).

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (The Double Trap):**
    *   *Visual:* Price sweeps IDM and reacts. Traders enter. Then price breaks that reaction (Sweeping Decisional) and heads for the Extreme.
    *   *Observation:* Right before the Extreme, there's a small zig-zag (Eng LQD).
    *   *Outcome:* Price sweeps that zig-zag, touches the origin candle (Extreme), and reverses 1:10.
*   **Scene 2 (Direct Entry):**
    *   *Luap's Advice:* "You don't always need a 1m CHoCH here. If you see a strong sweep of Eng LQD into an unmitigated extreme, you can enter with a limit order at the extreme."

---

## Structural Logic Gates for LLM
1. `LOCATE` the Extreme POI.
2. `LOCATE` the Eng LQD (last pullback before Extreme).
3. `IF` price touches Extreme `AND` Eng LQD has been swept `THEN` execute entry.
4. `IF` price reaches Extreme `WITHOUT` sweeping Eng LQD `THEN` exercise caution (possible deeper mitigation).
5. `TARGET` 1:5+ RR.
