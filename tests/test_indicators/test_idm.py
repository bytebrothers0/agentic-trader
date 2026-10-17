"""Tests for the BOS-anchored IDM (inducement) indicator.

Rule: after a structural break (BOS), the inducement is the most recent minor
fractal swing inside the impulse leg that sits beyond the leg origin (a
genuine higher low / lower high). No internal pullback -> no IDM. The detector
emits one IDM per break, deduped and capped per direction.

These tests pin the BOS family (``two_candle_rule=False``, ``ref_candle_rule=
False``) so the Luap families don't pollute the assertions; see
``test_luap_idm.py`` and ``test_ref_candle_idm.py``.
"""
import pandas as pd

from indicators.idm_detector import IDMDetector, IDMType


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _det(df, **kw):
    # Small, deterministic sensitivity so short fixtures still produce a BOS.
    kw.setdefault("bos_swing_length", 2)
    kw.setdefault("bos_internal_length", 2)
    kw.setdefault("swing_tol_atr", 0.0)
    kw.setdefault("two_candle_rule", False)
    kw.setdefault("ref_candle_rule", False)
    return IDMDetector(df, **kw)


def _lows(df, **kw):
    return [x for x in _det(df, **kw).detect_all()
            if x.idm_type == IDMType.IDM_LOW]


def _highs(df, **kw):
    return [x for x in _det(df, **kw).detect_all()
            if x.idm_type == IDMType.IDM_HIGH]


def _mirror(rows, base=200.0):
    """Flip a bullish fixture into its bearish mirror image."""
    return [
        {"open": base - r["close"], "high": base - r["low"],
         "low": base - r["high"], "close": base - r["open"]}
        for r in rows
    ]


# Origin low @2 (94.0), swing high @6 (106.0), higher low @8 (101.5),
# close-through BOS @10 -> IDM = 101.5 @8.
BULL_ROWS = [
    {"open": 99.0, "high": 99.5, "low": 97.5, "close": 98.0},
    {"open": 98.0, "high": 98.5, "low": 96.0, "close": 96.5},
    {"open": 96.5, "high": 97.0, "low": 94.0, "close": 96.0},
    {"open": 96.0, "high": 99.5, "low": 95.5, "close": 99.0},
    {"open": 99.0, "high": 102.0, "low": 98.5, "close": 101.5},
    {"open": 101.5, "high": 104.0, "low": 101.0, "close": 103.5},
    {"open": 103.5, "high": 106.0, "low": 103.0, "close": 105.6},
    {"open": 105.6, "high": 105.8, "low": 103.4, "close": 104.0},
    {"open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0},
    {"open": 102.0, "high": 104.5, "low": 101.9, "close": 104.2},
    {"open": 104.2, "high": 107.5, "low": 103.9, "close": 107.0},
    {"open": 107.0, "high": 108.0, "low": 106.5, "close": 107.5},
]


def test_bullish_idm_anchored_on_bos():
    lv = _lows(_df(BULL_ROWS))
    assert len(lv) == 1
    idm = lv[0]
    assert idm.price == 101.5
    assert idm.direction.value == "bullish"
    assert idm.formation_index == 8
    assert idm.swept is False
    assert idm.bos_break_index == 10
    assert idm.bos_kind in {"BOS", "I-BOS"}


def test_bearish_idm_is_mirror():
    hv = _highs(_df(_mirror(BULL_ROWS)))
    assert len(hv) == 1
    idm = hv[0]
    assert idm.price == 200.0 - 101.5      # 98.5
    assert idm.direction.value == "bearish"
    assert idm.formation_index == 8
    assert idm.swept is False


def test_swept_after_bos():
    rows = BULL_ROWS + [
        {"open": 108.0, "high": 108.5, "low": 107.0, "close": 108.2},
        {"open": 108.2, "high": 108.4, "low": 100.0, "close": 107.0},
    ]
    lv = _lows(_df(rows))
    assert len(lv) == 1
    assert lv[0].price == 101.5
    assert lv[0].swept is True
    assert lv[0].sweep_index == 13


def test_body_close_through_is_broken_not_swept():
    # Price closes *through* the IDM -> invalidated (broken), not a sweep.
    rows = BULL_ROWS + [
        {"open": 108.0, "high": 108.2, "low": 103.0, "close": 103.5},
        {"open": 103.5, "high": 104.0, "low": 99.0, "close": 100.0},
    ]
    lv = _lows(_df(rows))
    assert len(lv) == 1
    assert lv[0].swept is False
    assert lv[0].broken is True
    assert lv[0].broken_index == 13


def test_lower_low_is_not_an_inducement():
    # The pullback makes a LOWER low (below the leg origin) -> not an IDM.
    rows = [
        {"open": 99.0, "high": 99.5, "low": 97.5, "close": 98.0},
        {"open": 98.0, "high": 98.5, "low": 96.0, "close": 96.5},
        {"open": 96.5, "high": 97.0, "low": 94.0, "close": 96.0},
        {"open": 96.0, "high": 99.5, "low": 95.5, "close": 99.0},
        {"open": 99.0, "high": 102.0, "low": 98.5, "close": 101.5},
        {"open": 101.5, "high": 104.0, "low": 101.0, "close": 103.5},
        {"open": 103.5, "high": 106.0, "low": 103.0, "close": 105.6},
        {"open": 105.6, "high": 105.8, "low": 101.0, "close": 101.5},
        {"open": 101.5, "high": 101.8, "low": 92.0, "close": 93.0},
        {"open": 93.0, "high": 96.0, "low": 92.5, "close": 95.5},
        {"open": 95.5, "high": 107.5, "low": 95.0, "close": 107.0},
    ]
    assert _lows(_df(rows)) == []


def test_cap_keeps_newest_per_side():
    rows = BULL_ROWS + [
        {"open": 107.5, "high": 108.5, "low": 107.0, "close": 108.0},
        {"open": 108.0, "high": 110.0, "low": 107.5, "close": 109.6},
        {"open": 109.6, "high": 109.8, "low": 107.0, "close": 107.5},
        {"open": 107.5, "high": 108.0, "low": 105.5, "close": 106.0},
        {"open": 106.0, "high": 107.5, "low": 105.8, "close": 107.2},
        {"open": 107.2, "high": 111.5, "low": 107.0, "close": 111.0},
        {"open": 111.0, "high": 112.0, "low": 110.5, "close": 111.5},
        {"open": 111.5, "high": 112.5, "low": 111.0, "close": 112.0},
    ]
    lv = _lows(_df(rows), max_per_side=1)
    assert len(lv) == 1
    assert lv[0].formation_index == 15      # the newer of the two IDMs


def test_short_frame_returns_empty():
    df = _df([{"open": 1, "high": 2, "low": 0.5, "close": 1}])
    assert _det(df).detect_all() == []
