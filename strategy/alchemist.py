"""
alchemist.py — Alchemist X-Factor entry module (web strategy, end to end).

Top-down stack (one direction per run):
  1. BIAS: D1 dealing-range position (premium/discount/equilibrium) plus
     storyline chains MN1->W1, W1->D1, D1->H4 (HTF fresh-level rejection +
     LTF BOS agreement). Execution bias prefers the D1_H4 storyline, then
     W1_D1, then MN1_W1, then PD-side + H1 BOS agreement. No basis = no trade.
  2. TRIGGER (M15): XDetector crossings, tradable tier only (engulfing at
     point 3 mandatory), direction == bias.
  3. REFINEMENT (M5): pre-zone IDM swept recently OR an M5 doji touch at
     the X within tolerance. Missing M5 degrades to unrefined (noted).
  4. SIGNAL MATH: limit at the between-closes mid (70%) + near edge (30%);
     SL beyond the SNR extreme floored at max(0.5 ATR, 3x spread);
     TP at the opposite 30-bar pool; RR >= min_rr; SL <= 1.5 ATR; sizing
     through RiskManager (1% risk, tier multiplier).

Web rules honored: 2-TF confirmation, first-touch-wick validity (via
freshness touch counts), GAP legs never the X, level 2-use cap, QMX top
tier at full risk, standard at 0.7x.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

from indicators.bos_detector import BOSDetector
from indicators.candle_analyzer import CandleAnalyzer
from indicators.freshness_tracker import FreshnessTracker
from indicators.idm_detector import IDMDetector
from indicators.qm_detector import QMDetector
from indicators.trendline_detector import TLDetector
from indicators.ts_detector import TSDetector
from indicators.xfactor_detector import (
    XDetector, XDirection, detect_storyline,
)

MODEL_TYPE = "ALCHEMIST_X"

# Tiny TTL cache so /api/strategy + /api/signals (fetched back to back)
# share one computation per symbol.
_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 20.0


def _atr_last(df: pd.DataFrame, period: int = 14) -> float:
    h = df["high"]
    l = df["low"]
    c = df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean()
    try:
        return float(atr.iloc[-1])
    except Exception:
        return 0.0


def dealing_position(df: pd.DataFrame, lookback: int = 60) -> tuple:
    """(pd, range_high, range_low) of the last close in its N-bar range."""
    win = df.iloc[-max(2, lookback):]
    hi = float(win["high"].max())
    lo = float(win["low"].min())
    if not (hi > lo):
        return 0.5, hi, lo
    return (float(df["close"].iloc[-1]) - lo) / (hi - lo), hi, lo


@dataclass
class _Bias:
    direction: Optional[str]  # "SHORT" | "LONG" | None
    basis: str                # "storyline" | "pd_bos" | "none"
    detail: str = ""
    htf_tf: str = "D1"
    ltf_tf: str = "H1"


class AlchemistEngine:
    """Runs the full stack. `fetch(tf_key, count)` supplies OHLCV frames."""

    STORY_CHAINS = (("MN1", "W1", "MN1_W1"),
                    ("W1", "D1", "W1_D1"),
                    ("D1", "H4", "D1_H4"))

    def __init__(self, fetch: Callable[[str, int], pd.DataFrame],
                 symbol: str = "XAUUSD", params: Optional[Dict] = None):
        self.fetch = fetch
        self.symbol = symbol
        p = params or {}
        self.exec_tf: str = str(p.get("exec_tf", "M15"))
        self.ref_tf: str = str(p.get("ref_tf", "M5"))
        self.pd_lookback: int = int(p.get("pd_lookback", 60))
        self.min_rr: float = float(p.get("min_rr", 1.5))
        self.risk_pct: float = float(p.get("risk_pct", 1.0))
        self.max_signals: int = int(p.get("max_signals", 3))
        self.sl_buf_atr: float = float(p.get("sl_buf_atr", 0.3))
        self.sl_min_atr: float = float(p.get("sl_min_atr", 0.5))
        self.sl_spread_mult: float = float(p.get("sl_spread_mult", 3.0))
        self.spread_points: float = float(p.get("spread_points", 35.0))
        self.require_refinement: bool = bool(p.get("require_refinement", True))
        self.point_value: float = float(p.get("point_value", 0.01))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self) -> Dict:
        """Full /api/strategy payload (cached per symbol, 20s TTL)."""
        now = time.time()
        hit = _CACHE.get(self.symbol)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        payload = self._compute()
        _CACHE[self.symbol] = (now, payload)
        return payload

    def signals(self) -> List[Dict]:
        return list(self.analyze().get("entries", []))

    # ------------------------------------------------------------------
    def _compute(self) -> Dict:
        frames = self._fetch_all()
        d1 = frames.get("D1")
        if d1 is None or len(d1) < 30:
            return self._disabled("waiting for D1 data")
        pd_pos, _, _ = dealing_position(d1, self.pd_lookback)
        storylines = self._storylines(frames)
        bias = self._resolve_bias(frames, storylines, pd_pos)
        sigs: List[Dict] = []
        note = ""
        if bias.direction is not None:
            sigs, note = self._trigger(frames, bias)
        sigs = sigs[:self.max_signals]
        for rank, s in enumerate(sigs, start=1):
            s["priority_rank"] = rank
        payload = {
            "symbol": self.symbol,
            "storylines": storylines,
            "entries": sigs,
            "primary_entry": sigs[0] if sigs else None,
            "total_entries": len(sigs),
            "ftfl": {"tf": bias.htf_tf},
            "stfl": {"tf": bias.ltf_tf},
            "ttfl": {"tf": self.exec_tf},
            "obstacles": [],
            "bias": {"direction": bias.direction, "basis": bias.basis,
                     "detail": bias.detail or note},
            "disabled": False,
            "message": (f"Alchemist {bias.basis} "
                        f"{bias.direction or 'FLAT'}" + (f" ({note})" if note else "")),
        }
        return payload

    @staticmethod
    def _disabled(message: str) -> Dict:
        return {
            "symbol": "", "storylines": {}, "entries": [],
            "primary_entry": None, "total_entries": 0,
            "ftfl": None, "stfl": None, "ttfl": None, "obstacles": [],
            "disabled": True, "message": message,
        }

    # ------------------------------------------------------------------
    def _fetch_all(self) -> Dict[str, Optional[pd.DataFrame]]:
        want = {"MN1": 60, "W1": 150, "D1": 150, "H4": 250, "H1": 250,
                self.exec_tf: 400, self.ref_tf: 250}
        out: Dict[str, Optional[pd.DataFrame]] = {}
        for tf, count in want.items():
            try:
                df = self.fetch(tf, count)
                out[tf] = df if df is not None and len(df) > 10 else None
            except Exception:
                out[tf] = None
        return out

    # ------------------------------------------------------------------
    def _sr(self, df: pd.DataFrame) -> list:
        analyzer = CandleAnalyzer(df)
        levels = analyzer.detect_all()
        return FreshnessTracker(df).update(levels)

    def _storylines(self, frames: Dict) -> Dict:
        out = {}
        for htf_tf, ltf_tf, key in self.STORY_CHAINS:
            htf = frames.get(htf_tf)
            ltf = frames.get(ltf_tf)
            if htf is None or ltf is None:
                continue
            try:
                levels = self._sr(htf)
                bos = BOSDetector(ltf, swing_length=10,
                                  show_internal=False).detect_all()
            except Exception:
                continue
            for direction in (XDirection.SHORT, XDirection.LONG):
                try:
                    st = detect_storyline(htf, levels, bos, direction)
                except Exception:
                    st = None
                if st is None:
                    continue
                bias = ("BEARISH" if direction == XDirection.SHORT
                        else "BULLISH")
                cur = out.get(key)
                idx = (st.touch_index, st.bos_index)
                if cur is None or idx > (cur.get("_t", (-1, -1))):
                    out[key] = {
                        "bias": bias,
                        "rejection_time": self._iso(htf, st.touch_index),
                        "breakout_time": self._iso(ltf, st.bos_index),
                        "rejection_price": round(st.htf_price, 3),
                        "htf": htf_tf, "ltf": ltf_tf,
                        "_t": idx,
                    }
        for v in out.values():
            v.pop("_t", None)
        return out

    @staticmethod
    def _iso(df: pd.DataFrame, i: int) -> str:
        try:
            ts = df.index[min(max(int(i), 0), len(df) - 1)]
            return pd.Timestamp(ts).isoformat()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    def _resolve_bias(self, frames: Dict, storylines: Dict,
                      pd_pos: float) -> _Bias:
        for key, htf_tf, ltf_tf in (("D1_H4", "D1", "H4"),
                                    ("W1_D1", "W1", "D1"),
                                    ("MN1_W1", "MN1", "W1")):
            sl = storylines.get(key)
            if sl and sl.get("bias") in ("BULLISH", "BEARISH"):
                direction = ("LONG" if sl["bias"] == "BULLISH" else "SHORT")
                return _Bias(direction, "storyline",
                             f"{htf_tf} rejects {sl.get('rejection_price')} + "
                             f"{ltf_tf} BOS {sl['bias'].lower()}",
                             htf_tf, ltf_tf)
        # Fallback: dealing-range side + H1 BOS agreement (ABAX hierarchy).
        h1 = frames.get("H1")
        side = ("SHORT" if pd_pos > 0.55 else
                "LONG" if pd_pos < 0.45 else None)
        if side is not None and h1 is not None:
            try:
                bos = BOSDetector(h1, swing_length=10,
                                  show_internal=False).detect_all()
            except Exception:
                bos = []
            want = ("bearish" if side == "SHORT" else "bullish")
            if any(str(getattr(getattr(b, "direction", ""), "value",
                               getattr(b, "direction", ""))) == want
                   for b in bos[-5:]):
                return _Bias(side, "pd_bos",
                             f"D1 {'premium' if side == 'SHORT' else 'discount'} "
                             f"(PD {pd_pos:.2f}) + H1 BOS {want}",
                             "D1", "H1")
        return _Bias(None, "none",
                     f"no storyline; D1 PD {pd_pos:.2f} unaligned", "D1", "H1")

    # ------------------------------------------------------------------
    def _trigger(self, frames: Dict, bias: _Bias) -> tuple:
        m15 = frames.get(self.exec_tf)
        if m15 is None or len(m15) < 60:
            return [], f"waiting for {self.exec_tf} data"
        assert bias.direction in ("SHORT", "LONG")
        want_short = bias.direction == "SHORT"
        try:
            sr = self._sr(m15)
            tl = TLDetector(m15).detect_all()
            ts = TSDetector(m15).detect_all()
            qm = QMDetector(m15, sr).detect_all()
            xs = XDetector(m15, sr, tl, ts_levels=ts,
                           qm_levels=qm).detect_all()
        except Exception as e:
            return [], f"detector error: {e}"
        cands = [x for x in xs
                 if x.tradable and
                 (x.direction == XDirection.SHORT) == want_short]
        m5 = frames.get(self.ref_tf)
        atr = _atr_last(m15) or 1.0
        current = float(m15["close"].iloc[-1])
        spread = self.spread_points * self.point_value
        sigs = []
        for x in sorted(cands, key=lambda z: -z.score):
            ok, note = self._refine(m5, x)
            if self.require_refinement and not ok:
                continue
            sig = self._signal(m15, x, bias, atr, current, spread, note)
            if sig is not None:
                sigs.append(sig)
        return sigs, ("M5 refined" if m5 is not None else "M5 unavailable")

    def _refine(self, m5: Optional[pd.DataFrame], x) -> tuple:
        """LTF confirmation: pre-zone IDM swept recently OR an M5 doji
        touch at the X within tolerance (15-bar lookback)."""
        if m5 is None or len(m5) < 20:
            return True, "M5 unavailable"
        n = len(m5)
        try:
            idms = IDMDetector(m5).detect_all()
        except Exception:
            idms = []
        for im in idms:
            if im.swept and im.sweep_index is not None and im.sweep_index >= n - 40:
                return True, "M5 IDM swept"
        o = m5["open"].values
        h = m5["high"].values
        l = m5["low"].values
        c = m5["close"].values
        atr5 = _atr_last(m5) or 1.0
        tol = max(0.1 * atr5, 1e-9)
        for m in range(max(0, n - 15), n):
            rng = h[m] - l[m]
            if not (rng > 0):
                continue
            if abs(c[m] - o[m]) / rng < 0.15 and l[m] - tol <= x.x_price <= h[m] + tol:
                return True, "M5 doji touch"
        return False, "no M5 confirmation"

    # ------------------------------------------------------------------
    def _signal(self, m15: pd.DataFrame, x, bias: _Bias, atr: float,
                current: float, spread: float, note: str) -> Optional[Dict]:
        want_short = bias.direction == "SHORT"
        # Entry: between-closes mid (70%) + near edge (30%); else the X.
        if x.engulf and x.ex_top and x.ex_bottom:
            mid = (x.ex_top + x.ex_bottom) / 2.0
            # Near edge (closest to current price) fills first.
            near = (x.ex_top if abs(x.ex_top - current) < abs(x.ex_bottom - current)
                    else x.ex_bottom)
            entry, secondary = mid, float(near)
        else:
            entry = secondary = float(x.x_price)
        # SL beyond the extreme, floored (RanaAli rule in price units).
        buf = self.sl_buf_atr * atr + spread * 1.5
        floor = max(self.sl_min_atr * atr, self.sl_spread_mult * spread)
        sl_dist = max(buf, floor)
        if want_short:
            sl = entry + sl_dist
        else:
            sl = entry - sl_dist
        if not (sl_dist <= 1.5 * atr):
            return None  # oversized stop: skip
        # TP at the opposite 30-bar pool, inset for fill.
        look = m15.iloc[-30:]
        pool = float(look["low"].min()) if want_short else float(look["high"].max())
        tp = pool + (0.05 * atr if want_short else -0.05 * atr)
        if (want_short and not (tp < entry)) or (not want_short and not (tp > entry)):
            return None  # no room to the pool
        rr = abs(tp - entry) / sl_dist
        if rr < self.min_rr:
            return None
        mult = 1.0 if x.tier in ("QMX", "A+") else 0.7
        lots, risk_usd = self._size(entry, sl_dist, mult, want_short)
        direction = "BEARISH" if want_short else "BULLISH"
        return {
            "symbol": self.symbol,
            "direction": direction,
            "model_type": MODEL_TYPE,
            "tier": x.tier,
            "score": int(x.score),
            "confidence": f"{x.tier} {x.score}",
            "entry_price": round(entry, 3),
            "stop_loss": round(sl, 3),
            "take_profit": round(tp, 3),
            "lot_size": round(lots * 0.7, 2),
            "secondary_entry": {
                "entry_price": round(secondary, 3),
                "lot_size": round(lots * 0.3, 2),
            },
            "risk_usd": round(risk_usd * mult, 2),
            "distance_to_entry": round(abs(entry - current) / self.point_value, 1),
            "rr": round(rr, 2),
            "ftfl_tf": bias.htf_tf,
            "stfl_tf": bias.ltf_tf,
            "ttfl_tf": self.exec_tf,
            "storyline": bias.detail,
            "refinement": note,
            "management": {"partial_50_at_tp": True, "move_to_be": True,
                           "trail": "m15_structure"},
        }

    def _size(self, entry: float, sl_dist: float, mult: float,
              want_short: bool) -> tuple:
        try:
            from execution.risk_manager import RiskManager, BiasDirection
            from config.settings import RISK_PERCENT
            rm = RiskManager(
                risk_percent=self.risk_pct or RISK_PERCENT)
            plan = rm.calculate_position(
                self.symbol,
                BiasDirection.BEARISH if want_short else BiasDirection.BULLISH,
                entry, entry, entry,
                risk_multiplier=mult, model_name=MODEL_TYPE,
                sl_points_override=max(10, int(sl_dist / self.point_value)),
            )
            return float(plan.lot_size), float(plan.risk_amount_usd)
        except Exception:
            return 0.01, round(10000.0 * (self.risk_pct or 1.0) / 100.0, 2)
