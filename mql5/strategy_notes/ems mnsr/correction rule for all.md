this md file contains some corrections which need to be made on the other md files
on some of the entry models

Engulfing Fail (EG Fail) Setup

* **correct Identification:** Mark the candle that was engulfed(sometimes the body somethings include the wicks as well). Expect the price to pull back to this zone and reverse.
* **wrong identification :**  markinging an engulfing candle zone, you generally cover the entire engulfing candle (from high wick to low wick).

**TIIMEFRAME POI FOR BIAS AND ENTRy**:
timeframes for bot implementation and internal calulations to be used is :15m,H1,H4,D and Weekly
look for engulfing zones and markout the engulfled candle on the Weekly , Daily and H4
example candle1 was engulfed buy candle2, the zone or bot should be drawn from candle 1 and cover 3steps to the right, this the box should cover candle1 , candle 2 and the free space on the third step where the next candle would pull back into for an entry
drop two timeframes lower to find you smc setups thus, if zone was marked on Weekly, drop to H4, if daily,drop to H1 and if H4, drop to m15 for you smc setup, and in that LTF, if bullish or bearish, on that leg, find the liquidity and that liquidity(which is basically the low of a pullback in bullush or bearish leg) should inside the marked zone or box, incase there are no liquidy inside that box, then it can look for some above or below the box depending on the bias leg
after that liquidity has been marked, drop to your one timeframe higher, this if 15m, go to H1, if H1 go to H4, if H4 go to daily and so on
next is to find the closest key level above or below that liquidity based on the bias either bearish or bullish on that one time frame higher(thus below the liquidity when looking for buys and above the liquidity looking for sells) , its could be an ocl, qmr, snr,rbs,sbr and so on(and note that, these key levels must be in the zone marked box, all key levels outside the marked zone box must bot be used for an entry on the one time frame higher), if two or more entry key level are on the one timeframe higher  are closely packed to each other inside the marked box, we only use the key level closer to the liquidity as an entry level based on the bias(thus when looking for sells, we take the one timeframe higher key level that is above the liquidity but the closest to it, and for buys we look for one timeframe higher keylevel that is below the liquidity but closest to it,make sure that all those entry key level are coming from the marked zone box ),
**Engulfing Zone Wick Exception Rule:**
when marking the zone on the engulfed candle (candle1), check the total wick range of candle1 vs the total wick range of candle2 (the engulfing candle).

* If candle1's wick range (high - low) is LONGER than candle2's wick range or candle2's  egulfing body close (thus if bullish, if candle1 wick high is longer than candle 2 wick or body close, and if bearish, thus if candle1 wick low is longer that than candle2 wick body close or lower wick)
In this case, do NOT use candle1's full wicks for the box height. Instead, clamp the zone to candle1's BODY + its upper or lower wicks based on the bias (thus, include the lowerwicks when looking for buys and upper wicks when looking for sells, but the overall box hieght should be the highest wick height either candle 1 or 2 based on the bias as well), else mark the whole of candle1 including its wicks high and low as the zone if and only if candle1 bias wick is not longer than candle2 body as said earlier
* This prevents the box from being inflated by outlier wicks that are not representative of the true zone.
* The 3-4step extension and candle2/candle3 wick inclusion still applies as normal.
also one more thing, for when makring the zone , each candle has two wicks, upper and lower wicks, so the main candle in context thus the egulfed candle or candle1, for buys, when its upper wicks is too long or longer than the egulfing or candle2 wick, the zone should stick to the candles body+its lower wick, and for sells, the zone should stick to its body+upper wick
strict rule :also note that, correct EG zones must be formed by candles of the opposite colours

