# SSRN Research Dossier — Toward the Entry Module

**Compiled:** 2026-10-17
**Scope:** what SSRN (academic + industry practitioner research) says about the exact class of
trading this bot is being built for — SMC/ICT structure, liquidity sweeps, gold intraday,
entry timing, exits, sizing, and validation.
**How to use it:** not a copy list. Each entry gives *what was tested, what was found, why it should
make money, and what part of it we can turn into a rule*. The "Steal list" at the end is the
distilled rule catalog.

> **Honesty header.** SSRN is a preprint server, not peer review. Several of the most on-point
> papers here are single-author working papers posted 2026, with short samples and no replication.
> They are still the best available evidence for *this* niche — because almost nobody else has
> tested it at all. Treat every number below as a **prior to test on our own XAUUSD data**, never
> as a result we have earned. Where sources disagree, the disagreement is written down rather
> than smoothed over.

---

## Tier 0 — Papers that test *this exact framework* (SMC/ICT)

This is the most important tier, because it is the only tier that goes at the actual claims:
sweeps, CHoCH, FVG, order blocks — do they predict anything?

### 0.1 Smart Money or Costly Folklore? A Systematic Evaluation of ICT/SMC Trading Rules in G10 FX
Shepherd Mahadzva, 2026. SSRN **7430998** (part of the *Deflated Alpha Series*, paper 4 of 10).
34 pages. EURUSD, GBPUSD, AUDUSD, USDJPY, intraday TFs.

**Method.** Six mechanically well-defined, independently designed rules drawn from the
ICT/SMC tradition, run through a full walk-forward + bootstrap + permutation + locked-holdout
protocol.

**Findings.**
- Headline: *"No evidence that ICT/SMC concepts work as literally taught."*
- **The interesting part:** three independently constructed **liquidity-sweep mechanisms** —
  (a) swing-based **equal highs/lows**, (b) **real order blocks**, (c) **Asian session ranges** —
  **unanimously agree across 65 of 66 combined fold-selections** that *a swept level predicts
  continuation*, not the textbook reversal. Three different constructions of the same idea
  converging is much stronger evidence than one cherry-picked backtest.
- A fourth mechanism — **CHoCH confirmed by an FVG retracement** — unanimously found the
  **opposite type of error**: the textbook reversal read should be **faded, not traded**.
- Flagship: EURUSD H1 **CHoCH+FVG, faded** → p = 0.0192, walk-forward efficiency 1.58 (inside
  their band), holdout agrees (+19.3%, 60 trades, PF 1.50), Monte-Carlo placement ≈ 81st
  percentile. A second (AUDUSD H1, p = 0.0074) is *more* significant but WF efficiency 2.08 and
  97th percentile → flagged fragile.
- **Negative result worth as much as the positive:** a strategy's real R-multiple edge was
  *smaller than the fixed per-lot commission* it forced through **oversized, tight-stop position
  sizing**. Their fix: a **minimum-stop-distance floor**. (See also 3.5 and Tier 4.)
- Methodology case study: a real bug in their order-block detector was **invisible to every
  statistical gate** and was caught only by a human looking at a chart.

**Why it matters to us.** This is simultaneously (a) a warning that our indicator suite is not
automatically an edge, and (b) the single best external support for the *sweep* concept — with the
direction argument flipped relative to the popular telling. And the minimum-stop-distance finding
is a hard constraint our entry module must enforce.

### 0.2 Do Smart Money Concepts Predict Returns? Evidence from 44 Formalised Detectors on S&P 500 Daily Bars, 2010–2026
Krishna Harsha Tangirala, 2026. SSRN **7483658**. 25 pages.

**Method.** Two widely used open-source Pine Script SMC implementations translated into **44
formally specified event detectors**. 496 S&P 500 constituents, Jan 2010 – Jun 2026:
**2.20 million events, 17.6 million simulated trades**, eight holding horizons. Each trade is
benchmarked **against its own ticker's unconditional return** — a composition-matched null — with
calendar-time Newey-West inference and Benjamini-Hochberg control across **352** concept×horizon
hypotheses. They also run a calibration study with a known zero edge to check test size.

**Findings.**
- Against a naive **zero-return null: 38 of 44 concepts look significant.**
- Against the **matched null, with multiple-testing control: none beats random entry at any
  horizon — and none is significantly worse either.** An exact rotation test finds no winners.
- The **largest well-measured point estimates — 11–12 bp over ten days — are both
  liquidity-sweep detectors**, and they still have **p ≥ 0.23**.
- For ten concepts the data exclude (95%) an edge large enough to cover the lowest modelled
  round-trip cost of 11 bp; the **median concept's minimum detectable edge is 47 bp**.
- Concepts selected on three years of data earn **−31 bp out of sample**, close to the −35 bp
  average of *unselected* concepts.
- The paper is a *corrected re-analysis*: an earlier version claimed 28 of 42 concepts beat random
  entry, 27 of which had actually lost to it. They document exactly how each error manufactured
  a positive result.

**Why it matters to us.** The calibration lesson is the transferable asset. *Any* test without a
matched null and multiple-testing control will hand us 38 "working" rules. This paper is the
reason our entry module needs the validation harness designed **before** the rules.

**Caveats.** Daily bars, equities, US large caps, no intraday structure; results may not transfer
to M15 gold. But note the direction: the *only* detectors with positive point estimates are the
sweep detectors — consistent with 0.1 and with Osler (Tier 2).

### 0.3 The Illusion of Breakouts: Empirical Evidence of Institutional Liquidity Capture in Major Currency Pairs
Rodrigo Costa, 2026. SSRN **6592020**. 10 pages.

**Method.** Decade 2016–2026. Maps the **20-day institutional range** and analyses **3,800+ raw
breakout attempts** on EURUSD, GBPJPY, USDCAD, USDJPY, AUDUSD **and Gold**.

**Findings.**
- FX markets behave **primarily as mean-reversion mechanisms**: breakouts are invalidated and
  liquidity swept in **over 75%** of mapped occurrences.
- **Gold is the exception — a "macroeconomic directional flow anomaly" — consolidating true
  breakouts in over 66% of events.**
- Conclusion for FX: the edge is in **systematically absorbing exhaustion (false breakouts)**.

**Why it matters to us.** Two things. First, it is the *only* paper in this dossier that
explicitly measures gold breakout continuation — and it is **positive on gold while negative on
FX**. Second, it directly **contradicts 0.1 on FX post-sweep direction** (0.1 says swept →
continuation; 0.3 says swept → reversal >75%). That contradiction is itself the finding: the
post-sweep direction is instrument- and construction-dependent, so it must be *measured* on
XAUUSD rather than assumed from either paper. It also warns against lifting FX logic (including
any "fade the breakout" conclusion) straight onto gold.

---

## Tier 1 — Gold / XAUUSD specific

These are the papers written about *our instrument*, two of them about *our timeframe*.

### 1.1 Structural-Break Entry and the Disposition Effect in a Commercial XAUUSD Strategy: A Tick-Level Decomposition
Yongjun Quan, Zhu Zhong, Yonghong Jiang, 2026. SSRN **6941458**. 31 pages.
Spot gold (XAUUSD), 2024–2026, **1,571 trades**.

**Method.** A commercially deployed strategy decomposed **one component at a time** under a
controlled-variables design: entry signal vs position sizing vs exit rule.

**Findings.**
- **"Structural-break entry signals are the sole source of risk-adjusted alpha"
  — annualized Sharpe 2.6–3.1.**
- Robust to a **random-entry placebo**, multiple-testing correction, rolling windows, and
  slippage stress.
- **Regime-conditional position sizing acts as implicit leverage and does NOT outperform
  constant-risk sizing.**
- **The asymmetric partial-exit raises the win rate but institutionalizes the disposition effect
  without adding risk-adjusted return.**
- Methodological caution: tick-data granularity may reshape component-level attribution;
  full real-tick replication is left to future work.

**Why it matters to us.** This is the *closest thing to a direct mandate for the entry module*.
Three separable claims to steal:
1. On XAUUSD, **the structural break is where the alpha is** — our BOS/CHoCH + IDM stack is aimed
   at the right thing.
2. **Fancy sizing is not alpha.** Constant-risk (fixed-fractional) sizing is the honest default;
   any "regime-adaptive" sizing we add must beat it out-of-sample or be cut.
3. **Partial take-profits buy win rate, not expectancy.** If we add them, we should be able to
   say we're doing it for psychological/DD reasons, not because it adds edge.

**Caveats.** Commercially deployed, first author affiliated with the strategy (declared), no
public code, and the authors themselves flag the tick-granularity contingency.

### 1.2 A Regime-Filtered Intraday Trading Framework for Gold: Integrating VWAP Microstructure and EMA-Based Dynamic Exit Mechanisms
Amaanullah Bhatti, 2026. SSRN **6650958**. 22 pages.
**XAU/USD, 15-minute timeframe**, January–December 2024, **247 trades**.

**Rules (stated by the author as machine-testable, no hidden discretion).**
- **200-period EMA = binary regime classifier.**
- **Session VWAP = primary structural reference.**
- **Entry: a precisely defined pullback + rejection signal at the 50-period EMA, above (or below)
  the session VWAP.**
- **Exit: 50-period EMA as a dynamic trailing stop, activated on candle CLOSES only — explicitly
  not on intrabar wick penetrations.** (Motivated by "the propensity of gold prices to produce
  aggressive intrabar wicks that prematurely trigger conventional fixed-distance stop-loss
  orders.")
- Risk: **ATR-adjusted position sizing, hard daily loss limit, explicit news-event exclusion.**

**Reported performance.** 45.3% win rate, **mean expectancy +0.414R**, profit factor 1.76,
annualized Sharpe 3.99, max drawdown 5.1% on fixed 1% risk per trade; outperformed an EMA-crossover
benchmark on every metric.

**Why it matters to us.** This is a *ready-made M15 gold rule template* that is 80% structurally
compatible with what we already compute: VWAP (we don't have it yet), EMA regime, pullback entry
at a level, close-confirmed trailing exit, ATR sizing, daily loss cap, news filter. Two of its
insights are instrument-specific and match our own observations: **gold's wicks are the enemy of
fixed stops**, and **close-confirmed management beats intrabar management**.

**Caveats.** Single year, single instrument, single author, not peer-reviewed, no holdout — a
45% win rate with +0.414R and Sharpe 3.99 on 247 trades is a *very* strong claim that one year of
data cannot establish. Steal the *rule structure*, discount the *performance*.

### 1.3 Who Moves the Price? Trading-Session Return Decomposition and Cross-Session Momentum in Gold and Silver Markets
Wenling Wei, 2026. SSRN **7257240**. 16 pages. Hourly spot, 22 Jul 2024 – 7 Aug 2026.

**Method.** Decomposes gold (XAU/USD) and silver (XAG/USD) cumulative returns across **Asia
(00:00–08:00 UTC), Europe (08:00–14:30 UTC), US incl. late (14:30–24:00 UTC)**, then backtests a
session-to-session momentum rule.

**Findings.**
- **The Asian session produced 77.2% of gold's cumulative log return** (61.7% for silver).
  Europe added +36.2% / +46.6%. **The US session, despite being the most volatile, subtracted
  (−13.4% / −8.2%).**
- Asia's contribution is positive in **every** calendar year; the severe 2026 correction happened
  almost entirely during US hours.
- Session returns show **short-horizon momentum concentrated in continuation into the Asian
  session** (lag-1 autocorrelation +0.13 gold, +0.12 silver).
- Before costs, session momentum beats buy-and-hold; after **0.02% per position change, only the
  long-only variant survives** — net Sharpe **1.68 for gold** at roughly **half** the
  buy-and-hold drawdown (silver 0.84, drawdown 53.6% → 26.2%).
- **Momentum *run inside* the US session loses money net of costs** — consistent with US hours
  being high-variance, drift-less information trading.

**Why it matters to us.** Directly attacks the session question, and it is the sharpest
counter-intuitive result in the dossier: the "obvious" high-volatility window (London/NY overlap,
where every gold educator says to trade) is where the intraday *momentum* edge is weakest, while
the "quiet" Asian session carries the drift. It is also a *cost-sensitivity* lesson: a 0.02% cost
assumption killed every variant except long-only.

### 1.4 Intraday Seasonality in Efficiency, Liquidity, Volatility and Volume: Platinum and Gold Futures in Tokyo and New York
Kentaro Iwatsubo, Clinton Watkins, Tao Xu, 2017. SSRN **3021533**. 30th Australasian Finance and
Banking Conference.

**Findings.** Both Tokyo and NY gold markets show liquidity trading; **informed trading dominates
the New York day session** for both metals; **liquidity trading is more prevalent during the Tokyo
day session**. Different venues for the same underlying have different microstructure.

**Why it matters to us.** The academic counterpart to 1.3 and to every practitioner claim about
which session "matters": Tokyo = liquidity (range, accumulation), New York = information
(trends, real repricing). It also implies our **session filter should be part of the rule set, not
an afterthought** — the same setup is a different bet at 03:00 and at 15:30.

### 1.5 Arbitrage Trading Strategy in Gold Futures
Peter Bell, 2019. SSRN **6077836**.

**Findings.** A strategy **long gold overnight, between the daily London Fixes**, produced
**reliable profits 2000–2010**; the return profile resembles a Bollinger-band strategy extracting
profit from a mean-reverting series.

**Why it matters to us.** A concrete, historically documented calendar/session effect in gold —
and an honest cautionary tale about regime decay (it is stated for 2000–2010; the London Fix
mechanism itself changed).

### 1.6 Divergence in Disguise: Cross-Asset Structural Non-Confirmation as a Reversal Signal in Gold and G10 FX
Shepherd Mahadzva, 2026. SSRN **7431518** (Deflated Alpha Series).

**What it tests.** Dow-Theory-style "related markets must confirm each other" as a
walk-forward-disciplined signal across a G10-FX-plus-metals universe.

**Findings.** Two initial operationalizations fail comprehensively. A third — **comparing gold's
swing structure against the Australian dollar's** — produces **the strongest single result in the
entire ten-paper series**: it clears permutation significance, achieves the **maximum Deflated
Sharpe Ratio reading after full multiple-testing correction**, and **holds up on a locked
holdout**. It survives a **disclosed 100-fold increase in modeled trading costs** with
significance essentially unchanged. It **fails the series' walk-forward-efficiency gate** and
rests on a shorter price history than the FX majors; a fresh reproduction fell short of the
original magnitude (short-history fragility, disclosed).

**Why it matters to us.** This is the only *validated-on-gold* result in the series, and it points
at something our stack doesn't do yet: **gold's swing structure relative to a second reference
market** (AUD as a commodity-currency proxy; the obvious siblings for a gold bot are DXY, real
yields, and AUD). It also happens to be almost exactly a "storyline/bias" engine input — which is
the natural second half of an entry module (`bias → trigger → entry`).

---

## Tier 2 — The academic foundation for "liquidity": stop clustering, round numbers, cascades

Carol Osler's work is the peer-reviewed, *order-level* basis for the entire SMC liquidity story.
The data are real interbank order books, not chart patterns.

### 2.1 Support for Resistance: Technical Analysis and Intraday Exchange Rates
Carol L. Osler, 2000. *FRBNY Economic Policy Review* 6(2). SSRN **888805**.

**Finding.** Support/resistance levels supplied to customers by **six** FX firms were rigorously
evaluated for the first time: **"strong evidence that the levels help to predict intraday trend
interruptions"**, though predictive power **varies across exchange rates and firms**.

### 2.2 Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis
Carol L. Osler, 2003. *Journal of Finance* 58(5). SSRN **447361**.

**Findings (real order-book data, Royal Bank of Scotland).**
- **Take-profit orders cluster strongly AT round numbers.**
- **Stop-loss orders cluster strongly JUST BEYOND round numbers** — sell stops just *below*,
  buy stops just *above*.
- This asymmetry explains **two** classic technical-analysis predictions:
  (1) trends tend to **reverse** at predictable support/resistance levels;
  (2) trends tend to be **unusually rapid after crossing** such levels.
- And: **96% of analyst-supplied S/R levels end in 0 or 5; 20% end in 00.**

### 2.3 Stop-Loss Orders and Price Cascades in Currency Markets
Carol L. Osler, 2002/2005. FRB New York Staff Report **150**, *J. International Money & Finance*
24(2). SSRN **920687**.

**Findings.** Stop-loss orders generate **positive-feedback trading** and cause **price cascades**:
1. Exchange-rate trends are **unusually rapid** when rates reach levels where stop-loss orders are
   documented to cluster.
2. The response to **stop-loss** order clusters is **larger** than to take-profit clusters.
3. The response **lasts longer** than for take-profit clusters.
4. Cascades may occur **as frequently as once per week** in volatile regimes, and contribute to the
   **fat tails** of FX returns. Rates reverse course at round numbers **more frequently** than at
   other numbers.

**Why this tier matters to us.** It reframes our liquidity levels from folklore to microstructure:
- Our **EQH/EQL pools and round numbers are not arbitrary lines** — they are where price-contingent
  orders demonstrably rest, with a **directional asymmetry** (take-profits at the level, stops just
  beyond it) that predicts *both* the reversal *and* the acceleration.
- It gives a **testable, parameterised** version of "sweep": the sweep target is *just beyond* a
  round/equal level, and the expected behaviour is **acceleration** — which is exactly what 0.1
  found (swept → continuation) and what 0.3 counters on FX.
- It justifies treating **round numbers** (and gold's, e.g. 4150/4200) as first-class levels in the
  level engine, alongside structure-derived ones.
- Most results are significant **for hours, not days** — i.e. this is an *intraday* effect, which is
  the horizon we trade.

---

## Tier 3 — Intraday momentum, ORB, and VWAP (the "timing" school)

Zarattini/Aziz/Barbon are the industry side: practising day traders publishing backtests with
explicit rules and costs.

### 3.1 Can Day Trading Really Be Profitable? (ORB on QQQ / TQQQ)
Zarattini & Aziz, 2023. SSRN **4416622**. 18 pages.
### 3.2 A Profitable Day Trading Strategy For The U.S. Equity Market
Zarattini, Barbon, Aziz, 2024. Swiss Finance Institute RP 24-98. SSRN **4729284**. 26 pages.
7,000+ US stocks, 2016–2023.

**Rules (explicit, and they are worth copying almost verbatim as a template).**
- Take the **5-minute opening range** (first 5 minutes of the session).
- Direction = the direction of that first candle. **Enter at the open of the second 5-minute
  candle.**
- **Stop = the opposite side of the opening range.** Risk `$R = entry − stop`.
- **Target/exit: profit capped at 10R, otherwise liquidate at market close** (one trade per day).
- Sizing: `Shares = min( (A × 1%) / $R , 4 × A / P )` — 1% risk, 4× max intraday leverage.
- Bonus filters found valuable: **only trade "Stocks in Play"** (abnormally high relative volume /
  news). Also compares **15/30/60-minute** ORB variants.

**Results.** ORB win rate **24%** with **average +0.13R per trade** — a *low-accuracy, high-payoff
asymmetry*. Top-20 Stocks-in-Play portfolio: **>1,600% net, Sharpe 2.81, annualized alpha 36%**
vs 198% for passive S&P 500. Leveraged version 1,484% vs 169% for QQQ.

### 3.3 Beat the Market: An Effective Intraday Momentum Strategy for SPY
Zarattini, Aziz, Barbon, 2024. SFI RP 24-97. SSRN **4824172**. 43 pages.

**Findings.** Unlike the academic literature (which trades only the last 30 minutes), their model
**initiates trend-following positions as soon as there is an indication of abnormal demand/supply
imbalance in the intraday price action**, and uses **dynamic trailing stops** to cap downside while
keeping unlimited upside. 2007 – early 2024: **+1,985% net, 19.6% annualized, Sharpe 1.33**.
They also test volatility regimes, **dealer gamma imbalance** as a predictor of strategy
profitability, day-of-week effects, and slippage/commission sensitivity.

### 3.4 VWAP: The Holy Grail for Day Trading Systems
Zarattini & Aziz, 2023. SSRN **4631351**. 26 pages.

**Rule.** Long when price is **above** the (session) VWAP, short when **below**. QQQ/TQQQ,
2 Jan 2018 – 28 Sep 2023.

**Results.** $25,000 → **$192,656 net (+671%)**, max DD **9.4%**, Sharpe **2.1**, vs buy-and-hold
+126% / 37% DD / Sharpe 0.7. They explicitly say it is "not a fully developed trading system".

### 3.5 Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return
Gao, Han, Li, Zhou, 2015 / *Market Intraday Momentum*, JFE 2018. SSRN **2552752** / **2440866**.

**Findings.** S&P 500 ETF 1993–2013: **the first half-hour return (measured from the previous
close) predicts the last half-hour return**, both statistically and economically significant
(R² ≈ 1.6%). Stronger on **more volatile days, higher volume days, recession days, and major
macro-news release days**. Holds for ten other heavily traded ETFs. Attributed to the trading
behaviour of **day traders and informed traders**.

**Why Tier 3 matters to us.** It supplies the *timing and payoff-shape* defaults our entry module
needs: trade the **early-session imbalance** rather than waiting for the close; expect a **low win
rate with high R multiples** (so don't judge rules by accuracy); use **relative volume as a
"stock in play" filter** (our gold analogue: ATR/ADR expansion, news days); and treat **VWAP as a
first-class level**, not an add-on. Note the tension with 1.3: these are US-equity session effects;
gold's session decomposition (1.3) points the other way. Test, don't assume.

---

## Tier 4 — Exits, stops, and sizing (where the research is most brutal)

### 4.1 Nine Thousand Random Entries, Six Exit Policies: Expectancy Stays at the Spread While the Loss Tail Moves Fivefold
Marijan Tolusic, 2026. SSRN **7550078**. 5 pages.

**Method.** **Removes the entry.** 9,000 seeded **random** entries with **coin-flip direction**,
identical across treatments, run through **six pre-specified exit policies** on six major FX pairs,
hourly, 2023–2026, **net of each entry bar's own recorded spread**.

**Findings.**
- The six policy means span a band of **0.93 pips (−1.56 to −0.64 pips per trade)**, each within
  two standard errors of **its spread cost**, and **no pairwise difference is distinguishable from
  zero**.
- The same entries under the same policies differ enormously in **risk**: per-trade dispersion
  spans **2.34×** (23.8 → 55.8 pips); the **1% loss tail spans 5.14×** (−38.3 pips under a tight
  fixed stop, −196.7 under take-profit-only).
- Switching exit convexity on entry-time volatility beats its own inversion by nothing (t = −0.23).
- A seven-year repetition reproduces all three facts.

**Conclusion, in the author's words:** *"An exit rule cannot create expectancy on information-free
entries; what it chooses, at full force, is the distribution of outcomes."*

### 4.2 When Do Stop-Loss Rules Stop Losses?
Kathryn M. Kaminski & Andrew W. Lo, 2007/2013. *J. Financial Markets* 18. SSRN **968338**.

**Findings.** A framework for the "stopping premium". **Under the Random Walk Hypothesis, simple
0/1 stop-loss rules always DECREASE expected return.** In the presence of **momentum**, stop-loss
rules **can add value**. They derive explicit conditions for mean-reversion, momentum, and
Markov regime-switching processes; in the equities application (with bonds as the stop-out asset,
1950–2004) certain rules add **50–100 bp per month** during stop-out periods, and switching to a
lower-vol asset at the threshold **reduces portfolio variance**.

### 4.3 Stop-Loss Strategies with Serial Correlation, Regime Switching, and Transactions Costs
Andrew W. Lo & Alexander Remorov, 2015. SSRN **2695383**.

**Findings.** Closed-form impact of stop-loss strategies under serial correlation, regime
switching, and **costs**. On a large sample of US stocks: **tight stop-loss strategies tend to
UNDERPERFORM buy-and-hold in a mean-variance framework due to excessive trading costs.**
Outperformance is possible for stocks with **sufficiently high serial correlation** in returns.
They "succeed at reducing downside risk, but not substantially".

### 4.4 A Framework for Evaluating Position Sizing Policies in Algorithmic Trading
Mohammad Mahdi Masoumian, 2026. SSRN **7382618**. 23 pages. *(Python code released open-source.)*

**Findings.** A Monte-Carlo framework moving from a frictionless theoretical expectancy criterion
to a **cost-adjusted, empirically simulated** assessment of realized growth, drawdown, **ruin
probability**, and capital utilisation. Compares **fixed-dollar vs percentage-of-equity** sizing
and derives a **cost-adjusted Kelly criterion**. Key demonstration: **neglecting realistic
transaction costs can overstate reported returns by a substantial margin.**

### 4.5 Trade Sizing Techniques for Drawdown and Tail Risk Control
Issam S. Strub, 2012/2016. SSRN **2063848**. 34 pages.

**Findings.** Three sizing algorithms for controlling tail risk / max drawdown: (1) historical
**volatility** estimates; (2) **EVT → CVaR**; (3) **EVT on the drawdown distribution → CDaR**.
Applied to 10 years of daily returns across FX pairs, a Treasury future, and a G10 basket, with
detailed tail-risk/drawdown comparisons.

### 4.6 Bayesian Kelly Criterion with Parameter Uncertainty
Sergei Sukhov, 2026. SSRN **6195358**. 16 pages.

**Findings.** Closed-form **fractional Kelly under beta-distributed probability beliefs**;
Monte-Carlo across sample sizes shows Bayesian Kelly **reduces max drawdown by 40–60%** while
retaining **85–95% of optimal growth**, and produces structurally shallower drawdowns during
elevated estimation uncertainty. Out-of-sample validation on ~2 decades of S&P 500 E-mini futures.

### 4.7 Volume Profile Mean Reversion + "Tape Speed", SOL/USDT perp, 5 years
Nipun Perera, 2026. SSRN **6932998**. 25 pages.

**Findings.** 1,825 days / 525,600 five-minute candles with realistic futures costs
(0.05% maker, 0.05% taker, 0.02% slippage/side): a **0.15% stop-loss configuration is
mathematically unviable — transaction costs consume 93% of the risk allocation.** Stops of
**1.0–2.0%** show statistically significant profitability (Sharpe > 2.0, PF > 2.5).

**Why Tier 4 matters to us.** This is the tier that should change our priorities:
1. **Exits do not create edge** (4.1), and the one gold-specific decomposition we have agrees
   (1.1: entry = sole alpha; partial exits add win rate, not expectancy). So: get the **entry**
   right and keep exits boring.
2. **But stops still matter for survival, and they are only justified when returns are not a
   random walk** (4.2) — which is precisely what our momentum/structural thesis claims, so stops
   are consistent with our own premise *if* the premise is true.
3. **Tight stops are how small accounts lose** (4.3, 4.7, and 0.1's minimum-stop-distance floor).
   On gold, with a spread and swap on every trade, a 3-dollar stop is a fee-paying machine.
   Two independent papers (0.1, 4.7) converge on the same engineering fix: a **minimum stop
   distance**, expressed in ATR/spread terms.
4. **Sizing = fixed fractional, and regard anything fancier as unproven** (1.1 explicitly found
   regime-conditional sizing did not beat constant-risk). Fractional/Bayesian Kelly (4.4–4.6) is
   the honest ceiling, not the starting point.

---

## Tier 5 — Validation methodology (the non-negotiable toolkit)

If Tier 0–4 is *what to trade*, this is *how to know whether we're fooling ourselves*.

| Paper | SSRN | What to take |
|---|---|---|
| **Backtesting** — Harvey & Liu (2015) | 2345489 | A statistical framework that determines the **appropriate haircut for any reported Sharpe ratio** given the number of tests run, plus a "profit hurdle" for significance. The direct answer to "we tried 40 variants". |
| **Multiple Testing and the Mirage of Technical Alpha** (Paper 1 of the Deflated Alpha Series) — Mahadzva (2026) | 7430758 | The pre-registered protocol: **anchored six-fold walk-forward + locked 15% final holdout**, and three gates that must *all* pass: (1) permutation test vs a random-entry null, (2) **Deflated Sharpe Ratio corrected for the program's full trial count (7,708 trials)**, (3) positive holdout. Of 45 evaluable combinations, **zero cleared all three**; the best had positive walk-forward expectancy, failed permutation, **DSR 0.00**, and lost money on holdout. |
| **Do SMC Concepts Predict Returns?** — Tangirala (2026) | 7483658 | **Composition-matched null** (benchmark each trade against its own instrument's unconditional return) + calendar-time Newey-West + BH control. And the calibration test with a known zero edge to verify test *size*. |
| **Smart Money or Costly Folklore** — Mahadzva (2026) | 7430998 | Full gate stack in practice: permutation + **walk-forward efficiency band** (a metric that flags OOS results running *hotter* than in-sample implies) + bootstrap percentile placement + holdout. Also: their chart-inspection step caught a bug statistics could not. |
| **A Framework for Evaluating Position Sizing…** — Masoumian (2026) | 7382618 | Cost-adjusted evaluation: **frictionless vs realistic**, ruin probability, capital utilisation. |
| **Fibonacci Illusion** — Mahadzva (2026) | 7430898 | A worked example of a **selection-bias trap**: rare combined conditions winning folds on a handful of lucky trades. Also shows OOS-significant + holdout-disagreeing as a distinct failure mode. |
| **Session Microstructure and the Momentum Mirage** — Mahadzva (2026) | 7435081 | The four checks and which failure each catches: OOS significance, holdout agreement, walk-forward efficiency, fold-level direction consistency. Plus a deceptively good backtest reading "−290% of notional" drawdown that no margined account could sustain. |
| **Walk Forward Correlation** (2026) | 6324079 | Diagnostic for over-fitting *and* presence of genuine structural edge. |
| **Predictive Value of Within-Strategy Permutation Tests** — Gatto (2026) | 6636018 | 437,911 strategy configurations across nine instruments — whether acting on a permutation test actually improves forward selection. |

**Design consequence.** The entry module must be built with the **trial counter** as a first-class
citizen: every rule variant we evaluate increments the count that feeds the DSR, and the **final
holdout is spent once**. This is a build-time requirement, not a later cleanup.

---

## Tier 6 — Order flow / microstructure (honest assessment: mostly out of reach)

- **Cont, Kukanov & Stoikov (2014), *The Price Impact of Order Book Events*** — the canonical
  **Order Flow Imbalance (OFI)** result: OFI derived from the limit order book is strongly related
  to **contemporaneous** price changes at very short horizons.
- **Kethan S E (2026), *Predictive Order Flow Imbalance* — SSRN 7053198.** Twelve instruments,
  Apr 2024–Apr 2025, OFI from Level-1 NBBO at 10-second bars, walk-forward Ridge across 84
  fold-ticker combinations. Mean IC **+0.0044** (pooled t = 3.26, p = 0.0016), OOS IC +0.0022.
  HMM regimes give mixed signs (calm: +0.0161 IC at 5m; stressed: negative at 30s). **The strategy
  does not survive transaction costs — only NVDA nets a positive Sharpe (+0.14).** Regime findings
  do not survive multiple-testing correction.
- **Xu, Gould & Howison (2019), *Multi-Level Order-Flow Imbalance* — SSRN 3479741.** Out-of-sample
  fit improves with **each additional book level** included; order-flow activity **deep in the
  book** influences price formation.
- **Jonuzaj, Sancetta & Taranenko (2024) — SSRN 4971656.** NASDAQ, 35 large caps, 2019–2023.
  **Trade** order flow is the most persistent/predictable signal, but the informational advantage
  **dissipates within the first 10 milliseconds**; **model complexity does not ensure higher
  returns**; over time the value of order flow has **decreased**.
- **Zhang, Yichi et al. *ClusterLOB* — SSRN 5236285.** Clusters MBO events into directional /
  opportunistic / market-making participants; cluster-wise OFI as a signal beats benchmarks that
  ignore clustering.
- **Vafin (2026) — SSRN 6938742.** OFI in crypto: consolidates the literature and gives a
  reproducible evaluation plan (crypto is attractive precisely because the **aggressor side is
  reported** rather than estimated).

**Why this tier matters to us even though we can't use it directly.** MT5 gives us **tick volume,
not true volume, and no order-book depth** for XAUUSD CFD. So genuine OFI is not available in
this stack — which is worth stating plainly so we don't build a fake version of it. What *is*
transferable: (a) the **volume/participation** idea degrades gracefully into relative tick volume
and range expansion; (b) the finding that any order-flow edge **dies inside milliseconds and
rarely survives costs** is a strong prior *against* expecting an OFI-style edge at M15 for a retail
CFD; (c) if we ever want it, the path is a **crypto or futures instrument where the aggressor side
is public** (Vafin's point), not the CFD.

---

## The Steal List — distilled, with source and confidence

Confidence = how much I'd rely on it *before* testing on our own data.

### A. Entry architecture (high confidence, multiple sources)
| # | Rule | Source | Confidence |
|---|---|---|---|
| A1 | **The entry is where the alpha is.** Exits/sizing reshape the distribution; they do not create expectancy. | 1.1 (XAUUSD), 4.1 (9,000 random entries) | High — the two cleanest experiments in this dossier agree. |
| A2 | **Trade the structural break, not the reversal story.** On gold, structural-break entries are the sole source of risk-adjusted alpha and survive placebo + multiple-testing + slippage stress. | 1.1, 0.3 (gold: true breakouts hold >66%) | High for gold specifically. |
| A3 | **A swept level predicts continuation** — three independent constructions (EQH/EQL, order blocks, Asian range) agree in 65/66 fold-selections. | 0.1 | Medium-high (FX; contradicts 0.3 on FX, which makes instrument testing mandatory). |
| A4 | **The CHoCH+FVG "reversal" read is the losing side on FX; fading it is the profitable side.** | 0.1 (p=0.0192, holdout +19.3%, PF 1.50) | Medium (single author, FX-only, small holdout). *Directly tensions our current BOS/CHoCH-continuation entries → must be tested on gold.* |
| A5 | **Liquidity rests asymmetrically around round numbers**: take-profits *at* the level, stops *just beyond*; trends accelerate after crossing, reverse more often at round numbers. 96% of analyst S/R ends in 0/5. | 2.1, 2.2, 2.3 | High (peer-reviewed, real order-book data). Under-utilised in our level engine. |
| A6 | **Regime gate before signal**: 200-EMA (or equivalent) as a binary regime classifier; only take setups aligned with the regime. | 1.2 (XAUUSD M15) | Medium (rule structure is sound and testable). |
| A7 | **VWAP is a first-class level**, not an oscillator: above = long bias, below = short bias; and pullback-rejection at a fast EMA *relative to* session VWAP as the trigger. | 1.2, 3.4 | Medium-high. We don't compute VWAP yet — gap to fill. |
| A8 | **Twelve-hour/session bias step.** Bias → trigger → entry, with the bias step fed by structure *and* a second reference market (gold vs AUD/DXY/real yields). Gold-vs-AUD structure divergence is the best-validated result in the ten-paper series. | 1.6, 1.4, 1.3 | Medium (fails WF-efficiency gate; short history). |

### B. Timing (medium confidence, contested)
| # | Rule | Source | Confidence |
|---|---|---|---|
| B1 | **Trade the early-session imbalance**, not only the close: the first half-hour (from prior close) predicts the last half-hour. | 3.5 | High for US equities; unproven for gold. |
| B2 | **Relative-volatility "in play" filter**: only take signals on days/candles with abnormal participation. In equities this was the single biggest improvement. | 3.2, 3.5 | Medium-high as a concept. |
| B3 | **Session selection is a real edge/risk axis.** Gold's drift is concentrated in Asia (+77.2% of cumulative log return, positive every year); US hours are the most volatile and net *negative*; US-session momentum loses money net of costs. | 1.3, 1.4 | Medium (short sample, striking effect). Contradicts practitioner lore about London/NY — test it. |
| B4 | **Round-number levels** (gold: 4150/4200/…) as sweep targets and reversal zones. | 2.2, 2.3 | High (microstructure). |
| B5 | **ADR/budget check**: don't enter late in the day when the daily range is already spent. | practitioner consensus in search results; consistent with B3 | Low-medium (not in a paper we found; include only as a cheap filter). |

### C. Exits and stops (medium-high confidence)
| # | Rule | Source | Confidence |
|---|---|---|---|
| C1 | **Minimum stop distance floor** (ATR/spread-relative). Below it, costs eat the risk and the R-multiple edge is fiction. | 0.1 (explicit fix), 4.7 (0.15% stop → costs = 93% of risk) | High — two independent papers converge. |
| C2 | **Stop placement must respect gold's wick behaviour**: close-confirmed management, not intrabar wick stops. | 1.2 | Medium-high (and matches our own chart observations). |
| C3 | **Stops are justified by non-random-walk returns** — the stopping premium is negative under a random walk, positive with momentum/regime switching. So our stop is a *bet on our own momentum thesis*, not a free lunch. | 4.2 | High (peer-reviewed theory). |
| C4 | **Asymmetric payoff is normal**: 24% win rate with +0.13R average, target ~10R caps. Judge rules by expectancy, never by win rate. | 3.2 | High (large sample). |
| C5 | **Partial take-profits raise win rate but not risk-adjusted return.** Add only with a stated non-alpha reason. | 1.1 (XAUUSD), 4.1 | Medium-high. |
| C6 | **Trailing stops are legitimate on the momentum sleeve** (dynamic trailing stops, unlimited upside) — but they are a *risk-shaping* choice, consistent with 4.1. | 3.3, 1.2 | Medium. |

### D. Sizing (medium confidence)
| # | Rule | Source | Confidence |
|---|---|---|---|
| D1 | **Fixed-fractional, constant-risk sizing is the default.** Regime-conditional sizing acted as implicit leverage and did not beat it on XAUUSD. | 1.1 | High (directly on our instrument). |
| D2 | **1% risk per trade, hard daily loss limit, explicit news exclusion.** | 3.2, 1.2 | High as a starting policy. |
| D3 | **Fractional/Bayesian Kelly is the ceiling, not the start** (−40–60% max DD for 85–95% of growth). | 4.6 | Medium. |
| D4 | **Cost-adjust everything**: frictionless backtests materially overstate returns. | 4.4, 4.7, 1.3 (0.02% cost kills non-long-only variants) | High. |

### E. Validation (non-negotiable)
| # | Rule | Source | Confidence |
|---|---|---|---|
| E1 | **Locked final holdout, spent once.** Pre-registered folds. | 5 (7430758), 0.1 | High. |
| E2 | **Composition-matched null** — benchmark each trade against the instrument's own unconditional return at the same horizon, not against zero. | 7483658 | High — this is the test that turned 38 "winners" into 0. |
| E3 | **Deflated Sharpe / Sharpe haircut that counts our trials.** | 5 (2345489, 7430758) | High. |
| E4 | **Permutation test vs random-entry null** + **walk-forward efficiency band** (flags OOS running hotter than IS implies). | 0.1, 5 | High. |
| E5 | **Bootstrap the trade sequence** and report percentile placement, not just p-values. | 0.1 | Medium-high. |
| E6 | **Human chart inspection is a required gate.** A real order-block bug was invisible to every statistical test. | 0.1 | High — and it's how we already caught our own BOS miss. |

---

## What the research says NOT to do

1. **Don't assume the indicator suite is an edge.** 38 of 44 SMC concepts looked significant
   against a naive null and **none** beat a matched null with multiple-testing control.
2. **Don't judge by win rate.** The best-evidenced day-trading system in this dossier runs at 24%.
3. **Don't use tight stops.** Three sources converge that tight stops convert edge into fees.
4. **Don't expect exits to save a bad entry.** On information-free entries, six exit policies all
   landed within a standard error of the spread.
5. **Don't add regime-adaptive sizing and call it alpha** — on XAUUSD it didn't beat constant risk.
6. **Don't lift FX conclusions onto gold.** The two instruments land on opposite sides of the
   breakout-continuation question, twice, in this dossier.
7. **Don't build fake order flow.** MT5 doesn't give us book depth; a probe-volume "CVD" is not OFI.
8. **Don't trust a single p-value, ever.** The series that produced the SMC findings also produced
   four separate demonstrations of significant results that died on holdout.

---

## Open questions the research does NOT settle (inputs for the design)

1. **Continuation or reversal after a sweep on gold?** 0.1 (FX continuation) vs 0.3 (FX reversal
   >75%, gold continuation >66%) vs our own IDM logic (continuation in trend direction). This is
   the single highest-value experiment: our sweep detectors already fire, so we can measure the
   forward R-multiple conditional on construction, direction, and session, on years of XAUUSD.
2. **Which session should the entry module trade?** Practitioner lore says London/NY; 1.3 says
   Asia carries gold's drift and US-session momentum loses money net. Need a per-session
   expectancy breakdown from our own data.
3. **Does the CHoCH+FVG fade transfer to gold?** Our whole structure→IDM→entry chain currently
   bets on the continuation read. If A4 transfers, part of our chain is inverted.
4. **Is the structural break tradeable at M15 with a retail CFD spread?** 1.1 measured 1,571
   trades on real XAUUSD; 0.1 and 4.7 both found cost-driven minimum stop distances. We need our
   own cost model before any expectancy claim.
5. **Does the gold-vs-AUD framing (1.6) reproduce, and with which proxy (AUD, DXY, real yields)?**
6. **What is the module's actual job** — signal generator for human review, a backtestable rule
   engine, or live execution? This determines whether we build the validation harness first
   (Tier 5) or the rules first.

---

## Source index

| Ref | SSRN | Title |
|---|---|---|
| 0.1 | 7430998 | Smart Money or Costly Folklore? ICT/SMC Rules in G10 FX (Mahadzva) |
| 0.2 | 7483658 | Do SMC Predict Returns? 44 Detectors, S&P 500 Daily 2010–2026 (Tangirala) |
| 0.3 | 6592020 | The Illusion of Breakouts: Institutional Liquidity Capture (Costa) |
| 1.1 | 6941458 | Structural-Break Entry & Disposition Effect in a Commercial XAUUSD Strategy (Quan et al.) |
| 1.2 | 6650958 | A Regime-Filtered Intraday Trading Framework for Gold: VWAP + EMA (Bhatti) |
| 1.3 | 7257240 | Who Moves the Price? Session Decomposition & Cross-Session Momentum (Wei) |
| 1.4 | 3021533 | Intraday Seasonality: Platinum and Gold Futures, Tokyo & New York (Iwatsubo et al.) |
| 1.5 | 6077836 | Arbitrage Trading Strategy in Gold Futures (Bell) |
| 1.6 | 7431518 | Divergence in Disguise: Gold vs AUD Structural Non-Confirmation (Mahadzva) |
| 2.1 | 888805 | Support for Resistance (Osler, FRBNY EPR 2000) |
| 2.2 | 447361 | Currency Orders and Exchange Rate Dynamics (Osler, JF 2003) |
| 2.3 | 920687 | Stop-Loss Orders and Price Cascades (Osler, FRBNY SR150 / JIMF 2005) |
| 3.1 | 4416622 | Can Day Trading Really Be Profitable? (Zarattini & Aziz) |
| 3.2 | 4729284 | A Profitable Day Trading Strategy For The U.S. Equity Market (Zarattini et al.) |
| 3.3 | 4824172 | Beat the Market: Intraday Momentum for SPY (Zarattini et al.) |
| 3.4 | 4631351 | VWAP: The Holy Grail for Day Trading Systems (Zarattini & Aziz) |
| 3.5 | 2552752 | Intraday Momentum: First Half-Hour Predicts Last Half-Hour (Gao et al.), JFE 2018 |
| 4.1 | 7550078 | Nine Thousand Random Entries, Six Exit Policies (Tolusic) |
| 4.2 | 968338 | When Do Stop-Loss Rules Stop Losses? (Kaminski & Lo) |
| 4.3 | 2695383 | Stop-Loss Strategies with Serial Correlation, Regime Switching, Costs (Lo & Remorov) |
| 4.4 | 7382618 | Framework for Evaluating Position Sizing Policies (Masoumian) |
| 4.5 | 2063848 | Trade Sizing Techniques for Drawdown and Tail Risk Control (Strub) |
| 4.6 | 6195358 | Bayesian Kelly Criterion with Parameter Uncertainty (Sukhov) |
| 4.7 | 6932998 | Volume Profile Mean Reversion + Tape Speed, SOL/USDT (Perera) |
| 5 | 2345489 | Backtesting (Harvey & Liu) |
| 5 | 7430758 | Multiple Testing and the Mirage of Technical Alpha, Deflated Alpha Series Paper 1 (Mahadzva) |
| 5 | 7430898 | The Fibonacci Illusion (Mahadzva) |
| 5 | 7435081 | Session Microstructure and the Momentum Mirage (Mahadzva) |
| 5 | 6324079 | Walk Forward Correlation (2026) |
| 5 | 6636018 | Predictive Value of Within-Strategy Permutation Tests (Gatto) |
| 6 | 7053198 | Predictive Order Flow Imbalance: Cross-Asset Microstructure Alpha (Kethan S E) |
| 6 | 3479741 | Multi-Level Order-Flow Imbalance in a Limit Order Book (Xu et al.) |
| 6 | 4971656 | Information Content of Book and Trade Order Flow (Jonuzaj et al.) |
| 6 | 5236285 | ClusterLOB (Zhang et al.) |
| 6 | 6938742 | Order-Flow Imbalance and Short-Horizon Predictability in Crypto (Vafin) |

SSRN URLs are `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=<id>`.

---

## Status: entry-module build parked (2026-10-17)

Research stage complete. **No entry-module code has been written.** Nothing in the
indicator/rendering path was touched.

**Decisions locked in during the design conversation:**

- **Scope:** all three, staged — (1) rule engine + validation harness, (2) chart signal overlay,
  (3) MT5 execution last, once an entry is proven.
- **The engine is a read-only consumer** of the existing indicator payload. It defines its own
  rules *on top of* the levels; the indicator system and its chart rendering are not modified.
- **Toggleable from the settings tab:** each entry rule registers in `strategy/registry.py`
  (`MODULES`) and is switched via `GET/POST /api/settings/modules`, persisting to
  `config/modules_state.json` — already scaffolded, currently `MODULES = []`.
- **Layering:** indicators answer *"what is on the chart"*; the entry engine answers *"given that,
  is there a trade, and what is it"*.

**Still open:** the proof bar for calling a rule "working" (full gate stack vs a staged
visual → expectancy → gates progression).

**Highest-value first experiments, using indicators we already have:**

1. **Post-sweep direction on XAUUSD** — 7430998 finds continuation, 6592020 finds reversal in FX
   but continuation in gold. Our sweep detectors already fire, so this is measurable with no new
   indicators.
2. **Does the CHoCH+FVG fade (7430998's flagship) transfer to gold?** It attacks the exact
   assumption our structure → IDM → entry chain rests on.
3. **Session-conditional expectancy** (Asia vs Europe vs US) against 7257240's inversion of the
   London/NY consensus.
