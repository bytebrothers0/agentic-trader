"""Tests for the X-Factor (trendline x SNR confluence) indicator."""
import pandas as pd
from types import SimpleNamespace

from indicators.xfactor_detector import (
    XDetector, XDirection, detect_engulfing_zones, detect_storyline,
)
from indicators.trendline_detector import TLDetector, TLLine, TLSide, TLState
from indicators.candle_analyzer import CandleLevel, LevelType, LevelState
from indicators.ts_detector import TSLevel, TSType, TSDirection


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


def _row(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def _tl_upper(pivot=1, price=103.0, touches=(4,)):
    return TLLine(
        side=TLSide.UPPER, state=TLState.ACTIVE,
        pivot_price=price, pivot_index=pivot,
        pivot_time=pd.Timestamp("2024-01-02"), slope=0.0,
        end_index=9, end_time=pd.Timestamp("2024-01-10"),
        touches=len(touches), touch_bars=list(touches),
        anchor_kind="body", anchor_engulfing=True,
        alchemist="continuation",
    )


def _res(price=103.0, **kw):
    base = dict(level_type=LevelType.RESISTANCE, price=price,
                candle_index=0, candle_time=pd.Timestamp("2024-01-01"))
    base.update(kw)
    return CandleLevel(**base)


# Bars 0-3 hover under 103; bar 4 bull, bar 5 bear engulfs it (zone 99..104
# contains the 103 X); bars 6-9 flat doji at 101.
X_ROWS = [
    _row(100, 101, 99, 100),
    _row(100, 102, 99, 101),
    _row(101, 102, 100, 101.5),
    _row(101.5, 102.5, 100.5, 102),
    _row(100, 106, 99.5, 104),     # 4: bull
    _row(106, 106.5, 98.5, 99),    # 5: bear engulfs -> zone [99, 104]
    _row(101, 101.5, 100.5, 101),
    _row(101, 101.5, 100.5, 101),
    _row(101, 101.5, 100.5, 101),
    _row(101, 101.5, 100.5, 101),
]


def _ts_high(idx=5):
    return TSLevel(ts_type=TSType.TS_HIGH, direction=TSDirection.BEARISH,
                   price=106.0, candle_index=idx,
                   candle_time=pd.Timestamp("2024-01-06"))


def test_x_forms_with_a_plus_grade():
    df = _df(X_ROWS)
    det = XDetector(df, [_res()], [_tl_upper()],
                    ts_levels=[_ts_high()])
    lv = det.detect_all()
    assert len(lv) == 1, f"expected one X, got {lv}"
    x = lv[0]
    assert x.direction == XDirection.SHORT
    assert x.x_index == 5 and x.point2_index == 4
    assert x.engulf and x.sweep and not x.qm_match
    assert x.tier == "A+" and x.tradable
    assert x.score >= 5  # X + continuation + fresh + 2x engulf + sweep
    assert (x.ex_top, x.ex_bottom) == (104, 99)  # between-closes limit box


def test_x_without_engulf_is_no_trade():
    rows = [dict(r) for r in X_ROWS]
    rows[5] = _row(104, 104.5, 100.5, 102)  # small bear, no engulf
    df = _df(rows)
    det = XDetector(df, [_res()], [_tl_upper()],
                    ts_levels=[_ts_high()])
    lv = det.detect_all()
    assert len(lv) == 1
    assert lv[0].tier == "no-trade" and not lv[0].tradable


def test_qm_coincidence_upgrades_to_qmx():
    df = _df(X_ROWS)
    qm = SimpleNamespace(price=103.0)
    det = XDetector(df, [_res()], [_tl_upper()],
                    ts_levels=[_ts_high()], qm_levels=[qm])
    lv = det.detect_all()
    assert len(lv) == 1 and lv[0].tier == "QMX" and lv[0].tradable


def test_gap_level_never_forms_x():
    df = _df(X_ROWS)
    det = XDetector(df, [_res(is_gap=True)], [_tl_upper()],
                    ts_levels=[_ts_high()])
    assert det.detect_all() == []


def test_exhausted_level_never_forms_x():
    df = _df(X_ROWS)
    det = XDetector(df, [_res(touch_count=2)], [_tl_upper()],
                    ts_levels=[_ts_high()])
    assert det.detect_all() == []


def test_wrong_side_level_ignored():
    df = _df(X_ROWS)
    sup = CandleLevel(level_type=LevelType.SUPPORT, price=103.0,
                      candle_index=0,
                      candle_time=pd.Timestamp("2024-01-01"))
    det = XDetector(df, [sup], [_tl_upper()], ts_levels=[_ts_high()])
    assert det.detect_all() == []


def test_detector_lines_carry_touch_bars():
    # Two descending close peaks (103 @ 2, 102.5 @ 10) form a resistance line.
    closes = [100, 101, 103, 102, 101, 100, 99, 100, 101, 102, 102.5,
              102, 101, 100, 99, 98]
    rows = []
    prev = closes[0]
    for cl in closes:
        rows.append(_row(prev, max(prev, cl) + 0.5, min(prev, cl) - 0.5, cl))
        prev = cl
    df = _df(rows)
    lines = TLDetector(df, pivot_length=2).detect_all()
    assert lines and all(hasattr(x, "touch_bars") for x in lines)
    assert all(len(x.touch_bars) == x.touches for x in lines)


def test_engulf_zones_between_closes_and_gap_flag():
    df = _df([
        _row(100, 102, 99, 101),      # 0 bull
        _row(101, 101.5, 98, 99),     # 1 bear engulfs -> zone [99, 101]
        _row(99, 100, 98, 99.5),      # 2
        _row(105, 106, 104, 104.5),   # 3 gap up, bear
        _row(103, 107, 102, 106),     # 4 bull engulfs 3 with gap -> GAP zone
    ])
    zones = detect_engulfing_zones(df, gap_atr_mult=0.1)
    assert len(zones) == 2
    assert (zones[0].top, zones[0].bottom) == (101, 99)
    assert not zones[0].is_gap
    assert (zones[1].top, zones[1].bottom) == (106, 104.5)
    assert zones[1].is_gap


def test_storyline_htf_rejection_plus_ltf_bos():
    htf = _df([
        _row(98, 99, 97, 98),
        _row(98, 101, 97.5, 98),   # 1: wick touches 100, body back below
        _row(98, 99.5, 97, 97.5),
        _row(97.5, 98.5, 96.5, 97),
        _row(97, 98, 96, 96.5),
        _row(96.5, 97.5, 95.5, 96),
    ])
    lvl = CandleLevel(level_type=LevelType.RESISTANCE, price=100.0,
                      candle_index=0,
                      candle_time=pd.Timestamp("2024-01-01"),
                      state=LevelState.UNFRESH, first_touch_index=1)
    bos = [SimpleNamespace(direction="bearish", break_index=3)]
    st = detect_storyline(htf, [lvl], bos, XDirection.SHORT)
    assert st is not None
    assert st.direction == XDirection.SHORT and st.touch_index == 1
    assert st.bos_index == 3


def test_storyline_none_without_bos():
    htf = _df([
        _row(98, 99, 97, 98),
        _row(98, 101, 97.5, 98),
        _row(98, 99.5, 97, 97.5),
    ])
    lvl = CandleLevel(level_type=LevelType.RESISTANCE, price=100.0,
                      candle_index=0,
                      candle_time=pd.Timestamp("2024-01-01"),
                      state=LevelState.UNFRESH, first_touch_index=1)
    assert detect_storyline(htf, [lvl], [], XDirection.SHORT) is None
