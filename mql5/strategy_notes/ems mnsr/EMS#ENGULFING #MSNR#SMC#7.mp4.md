# EMS#ENGULFING #MSNR#SMC#_7

## Core Strategy Logic

This video explains a top-down approach utilizing Smart Money Concepts (SMC) combined with Engulfing candle confirmations (EMS/MSNR). The strategy relies on identifying POIs (Points of Interest) on higher timeframes (HTF) and waiting for lower timeframe (LTF) engulfing confirmations to execute trades.

### Step-by-Step Breakdown:
1. **HTF Market Direction & Structure**:
   - Identify the current trend (e.g., bearish or bullish) on the Daily or H4 timeframe.
   - Look for a **Break of Structure (BOS)** where the body of a candle closes below a previous significant low (for bearish) or above a high (for bullish).
   - Identify a **Liquidity Sweep**: Price wicks above a previous high or below a previous low but the body closes back inside the range. This forms "Type 2 Liquidity".

2. **Defining the POI (Point of Interest)**:
   - Identify the key candle that initiated the move or sweep.
   - Draw the POI zone covering the highest point of the wick (shadow) to the lowest point of the wick of that specific candle.
   - Specifically look for "Open Close" (OCL) levels or Engulfing candles that failed (failed engulfing zones).

3. **Refining and Entry Confirmation (LTF)**:
   - Drop down to a lower timeframe (e.g., H1, M30, M15, or M5).
   - Wait for the price to return and **tap into the HTF POI**.
   - **Crucial Trigger**: Once inside the POI, wait for a new **Engulfing Candle** to form in the direction of your HTF bias.
   - **Entry**: Enter the trade on the close of the LTF engulfing candle, or wait for a small pullback into the engulfed zone.

4. **Stop Loss (SL) and Take Profit (TP)**:
   - **SL Placement**: Placed above the high of the LTF engulfing candle or slightly above the entire HTF POI zone for safety.
   - **TP Placement**: Target **External Range Liquidity (ERL)**. Price moves from Internal Range Liquidity (IRL) to ERL. Your target is the most recent major swing low (in a downtrend) or swing high (in an uptrend).

---

## Visual Ambiguities for Bot Coding

To code this bot accurately, several visual elements need strict mathematical definitions:

1. **Defining the "Sweep" vs. "BOS"**:
   - **BOS**: `Close[1] < Low[Swing]` (Bearish) or `Close[1] > High[Swing]` (Bullish). The body must close beyond the level.
   - **Sweep**: `High[1] > High[Swing]` but `Close[1] < High[Swing]` (Bearish sweep). The wick pierces the level, but the body closes inside.

2. **Engulfing Candle Definition**:
   - The bot needs strict parameters for an "Engulfing" pattern.
   - Bearish Engulfing: `Close[1] < Open[2]` AND `Open[1] >= Close[2]`. Does it need to engulf the wick too? The video implies standard body engulfment is sufficient for confirmation, but a stronger signal engulfs the wick.
   
3. **Drawing the POI Zone ("Shadow to Shadow")**:
   - The bot must calculate the POI using the `High` and `Low` of the specific reference candle (the one causing the sweep or the failed engulfing).
   - Variables: `Zone_High = High[Reference_Candle]`, `Zone_Low = Low[Reference_Candle]`.

4. **Failed Engulfing Zones**:
   - The video mentions using a "failed engulfing" as a POI. The bot must track engulfing setups that hit their SL. The zone of that failed engulfing becomes a strong support/resistance level for future price taps.

5. **Internal vs. External Range Liquidity**:
   - **Range Definition**: Defined by the most recent major Swing High and Swing Low.
   - **IRL**: Any minor swings *inside* the High/Low range.
   - **ERL**: The boundaries (the Swing High and Swing Low themselves).
   - **Logic**: If price taps a POI at the top of the range (IRL), the bot must set the TP at the exact price of the Swing Low (ERL).

6. **Multiple Timeframe Alignment (MTF)**:
   - The bot must run virtual HTF checks (e.g., using `iClose`, `iHigh` on `PERIOD_D1` or `PERIOD_H4`) while executing on `PERIOD_M15` or `PERIOD_H1`.
   - The "Tap" is defined as `High[0] >= POI_Low` (for a bearish POI). The bot must then switch to a monitoring state waiting for the `Close[0]` of the engulfing candle.
