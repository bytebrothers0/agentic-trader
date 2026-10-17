"""Tests for the Luap "True SMC" two-candle inducement family.

Rule (Part 1 + Part 3): a pullback only counts once a candle takes the
liquidity of the candle that ended the impulse — the low (bullish) / high
(bearish) of the previous Highest-High / Lowest-Low candle ("Target Candle").
Wick or body, colour irrelevant. The pullback's extreme becomes the IDM; a new
extreme without taking the IDM *shifts* it; a cross (wick or body) takes it.
"""
import pandas as pd

from indicators.idm_detector import IDMDetector, IDMType, IDMDirection
from indicators.idm_detector import LuapIDMDetector


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _r(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


# Impulse to HH @3 (low 108) -> valid pullback to 100 @6 -> new HH @9
# -> two-candle IDM = 100 @6, confirmed by the HH @9.
BULL = [
    _r(100, 102, 99, 101),    # 0
    _r(101, 105, 100, 104),   # 1
    _r(104, 108, 103, 107),   # 2
    _r(107, 112, 108, 111),   # 3  Target Candle (HH, low 108)
    _r(111, 111, 105, 106),   # 4
    _r(106, 106, 103, 104),   # 5  takes 108 -> valid pullback
    _r(104, 105, 100, 102),   # 6  pullback extreme 100
    _r(102, 106, 102, 105),   # 7
    _r(105, 110, 104, 109),   # 8
    _r(109, 115, 108, 114),   # 9  new HH -> IDM = 100
]


def _mirror(rows, base=200.0):
    return [
        {"open": base - r["close"], "high": base - r["low"],
         "low": base - r["high"], "close": base - r["open"]}
        for r in rows
    ]


def test_valid_pullback_becomes_idm():
    lv = LuapIDMDetector(_df(BULL)).detect_all()
    assert len(lv) == 1
    idm = lv[0]
    assert idm.rule == "two_candle"
    assert idm.idm_type == IDMType.IDM_LOW
    assert idm.direction == IDMDirection.BULLISH
    assert idm.price == 100.0
    assert idm.formation_index == 6
    assert idm.confirm_index == 9          # the new HH that confirmed it
    assert idm.swept is False


def test_shallow_pullback_is_not_an_idm():
    # Each dip is shallower than the Target Candle's low, so no valid pullback.
    rows = [
        _r(100, 102, 99, 101),    # 0
        _r(101, 105, 100, 104),   # 1
        _r(104, 108, 103, 107),   # 2
        _r(107, 112, 108, 111),   # 3  Target Candle (low 108)
        _r(111, 113, 109, 112),   # 4  low 109 > 108 -> shallow
        _r(112, 116, 111, 115),   # 5  new HH
        _r(115, 118, 114, 117),   # 6  new HH
    ]
    assert LuapIDMDetector(_df(rows)).detect_all() == []


def test_idm_taken_on_cross():
    rows = BULL + [
        _r(114, 114, 110, 111),   # 10
        _r(111, 111, 105, 106),   # 11
        _r(106, 106, 99, 101),    # 12 wick through 100 -> taken
    ]
    lv = LuapIDMDetector(_df(rows)).detect_all()
    assert len(lv) == 1
    assert lv[0].price == 100.0
    assert lv[0].swept is True
    assert lv[0].sweep_index == 12


def test_body_close_through_is_broken_not_swept():
    # Part 8: a body close through the IDM is NOT a sweep -> setup cancelled.
    rows = BULL + [
        _r(114, 114, 110, 111),   # 10
        _r(111, 111, 105, 106),   # 11
        _r(106, 106, 99, 98),     # 12 wick through, but close 98 < 100
    ]
    lv = LuapIDMDetector(_df(rows)).detect_all()
    assert len(lv) == 1
    assert lv[0].swept is False
    assert lv[0].broken is True
    assert lv[0].broken_index == 12


def test_bearish_idm_is_mirror():
    lv = LuapIDMDetector(_df(_mirror(BULL))).detect_all()
    assert len(lv) == 1
    idm = lv[0]
    assert idm.idm_type == IDMType.IDM_HIGH
    assert idm.direction == IDMDirection.BEARISH
    assert idm.price == 100.0              # 200 - 100
    assert idm.formation_index == 6
    assert idm.swept is False


def test_idm_shifts_on_new_extreme():
    # A new HH with no intervening pullback keeps the current IDM; the next
    # pullback + HH *shifts* it forward, dropping the older unswept one.
    rows = BULL + [
        _r(114, 116, 110, 115),   # 10 new HH, no pullback -> IDM unchanged
        _r(115, 115, 108, 109),   # 11 new pullback (breaks 110)
        _r(109, 112, 105, 106),   # 12 pullback extreme 105
        _r(106, 118, 106, 117),   # 13 new HH -> IDM shifts to 105
    ]
    lv = LuapIDMDetector(_df(rows)).detect_all()
    assert len(lv) == 1                     # the 100 @6 IDM is dropped
    assert lv[0].price == 105.0
    assert lv[0].formation_index == 12
    assert lv[0].swept is False


def test_cap_keeps_newest_per_side():
    rows = BULL + [
        _r(114, 115, 109, 110),   # 10
        _r(110, 111, 104, 105),   # 11 pullback 104 -> new HH below
        _r(105, 117, 104, 116),   # 12 new HH -> IDM 104 @11
        _r(116, 117, 111, 112),   # 13
        _r(112, 113, 102, 103),   # 14 pullback 102
        _r(103, 120, 102, 119),   # 15 new HH -> IDM 102 @14
    ]
    lv = LuapIDMDetector(_df(rows), max_per_side=1).detect_all()
    assert len(lv) == 1
    assert lv[0].formation_index == 14      # newest


# Same pullback marked by both families (origin low @2, HH @6, higher low @8).
BOTH = [
    _r(99.0, 99.5, 97.5, 98.0),
    _r(98.0, 98.5, 96.0, 96.5),
    _r(96.5, 97.0, 94.0, 96.0),
    _r(96.0, 99.5, 95.5, 99.0),
    _r(99.0, 102.0, 98.5, 101.5),
    _r(101.5, 104.0, 101.0, 103.5),
    _r(103.5, 106.0, 103.0, 105.6),
    _r(105.6, 105.8, 103.4, 104.0),
    _r(104.0, 104.5, 101.5, 102.0),
    _r(102.0, 104.5, 101.9, 104.2),
    _r(104.2, 107.5, 103.9, 107.0),
    _r(107.0, 108.0, 106.5, 107.5),
]


def test_idm_detector_merges_both_families():
    # two_candle_rule off -> BOS family only; on -> both, deduped by pullback.
    off = IDMDetector(_df(BOTH), bos_swing_length=2, bos_internal_length=2,
                      swing_tol_atr=0.0, two_candle_rule=False).detect_all()
    assert off and all(lv.rule == "bos" for lv in off)

    on = IDMDetector(_df(BOTH), bos_swing_length=2, bos_internal_length=2,
                     swing_tol_atr=0.0, two_candle_rule=True).detect_all()
    # Both families flag the same pullback bar -> one level, BOS wins.
    assert len(on) == 1
    assert on[0].rule == "bos"
    assert on[0].idm_type == IDMType.IDM_LOW
    assert on[0].formation_index == 8


def test_merged_output_has_no_duplicate_pullbacks():
    lv = IDMDetector(_df(BULL + [_r(114, 118, 108, 117)]),
                     two_candle_rule=True).detect_all()
    keys = [(x.idm_type, x.formation_index) for x in lv]
    assert len(keys) == len(set(keys))
