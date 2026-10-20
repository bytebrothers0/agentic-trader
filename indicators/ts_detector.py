"""
ts_detector.py — Turtle Soup (TS) indicator — full variant taxonomy.

The anchor candle is the RANGE (CRH = its high, CRL = its low; the liquidity
pool). A later candle within the TS_MAX_BETWEEN window sweeps one boundary
(strict breach) and its BODY closes back inside — that manipulation candle is
the Turtle Soup. A body close THROUGH the boundary instead is a real breakout:
the side dies and no level is born from it.

Variants (spec: docs/specs/2026-10-20-ts-variant-taxonomy-design.md) — the
structure of the bars between the anchor and the sweep candle fully determines
them:

  TWO_CANDLE           k=1 and the sweep candle itself reaches the OPPOSITE
                       boundary (it manipulates AND delivers) — volatility.
  CLASSIC              k=1, no same-bar delivery — the textbook 3-candle form
                       at the manipulation candle (distribution follows).
  INSIDE_BAR           k=2 and the single in-between bar is an inside bar of
                       the anchor (touching the boundary is still inside; only
                       a strict exceed sweeps).
  MULTIPLE_INSIDE_BAR  k>=3 and EVERY in-between bar is an inside bar — the
                       highest-probability accumulation (liquidity banked).
  MULTIPLE_CANDLE      k>=2 with non-inside bars between (pullback windows).

Discipline
----------
- One signal per (anchor, side): the EARLIEST valid sweep in the window wins;
  a first breach that body-closes through kills the side for that anchor.
- Both boundaries in one candle = one event: the DEEPER raid wins; an exact
  tie keeps both (documented legacy behaviour).
- Invalidation is terminal and has NO window: any later close through the
  swept boundary marks the level INVALIDATED; wick-only re-pokes never count.
- Colour-independent: dojis sweep (body edges count).

The anchor's swept-side wick gates (`min_wick_body_frac`/`min_wick_range_frac`)
stay opt-in display filters exactly as before (defaults 0.0; the live chart
passes its tuned fractions).
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TSType(Enum):
    TS_HIGH = "ts_high"  # bearish — sweep of highs, body back below
    TS_LOW = "ts_low"    # bullish — sweep of lows, body back above


class TSDirection(Enum):
    BEARISH = "bearish"
    BULLISH = "bullish"


class TSVariant(Enum):
    # Deliberate lowercase values: the payload ships them verbatim (the same
    # "snake_case variant" contract as the CRT family).
    TWO_CANDLE = "two_candle"
    CLASSIC = "classic"
    INSIDE_BAR = "inside_bar"
    MULTIPLE_INSIDE_BAR = "multiple_inside_bar"
    MULTIPLE_CANDLE = "multiple_candle"


class TSState(Enum):
    SWEPT = "swept"              # manipulation confirmed, setup alive
    INVALIDATED = "invalidated"  # a later body closed through — breakout real


@dataclass
class TSLevel:
    """A single Turtle Soup sweep."""
    ts_type: TSType
    direction: TSDirection
    price: float              # swept level (anchor high or low)
    candle_index: int         # iloc of the sweeping (manipulation) candle
    candle_time: pd.Timestamp
    sweep_candle_index: int = 0   # iloc of the anchor (range) candle
    sweep_amount: float = 0.0     # how far the wick swept past (price units)
    close_back_distance: float = 0.0  # body-close back inside vs level
    forming_candle_indices: List[int] = field(default_factory=list)
    variant: TSVariant = TSVariant.CLASSIC
    inside_bars: int = 0          # in-between inside-bar count (informational)
    state: TSState = TSState.SWEPT
    end_time: Optional[pd.Timestamp] = None
    invalidated_candle_index: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"TSLevel({self.ts_type.value} @ {self.price:.5f} "
            f"[idx={self.candle_index}] dir={self.direction.value} "
            f"variant={self.variant.value} state={self.state.value})"
        )


class TSDetector:
    """
    Detects Turtle Soup sweeps (full variant taxonomy) on OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    sweep_min : float
        Minimum sweep distance in price units (default 0.0 = any strict sweep).
    min_sweep_atr : float
        Minimum sweep size as a multiple of local ATR(14). Micro-sweeps
        below this never count (default 0.0 = off).
    max_between : int
        Max bars between the anchor and the sweeping candle (>= 1).
        Default 5 — bounds the anchor->sweep window for ALL variants.
    min_wick_body_frac : float
        Opt-in display gate only (default 0.0 = off). The live chart passes
        its tuned fractions; entry math leaves these at 0.0.
    min_wick_range_frac : float
        Opt-in display gate only (default 0.0 = off). Same as above.
    atr_period : int
        ATR lookback for the sweep gate. Default 14.
    """

    def __init__(self, df: pd.DataFrame, sweep_min: float = 0.0,
                 min_sweep_atr: float = 0.0, atr_period: int = 14,
                 min_wick_body_frac: float = 0.0,
                 min_wick_range_frac: float = 0.0,
                 max_between: int = 5):
        self._validate(df)
        if max_between < 1:
            raise ValueError("max_between must be >= 1")
        self.df = df.copy()
        self.sweep_min = sweep_min
        self.min_sweep_atr = min_sweep_atr
        self.atr_period = atr_period
        self.min_wick_body_frac = min_wick_body_frac
        self.min_wick_range_frac = min_wick_range_frac
        self.max_between = int(max_between)
        self._atr = self._compute_atr() if min_sweep_atr > 0 else None
        self._levels: List[TSLevel] = []

    def detect_all(self) -> List[TSLevel]:
        self._levels = []
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        # numpy plain dtype: DatetimeIndex.__getitem__ boxes a Timestamp per
        # call, which dominates runtime on long series.
        dtimes = self.df.index.values
        times = self.df.index
        n = len(self.df)

        # Pass 1 — one signal per (anchor, side): earliest valid sweep within
        # the window; the first breach whose CLOSE runs through the boundary
        # kills the side (real breakout -> no level from this anchor).
        signals: List[TSLevel] = []
        for i in range(n - 1):
            crh = float(h[i])
            crl = float(l[i])
            last = min(i + self.max_between, n - 1)
            # UPPER side: anchor needs a visible swept-side (upper) wick.
            if self._visible_wick(
                    float(h[i]), float(max(o[i], c[i])),
                    float(abs(c[i] - o[i])), float(h[i] - l[i])):
                for j in range(i + 1, last + 1):
                    if c[j] > crh:                      # breakout — side dead
                        break
                    swept = h[j] > crh + self.sweep_min
                    if swept and self._big_enough(float(h[j] - crh), j):
                        if max(o[j], c[j]) < crh:       # body back inside
                            signals.append(self._build(
                                TSType.TS_HIGH, TSDirection.BEARISH,
                                anchor=i, j=j, boundary=crh, crl=crl,
                                sweep=float(h[j] - crh),
                                close_back=float(crh - max(o[j], c[j])),
                                o=o, h=h, l=l, c=c, times=times))
                            break
                        # straddling body (open beyond, close inside):
                        # neither a close-back nor a close-through — keep
                        # scanning, the side is still armed.
            # LOWER side: mirror.
            if self._visible_wick(
                    float(min(o[i], c[i])), float(l[i]),
                    float(abs(c[i] - o[i])), float(h[i] - l[i])):
                for j in range(i + 1, last + 1):
                    if c[j] < crl:
                        break
                    swept = l[j] < crl - self.sweep_min
                    if swept and self._big_enough(float(crl - l[j]), j):
                        if min(o[j], c[j]) > crl:
                            signals.append(self._build(
                                TSType.TS_LOW, TSDirection.BULLISH,
                                anchor=i, j=j, boundary=crl, crl=crl,
                                sweep=float(crl - l[j]),
                                close_back=float(min(o[j], c[j]) - crl),
                                o=o, h=h, l=l, c=c, times=times))
                            break

        # Pass 2a — one manipulation candle may sweep the boundaries of MANY
        # anchors at once (the usual inside-bar double-count). Candidates
        # NESTED inside another candidate's range collapse to the OUTERMOST
        # container — CRT's "widest range wins" discipline. Non-nested
        # candidates are independent signals and all survive; an EXACT
        # range-size tie keeps the earliest anchor.
        by_j: dict = {}
        for sig in signals:
            by_j.setdefault((sig.candle_index, sig.ts_type), []).append(sig)
        reduced: List[TSLevel] = []
        for group in by_j.values():
            keep = []
            for s in group:
                a = s.sweep_candle_index
                hd, ld = float(h[a]), float(l[a])
                dominated = False
                for t in group:
                    if t is s:
                        continue
                    b = t.sweep_candle_index
                    hb, lb = float(h[b]), float(l[b])
                    # t dominates s if s's range sits inside t's — strictly
                    # wider, or the same width but earlier (equal ranges).
                    if (hb >= hd and lb <= ld
                            and (hb > hd or lb < ld or b < a)):
                        dominated = True
                        break
                if not dominated:
                    keep.append(s)
            reduced.extend(keep)
        # Pass 2b — both boundaries of ONE anchor breached on ONE candle =
        # one event: the deeper raid wins. An EXACT tie keeps both.
        by_pair: dict = {}
        for sig in reduced:
            by_pair.setdefault((sig.sweep_candle_index, sig.candle_index),
                               []).append(sig)
        deduped: List[TSLevel] = []
        for group in by_pair.values():
            if len(group) == 2 and group[0].sweep_amount != group[1].sweep_amount:
                deduped.append(max(group, key=lambda s: s.sweep_amount))
            else:
                deduped.extend(group)

        # Pass 3 — invalidation: chronological scan so each level settles on
        # the FIRST later close-through (no window — a level only dies once;
        # wick-only re-pokes never count).
        pending = sorted(deduped, key=lambda s: s.candle_index)
        active: List[TSLevel] = []
        nxt = 0
        for t in range(n):
            still = []
            for sig in active:
                through = (c[t] > sig.price if sig.ts_type is TSType.TS_HIGH
                           else c[t] < sig.price)
                if through:
                    sig.state = TSState.INVALIDATED
                    sig.invalidated_candle_index = t
                    sig.end_time = pd.Timestamp(dtimes[t])
                else:
                    still.append(sig)
            active = still
            while nxt < len(pending) and pending[nxt].candle_index == t:
                active.append(pending[nxt])   # added AFTER settling bar t
                nxt += 1

        self._levels = pending
        return self._levels

    # ------------------------------------------------------------------
    # construction + variant classification
    # ------------------------------------------------------------------
    def _build(self, ts_type: TSType, direction: TSDirection,
               anchor: int, j: int, boundary: float, crl: float,
               sweep: float, close_back: float,
               o: "pd.Series", h: "pd.Series", l: "pd.Series",
               c: "pd.Series", times) -> TSLevel:
        variant, inside = self._classify(anchor, j, boundary, crl, ts_type,
                                         h, l)
        return TSLevel(
            ts_type=ts_type,
            direction=direction,
            price=boundary,
            candle_index=j,
            candle_time=pd.Timestamp(times[j]),
            sweep_candle_index=anchor,
            sweep_amount=sweep,
            close_back_distance=close_back,
            forming_candle_indices=list(range(anchor, j + 1)),
            variant=variant,
            inside_bars=inside,
        )

    def _classify(self, anchor: int, j: int, crh: float, crl: float,
                  ts_type: TSType, h, l) -> tuple:
        """Variant is fully determined by the structure of (anchor, j]."""
        k = j - anchor
        if k == 1:
            delivered = (l[j] <= crl if ts_type is TSType.TS_HIGH
                         else h[j] >= crh)
            return ((TSVariant.TWO_CANDLE, 0) if delivered
                    else (TSVariant.CLASSIC, 0))
        between = [b for b in range(anchor + 1, j)]
        # bool(): numpy h/l comparisons yield numpy.bool_, and sum() over
        # those is numpy.int32 — a scalar FastAPI/jsonable_encoder cannot
        # serialize (a bare np.int32 in the payload 500s the endpoint).
        inside_flags = [bool(h[b] <= crh and l[b] >= crl) for b in between]
        if k == 2:
            if inside_flags[0]:
                return TSVariant.INSIDE_BAR, 1
            return TSVariant.MULTIPLE_CANDLE, 0
        if all(inside_flags):
            return TSVariant.MULTIPLE_INSIDE_BAR, int(k - 1)
        return TSVariant.MULTIPLE_CANDLE, int(sum(inside_flags))

    @property
    def levels(self) -> List[TSLevel]:
        return self._levels

    def _visible_wick(self, extreme: float, body_edge: float,
                      body: float, crange: float) -> bool:
        """True if the swept-side wick visibly protrudes past the body."""
        wick = extreme - body_edge
        if not (wick > 0):
            return False
        if wick < self.min_wick_body_frac * body:
            return False
        if crange > 0 and wick < self.min_wick_range_frac * crange:
            return False
        return True

    def _big_enough(self, sweep: float, idx: int) -> bool:
        if self.min_sweep_atr <= 0 or self._atr is None:
            return True
        atr = self._atr[idx]
        if atr is None or not (atr > 0):
            return True
        return sweep >= self.min_sweep_atr * atr

    def _compute_atr(self) -> list:
        h = self.df["high"]
        l = self.df["low"]
        c = self.df["close"]
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                       axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / self.atr_period, min_periods=1,
                      adjust=False).mean().tolist()

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
