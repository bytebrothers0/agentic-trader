"""
crt_detector.py — Candle Range Theory (CRT) indicator.

CRT reads price as *ranges that liquidate each other*. One candle — the **range
candle** — defines the range::

    CRH = range candle high        CRL = range candle low

A later candle then **sweeps** one boundary (wick beyond it) and **closes back
inside** the range. That is the manipulation: the boundary was raided for
liquidity, not genuinely broken. The projection is toward the **opposite**
extreme::

    BULLISH CRT : CRL swept, close back above CRL  -> target CRH
    BEARISH CRT : CRH swept, close back below CRH  -> target CRL

Three phases, A-M-D: **accumulation** (the range) -> **manipulation** (the
sweep) -> **distribution** (the expansion to the far side).

Two variants
------------
CLASSIC
    The manipulation candle is the candle straight after the range candle: the
    strict 3-candle CRT (anchor, manipulation, distribution).

INSIDE_BAR
    The accumulation *nests inside bars* inside the anchor's range before the
    manipulation (anchor -> 1..N inside bars -> manipulation). The range stays
    defined by the anchor; the inside bars are the compression that builds the
    liquidity sitting beyond the boundary. The community reading is that more
    inside bars means more accumulated liquidity and a higher-probability
    expansion, which is why it is a variant and not just "more candles".

Life cycle
----------
A formed CRT is resolved by whichever comes first, scanning **after** the
manipulation candle:

- **INVALIDATED** — a body **close** beyond the swept extreme (bullish: close
  below CRL). The sweep was a genuine break, not a manipulation; the setup is
  void. Checked first, so a bar that both closes through and taps the far side
  is reported as void rather than as a win.
- **DISTRIBUTED** — a later candle reaches the opposite extreme (the target).
- otherwise **MANIPULATED** (still live, still awaiting distribution).

Distribution is deliberately *not* credited to the manipulation candle itself:
in A-M-D the third phase comes after the manipulation, and a bar that both
sweeps and closes through the far side is a far stronger reversal than a CRT,
not the same thing.

Dedupe and caps
---------------
Every candle is a candidate anchor, so the same manipulation candle can belong
to several ranges. Exactly **one** CRT is kept per manipulation candle, and it
is the one with the **widest range** (the outermost accumulation container is
the real one), then the most inside bars, then the earliest anchor. When a
single candle sweeps *both* boundaries, the side with the larger penetration
wins — one bar is one manipulation, not two.

Anchor colour
-------------
Sources disagree on whether the range candle must be directional and in which
direction, so it is an opt-in filter (`require_directional_anchor`, default
off): the sweep plus close-back-inside is the definition, the anchor's colour
is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd


class CRTDirection(Enum):
    """The side the CRT projects toward."""
    BULLISH = "bullish"   # CRL swept -> target CRH
    BEARISH = "bearish"   # CRH swept -> target CRL


class CRTVariant(Enum):
    CLASSIC = "classic"        # strict 3-candle: anchor -> manipulation -> distribution
    INSIDE_BAR = "inside_bar"  # accumulation nests >= 1 inside bar inside the anchor


class CRTState(Enum):
    MANIPULATED = "manipulated"   # swept and closed back inside; still live
    DISTRIBUTED = "distributed"   # opposite extreme reached (target hit)
    INVALIDATED = "invalidated"   # body closed beyond the swept extreme


_END_KINDS = {
    CRTState.MANIPULATED.value: "active",
    CRTState.DISTRIBUTED.value: "distributed",
    CRTState.INVALIDATED.value: "invalidated",
}


@dataclass
class CRTLevel:
    """A single Candle Range Theory setup."""
    direction: CRTDirection
    variant: CRTVariant
    state: CRTState
    crh: float                    # range high (anchor candle high)
    crl: float                    # range low (anchor candle low)
    swept_level: float            # the boundary taken (the drawn ray price)
    target_level: float           # the opposite boundary (the projection)
    anchor_index: int             # iloc of the range candle
    anchor_time: pd.Timestamp
    manipulation_index: int       # iloc of the sweeping candle
    manipulation_time: pd.Timestamp
    inside_bar_indices: List[int] = field(default_factory=list)
    sweep_amount: float = 0.0         # wick penetration past the swept boundary
    close_back_distance: float = 0.0  # body close back inside, vs the swept boundary
    range_atr: float = 0.0            # anchor range size in ATR(14) at the anchor
    distribution_index: Optional[int] = None
    distribution_time: Optional[pd.Timestamp] = None
    invalidated_index: Optional[int] = None
    invalidated_time: Optional[pd.Timestamp] = None

    @property
    def price(self) -> float:
        """The plotted level: the swept boundary."""
        return self.swept_level

    @property
    def inside_count(self) -> int:
        return len(self.inside_bar_indices)

    @property
    def range_size(self) -> float:
        return self.crh - self.crl

    @property
    def end_index(self) -> Optional[int]:
        if self.state is CRTState.INVALIDATED:
            return self.invalidated_index
        if self.state is CRTState.DISTRIBUTED:
            return self.distribution_index
        return None

    @property
    def end_kind(self) -> str:
        return _END_KINDS[self.state.value]

    def __repr__(self) -> str:
        return (
            f"CRTLevel({self.direction.value}/{self.variant.value} "
            f"swept={self.swept_level:.5f} target={self.target_level:.5f} "
            f"[anchor={self.anchor_index} manip={self.manipulation_index}] "
            f"state={self.state.value})"
        )


class CRTDetector:
    """
    Detects Candle Range Theory setups on OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    min_range_atr : float
        Anchor range must be at least this multiple of ATR(14) — drops the
        micro-ranges that make every candle a "setup". Default 0.0 = off
        (indicator display; the live chart passes a tuned value).
    min_sweep_atr : float
        Wick penetration past the swept boundary, as a multiple of ATR(14).
        Default 0.0 = off.
    min_close_back_atr : float
        How far the body must close back inside, past the swept boundary, in
        ATR(14). Default 0.0 = off (any close back inside counts).
    max_inside_bars : int
        Longest inside-bar accumulation accepted before the manipulation.
        Beyond this it is a range, not a compression — the anchor is skipped.
        Default 8.
    require_directional_anchor : bool
        Opt-in quality filter: bullish CRTs need a bearish range candle (and
        mirror). Default False — see the module docstring.
    max_per_side : int
        Newest resolved (distributed/invalidated) setups kept per direction.
        Default 8.
    max_live_per_side : int
        Newest still-live (manipulated) setups kept per direction. Default 30.
    sweep_min : float
        Absolute minimum penetration in price units. Default 0.0.
    atr_period : int
        ATR lookback for the gates. Default 14.
    """

    def __init__(self, df: pd.DataFrame, min_range_atr: float = 0.0,
                 min_sweep_atr: float = 0.0, min_close_back_atr: float = 0.0,
                 max_inside_bars: int = 8,
                 require_directional_anchor: bool = False,
                 max_per_side: int = 8, max_live_per_side: int = 30,
                 sweep_min: float = 0.0, atr_period: int = 14):
        self._validate(df)
        self.df = df.copy()
        self.min_range_atr = min_range_atr
        self.min_sweep_atr = min_sweep_atr
        self.min_close_back_atr = min_close_back_atr
        self.max_inside_bars = max(0, int(max_inside_bars))
        self.require_directional_anchor = require_directional_anchor
        self.max_per_side = max(0, int(max_per_side))
        self.max_live_per_side = max(0, int(max_live_per_side))
        self.sweep_min = sweep_min
        self.atr_period = atr_period
        self._atr = self._compute_atr()
        self._levels: List[CRTLevel] = []

    # ------------------------------------------------------------------ detect

    def detect_all(self) -> List[CRTLevel]:
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index
        n = len(self.df)

        # One setup per manipulation candle: the widest range wins.
        best: Dict[int, CRTLevel] = {}

        for i in range(n - 1):
            crh = float(h[i])
            crl = float(l[i])
            rng = crh - crl
            if rng <= 0:
                continue
            if not self._range_ok(rng, i):
                continue

            # Accumulation: inside bars fully contained in the anchor range.
            inside: List[int] = []
            j = i + 1
            while j < n and self._is_inside(float(h[j]), float(l[j]), crh, crl):
                if len(inside) >= self.max_inside_bars:
                    break
                inside.append(j)
                j += 1
            if j >= n:
                continue
            if self._is_inside(float(h[j]), float(l[j]), crh, crl):
                # The inside-bar run is longer than the cap: a range, not a
                # compression. Not this anchor's pattern.
                continue

            # j is the first candle outside the range: the manipulation candidate.
            sweep_low = crl - float(l[j])
            sweep_high = float(h[j]) - crh
            bull_ok = (sweep_low > self.sweep_min and self._sweep_ok(sweep_low, j)
                       and float(c[j]) > crl
                       and self._close_back_ok(float(c[j]) - crl, j))
            bear_ok = (sweep_high > self.sweep_min and self._sweep_ok(sweep_high, j)
                       and float(c[j]) < crh
                       and self._close_back_ok(crh - float(c[j]), j))
            if not (bull_ok or bear_ok):
                continue

            if bull_ok and bear_ok:
                # One bar is one manipulation; the deeper raid is the story.
                direction = (CRTDirection.BULLISH if sweep_low >= sweep_high
                             else CRTDirection.BEARISH)
            elif bull_ok:
                direction = CRTDirection.BULLISH
            else:
                direction = CRTDirection.BEARISH

            bullish = direction is CRTDirection.BULLISH
            if self.require_directional_anchor and not self._anchor_is_counter(i, o, c, bullish):
                continue
            candidate = CRTLevel(
                direction=direction,
                variant=CRTVariant.INSIDE_BAR if inside else CRTVariant.CLASSIC,
                state=CRTState.MANIPULATED,
                crh=crh,
                crl=crl,
                swept_level=crl if bullish else crh,
                target_level=crh if bullish else crl,
                anchor_index=i,
                anchor_time=times[i],
                manipulation_index=j,
                manipulation_time=times[j],
                inside_bar_indices=list(inside),
                sweep_amount=float(sweep_low if bullish else sweep_high),
                close_back_distance=float(float(c[j]) - crl if bullish else crh - float(c[j])),
                range_atr=self._range_atr(rng, i),
            )
            incumbent = best.get(j)
            if incumbent is None or self._prefer(candidate, incumbent):
                best[j] = candidate

        levels: List[CRTLevel] = []
        for j in sorted(best):
            lvl = best[j]
            self._resolve(lvl, h, l, c, times, n)
            levels.append(lvl)

        self._levels = self._cap(levels)
        return self._levels

    @property
    def levels(self) -> List[CRTLevel]:
        return self._levels

    # ------------------------------------------------------------------ resolve

    def _resolve(self, lvl: CRTLevel, h, l, c, times, n: int) -> None:
        """Walk forward from the bar after the manipulation to the first
        decisive event: invalidation (body close beyond the swept boundary)
        beats distribution (target reached) on the same bar."""
        bullish = lvl.direction is CRTDirection.BULLISH
        for k in range(lvl.manipulation_index + 1, n):
            if bullish:
                if float(c[k]) < lvl.crl:
                    lvl.state = CRTState.INVALIDATED
                    lvl.invalidated_index = k
                    lvl.invalidated_time = times[k]
                    return
                if float(h[k]) >= lvl.crh:
                    lvl.state = CRTState.DISTRIBUTED
                    lvl.distribution_index = k
                    lvl.distribution_time = times[k]
                    return
            else:
                if float(c[k]) > lvl.crh:
                    lvl.state = CRTState.INVALIDATED
                    lvl.invalidated_index = k
                    lvl.invalidated_time = times[k]
                    return
                if float(l[k]) <= lvl.crl:
                    lvl.state = CRTState.DISTRIBUTED
                    lvl.distribution_index = k
                    lvl.distribution_time = times[k]
                    return

    # ------------------------------------------------------------------ caps

    def _cap(self, levels: List[CRTLevel]) -> List[CRTLevel]:
        """Live setups are always kept (bounded); resolved history is capped
        per direction, newest first — same philosophy as the IDM/liquidity caps."""
        keep: List[CRTLevel] = []
        for direction in (CRTDirection.BULLISH, CRTDirection.BEARISH):
            side = [x for x in levels if x.direction is direction]
            live = [x for x in side if x.state is CRTState.MANIPULATED]
            resolved = [x for x in side if x.state is not CRTState.MANIPULATED]
            keep.extend(live[-self.max_live_per_side:] if self.max_live_per_side else [])
            keep.extend(resolved[-self.max_per_side:] if self.max_per_side else [])
        keep.sort(key=lambda x: x.manipulation_index)
        return keep

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _is_inside(high: float, low: float, crh: float, crl: float) -> bool:
        """Fully contained in the anchor range: an inside bar."""
        return low >= crl and high <= crh

    @staticmethod
    def _prefer(candidate: CRTLevel, incumbent: CRTLevel) -> bool:
        """Widest accumulation container wins; then most inside bars; then
        the earliest anchor."""
        eps = 1e-12
        if candidate.range_size > incumbent.range_size + eps:
            return True
        if abs(candidate.range_size - incumbent.range_size) <= eps:
            if candidate.inside_count != incumbent.inside_count:
                return candidate.inside_count > incumbent.inside_count
            return candidate.anchor_index < incumbent.anchor_index
        return False

    @staticmethod
    def _anchor_is_counter(i: int, o, c, bullish_crt: bool) -> bool:
        """True if the anchor candle is directional *against* the CRT it hosts
        (bullish CRT -> bearish range candle). Only used when
        `require_directional_anchor` is on; a doji satisfies neither side."""
        anchor_bullish = float(c[i]) > float(o[i])
        anchor_bearish = float(c[i]) < float(o[i])
        return anchor_bearish if bullish_crt else anchor_bullish

    def _range_ok(self, rng: float, i: int) -> bool:
        if self.min_range_atr <= 0:
            return True
        atr = self._atr_at(i)
        return atr is None or rng >= self.min_range_atr * atr

    def _sweep_ok(self, sweep: float, j: int) -> bool:
        if self.min_sweep_atr <= 0:
            return True
        atr = self._atr_at(j)
        return atr is None or sweep >= self.min_sweep_atr * atr

    def _close_back_ok(self, distance: float, j: int) -> bool:
        if self.min_close_back_atr <= 0:
            return True
        atr = self._atr_at(j)
        return atr is None or distance >= self.min_close_back_atr * atr

    def _range_atr(self, rng: float, i: int) -> float:
        atr = self._atr_at(i)
        return float(rng / atr) if atr else 0.0

    def _atr_at(self, idx: int) -> Optional[float]:
        if not self._atr or idx >= len(self._atr):
            return None
        atr = self._atr[idx]
        if atr is None:
            return None
        atr = float(atr)
        return atr if atr > 0 else None

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
