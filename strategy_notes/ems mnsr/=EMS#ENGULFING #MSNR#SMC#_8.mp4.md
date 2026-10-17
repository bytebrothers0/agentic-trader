# EMS#ENGULFING #MSNR#SMC#_8.mp4 Strategy Extraction

## Core Strategy Logic
The video discusses a Smart Money Concept (SMC) and BBMA-based strategy applied across synthetic indices (Crash 1000, Boom 1000, Jump indices, Step Index, Volatility 75) and currency pairs (NZDJPY, USDCAD, EURUSD, EURGBP, EURJPY, NZDUSD).

### 1. Engulfing Candles & Multi-Timeframe Analysis
- **High Timeframe (HTF) Focus:** The strategy relies heavily on spotting **Engulfing candles** on higher timeframes (Weekly, Daily, H4).
- **Context is Key:** When an engulfing candle is spotted, the primary question to ask is: *"Where is price actually coming from?"* The price needs to be reacting from a clear, fresh Point of Interest (POI) or Support/Resistance (SNR) level.
- **Lower Timeframe (LTF) Refinement:** Once an HTF engulfing is identified, drop down 2 or 3 timeframes (e.g., from Daily to H4 or H1) to look for entry setups.
- **Engulfing Zone:** The entire body and wick of the engulfed candle are considered a zone.

### 2. Liquidity Sweeps and Break of Structure (BOS)
- **Setup Pattern:** The ideal entry setup involves:
  1. A **Liquidity Sweep** (price takes out a previous high or low).
  2. A **Break of Structure (BOS)** / Market Structure Shift in the opposite direction.
  3. A pullback into a fresh POI / open-close level for an entry.
- **Open-Close Levels:** The speaker frequently uses specific "open-close" levels of candles as entry points after a liquidity sweep.

### 3. BBMA (Bollinger Bands Moving Average) Settings
The video explicitly shares the BBMA indicator settings used for confirming directional momentum:
- **Bollinger Bands:** Period = 20, Deviation = 2.0, Shift = 0, Apply = Close
- **MA 50:** Period = 50, Method = Exponential, Shift = 0, Apply = Close
- **MA 5 LOW:** Period = 5, Method = Linear Weighted, Shift = 0, Apply = Low
- **MA 5 HIGH:** Period = 5, Method = Linear Weighted, Shift = 0, Apply = High
- **MA 10 LOW:** Period = 10, Method = Linear Weighted, Shift = 0, Apply = Low
- **MA 10 HIGH:** Period = 10, Method = Linear Weighted, Shift = 0, Apply = High

### 4. Directional Candlesticks
- The speaker looks for a "directional candlestick" on the BBMA to confirm momentum before taking a reentry on a pullback.

### 5. Visual Ambiguities for Bot Development
- **"Freshness" of POI:** The bot needs a way to determine if an SNR or POI level is "fresh" (unmitigated). This requires tracking historical touches of a price zone.
- **Identifying "Sweeps":** A sweep is often a wick that goes beyond a previous structural point and closes back within the range. The bot must distinguish between a body close (BOS) and a wick rejection (Sweep).
- **Engulfing Zone Definition:** The bot should map the High and Low of the *engulfed* candle as the bounds of the POI for the lower timeframe pullback.
- **BBMA Confirmation:** The bot logic must check if the current price action aligns with the MA 5/10 and Bollinger Band conditions (e.g., price breaking out of the MA 5/10 high/low channel).
