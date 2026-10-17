# Full Strategy for EMS with Breakdown of How to Use EG and EF for Bias (Part 1)

This document extracts the trading logic and visual mechanics from the first video on the EMS/MSNR/SMC strategy. It details the core concepts of Engulfing candles, Storylines, Key Levels, and the multi-timeframe entry protocol.

## 1. Engulfing Candles (EG) and Engulfing Fails (EF)

The strategy heavily relies on understanding and reacting to engulfing candlestick patterns. There are two primary ways these patterns are traded.

### Main Engulfing (EG)
*   **Visual Definition:** A large candle (the engulfing candle) completely covers the body (and often wicks) of the preceding smaller candle(s).
*   **Bullish EG:** A small bearish candle is followed by a larger bullish candle that completely engulfs it.
*   **Bearish EG:** A small bullish candle is followed by a larger bearish candle that completely engulfs it.
*   **Mechanic:** After a valid EG is formed, the expectation is that price will pull back into the zone of the engulfed candle and then continue in the direction of the engulf (fly to the upside for bullish, fall to the downside for bearish).

### Engulfing Fail (EF)
*   **Visual Definition:** An engulfing pattern forms, but the price fails to respect it. Instead of bouncing from the engulfing zone, the price breaks entirely through it.
*   **Mechanic:** The strategy treats failed setups as opportunities. When price breaks through an engulfing zone, wait for the price to pull back *into* that now-failed zone. The failed zone acts as a reversal point (resistance becomes support, support becomes resistance).
*   **Example:** A bullish engulfing pattern forms. Price pulls back but breaks below the pattern. We now expect price to pull up into this failed bullish zone and reject it to the downside (sell off).

## 2. Key Levels and Storylines

A "Storyline" dictates the overall bias and direction. Storylines are built upon reactions at "Key Levels".

### Types of Key Levels
1.  **A-Shape Figure (Resistance):** A clear peak in the market structure resembling an 'A'.
2.  **V-Shape Figure (Support):** A clear valley in the market structure resembling a 'V'.
3.  **OCL (Open Close Level):** Significant levels where candles frequently open and close with strong momentum.
4.  **QMR (Quasimodo Resistance/Support):** A classic QM pattern level (Higher High followed by a Lower Low, entry at the previous High/Shoulder).

### The Role of Key Levels
*   These key levels act as **rejection zones**.
*   **Valid Rejection:** For a key level to be confirmed, price must tap the level and then **close below** (for resistance) or **close above** (for support) the key level zone. Just a wick tap is not enough; the body close confirms the rejection and sets the storyline.

## 3. Determining Direction (Bias)

Direction is always determined from a Higher Timeframe (HTF) using the Storyline concept.

*   **Primary HTF:** Start with the Weekly timeframe.
*   **Protocol:** Look for a rejection at a Weekly Key Level. If the Weekly chart taps a Weekly Key Level and closes below it (e.g., rejecting resistance), the bias is **Bearish**.
*   **Secondary HTF:** If there is no clear rejection on the Weekly timeframe, step down to the Daily timeframe to find the storyline rejection.

## 4. The Multi-Timeframe Entry Protocol

Once the HTF bias is established, the bot should follow a cascading top-down approach for entries.

### Step-by-Step Entry Flow:
1.  **HTF Bias (Weekly or Daily):** Identify a clean rejection (tap and close beyond) at a Key Level (A-shape, V-shape, OCL, QMR).
    *   *Example: Daily chart taps a Daily resistance OCL and closes below it.*
2.  **Intermediate Confirmation (4H):** Drop to the 4H timeframe. Wait for an **Engulfing Candle (EG)** to form in the direction of the HTF bias.
    *   *Example: Following the Daily bearish rejection, look for a bearish engulfing candle on the 4H chart.*
3.  **LTF Entry Setup (15m or 30m):** Once the 4H Engulfing is established, drop to a Lower Timeframe (15m or 30m). Wait for price to pull back into the 4H engulfing zone. Inside this zone, look for:
    *   **Sweep of Liquidity:** Price sweeps a recent low/high.
    *   **Break of Structure (BOS):** Price breaks structure in the direction of the trade.
    *   *Alternative LTF Confirmation:* If Sweep/BOS is messy on the 15m, you can use a 1H Engulfing candle as your final entry trigger.
4.  **Execution:** Place a pending limit order or enter at market when price pulls back into the unmitigated zone (the LTF Order Block, OCL, or the Engulfing zone itself) after the LTF confirmation.
5.  **Stop Loss:** Placed just below the lowest point of the setup (for buys) or above the highest point (for sells). Do not place the SL tightly inside the zone; give it breathing room beyond the structural swing.

## 5. Liquidity and Premium/Discount Concepts

*   **Liquidity Focus:** The best entries occur when there is clear liquidity (e.g., relative equal highs/lows or a clear inducement trendline) sitting *before* the entry zone. When this liquidity is swept, the setup becomes high probability.
*   **Premium/Discount Tool:** Using a Fibonacci tool from Swing High to Swing Low to define Discount (below 50%) and Premium (above 50%) is valid but secondary.
*   **Mechanic:** If a setup has clear liquidity backing it, the bot does *not* necessarily need to wait for price to reach the deep Discount/Premium zone. However, if there is *no* obvious liquidity, expect a deeper pullback into the Premium/Discount zone (or into an OCL/Extreme zone) before the reversal happens.
