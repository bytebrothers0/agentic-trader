
## QM module probe — Task 15, 2026-11-14 — RESULT: FAILED hold-out gate, not merged

Source rules: part03 QM family, part04 QM quality gate (BOS body ≥0.8×ATR, hesitation), video_3 ftQM/stQM, video_1 failed-flip = QM.

Scout implementation (`qm_module` flag, OFF = exact baseline regression — verified bit-identical on both windows):
- QM spawns when a tested level breaks (body close through + break_buf), playing the flipped role; quality gate breakout body ≥ qm_bos_atr × ATR (0.8); ftQM full size / stQM 0.7×; QM grade bonus +1.

Results (Model=4-equivalent M5 replay, risk% sizing, grade_min=3.0):

| Run | Trades | WR | Net R | Source |
|---|---|---|---|---|
| baseline (qm off) IS | 26 | 46.2% | +11.14 | wu12 baseline |
| QM IS | ~105 | ~43% | +20 | H4/QM = 79 trades |
| baseline (qm off) HO | 6 | 66.7% | +8.88 | wu12 baseline |
| QM HO | ~24 | ~30% | −6 | H4/QM = 18 trades, **−8.2R, 17% WR** |

Verdict: **QM fails the two-window hold-out gate** (HO deeply negative, 17% WR). Not merged into the EA. Honest note: the mechanization spawns QM on a tested level's first break rather than the doctrinal "flipped level breaks again" (second break), which is hard to capture without cross-rebuild state; regardless, the hold-out result is decisively negative. Documented as a failed probe — not added "because I was told to."
