"""Tests for the MNSR + TS entry model (M15)."""
import pandas as pd

from strategy.ts_entry import TSEntryEngine
from strategy.entry_engine import EntryModelType
from strategy.storyline_engine import BiasDirection


def _df(rows):
    df = pd.DataFrame(rows, index=pd.date_range("2024-01-01", periods=len(rows), freq="15min"))
    df["time"] = (df.index.astype("int64") // 10**9).astype(int)
    return df


BULL_CHAIN = [
    {"open": 101, "high": 102, "low": 99, "close": 100},
    {"open": 101, "high": 105, "low": 102, "close": 104},
    {"open": 104, "high": 104.5, "low": 100, "close": 103},
    {"open": 103, "high": 105, "low": 98, "close": 99.5},
    {"open": 101, "high": 102, "low": 96, "close": 99.5},
    {"open": 99.5, "high": 101, "low": 98.5, "close": 100.5},
    {"open": 100.5, "high": 102, "low": 100, "close": 101.5},
    {"open": 101.5, "high": 103, "low": 101, "close": 102.5},
    {"open": 102.5, "high": 102.5, "low": 100.5, "close": 101},
    {"open": 101, "high": 101.5, "low": 99.8, "close": 100.2},
    {"open": 100.2, "high": 102.5, "low": 100, "close": 101.5},
    {"open": 101.5, "high": 104, "low": 101, "close": 103.5},
    {"open": 103.5, "high": 106, "low": 103, "close": 105.5},
    {"open": 105.5, "high": 105.8, "low": 102.5, "close": 104},
    {"open": 104, "high": 107, "low": 103.5, "close": 106.5},
]


def test_bullish_full_chain():
    sigs = [s for s in TSEntryEngine(_df(BULL_CHAIN)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert len(sigs) == 1
    s = sigs[0]
    assert s.model_type == EntryModelType.MODEL_TS_M15
    assert s.primary_plan.raw_entry == 100
    assert s.primary_plan.stop_loss == 96.6   # 350pt fixed SL
    assert s.primary_plan.take_profit == 130  # 3000pt fixed TP
    assert s.primary_plan.sl_points == 350
    assert "IDM" in s.rationale and "QM@100" in s.rationale


def test_bearish_mirror_chain():
    rows = [{"open": 200 - r["open"], "close": 200 - r["close"],
             "high": 200 - r["low"], "low": 200 - r["high"]} for r in BULL_CHAIN]
    sigs = [s for s in TSEntryEngine(_df(rows)).scan()
            if s.direction == BiasDirection.BEARISH]
    assert len(sigs) == 1
    s = sigs[0]
    assert s.primary_plan.raw_entry == 100
    assert s.primary_plan.stop_loss == 103.4
    assert s.primary_plan.take_profit == 70


def test_sr_shelf_break_leg(monkeypatch):
    # Impulse with no confirmable swing: structure BOS muted, S/R shelf
    # carries the break leg -> SELL at the failed-RBS QM.
    from indicators import bos_detector
    monkeypatch.setattr(bos_detector.BOSDetector, "detect_all", lambda self: [])
    rows = [
        {"open": 108, "high": 110, "low": 107, "close": 109.5},
        {"open": 109.5, "high": 110, "low": 106, "close": 107},
        {"open": 107, "high": 112, "low": 106, "close": 111},
        {"open": 111, "high": 111.5, "low": 108, "close": 109},
        {"open": 109, "high": 110, "low": 106, "close": 109.5},
        {"open": 109.5, "high": 115, "low": 108, "close": 114},
        {"open": 114, "high": 118, "low": 112, "close": 112.5},
        {"open": 112.5, "high": 113, "low": 105, "close": 106},
        {"open": 106, "high": 106.5, "low": 102, "close": 103},
        {"open": 103, "high": 104, "low": 101, "close": 103.5},
        {"open": 103.5, "high": 107, "low": 102, "close": 106},
        {"open": 106, "high": 106.5, "low": 104, "close": 104.5},
        {"open": 104.5, "high": 105, "low": 104, "close": 104.2},
    ]
    sigs = [s for s in TSEntryEngine(_df(rows)).scan()
            if s.direction == BiasDirection.BEARISH]
    assert len(sigs) == 1
    s = sigs[0]
    assert s.primary_plan.raw_entry == 109.5
    assert s.primary_plan.stop_loss == 112.9
    assert s.primary_plan.take_profit == 79.5
    assert "SR break" in s.rationale


def test_no_idm_fallback_to_support(monkeypatch):
    from indicators import idm_detector
    monkeypatch.setattr(idm_detector.IDMDetector, "detect_all", lambda self: [])
    rows = BULL_CHAIN + [
        {"open": 106.5, "high": 107, "low": 97, "close": 98},
        {"open": 98, "high": 99, "low": 97.5, "close": 98.5},
    ]
    sigs = [s for s in TSEntryEngine(_df(rows)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert len(sigs) == 1
    s = sigs[0]
    assert s.primary_plan.raw_entry == 98
    assert s.primary_plan.stop_loss == 94.6
    assert s.primary_plan.take_profit == 128
    assert "fallback" in s.rationale


def test_stale_ts_skipped(monkeypatch):
    import strategy.ts_entry as te
    monkeypatch.setattr(te, "TS_ENTRY_MAX_AGE", 5)
    sigs = TSEntryEngine(_df(BULL_CHAIN)).scan()
    assert [s for s in sigs if s.direction == BiasDirection.BULLISH] == []


def test_qm_after_liquidity_excluded(monkeypatch):
    from types import SimpleNamespace
    from indicators.qm_detector import QMDirection
    from indicators import qm_detector
    late_qm = SimpleNamespace(price=100.0, break_candle_index=14,
                              direction=QMDirection.BULLISH)
    monkeypatch.setattr(qm_detector.QMDetector, "detect_all", lambda self: [late_qm])
    sigs = [s for s in TSEntryEngine(_df(BULL_CHAIN)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert sigs == []
    # Same QM confirmed BEFORE the IDM -> valid entry.
    early_qm = SimpleNamespace(price=100.0, break_candle_index=6,
                               direction=QMDirection.BULLISH)
    monkeypatch.setattr(qm_detector.QMDetector, "detect_all", lambda self: [early_qm])
    sigs = [s for s in TSEntryEngine(_df(BULL_CHAIN)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert len(sigs) == 1 and sigs[0].primary_plan.raw_entry == 100


def test_far_stack_rejected_by_proximity_cap(monkeypatch):
    import strategy.ts_entry as te
    monkeypatch.setattr(te, "TS_MAX_QM_DIST", 0.5)
    sigs = [s for s in TSEntryEngine(_df(BULL_CHAIN)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert sigs == []


def test_fractal_liquidity_path(monkeypatch):
    from indicators import idm_detector
    monkeypatch.setattr(idm_detector.IDMDetector, "detect_all", lambda self: [])
    rows = BULL_CHAIN + [
        {"open": 106.5, "high": 107, "low": 100.3, "close": 101.5},
        {"open": 101.5, "high": 102, "low": 101, "close": 101.5},
        {"open": 101.5, "high": 102.5, "low": 101.2, "close": 102},
    ]
    sigs = [s for s in TSEntryEngine(_df(rows)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert len(sigs) == 1
    s = sigs[0]
    assert s.primary_plan.raw_entry == 100
    assert "LIQ@" in s.rationale


def test_qm_outside_ts_bos_sandwich_rejected(monkeypatch):
    # QM above the break level (not between TS and BOS): misleading QM,
    # no entry even though it sits below the liquidity.
    from types import SimpleNamespace
    from indicators.qm_detector import QMDirection
    from indicators.idm_detector import IDMType, IDMDetector
    from indicators import qm_detector
    high_qm = SimpleNamespace(price=104.0, break_candle_index=6,
                              direction=QMDirection.BULLISH)
    monkeypatch.setattr(qm_detector.QMDetector, "detect_all", lambda self: [high_qm])
    high_idm = SimpleNamespace(idm_type=IDMType.IDM_LOW, price=106.0,
                               formation_index=12)
    monkeypatch.setattr(IDMDetector, "detect_all", lambda self: [high_idm])
    sigs = [s for s in TSEntryEngine(_df(BULL_CHAIN)).scan()
            if s.direction == BiasDirection.BULLISH]
    assert sigs == []
