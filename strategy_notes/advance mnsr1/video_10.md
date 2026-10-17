# Advanced MSNR Video 10: Top-Down Analysis

This video demonstrates the complete top-down analysis workflow in the MSNR strategy, applying all the concepts from previous videos (Storyline, FTFL, STFL, TTFL, and Equilibrium) into a cohesive routine.

## 1. The Routine
Top-down analysis is not done on every timeframe every single day. There is a specific schedule:
- **Monthly Analysis**: Done once at the beginning of the new month.
- **Weekly Analysis**: Done once at the beginning of the week (usually over the weekend, Saturday or Sunday).
- **Daily Analysis**: Done every single day to catch intraday continuation and confirmation entries.

## 2. Determining the Overall Storyline
You must write down the Storyline for each major timeframe:
- **Monthly**: Bullish or Bearish?
- **Weekly**: Bullish or Bearish?
- **Daily**: Bullish or Bearish?

*Example*: If Monthly is Bearish, Weekly is Bullish, and Daily is Bullish, you have conflicting timelines, but your immediate trading bias for the week will follow the Weekly/Daily alignment (looking for buys) until it reaches a Monthly resistance.

## 3. Top-Down Refinement Workflow
If your analysis determines a Bullish bias, you are looking for Buys. You follow the timeframes down to refine the entry:

1. **FTFL (First Time Frame Level)**: 
   - Identify the primary Key Level (Support, Resistance, QM, or OCL) on the Weekly or Daily chart.
   - Example: If using a Weekly Support, draw a box around the body and wick of that support.
2. **STFL (Second Time Frame Level)**:
   - Drop down one timeframe. If FTFL is Weekly, go to Daily. If FTFL is Daily, go to 4H.
   - Look for a fresh Support or QM *inside* the FTFL box. Draw a new, smaller box.
3. **TTFL (Third Time Frame Level)**:
   - Drop down again. If STFL is Daily, go to 4H. If STFL is 4H, go to 1H.
   - Look for a fresh Support or QM *inside* the STFL box.
   - **Equilibrium**: If the TTFL box still has a very long wick and you want an even tighter stop loss, you use the 50% midpoint (Equilibrium) of the TTFL wick as your precise entry point.


new note: to when drawing the box for the tfl zones, 
scenrio 1 : support or ressistance or qmr level; since two candles makes this key level lets ay candle 1 and candle2, the box should cover both candle1 and candle2 wicks (it should use the highest wicks as the hieght of the boz)and extend it to one step to the right thus as if to cover the next candle's wick as if it was the box was covering candle1,candle2 and candle3 wick
this logic applies to marking all fls zone, from ftfl, ttfl and stfl

scerrio 2: for ocls, candle1 and candle2 forms and ocl, so when marking or drawing a box arround the candle2's wick, the box should also cover and use the full wicks hieght for the box zone and extend it one step to both left and right, thus to cover candle1,candle2 and candle3, this logic applies to marking all fls zone, from ftfl, ttfl and stfl
what was meant was that , candle1 and candle2 forms the ocl, inside that ocl level, there are two wicks, thuse the wick high of candle1 and wick low of candle2 thats for bullish, and bearish the wick low of candle1 and wick high of candle2, the zone marking is only to mark the wick of candle2 and extend 1 step to both left and right and should not include the wicks of candle 1,
scenrio for buys, it makrs the hight of candle2 lower wick and extend one step to the left and one step to right covering part of candle1 body, candle2 wich, and empty space or candle3 or idx3 or something if you get what i mean and vice versa for sells just like in the image , so please correct it
 therefore with this correction, this should extend the bots entry range inside that box and not just within the wicks but the new range



## 4. Accounting for Broker Spread
A critical practical tip shared in this video:
- Brokers have spreads (the difference between bid and ask price), which can prevent your trade from triggering if you place your entry exactly on the line.
- **The Spread Buffer**: Always add a buffer to your entry and stop loss. The instructor recommends adding **extra pips** (e.g., 0.5 to 1 full pip, or 5 to 10 points) above your buy entry line to ensure you get tagged in.
- Similarly, extend your Stop Loss slightly beyond the invalidation level to prevent getting "spread out" of a valid trade by a fraction of a pip.
