# Analysis of EMS#ENGULFING #MSNR#SMC.mp4

## Overview
This video discusses a trading strategy heavily reliant on Multi-Timeframe (MTF) analysis, liquidity sweeps, Points of Interest (POI), and specifically a setup referred to as "CRT" (which relies on V-shaped key levels and engulfing candles).

## Core Logic & Ambiguities to Code

### 1. Multi-Timeframe POI Selection
- **Logic:** The POI (Point of Interest) should always be selected from a Higher Time Frame (HTF), specifically one or two timeframes higher than the execution timeframe (e.g., if executing on 1H, check 4H or Daily for the POI).
- **Rule:** The target zone must **always** be the one closest to liquidity. For example, if there is a Break of Structure (BOS) or a Quasimodo (QMR) level, pick the key level that is nearest to the liquidity pool.
- **Bot Ambiguity Resolution:** 
  - The bot needs a strict definition of "liquidity". This is usually a recent swing high/swing low or a breaker block. 
  - The bot should scan HTF (e.g., H4, D1), identify key support/resistance levels, and prioritize the one with the smallest pip-distance to the nearest unmitigated swing point (liquidity).

### 2. The CRT Setup (V-Shape Key Level)
- **Logic:** This setup focuses on a "V-shape" key level rejection.
- **Pattern Recognition (3-Candle Formation):**
  1. **Touch Candle:** A candle that touches the key zone/level.
  2. **Indecision Candle:** A middle candle that represents indecision (often a Doji, spinning top, or small body candle). This candle creates a "Range High" and a "Range Low".
  3. **Confirmation/Entry Candle:** The third candle that sweeps the liquidity of the range.
- **Execution:** Once the third candle sweeps the range high (taking out upper liquidity) and closes back inside or below, a short entry is triggered, targeting the "Range Low" liquidity. (Inverse for long setups).
- **Bot Ambiguity Resolution:**
  - **V-Shape Key Level:** Can be defined algorithmically as an extreme fractal point (e.g., using iFractals) on a HTF.
  - **Indecision Candle:** Defined by the ratio of the body to the wicks. (e.g., Body size <= 30% of total candle range).
  - **Sweep & Close:** The third candle's High must be > Indecision Candle's High, but the Close must be < Indecision Candle's High (for a bearish setup).

### 3. Engulfing Candle Confirmations
- **Logic:** The strategy heavily uses Engulfing candles as an entry confirmation.
- **Rule:** If a setup (like the CRT) is not extremely clear, drop to a Lower Time Frame (LTF) (e.g., if POI is Daily, drop to 4H or 1H). Look for an Engulfing candle rejecting the HTF POI.
- **Execution:** Once the Engulfing candle closes, mark its open/close as a mini-zone. Wait for price to pull back and tap into this new mini-zone before executing the trade.
- **Bot Ambiguity Resolution:**
  - **Engulfing Definition:** Candle 2's body completely engulfs Candle 1's body.
  - **Retracement Entry:** Place a Limit order at the open of the engulfed candle (or the 50% fib level of the engulfing candle) rather than entering at market on close. This offers better Risk to Reward.

## Summary for Bot Implementation
1. **Identify HTF Liquidity & POI:** Scan D1/H4 for key levels nearest to swing highs/lows.
2. **Wait for Tap:** Wait for LTF (e.g., H1/M15) price to touch the HTF POI.
3. **Form the Setup:** 
   - Option A: Look for the 3-candle CRT setup (Touch -> Indecision -> Sweep & Close).
   - Option B: Look for a valid Engulfing candle.
4. **Execute & Target:** Set limit orders on the pullback (to the engulfing zone or range boundary). Target the opposite side of the local liquidity (e.g., the range low of the indecision candle).
