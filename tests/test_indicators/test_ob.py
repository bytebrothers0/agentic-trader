"""Tests for OB + Breaker Blocks (LuxAlgo port + Luap status)."""
import pandas as pd

from indicators.ob_detector import OBDetector, OBDirection


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _bull(df, **kw):
    # LuxAlgo-core tests run unfiltered; Luap gates are tested separately.
    kw.setdefault("require_fvg", False)
    kw.setdefault("require_sweep", False)
    kw.setdefault("mark_decisional", False)
    return [x for x in OBDetector(df, swing_length=2, **kw).detect_all()
            if x.direction == OBDirection.BULLISH]


def _bear(df, **kw):
    kw.setdefault("require_fvg", False)
    kw.setdefault("require_sweep", False)
    kw.setdefault("mark_decisional", False)
    return [x for x in OBDetector(df, swing_length=2, **kw).detect_all()
            if x.direction == OBDirection.BEARISH]


BULL_BASE = [
    {"open": 100, "high": 102, "low": 99, "close": 101},
    {"open": 101, "high": 105, "low": 100, "close": 104},
    {"open": 104, "high": 103, "low": 101, "close": 102},
    {"open": 102, "high": 104, "low": 101, "close": 103},
    {"open": 103, "high": 106, "low": 102, "close": 105.5},
]


def test_bullish_ob_formation():
    lv = _bull(_df(BULL_BASE))
    assert len(lv) == 1
    assert not lv[0].is_breaker
    assert lv[0].bottom == 101 and lv[0].top == 103
    assert lv[0].formation_index == 2


def test_bullish_breaker_flip():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 106, "low": 100, "close": 100.5},
    ])
    lv = _bear(df)
    assert len(lv) == 1
    assert lv[0].is_breaker
    assert lv[0].bottom == 101 and lv[0].top == 103
    assert lv[0].break_index == 5


def test_breaker_removed_on_acceptance_back():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 106, "low": 100, "close": 100.5},
        {"open": 100.5, "high": 112, "low": 101, "close": 111},
    ])
    assert _bear(df) == [] and _bull(df) == []


def test_bearish_ob_formation():
    df = _df([
        {"open": 103, "high": 106, "low": 102, "close": 105},
        {"open": 105, "high": 106, "low": 100, "close": 101},
        {"open": 101, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 99.5, "close": 102.5},
        {"open": 102.5, "high": 103, "low": 100, "close": 101},
        {"open": 101, "high": 101.5, "low": 96, "close": 97},
    ])
    lv = _bear(df)
    assert len(lv) == 1
    assert not lv[0].is_breaker
    assert lv[0].bottom == 99.5 and lv[0].top == 103


def test_wick_only_swing_cross_is_nothing():
    df = _df([
        {"open": 100, "high": 102, "low": 99, "close": 101},
        {"open": 101, "high": 105, "low": 100, "close": 104},
        {"open": 104, "high": 103, "low": 101, "close": 102},
        {"open": 102, "high": 107, "low": 101, "close": 103.5},
        {"open": 103.5, "high": 104, "low": 102, "close": 103},
    ])
    assert OBDetector(df, swing_length=2).detect_all() == []


def test_show_last_keeps_newest_per_side():
    df = _df(BULL_BASE + [
        {"open": 105.5, "high": 107, "low": 104, "close": 106},
        {"open": 106, "high": 106.5, "low": 102, "close": 103},
        {"open": 103, "high": 109, "low": 102, "close": 107.5},
        {"open": 107.5, "high": 108, "low": 106, "close": 107},
        {"open": 107, "high": 107.5, "low": 106, "close": 106.5},
        {"open": 106.5, "high": 110, "low": 106, "close": 109.5},
    ])
    assert len(_bull(df)) == 2
    short = _bull(df, show_last=1)
    # Web-exact origin: last opposite-colour candle before displacement
    # (bar 9, bearish) instead of the most extreme bar (bar 8).
    assert len(short) == 1 and short[0].formation_index == 9
    assert short[0].bottom == 106 and short[0].top == 107.5


# ------------------------------------------------------------------
# Luap Valid-OB gates (Part 5/6): sweep + FVG, Extreme/Decisional.
# ------------------------------------------------------------------

# Bullish displacement: origin bar sweeps the prior low with a longer
# wick, then a same-direction FVG overlaps the origin zone.
SWEEP_FVG_BASE = [
    {"open": 100, "high": 101, "low": 99, "close": 99.5},
    {"open": 99.5, "high": 100, "low": 98, "close": 98.5},
    # origin: takes prior low (98 -> 97.5) with a longer lower wick
    {"open": 99, "high": 99.5, "low": 97.5, "close": 98.8},
    # displacement with a bullish FVG above the origin (low 99.6 > 98.8)
    {"open": 99.0, "high": 103, "low": 99.6, "close": 102.5},
    {"open": 102.5, "high": 104, "low": 102, "close": 103.5},
    {"open": 103.5, "high": 105, "low": 103, "close": 104.5},
]


def test_luap_valid_ob_passes_both_gates():
    lv = [x for x in OBDetector(_df(SWEEP_FVG_BASE), swing_length=2,
                                show_last=10).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1
    assert lv[0].ob_type in ("EXTREME", "DECISIONAL")


def test_no_sweep_no_displacement_no_ob():
    # Origin never takes the prior low AND the break bar is small
    # (range 2.3 < 1.5x median 2.0) -> Weak/Engineered OB, rejected.
    rows = [dict(r) for r in SWEEP_FVG_BASE]
    rows[2] = {"open": 99, "high": 99.5, "low": 98.2, "close": 98.8}
    rows[3] = {"open": 99, "high": 101.5, "low": 99.2, "close": 101.2}
    lv = [x for x in OBDetector(_df(rows), swing_length=2,
                                show_last=10, require_fvg=False).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert lv == []


def test_displacement_without_sweep_is_valid():
    # Same shape with the forceful break bar: no sweep, but the break
    # displaces (range 3.4 >= 1.5x median 2.0) -> valid web OB.
    rows = [dict(r) for r in SWEEP_FVG_BASE]
    rows[2] = {"open": 99, "high": 99.5, "low": 98.2, "close": 98.8}
    lv = [x for x in OBDetector(_df(rows), swing_length=2,
                                show_last=10, require_fvg=False).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1


def test_no_fvg_no_ob():
    # Sweep present but no gap anywhere (bar4 low wipes the gap), with the
    # FVG confluence gate explicitly on -> Engineered OB rejected.
    # (Default is off: FVG overlap scores entries, it doesn't veto OBs.)
    rows = [dict(r) for r in SWEEP_FVG_BASE]
    rows[4] = {"open": 102.5, "high": 104, "low": 99.0, "close": 103.5}
    lv = [x for x in OBDetector(_df(rows), swing_length=2,
                                show_last=10, require_sweep=False,
                                require_fvg=True).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert lv == []


def test_decisional_marking_near_idm(monkeypatch):
    from types import SimpleNamespace
    from indicators.idm_detector import IDMType
    from indicators import idm_detector
    df = _df(SWEEP_FVG_BASE)
    near = SimpleNamespace(idm_type=IDMType.IDM_LOW, price=98.0,
                           formation_index=2)
    monkeypatch.setattr(idm_detector.IDMDetector, "detect_all",
                        lambda self: [near])
    lv = [x for x in OBDetector(df, swing_length=2,
                                show_last=10).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1 and lv[0].ob_type == "DECISIONAL"
    far = SimpleNamespace(idm_type=IDMType.IDM_LOW, price=200.0,
                          formation_index=0)
    monkeypatch.setattr(idm_detector.IDMDetector, "detect_all",
                        lambda self: [far])
    lv = [x for x in OBDetector(df, swing_length=2,
                                show_last=10).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1 and lv[0].ob_type == "EXTREME"


# ------------------------------------------------------------------
# Sweep-family classification: TS (Turtle Soup) and FS (False Sweep).
# ------------------------------------------------------------------

def _mirror(rows):
    """Exact bearish mirror of a synthetic fixture. Negating open/close
    flips every candle's colour (so 'last opposite-colour candle' picks
    the mirrored origin), and swapping+negating high/low keeps the wicks
    outside the body. Guarantees the detector's symmetric branches see
    the mirrored shape instead of hand-transcribed approximations."""
    return [{"open": 200 - x["open"], "close": 200 - x["close"],
             "high": 200 - x["low"], "low": 200 - x["high"]}
            for x in rows]


def test_ts_origin_from_turtle_soup_wick_sweep():
    # SWEEP_FVG_BASE: the origin candle (idx 2) wick-sweeps the standing
    # low at 98 (anchor idx 1, body back above) — the TSDetector verdict
    # — then displaces up. The zone carries the TS family with the swept
    # pool as metadata.
    lv = [x for x in OBDetector(_df(SWEEP_FVG_BASE), swing_length=2,
                                show_last=10).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1
    assert lv[0].sweep_class == "TS"
    assert lv[0].sweep_price == 98.0
    assert lv[0].sweep_variant in ("classic", "two_candle")


# Standing pool 98.2 = bar 1's low. Origin (bar 4, bearish) body-closes
# below it (body min 98.1), and bar 5's body reclaims (body min 98.3)
# by the birth bar (bar 6 closes above the swing high 100.5). The
# displacement also births a mid-leg zone that flips to a breaker on
# bar 6 — filtered in these tests.
FS_BULL_BASE = [
    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 99.6},
    {"open": 99.6, "high": 99.8, "low": 98.2, "close": 98.6},
    {"open": 98.6, "high": 99.4, "low": 98.4, "close": 99.2},
    {"open": 99.2, "high": 100.5, "low": 99.0, "close": 100.2},
    {"open": 100.0, "high": 100.3, "low": 98.0, "close": 98.1},
    {"open": 98.3, "high": 100.0, "low": 98.25, "close": 99.8},
    {"open": 99.8, "high": 101.4, "low": 99.7, "close": 101.2},
]


def test_fs_origin_from_body_close_through_then_reclaim():
    lv = [x for x in _bull(_df(FS_BULL_BASE)) if not x.is_breaker]
    assert len(lv) == 1
    assert lv[0].formation_index == 4
    assert lv[0].sweep_class == "FS"
    assert lv[0].sweep_price == 98.2
    assert lv[0].sweep_variant == "body_reclaim"


def test_fs_origin_mirrored_bearish():
    lv = [x for x in _bear(_df(_mirror(FS_BULL_BASE)))
          if not x.is_breaker]
    assert len(lv) == 1
    assert lv[0].formation_index == 4
    assert lv[0].sweep_class == "FS"
    assert round(lv[0].sweep_price, 4) == 101.8


def test_fs_needs_the_body_reclaim_by_birth():
    # Same shape, but the pool is never body-reclaimed by the birth bar:
    # bar 5 stays under (body max 99.2 with its open 98.15 below the
    # pool), and the birth bar (bar 6) STRADDLES the pool (open 98.0,
    # close 101.2) — the market never showed a closed-back body, so the
    # false-sweep credit is withheld (TS discipline: straddles don't
    # count). Untagged.
    df = _df([
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 99.6},
        {"open": 99.6, "high": 99.8, "low": 98.2, "close": 98.6},
        {"open": 98.6, "high": 99.4, "low": 98.4, "close": 99.2},
        {"open": 99.2, "high": 100.5, "low": 99.0, "close": 100.2},
        {"open": 100.0, "high": 100.3, "low": 98.0, "close": 98.1},
        {"open": 98.15, "high": 100.0, "low": 98.0, "close": 99.2},
        {"open": 98.0, "high": 101.5, "low": 97.9, "close": 101.2},
    ])
    lv_bull = [x for x in _bull(df) if not x.is_breaker]
    assert len(lv_bull) == 1
    assert lv_bull[0].formation_index == 4
    assert lv_bull[0].sweep_class == ""


def test_plain_grab_origin_gets_no_family():
    # BULL_BASE: a clean displacement OB with no TS event and no body
    # through any standing pool — untagged, classification adds nothing.
    lv = _bull(_df(BULL_BASE))
    assert len(lv) == 1
    assert lv[0].sweep_class == ""
    assert lv[0].sweep_price is None


def test_classify_sweeps_can_be_turned_off():
    lv = [x for x in OBDetector(_df(SWEEP_FVG_BASE), swing_length=2,
                                show_last=10,
                                classify_sweeps=False).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1
    assert lv[0].sweep_class == ""


def test_invalidated_ts_before_birth_does_not_count(monkeypatch):
    # A direction-matched TS event exists on the zone's forming window,
    # but its boundary was body-closed-through BEFORE the zone's birth
    # (real breakout in between) -> no TS tag. The local FS check also
    # fails: the origin body stayed inside its pool.
    import indicators.ts_detector as ts_mod
    from indicators.ts_detector import TSDirection, TSType, TSLevel, TSVariant
    fake = TSLevel(
        ts_type=TSType.TS_LOW,
        direction=TSDirection.BULLISH,
        price=98.0,
        candle_index=3,               # within [origin 2, birth 3]
        candle_time=pd.Timestamp("2024-01-04"),
        variant=TSVariant.CLASSIC,
        invalidated_candle_index=2,   # settled dead before birth
    )
    monkeypatch.setattr(ts_mod.TSDetector, "detect_all",
                        lambda self: [fake])
    lv = [x for x in OBDetector(_df(SWEEP_FVG_BASE), swing_length=2,
                                show_last=10).detect_all()
          if x.direction == OBDirection.BULLISH]
    assert len(lv) == 1
    assert lv[0].sweep_class == ""
