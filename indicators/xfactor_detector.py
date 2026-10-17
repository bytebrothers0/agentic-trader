"""
xfactor_detector.py — Alchemist X-Factor: trendline x SNR confluence (web math).

The X-Factor ("crown jewel" of the web Alchemist method) is the point where
a trendline CROSSES a horizontal SNR level: trendline says the direction,
SNR says the price — both agreeing at the same point is the entry.

Pipeline (all rules web-sourced):
  Point 1  = trendline anchor (TLLine.pivot).
  Point 2  = first validation touch (TLLine.touch_bars[0]). Never enter here.
  Point 3  = first bar after point 2 where |TL.value - SNR.price| <= xtol.
             The SNR leg must be usable (fresh or once-touched: 2-use rule)
             and must NOT be a GAP (hidden) zone.
  Grades   = engulfing AT point 3 is MANDATORY ("no validation, no trade"):
             without it the X emits as tier "no-trade". Sweep at the X
             (TS within sweep_window) is the bonus tier. QM coincidence +
             engulfing = QMX top tier.

Engulfing zones: second candle body covers the first (regular), or opens
with a gap and still covers (GAP engulfing, stronger). Opposite colours
(or doji wildcard). The zone is marked BETWEEN THE TWO CLOSES
(top = higher close, bottom = lower close) — limit orders live there.

Storyline gate: HTF fresh-level rejection (wick touch + body close back
inside within rej_window, never a body break) AND a same-direction LTF
BOS within bos_window bars. Mirrors the "2 TF confirmation" rule.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class XDirection(Enum):
    SHORT = "short"  # upper TL into resistance
    LONG = "long"    # lower TL into support


class EngulfDirection(Enum):
    BULLISH = "bullish"  # bull body covers bear (support on retest)
    BEARISH = "bearish"  # bear body covers bull (resistance on retest)


@dataclass
class EngulfZone:
    """An engulfing pair; the zone is marked between the two closes."""
    direction: EngulfDirection
    top: float                  # higher of the two closes
    bottom: float               # lower of the two closes
    first_index: int            # iloc of candle 1 (engulfed)
    formation_index: int        # iloc of candle 2 (engulfing)
    candle_time: pd.Timestamp
    is_gap: bool = False        # GAP engulfing (opened with a gap)
    forming_candle_indices: List[int] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def __repr__(self) -> str:
        return (
            f"EngulfZone({self.direction.value} [{self.bottom:.5f}..{self.top:.5f}] "
            f"[idx={self.formation_index}]{' GAP' if self.is_gap else ''})"
        )


@dataclass
class XLevel:
    """One trendline x SNR crossing (point 3)."""
    direction: XDirection
    x_index: int                # point-3 bar
    x_price: float              # SNR price (the agreed point)
    tl_value: float             # trendline value at point 3
    sr_price: float
    sr_kind: str                # level_type string of the SNR leg
    tl_pivot_index: int
    tl_anchor_kind: str         # "wick" | "body"
    tl_alchemist: str           # "continuation" | "standard"
    candle_time: pd.Timestamp
    point2_index: int = 0
    engulf: bool = False
    engulf_gap: bool = False
    ex_top: Optional[float] = None     # between-closes box (limit zone)
    ex_bottom: Optional[float] = None
    sweep: bool = False
    qm_match: bool = False
    misses: int = 0
    touches: int = 0
    score: int = 0
    tier: str = "no-trade"      # "QMX" | "A+" | "standard" | "no-trade"
    tradable: bool = False
    forming_candle_indices: List[int] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"XLevel({self.direction.value} @{self.x_price:.5f} "
            f"[idx={self.x_index}] {self.tier}"
            f"{' ENG' if self.engulf else ''}"
            f"{' SWEEP' if self.sweep else ''})"
        )


@dataclass
class Storyline:
    """HTF rejection + LTF BOS agreement (2-TF confirmation)."""
    direction: XDirection
    htf_price: float
    touch_index: int
    bos_index: int
    candle_time: pd.Timestamp

    def __repr__(self) -> str:
        return (
            f"Storyline({self.direction.value} @{self.htf_price:.5f} "
            f"[touch={self.touch_index} bos={self.bos_index}])"
        )


def _atr_list(df: pd.DataFrame, period: int = 14) -> list:
    h = df["high"]
    l = df["low"]
    c = df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=1,
                  adjust=False).mean().tolist()


def _polarity(o, c, i: int) -> int:
    if c[i] > o[i]:
        return 1
    if c[i] < o[i]:
        return -1
    return 0


def _covers(o, c, i: int, j: int) -> bool:
    """Candle i's body covers candle j's body with opposite colours
    (doji wildcards either side)."""
    top_i, bot_i = max(o[i], c[i]), min(o[i], c[i])
    top_j, bot_j = max(o[j], c[j]), min(o[j], c[j])
    if not (top_i >= top_j and bot_i <= bot_j
            and (top_i > top_j or bot_i < bot_j)):
        return False
    pi, pj = _polarity(o, c, i), _polarity(o, c, j)
    return pi == 0 or pj == 0 or pi != pj


def detect_engulfing_zones(df: pd.DataFrame,
                            gap_atr_mult: float = 0.1,
                            atr_period: int = 14) -> List[EngulfZone]:
    """All engulfing pairs; zones marked between the two closes."""
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    times = df.index
    atr = _atr_list(df, atr_period)
    out: List[EngulfZone] = []
    for i in range(len(df) - 1):
        j = i + 1
        if _covers(o, c, j, i):
            direction = (EngulfDirection.BULLISH if c[j] >= o[j]
                         else EngulfDirection.BEARISH)
            a = atr[j] if 0 <= j < len(atr) else 0.0
            is_gap = bool(a and a > 0 and abs(o[j] - c[i]) > gap_atr_mult * a)
            out.append(EngulfZone(
                direction=direction,
                top=float(max(c[i], c[j])),
                bottom=float(min(c[i], c[j])),
                first_index=i,
                formation_index=j,
                candle_time=times[j],
                is_gap=is_gap,
                forming_candle_indices=[i, j],
            ))
    return out


def _level_side_ok(sr_kind: str, want_short: bool) -> bool:
    k = (sr_kind or "").lower()
    if want_short:
        return k in ("resistance", "sbr")
    return k in ("support", "rbs")


def _usable(sr, max_uses: int = 2) -> bool:
    state = getattr(sr, "state", None)
    state_ok = True
    if state is not None:
        val = state.value if hasattr(state, "value") else str(state)
        state_ok = val != "broken"
    touches = getattr(sr, "touch_count", 0) or 0
    return bool(state_ok and touches < max_uses)


class XDetector:
    """
    Finds trendline x SNR crossings (point 3) with web grades.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV of the execution timeframe (index DatetimeIndex).
    sr_levels : list
        Horizontal levels (CandleLevel-compatible: .price, .level_type,
        .state, .touch_count, .is_gap). OCL/QM levels pass through
        .to_candle_level() first.
    tl_lines : list
        TLLine objects (must carry touch_bars).
    ts_levels : list, optional
        TSLevel objects (.ts_type, .candle_index) for the sweep bonus.
    qm_levels : list, optional
        QM levels (.price / CandleLevel-compatible) for the QMX tier.
    xtol_atr : float
        Crossing tolerance as a fraction of local ATR. Default 0.1.
    sweep_window : int
        TS within this many bars of point 3 counts as the sweep bonus.
        Default 3.
    max_uses : int
        SNR legs with this many touches are exhausted. Default 2.
    """

    def __init__(self, df: pd.DataFrame, sr_levels: list, tl_lines: list,
                 ts_levels: Optional[list] = None,
                 qm_levels: Optional[list] = None,
                 xtol_atr: float = 0.1, sweep_window: int = 3,
                 max_uses: int = 2, atr_period: int = 14):
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame index must be a DatetimeIndex.")
        self.df = df.copy()
        self.sr_levels = list(sr_levels or [])
        self.tl_lines = list(tl_lines or [])
        self.ts_levels = list(ts_levels or [])
        self.qm_levels = list(qm_levels or [])
        self.xtol_atr = float(xtol_atr)
        self.sweep_window = int(sweep_window)
        self.max_uses = int(max_uses)
        self._atr = _atr_list(self.df, atr_period)
        self._zones = detect_engulfing_zones(self.df)
        self._levels: List[XLevel] = []

    def detect_all(self) -> List[XLevel]:
        self._levels = []
        n = len(self.df)
        for tl in self.tl_lines:
            touch_bars = list(getattr(tl, "touch_bars", []) or [])
            if not touch_bars:
                continue  # no point 2, never entered
            want_short = str(getattr(getattr(tl, "side", ""), "value",
                                     getattr(tl, "side", ""))).lower() == "upper"
            direction = (XDirection.SHORT if want_short else XDirection.LONG)
            horizon = int(getattr(tl, "end_index", n - 1))
            point2 = touch_bars[0]
            claimed: set = set()
            for m in range(point2 + 1, min(horizon, n - 1) + 1):
                atr = self._atr[m] if 0 <= m < len(self._atr) else 0.0
                if not (atr and atr > 0):
                    continue
                tol = self.xtol_atr * atr
                try:
                    tl_val = float(tl.value_at(m))
                except Exception:
                    continue
                for sr in self.sr_levels:
                    kind = getattr(getattr(sr, "level_type", ""), "value",
                                   getattr(sr, "level_type", ""))
                    if not _level_side_ok(str(kind), want_short):
                        continue
                    if bool(getattr(sr, "is_gap", False)):
                        continue  # hidden zone: refinement only, never the X
                    if not _usable(sr, self.max_uses):
                        continue
                    price = float(sr.price)
                    if abs(tl_val - price) > tol:
                        continue
                    key = (tl.pivot_index, round(price, 6))
                    if key in claimed:
                        continue
                    claimed.add(key)
                    self._levels.append(self._grade(
                        tl, direction, m, price, str(kind), tol))
        self._levels.sort(key=lambda x: x.x_index)
        return self._levels

    # ------------------------------------------------------------------
    def _grade(self, tl, direction: XDirection, m: int, price: float,
               sr_kind: str, tol: float) -> XLevel:
        times = self.df.index
        zone = self._engulf_zone_at(m, price, tol)
        eng = zone is not None
        eng_gap = bool(zone.is_gap) if zone else False
        sweep = self._sweep_near(m, direction)
        qm_match = self._qm_near(price, tol)
        score = 1  # the X itself
        if getattr(tl, "alchemist", "") == "continuation":
            score += 1
        if self._sr_is_fresh(price, sr_kind):
            score += 1
        if eng:
            score += 2  # mandatory validation carries the most weight
        if sweep:
            score += 1
        if qm_match and eng:
            tier, tradable = "QMX", True
        elif eng and sweep:
            tier, tradable = "A+", True
        elif eng:
            tier, tradable = "standard", True
        else:
            tier, tradable = "no-trade", False
        return XLevel(
            direction=direction,
            x_index=m,
            x_price=price,
            tl_value=float(tl.value_at(m)),
            sr_price=price,
            sr_kind=sr_kind,
            tl_pivot_index=int(tl.pivot_index),
            tl_anchor_kind=str(getattr(tl, "anchor_kind", "wick")),
            tl_alchemist=str(getattr(tl, "alchemist", "standard")),
            candle_time=times[m],
            point2_index=int(getattr(tl, "touch_bars", [m])[0]),
            engulf=eng,
            engulf_gap=eng_gap,
            ex_top=(float(zone.top) if zone else None),
            ex_bottom=(float(zone.bottom) if zone else None),
            sweep=sweep,
            qm_match=qm_match,
            misses=int(getattr(tl, "misses", 0)),
            touches=int(getattr(tl, "touches", 0)),
            score=score,
            tier=tier,
            tradable=tradable,
            forming_candle_indices=[int(tl.pivot_index), m],
        )

    def _sr_is_fresh(self, price: float, sr_kind: str) -> bool:
        for sr in self.sr_levels:
            kind = getattr(getattr(sr, "level_type", ""), "value",
                           getattr(sr, "level_type", ""))
            if str(kind) == sr_kind and abs(float(sr.price) - price) < 1e-9:
                state = getattr(sr, "state", None)
                val = (state.value if hasattr(state, "value")
                       else str(state)) if state is not None else "fresh"
                touches = getattr(sr, "touch_count", 0) or 0
                return bool(val == "fresh" and touches == 0)
        return False

    def _engulf_zone_at(self, m: int, price: float,
                        tol: float) -> Optional[EngulfZone]:
        """Engulfing zone overlapping the X within tolerance, formed
        within one bar of point 3."""
        for z in self._zones:
            if abs(z.formation_index - m) > 1:
                continue
            if z.bottom - tol <= price <= z.top + tol:
                return z
        return None

    def _sweep_near(self, m: int, direction: XDirection) -> bool:
        want = ("ts_high" if direction == XDirection.SHORT else "ts_low")
        for ts in self.ts_levels:
            t = getattr(getattr(ts, "ts_type", ""), "value",
                        getattr(ts, "ts_type", ""))
            idx = int(getattr(ts, "candle_index", -10 ** 9))
            if str(t) == want and abs(idx - m) <= self.sweep_window:
                return True
        return False

    def _qm_near(self, price: float, tol: float) -> bool:
        for qm in self.qm_levels:
            try:
                if abs(float(getattr(qm, "price", float("nan"))) - price) <= tol:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @property
    def levels(self) -> List[XLevel]:
        return self._levels

    @property
    def zones(self) -> List[EngulfZone]:
        return self._zones


def detect_storyline(htf_df: pd.DataFrame, htf_levels: list,
                     ltf_bos: list, direction: XDirection,
                     rej_window: int = 5, bos_window: int = 10) -> Optional[Storyline]:
    """2-TF confirmation: HTF fresh-level rejection (wick touch + body
    close back inside within rej_window, never a body break) AND a
    same-direction LTF BOS within bos_window bars after the touch.

    htf_levels: CandleLevel-compatible (.price, .level_type, .first_touch_index).
    ltf_bos: BOSLevel-compatible (.direction [.value], .break_index).
    """
    o = htf_df["open"].values
    h = htf_df["high"].values
    l = htf_df["low"].values
    c = htf_df["close"].values
    times = htf_df.index
    n = len(htf_df)
    want_short = direction == XDirection.SHORT
    for lv in htf_levels:
        kind = getattr(getattr(lv, "level_type", ""), "value",
                       getattr(lv, "level_type", ""))
        if not _level_side_ok(str(kind), want_short):
            continue
        touch = getattr(lv, "first_touch_index", None)
        if touch is None:
            continue
        touch = int(touch)
        price = float(lv.price)
        # Rejection: body back on the near side within rej_window, no break.
        rejected = False
        for m in range(touch, min(touch + rej_window + 1, n)):
            if want_short:
                if c[m] > price:
                    break  # body broke through: no rejection
                if max(o[m], c[m]) < price:
                    rejected = True
                    break
            else:
                if c[m] < price:
                    break
                if min(o[m], c[m]) > price:
                    rejected = True
                    break
        if not rejected:
            continue
        # LTF BOS agreement within bos_window after the touch.
        want_bos = ("bearish" if want_short else "bullish")
        for b in ltf_bos:
            bd = getattr(getattr(b, "direction", ""), "value",
                         getattr(b, "direction", ""))
            bi = int(getattr(b, "break_index", -10 ** 9))
            if str(bd) == want_bos and touch <= bi <= touch + bos_window:
                return Storyline(direction=direction, htf_price=price,
                                 touch_index=touch, bos_index=bi,
                                 candle_time=times[min(bi, n - 1)])
    return None
