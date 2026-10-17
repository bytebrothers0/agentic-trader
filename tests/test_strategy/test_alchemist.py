"""Tests for the Alchemist X-Factor entry module (strategy stack)."""
import pandas as pd
import pytest

import strategy.alchemist as AL
from strategy.alchemist import AlchemistEngine, dealing_position
import strategy.registry as REG
from indicators.xfactor_detector import XDirection, XLevel


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=dates)


def _row(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def _trend(n, start, step, wig=0.3):
    rows = []
    for i in range(n):
        base = start + i * step
        o = base
        c = base + step
        rows.append(_row(o, max(o, c) + wig, min(o, c) - wig, c))
    return _df(rows)


def _xlong(idx=65, price=101.0):
    return XLevel(
        direction=XDirection.LONG, x_index=idx, x_price=price,
        tl_value=price, sr_price=price, sr_kind="support",
        tl_pivot_index=40, tl_anchor_kind="body", tl_alchemist="continuation",
        candle_time=pd.Timestamp("2024-01-04"), point2_index=60,
        engulf=True, engulf_gap=False, ex_top=102.0, ex_bottom=100.0,
        sweep=True, qm_match=False, misses=2, touches=1,
        score=6, tier="A+", tradable=True,
        forming_candle_indices=[40, idx],
    )


def _frames():
    # D1 declining -> PD discount (LONG side). H1 flat then ramp (bull BOS).
    d1 = _trend(150, 150.0, -0.35)
    h1_rows = [_row(100, 100.2, 99.8, 100) for _ in range(25)]
    for i in range(15):
        base = 100 + i * 0.9
        h1_rows.append(_row(base, base + 0.4, base - 0.2, base + 0.7))
    h1 = _df(h1_rows)
    # M15: chop + a 105 high in the last 30 (TP pool).
    m15_rows = [_row(100 + (i % 5) * 0.3, 101.5, 99.5, 100.5) for i in range(40)]
    for i in range(30):
        base = 100 + (i % 7) * 0.4
        hi = 105.0 if i == 10 else base + 0.6
        m15_rows.append(_row(base, hi, base - 0.4, base + 0.2))
    m15 = _df(m15_rows)
    # M5 with a doji touch at 101 near the live edge.
    m5_rows = [_row(100.5, 101, 100, 100.6) for _ in range(45)]
    m5_rows += [_row(101, 101.3, 100.7, 101)]
    m5_rows += [_row(101, 101.4, 100.6, 101.1) for _ in range(14)]
    m5 = _df(m5_rows)
    return {"MN1": _trend(60, 120.0, 0.2), "W1": _trend(150, 110.0, 0.2),
            "D1": d1, "H4": _trend(250, 100.0, 0.05), "H1": h1,
            "M15": m15, "M5": m5}


def test_dealing_position_marks_premium_discount():
    up = _trend(100, 100.0, 0.5)
    pd_pos, hi, lo = dealing_position(up, 60)
    assert pd_pos > 0.55 and hi > lo
    dn = _trend(100, 150.0, -0.5)
    pd_pos, _, _ = dealing_position(dn, 60)
    assert pd_pos < 0.45


def test_bias_prefers_storyline_then_pd_bos():
    eng = AlchemistEngine(lambda tf, n: _df([_row(100, 101, 99, 100)] * 40))
    sl = {"D1_H4": {"bias": "BEARISH", "rejection_price": 105.0}}
    b = eng._resolve_bias({}, sl, 0.9)
    assert (b.direction, b.basis) == ("SHORT", "storyline")
    assert "D1" in b.detail and "H4" in b.detail
    b2 = eng._resolve_bias({}, {}, 0.5)
    assert b2.direction is None and b2.basis == "none"


def test_full_stack_signal_shape(monkeypatch):
    frames = _frames()
    eng = AlchemistEngine(lambda tf, n: frames[tf])
    monkeypatch.setattr(
        AL, "XDetector",
        lambda *a, **k: type("FakeX", (), {
            "__init__": lambda self, *a, **k: None,
            "detect_all": lambda self: [_xlong()]})(*a, **k))
    out = eng.analyze()
    assert out["disabled"] is False
    assert out["total_entries"] == 1
    sig = out["entries"][0]
    for key in ("symbol", "direction", "model_type", "entry_price",
                "stop_loss", "take_profit", "lot_size", "distance_to_entry",
                "priority_rank", "ftfl_tf", "stfl_tf", "ttfl_tf",
                "confidence", "secondary_entry", "storyline", "risk_usd"):
        assert key in sig, f"missing {key}"
    assert sig["direction"] == "BULLISH"
    assert sig["model_type"] == "ALCHEMIST_X"
    assert sig["stop_loss"] < sig["entry_price"] < sig["take_profit"]
    assert sig["rr"] >= 1.5
    assert out["primary_entry"] is sig or out["primary_entry"] == sig
    assert set(out["storylines"]) <= {"MN1_W1", "W1_D1", "D1_H4"}


def test_signal_guards_reject_bad_rr():
    eng = AlchemistEngine(lambda tf, n: None)
    m15 = _df([_row(100.5, 101.2, 100, 100.8)] * 40)
    x = _xlong(idx=35, price=101.0)
    bias = AL._Bias("LONG", "pd_bos", "t", "D1", "H1")
    # Pool (max high 101.2) too close to entry 101 -> RR fail -> None.
    assert eng._signal(m15, x, bias, 1.0, 100.8, 0.35, "n") is None


def test_signal_guards_reject_oversize_sl():
    eng = AlchemistEngine(lambda tf, n: None)
    m15 = _df([_row(100, 106, 99, 101)] * 40)
    x = _xlong(idx=35, price=101.0)
    bias = AL._Bias("LONG", "pd_bos", "t", "D1", "H1")
    # Huge spread balloons the SL floor past 1.5 ATR -> None.
    assert eng._signal(m15, x, bias, 1.0, 101.0, 10.0, "n") is None


def test_refinement_missing_m5_degrades_gracefully():
    eng = AlchemistEngine(lambda tf, n: None)
    ok, note = eng._refine(None, _xlong())
    assert ok and "unavailable" in note


def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(REG, "_STATE_PATH", str(tmp_path / "mods.json"))
    mods = REG.list_modules()
    assert any(m["id"] == "alchemist_x" and m["enabled"] for m in mods)
    mods = REG.set_enabled("alchemist_x", False)
    assert not [m for m in mods if m["id"] == "alchemist_x"][0]["enabled"]
    assert REG.is_enabled("alchemist_x") is False
    with pytest.raises(KeyError):
        REG.set_enabled("nope", True)
