# MSNR Trading Strategy - Part 5: Retracements and Entry Triggers

## 1. The Anatomy of the Pullback

Once the bot has successfully identified the sequence: **Trend (BOS) -> Target Sweep (TS) -> Market Structure Shift (MSS)**, the trap has been set. The final phase is waiting for price to retrace back up into a premium area to execute a short trade (or vice-versa for longs).

The PDF states: "After the chart makes a Market Structure Shift (MSS), wait for it to retrace upward and sweep liquidity. A strong entry point is often supported by liquidity just before reaching the target zone."

### 1.1 Why We Wait for the Pullback

Entering immediately upon the MSS is aggressive and often results in poor Risk-to-Reward. Smart money algorithms are designed to push price back into the "origin" of the move that caused the MSS to mitigate (close at break-even) losing positions they accumulated during the Target Sweep phase.

**Bot Logic for Pullback Detection:**
1.  **Define the Range:** After the MSS is confirmed, the bot must define the current trading range. The high is the TS point, and the low is the lowest point reached after the MSS break.
2.  **Premium/Discount Zones:** The bot should calculate the Fibonacci retracement levels of this range. Typically, entry zones are located above the 50% mark (Premium pricing for a short). The bot should ignore entry signals that occur below the 50% equilibrium level.
3.  **Identify the Point of Interest (POI):** Within the Premium zone, the bot scans for specific POIs. In the MSNR strategy, these are often Order Blocks (the last bullish candle before the strong bearish MSS move) or Fair Value Gaps (imbalances).

## 2. Entry Triggers: Resistance and Doji

The MSNR strategy is highly specific about its entry triggers. It doesn't just blindly place limit orders at a POI; it looks for specific candlestick confirmations.

The PDF highlights: "The second entry point is at a resistance level combined with a Doji... The presence of a Doji makes this entry especially strong."

### 2.1 Defining "Resistance" for the Bot

"Resistance" in this context is usually the area around the Target Sweep or a prominent structural high formed just before the MSS.
**Bot Implementation:**
- The bot must store the precise price levels of the TS and other minor swing highs formed during the consolidation before the drop.
- These levels become the `ResistanceZone`.

### 2.2 The Power of the Doji Candle

A Doji represents indecision. When a Doji forms exactly at a predefined Resistance Zone after a strong pullback, it signifies that the bullish retracement momentum has suddenly evaporated right where sellers are waiting.

**Coding the Doji Detection:**
This is where visual ambiguity must be translated into strict mathematical ratios.
1.  **Doji Anatomy:** A Doji has an open and close that are very close together, with long upper and lower wicks.
2.  **Mathematical Definition for the Bot:**
    - Calculate Total Candle Size (High - Low).
    - Calculate Candle Body Size (MathAbs(Open - Close)).
    - Define a `DojiRatio` threshold. For example, if Body Size is less than 15% of Total Candle Size, classify it as a Doji.
    - `if (BodySize / TotalSize) < 0.15 => isDoji = true`.
3.  **Context is Everything:** The bot must not trade every Doji. The condition is: `if (Price in PremiumZone AND Price at ResistanceLevel AND isDoji == true) -> Trigger Entry Sequence`.

## 3. The "Liquidity Before the Zone" Concept

A crucial nuance in the PDF is: "A strong entry point is often supported by liquidity just before reaching the target zone."

This means the setup is much higher probability if, during the pullback, price creates minor resistance levels (inducement/liquidity) *below* the main entry POI, and then sweeps them just before hitting the actual entry Doji.

**Bot Logic for Inducement Detection:**
1.  As price retraces upwards, the bot tracks minor swing highs.
2.  If it detects a minor swing high forming *below* the main Resistance/Doji POI, it marks this as `Pre_Zone_Liquidity`.
3.  The optimal entry sequence is triggered when price spikes through `Pre_Zone_Liquidity` (triggering early sellers' stops) and immediately taps the main Resistance/Doji POI.

## 4. Execution and Risk Management (The 10 Pip SL)

The MSNR strategy aims for incredibly tight stop losses, often around 10 pips, as indicated by the PDF title. This requires extreme precision.

**Bot Execution Logic:**
- **Entry Type:** When the Doji condition is met at the Resistance level, the bot can execute a Market Order immediately upon the Doji candle close. Alternatively, it can place a Sell Stop order just below the low of the Doji candle for extra confirmation.
- **Stop Loss Placement:** The Stop Loss must be placed strictly above the high of the TS (Target Sweep) or slightly above the wick of the entry Doji, plus a small buffer for spread.
- If the bot detects the setup but the distance from the entry price to the required Stop Loss level is greater than the allowed maximum (e.g., > 15 pips), the bot *must skip* the trade. The RR ratio relies entirely on these tight stops.

In summary, Part 5 requires programming the bot to be patient. It must wait for the price to return to the scene of the crime (the Premium zone), hunt for a specific pattern (the Doji at Resistance), and verify that preliminary liquidity was swept before pulling the trigger with strict risk parameters.
