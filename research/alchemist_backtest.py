"""
alchemist_backtest.py — mechanical backtest of the Alchemist MSNR strategy
on real XAUUSDm history (Exness feed, cached by cache_history.py).

Mirrors mql5/Experts/MSNR_Alchemist.mq5 rule-for-rule so the Python replay
validates the EA:

  DIRECTION  D1 external structure (confirmed close-price pivots) must be
             broken in the same direction on H1 — else WAIT.
  LEVELS     H4(+D1): A/V levels (close of the first candle of an
             opposite-colour pair), GAP levels (same-colour pair with an
             untraded band >= gap_min x ATR), OCL levels (one per
             same-colour run: close of the FIRST candle of the run).
  LIFECYCLE  replayed on the level's NATIVE timeframe at book-rebuild time:
             wick touch consumes freshness (fresh->unfresh, touches++),
             a body close beyond price + break_buf x ATR breaks the level.
  TRIGGER    on a closed M30 bar: a fresh right-side level within reach,
             reached by price in the last 6 bars without an M30 body close
             through it (the reaction), then an M30 body close through the
             last confirmed minor swing (pivot window w) in the level's
             direction — the structure shift.
  ENTRY      market at the trigger bar close.
  STOP       beyond the reaction extreme (last 12 M30 bars) + sl_buf x ATR(M30).
  TARGET     nearest opposing UNBROKEN level ahead that clears the stop
             distance (TPMode=level) or fixed RR (TPMode=fixed).
             Trade skipped if RR < min_rr.
  SESSION    optional London/NY filter (UTC hours 7..19 inclusive).
  TIME EXIT  flat after time_exit_bars M30 bars.

Win/loss resolved intrabar on M5 (real ticks in the MT5 tester are the
authoritative loop; M5 resolution is the offline approximation).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
SYMBOL = "XAUUSDm"

P = dict(
    gap_min_atr=0.10,
    ocl_run_min=2,
    h4_bars=300,
    d1_bars=60,
    level_max_age=300,        # bars of the level's own TF
    break_buf_atr=0.10,
    uses_h4=2,
    uses_d1=4,
    require_fresh=True,
    story_pivot=3,
    bias_mode="d1_h1",        # "d1_h1" (strict) | "d1" (D1-only direction)
    swing_pivot=2,
    trig_after_touch=8,       # trigger close must be within N M30 bars of the touch
    swing_near_atr=0.75,      # broken minor swing must sit within X ATR of the level
    require_sweep=False,      # wick THROUGH the level then close-back
    reach_bars=12,            # level-touch lookback window (M30 bars)
    sl_buf_atr=0.10,
    min_rr=1.5,
    tp_mode="level",          # "level" | "fixed_rr"
    fixed_rr=2.0,
    entry_style="trigger",    # "trigger" (after M30 swing break) | "sweep" (at the close-back)
    trigger_required=True,  # if False: enter on level reaction alone (touch + close-back), no swing break
    # ---- F1 Confirmation Entry (video_9) ----
    f1_module=False,          # HTF D1 key-level rejection + LTF structure shift entry
    f1_rej_buf_atr=0.25,      # wick must pierce HTF level by >= this x ATR to count as rejection
    time_exit_bars=200,
    session_filter=True,
    session_start=7,
    session_end=20,
    max_dist_atr=3.0,
    entry_tf="M30",             # entry/decision timeframe: M30 (baseline) | M15 (2x frequency)
    max_candidates=1,           # max nearest level candidates tried per bar (F6 top-N)
    # ---- QM module (Task 15) ----
    qm_module=False,          # QM failed-flip levels as strong S/R (OFF = baseline)
    qm_bos_atr=0.8,           # QM quality gate: breakout body >= 0.8 x ATR (real BOS, not wick)
    qm_st_multiplier=0.70,    # stQM (second+ retest) size multiplier (ftQM = full)
    qm_grade_bonus=1.0,       # grade bonus for QM levels (strong S/R)
    # ---- PD gate (Task 16) ----
    pd_gate=False,            # long only in D1 discount, short only in premium; EQ = no trade
    pd_eq_band=0.05,          # equilibrium band around 0.5 (0.45-0.55)
    # ---- EMS module (Task 17) ----
    ems_module=False,         # engulfing-fail flipped zones as strong S/R (OFF = baseline)
    ems_grade_bonus=1.0,      # grade bonus for flipped engulfing zones
    ems_uses=2,               # EMS zone use budget (2-times rule)
    ems_buf=0.05,             # flip buffer x ATR (M30)
    # ---- APA consumption gate (Task 18) ----
    consume_gate=False,       # skip levels whose zone depth is >=50% used since birth (APA5-01)
    # ---- management layer (docs/specs/2026-11-14-management-layer.md) ----
    mgmt=False,             # regression mode: identical to the 2026-11-14 baseline
    grade_min=4.0,          # admission gate (P11-06)
    grade_aplus=5.0,
    size_a=0.70,            # A-grade size (P11-06, V5-02)
    size_b=0.50,            # B-grade size (V5-02 "reduce risk" extension; logged)
    tp1_rr=1.5,             # TP1 = 1:1.5 RR (P11-03)
    tp1_close=0.50,         # close 50% at TP1 (P11-03)
    tp2_close=0.30,         # close 30% at TP2/level (P11-03)
    be_after_tp1=True,      # SL -> breakeven after TP1 (P11-03, PH10-03)
    mgmt_profile=1,         # 1 = partials ladder, 2 = obstacle mgmt (V11-02)
    obstacle_close=0.80,    # profile 2: close 80% at first obstacle (V11-02)
    max_losses_day=2,       # psych: stop after N losses/day (P11-05)
    max_reentry_zone=1,     # psych: max entries per zone/day (P11-05)
)

SUPPORT, RESIST = 1, -1


# ------------------------------------------------------------------- loading
_cache: dict = {}


def load(tf: str) -> pd.DataFrame:
    if tf not in _cache:
        df = pd.read_csv(os.path.join(DATA, f"{SYMBOL}_{tf}.csv"), parse_dates=["time"])
        df = df.set_index("time").sort_index()
        _cache[tf] = df
    return _cache[tf]


def atr_series(df: pd.DataFrame, period=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


# ------------------------------------------------------------------ storyline
def _pivot_break_dir(c: np.ndarray, w: int) -> int:
    """Last confirmed close-pivot break direction: +1 up, -1 down, 0 none.
    Vectorized: pivot high = close equals the max of its centred window
    (ties allowed — matches the EA's PivotBias)."""
    n = len(c)
    s = pd.Series(c)
    win_hi = s.rolling(2 * w + 1, center=True, min_periods=2 * w + 1).max().values
    win_lo = s.rolling(2 * w + 1, center=True, min_periods=2 * w + 1).min().values
    is_h = np.nan_to_num(win_hi, nan=np.inf) <= c      # c == window max (no NaN edges)
    is_l = np.nan_to_num(win_lo, nan=-np.inf) >= c
    hi_idx = np.flatnonzero(is_h)
    lo_idx = np.flatnonzero(is_l)
    if hi_idx.size == 0 or lo_idx.size == 0:
        return 0
    last_h, last_l = int(hi_idx[-1]), int(lo_idx[-1])
    iu = idn = -1
    after_h = c[last_h + 1:] > c[last_h]
    after_l = c[last_l + 1:] < c[last_l]
    if after_h.any():
        iu = last_h + 1 + int(np.argmax(after_h))
    if after_l.any():
        idn = last_l + 1 + int(np.argmax(after_l))
    if iu < 0 and idn < 0:
        return 0
    if idn < 0 or (iu >= 0 and iu >= idn):
        return 1
    return -1


def storyline(d1: pd.DataFrame, h1: pd.DataFrame, ts: pd.Timestamp) -> int:
    d1i, d1c = d1.index, d1["close"].values
    # only bars that had CLOSED before ts (exclude the forming bar)
    dp = d1i.searchsorted(ts - timedelta(days=1), side="right")
    d1v = d1c[max(0, dp - 120): dp]    # EA parity: 120 D1 closes
    if len(d1v) < 60:
        return 0
    a = _pivot_break_dir(d1v, P["story_pivot"])
    if a == 0:
        return 0
    if P.get("bias_mode", "d1_h1") == "d1":
        return a
    h1c = h1["close"].values
    hp = h1.index.searchsorted(ts - timedelta(hours=1), side="right")
    h1v = h1c[max(0, hp - 400): hp]
    if len(h1v) < 60:
        return 0
    b = _pivot_break_dir(h1v, P["story_pivot"])
    if a == b:
        return a
    return 0


# ------------------------------------------------------------------ level book
@dataclass
class Level:
    price: float
    side: int          # SUPPORT / RESIST
    born: pd.Timestamp
    tf: str            # "H4" | "D1"
    kind: str          # A / V / GAP / OCL
    fresh: bool = True
    touches: int = 0
    broken: bool = False
    birth_extreme: float = 0.0   # AOL depth anchor: low of birth candle (support) / high (resist)
    min_close: float = float('inf')   # min close since birth (consumption tracking)
    max_close: float = float('-inf')  # max close since birth (consumption tracking)


@dataclass
class QMLevel:
    price: float
    side: int          # strong role the QM now plays (SUPPORT/RESIST)
    tf: str
    born: pd.Timestamp  # bar time of the break that formed the QM
    tested: int = 0     # retest count since formation
    armed: bool = True  # waiting for first retest (ftQM vs stQM)


@dataclass
class EMSBox:
    lo: float           # engulfed candle body low
    hi: float           # engulfed candle body high
    side: int           # role the zone plays (SUPPORT=bullish-engulf zone, RESIST=bearish-engulf zone)
    formed_i: int       # M30 bar index of formation
    flipped: bool = False
    tested: int = 0


def _ems_pseudo(ez: EMSBox):
    """Pseudo-level for EMS zone grading (not fresh, M30 TF, touched count)."""
    from types import SimpleNamespace
    return SimpleNamespace(tf="EMS", kind="EG", price=0.5 * (ez.lo + ez.hi),
                           fresh=False, touches=ez.tested)


def _scan_tf(df: pd.DataFrame, tf: str, gap_min_atr: float, ocl_run_min: int,
             a: pd.Series, out: List[tuple]) -> None:
    """Scan closed bars; out appends (Level, birth_position_in_df)."""
    n = len(df)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    av = a.values
    idx = df.index
    for i in range(1, n - 1):
        t = idx[i]
        av_i = av[i]
        if np.isnan(av_i) or av_i <= 0:
            continue
        col_i = c[i] > o[i]
        col_j = c[i + 1] > o[i + 1]
        born = t
        if col_i and not col_j:
            out.append((Level(c[i], RESIST, born, tf, "A", birth_extreme=h[i]), i))
        elif not col_i and col_j:
            out.append((Level(c[i], SUPPORT, born, tf, "V", birth_extreme=l[i]), i))
        elif col_i and col_j:
            if o[i + 1] - c[i] >= gap_min_atr * av_i:
                out.append((Level(c[i], SUPPORT, born, tf, "GAP", birth_extreme=l[i]), i))
        else:
            if c[i] - o[i + 1] >= gap_min_atr * av_i:
                out.append((Level(c[i], RESIST, born, tf, "GAP", birth_extreme=h[i]), i))
        # OCL: one level per run — the first candle of a same-colour run
        run = 1
        j = i + 1
        while j < n and (c[j] > o[j]) == col_i:
            run += 1
            j += 1
        if run >= ocl_run_min:
            out.append((Level(c[i], SUPPORT if col_i else RESIST, born, tf, "OCL",
                              birth_extreme=(l[i] if col_i else h[i])), i))


def _replay_life(lv: Level, op: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray,
                 born_i: int, buf: float, qm_bos_atr: float, atr_val: float,
                 qms_out: List[QMLevel], tf: str, born_ts: pd.Timestamp) -> None:
    """Vectorized lifecycle: touches counted up to the first body break.
    When a level breaks with a real body (breakout body >= qm_bos_atr x ATR)
    it spawns a QM level at the break price playing the flipped role.
    Arrays are chronological; born_i = birth position; bars after birth drive lifecycle."""
    n = len(cl)
    if born_i + 1 >= n:
        return
    if lv.side == SUPPORT:
        touches = lo[born_i + 1:] <= lv.price
        breaks = cl[born_i + 1:] < lv.price - buf
    else:
        touches = hi[born_i + 1:] >= lv.price
        breaks = cl[born_i + 1:] > lv.price + buf
    if breaks.any():
        first_break = int(np.argmax(breaks))
        lv.broken = True
        lv.touches = int(touches[: first_break + 1].sum())
        # consumption tracking: min/max close since birth up to break point
        seg_end = born_i + 1 + first_break + 1
        seg = cl[born_i + 1: seg_end]
        lv.min_close = float(seg.min()) if seg.size else float('inf')
        lv.max_close = float(seg.max()) if seg.size else float('-inf')
        # QM quality gate: level must have been touched/tested (failed flip) AND
        # breakout body >= qm_bos_atr x ATR (real BOS, not a wick)
        j = born_i + 1 + first_break
        body = abs(float(cl[j]) - float(op[j]))
        if lv.touches >= 1 and body >= qm_bos_atr * atr_val:
            qms_out.append(QMLevel(price=lv.price, side=(-lv.side), tf=tf,
                                   born=born_ts, tested=0, armed=True))
    else:
        lv.touches = int(touches.sum())
        seg = cl[born_i + 1:]
        lv.min_close = float(seg.min()) if seg.size else float('inf')
        lv.max_close = float(seg.max()) if seg.size else float('-inf')
    lv.fresh = lv.touches == 0


class Book:
    """Level book rebuilt per closed H4 bar (mirrors the EA)."""

    def __init__(self):
        self.levels: List[Level] = []
        self.qms: List[QMLevel] = []
        self.ems_zones: List[EMSBox] = []
        self.h4 = load("H4")
        self.d1 = load("D1")
        self.a_h4 = atr_series(self.h4)
        self.a_d1 = atr_series(self.d1)
        self.built_on: Optional[pd.Timestamp] = None

    def rebuild(self, ts: pd.Timestamp) -> None:
        # bars that had CLOSED before the decision instant (no forming bar —
        # a forming bar's final OHLC reaches hours past ts: look-ahead)
        h4 = self.h4[self.h4.index + timedelta(hours=4) <= ts]
        d1 = self.d1[self.d1.index + timedelta(days=1) <= ts]
        if len(h4) < 40 or len(d1) < 20:
            return
        h4 = h4.tail(P["h4_bars"])
        d1 = d1.tail(P["d1_bars"])
        lvls: List[tuple] = []
        a4 = self.a_h4.reindex(h4.index)
        ad = self.a_d1.reindex(d1.index)
        _scan_tf(h4, "H4", P["gap_min_atr"], P["ocl_run_min"], a4, lvls)
        _scan_tf(d1, "D1", P["gap_min_atr"] * 2.0, P["ocl_run_min"], ad, lvls)
        # age filter + lifecycle on native TF (positions come straight from the scan)
        hi4, lo4, cl4 = h4["high"].values, h4["low"].values, h4["close"].values
        op4, opd = h4["open"].values, d1["open"].values
        hid, lod, cld = d1["high"].values, d1["low"].values, d1["close"].values
        buf4 = P["break_buf_atr"] * float(a4.iloc[-1])
        bufd = P["break_buf_atr"] * float(ad.iloc[-1])
        atr4 = float(a4.iloc[-1]); atrd = float(ad.iloc[-1])
        keep: List[Level] = []
        qms_collected: List[QMLevel] = []
        qm_bos = P["qm_bos_atr"] if P["qm_module"] else 999.0  # gate off when module off
        for lv, born_i in lvls:
            age = (h4 if lv.tf == "H4" else d1).shape[0] - 1 - born_i
            if age > P["level_max_age"]:
                continue
            _replay_life(lv, op4 if lv.tf == "H4" else opd,
                         hi4 if lv.tf == "H4" else hid,
                         lo4 if lv.tf == "H4" else lod,
                         cl4 if lv.tf == "H4" else cld,
                         born_i, buf4 if lv.tf == "H4" else bufd,
                         qm_bos, atr4 if lv.tf == "H4" else atrd,
                         qms_collected, lv.tf,
                         h4.index[born_i] if lv.tf == "H4" else d1.index[born_i])
            keep.append(lv)
        self.levels = keep
        self.qms = qms_collected
        self.built_on = h4.index[-1]

    def qm_candidates(self, side: int, px_now: float, max_dist: float,
                      k: int, m30_cl: np.ndarray, m30_op: np.ndarray,
                      m30_hi: np.ndarray, m30_lo: np.ndarray,
                      a30v: np.ndarray, nm: int) -> List[tuple]:
        """QM retest candidates near price. A QM is 'retested' when price
        touches its level within the last reach_bars bars without closing
        through it (reaction), i.e. the same reaction logic as normal levels.
        Returns list of (QMLevel, touch_bar_index)."""
        out: List[tuple] = []
        reach = P["reach_bars"]
        for qm in self.qms:
            if not qm.armed:
                continue
            if qm.side != side:
                continue
            if abs(qm.price - px_now) > max_dist:
                continue
            # retest within reach window: wick reaches QM price, body does not close through
            reached = False
            touch_bar = -1
            for i in range(max(1, k - reach + 1), k + 1):
                a_i = a30v[i]
                if np.isnan(a_i):
                    continue
                if qm.side == SUPPORT:
                    if m30_lo[i] <= qm.price + 0.05 * a_i:
                        reached = True
                        if touch_bar < 0:
                            touch_bar = i
                    if m30_cl[i] < qm.price - 0.10 * a_i:
                        reached = False   # closed through -> QM invalidated
                        break
                else:
                    if m30_hi[i] >= qm.price - 0.05 * a_i:
                        reached = True
                        if touch_bar < 0:
                            touch_bar = i
                    if m30_cl[i] > qm.price + 0.10 * a_i:
                        reached = False
                        break
            if reached and touch_bar >= 0:
                out.append((qm, touch_bar))
        return out

    def ems_candidates(self, side: int, px_now: float, max_dist: float,
                       k: int, m30_cl: np.ndarray, m30_hi: np.ndarray,
                       m30_lo: np.ndarray, a30v: np.ndarray, nm: int) -> List[tuple]:
        """EMS engulfing-fail flipped zones as strong S/R. Candidate if zone
        role matches trade side and price retests zone (wick reaches, body
        does not close through) within reach window."""
        out: List[tuple] = []
        reach = P["reach_bars"]
        for ez in self.ems_zones:
            if ez.flipped and ez.tested >= P["ems_uses"]:
                continue
            if ez.side != side:
                continue
            mid = 0.5 * (ez.lo + ez.hi)
            if abs(mid - px_now) > max_dist:
                continue
            reached = False
            touch_bar = -1
            for i in range(max(1, k - reach + 1), k + 1):
                a_i = a30v[i]
                if np.isnan(a_i):
                    continue
                if ez.side == SUPPORT:
                    if m30_lo[i] <= ez.lo + 0.05 * a_i:
                        reached = True
                        if touch_bar < 0:
                            touch_bar = i
                    if m30_cl[i] < ez.lo - 0.10 * a_i:
                        reached = False
                        break
                else:
                    if m30_hi[i] >= ez.hi - 0.05 * a_i:
                        reached = True
                        if touch_bar < 0:
                            touch_bar = i
                    if m30_cl[i] > ez.hi + 0.10 * a_i:
                        reached = False
                        break
            if reached and touch_bar >= 0:
                out.append((ez, touch_bar))
        return out

    def candidates(self, side: int, fresh_only: bool, uses: int) -> List[Level]:
        out = []
        for lv in self.levels:
            if lv.broken or lv.side != side:
                continue
            budget = P["uses_h4"] if lv.tf == "H4" else P["uses_d1"]
            if lv.touches >= min(budget, uses if uses < budget else budget):
                continue
            if fresh_only and not lv.fresh:
                continue
            out.append(lv)
        return out


def _consumed(lv: Level) -> bool:
    """APA5-01 consumption gate: an AOL is consumed if price has used >=50% of
    its zone depth since birth. For support: min close since birth <= midpoint
    of zone [birth_extreme, price]. For resist: max close >= midpoint."""
    mid = (lv.price + lv.birth_extreme) / 2.0
    if lv.side == SUPPORT:
        return lv.min_close <= mid
    return lv.max_close >= mid


# ----------------------------------------------------------------------
# Entry evaluation helper (used by both normal levels and QM retests).
# Returns dict(entry, sl, tp, risk, rr, touch_bar, sweep_bar) or None.
# ----------------------------------------------------------------------
def _eval_entry(side: int, dirn: int, lvl_price: float, k: int,
                m30_op: np.ndarray, m30_cl: np.ndarray, m30_hi: np.ndarray,
                m30_lo: np.ndarray, a30v: np.ndarray, nm: int,
                book_levels: List[Level], atr_k: float, P: dict) -> Optional[dict]:
    reach = P["reach_bars"]
    last = k

    # ---------- reaction: level touched in reach window, body not closed through ----------
    reached = reacted = False
    touch_bar = -1
    for i in range(max(1, last - reach + 1), last + 1):
        a_i = a30v[i]
        if np.isnan(a_i):
            continue
        if side == SUPPORT:
            if m30_lo[i] <= lvl_price + 0.05 * a_i:
                reached = True
                if touch_bar < 0:
                    touch_bar = i
            if m30_cl[i] < lvl_price - 0.10 * a_i:
                reacted = True
                break
        else:
            if m30_hi[i] >= lvl_price - 0.05 * a_i:
                reached = True
                if touch_bar < 0:
                    touch_bar = i
            if m30_cl[i] > lvl_price + 0.10 * a_i:
                reacted = True
                break
    if not reached or reacted:
        return(None)

    # ---------- optional CRT-style sweep ----------
    sweep_bar = -1
    if P["require_sweep"]:
        for i in range(max(1, last - reach + 1), last + 1):
            a_i = a30v[i]
            if side == SUPPORT:
                bar_swept = (m30_lo[i] < lvl_price - 0.05 * a_i
                             and m30_cl[i] > lvl_price)
            else:
                bar_swept = (m30_hi[i] > lvl_price + 0.05 * a_i
                             and m30_cl[i] < lvl_price)
            if bar_swept and sweep_bar < 0:
                sweep_bar = i
        if sweep_bar < 0:
            return(None)

    # ---------- session filter ----------
    # (applied in the caller via t.hour; kept here for completeness of gate order)

    # ---------- entry style ----------
    sweep_bar2 = sweep_bar
    entry = sl = tp = 0.0
    if P.get("entry_style", "trigger") == "sweep":
        if sweep_bar2 != last:
            return(None)
        entry = float(m30_cl[last])
        if dirn > 0:
            ext = float(m30_lo[sweep_bar2: last + 1].min())
            sl = ext - P["sl_buf_atr"] * atr_k
        else:
            ext = float(m30_hi[sweep_bar2: last + 1].max())
            sl = ext + P["sl_buf_atr"] * atr_k
    else:
        # ---------- M30 structure-shift trigger ----------
        cl = m30_cl
        if P.get("trigger_required", True):
            w = P["swing_pivot"]
            swing_j = -1
            swing_px = 0.0
            for j in range(k - w, w, -1):
                win = cl[j - w: j + w + 1]
                if dirn > 0 and cl[j] == win.min():
                    swing_j, swing_px = j, cl[j]
                    break
                if dirn < 0 and cl[j] == win.max():
                    swing_j, swing_px = j, cl[j]
                    break
            if swing_j < 0:
                return(None)
            trig = False
            for x in range(swing_j + 1, k + 1):
                if (dirn > 0 and cl[x] > swing_px) or (dirn < 0 and cl[x] < swing_px):
                    trig = True
                    break
            if not trig:
                return(None)
            # sequencing: the shift must follow the touch and live at the level
            if touch_bar >= 0 and (k - touch_bar) > P["trig_after_touch"]:
                return(None)
            if abs(swing_px - lvl_price) > P["swing_near_atr"] * atr_k:
                return(None)
        else:
            # reaction-only entry: swing lives at the level by construction
            swing_px = lvl_price
        entry = float(cl[k])
        seg_from = max(1, last - 11)
        ext = m30_lo[seg_from] if dirn > 0 else m30_hi[seg_from]
        for i in range(seg_from + 1, last + 1):
            if dirn > 0:
                ext = min(ext, float(m30_lo[i]))
            else:
                ext = max(ext, float(m30_hi[i]))
        sl = (ext - P["sl_buf_atr"] * atr_k) if dirn > 0 else (ext + P["sl_buf_atr"] * atr_k)

    risk = abs(entry - sl)
    if risk <= 0:
        return(None)

    # ---------- TP ----------
    if P["tp_mode"] == "level":
        opp = RESIST if dirn > 0 else SUPPORT
        best = None
        best_d = 1e30
        for o in book_levels:
            if o.broken or o.side != opp:
                continue
            ahead = (o.price - entry) if dirn > 0 else (entry - o.price)
            if ahead <= risk:
                continue
            if ahead < best_d:
                best_d, best = ahead, o.price
        if best is None:
            return(None)
        tp = best
    else:
        tp = entry + dirn * P["fixed_rr"] * risk

    rr = abs(tp - entry) / risk
    if rr < P["min_rr"]:
        return(None)

    return({"entry": entry, "sl": sl, "tp": tp, "risk": risk, "rr": rr,
            "touch_bar": touch_bar, "sweep_bar": sweep_bar})


# ----------------------------------------------------------------------
# F1 Confirmation Entry (video_9): HTF (D1) key-level rejection on LTF, then a
# structure shift in the trade direction -> enter at the close.
# Returns a setup dict like _eval_entry or None.
# ----------------------------------------------------------------------
def _f1_confirmation_entry(side: int, dirn: int, px: float, k: int,
                           m30_op: np.ndarray, m30_cl: np.ndarray,
                           m30_hi: np.ndarray, m30_lo: np.ndarray,
                           a30v: np.ndarray, book, atr_k: float, P: dict) -> Optional[dict]:
    if not P.get("f1_module"):
        return None
    if k < 2:
        return None
    atr = atr_k
    if np.isnan(atr) or atr <= 0:
        return None
    reach = P["reach_bars"]
    buf = P["f1_rej_buf_atr"] * atr
    # HTF (D1) key levels on the trade side near price, not broken, within reach
    cand_lvls = [lv for lv in book.levels
                 if lv.tf == "D1" and lv.side == side and not lv.broken
                 and abs(lv.price - px) <= P["max_dist_atr"] * atr]
    if not cand_lvls:
        return None
    # rejection on the last closed bar (k-1): wick pierced the HTF level but
    # closed back on the trade side
    o_prev, c_prev, h_prev, l_prev = m30_op[k - 1], m30_cl[k - 1], m30_hi[k - 1], m30_lo[k - 1]
    for lv in cand_lvls:
        lp = lv.price
        rejected = False
        rej_extreme = lp
        if side == SUPPORT:   # bullish: pierced below support, closed back above
            if l_prev < lp - buf and c_prev > lp:
                rejected = True
                rej_extreme = l_prev
        else:                 # bearish: pierced above resistance, closed back below
            if h_prev > lp + buf and c_prev < lp:
                rejected = True
                rej_extreme = h_prev
        if not rejected:
            continue
        # structure-shift trigger: close breaks the minor swing in trade direction
        cl = m30_cl
        w = P["swing_pivot"]
        swing_j = -1
        swing_px = 0.0
        for j in range(k - w, w, -1):
            win = cl[j - w: j + w + 1]
            if dirn > 0 and cl[j] == win.min():
                swing_j, swing_px = j, cl[j]; break
            if dirn < 0 and cl[j] == win.max():
                swing_j, swing_px = j, cl[j]; break
        if swing_j < 0:
            continue
        trig = False
        for x in range(swing_j + 1, k + 1):
            if (dirn > 0 and cl[x] > swing_px) or (dirn < 0 and cl[x] < swing_px):
                trig = True; break
        if not trig:
            continue
        if abs(swing_px - lp) > P["swing_near_atr"] * atr:
            continue
        entry = float(cl[k])
        risk = abs(entry - rej_extreme)
        if risk <= 0:
            continue
        # TP: nearest opposing unbroken level ahead clearing risk, else fixed RR
        opp = RESIST if dirn > 0 else SUPPORT
        tp = None
        best_d = 1e30
        for o in book.levels:
            if o.broken or o.side != opp:
                continue
            ahead = (o.price - entry) if dirn > 0 else (entry - o.price)
            if ahead <= risk:
                continue
            if ahead < best_d:
                best_d, tp = ahead, o.price
        if tp is None:
            tp = entry + dirn * P["fixed_rr"] * risk
        rr = abs(tp - entry) / risk
        if rr < P["min_rr"]:
            continue
        return({"entry": entry, "sl": rej_extreme, "tp": tp, "risk": risk, "rr": rr,
                "touch_bar": k - 1, "sweep_bar": -1})
    return None


def _f1_pseudo(px: float):
    """Pseudo-level for F1 Confirmation Entry grading (D1 TF, confirmation kind)."""
    from types import SimpleNamespace
    return SimpleNamespace(tf="D1", kind="CONF", price=float(px), fresh=False, touches=0)


# ---------------------------------------------------------------------- run
def run(start, end, params=None):
    if params:
        P.update(params)
    book = Book()
    h1 = load("H1")
    m30 = load(P.get("entry_tf", "M30"))
    m5 = load("M5")
    d1 = load("D1")
    nm = len(m30)
    nd1 = len(d1)
    d1_idx = d1.index

    trades: List[dict] = []
    open_trade: Optional[dict] = None
    entry_i: Optional[int] = None
    losses_day: dict = {}     # mgmt psych: losses per calendar day
    zone_day: dict = {}       # mgmt psych: entries per (day, zone)

    a30 = atr_series(m30)
    a30v = a30.values
    m30_lo = m30["low"].values
    m30_hi = m30["high"].values
    m30_cl = m30["close"].values
    m5_lo = m5["low"]
    m5_hi = m5["high"]
    m5i = {t: k for k, t in enumerate(m5.index)}

    seg12 = 12   # reaction extreme window (EA parity)

    bias = 0
    cur_h1_closed: Optional[pd.Timestamp] = None
    h1_idx = h1.index

    for k, t in enumerate(m30.index):
        if not (start <= t < end):
            continue

        # ---------- manage the open trade (M5 intrabar resolution) ----------
        if open_trade:
            tr = open_trade
            j0 = m5i.get(t - timedelta(minutes=30))
            j1 = m5i.get(t)
            exit_px = reason = None
            done = False
            if j0 is not None and j1 is not None:
                lo5 = m5_lo.iloc[j0 + 1: j1 + 1].values
                hi5 = m5_hi.iloc[j0 + 1: j1 + 1].values
                d = tr["dir"]
                f_sl = (lo5 <= tr["sl"]) if d > 0 else (hi5 >= tr["sl"])
                f_tp = (hi5 >= tr["tp"]) if d > 0 else (lo5 <= tr["tp"])
                tp1v = tr["tp1"] if P["mgmt"] else None
                f_tp1 = None
                if tp1v is not None and not tr["tp1_done"]:
                    f_tp1 = (hi5 >= tp1v) if d > 0 else (lo5 <= tp1v)

                def _real(px: float, frac: float) -> None:
                    tr["r"] += frac * ((px - tr["entry"]) * d) / tr["risk"]

                if f_sl.any():
                    # pessimistic (parity with baseline): stop first —
                    # the whole remaining fraction exits at SL
                    _real(tr["sl"], tr["open_frac"])
                    tr["open_frac"] = 0.0
                    exit_px, reason = tr["sl"], "LOSS"
                    done = True
                elif f_tp1 is not None and f_tp1.any():
                    # TP1 partial -> move SL to breakeven
                    take = min(tr["_p1c"], tr["open_frac"])
                    _real(tp1v, take)
                    tr["open_frac"] -= take
                    tr["tp1_done"] = True
                    if P["be_after_tp1"]:
                        tr["sl"] = max(tr["sl"], tr["entry"]) if d > 0 else min(tr["sl"], tr["entry"])
                    # same-bar TP pass-through (price passed TP1 toward TP):
                    if f_tp.any() and tr["open_frac"] > 1e-9:
                        take2 = min(P["tp2_close"], tr["open_frac"])
                        _real(tr["tp"], take2)
                        tr["open_frac"] -= take2
                        tr["runner"] = True
                elif f_tp.any():
                    if tr["runner"]:
                        # runner is active: the level TP closes whatever remains
                        _real(tr["tp"], tr["open_frac"])
                        tr["open_frac"] = 0.0
                        exit_px, reason = tr["tp"], "WIN"
                        done = True
                    elif tp1v is not None and ((d > 0 and tp1v >= tr["tp"]) or (d < 0 and tp1v <= tr["tp"])):
                        # collapsed ladder (TP1 == TP): 50% + 30% both at TP
                        take = min(P["tp1_close"], tr["open_frac"])
                        _real(tr["tp"], take)
                        tr["open_frac"] -= take
                        tr["tp1_done"] = True
                        if P["be_after_tp1"]:
                            tr["sl"] = max(tr["sl"], tr["entry"]) if d > 0 else min(tr["sl"], tr["entry"])
                        take2 = min(P["tp2_close"], tr["open_frac"])
                        _real(tr["tp"], take2)
                        tr["open_frac"] -= take2
                        tr["runner"] = True
                    else:
                        take = 1.0 if tp1v is None else min(P["tp2_close"], tr["open_frac"])
                        _real(tr["tp"], take)
                        tr["open_frac"] -= take
                        if tp1v is None:
                            exit_px, reason = tr["tp"], "WIN"
                            done = True
                        else:
                            tr["runner"] = True

            if not done:
                # runner trail: last confirmed M30 close-pivot in trade direction
                if P["mgmt"] and tr["runner"] and tr["open_frac"] > 1e-9:
                    w = P["swing_pivot"]
                    j = k - w
                    while j > w:
                        win = m30_cl[j - w: j + w + 1]
                        if tr["dir"] > 0 and m30_cl[j] == win.min():
                            tr["sl"] = max(tr["sl"], float(m30_cl[j]))
                            break
                        if tr["dir"] < 0 and m30_cl[j] == win.max():
                            tr["sl"] = min(tr["sl"], float(m30_cl[j]))
                            break
                        j -= 1
                if (k - entry_i) >= P["time_exit_bars"]:
                    exit_px = float(m30_cl[k])
                    reason = "TIME"
                    tr["r"] += tr["open_frac"] * ((exit_px - tr["entry"]) * tr["dir"]) / tr["risk"]
                    tr["open_frac"] = 0.0
                    done = True

            if done:
                tr["exit"] = exit_px
                tr["exit_reason"] = reason
                if P["mgmt"]:
                    # final label by realized R (BE = TP1 taken, rest at entry)
                    tr["reason"] = "WIN" if tr["r"] > 0.01 else ("LOSS" if tr["r"] < -0.01 else "BE")
                    if tr["r"] < -1e-9:
                        day = t.date()
                        losses_day[day] = losses_day.get(day, 0) + 1
                else:
                    tr["reason"] = reason
                trades.append(tr)
                open_trade = None
            continue

        # ---------- book per H4 bar ----------
        if book.built_on is None or book.built_on != _prev_closed_h4(t):
            book.rebuild(t)
            if not book.levels:
                continue
        if not book.levels:
            continue

        # ---------- storyline per H1 closed bar (cached) ----------
        pos = h1_idx.searchsorted(t, side="right") - 1
        h1_closed = h1_idx[pos] if pos >= 0 else None
        if h1_closed != cur_h1_closed:
            cur_h1_closed = h1_closed
            bias = storyline(load("D1"), h1, t) if h1_closed is not None else 0
        if bias == 0:
            continue

        px = m30_cl[k]
        atr_k = a30v[k]
        if np.isnan(atr_k) or atr_k <= 0:
            continue

        side = SUPPORT if bias > 0 else RESIST
        dirn = bias

        # ---------- PD gate (Task 16): long only in D1 discount, short only in premium ----------
        if P["pd_gate"]:
            dpos = int(d1_idx.searchsorted(t, side="right")) - 1
            if dpos >= 0:
                d1_hi = float(d1["high"].iloc[dpos])
                d1_lo = float(d1["low"].iloc[dpos])
                rng = d1_hi - d1_lo
                if rng > 0:
                    pdv = (px - d1_lo) / rng
                    eq_lo = 0.5 - P["pd_eq_band"]; eq_hi = 0.5 + P["pd_eq_band"]
                    if pdv < eq_lo:
                        if dirn < 0:
                            continue   # short not allowed in discount
                    elif pdv > eq_hi:
                        if dirn > 0:
                            continue   # long not allowed in premium
                    else:
                        continue       # equilibrium — no new entries

        # ---------- EMS engulfing-fail zone tracking (Task 17) ----------
        m30_op = m30["open"].values   # needed by QM / sweep body checks
        if P["ems_module"]:
            # engulfing candle detection on current closed bar k vs k-1
            o1, c1, h1_, l1 = m30_op[k-1], m30_cl[k-1], m30_hi[k-1], m30_lo[k-1]
            o2, c2, h2_, l2 = m30_op[k],   m30_cl[k],   m30_hi[k],   m30_lo[k]
            bull_eng = (c1 < o1) and (c2 > o2) and (c2 > o1) and (o2 < c1)   # body engulf
            bear_eng = (c1 > o1) and (c2 < o2) and (c2 < o1) and (o2 > c1)
            if bull_eng or bear_eng:
                # mark zone = engulfed candle body [min(o1,c1)..max(o1,c1)]
                ez_lo, ez_hi = min(o1, c1), max(o1, c1)
                # existing zone same price? refresh
                found = False
                for ez in book.ems_zones:
                    if abs(ez.lo - ez_lo) < 1e-9 and abs(ez.hi - ez_hi) < 1e-9:
                        found = True
                        ez.side = SUPPORT if bull_eng else RESIST   # role = direction of engulf
                        ez.flipped = False
                        ez.tested = 0
                        break
                if not found:
                    book.ems_zones.append(EMSBox(lo=ez_lo, hi=ez_hi,
                                                 side=SUPPORT if bull_eng else RESIST,
                                                 formed_i=k))
            # flip detection: price closes through an armed EMS zone -> flipped role
            # (skip zones formed on this same bar)
            for ez in book.ems_zones:
                if ez.formed_i == k:
                    continue
                if ez.flipped or ez.tested >= P["ems_uses"]:
                    continue
                if ez.side == SUPPORT and m30_cl[k] < ez.lo - P["ems_buf"] * atr_k:
                    ez.flipped = True; ez.side = RESIST; ez.tested = 0
                elif ez.side == RESIST and m30_cl[k] > ez.hi + P["ems_buf"] * atr_k:
                    ez.flipped = True; ez.side = SUPPORT; ez.tested = 0

        cands = book.candidates(side, P["require_fresh"], 10**9)
        if not cands:
            continue
        near = [lv for lv in cands if abs(lv.price - px) <= P["max_dist_atr"] * atr_k]

        # ---------- entry evaluation: normal level, then QM retest fallback ----------
        setup = None
        qm_obj = None
        qm_bonus = 0.0
        qm_st = False
        lvl_obj = None
        if near:
            # F6 top-N: try up to max_candidates nearest levels per bar until one
            # produces a valid setup (nearest first). max_candidates=1 = baseline.
            near_sorted = sorted(near, key=lambda o: abs(o.price - px))
            tried = 0
            for lv in near_sorted:
                if tried >= P["max_candidates"]:
                    break
                tried += 1
                # APA consumption gate (Task 18): skip if zone depth >=50% used since birth
                if P["consume_gate"] and _consumed(lv):
                    continue
                setup = _eval_entry(side, dirn, lv.price, k, m30_op, m30_cl, m30_hi,
                                    m30_lo, a30v, nm, book.levels, atr_k, P)
                if setup is not None:
                    lvl_obj = lv
                    break
        if setup is None and P["qm_module"]:
            qcands = book.qm_candidates(side, px, P["max_dist_atr"] * atr_k, k,
                                        m30_cl, m30_op, m30_hi, m30_lo,
                                        a30v, nm)
            if qcands:
                qm, _tb = min(qcands, key=lambda q: abs(q[0].price - px))
                setup = _eval_entry(side, dirn, qm.price, k, m30_op, m30_cl, m30_hi,
                                    m30_lo, a30v, nm, book.levels, atr_k, P)
                if setup is not None:
                    qm_obj = qm
                    qm.armed = False            # QM consumed at this retest
                    qm.tested += 1
                    qm_bonus = P["qm_grade_bonus"]
                    qm_st = qm.tested >= 2      # stQM on 2nd+ retest
                    lvl_obj = qm
        if setup is None and P["ems_module"]:
            ecands = book.ems_candidates(side, px, P["max_dist_atr"] * atr_k, k,
                                         m30_cl, m30_hi, m30_lo, a30v, nm)
            if ecands:
                ez, _tb = min(ecands, key=lambda e: abs(0.5 * (e[0].lo + e[0].hi) - px))
                ez_price = 0.5 * (ez.lo + ez.hi)
                setup = _eval_entry(side, dirn, ez_price, k, m30_op, m30_cl, m30_hi,
                                    m30_lo, a30v, nm, book.levels, atr_k, P)
                if setup is not None:
                    ez.tested += 1
                    qm_bonus = P["ems_grade_bonus"]
                    # EMS pseudo-level for grading (not fresh, M30 TF, touched)
                    lvl_obj = _ems_pseudo(ez)
        if setup is None and P["f1_module"]:
            f1s = _f1_confirmation_entry(side, dirn, px, k, m30_op, m30_cl,
                                         m30_hi, m30_lo, a30v, book, atr_k, P)
            if f1s is not None:
                setup = f1s
                lvl_obj = _f1_pseudo(px)
        if setup is None:
            continue
        entry, sl, tp, risk, rr = setup["entry"], setup["sl"], setup["tp"], setup["risk"], setup["rr"]
        swept = setup["sweep_bar"] >= 0

        # ---------- session filter ----------
        if P["session_filter"] and not (P["session_start"] <= t.hour < P["session_end"]):
            continue

        # ---------- management layer: grading + psych filters ----------
        size = 1.0
        tp1p = None
        if P["mgmt"]:
            day = t.date()
            if losses_day.get(day, 0) >= P["max_losses_day"]:
                continue
            zkey = (lvl_obj.tf if lvl_obj else "QM",
                    getattr(lvl_obj, "kind", "QM"),
                    round(getattr(lvl_obj, "price", 0.0), 0))
            if zone_day.get((day, zkey), 0) >= P["max_reentry_zone"]:
                continue
            score = ((1.0 if swept else 0.0)            # sweep at zone
                     + (1.0 if getattr(lvl_obj, "fresh", False) else 0.0)  # fresh level
                     + (1.0 if getattr(lvl_obj, "tf", "QM") == "D1" else 0.5)  # TF weight
                     + 1.0                               # storyline gate passed (V4-01)
                     + (0.5 if P["session_filter"] else 0.0)   # session weight
                     + (0.5 if rr >= 1.5 else 0.0)       # RR quality
                     - (0.5 if getattr(lvl_obj, "touches", 0) == 1 else 0.0)  # 2nd-touch derate
                     + qm_bonus)                         # QM strong S/R bonus
            if not swept and score > 4.5:                # C11: no sweep never A+
                score = 4.5
            if score < P["grade_min"]:
                continue
            size = (1.0 if score >= P["grade_aplus"]
                    else P["size_b"] if (qm_st and score >= 3.0)   # stQM reduced
                    else P["size_a"] if score >= 4.0
                    else P["size_b"])
            dbg_score = score

        open_trade = dict(
            dir=dirn, entry=entry, sl=sl, tp=tp, risk=risk, rr=rr,
            entry_time=t,
            level=f"{getattr(lvl_obj, 'tf', 'QM')}/{getattr(lvl_obj, 'kind', 'QM')}",
            level_price=getattr(lvl_obj, "price", entry),
            bias="BULL" if bias > 0 else "BEAR",
            size=size, tp1=None, tp1_done=False, open_frac=1.0, runner=False,
            r=0.0, score=(dbg_score if P["mgmt"] else None),
            qm_entry=(qm_obj is not None),
        )
        if P["mgmt"]:
            if P["mgmt_profile"] == 2:
                # profile B (V11-02): first obstacle = TP, close obstacle_close
                # there, SL->BE, remainder trails (implemented as a collapsed
                # ladder with the obstacle fraction)
                open_trade["tp1"] = tp
                open_trade["_p1c"] = 0.0
                open_trade["_p2c"] = P["obstacle_close"]
            else:
                tp1p = entry + dirn * P["tp1_rr"] * risk
                if (dirn > 0 and tp1p >= tp) or (dirn < 0 and tp1p <= tp):
                    tp1p = tp                                # ladder collapse
                open_trade["tp1"] = tp1p
                open_trade["_p1c"] = P["tp1_close"]
                open_trade["_p2c"] = P["tp2_close"]
            day = t.date()
            zkey = (getattr(lvl_obj, "tf", "QM"),
                    getattr(lvl_obj, "kind", "QM"),
                    round(getattr(lvl_obj, "price", 0.0), 0))
            zone_day[(day, zkey)] = zone_day.get((day, zkey), 0) + 1
        entry_i = k

    if open_trade:
        tr = open_trade
        px = float(m30["close"].iloc[-1])
        tr["exit"], tr["exit_reason"] = px, "EOD"
        tr["r"] += tr["open_frac"] * ((px - tr["entry"]) * tr["dir"]) / tr["risk"]
        if P["mgmt"]:
            tr["reason"] = "WIN" if tr["r"] > 0.01 else ("LOSS" if tr["r"] < -0.01 else "BE")
        else:
            tr["reason"] = "EOD"
        trades.append(tr)
    return trades


def _prev_closed_h4(t: pd.Timestamp) -> pd.Timestamp:
    """The last H4 bar that had CLOSED before t (book rebuild marker)."""
    h4 = load("H4")
    idx = h4.index
    pos = idx.searchsorted(t - timedelta(hours=4), side="right") - 1
    return idx[pos] if pos >= 0 else idx[0]


def report(trades: List[dict], save="alchemist_trades.csv"):
    if not trades:
        print("No trades.")
        return
    df = pd.DataFrame(trades)
    wins = df[df["reason"] == "WIN"]
    losses = df[df["reason"] == "LOSS"]
    outs = df[~df["reason"].isin(["WIN", "LOSS"])]
    wr = len(wins) / len(df) * 100
    print(f"trades={len(df)}  wins={len(wins)}  losses={len(losses)}  time-outs={len(outs)}")
    print(f"win rate={wr:.1f}%   total R={df['r'].sum():+.2f}   avg R={df['r'].mean():+.2f}   avg RR={df['rr'].mean():.2f}")
    if "size" in df.columns and (df["size"] != 1.0).any():
        wr_r = (df["r"] > 0.01).mean() * 100
        print(f"[mgmt] R-based WR={wr_r:.1f}%  weighted R(sum size*r)={(df['size']*df['r']).sum():+.2f}")
    for col in ("bias", "level"):
        print(f"by {col}:")
        for v, g in df.groupby(col):
            w = (g["reason"] == "WIN").sum()
            print(f"  {v}: n={len(g)} wr={w/len(g)*100:.0f}% R={g['r'].sum():+.1f}")
    df.to_csv(os.path.join(HERE, save), index=False)
    print(f"saved -> research/{save}")


if __name__ == "__main__":
    import sys
    start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else pd.Timestamp("2025-11-01")
    end = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2026-11-10")
    save = sys.argv[3] if len(sys.argv) > 3 else "alchemist_trades.csv"
    if len(sys.argv) > 4:                       # quick variant toggles: k=v,k=v
        for kv in sys.argv[4].split(","):
            key, val = kv.split("=")
            cur = P[key]
            P[key] = (val.lower() == "true") if isinstance(cur, bool) else type(cur)(val)
    print(f"window {start.date()} -> {end.date()}  save={save}")
    print(f"params={P}")
    tr = run(start, end)
    report(tr, save)
