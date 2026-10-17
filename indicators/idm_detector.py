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
    """A single BOS-anchored Inducement level."""

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
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        if self.swept:
            state = f"swept@{self.sweep_index}"
        elif self.broken:
            state = f"broken@{self.broken_index}"
        else:
            state = "active"
        return (
            f"IDMLevel({self.idm_type.value} @ {self.price:.5f} "
            f"[idx={self.formation_index}] {self.bos_kind or 'BOS'} {state})"
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
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 2,
                 bos_swing_length: int = 25, bos_internal_length: int = 3,
                 show_internal: bool = True, swing_tol_atr: float = 0.05,
                 max_per_side: int = 3, atr_period: int = 14):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = max(1, int(swing_length))
        self.bos_swing_length = bos_swing_length
        self.bos_internal_length = bos_internal_length
        self.show_internal = show_internal
        self.swing_tol_atr = swing_tol_atr
        self.max_per_side = max(1, int(max_per_side))
        self.atr_period = atr_period
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

        self._cap()
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

    def _cap(self) -> None:
        """Keep the newest ``max_per_side`` per direction, still-live first."""
        for d in (IDMDirection.BULLISH, IDMDirection.BEARISH):
            group = [lv for lv in self._levels if lv.direction == d]
            if len(group) <= self.max_per_side:
                continue
            group.sort(key=lambda lv:
                       (lv.swept or lv.broken, -lv.formation_index))
            drop = {id(lv) for lv in group[self.max_per_side:]}
            self._levels = [lv for lv in self._levels if id(lv) not in drop]

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
