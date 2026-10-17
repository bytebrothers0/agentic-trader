"""
bos_detector.py — Break of Structure (Mxwll-style port + Luap Part 2 labels).

Ported from the Mxwll suite (AETHER/Fatich Pine):
  Swings: Donchian-style zigzag state machine. The bar `swing_length` ago
    is the candidate; if its high meets or exceeds all `swing_length` bars
    after it, trend state flips up and that bar becomes the swing high
    (mirror for lows). Non-strict on purpose: a level tapped 3-5 times at
    the SAME price still counts as a swing (the script's strict version
    misses these). A swing prints only on a state FLIP, and each new swing
    re-arms its level (one-shot per level).
  Structure: CLOSE through the last swing high/low fires. Wick-only crosses
    never count. Break with the trend state = BOS, against it = CHoCH.
  Range levels: a break is also armed against the highest swing high (or
    lowest swing low) since the last break on that side. A shallow pullback
    pivots a *lower* high, which must not erase the range high the market
    left behind — the level a continuation BOS clears is that range
    extreme. Both levels are checked each bar; a same-bar take reports the
    nearer swing, so the classic sequence reads CHoCH (pullback high) then
    BOS (range high).
    External (major) sensitivity default 25, mirroring the script's
    Externals Sensitivity (options 10/25/50); internal (minor) default 5,
    mirroring Internals Sensitivity (options 3/5/8). Internals emit as
    I-BOS / I-CHOCH so both layers stay visible.

Ray runs swing bar -> break bar (as the script draws it).
"""

from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class BOSDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class BOSLevel:
    """A single Break of Structure / Change of Character."""
    direction: BOSDirection
    price: float                  # swing high/low that was broken
    extreme_index: int            # iloc of the swing bar
    break_index: int              # iloc of the close-through bar
    candle_time: pd.Timestamp     # time of the break bar
    is_choch: bool = False
    internal: bool = False        # internal (minor) layer vs external (major)
    from_range: bool = False      # break of a range extreme, not the latest pivot
    forming_candle_indices: List[int] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return ("I-" if self.internal else "") + ("CHOCH" if self.is_choch else "BOS")

    def __repr__(self) -> str:
        return (
            f"BOSLevel({self.kind} {self.direction.value} @ {self.price:.5f} "
            f"[swing={self.extreme_index} break={self.break_index}])"
        )


class BOSDetector:
    """
    Mxwll-style BOS/CHoCH detector.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with columns: open, high, low, close.
        Index must be a DatetimeIndex.
    swing_length : int
        External (major) swing sensitivity (bars). Default 25.
    internal_length : int
        Internal (minor) swing sensitivity (bars). Default 3 (fastest of
        the script's 3/5/8 options — confirms structure nearest the live edge).
        Runs as a second independent state machine emitting I-BOS/I-CHOCH.
    show_internal : bool
        Include the internal layer. Default True.
    swing_tol_atr : float
        Same-level tolerance as a multiple of local ATR(14). Taps within
        this band of the window extreme still confirm the swing, so levels
        wicked 3-5 times at nearly (not exactly) the same price count.
        Default 0.05.
    atr_period : int
        ATR lookback for the tolerance band. Default 14.
    """

    def __init__(self, df: pd.DataFrame, swing_length: int = 25,
                 internal_length: int = 3, show_internal: bool = True,
                 swing_tol_atr: float = 0.05, atr_period: int = 14):
        self._validate(df)
        self.df = df.copy()
        self.swing_length = swing_length
        self.internal_length = internal_length
        self.show_internal = show_internal
        self.swing_tol_atr = swing_tol_atr
        self.atr_period = atr_period
        self._atr = self._compute_atr()
        self._levels: List[BOSLevel] = []

    def detect_all(self) -> List[BOSLevel]:
        self._levels = []
        self._run(self.swing_length, internal=False)
        if self.show_internal:
            self._run(self.internal_length, internal=True)
        self._levels.sort(key=lambda lv: lv.break_index)
        return self._levels

    def _run(self, L: int, internal: bool):
        h = self.df["high"].values
        l = self.df["low"].values
        c = self.df["close"].values
        times = self.df.index
        n = len(self.df)

        intra: Optional[int] = None   # 0 = up-leg, 1 = down-leg
        up: Optional[tuple] = None    # (price, idx) last swing high
        dn: Optional[tuple] = None    # (price, idx) last swing low
        # Range levels: the extreme swing since the last break on that side.
        # Unlike up/dn these never demote — a lower high does not replace the
        # range high, so a continuation BOS still has the real boundary to
        # clear after a shallow pullback.
        hi_ext: Optional[tuple] = None
        lo_ext: Optional[tuple] = None
        upside = 0                    # swing-high level armed
        downside = 0                  # swing-low level armed
        moving = 0                    # trend state: 1 up, -1 down

        for t in range(L, n):
            cand = t - L
            # Swings first (same-bar order as the script). Within tolerance
            # so multi-tapped near-equal levels still form swings; the flip
            # guard below prevents duplicate swings.
            tol = self.swing_tol_atr * self._atr[cand]
            if h[cand] >= max(h[cand + 1:t + 1]) - tol:
                if hi_ext is None or h[cand] > hi_ext[0]:
                    hi_ext = (float(h[cand]), cand)
                if intra != 0:
                    intra = 0
                    up = (float(h[cand]), cand)
                    upside = 1
            elif l[cand] <= min(l[cand + 1:t + 1]) + tol:
                if lo_ext is None or l[cand] < lo_ext[0]:
                    lo_ext = (float(l[cand]), cand)
                if intra != 1:
                    intra = 1
                    dn = (float(l[cand]), cand)
                    downside = 1
            # Then close-through crosses (one-shot per level).
            #
            # Two kinds of bullish level sit overhead: the last swing high
            # (the pullback high a CHoCH takes out) and the range high (the
            # highest swing high since the range last expanded). A pullback
            # pivot must NOT erase the range level — the boundary a
            # continuation BOS still has to clear. When both go on one bar
            # the nearer swing is reported, exactly as the pivot-only state
            # machine did, and the range take is flagged so structure
            # consumers that track pivots (the IDM gate) can ignore it.
            taken_up = (up if (up is not None and upside
                               and c[t - 1] <= up[0] < c[t]) else None)
            taken_hi = (hi_ext if (hi_ext is not None
                                   and c[t - 1] <= hi_ext[0] < c[t]) else None)
            if taken_up is not None or taken_hi is not None:
                if taken_up is not None:
                    lvl, from_range = taken_up, False
                else:
                    lvl, from_range = taken_hi, True
                self._levels.append(BOSLevel(
                    direction=BOSDirection.BULLISH,
                    price=lvl[0],
                    extreme_index=lvl[1],
                    break_index=t,
                    candle_time=times[t],
                    is_choch=moving < 0,
                    internal=internal,
                    from_range=from_range,
                    forming_candle_indices=[lvl[1], t],
                ))
                if taken_up is not None:
                    upside = 0
                if taken_hi is not None:
                    # Upside expansion: the range re-bases around the new
                    # leg, so both boundaries start fresh.
                    hi_ext = None
                    lo_ext = None
                moving = 1
            elif hi_ext is not None and c[t] > hi_ext[0]:
                # Armed under the close (gap/flip): it can never print a
                # cross, so retire it rather than reviving it much later.
                hi_ext = None
            taken_dn = (dn if (dn is not None and downside
                               and c[t - 1] >= dn[0] > c[t]) else None)
            taken_lo = (lo_ext if (lo_ext is not None
                                   and c[t - 1] >= lo_ext[0] > c[t]) else None)
            if taken_dn is not None or taken_lo is not None:
                if taken_dn is not None:
                    lvl, from_range = taken_dn, False
                else:
                    lvl, from_range = taken_lo, True
                self._levels.append(BOSLevel(
                    direction=BOSDirection.BEARISH,
                    price=lvl[0],
                    extreme_index=lvl[1],
                    break_index=t,
                    candle_time=times[t],
                    is_choch=moving > 0,
                    internal=internal,
                    from_range=from_range,
                    forming_candle_indices=[lvl[1], t],
                ))
                if taken_dn is not None:
                    downside = 0
                if taken_lo is not None:
                    # Downside expansion mirrors the bullish re-base.
                    lo_ext = None
                    hi_ext = None
                moving = -1
            elif lo_ext is not None and c[t] < lo_ext[0]:
                lo_ext = None

    @property
    def levels(self) -> List[BOSLevel]:
        return self._levels

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
