# Video Analysis: EMS.mp4

## Core Concept: EMS (Engulfing MSNR SMC)
The EMS strategy is a hybrid trading approach that combines Malaysian Support and Resistance (MSNR) with Smart Money Concepts (SMC) and Candle Range Theory (CRT).

## Visual Ambiguities & Definitions for Bot Coding

### 1. Key Levels (A-Shape and V-Shape)
- **A-Shape (Resistance)**: A peak structure visible clearly on a line chart, representing a swing high.
- **V-Shape (Support)**: A trough structure visible on a line chart, representing a swing low.
- **Coding Implication**: The bot needs a fractal or swing point detection algorithm. An A-shape is formed when a candle's high is higher than the `N` candles to its left and right. 

### 2. Engulfing Candles & Momentum
- An engulfing candle is defined as a candle that completely eclipses the body of the preceding candle. The speaker emphasizes that engulfing candles dictate momentum.
- **Coding Implication**: 
  - Bullish Engulfing: `Close[1] > Open[2]` AND `Open[1] < Close[2]`.
  - Bearish Engulfing: `Close[1] < Open[2]` AND `Open[1] > Close[2]`.
  - Additional confirmation: The trend bias is also read by counting the ratio and length of white (bullish) vs black (bearish) candles over a recent period.

### 3. CRT (Candle Range Theory)
- A range is defined by the high and low of a specific reference candle's wicks.
- **Internal vs External Range Liquidity**: The wicks of the candle represent the external range. If price sweeps one side of the range (takes out liquidity) but fails to close outside it, and subsequently breaks and *closes* beyond the opposite side of the range, it confirms the direction.
- **Coding Implication**: The bot must track the High and Low of a target reference candle. A "sweep" is registered if `High[i] > RangeHigh` but `Close[i] < RangeHigh`. A "break" is registered if `Close[i] < RangeLow`. 

### 4. SMC Setup (Entry Confirmation)
The standard SMC entry model requires a sequence of four events:
1. **Sweep of Liquidity**: Price breaks above equal highs or a key structural point but does not close above it (wick rejection).
2. **Break of Structure (BOS)**: Price reverses and breaks the opposite swing point, closing beyond it.
3. **Internal Liquidity Creation**: Price consolidates or pulls back slightly, creating a trap.
4. **QMR / Order Block Mitigation**: Price returns to the origin of the move (the Quasimodo level or unmitigated order block) to trigger the entry.
- **Coding Implication**: 
  - The bot must map local swing highs/lows.
  - State machine required: `State 1: Wait for Sweep` -> `State 2: Wait for BOS` -> `State 3: Set Limit Order at QMR`.

## The Trading "Storyline" (Workflow)
1. **Determine Bias (HTF - Daily or Weekly)**: Look for an Engulfing candle that rejects a clear A-Shape or V-Shape key level. 
2. **Refine Zone (MTF - H4 or Daily)**: Drop down one timeframe. Find the exact open/close levels, or RBS (Resistance Becomes Support) / SBR (Support Becomes Resistance) zones.
3. **Execute (LTF - H1 or M15)**: Wait for price to tap the refined zone. Wait for the SMC Setup (Sweep -> BOS -> Pullback to QMR) to execute the trade. Target the next major external liquidity pool (previous HTF high/low) as Take Profit.
