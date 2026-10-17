# Pilot checklist (rev 1, mistake-driven)
1. ✅ Confirm a clear break of structure (BOS/CHOCH) before entry.
2. ✅ Ensure a Quality Market (QM) level is present and respected on the next candle.
3. ✅ Place stop‑loss at least 0.5 ATR (or ≥0.2 pts on this instrument) away from entry.
4. ✅ Avoid entering inside the candle that generated the signal; wait for a confirming close beyond the entry level.
5. ✅ Require at least two independent confluence factors (e.g., BOS + liquidity sweep, or OB + FVG).
6. ✅ Verify that price does not close on the same bar in the opposite direction of the intended bias.

## Costly patterns
- **Tight stop near entry** (~0.0R): Stops placed <0.2 points (≈0.05 ATR) from entry caused the loss on setup 24; such tight stops are easily hit by normal volatility.
- **Entry inside bar without decisive break** (~0.0R): Entering when the price closes above (for bearish) or below (for bullish) the entry level on the same candle invalidates the bias and increases stop‑run risk.
- **Reliance on single confluence (e.g., FVG) without market‑structure confirmation** (~0.0R): Many losing or marginal setups used only a Fair‑Value Gap as the anchor; without a clear BOS/CHOCH or Quality Market (QM) level the trade lacked a strong directional premise.
- **Missing Quality Market (QM) anchor** (~0.0R): Setups where QM was NaN or absent (e.g., 14, 22) showed weak structural support and resulted in poor risk‑reward.

The only actual loss came from a bullish setup (ID 24) that satisfied many confluence criteria but failed because the stop was extremely tight and the entry was taken inside a bar that immediately moved against the trade. Across the 26 back‑tests, the AI flagged similar weaknesses (tight stops, missing QM, entry inside bar) in many setups that still hit TP, indicating these are high‑risk patterns that can erode profitability when market conditions tighten. Applying the checklist above should preserve the high‑R winners while filtering out the fragile trades that caused the loss.
