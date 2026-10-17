# Part 9: Decisional POI Mitigation - True SMC (Luap)

## Strategy Overview
Decisional POIs are "mid-range" zones that caused a structural break. While lower probability than Extremes, they offer many trade opportunities. This module focuses on how to identify when a Decisional POI is "valid enough" to trade.

---

## Visual Setup & Chart Layout
*   **Location:** The unmitigated OrderFlow/OrderBlock responsible for the most recent BOS.
*   **Visual Marker:** Labeled as "Decisional POI".

---

## Core Mechanical Rules (IF/THEN Logic)

### 1. Identifying the Decisional POI
*   **IF** Price creates a BOS:
    *   **THEN** Trace the move back to the point where the impulsive push started.
    *   **THEN** Identify the first unmitigated OB/OF in that push. This is the **Decisional**.

### 2. The "Inducement" Filter for Decisional
*   **IF** a Decisional POI has **NO Inducement** (no pullback) before it:
    *   **THEN** It is **Invalid/SMT**.
*   **IF** there is a clear IDM sweep into the Decisional POI:
    *   **THEN** The POI is **Valid for Entry**.

### 3. Mitigation Rules
*   **IF** Price taps the Decisional POI and shows a reversal:
    *   **THEN** The POI is **Mitigated**. 
    *   **IF** the reaction fails and price breaks through:
        *   **THEN** The market is heading for the **Extreme POI**.

---

## Visual Example Breakdown (Video Reference)
*   **Scene 1 (Decisional vs Extreme):**
    *   *Visual:* A chart with two boxes. One near the IDM (Decisional) and one at the very bottom (Extreme).
    *   *Observation:* Price hits the Decisional, gives a small 5m CHoCH, then fails. 
    *   *Luap's Logic:* "This is why we use small risk at Decisional. It often acts as Engineering Liquidity for the Extreme."
*   **Scene 2 (The Successful Decisional):**
    *   *Visual:* A clean IDM sweep directly into a Decisional OB followed by a massive move.
    *   *Constraint:* This happens when the Decisional itself is part of a "Major" OrderFlow.

---

## Structural Logic Gates for LLM
1. `FIND` the zone that caused the BOS.
2. `CHECK` for unmitigated status.
3. `CHECK` for IDM sweep before the zone.
4. `IF` IDM exists `AND` zone is unmitigated `THEN` set as secondary entry POI.
5. `LIMIT` risk to 0.5% at Decisional, 1% at Extreme.
