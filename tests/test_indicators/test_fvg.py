"""Tests for FVG + IFVG (LuxAlgo detectFVG port + overlap inversion)."""
import pandas as pd

from indicators.fvg_detector import FVGDetector, FVGDirection


def _df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates)


GAP_UP = [
    {"open": 100, "high": 101, "low": 99, "close": 100},
    {"open": 100, "high": 102, "low": 99.5, "close": 101.5},
    {"open": 101.5, "high": 104, "low": 103, "close": 103.5},
]


def test_bullish_fvg_zone_bounds():
    fv = FVGDetector(_df(GAP_UP)).detect_all()
    assert len(fv) == 1
    assert fv[0].direction == FVGDirection.BULLISH
    assert fv[0].bottom == 101 and fv[0].top == 103
    assert fv[0].formation_index == 2
    assert not fv[0].mitigated
    assert fv[0].fresh


def test_gap_with_mid_close_inside_is_fvg():
    # Web-exact: pure 3-candle gap counts even when the middle candle
    # closed inside the gap (no displacement clause).
    df = _df([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 100, "high": 102, "low": 99.5, "close": 100.5},
        {"open": 101.5, "high": 104, "low": 103, "close": 103.5},
    ])
    fv = FVGDetector(df).detect_all()
    assert len(fv) == 1 and fv[0].direction == FVGDirection.BULLISH


def test_no_gap_no_fvg():
    df = _df([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 100, "high": 102, "low": 99.5, "close": 101},
        {"open": 101, "high": 102, "low": 100, "close": 101.5},
    ])
    assert FVGDetector(df).detect_all() == []


def test_mitigation_on_close_through():
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
    ])
    fv = FVGDetector(df).detect_all()
    bull = [x for x in fv if x.direction == FVGDirection.BULLISH]
    assert len(bull) == 1 and bull[0].mitigated
    assert bull[0].mitigation_index == 4


def test_ifvg_opposite_overlap_inverts():
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
    ])
    det = FVGDetector(df)
    iv = det.detect_ifvg(det.detect_all())
    assert len(iv) == 1
    assert iv[0].direction == FVGDirection.BEARISH
    # The genuine OVERLAP region (here the engulfing case equals it).
    assert iv[0].top == 103 and iv[0].bottom == 102
    assert iv[0].formation_index == 4


def test_ifvg_stale_first_fvg_ignored():
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
    ])
    det = FVGDetector(df, max_gap_bars=1)
    assert det.detect_ifvg(det.detect_all()) == []


def test_ifvg_wick_only_return_ignored():
    # Overlap exists but every close holds inside the first zone: no break.
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 104, "low": 102.8, "close": 102.5},
        {"open": 103.2, "high": 102.5, "low": 101.5, "close": 102},
    ])
    det = FVGDetector(df)
    fv = det.detect_all()
    assert any(x.direction == FVGDirection.BEARISH for x in fv)  # overlap exists
    assert det.detect_ifvg(fv) == []


def test_ifvg_sliver_overlap_rejected():
    # Break + recency hold, but the overlap is a wick-tip kiss (11% and
    # 29% of the smaller zones): not a proper overlap, no IFVG.
    df = _df([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 100, "high": 103.6, "low": 99.5, "close": 101.5},
        {"open": 101.5, "high": 104, "low": 103, "close": 103.5},
        {"open": 103.5, "high": 105, "low": 103.8, "close": 104.5},
        {"open": 104.5, "high": 104.6, "low": 104, "close": 103.7},
        {"open": 104.2, "high": 102.9, "low": 102, "close": 102.5},
        {"open": 102.5, "high": 102.6, "low": 99, "close": 99.5},
    ])
    det = FVGDetector(df)
    fv = det.detect_all()
    assert any(x.direction == FVGDirection.BEARISH for x in fv)
    assert det.detect_ifvg(fv) == []


def test_no_overlap_no_ifvg():
    # Only bullish gaps stacked upward: nothing opposite, no inversion.
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 105, "low": 104, "close": 104.5},
        {"open": 104.5, "high": 106, "low": 105, "close": 105.5},
    ])
    det = FVGDetector(df)
    fv = det.detect_all()
    assert fv and all(x.direction == FVGDirection.BULLISH for x in fv)
    assert det.detect_ifvg(fv) == []


def test_sliver_gap_filtered():
    # 0.05 gap with ~2.0 ATR: too thin to see, skipped.
    df = _df([
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 100, "high": 102, "low": 99.5, "close": 101.5},
        {"open": 101.5, "high": 103, "low": 101.05, "close": 102.5},
    ])
    assert FVGDetector(df, min_atr_mult=0.1).detect_all() == []
    # Same gap passes with the filter off.
    assert len(FVGDetector(df, min_atr_mult=0.0).detect_all()) == 1


def test_fvg_fresh_property_tracks_mitigation():
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
    ])
    bull = [x for x in FVGDetector(df).detect_all()
            if x.direction == FVGDirection.BULLISH][0]
    assert bull.mitigated and not bull.fresh


def test_ifvg_unmitigated_is_fresh():
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
    ])
    det = FVGDetector(df)
    iv = det.detect_ifvg(det.detect_all())
    assert len(iv) == 1
    assert iv[0].fresh and not iv[0].mitigated


def test_ifvg_mitigation_on_close_back_through():
    # Bearish IFVG [102..103] forms at idx 4, then price closes back above
    # its top -> mitigated (no longer shown).
    df = _df(GAP_UP + [
        {"open": 103.5, "high": 103.8, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 98, "close": 98.5},
        {"open": 98.5, "high": 103.3, "low": 98.4, "close": 103.2},
    ])
    det = FVGDetector(df)
    iv = det.detect_ifvg(det.detect_all())
    assert len(iv) == 1 and iv[0].direction == FVGDirection.BEARISH
    assert iv[0].mitigated and iv[0].mitigation_index == 5
    assert not iv[0].fresh
