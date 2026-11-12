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
    time_exit_bars=200,
    session_filter=True,
    session_start=7,
    session_end=20,
    max_dist_atr=3.0,
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
            out.append((Level(c[i], RESIST, born, tf, "A"), i))
        elif not col_i and col_j:
            out.append((Level(c[i], SUPPORT, born, tf, "V"), i))
        elif col_i and col_j:
            if o[i + 1] - c[i] >= gap_min_atr * av_i:
                out.append((Level(c[i], SUPPORT, born, tf, "GAP"), i))
        else:
            if c[i] - o[i + 1] >= gap_min_atr * av_i:
                out.append((Level(c[i], RESIST, born, tf, "GAP"), i))
        # OCL: one level per run — the first candle of a same-colour run
        run = 1
        j = i + 1
        while j < n and (c[j] > o[j]) == col_i:
            run += 1
            j += 1
        if run >= ocl_run_min:
            out.append((Level(c[i], SUPPORT if col_i else RESIST, born, tf, "OCL"), i))


def _replay_life(lv: Level, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray,
                 born_i: int, buf: float) -> None:
    """Vectorized lifecycle: touches counted up to the first body break.
    Arrays are the level's native-TF OHLC closes; born_i = birth position."""
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
    else:
        lv.touches = int(touches.sum())
    lv.fresh = lv.touches == 0


class Book:
    """Level book rebuilt per closed H4 bar (mirrors the EA)."""

    def __init__(self):
        self.levels: List[Level] = []
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
        hid, lod, cld = d1["high"].values, d1["low"].values, d1["close"].values
        buf4 = P["break_buf_atr"] * float(a4.iloc[-1])
        bufd = P["break_buf_atr"] * float(ad.iloc[-1])
        keep: List[Level] = []
        for lv, born_i in lvls:
            age = (h4 if lv.tf == "H4" else d1).shape[0] - 1 - born_i
            if age > P["level_max_age"]:
                continue
            _replay_life(lv, hi4 if lv.tf == "H4" else hid,
                         lo4 if lv.tf == "H4" else lod,
                         cl4 if lv.tf == "H4" else cld,
                         born_i, buf4 if lv.tf == "H4" else bufd)
            keep.append(lv)
        self.levels = keep
        self.built_on = h4.index[-1]

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


# ---------------------------------------------------------------------- run
def run(start, end, params=None):
    if params:
        P.update(params)
    book = Book()
    h1 = load("H1")
    m30 = load(P.get("entry_tf", "M30"))
    m5 = load("M5")

    trades: List[dict] = []
    open_trade: Optional[dict] = None
    entry_i: Optional[int] = None

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
            if j0 is not None and j1 is not None:
                lo5 = m5_lo.iloc[j0 + 1: j1 + 1]
                hi5 = m5_hi.iloc[j0 + 1: j1 + 1]
                exit_px, reason = None, None
                if tr["dir"] > 0:
                    hit_sl = lo5 <= tr["sl"]
                    hit_tp = hi5 >= tr["tp"]
                else:
                    hit_sl = hi5 >= tr["sl"]
                    hit_tp = lo5 <= tr["tp"]
                if hit_sl.any() and hit_tp.any():
                    # ambiguity: pessimistic — stop first
                    exit_px, reason = tr["sl"], "LOSS"
                elif hit_sl.any():
                    exit_px, reason = tr["sl"], "LOSS"
                elif hit_tp.any():
                    exit_px, reason = tr["tp"], "WIN"
            if exit_px is None and (k - entry_i) >= P["time_exit_bars"]:
                exit_px, reason = m30["close"].iloc[k], "TIME"
            if exit_px is not None:
                tr["exit"] = exit_px
                tr["reason"] = reason
                tr["r"] = ((exit_px - tr["entry"]) * tr["dir"]) / tr["risk"]
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

        cands = book.candidates(side, P["require_fresh"], 10**9)
        if not cands:
            continue
        near = [lv for lv in cands if abs(lv.price - px) <= P["max_dist_atr"] * atr_k]
        if not near:
            continue
        lv = min(near, key=lambda o: abs(o.price - px))

        # ---------- the reaction (last `reach_bars` closed bars incl. current) ----------
        reached = reacted = False
        touch_bar = -1
        for i in range(max(1, k - P["reach_bars"] + 1), k + 1):
            a_i = a30v[i]
            if np.isnan(a_i):
                continue
            if side == SUPPORT:
                if m30_lo[i] <= lv.price + 0.05 * a_i:
                    reached = True
                    if touch_bar < 0:
                        touch_bar = i
                if m30_cl[i] < lv.price - 0.10 * a_i:
                    reacted = True
                    break
            else:
                if m30_hi[i] >= lv.price - 0.05 * a_i:
                    reached = True
                    if touch_bar < 0:
                        touch_bar = i
                if m30_cl[i] > lv.price + 0.10 * a_i:
                    reacted = True
                    break
        if not reached or reacted:
            continue

        # optional CRT-style sweep: wick through the level then close back inside
        if P["require_sweep"]:
            swept = False
            for i in range(max(1, k - P["reach_bars"] + 1), k + 1):
                a_i = a30v[i]
                if side == SUPPORT:
                    swept = swept or (m30_lo[i] < lv.price - 0.05 * a_i
                                      and m30_cl[i] > lv.price)
                else:
                    swept = swept or (m30_hi[i] > lv.price + 0.05 * a_i
                                      and m30_cl[i] < lv.price)
            if not swept:
                continue

        # ---------- session filter ----------
        if P["session_filter"] and not (P["session_start"] <= t.hour < P["session_end"]):
            continue

        # ---------- entry style ----------
        sweep_bar = -1
        for i in range(max(1, k - P["reach_bars"] + 1), k + 1):
            a_i = a30v[i]
            if side == SUPPORT:
                if m30_lo[i] < lv.price - 0.05 * a_i and m30_cl[i] > lv.price:
                    sweep_bar = i
                    break
            else:
                if m30_hi[i] > lv.price + 0.05 * a_i and m30_cl[i] < lv.price:
                    sweep_bar = i
                    break

        if P.get("entry_style", "trigger") == "sweep":
            # sniper entry: market at the close of the bar right after the
            # sweep bar closed (strict parity with the EA: the sweep must be
            # the JUST-CLOSED bar — no stale-price fills).
            if sweep_bar != k:
                continue
            entry = float(m30_cl[sweep_bar])
            if dirn > 0:
                ext = float(m30_lo[sweep_bar: k + 1].min())
                sl = ext - P["sl_buf_atr"] * atr_k
            else:
                ext = float(m30_hi[sweep_bar: k + 1].max())
                sl = ext + P["sl_buf_atr"] * atr_k
            risk = abs(entry - sl)
            if risk <= 0:
                continue
        else:
            # ---------- M30 structure-shift trigger ----------
            cl = m30_cl
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
                continue
            trig = False
            for x in range(swing_j + 1, k + 1):
                if (dirn > 0 and cl[x] > swing_px) or (dirn < 0 and cl[x] < swing_px):
                    trig = True
                    break
            if not trig:
                continue
            # sequencing: the shift must follow the touch and live at the level
            if touch_bar >= 0 and (k - touch_bar) > P["trig_after_touch"]:
                continue
            if abs(swing_px - lv.price) > P["swing_near_atr"] * atr_k:
                continue
            entry = float(cl[k])
            if dirn > 0:
                ext = float(m30_lo[k - seg12 + 1: k + 1].min())
                sl = ext - P["sl_buf_atr"] * atr_k
            else:
                ext = float(m30_hi[k - seg12 + 1: k + 1].max())
                sl = ext + P["sl_buf_atr"] * atr_k
            risk = abs(entry - sl)
            if risk <= 0:
                continue

        if P["tp_mode"] == "level":
            opp = RESIST if dirn > 0 else SUPPORT
            best = None
            best_d = 1e30
            for o in book.levels:
                if o.broken or o.side != opp:
                    continue
                ahead = (o.price - entry) if dirn > 0 else (entry - o.price)
                if ahead <= risk:
                    continue
                if ahead < best_d:
                    best_d, best = ahead, o.price
            if best is None:
                continue
            tp = best
        else:
            tp = entry + dirn * P["fixed_rr"] * risk

        rr = abs(tp - entry) / risk
        if rr < P["min_rr"]:
            continue

        open_trade = dict(
            dir=dirn, entry=entry, sl=sl, tp=tp, risk=risk, rr=rr,
            entry_time=t, level=f"{lv.tf}/{lv.kind}", level_price=lv.price,
            bias="BULL" if bias > 0 else "BEAR",
        )
        entry_i = k

    if open_trade:
        tr = open_trade
        px = float(m30["close"].iloc[-1])
        tr["exit"], tr["reason"] = px, "EOD"
        tr["r"] = ((px - tr["entry"]) * tr["dir"]) / tr["risk"]
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
