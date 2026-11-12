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
    swing_pivot=2,
    trig_after_touch=8,       # trigger close must be within N M30 bars of the touch
    swing_near_atr=0.75,      # broken minor swing must sit within X ATR of the level
    require_sweep=False,      # wick THROUGH the level then close-back
    reach_bars=12,            # level-touch lookback window (M30 bars)
    sl_buf_atr=0.10,
    min_rr=1.5,
    tp_mode="level",          # "level" | "fixed_rr"
    fixed_rr=2.0,
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
    """Last confirmed close-pivot break direction: +1 up, -1 down, 0 none."""
    n = len(c)
    last_h = last_l = -1
    for j in range(w, n - w):
        win = c[j - w: j + w + 1]
        if c[j] == win.max() and (win == win.max()).sum() == 1:
            last_h = j
        elif c[j] == win.min() and (win == win.min()).sum() == 1:
            last_l = j
    if last_h < 0 or last_l < 0:
        return 0
    iu = idn = -1
    for x in range(last_h + 1, n):
        if c[x] > c[last_h]:
            iu = x
            break
    for x in range(last_l + 1, n):
        if c[x] < c[last_l]:
            idn = x
            break
    if iu < 0 and idn < 0:
        return 0
    if idn < 0 or (iu >= 0 and iu >= idn):
        return 1
    return -1


def storyline(d1: pd.DataFrame, h1: pd.DataFrame, ts: pd.Timestamp) -> int:
    d1v = d1[d1.index < ts]["close"].values
    h1v = h1[h1.index < ts]["close"].values
    if len(d1v) < 60 or len(h1v) < 60:
        return 0
    a = _pivot_break_dir(d1v[-250:], P["story_pivot"])
    b = _pivot_break_dir(h1v[-400:], P["story_pivot"])
    if a != 0 and a == b:
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
             a: pd.Series, out: List[Level]) -> None:
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
            out.append(Level(c[i], RESIST, born, tf, "A"))
        elif not col_i and col_j:
            out.append(Level(c[i], SUPPORT, born, tf, "V"))
        elif col_i and col_j:
            if o[i + 1] - c[i] >= gap_min_atr * av_i:
                out.append(Level(c[i], SUPPORT, born, tf, "GAP"))
        else:
            if c[i] - o[i + 1] >= gap_min_atr * av_i:
                out.append(Level(c[i], RESIST, born, tf, "GAP"))
        # OCL: one level per run — the first candle of a same-colour run
        run = 1
        j = i + 1
        while j < n and (c[j] > o[j]) == col_i:
            run += 1
            j += 1
        if run >= ocl_run_min:
            out.append(Level(c[i], SUPPORT if col_i else RESIST, born, tf, "OCL"))


def _replay_life(lv: Level, df: pd.DataFrame, born_i: int, buf: float) -> None:
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values
    n = len(df)
    for j in range(born_i + 1, n):          # bars strictly after birth
        touched = False
        if lv.side == SUPPORT:
            if lo[j] <= lv.price:
                touched = True
            if cl[j] < lv.price - buf:
                lv.broken = True
                break
        else:
            if hi[j] >= lv.price:
                touched = True
            if cl[j] > lv.price + buf:
                lv.broken = True
                break
        if touched:
            lv.fresh = False
            lv.touches += 1


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
        h4 = self.h4[self.h4.index < ts]
        d1 = self.d1[self.d1.index < ts]
        if len(h4) < 40 or len(d1) < 20:
            return
        h4 = h4.tail(P["h4_bars"])
        d1 = d1.tail(P["d1_bars"])
        lvls: List[Level] = []
        a4 = self.a_h4.reindex(h4.index)
        ad = self.a_d1.reindex(d1.index)
        _scan_tf(h4, "H4", P["gap_min_atr"], P["ocl_run_min"], a4, lvls)
        _scan_tf(d1, "D1", P["gap_min_atr"] * 2.0, P["ocl_run_min"], ad, lvls)
        # age filter + lifecycle on native TF
        keep: List[Level] = []
        for lv in lvls:
            src = h4 if lv.tf == "H4" else d1
            age = (ts - lv.born) / (timedelta(hours=4) if lv.tf == "H4" else timedelta(days=1))
            if age > P["level_max_age"]:
                continue
            pos = src.index.get_loc(lv.born)
            if not isinstance(pos, (int, np.integer)):
                continue
            buf = P["break_buf_atr"] * float((a4 if lv.tf == "H4" else ad).iloc[-1])
            if np.isnan(buf) or buf <= 0:
                continue
            _replay_life(lv, src, int(pos), buf)
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
    m5_lo = m5["low"]
    m5_hi = m5["high"]
    m5i = {t: k for k, t in enumerate(m5.index)}

    seg12 = 12   # reaction extreme window (EA parity)

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

        # ---------- storyline per H1 bar (cached by callers) ----------
        bias = storyline(load("D1"), h1, t)
        if bias == 0:
            continue

        px = m30["close"].iloc[k]
        atr_k = a30.iloc[k]
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
            a_i = a30.iloc[i]
            if np.isnan(a_i):
                continue
            if side == SUPPORT:
                if m30["low"].iloc[i] <= lv.price + 0.05 * a_i:
                    reached = True
                    if touch_bar < 0:
                        touch_bar = i
                if m30["close"].iloc[i] < lv.price - 0.10 * a_i:
                    reacted = True
                    break
            else:
                if m30["high"].iloc[i] >= lv.price - 0.05 * a_i:
                    reached = True
                    if touch_bar < 0:
                        touch_bar = i
                if m30["close"].iloc[i] > lv.price + 0.10 * a_i:
                    reacted = True
                    break
        if not reached or reacted:
            continue

        # optional CRT-style sweep: wick through the level then close back inside
        if P["require_sweep"]:
            swept = False
            for i in range(max(1, k - P["reach_bars"] + 1), k + 1):
                a_i = a30.iloc[i]
                if side == SUPPORT:
                    swept = swept or (m30["low"].iloc[i] < lv.price - 0.05 * a_i
                                      and m30["close"].iloc[i] > lv.price)
                else:
                    swept = swept or (m30["high"].iloc[i] > lv.price + 0.05 * a_i
                                      and m30["close"].iloc[i] < lv.price)
            if not swept:
                continue

        # ---------- session filter ----------
        if P["session_filter"] and not (P["session_start"] <= t.hour < P["session_end"]):
            continue

        # ---------- M30 structure-shift trigger ----------
        cl = m30["close"].values
        op = m30["open"].values
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

        # ---------- entry / stop / target ----------
        entry = float(cl[k])
        lo12 = m30["low"].iloc[k - seg12 + 1: k + 1].min() if dirn > 0 else None
        hi12 = m30["high"].iloc[k - seg12 + 1: k + 1].max() if dirn < 0 else None
        if dirn > 0:
            ext = float(lo12)
            sl = ext - P["sl_buf_atr"] * atr_k
        else:
            ext = float(hi12)
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
    """The last H4 bar that closed before or at t (book rebuild marker)."""
    h4 = load("H4")
    idx = h4.index
    pos = idx.searchsorted(t, side="right") - 1
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
