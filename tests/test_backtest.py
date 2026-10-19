"""Phase CRT-backtest: the frozen replay feed and the CRT scanner.

Two things carry the backtest's honesty, and both are pinned here:

* ``backtest.historical.FrozenLoader`` never serves a bar that had not closed by
  the freeze instant. If it did, the agent would see the future and the replay
  would be worthless. ``fetch_timeframe`` keeps MT5's "bars back from the newest"
  semantics, so the agent's ``view.offset`` behaves exactly as it does live.
* ``backtest.crt_scan`` finds a *classic* three-candle CRT, prices it as a naive
  trade from the manipulation close, and reports the R:R that trade carried.

No MT5 terminal and no model: the frames are synthetic and the detector is real.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtest.crt_scan import scan_classic_crts
from backtest.historical import TF_SECONDS, FrozenLoader

T0 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)


def _frame(rows, *, timeframe="M15", start=T0):
    """Build an ``MT5DataLoader``-shaped frame from ``(o, h, l, c)`` rows."""
    step = timedelta(seconds=TF_SECONDS[timeframe])
    index = pd.DatetimeIndex([start + i * step for i in range(len(rows))], name="datetime")
    return pd.DataFrame(
        {
            "time": [int(ts.timestamp()) for ts in index],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1] * len(rows),
        },
        index=index,
    )


def _flat(count, base=100.0, step=0.0):
    return [(base + i * step, base + i * step + 1, base + i * step - 1, base + i * step + 0.5)
            for i in range(count)]


def _freeze_after(frame, timeframe, closed_count):
    """An instant at which exactly ``closed_count`` bars of ``frame`` have closed."""
    step = TF_SECONDS[timeframe]
    last_open = frame.index[closed_count - 1]
    return (last_open + pd.Timedelta(seconds=step)).to_pydatetime()


# --------------------------------------------------------------------------- #
# The frozen loader
# --------------------------------------------------------------------------- #

def test_fetch_ends_at_the_freeze_and_never_crosses_it():
    frame = _frame(_flat(200))
    as_of = _freeze_after(frame, "M15", 101)      # bars 0..100 have closed
    loader = FrozenLoader("XAUUSDm", {"M15": frame}, as_of)

    window = loader.fetch_timeframe("M15", count=5)
    assert list(window.index) == list(frame.index[96:101])
    assert len(loader.closed["M15"]) == 101

    # The invariant: every served bar had closed at or before as_of.
    last = window.index[-1]
    assert last + pd.Timedelta(seconds=900) <= pd.Timestamp(as_of)


def test_start_shifts_the_window_back_from_the_freeze():
    frame = _frame(_flat(200))
    as_of = _freeze_after(frame, "M15", 101)
    loader = FrozenLoader("XAUUSDm", {"M15": frame}, as_of)

    window = loader.fetch_timeframe("M15", count=5, start=3)
    assert list(window.index) == list(frame.index[93:98])


def test_a_window_the_feed_does_not_hold_is_refused():
    from data.mt5_loader import InsufficientHistory

    frame = _frame(_flat(200))
    as_of = _freeze_after(frame, "M15", 101)
    loader = FrozenLoader("XAUUSDm", {"M15": frame}, as_of)

    with pytest.raises(InsufficientHistory):
        loader.fetch_timeframe("M15", count=200)   # only 101 settled
    with pytest.raises(InsufficientHistory):
        loader.fetch_timeframe("H1", count=10)     # never preloaded


def test_a_synthesized_timeframe_is_built_from_the_frozen_m15():
    # 300 M15 bars -> 75 M45 bars; freeze after 250 M15 bars have closed.
    frame = _frame(_flat(300))
    as_of = _freeze_after(frame, "M15", 250)
    loader = FrozenLoader("XAUUSDm", {"M15": frame}, as_of)

    m45 = loader.fetch_timeframe("M45", count=10)
    assert len(m45) == 10
    step = (m45.index[1] - m45.index[0]).total_seconds()
    assert step == TF_SECONDS["M45"]
    assert m45.index[-1] + pd.Timedelta(seconds=TF_SECONDS["M45"]) <= pd.Timestamp(as_of)


# --------------------------------------------------------------------------- #
# The scanner
# --------------------------------------------------------------------------- #

def _classic_bullish_frame():
    """Flat noise, then a textbook bullish CRT that distributes in one bar."""
    rows = _flat(50, base=104.0, step=0.01)
    rows += [
        (105.0, 110.0, 100.0, 105.0),   # anchor: CRH 110 / CRL 100
        (101.0, 103.0, 98.0, 102.0),    # manipulation: sweeps CRL, closes back in
        (102.0, 111.0, 101.0, 110.0),   # distribution: reaches CRH
    ]
    rows += _flat(10, base=110.0, step=0.01)
    return _frame(rows)


def test_scan_finds_the_classic_crt_and_prices_the_naive_trade():
    frame = _classic_bullish_frame()
    found = scan_classic_crts(
        frame, "M15", since=None, min_rr=0.0, only_distributed=True, top=50
    )
    bullish = [
        c for c in found
        if c.direction == "bullish"
        and abs(c.crh - 110.0) < 1e-6
        and abs(c.crl - 100.0) < 1e-6
    ]
    assert bullish, "the textbook bullish CRT was not detected"
    cand = bullish[0]
    assert cand.state == "distributed"
    assert cand.variant == "classic"
    assert cand.bars_to_target == 1
    # entry is the manipulation close; target is the far boundary; stop is beyond
    # the sweep wick, so risk is strictly positive and R:R is a real number.
    assert cand.entry == pytest.approx(102.0)
    assert cand.target == pytest.approx(110.0)
    assert cand.stop < 98.0
    assert cand.risk > 0 and cand.rr > 0


def test_scan_drops_setups_that_did_not_work_when_asked():
    # A bullish CRT whose target is never reached: only_distributed must drop it.
    rows = _flat(50, base=104.0, step=0.01)
    rows += [
        (105.0, 110.0, 100.0, 105.0),   # anchor
        (101.0, 103.0, 98.0, 102.0),    # manipulation (sweeps and reclaims)
        (102.0, 104.0, 101.0, 103.0),   # drifts, never reaches CRH
    ]
    rows += _flat(10, base=103.0, step=0.01)
    frame = _frame(rows)

    resolved = scan_classic_crts(frame, "M15", since=None, min_rr=0.0, top=50)
    assert not [
        c for c in resolved
        if c.direction == "bullish" and abs(c.crh - 110.0) < 1e-6
        and c.state == "distributed"
    ]
    everything = scan_classic_crts(
        frame, "M15", since=None, min_rr=0.0, only_distributed=False, top=50
    )
    assert [
        c for c in everything
        if c.direction == "bullish" and abs(c.crh - 110.0) < 1e-6
    ], "the setup should still be visible when unresolved setups are allowed"
