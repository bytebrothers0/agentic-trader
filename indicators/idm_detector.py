"""
idm_detector.py — Inducement (IDM) indicator, BOS-anchored.

Inducement is the *internal pullback* inside an impulse leg: the "higher low"
(bullish) / "lower high" (bearish) that price has to sweep before the leg
continues. It only means something **after a structural break** (BOS/CHoCH),
so the detector anchors on ``BOSDetector`` events and reports the last minor
fractal swing inside the leg that produced the break.

Why the rewrite
---------------
The previous version treated *every* bar as "reference candle 1" and required a
pullback + continuation around it. That labels essentially every push/pull on
the chart — the "maps every high/low/wick" noise. Anchoring on structure and
emitting **one IDM per BOS** (deduped, capped per side) keeps only the levels
that actually matter.

Rules
-----
Bullish BOS at ``break_index``:
  - origin = the last minor pivot low before the broken swing high;
  - IDM = the most recent minor pivot low between the origin and the break bar
    that sits *above* the origin (a genuine higher low);
  - no internal pullback (pure displacement) -> no IDM.
Bearish BOS mirrors (a lower high below the origin high).

Sweep (unchanged): the first bar after the break whose wick crosses the IDM
and whose body closes back inside. A body close through is a break, not a
sweep — the IDM is invalidated (``broken``). Swept IDMs render faded; broken
ones render as thin gray "history" like the other detectors.

Two families
------------
The detector emits inducement from two independent sources, both tagged on
``IDMLevel.rule`` so the chart can tell them apart:

* ``"bos"`` — the BOS-anchored pullback described above (unchanged).
* ``"two_candle"`` — the Luap "True SMC" valid-pullback rule (Part 1 + Part 3),
  implemented by :class:`LuapIDMDetector`. A pullback only counts once a candle
  takes the liquidity (wick *or* body) of the candle that ended the impulse —
  i.e. the low/high of the previous Highest-High / Lowest-Low candle. It is
  added *alongside* the BOS family, not in place of it.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

from indicators.bos_detector import BOSDetector, BOSDirection
from indicators.swings import Pivot, find_pivots


class IDMType(Enum):
    IDM_LOW = "idm_low"    # bullish-leg inducement (low to be swept)
    IDM_HIGH = "idm_high"  # bearish-leg inducement (high to be swept)


class IDMDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class IDMLevel:
    """A single Inducement level (BOS-anchored or two-candle pullback)."""

    idm_type: IDMType
    direction: IDMDirection
    price: float                            # pullback extreme (low or high)
    formation_index: int                    # iloc of the pullback swing bar
    candle_time: pd.Timestamp
    swept: bool = False
    sweep_index: Optional[int] = None
    broken: bool = False                    # body closed through (invalidated)
    broken_index: Optional[int] = None
    bos_price: Optional[float] = None       # structural level that broke
    bos_break_index: Optional[int] = None   # iloc of the break bar
    bos_kind: str = ""                      # BOS / CHoCH / I-BOS / I-CHOCH
    rule: str = "bos"                       # "bos" | "two_candle"
    confirm_index: Optional[int] = None     # two-candle: bar that made the new HH/LL
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        if self.swept:
            state = f"swept@{self.sweep_index}"
        elif self.broken:
            state = f"broken@{self.broken_index}"
        else:
            state = "active"
        origin = self.bos_kind or ("2-candle" if self.rule == "two_candle" else "BOS")
        return (
            f"IDMLevel({self.idm_type.value} @ {self.price:.5f} "
            f"[idx={self.formation_index}] {origin} {state})"
        )


class IDMDetector:
    """
    BOS-anchored inducement detector.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe (open/high/low/close) with a DatetimeIndex.
    swing_length : int
        Fractal window for the *internal* pullback swing. Default 2.
    bos_swing_length : int
        External (major) BOS sensitivity, in bars. Default 25.
    bos_internal_length : int
        Internal (minor) BOS sensitivity, in bars. Default 3.
    show_internal : bool
        Also anchor on internal (I-BOS / I-CHOCH) breaks. Default True.
    swing_tol_atr : float
        Same-level tolerance for BOS swings (fraction of ATR). Default 0.05.
    max_per_side : int
        Keep at most this many IDMs per direction (newest, unswept first).
    atr_period : int
        ATR lookback for the BOS tolerance band. Default 14.
    two_candle_rule : bool
        Also emit Luap "True SMC" valid-pullback IDMs (``rule="two_candle"``)
        alongside the BOS-anchored ones. Default True.
    ref_candle_rule : bool
        Also emit Luap reference-candle ("candle 1") IDMs (``rule="ref_candle"``),
        gated by the prevailing structure direction. Default True.
    ref_candle_max_bars : int
        Continuation look-ahead for the reference-candle family. Default 500.
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 2,
                 bos_swing_length: int = 25, bos_internal_length: int = 3,
                 show_internal: bool = True, swing_tol_atr: float = 0.05,
                 max_per_side: int = 3, atr_period: int = 14,
                 two_candle_rule: bool = True, ref_candle_rule: bool = True,
                 ref_candle_max_bars: int = 500):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = max(1, int(swing_length))
        self.bos_swing_length = bos_swing_length
        self.bos_internal_length = bos_internal_length
        self.show_internal = show_internal
        self.swing_tol_atr = swing_tol_atr
        self.max_per_side = max(1, int(max_per_side))
        self.atr_period = atr_period
        self.two_candle_rule = bool(two_candle_rule)
        self.ref_candle_rule = bool(ref_candle_rule)
        self.ref_candle_max_bars = max(1, int(ref_candle_max_bars))
        self._levels: List[IDMLevel] = []

    def detect_all(self) -> List[IDMLevel]:
        self._levels = []
        h = self.df["high"].values
        l = self.df["low"].values
        o = self.df["open"].values
        c = self.df["close"].values

        pivots = find_pivots(h, l, self.swing_length)
        pivot_lows = [p for p in pivots if p.is_low]
        pivot_highs = [p for p in pivots if p.is_high]

        bos = BOSDetector(
            self.df,
            swing_length=self.bos_swing_length,
            internal_length=self.bos_internal_length,
            show_internal=self.show_internal,
            swing_tol_atr=self.swing_tol_atr,
            atr_period=self.atr_period,
        ).detect_all()

        for bo in bos:
            if bo.direction == BOSDirection.BULLISH:
                self._anchor_bullish(bo, pivot_lows, l, o, c)
            else:
                self._anchor_bearish(bo, pivot_highs, h, o, c)

        _cap_per_side(self._levels, self.max_per_side)

        # Other families are added only where they mark a pullback the families
        # already present did not (same type + same pullback bar).
        keys = {(lv.idm_type, lv.formation_index) for lv in self._levels}
        if self.two_candle_rule:
            for lv in LuapIDMDetector(
                    self.df, max_per_side=self.max_per_side).detect_all():
                if (lv.idm_type, lv.formation_index) in keys:
                    continue
                self._levels.append(lv)
                keys.add((lv.idm_type, lv.formation_index))
        if self.ref_candle_rule:
            for lv in RefCandleIDMDetector(
                    self.df, max_per_side=self.max_per_side,
                    max_bars=self.ref_candle_max_bars,
                    bos_swing_length=self.bos_swing_length,
                    bos_internal_length=self.bos_internal_length,
                    show_internal=self.show_internal,
                    swing_tol_atr=self.swing_tol_atr,
                    atr_period=self.atr_period).detect_all():
                if (lv.idm_type, lv.formation_index) in keys:
                    continue
                self._levels.append(lv)
                keys.add((lv.idm_type, lv.formation_index))

        self._levels.sort(key=lambda lv: lv.formation_index)
        return self._levels

    # ------------------------------------------------------------------
    # Bullish: higher low inside the up-leg that broke structure.
    # ------------------------------------------------------------------
    def _anchor_bullish(self, bo, pivot_lows: Sequence[Pivot],
                        l, o, c) -> None:
        origin = None
        for p in pivot_lows:                       # index-sorted
            if p.index < bo.extreme_index:
                origin = p
            else:
                break
        if origin is None:
            return

        pull = None
        for p in pivot_lows:
            if origin.index < p.index < bo.break_index and p.price > origin.price:
                pull = p                              # keep the newest
        if pull is None:
            return

        sweep, broken = self._resolve_low(pull.price, bo.break_index, l, o, c)
        self._add(IDMType.IDM_LOW, IDMDirection.BULLISH, pull, sweep, broken,
                  [origin.index, pull.index, bo.break_index], bo)

    # ------------------------------------------------------------------
    # Bearish: lower high inside the down-leg that broke structure.
    # ------------------------------------------------------------------
    def _anchor_bearish(self, bo, pivot_highs: Sequence[Pivot],
                        h, o, c) -> None:
        origin = None
        for p in pivot_highs:
            if p.index < bo.extreme_index:
                origin = p
            else:
                break
        if origin is None:
            return

        pull = None
        for p in pivot_highs:
            if origin.index < p.index < bo.break_index and p.price < origin.price:
                pull = p                              # keep the newest
        if pull is None:
            return

        sweep, broken = self._resolve_high(pull.price, bo.break_index, h, o, c)
        self._add(IDMType.IDM_HIGH, IDMDirection.BEARISH, pull, sweep, broken,
                  [origin.index, pull.index, bo.break_index], bo)

    @staticmethod
    def _resolve_low(price: float, from_i: int, l, o, c):
        """First post-break event for a bullish IDM: sweep or body break.

        Returns ``(sweep_index, broken_index)`` — at most one is set.
        """
        for m in range(from_i + 1, len(l)):
            if l[m] < price:
                if min(o[m], c[m]) > price:
                    return m, None          # wick through, body back inside
                return None, m              # body closed through -> invalidated
        return None, None

    @staticmethod
    def _resolve_high(price: float, from_i: int, h, o, c):
        """First post-break event for a bearish IDM: sweep or body break."""
        for m in range(from_i + 1, len(h)):
            if h[m] > price:
                if max(o[m], c[m]) < price:
                    return m, None
                return None, m
        return None, None

    def _add(self, idm_type: IDMType, direction: IDMDirection, pull: Pivot,
             sweep: Optional[int], broken: Optional[int],
             forming: List[int], bo) -> None:
        for lv in self._levels:
            if (lv.idm_type == idm_type and lv.price == pull.price
                    and lv.formation_index == pull.index):
                # Same swing seen by another BOS anchor; keep one ray but
                # upgrade the state if this anchor resolved a sweep/break.
                if lv.sweep_index is None and lv.broken_index is None:
                    if sweep is not None:
                        lv.swept, lv.sweep_index = True, sweep
                    elif broken is not None:
                        lv.broken, lv.broken_index = True, broken
                return
        self._levels.append(IDMLevel(
            idm_type=idm_type,
            direction=direction,
            price=float(pull.price),
            formation_index=pull.index,
            candle_time=self.df.index[pull.index],
            swept=sweep is not None,
            sweep_index=sweep,
            broken=broken is not None,
            broken_index=broken,
            bos_price=float(bo.price),
            bos_break_index=bo.break_index,
            bos_kind=bo.kind,
            forming_candle_indices=list(forming)
            + [x for x in (sweep, broken) if x is not None],
        ))

    @property
    def levels(self) -> List[IDMLevel]:
        return self._levels

    @staticmethod
    def _validate(df: pd.DataFrame):
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame index must be a DatetimeIndex.")
        if df.empty:
            raise ValueError("DataFrame is empty.")


def _cap_per_side(levels: List[IDMLevel], max_per_side: int) -> None:
    """Keep the newest ``max_per_side`` levels per direction (in place).

    Live levels (not swept and not broken) are kept first; among equals the
    newest (highest ``formation_index``) wins.
    """
    for d in (IDMDirection.BULLISH, IDMDirection.BEARISH):
        group = [lv for lv in levels if lv.direction == d]
        if len(group) <= max_per_side:
            continue
        group.sort(key=lambda lv: (lv.swept or lv.broken, -lv.formation_index))
        drop = {id(lv) for lv in group[max_per_side:]}
        levels[:] = [lv for lv in levels if id(lv) not in drop]


class LuapIDMDetector:
    """
    Luap "True SMC" valid-pullback inducement (Part 1 + Part 3).

    A pullback is only *valid* once a candle takes the liquidity of the candle
    that ended the impulse — the low (bullish) / high (bearish) of the
    **Target Candle**, i.e. the candle that made the current Highest High
    (bullish) / Lowest Low (bearish). The take counts on a wick *or* a body,
    colour irrelevant. A pullback that never takes that liquidity is not a
    structure point, so it is not inducement.

    The extreme of the most recent valid pullback becomes the **IDM**. When
    price makes a *new* extreme without taking the IDM, the IDM **shifts** to
    the newer pullback (the older unswept one is dropped). Inside bars are
    non-events and ignored (Part 1 rule 3).

    Resolution (Part 8, "IDM Sweep Entry Module"): a candle that **wicks**
    through the IDM and **closes back inside** is a *sweep* (``swept``); a
    candle whose **body closes through** the level is not a sweep — it cancels
    the setup (``broken``), rendered as thin gray history like the other
    detectors.

    This is a state machine — one running Target Candle per leg — so it stays
    clean instead of labelling a pullback around every bar.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with a DatetimeIndex.
    max_per_side : int
        Keep at most this many levels per direction (newest, live first).
    ignore_inside_bars : bool
        Skip candles fully inside the previous candle. Default True.
    """

    def __init__(self, df: pd.DataFrame, max_per_side: int = 3,
                 ignore_inside_bars: bool = True):
        IDMDetector._validate(df)
        self.df = df.copy()
        self.max_per_side = max(1, int(max_per_side))
        self.ignore_inside_bars = bool(ignore_inside_bars)
        self._levels: List[IDMLevel] = []

    def detect_all(self) -> List[IDMLevel]:
        self._levels = []
        h = self.df["high"].values
        l = self.df["low"].values
        o = self.df["open"].values
        c = self.df["close"].values

        self._scan(h, l, o, c, bullish=True)
        self._scan(h, l, o, c, bullish=False)

        # Drop any duplicate (same price + same pullback bar) from shifting.
        seen = set()
        unique: List[IDMLevel] = []
        for lv in self._levels:
            key = (lv.idm_type, lv.price, lv.formation_index)
            if key in seen:
                continue
            seen.add(key)
            unique.append(lv)
        self._levels = unique

        _cap_per_side(self._levels, self.max_per_side)
        self._levels.sort(key=lambda lv: lv.formation_index)
        return self._levels

    def _scan(self, h, l, o, c, bullish: bool) -> None:
        n = len(h)
        if n < 3:
            return
        idm_type = IDMType.IDM_LOW if bullish else IDMType.IDM_HIGH
        direction = IDMDirection.BULLISH if bullish else IDMDirection.BEARISH

        t_high = float(h[0])          # Target Candle = current HH
        t_low = float(l[0])
        pb_price = None               # running extreme of the valid pullback
        pb_idx = None
        active = None                 # confirmed IDM awaiting a take

        for i in range(1, n):
            if (self.ignore_inside_bars
                    and h[i] <= h[i - 1] and l[i] >= l[i - 1]):
                continue

            # 1) Has the live IDM been resolved? (Part 8)
            #    wick through + body back inside -> sweep; body through -> break.
            if active is not None:
                if bullish:
                    if l[i] < active["price"]:
                        if min(o[i], c[i]) > active["price"]:
                            self._emit(idm_type, direction, active, i, None)
                        else:
                            self._emit(idm_type, direction, active, None, i)
                        active = None
                else:
                    if h[i] > active["price"]:
                        if max(o[i], c[i]) < active["price"]:
                            self._emit(idm_type, direction, active, i, None)
                        else:
                            self._emit(idm_type, direction, active, None, i)
                        active = None

            new_extreme = (h[i] > t_high) if bullish else (l[i] < t_low)
            broke = (l[i] < t_low) if bullish else (h[i] > t_high)

            if new_extreme:
                # Impulse resumed: the completed pullback's extreme is the IDM.
                # A newer pullback *shifts* the IDM (older unswept one drops).
                if pb_price is not None:
                    active = {"price": pb_price, "index": pb_idx, "confirm": i}
                t_high, t_low = float(h[i]), float(l[i])
                pb_price, pb_idx = None, None
                continue

            if broke:
                # Valid pullback confirmed: track its extreme.
                if bullish:
                    if pb_price is None or l[i] < pb_price:
                        pb_price, pb_idx = float(l[i]), i
                else:
                    if pb_price is None or h[i] > pb_price:
                        pb_price, pb_idx = float(h[i]), i

        # The live (unswept, unbroken) IDM, if the leg ran out of data.
        if active is not None:
            self._emit(idm_type, direction, active, None, None)

    def _emit(self, idm_type: IDMType, direction: IDMDirection,
              active: dict, sweep: Optional[int],
              broken: Optional[int]) -> None:
        idx = active["index"]
        self._levels.append(IDMLevel(
            idm_type=idm_type,
            direction=direction,
            price=float(active["price"]),
            formation_index=idx,
            candle_time=self.df.index[idx],
            swept=sweep is not None,
            sweep_index=sweep,
            broken=broken is not None,
            broken_index=broken,
            rule="two_candle",
            confirm_index=active.get("confirm"),
            forming_candle_indices=[x for x in
                                    (idx, active.get("confirm"), sweep, broken)
                                    if x is not None],
        ))


def _structure_direction(n: int, bos_levels) -> List[Optional[BOSDirection]]:
    """Per-bar prevailing structure direction from the last break (BOS/CHoCH).

    ``dirs[i]`` is the direction of the most recent break at or before bar ``i``
    — up for BOS / I-BOS / CHoCH / I-CHOCH to the upside, down otherwise — or
    ``None`` before the first break seen.
    """
    events = sorted((b.break_index, b.direction) for b in bos_levels
                    if b.break_index is not None)
    dirs: List[Optional[BOSDirection]] = [None] * n
    cur: Optional[BOSDirection] = None
    e = 0
    for i in range(n):
        while e < len(events) and events[e][0] <= i:
            cur = events[e][1]
            e += 1
        dirs[i] = cur
    return dirs


class RefCandleIDMDetector:
    """
    Luap reference-candle ("candle 1") inducement, structure-gated.

    Every candle can be the reference candle ("candle 1"): its high/low define a
    range. In an **upside** structure a later candle taking candle 1's LOW arms
    the pullback, and a later candle taking candle 1's HIGH completes it — the
    **lowest low** of that pullback series is the IDM. In a **downside**
    structure the mirror holds: candle 1's HIGH is taken, then its LOW, and the
    **highest high** of the pullback series is the IDM.

    The gate is the direction of the leg the pullback belongs to, read at the
    **continuation** bar — the break the IDM precipitates. That matters: candle 1
    lies *before* its break, so reading the structure there would miss every
    pullback that precedes a break (i.e. every CHoCH / reversal, and the first
    break in view). Reading it at the continuation ties each IDM to the break it
    fed, which is what "follows the leg or trend" means.

    Candle 1 need not be a swing point, so this catches the smaller intra-leg
    pullbacks the two-candle family skips. Out: `swept` (wick through, body back
    inside) / `broken` (body close through) / active, per Part 8.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with a DatetimeIndex.
    max_per_side : int
        Keep at most this many levels per direction (newest, live first).
    max_bars : int
        Give up looking for candle 1's continuation after this many bars.
    bos_swing_length, bos_internal_length, show_internal, swing_tol_atr,
    atr_period :
        Passed to ``BOSDetector`` for the structure gate (keep in step with the
        IDM detector's own BOS settings).
    """

    def __init__(self, df: pd.DataFrame, max_per_side: int = 3,
                 max_bars: int = 500, bos_swing_length: int = 25,
                 bos_internal_length: int = 3, show_internal: bool = True,
                 swing_tol_atr: float = 0.05, atr_period: int = 14):
        IDMDetector._validate(df)
        self.df = df.copy()
        self.max_per_side = max(1, int(max_per_side))
        self.max_bars = max(1, int(max_bars))
        self.bos_swing_length = bos_swing_length
        self.bos_internal_length = bos_internal_length
        self.show_internal = show_internal
        self.swing_tol_atr = swing_tol_atr
        self.atr_period = atr_period
        self._levels: List[IDMLevel] = []

    def detect_all(self) -> List[IDMLevel]:
        self._levels = []
        h = self.df["high"].values
        l = self.df["low"].values
        o = self.df["open"].values
        c = self.df["close"].values
        n = len(h)
        if n < 3:
            return self._levels

        bos = BOSDetector(
            self.df,
            swing_length=self.bos_swing_length,
            internal_length=self.bos_internal_length,
            show_internal=self.show_internal,
            swing_tol_atr=self.swing_tol_atr,
            atr_period=self.atr_period,
        ).detect_all()
        dirs = _structure_direction(n, bos)

        # key -> the best resolution seen for that exact IDM
        best: dict = {}

        def keep(bullish, idx, price, sweep, broken, ref):
            key = (bullish, idx, price)
            prev = best.get(key)
            if prev is None or self._earlier(sweep, broken, prev[0], prev[1]):
                best[key] = (sweep, broken, ref)

        for i in range(n):
            hi, lo = float(h[i]), float(l[i])
            end = min(n, i + 1 + self.max_bars)

            # Upside leg: take candle 1's LOW, then its HIGH, on an up-break.
            j = next((m for m in range(i + 1, end) if l[m] < lo), None)
            if j is not None:
                k = next((m for m in range(j, end) if h[m] > hi), None)
                if k is not None and dirs[k] == BOSDirection.BULLISH:
                    window = l[j:k + 1]
                    idx = j + int(window.argmin())
                    price = float(l[idx])
                    sweep, broken = IDMDetector._resolve_low(price, k, l, o, c)
                    keep(True, idx, price, sweep, broken, i)

            # Downside leg: take candle 1's HIGH, then its LOW, on a down-break.
            j = next((m for m in range(i + 1, end) if h[m] > hi), None)
            if j is not None:
                k = next((m for m in range(j, end) if l[m] < lo), None)
                if k is not None and dirs[k] == BOSDirection.BEARISH:
                    window = h[j:k + 1]
                    idx = j + int(window.argmax())
                    price = float(h[idx])
                    sweep, broken = IDMDetector._resolve_high(price, k, h, o, c)
                    keep(False, idx, price, sweep, broken, i)

        for (bullish, idx, price), (sweep, broken, ref) in sorted(
                best.items(), key=lambda kv: kv[0][1]):
            idm_type = IDMType.IDM_LOW if bullish else IDMType.IDM_HIGH
            direction = (IDMDirection.BULLISH if bullish
                         else IDMDirection.BEARISH)
            self._levels.append(IDMLevel(
                idm_type=idm_type,
                direction=direction,
                price=price,
                formation_index=idx,
                candle_time=self.df.index[idx],
                swept=sweep is not None,
                sweep_index=sweep,
                broken=broken is not None,
                broken_index=broken,
                rule="ref_candle",
                confirm_index=ref,
                forming_candle_indices=[x for x in (idx, ref, sweep, broken)
                                        if x is not None],
            ))

        _cap_per_side(self._levels, self.max_per_side)
        self._levels.sort(key=lambda lv: lv.formation_index)
        return self._levels

    @staticmethod
    def _earlier(sweep_a, broken_a, sweep_b, broken_b) -> bool:
        """True when A resolves at least as early as B (resolved beats not)."""
        a = sweep_a if sweep_a is not None else broken_a
        b = sweep_b if sweep_b is not None else broken_b
        if a is None:
            return False
        if b is None:
            return True
        return a < b
