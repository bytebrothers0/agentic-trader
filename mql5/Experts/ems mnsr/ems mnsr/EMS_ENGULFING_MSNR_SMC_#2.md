# Video Analysis: EMS#ENGULFING #MSNR#SMC#_2.mp4

## Core Concept: Confirmation Entries via Engulfing Candles
This video focuses on how to execute "confirmation entries" after the price has reached a Higher Timeframe (HTF) Point of Interest (POI) or key level. The strategy heavily relies on identifying engulfing candles and Open/Close Levels (OCL) on multiple timeframes to confirm trend direction and validate entry zones.

## Visual Ambiguities & Definitions for Bot Coding

### 1. HTF Trend and Key Levels
- **Trend Identification**: The bot first needs to determine the overall trend on a higher timeframe (e.g., Daily or H4).
- **Key Levels (OCL and QMR)**: The bot must mark out recent key levels. These include Open/Close Levels (OCL) where significant price rejection occurred, and Quasimodo (QMR) levels.
- **Coding Implication**: The bot needs to scan the HTF for recent swing highs/lows and significant engulfing candles to mark as POIs. 

### 2. Lower Timeframe (LTF) Confirmation
- Once price taps into the HTF POI, the bot must drop down to a lower timeframe (e.g., H1, M30, or M15) to look for confirmation.
- **Confirmation Setup**: Confirmation is defined as a Break of Structure (BOS) or Change of Character (CHoCH) in the direction of the anticipated trade.
- **Engulfing Candle Identification**: After the BOS/CHoCH on the LTF, the bot must identify the engulfing candle that initiated the break.

### 3. Entry and Stop Loss
- **Entry**: The entry is typically set as a limit order at the 50% retracement level of the LTF engulfing candle or at the newly formed LTF key level (OCL/QMR).
- **Stop Loss**: The stop loss is placed strictly above the high (for a sell) or below the low (for a buy) of the engulfing candle zone to invalidate the setup if broken.
- **Coding Implication**: 
  - `EntryPrice = EngulfingCandle.Low + (EngulfingCandle.High - EngulfingCandle.Low) * 0.5` (for a buy, adjust based on the specific zone marked).
  - State machine required: `State 1: Wait for HTF POI Tap` -> `State 2: Wait for LTF BOS/CHoCH` -> `State 3: Identify LTF Engulfing Zone` -> `State 4: Set Limit Order at 50% Retracement`.

## The Trading "Storyline" (Workflow)
1. **Analyze HTF (Daily/H4)**: Identify the trend. Mark recent key levels (OCL, QMR, Engulfing zones).
2. **Wait for Tap**: Wait for the current price to tap into the marked HTF key level.
3. **Confirm on LTF (H1/M15)**: Drop to a lower timeframe. Wait for a clear Break of Structure (BOS) indicating a reversal from the HTF key level.
4. **Identify Entry Zone**: Find the engulfing candle on the LTF that caused the BOS.
5. **Execute**: Place a limit order at the 50% mark of the LTF engulfing candle with the stop loss safely outside the zone. Target the next major liquidity pool for take profit.
