# EMS Engulfing Strategy & Engulfing Fail (EF) for Bias

This document extracts the trading logic and visual ambiguities explained in the video "full strategy for EMS with breakdown of how to use EG and EF for bias part 2#Engulfing #smctrading.mp4".

## Core Concepts Explained

### 1. Marking Engulfing (EG) Zones
- **Visual Rule:** When marking an engulfing candle zone, you generally cover the entire engulfing candle (from high wick to low wick). 
- **Ambiguity Resolution:** If the wick of the *engulfed* candle is longer than the engulfing candle's wick, you should ideally cover the longer wick as well. However, the instructor often prefers marking just the engulfing candle's body and wicks for a tighter Point of Interest (POI), as long as it's within a valid Break of Structure (BOS) zone.

### 2. The "Engulfing Fail" (EF) Concept
- **Definition:** An Engulfing Fail occurs when a valid engulfing setup fails to hold the price. For example, a bullish engulfing candle is formed, but price subsequently closes *below* the low of this bullish engulfing zone.
- **Trading Logic:** Once an engulfing zone fails, that exact zone flips into a POI for the opposite direction. A failed bullish engulfing becomes a bearish POI (resistance), and a failed bearish engulfing becomes a bullish POI (support).
- **Bot Implementation:** The bot needs to track valid engulfing zones. If price closes beyond the invalidation level of an active engulfing zone, the bot should immediately mark that zone as an "Engulfing Fail" and monitor it for a retest in the opposite direction.

### 3. Multi-Timeframe (MTF) Alignment
- **Top-Down Approach:** The strategy relies heavily on MTF alignment. The overall bias is determined on a Higher Timeframe (HTF) like the Daily or H4 chart.
- **POI Identification:** POIs (Engulfing or Engulfing Fails) are identified on the HTF.
- **Entry Confirmation:** Once price taps into the HTF POI, you drop to a Lower Timeframe (LTF) like H1 or m15. You do NOT enter blindly. You must wait for an LTF confirmation, which consists of:
  1. A sweep of LTF liquidity.
  2. A Break of Structure (BOS) or Change of Character (CHoCH).
  3. A new LTF Engulfing candle forming as the entry trigger.

### 4. Liquidity Sweeps
- **Requirement:** Before taking any trade from a POI, there must be a clear sweep of liquidity.
- **Visual cues:** Look for equal highs/lows, or a "V-shape" swing point just before the POI. Price must sweep this liquidity (take out the high/low) before reversing. If a POI is reached but no clear liquidity was swept beforehand, the POI is lower probability.

### 5. The "Third Candle" Entry Rule
- **Standard Expectation:** After an engulfing candle forms (Candle 1 is engulfed, Candle 2 is the engulfing), Candle 3 is typically expected to pull back into the engulfing zone to provide the entry.
- **Exception:** The instructor clarifies that while the 3rd candle often provides the entry, it's not a strict rule. If the momentum is strong, price might take 4, 5, or more candles to return to the zone.
- **Bot Implementation:** The bot should not invalidate an engulfing zone just because the immediate next candle didn't retest it. The zone remains valid as long as the structural rules (BOS, Liquidity) are intact.

## Step-by-Step Execution Logic for the Bot

1. **Scan HTF (e.g., Daily/H4):** Identify the directional bias by mapping recent Break of Structures (BOS) and identifying active Engulfing (EG) or Engulfing Fail (EF) zones.
2. **Mark POI:** Draw the zone based on the full EG/EF candle.
3. **Wait for Price Action:** Wait for price to enter the HTF POI.
4. **Scan LTF (e.g., H1):** Once in the POI, monitor the LTF for a structural shift.
5. **Confirm Liquidity Sweep:** Ensure the LTF structural shift swept recent liquidity.
6. **Identify LTF Trigger:** Wait for a clear LTF Engulfing candle in the direction of the HTF bias.
7. **Place Order:** Set a limit order at the open/50% of the LTF Engulfing zone, with a Stop Loss just beyond the sweep/engulfing candle wick.
8. **Invalidation:** If a candle closes beyond the POI zone, invalidate the setup. If it's an EG zone that gets broken, immediately convert it to an EF zone for potential reverse trades.
