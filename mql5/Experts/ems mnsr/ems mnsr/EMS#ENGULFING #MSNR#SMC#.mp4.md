# EMS Engulfing MSNR SMC (Part 1)

This document summarizes the core logic extracted from the video `EMS#ENGULFING #MSNR#SMC#.mp4`.

## Basic Market Structure
The foundation of the trading strategy relies on identifying three basic market structures:
1. **Uptrend**: Characterized by higher highs and higher lows.
2. **Downtrend**: Characterized by lower highs and lower lows.
3. **Ranging/Consolidation**: Price moves sideways within a specific range, bouncing between a ceiling (resistance) and a floor (support).

### Liquidity
- **Definition**: In this context, liquidity represents money. Specifically, it refers to areas where retail traders place their stop losses (e.g., above highs or below lows).
- **Market Behavior**: The market (driven by large institutions) actively seeks to "sweep" or "grab" this liquidity.
- **Rule of Thumb**: Any sharp point or edge on the chart is a potential liquidity pool. The market will naturally gravitate towards these areas to trigger stop losses before continuing its intended direction.

## Advanced Market Structure
The strategy moves beyond basic trends to focus on:
1. **Swing Structure**
2. **Sub Structure**
3. **Minor Structure**

### Swing Structure & Break of Structure (BOS)
- **Swing Structure**: A swing structure is defined by the price movement that causes a Break of Structure (BOS). In an uptrend, it's the lowest point to the highest point of the move that breaks the previous high.
- **BOS (Break of Structure)**: When the price surpasses a previous structural high (in an uptrend) or low (in a downtrend).
- **Trading the Swing Structure**:
  - Once a BOS occurs, a new swing structure is formed.
  - Traders should *not* buy immediately after a BOS. Instead, wait for the price to retrace *back into* the swing structure (the zone between the low and the high that caused the break).
  - The entry (buy in an uptrend, sell in a downtrend) should be taken when the price returns to this swing zone, anticipating the next leg in the direction of the trend.
  - The previous structural points often act as transactional liquidity which the market will sweep before moving.

## Bot Coding Considerations (Visual Ambiguities)
When coding a bot based on this logic, consider the following ambiguities:
1. **Defining "Sharp Points" (Liquidity)**: The bot needs a mathematical way to define a "sharp edge" or "swing high/low". This is typically done using fractals or a rolling window to identify local maximums and minimums (e.g., a high that is higher than the 2 candles to its left and right).
2. **Break of Structure (BOS) Criteria**: Does a BOS require a candle *close* above the previous high, or is a *wick* sufficient? The bot must be explicitly programmed for one or the other. (Usually, a close is preferred for a true BOS, while a wick is considered a liquidity sweep).
3. **Swing Structure Zone Identification**: After a BOS, the bot must precisely record the lowest low of that upward push (for an uptrend) to define the lower boundary of the swing structure. The retracement entry logic will rely on price entering this defined zone.
4. **Ranging Markets vs. Trend Reversals**: The bot must have clear criteria (e.g., number of equal highs/lows or an indicator like ADX) to distinguish between a ranging market (where it should buy low/sell high) and the start of a new trend.
