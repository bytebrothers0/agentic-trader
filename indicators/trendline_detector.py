"""
trendline_detector.py — Point-to-point trendlines through close-price apexes,
with channel pairing, break-retest role flips and trendline-liquidity sweeps.

MSNR definition (strategy_notes/phoenix_mnsr/MSNR_Part6,
strategy_notes/abax mnsr/part06_trendlines_confluence_direction.md §7):
a trendline is a straight line through 2-3 APEX points on the LINE CHART
(close prices).

  SUPPORT    = line through ascending/descending close VALLEYS (V-bottoms).
               Price rides ABOVE it.
  RESISTANCE = line through ascending/descending close PEAKS (A-tops).
               Price rides BELOW it.

The line is the straight segment through those points; the slope is DERIVED
from the points (no forced/ATR slope). The slope may be up, down or flat — a
descending channel's lower boundary and an ascending channel's upper boundary
are both valid. Price must stay on the correct side of the line between the
anchors, else the candidate is void.

TRENDLINE LIQUIDITY (MSNR_Part6 §4): a trendline is a pool of resting orders.
  CHANNEL  = a roughly parallel resistance line above a support line.
  SWEEP    = a wick that pokes clearly through the line while the body holds
             on the original side (the stop-hunt / "double trap").
  BREAK    = a body CLOSE through the line (wick pokes never count).
  RETEST   = after a break, a wick-touch from the far side within retest_bars
             without closing back across; a close back across voids it. A
             retested line FLIPS its role (resistance <-> support).

Anchors are strict close fractals: a bar whose close strictly beats every bar
in the symmetric window. Bars that opened with a gap are never anchors.
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


class TLSide(Enum):
    UPPER = "upper"      # resistance, built from close peaks
    LOWER = "lower"      # support, built from close valleys


class TLState(Enum):
    ACTIVE = "active"
    BROKEN = "broken"


@dataclass
class TLLine:
    """A trendline defined by 2-3 close-price apex points."""
    side: TLSide
    state: TLState
    pivot_price: float          # line value at the first anchor
    pivot_index: int            # iloc of the first anchor (line origin)
    pivot_time: pd.Timestamp
    slope: float                # SIGNED price units per bar
    end_index: int              # break bar, else last bar
    end_time: pd.Timestamp
    break_index: Optional[int] = None
    retested: bool = False
    retest_index: Optional[int] = None
    touches: int = 0            # respected points on the line (>= 1)
    touch_bars: List[int] = field(default_factory=list)  # point 2..n bars
    forming_candle_indices: List[int] = field(default_factory=list)
    anchor_kind: str = "close"  # "close" (line-chart apex)
    anchor_engulfing: bool = False  # 1st anchor bar engulfs a neighbour
    anchor_engulfed: bool = False   # 1st anchor bar engulfed by a neighbour
    engulfing_touches: int = 0  # touches on engulfing/engulfed bars
    misses: int = 0  # MISS bars (skipped past without touching) — validate
    alchemist: str = "standard"  # "continuation" if anchor + point-2 engulf
    apex_points: int = 2        # number of apexes on the line (2 or 3)
    second_anchor_index: Optional[int] = None  # iloc of the 2nd anchor
    channel_id: Optional[int] = None  # shared id for a paired channel
    swept: bool = False         # a liquidity sweep (wick through, body holds)
    sweep_bars: List[int] = field(default_factory=list)

    @property
    def role(self) -> str:
        """Support (price above) or resistance (price below)."""
        return "resistance" if self.side == TLSide.UPPER else "support"

    @property
    def flipped(self) -> bool:
        """Broken then retested: the line's role has flipped."""
        return bool(self.state == TLState.BROKEN and self.retested)

    @property
    def retest_role(self) -> str:
        """Role after a break-retest flip (opposite of the original)."""
        if not self.flipped:
            return self.role
        return "support" if self.side == TLSide.UPPER else "resistance"

    def value_at(self, bar: int) -> float:
        """Signed line value at bar index (clamped before the origin)."""
        step = max(0, bar - self.pivot_index)
        return self.pivot_price + self.slope * step

    @property
    def kind(self) -> str:
        return "BRT" if self.flipped else "TL"

    def __repr__(self) -> str:
        return (
            f"TLLine({self.role} @{self.pivot_price:.5f} "
            f"[pivot={self.pivot_index}->{self.second_anchor_index}] "
            f"{self.state.value}"
            f"{'+retest' if self.retested else ''} touches={self.touches} "
            f"apexes={self.apex_points}"
            f"{' CH' + str(self.channel_id) if self.channel_id else ''}"
            f"{' SWEEP' if self.swept else ''}"
            f"{' FLIP' if self.flipped else ''}"
            f" {self.alchemist})"
        )


class TLDetector:
    """
    Detects point-to-point trendlines through close-price apexes.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    pivot_length : int
        Primary symmetric fractal window for the close apexes. Default 14.
        Also sets the minimum bar overlap for a channel pair.
    pivot_windows : sequence of int, optional
        Multi-scale apex windows. A swing qualifies if it is the extreme of
        ANY window here; the results are merged. When omitted, a single
        window `(pivot_length,)` is used (legacy behaviour).
    max_lines : int
        Most recent lines kept per side. Default 3.
    retest_bars : int
        Forward window for retest scan after a break. Default 30.
    atr_period : int
        ATR lookback for the touch tolerance. Default 14.
    tol_atr : float
        Touch/collinearity tolerance as a fraction of ATR(14). Default 0.25.
    channel_parallel_atr : float
        Channel slope-match tolerance (ATR fraction over 10 bars). Default 0.2.
    sweep_atr : float
        Wick penetration past the line (ATR fraction) to count as a liquidity
        sweep. Default 0.5.
    require_engulfing : bool
        Keep only lines whose first anchor is engulfing/engulfed. Default False.
    skip_gap_anchors : bool
        Never anchor at a bar that opened with a gap. Default True.
    gap_atr_mult : float
        Gap = |open[p] - close[p-1]| beyond this x local ATR. Default 0.1.
    slope_mult, body_pivots : deprecated
        Accepted for backward compatibility; no longer used.
    """

    def __init__(self, df: pd.DataFrame, pivot_length: int = 14,
                 slope_mult: float = 1.0, max_lines: int = 3,
                 retest_bars: int = 30, atr_period: int = 14,
                 body_pivots: bool = True,
                 require_engulfing: bool = False,
                 skip_gap_anchors: bool = True,
                 gap_atr_mult: float = 0.1,
                 tol_atr: float = 0.25,
                 channel_parallel_atr: float = 0.2,
                 sweep_atr: float = 0.5,
                 pivot_windows: Optional[Sequence[int]] = None):
        self._validate(df)
        self.df = df.copy()
        self.pivot_length = max(1, int(pivot_length))
        # Multi-scale apex windows (merged). Default = the single legacy
        # window so existing callers keep their exact behaviour.
        if pivot_windows:
            self.pivot_windows = tuple(
                sorted({max(2, int(w)) for w in pivot_windows}))
        else:
            self.pivot_windows = (max(2, int(pivot_length)),)
        # Never connect two apexes closer than the smallest window.
        self.min_anchor_gap = max(2, min(self.pivot_windows))
        # Deprecated knobs, kept so old callers keep working.
        self.slope_mult = float(slope_mult)
        self.body_pivots = bool(body_pivots)
        self.max_lines = max(1, int(max_lines))
        self.retest_bars = max(0, int(retest_bars))
        self.atr_period = atr_period
        self.require_engulfing = bool(require_engulfing)
        self.skip_gap_anchors = bool(skip_gap_anchors)
        self.gap_atr_mult = float(gap_atr_mult)
        self.tol_atr = float(tol_atr)
        self.channel_parallel_atr = float(channel_parallel_atr)
        self.sweep_atr = float(sweep_atr)
        self._atr = self._compute_atr()
        self._lines: List[TLLine] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_all(self) -> List[TLLine]:
        self._lines = []
        o = self.df["open"].values
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index
        n = len(self.df)
        last = n - 1

        # Close-price apexes (line-chart A/V points).
        apex_hi = self._pivots(c, True)   # peaks  -> resistance lines
        apex_lo = self._pivots(c, False)  # valleys -> support lines
        engulf = self._engulf_map(o, c)

        resistance = self._side_lines(TLSide.UPPER, apex_hi, o, h, l, c, times,
                                      last, engulf)
        support = self._side_lines(TLSide.LOWER, apex_lo, o, h, l, c, times,
                                   last, engulf)

        self._tag_channels(resistance, support)

        resistance.sort(key=self._rank_key)
        support.sort(key=self._rank_key)
        self._lines = self._select_candidates(resistance) + self._select_candidates(support)
        return self._lines

    @property
    def lines(self) -> List[TLLine]:
        return self._lines

    @staticmethod
    def _rank_key(lv: "TLLine"):
        """Channel members first, then most recent, then strongest."""
        return (lv.channel_id is None,
                -(lv.second_anchor_index if lv.second_anchor_index is not None
                  else lv.pivot_index),
                -lv.apex_points, -lv.touches)

    def _select_candidates(self, lines: List[TLLine]) -> List[TLLine]:
        """Keep a balanced menu of active, broken, and retested candidates."""
        ordered = sorted(lines, key=self._rank_key)
        buckets = [
            [line for line in ordered if line.flipped],
            [line for line in ordered if line.state == TLState.ACTIVE],
            [line for line in ordered if line.state == TLState.BROKEN and not line.retested],
        ]
        selected: List[TLLine] = []
        seen = set()
        while len(selected) < self.max_lines and any(buckets):
            for bucket in buckets:
                while bucket:
                    line = bucket.pop(0)
                    key = (line.pivot_index, line.second_anchor_index)
                    if key not in seen:
                        selected.append(line)
                        seen.add(key)
                        break
                if len(selected) >= self.max_lines:
                    break
        return selected

    # ------------------------------------------------------------------
    # Apex run construction
    # ------------------------------------------------------------------

    def _side_lines(self, side, apexes, o, h, l, c, times, last,
                    engulf) -> List[TLLine]:
        """Build candidates from every eligible pair of close-price apexes."""
        out: List[TLLine] = []
        for i, p1 in enumerate(apexes[:-1]):
            for p2 in apexes[i + 1:]:
                if p2 - p1 < self.min_anchor_gap:
                    continue
                line = self._try_build(side, p1, p2, o, h, l, c, times,
                                       last, engulf)
                if line is not None:
                    out.append(line)
        return out

    def _on_line(self, line: TLLine, idx: int, c) -> bool:
        return abs(c[idx] - line.value_at(idx)) <= self._tol(idx)

    def _try_build(self, side, p1, p2, o, h, l, c, times, last,
                   engulf) -> Optional[TLLine]:
        if p2 <= p1:
            return None
        if self.skip_gap_anchors and (self._gapped(o, c, p1)
                                      or self._gapped(o, c, p2)):
            return None
        if self.require_engulfing and not (engulf[p1][0] or engulf[p1][1]):
            return None

        v1, v2 = float(c[p1]), float(c[p2])
        slope = (v2 - v1) / float(p2 - p1)

        def value(mm: int) -> float:
            return v1 + slope * (mm - p1)

        # Price must stay on the correct side between the anchors: above a
        # support line (LOWER), below a resistance line (UPPER).
        for mm in range(p1 + 1, p2):
            if side == TLSide.UPPER and c[mm] > value(mm) + self._tol(mm):
                return None
            if side == TLSide.LOWER and c[mm] < value(mm) - self._tol(mm):
                return None

        # Break: first body CLOSE through the line after the 2nd anchor.
        brk = None
        for mm in range(p2 + 1, last + 1):
            if side == TLSide.UPPER and c[mm] > value(mm):
                brk = mm
                break
            if side == TLSide.LOWER and c[mm] < value(mm):
                brk = mm
                break

        horizon = brk if brk is not None else last

        # Touches + liquidity sweeps after the line forms.
        touch_bars: List[int] = [p2]
        touches = 1
        eng_touches = 1 if (engulf[p2][0] or engulf[p2][1]) else 0
        misses = 0
        swept = False
        sweep_bars: List[int] = []
        for mm in range(p2 + 1, horizon + 1):
            tol = self._tol(mm)
            sbuf = self._sweep_buf(mm)
            body_top = max(o[mm], c[mm])
            body_bot = min(o[mm], c[mm])
            if side == TLSide.UPPER:
                touched = (h[mm] >= value(mm) - tol
                           and body_top <= value(mm) + tol)
                # Wick pierces clearly through while the close holds below.
                if touched and h[mm] > value(mm) + sbuf and c[mm] < value(mm):
                    swept = True
                    sweep_bars.append(mm)
            else:
                touched = (l[mm] <= value(mm) + tol
                           and body_bot >= value(mm) - tol)
                if touched and l[mm] < value(mm) - sbuf and c[mm] > value(mm):
                    swept = True
                    sweep_bars.append(mm)
            if touched:
                touch_bars.append(mm)
                touches += 1
                if engulf[mm][0] or engulf[mm][1]:
                    eng_touches += 1
            elif mm != brk:
                misses += 1

        # Retest: first far-side wick touch after the break without a close
        # back across (which voids it as a failed break).
        retested, retest_idx = False, None
        if brk is not None and self.retest_bars > 0:
            for mm in range(brk + 1, min(last, brk + self.retest_bars) + 1):
                if side == TLSide.UPPER:
                    if c[mm] <= value(mm):
                        break
                    if l[mm] <= value(mm):
                        retested, retest_idx = True, mm
                        break
                else:
                    if c[mm] >= value(mm):
                        break
                    if h[mm] >= value(mm):
                        retested, retest_idx = True, mm
                        break

        end = brk if brk is not None else last
        a_engulfing, a_engulfed = engulf[p1]
        alchemist = ("continuation"
                     if (a_engulfing or a_engulfed)
                     and (engulf[p2][0] or engulf[p2][1])
                     else "standard")
        return TLLine(
            side=side,
            state=TLState.BROKEN if brk is not None else TLState.ACTIVE,
            pivot_price=v1,
            pivot_index=int(p1),
            pivot_time=times[p1],
            slope=slope,
            end_index=int(end),
            end_time=times[end],
            break_index=brk,
            retested=retested,
            retest_index=retest_idx,
            touches=touches,
            touch_bars=touch_bars,
            forming_candle_indices=[int(p1), int(p2)],
            anchor_kind="close",
            anchor_engulfing=bool(a_engulfing),
            anchor_engulfed=bool(a_engulfed),
            engulfing_touches=eng_touches,
            misses=misses,
            alchemist=alchemist,
            apex_points=2,
            second_anchor_index=int(p2),
            swept=swept,
            sweep_bars=sweep_bars,
        )

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def _tag_channels(self, resistance: List[TLLine],
                      support: List[TLLine]) -> None:
        """Pair an active resistance + support line into a channel when their
        ranges overlap, their slopes match, and the resistance sits above the
        support across the overlap."""
        atr_last = self._atr[-1] if self._atr else 0.0
        if not (atr_last and atr_last > 0):
            return
        slope_tol = self.channel_parallel_atr * atr_last / 10.0
        cid = 0
        for up in resistance:
            if up.state != TLState.ACTIVE:
                continue
            for lo in support:
                if lo.state != TLState.ACTIVE:
                    continue
                start = max(up.pivot_index, lo.pivot_index)
                end = min(up.end_index, lo.end_index)
                if end - start < self.pivot_length:
                    continue
                if abs(up.slope - lo.slope) > slope_tol:
                    continue
                steps = max(1, (end - start) // 5)
                if not all(up.value_at(b) > lo.value_at(b)
                           for b in range(start, end + 1, steps)):
                    continue
                cid += 1
                up.channel_id = cid
                lo.channel_id = cid
                break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pivots(self, vals, is_high: bool) -> List[int]:
        """Multi-scale strict fractal pivots, merged across all windows."""
        out: set = set()
        for L in self.pivot_windows:
            out.update(self._pivots_at(vals, is_high, L))
        return sorted(out)

    def _pivots_at(self, vals, is_high: bool, L: int) -> List[int]:
        """Strict fractal pivots: extreme strictly beats every window bar."""
        n = len(self.df)
        out = []
        for i in range(L, n - L):
            window = list(vals[i - L:i]) + list(vals[i + 1:i + L + 1])
            if is_high:
                if all(vals[i] > v for v in window):
                    out.append(i)
            else:
                if all(vals[i] < v for v in window):
                    out.append(i)
        return out

    def _tol(self, idx: int) -> float:
        atr = self._atr[idx] if 0 <= idx < len(self._atr) else 0.0
        if not (atr and atr > 0):
            return 1e-9
        return self.tol_atr * atr

    def _sweep_buf(self, idx: int) -> float:
        atr = self._atr[idx] if 0 <= idx < len(self._atr) else 0.0
        if not (atr and atr > 0):
            return 1e-9
        return self.sweep_atr * atr

    def _gapped(self, o, c, p: int) -> bool:
        """True if bar p opened with a gap vs the prior close (GAP SNR —
        trendlines must never anchor there)."""
        if p <= 0 or p >= len(self.df):
            return False
        atr = self._atr[p] if 0 <= p < len(self._atr) else 0.0
        if not (atr and atr > 0):
            return bool(o[p] != c[p - 1])
        return bool(abs(o[p] - c[p - 1]) > self.gap_atr_mult * atr)

    @staticmethod
    def _polarity(o, c, i: int) -> int:
        if c[i] > o[i]:
            return 1
        if c[i] < o[i]:
            return -1
        return 0  # doji: wildcard, pairs with either direction

    def _body_engulfs(self, o, c, i: int, j: int) -> bool:
        """True if candle i's body engulfs candle j's body."""
        top_i, bot_i = max(o[i], c[i]), min(o[i], c[i])
        top_j, bot_j = max(o[j], c[j]), min(o[j], c[j])
        if not (top_i >= top_j and bot_i <= bot_j
                and (top_i > top_j or bot_i < bot_j)):
            return False
        pi, pj = self._polarity(o, c, i), self._polarity(o, c, j)
        return pi == 0 or pj == 0 or pi != pj

    def _engulf_map(self, o, c) -> List[tuple]:
        """Per-bar (is_engulfing, is_engulfed) body-engulf flags."""
        n = len(self.df)
        out: List[tuple] = []
        for i in range(n):
            engulfing, engulfed = False, False
            for j in (i - 1, i + 1):
                if 0 <= j < n:
                    if self._body_engulfs(o, c, i, j):
                        engulfing = True
                    if self._body_engulfs(o, c, j, i):
                        engulfed = True
            out.append((engulfing, engulfed))
        return out

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
