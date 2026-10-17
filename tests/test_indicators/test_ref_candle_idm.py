"""Tests for the reference-candle ("candle 1") inducement family.

Rule: EVERY candle can be candle 1 — its high/low define a range — but the rule
follows the structure. In an upside structure a later candle taking candle 1's
LOW arms the pullback and a later candle taking candle 1's HIGH completes it;
the lowest low of that pullback series is the IDM. A downside structure mirrors
(candle 1's HIGH then LOW -> the highest high is the IDM).
"""
import pandas as pd

from indicators.bos_detector import BOSDetector
from indicators.idm_detector import (IDMDetector, IDMType, IDMDirection,
                                     RefCandleIDMDetector)
from indicators.swings import find_pivots


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=dates)


# Up-leg that breaks structure at bars 4 and 10 (BOS up), so the structure gate
# is bullish from bar 4 on. Bar 10 -> BOS.
BULL = [
    (99.0, 99.5, 97.5, 98.0),      # 0
    (98.0, 98.5, 96.0, 96.5),      # 1
    (96.5, 97.0, 94.0, 96.0),      # 2
    (96.0, 99.5, 95.5, 99.0),      # 3
    (99.0, 102.0, 98.5, 101.5),    # 4  BOS up
    (101.5, 104.0, 101.0, 103.5),  # 5
    (103.5, 106.0, 103.0, 105.6),  # 6
    (105.6, 105.8, 103.4, 104.0),  # 7
    (104.0, 104.5, 101.5, 102.0),  # 8
    (102.0, 104.5, 101.9, 104.2),  # 9
    (104.2, 107.5, 103.9, 107.0),  # 10 BOS up
    (107.0, 108.0, 106.5, 107.5),  # 11
    (107.5, 107.8, 105.0, 105.5),  # 12 takes 106.5 -> pullback
    (105.5, 106.0, 103.0, 103.5),  # 13 lowest low 103
    (103.5, 106.0, 103.0, 105.5),  # 14
    (105.5, 109.5, 105.0, 109.0),  # 15 takes 108 -> continuation
    (109.0, 110.0, 108.5, 109.5),  # 16
    (109.5, 110.0, 107.0, 107.5),  # 17
    (107.5, 108.0, 102.0, 102.5),  # 18 body close 102.5 < 103 -> broken
]

_KW = dict(bos_swing_length=2, bos_internal_length=2, swing_tol_atr=0.0)


def _ref(df, **kw):
    return RefCandleIDMDetector(df, **{**_KW, **kw}).detect_all()


def _mirror(rows, base=200.0):
    return [(base - c, base - l, base - h, base - o) for o, h, l, c in rows]


def test_upside_structure_marks_range_lows_only():
    lv = _ref(_df(BULL))
    assert {x.rule for x in lv} == {"ref_candle"}
    # upside structure -> only range-low IDMs, never range-high ones
    assert all(x.idm_type == IDMType.IDM_LOW for x in lv)
    assert all(x.direction == IDMDirection.BULLISH for x in lv)
    got = {(x.price, x.formation_index) for x in lv}
    assert got == {(101.5, 8), (103.0, 13), (102.0, 18)}


def test_downside_structure_marks_range_highs_only():
    lv = _ref(_df(_mirror(BULL)))
    assert all(x.idm_type == IDMType.IDM_HIGH for x in lv)
    assert all(x.direction == IDMDirection.BEARISH for x in lv)
    got = {(x.price, x.formation_index) for x in lv}
    assert got == {(98.5, 8), (97.0, 13), (98.0, 18)}   # 200 - {101.5, 103, 102}


def test_idm_is_the_lowest_point_of_the_pullback_series():
    # candle 1 @11 (h108, l106.5): bar 12 takes the low, bar 15 takes the high
    # -> IDM is the lowest low of bars 12..15, i.e. 103 @13 (not 106.5 @12).
    lv = _ref(_df(BULL))
    mid = next(x for x in lv if x.formation_index == 13)
    assert mid.price == 103.0
    assert mid.idm_type == IDMType.IDM_LOW


def test_body_close_through_is_broken_not_swept():
    lv = _ref(_df(BULL))
    mid = next(x for x in lv if x.formation_index == 13)
    assert mid.swept is False
    assert mid.broken is True
    assert mid.broken_index == 18


def test_candle_1_need_not_be_a_swing_point():
    # The 102.0 @18 IDM comes from candle 1 @13, which is NOT a fractal pivot.
    df = _df(BULL)
    lv = _ref(df)
    last = next(x for x in lv if x.formation_index == 18)
    assert last.confirm_index == 13
    pivots = {p.index for p in find_pivots(df["high"].values,
                                           df["low"].values, 2) if p.is_low}
    assert 13 not in pivots


def test_continuation_is_required():
    # candle 1 @11 has its low taken, but its high (108) is never taken -> no IDM
    rows = BULL[:11] + [
        (107.0, 108.0, 106.5, 107.5),   # 11 candle 1
        (107.5, 107.6, 105.0, 105.5),   # 12 takes 106.5
        (105.5, 107.5, 105.0, 107.0),   # 13 high 107.5 < 108
        (107.0, 107.2, 106.0, 106.5),   # 14
    ]
    lv = _ref(_df(rows))
    assert all(x.confirm_index != 11 for x in lv)
    # only the earlier, fully-formed pullback survives
    assert {(x.price, x.formation_index) for x in lv} == {(101.5, 8)}


def test_no_structure_break_means_no_idm():
    rows = [
        (100, 101, 99.5, 100.5), (100.5, 101.5, 100, 101),
        (101, 102, 100.8, 101.5), (101.5, 102.5, 101.2, 102),
        (102, 103, 101.8, 102.5), (102.5, 103.5, 102.2, 103),
    ]
    assert BOSDetector(_df(rows), swing_length=2, internal_length=2,
                       swing_tol_atr=0.0).detect_all() == []
    assert _ref(_df(rows)) == []


def test_short_frame_returns_empty():
    assert _ref(_df([(1, 2, 0.5, 1)])) == []


def test_idm_detector_merges_all_three_families():
    df = _df(BULL)
    out = IDMDetector(df, **_KW).detect_all()
    assert {x.rule for x in out} == {"bos", "two_candle", "ref_candle"}
    keys = [(x.idm_type, x.formation_index) for x in out]
    assert len(keys) == len(set(keys))          # no duplicated pullback

    # turning the family off drops its levels
    off = IDMDetector(df, ref_candle_rule=False, **_KW).detect_all()
    assert all(x.rule != "ref_candle" for x in off)
