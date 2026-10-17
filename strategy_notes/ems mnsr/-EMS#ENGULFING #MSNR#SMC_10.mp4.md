# Video Analysis: EMS#ENGULFING #MSNR#SMC_10.mp4

## Core Trading Logic & Bot Implementation Details

This document extracts the core trading logic, entry models, and visual/structural ambiguities discussed in the video to guide the coding of the MSNR/SMC bot.

### 1. Handling Multiple Order Blocks (OBs) / POIs
**Problem:** What happens when there are multiple Order Blocks or Points of Interest (POIs) in a given area? How do we determine which one to use?
**Bot Logic/Rule:**
*   **Proximity to Liquidity:** Always select the OB/POI that is *closest* to the identified liquidity pool.
*   **Timeframe Scaling for Clarity:** If the lower timeframe (LTF) is noisy and it's hard to pick the right OB, **go one timeframe higher (HTF)**. The HTF will filter out the noise and usually present a clearer, singular Key Level (like a Daily Open-Close Level) that is close to liquidity. 
*   **Example:** If stuck between multiple H1 order blocks, switch to the Daily timeframe to find the Daily Open-Close Level (OCL).

### 2. The Standard Entry Model
The video outlines a top-down, multi-timeframe approach for framing a setup.
**Bot Steps:**
1.  **Identify Sweep & Break of Structure (BOS):** Wait for price to sweep a liquidity pool, followed by a valid Break of Structure.
2.  **Define the Swing Range:** Mark the Swing High and Swing Low. A valid "swing" is confirmed *only* when a break of structure has occurred.
3.  **Premium/Discount Filtering:** 
    *   Use a 50% retracement tool (like a Fibonacci with only 0, 0.5, 1 levels) across the swing range.
    *   For **Sells**: The POI must be in the **Premium Zone** (above the 50% mark).
    *   For **Buys**: The POI must be in the **Discount Zone** (below the 50% mark).
4.  **Identify Internal Liquidity:** Look for structural liquidity built up during the pullback phase (often V-shaped or A-shaped).
5.  **Identify the POI:** Within the Premium/Discount zone, locate the Open-Close Level (OCL) or Breaker Block that sits just above/below the internal liquidity.
6.  **Refinement (The 2-Timeframe Drop):**
    *   Once the HTF POI is identified (e.g., Weekly), drop down **two timeframes** (e.g., to H4) to refine the zone.
    *   Wait for price to tap the HTF zone.
    *   Look for an LTF confirmation (LTF Sweep + LTF BOS) before executing the trade.

### 3. Handling Failed POIs
**Problem:** What if the primary POI fails (price breaks through it and hits the stop loss)?
**Bot Logic/Rule:**
*   **Next Level Check:** You can look for the next available Breaker Block or "last resort" level further deep in the Premium/Discount zone.
*   **Distance to Liquidity Filter:** **CRITICAL RULE:** Do not blindly take the next level. If the next level is *too far* away from the initial liquidity sweep, the setup is invalid.
*   **Reset Condition:** If the next level is too far from liquidity, the bot must abort the current storyline and wait for a completely new structure to form (a fresh sweep and a fresh BOS).

### 4. Visual Ambiguities & Definitions for Coding
*   **Swing:** Do not define a swing purely by a fractal high/low. A swing is only validated when a subsequent Break of Structure happens.
*   **Structural Liquidity:** Visualized as "A-shaped" (for buys) or "V-shaped" (for sells) price action during a pullback. The bot should look for prominent pivot points within the retracement leg before the POI is hit.
*   **Open-Close Level (OCL):** A strong support/resistance level formed by the open/close prices of prominent candles, specifically those that precede a strong push breaking structure. On higher timeframes, these serve as massive magnets for price.
