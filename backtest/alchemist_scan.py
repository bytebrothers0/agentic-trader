"""
backtest/alchemist_scan.py — find Alchemist MNSR setups on real history and price
them the way the playbook (``strategies/phoenix_mnsr.md``) would.

The codified claim
------------------
The playbook's reversal arc is deterministic enough to be *scanned*, exactly the
way ``crt_scan`` scans the CRT detector:

1. **Sweep** (``ts`` in the bot's vocabulary): a candle whose wick pierces the
   standing range extreme (the highest high of the previous ``DONCH`` bars —
   the pool the market is raiding) and whose **body closes back inside** — the
   e-book's FAKE, not a breakout. A push that *closes* beyond the pool means
   the raid drove on: the arc dies (the container is re-established by the
   rolling window itself).
2. **The shift (MSS)**: within ``SHIFT_WINDOW`` bars of the sweep, a **body
   close** through the most recent confirmed swing on the other side (the pull
   back pivot that preceded the raid). The shift bar's close is the decision
   instant — the moment a real Alchemist limit would be placed.
3. **The range**: sweep extreme (the raid's wick tip) -> the post-MSS extreme.
   Its 50% is the premium/discount line.
4. **The POI**: the playbook's "at most two, nearest to price" — the range
   midpoint and the OB50 of the last opposite-colour candle before the shift.
   For a short the larger (higher) one is the first-filled edge. A POI outside
   the range interior is invalid and dropped.
5. **The naive trade**: entry = the POI limit (pending order; ``replay.simulate``
   walks fills the way the harness does), stop beyond the sweep wick tip +
   ``STOP_BUFFER_ATR`` x ATR(14), target = the nearest opposing swing
   **established before the raid** (the SSL/BSL stair below/above; the pool
   "the setup has no reason to exist" without), at least ``TARGET_MIN_ATR``
   away from the entry. The playbook's hard budget (45 pips = 4.50) and risk
   floor are applied as *filters*; a setup without a sane target has no reason
   to exist and is not collected.

Nothing here is a second perception path: scoring uses the full scan frame, the
replayed agent uses ``FrozenLoader`` + the real detectors. Read-only throughout.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.historical import tf_seconds
from indicators.swings import Pivot, find_pivots

#: Stop buffer beyond the sweep wick, in ATR(14) — playbook §7 (~0.3xATR).
STOP_BUFFER_ATR = 0.3
#: The playbook's hard stop budget on gold: 45 pips (4.50). Beyond = skip.
SL_CEILING = 4.5
#: Minimum meaningful risk (1.5 pips) — tighter means the POI hugs the wick tip.
SL_FLOOR = 0.15
#: Bars the shift must print within, else the arc is dead (TS's 1..max_between spirit).
SHIFT_WINDOW = 20
#: Bars watched after the MSS for the post-shift extreme to form.
POST_WINDOW = 8
#: The rolling container: a pool is the extreme of the previous N bars.
DONCH = 6
#: The pullback pit: the raid launches from the low (high) of the previous N bars.
PIT_WINDOW = 6
#: Bars a (near-)same-level activation stays cooldown, so one raid is one setup.
POOL_COOLDOWN = 4
#: Bars between two same-direction arcs, whatever the pool — the raid is one story.
ARC_COOLDOWN = 3
#: Fractal pivots confirmed this many bars after the swing bar.
PIVOT_LENGTH = 2
#: The opposing swing must sit at least this many ATRs from the entry.
TARGET_MIN_ATR = 1.0
#: R:R at/above this meets the playbook floor (reported, not dropped).
RR_FLOOR = 1.5


@dataclass
class AlchemistCandidate:
    """One swept-pool Alchemist arc, priced as the playbook's naive limit."""

    timeframe: str = ""
    direction: str = ""                 # "bullish" | "bearish"
    pool_price: float = 0.0             # the swept range extreme
    sweep_extreme: float = 0.0          # the raid's wick tip
    post_extreme: float = 0.0           # the post-MSS leg extreme
    range_size: float = 0.0
    range_mid: float = 0.0              # the 50% PD line
    poi_price: float = 0.0              # the limit placed ("nearest to price")
    poi_kind: str = ""                  # "mid50" | "ob50"
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0                 # nearest opposing pre-raid swing
    target_kind: str = ""               # "swing" | "post_extreme"
    risk: float = 0.0
    reward: float = 0.0
    rr: float = 0.0
    stop_distance_pips: float = 0.0     # 1 pip = 0.10
    # -- indices/times on the scan frame -------------------------------------
    sweep_index: int = 0                # the piercing bar's iloc
    shift_index: int = 0                # the MSS bar (the decision bar)
    sweep_time: str = ""
    shift_time: str = ""
    decision_time: str = ""
    #: the replay scorer's vocabulary (the decision bar it walks forward from)
    manipulation_index: int = 0
    state: str = "armed"
    bars_to_target: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        return (
            f"[{self.timeframe}] {self.direction.upper()} sweep of {self.pool_price:.3f} "
            f"-> shift at {self.shift_time} (extreme {self.sweep_extreme:.3f}, "
            f"post {self.post_extreme:.3f}); limit {self.poi_kind} {self.poi_price:.3f} "
            f"/ {self.stop:.3f} / {self.target:.3f} R:R {self.rr:.2f}"
        )


def scan_alchemist_setups(
    df: pd.DataFrame,
    timeframe: str = "M15",
    *,
    since: Optional[pd.Timestamp] = None,
    until: Optional[pd.Timestamp] = None,
) -> tuple[List[AlchemistCandidate], List[Dict[str, Any]]]:
    """Every placeable Alchemist arc in the window, chronologically — plus the
    skip ledger.

    Returns ``(candidates, skips)``. ``candidates`` are placeable arcs; ``skips``
    are arcs the playbook *saw* through the sweep and the shift but then refused
    by its own filters (SL budget, no sane target, no displacement) — recorded,
    never hidden, because "every setup, win or lose" includes the ones the book
    tells you to leave alone.

    The pool is the sliding extreme of the previous ``DONCH`` bars; one setup
    per raid — a near-same pool price stays cooldown for ``POOL_COOLDOWN`` bars.
    """
    high = [float(v) for v in df["high"]]
    low = [float(v) for v in df["low"]]
    close = [float(v) for v in df["close"]]
    open_ = [float(v) for v in df["open"]]
    atr = _atr(df)
    pivots = find_pivots(high, low, PIVOT_LENGTH)
    n = len(df)

    since_ts = _aware(since)
    until_ts = _aware(until)
    start_bar = max(DONCH, _bar_of(df, since_ts, default=0))
    end_bar = min(n - 1, _bar_of(df, until_ts, default=n - 1))
    tf_ns = tf_seconds(timeframe)

    last_activation: Dict[float, int] = {}  # rounded pool price -> last sweep bar
    last_arc: Dict[str, int] = {}           # direction -> last collected arc bar
    out: List[AlchemistCandidate] = []
    skips: List[Dict[str, Any]] = []
    seen_keys: set = set()

    for j in range(start_bar, end_bar + 1):
        # ---- sweep UP of the standing high container -> bearish arc -------- #
        run_hi = max(high[j - DONCH:j])
        if high[j] > run_hi and close[j] < run_hi:
            key = round(run_hi, 1)
            fresh = last_activation.get(key, j - POOL_COOLDOWN)
            if j - fresh >= POOL_COOLDOWN and j - last_arc.get("bearish", j - ARC_COOLDOWN) >= ARC_COOLDOWN:
                last_activation[key] = j
                candidate = _arc_bearish(
                    df, high, low, close, open_, atr, pivots, j, run_hi, timeframe, tf_ns
                )
                if candidate is not None:
                    last_arc["bearish"] = j
                    _maybe_collect(candidate, seen_keys, out)
                else:
                    reason = _skip_reason(
                        df, high, low, close, open_, atr, pivots, j, run_hi, "bearish"
                    )
                    if reason:
                        skips.append({
                            "time": pd.Timestamp(df.index[j]).isoformat(),
                            "direction": "bearish",
                            "pool_price": round(run_hi, 3),
                            "reason": reason,
                        })

        # ---- sweep DOWN of the standing low container -> bullish arc ------- #
        run_lo = min(low[j - DONCH:j])
        if low[j] < run_lo and close[j] > run_lo:
            key = round(run_lo, 1)
            fresh = last_activation.get(key, j - POOL_COOLDOWN)
            if j - fresh >= POOL_COOLDOWN and j - last_arc.get("bullish", j - ARC_COOLDOWN) >= ARC_COOLDOWN:
                last_activation[key] = j
                candidate = _arc_bullish(
                    df, high, low, close, open_, atr, pivots, j, run_lo, timeframe, tf_ns
                )
                if candidate is not None:
                    last_arc["bullish"] = j
                    _maybe_collect(candidate, seen_keys, out)
                else:
                    reason = _skip_reason(
                        df, high, low, close, open_, atr, pivots, j, run_lo, "bullish"
                    )
                    if reason:
                        skips.append({
                            "time": pd.Timestamp(df.index[j]).isoformat(),
                            "direction": "bullish",
                            "pool_price": round(run_lo, 3),
                            "reason": reason,
                        })
    return out, skips


def _skip_reason(
    df: pd.DataFrame,
    high: List[float],
    low: List[float],
    close: List[float],
    open_: List[float],
    atr: List[float],
    pivots: List[Pivot],
    j: int,
    pool_price: float,
    direction: str,
) -> Optional[str]:
    """Why an arc that reached the shift never became a placeable trade."""
    bearish = direction == "bearish"
    extremes_low, extremes_high = (low, high) if bearish else (high, low)
    pit = min(low[j - PIT_WINDOW:j]) if bearish else max(high[j - PIT_WINDOW:j])
    shift = -1
    for m in range(j, min(j + SHIFT_WINDOW, len(df) - 1) + 1):
        if bearish and close[m] > pool_price:
            return None   # breakout — not a skip, just a dead raid
        if not bearish and close[m] < pool_price:
            return None
        if ((bearish and close[m] < pit) or (not bearish and close[m] > pit)) and m > j:
            shift = m
            break
    if shift < 0:
        return None       # the raid was waived off — no shift, nothing owed
    sweep_extreme = max(high[j:shift + 1]) if bearish else min(low[j:shift + 1])
    post_extreme = min(low[shift:shift + POST_WINDOW + 1]) if bearish else max(high[shift:shift + POST_WINDOW + 1])
    if (bearish and post_extreme >= pool_price) or (not bearish and post_extreme <= pool_price):
        return "no_displacement"
    rng = abs(sweep_extreme - post_extreme)
    if rng <= 0:
        return "no_displacement"
    mid50 = (sweep_extreme + post_extreme) / 2.0
    ob50 = _turn_ob50(high, low, open_, close, j, shift, bearish)
    inside = [c for c in (mid50, ob50) if c is not None
              and min(sweep_extreme, post_extreme) < c < max(sweep_extreme, post_extreme)]
    if not inside:
        return "no_valid_poi"
    poi = min(inside) if bearish else max(inside)
    buffer = STOP_BUFFER_ATR * float(atr[j] or 0.0)
    risk = (sweep_extreme + buffer - poi) if bearish else (poi - (sweep_extreme - buffer))
    if risk < SL_FLOOR:
        return "stop_too_tight"
    if risk > SL_CEILING:
        return f"sl_budget ({risk / 0.1:.0f} pips > {SL_CEILING / 0.1:.0f})"
    target = _opposing_target(
        pivots, poi, "low" if bearish else "high", j, atr[j]
    )
    if target is None:
        target = post_extreme
    reward = (poi - target) if bearish else (target - poi)
    if not (0.0 < reward):
        return "no_sane_target"
    rr = reward / risk
    if rr < RR_FLOOR:
        return f"rr_floor ({rr:.2f} < {RR_FLOOR})"
    return None


def _arc_bearish(
    df: pd.DataFrame,
    high: List[float],
    low: List[float],
    close: List[float],
    open_: List[float],
    atr: List[float],
    pivots: List[Pivot],
    j: int,
    pool_price: float,
    timeframe: str,
    tf_ns: int,
) -> Optional[AlchemistCandidate]:
    """High-sweep arc: shift = a body close below the raid's launch pit — the
    pullback low the raid launched from, i.e. "the swing that preceded the
    sweep" (a just-printed pit needs no pivot confirmation)."""
    pit = min(low[j - PIT_WINDOW:j])
    shift = -1
    for m in range(j, min(j + SHIFT_WINDOW, len(df) - 1) + 1):
        if close[m] > pool_price:
            return None  # the raid drove on and closed above: breakout, arc dead
        if close[m] < pit and m > j:
            shift = m
            break
    if shift < 0:
        return None
    sweep_extreme = max(high[j:shift + 1])
    post_extreme = min(low[shift:shift + POST_WINDOW + 1])
    if post_extreme >= pool_price:
        return None  # the "shift" never displaced: no range to ride
    return _build_candidate(
        df, high, low, open_, close, atr, pivots, j, pool_price, sweep_extreme,
        post_extreme, shift, "bearish", timeframe, tf_ns,
    )


def _arc_bullish(
    df: pd.DataFrame,
    high: List[float],
    low: List[float],
    close: List[float],
    open_: List[float],
    atr: List[float],
    pivots: List[Pivot],
    j: int,
    pool_price: float,
    timeframe: str,
    tf_ns: int,
) -> Optional[AlchemistCandidate]:
    """Low-sweep arc: shift = a body close above the raid's launch pit."""
    pit = max(high[j - PIT_WINDOW:j])
    shift = -1
    for m in range(j, min(j + SHIFT_WINDOW, len(df) - 1) + 1):
        if close[m] < pool_price:
            return None
        if close[m] > pit and m > j:
            shift = m
            break
    if shift < 0:
        return None
    sweep_extreme = min(low[j:shift + 1])
    post_extreme = max(high[shift:shift + POST_WINDOW + 1])
    if post_extreme <= pool_price:
        return None
    return _build_candidate(
        df, high, low, open_, close, atr, pivots, j, pool_price, sweep_extreme,
        post_extreme, shift, "bullish", timeframe, tf_ns,
    )


def _build_candidate(
    df: pd.DataFrame,
    high: List[float],
    low: List[float],
    open_: List[float],
    close: List[float],
    atr: List[float],
    pivots: List[Pivot],
    sweep_i: int,
    pool_price: float,
    sweep_extreme: float,
    post_extreme: float,
    shift_i: int,
    direction: str,
    timeframe: str,
    tf_ns: int,
) -> Optional[AlchemistCandidate]:
    """Price the arc as the playbook's limit: POI / wick-tip stop / pre-raid swing target."""
    bearish = direction == "bearish"
    rng = abs(sweep_extreme - post_extreme)
    if rng <= 0:
        return None
    mid50 = (sweep_extreme + post_extreme) / 2.0
    ob50 = _turn_ob50(high, low, open_, close, sweep_i, shift_i, bearish)

    interior_lo = min(sweep_extreme, post_extreme)
    interior_hi = max(sweep_extreme, post_extreme)
    inside = [c for c in (mid50, ob50) if c is not None and interior_lo < c < interior_hi]
    if not inside:
        return None
    # "Nearest to price": at the decision instant price sits just past the shift,
    # inside the discount (bearish) / premium (bullish). The retracement climbs
    # (bearish) through premium, so the FIRST resting edge it meets is the
    # lowest (bearish) / highest (bullish) candidate — the proximal OB edge.
    poi_price = min(inside) if bearish else max(inside)
    poi_kind = "ob50" if ob50 is not None and poi_price == ob50 else "mid50"

    buffer = STOP_BUFFER_ATR * float(atr[sweep_i] or 0.0)
    if bearish:
        stop = sweep_extreme + buffer
        risk = stop - poi_price
        target = _opposing_target(pivots, poi_price, "low", sweep_i, atr[sweep_i])
        target_kind = "swing" if target is not None else "post_extreme"
        if target is None:
            target = post_extreme
        reward = poi_price - target
    else:
        stop = sweep_extreme - buffer
        risk = poi_price - stop
        target = _opposing_target(pivots, poi_price, "high", sweep_i, atr[sweep_i])
        target_kind = "swing" if target is not None else "post_extreme"
        if target is None:
            target = post_extreme
        reward = target - poi_price
    if risk < SL_FLOOR or risk > SL_CEILING:
        return None
    if not (0.0 < reward <= risk * 10.0):
        return None
    rr = reward / risk

    decision = df.index[shift_i] + pd.Timedelta(seconds=tf_ns)
    return AlchemistCandidate(
        timeframe=timeframe.upper(),
        direction=direction,
        pool_price=round(pool_price, 3),
        sweep_extreme=round(sweep_extreme, 3),
        post_extreme=round(post_extreme, 3),
        range_size=round(rng, 3),
        range_mid=round(mid50, 3),
        poi_price=round(poi_price, 3),
        poi_kind=poi_kind,
        entry=round(poi_price, 3),
        stop=round(stop, 3),
        target=round(target, 3),
        target_kind=target_kind,
        risk=round(risk, 3),
        reward=round(reward, 3),
        rr=round(rr, 3),
        stop_distance_pips=round(risk * 10.0, 1),
        sweep_index=int(sweep_i),
        shift_index=int(shift_i),
        sweep_time=pd.Timestamp(df.index[sweep_i]).isoformat(),
        shift_time=pd.Timestamp(df.index[shift_i]).isoformat(),
        decision_time=pd.Timestamp(decision).isoformat(),
        manipulation_index=int(shift_i),
    )


def _turn_ob50(
    high: List[float],
    low: List[float],
    open_: List[float],
    close: List[float],
    sweep_i: int,
    shift_i: int,
    bearish: bool,
) -> Optional[float]:
    """OB50 of the turn: the last opposite-colour candle at/before the sweep
    extreme — the body of the candle the displacement launched from. Alchemist
    places the limit at *that* OB, near the wick, not deep in the range."""
    if bearish:
        seg = high[sweep_i:shift_i + 1]
        extreme_i = sweep_i + seg.index(max(seg))
    else:
        seg = low[sweep_i:shift_i + 1]
        extreme_i = sweep_i + seg.index(min(seg))
    for k in range(extreme_i, sweep_i - 1, -1):
        up = close[k] > open_[k]
        if (up and bearish) or (not up and not bearish):
            top = max(open_[k], close[k])
            bot = min(open_[k], close[k])
            return (top + bot) / 2.0
    return None


def _opposing_target(
    pivots: List[Pivot], entry: float, kind: str, before: int, atr: float
) -> Optional[float]:
    """The nearest opposing swing **established before the raid** (index < before),
    at least ``TARGET_MIN_ATR`` from the entry — the stair of SSLs/BSLs the raid
    left behind. ``None`` when no sane target exists (no reason to trade)."""
    floor = TARGET_MIN_ATR * float(atr or 0.0)
    best: Optional[float] = None
    for pivot in pivots:
        if pivot.kind != kind or pivot.index + PIVOT_LENGTH > before:
            continue
        if kind == "low":
            if pivot.price < entry - floor and (best is None or pivot.price > best):
                best = pivot.price
        else:
            if pivot.price > entry + floor and (best is None or pivot.price < best):
                best = pivot.price
    return best


def _maybe_collect(
    candidate: Optional[AlchemistCandidate],
    seen_keys: set,
    out: List[AlchemistCandidate],
) -> None:
    """Dedupe (one setup per sweep extreme) and keep every candidate — win or lose."""
    if candidate is None:
        return
    key = (candidate.direction, candidate.pool_price, candidate.sweep_index)
    if key in seen_keys:
        return
    seen_keys.add(key)
    out.append(candidate)


def _last_confirmed(pivots: List[Pivot], kind: str, at: int, length: int) -> Optional[Pivot]:
    """The newest ``kind`` pivot whose right-side confirmation closed by ``at``."""
    for pivot in reversed(pivots):
        if pivot.kind == kind and pivot.index + length <= at:
            return pivot
    return None


def _atr(df: pd.DataFrame, period: int = 14) -> List[float]:
    """Wilder ATR aligned to df rows (same rule the endpoint reports)."""
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean().tolist()


def _aware(value: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts


def _bar_of(df: pd.DataFrame, ts: Optional[pd.Timestamp], *, default: int) -> int:
    aware = _aware(ts)
    if aware is None:
        return default
    idx = df.index.searchsorted(aware, side="left")
    return int(min(idx, len(df) - 1))
