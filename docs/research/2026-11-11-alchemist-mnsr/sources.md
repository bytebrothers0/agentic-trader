# Research Log — Alchemist MSNR Strategy (2026-11-11, night 2)

Fresh research per the operator's instruction: **no reference to the local
`alchemy_mnsr.md` or its git history** — everything below comes from the open
web, graded A–D, with the unverified discarded.

## Identity resolution

- **MSNR = Malaysian Support & Resistance** (NOT "midnight session range" —
  several YouTube channels conflate the two; the Alchemist course ecosystem
  consistently means Malaysian SNR). Body-based S/R zones drawn from candle
  open/close clusters, judged fresh vs unfresh, with a storyline and rejection
  evidence before entry.
- **The "Alchemist"** is the educator brand (course: "Master The Alchemist
  Trading Strategy {MSNR Full Course}"; TikTok @alchemistsnr0, @tx.alchemist;
  YouTube "Alchemist snr (full course)" playlist) selling a **MSNR × SMC × ICT
  × CRT** blend focused on **XAUUSD**.
- **Disambiguation (important):** `FxAlchemist` / the-algorithmic-trader.com is
  an UNRELATED bot vendor — flagged by the FCA as unauthorised, with user-loss
  reports. Excluded entirely.

## Sources

- [S1] MSNR Trading Strategy: Rules, Workflow and Risk | hoclamtrader.com | 2026 | C
  Workflow: HTF context → mark only obvious zones (areas, not lines) → current
  structure → wait for price at zone → read the reaction → plan (entry,
  invalidation, stop, target) → journal. Anti-patterns named: too many levels,
  entering on touch without reaction, ignoring HTF, random stops, treating
  zones as signals. Access: full.
- [S2] MSNR Terminology: SNR, Fresh Level, Storyline, Rejection, Confluence | hoclamtrader.com | 2026 | C
  Definitions: fresh = untested since creation (order-consumption logic);
  storyline = the narrative that makes a level matter NOW; rejection =
  failed continuation at the zone (wick, close-away, failed break, minor
  structure shift); confluence = independent reasons, never decoration.
  Access: full.
- [S3] MSNR Close and Open Levels | hoclamtrader.com | 2026 | C
  Malaysian-SNR drawing convention: zones anchored to candle **bodies**
  (open/close clusters = acceptance), wicks as tolerance/invalidation
  context, close-based evidence before acting. Bodies show acceptance; wicks
  show attempted rejection. Access: full.
- [S4] Alchemist Trading Framework: Storyline, POI, Trigger, Invalidation | hoclamtrader.com | 2026 | C
  The four-stage decision loop: STORYLINE (what is price doing, one factual
  sentence) → POI (bounded area with a reason and HTF relationship) → TRIGGER
  (observable event: reclaim, rejection, close, structure break) →
  INVALIDATION (what proves it wrong). Conditional if/then branches (bullish
  branch, bearish branch, no-trade condition), written BEFORE price arrives.
  "No trade" is a valid outcome. Editorial reconstruction — the author
  explicitly notes no authoritative standard exists for the label.
- [S5] MSNR x SMC x ICT — the Alchemist (Yanu Emmanuel) | scribd 863955768 | B (primary course doc, partially accessible)
  Confirms the blend and the pillars: candlestick + line charts, SNR levels,
  storyline importance, SMC/ICT integration. Full text behind Scribd paywall —
  **blocked**; only abstract-level claims verified.
- [S6] Alchemist MSNR | scribd 846189119 / es 846189042 | D-access (blocked)
  Multi-timeframe storylines, confirmations before entries, risk per
  timeframe, gold scalping. **Blocked** — snippets only.
- [S7] Alchemist SNR Trading Checklist | scribd 902459650 | D-access (blocked)
- [S8] Candle Range Theory (CRT) | fxnx.com + grandalgo.com + strefatradingu.pl + innercircletrader.net + tradingfinder.com | C (five independent explainers agree)
  Canon: an HTF candle (H1/H4/D1) IS a dealing range; the next candle sweeps
  (purges) one extreme for liquidity and CLOSES BACK INSIDE → mean-reversion
  toward the opposing boundary. "Trade the reversal, not the sweep." Cleaner
  when the sweep interacts with an HTF level / session level / FVG. Parent →
  Purge → Delivery. Maps 1:1 onto this system's `crt` detector.
- [S9] MSNR/ICT XAUUSD recaps + "AOX Entry Model" | YouTube ecosystem (dPlIsJ-YYKU, S7hpQriWyZ0, XlC2Wk90E6U, HqF2-Cu79mo, ZrNy9ZzUSUs, I-9ZJ1bINdU) | C
  Top-down: daily bias → 4H refinement → 30m/1H confirmation; mark broken key
  levels, FVGs, CRT zones; require structure change before entry; gold focus.
  Video bodies not accessible via text fetch — descriptions + DDG snippets only.
- [S10] ICT Midnight Opening Range content (scSh-pgDvZE, edgeful.com, MQL5 midnight range) | C
  Kept SEPARATE: genuinely a different concept family (session ranges).
  Relevant to this system via time-sessions.md but NOT part of the MSNR
  strategy core. edgeful.com reports data-backed probabilities for midnight
  open retracement per market — cited as supporting statistics, not doctrine.

## Published trade history — BLOCKED, honestly

- The MSNR/Alchemist-SNR educator has **no verified public track record**
  found: no Myfxbook/TradingView-verified account attributable to this brand;
  the TikTok bios funnel to VIP signal groups via WhatsApp (a classic
  unverified-claims pattern, noted as a red flag by the operator's own
  warning "not all sources are legit").
- Myfxbook's "THEALCHEMIST" profile exists but cannot be attributed to this
  educator with the evidence available → discarded rather than assumed.
- **Consequence for the backtest:** the ≥70% score is measured as **outcome
  agreement** (operator-confirmed metric) — replay historical XAUUSD windows
  through the agent wearing the strategy, score its directional calls against
  the realized win/loss of the market itself (a win is a win, a loss is a
  loss), NOT against a published ledger that does not exist. Documented as a
  design deviation with the reason.

## Where sources disagree / cautions

- hoclamtrader.com is a content-farm cluster (affiliate-monetised); its
  articles are editorial reconstructions of community concepts — used for
  structure and terminology, graded C, never as authority on profitability.
- "Alchemist" label has no authoritative standard (S4 says so explicitly).
- MSNR vs midnight-range conflation in YouTube titles — resolved above.
- CRT probability claims (e.g. "80%") are per-market, per-config marketing
  statistics — recorded as unverified; the replay backtest is our own
  measurement.

## Confidence

- High: MSNR body-zone drawing convention, fresh/unfresh doctrine, storyline
  → POI → trigger → invalidation loop, CRT sweep-and-reclaim mechanics.
- Medium: exact entry-model catalogue of the paid course (paywalled); gold
  scalping specifics.
- Low: any profitability claim by any source — none accepted.
