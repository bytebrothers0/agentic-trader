"""Phase 6d: the MT5 loader's ``start`` (offset) parameter.

``fetch_timeframe(tf, count, start)`` maps ``start`` onto MT5's ``start_pos`` (the
number of bars to skip back from the newest bar) and the synthesized M45 path
slices the same window out of M15. No MT5 terminal: ``copy_rates_from_pos`` is
monkeypatched to return deterministic rows.
"""
from datetime import datetime, timezone

import pytest

import data.mt5_loader as mt5_loader
from data.mt5_loader import MT5DataLoader

ORIGIN_TS = int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp())


def _m15(count, origin=ORIGIN_TS):
    return [
        {
            "time": origin + i * 900,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "tick_volume": 1,
        }
        for i in range(count)
    ]


@pytest.fixture
def loader():
    inst = MT5DataLoader("XAUUSDm")
    inst._connected = True
    inst.resolved_symbol = "XAUUSDm"
    return inst


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """Tests collapse the mid-download retry wait (the logic stays, the sleep goes)."""
    monkeypatch.setattr(mt5_loader, "FEED_RETRY_WAIT_S", 0.0)


def test_start_is_passed_to_copy_rates_from_pos_and_shifts_the_window(loader, monkeypatch):
    seen = {}
    latest = ORIGIN_TS + 10_000 * 3600  # the broker's newest H1 bar

    def fake(symbol, timeframe, start, count):
        seen["args"] = (symbol, timeframe, start, count)
        # Model a fixed newest bar: start_pos counts back from it, ascending.
        return [
            {
                "time": latest - (start + (count - 1 - i)) * 3600,
                "open": 1.0,
                "high": 1.5,
                "low": 0.5,
                "close": 1.2,
                "tick_volume": 1,
            }
            for i in range(count)
        ]

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    df = loader.fetch_timeframe("H1", count=50, start=10)
    assert seen["args"][0] == "XAUUSDm"
    assert seen["args"][2] == 10  # start_pos
    assert seen["args"][3] == 50  # bars
    assert len(df) == 50
    # The window really moved back 10 bars: both ends are 10 h behind the live edge.
    assert int(df["time"].iloc[-1]) == latest - 10 * 3600
    assert int(df["time"].iloc[0]) == latest - (10 + 50 - 1) * 3600

    live = loader.fetch_timeframe("H1", count=50, start=0)
    assert int(live["time"].iloc[-1]) == latest
    assert int(live["time"].iloc[0]) != int(df["time"].iloc[0])


def test_default_start_is_zero(loader, monkeypatch):
    seen = {}

    def fake(symbol, timeframe, start, count):
        seen["start"] = start
        return [
            {
                "time": ORIGIN_TS + i * 3600,
                "open": 1.0,
                "high": 1.5,
                "low": 0.5,
                "close": 1.2,
                "tick_volume": 1,
            }
            for i in range(count)
        ]

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)
    loader.fetch_timeframe("H1", count=5)
    assert seen["start"] == 0


def test_resample_slices_the_right_m15_window(loader, monkeypatch):
    def fake(symbol, timeframe, start, count):
        # the synthesized path only ever calls this for native M15
        return _m15(count)

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    df = loader.fetch_timeframe("M45", count=5, start=2)
    # 8 M45 bars are available from 24 M15 bars; the newest 2 are dropped, then
    # the last 5 of the remaining 6 are returned -> original indices 1..5.
    assert list(df["time"]) == [ORIGIN_TS + 2700 * i for i in range(1, 6)]


def test_resample_start_zero_is_the_latest_window(loader, monkeypatch):
    def fake(symbol, timeframe, start, count):
        return _m15(count)

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    df = loader.fetch_timeframe("M45", count=5)
    # start=0 fetches 18 M15 bars -> 6 M45 bars; the last 5 are returned (1..5).
    assert list(df["time"]) == [ORIGIN_TS + 2700 * i for i in range(1, 6)]


def test_resample_raises_when_the_offset_is_beyond_the_history(loader, monkeypatch):
    def fake(symbol, timeframe, start, count):
        return _m15(6)  # the broker only holds 6 M15 bars -> 2 M45 bars

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    with pytest.raises(mt5_loader.InsufficientHistory):
        loader.fetch_timeframe("M45", count=5, start=2)


def test_native_short_window_raises_insufficient_history(loader, monkeypatch):
    # ``copy_rates_from_pos`` silently returns a short series when the request
    # reaches past the oldest bar; an explicit window must surface it.
    def fake(symbol, timeframe, start, count):
        return _m15(count - 3)

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    with pytest.raises(mt5_loader.InsufficientHistory) as exc:
        loader.fetch_timeframe("M15", count=50)
    assert isinstance(exc.value, ValueError)  # a client error, not a bare crash


def test_offset_past_history_raises_insufficient_history(loader, monkeypatch):
    def fake(symbol, timeframe, start, count):
        return []  # nothing left at this start_pos

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    with pytest.raises(mt5_loader.InsufficientHistory):
        loader.fetch_timeframe("M15", count=50, start=5000)


def test_no_explicit_count_keeps_the_legacy_runtime_error(loader, monkeypatch):
    # ``fetch_all_timeframes`` calls with no count; an empty feed is still a
    # genuine error there, not a fixable offset refusal.
    def fake(symbol, timeframe, start, count):
        return []

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    with pytest.raises(RuntimeError):
        loader.fetch_timeframe("M15")


# --------------------------------------------------------------------------- #
# The mid-download transient (a fresh terminal returns nothing on first ask)
# --------------------------------------------------------------------------- #

def test_empty_then_full_is_served_not_refused(loader, monkeypatch):
    """First ask returns nothing (the terminal is downloading the series), the
    second succeeds — the client must see candles, not a 422."""
    attempts = []

    def fake(symbol, timeframe, start, count):
        attempts.append(1)
        return _m15(count) if len(attempts) >= 2 else []

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    df = loader.fetch_timeframe("D1", count=300)
    assert len(attempts) == 2
    assert len(df) == 300


def test_short_then_full_is_served_not_refused(loader, monkeypatch):
    """A short first window (download mid-flight) also resolves on the retry."""
    attempts = []

    def fake(symbol, timeframe, start, count):
        attempts.append(1)
        return _m15(count) if len(attempts) >= 2 else _m15(count - 10)

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    df = loader.fetch_timeframe("D1", count=300)
    assert len(df) == 300


def test_a_feed_that_stays_empty_names_the_terminal_error(loader, monkeypatch):
    def fake(symbol, timeframe, start, count):
        return []

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)
    monkeypatch.setattr(mt5_loader.mt5, "last_error", lambda: (1, "history not loaded"))

    with pytest.raises(mt5_loader.InsufficientHistory) as exc:
        loader.fetch_timeframe("D1", count=300)
    # the diagnosis says WHY: not 'none' alone, the terminal state rides along
    assert "history not loaded" in str(exc.value)


def test_a_feed_that_stays_short_after_retries_still_refuses(loader, monkeypatch):
    attempts = []

    def fake(symbol, timeframe, start, count):
        attempts.append(1)
        return _m15(count - 3)  # the broker genuinely holds fewer bars

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake)

    with pytest.raises(mt5_loader.InsufficientHistory):
        loader.fetch_timeframe("D1", count=300)
    assert len(attempts) == mt5_loader.FEED_RETRY_ATTEMPTS


def test_a_dead_ipc_pipe_reattaches_and_serves(loader, monkeypatch):
    """A stray ``mt5.shutdown()`` anywhere drops the *process-wide* pipe; the
    loader's next fetch must heal in place ("-10004 No IPC connection" first,
    candles on the retry) instead of 422-ing until the server restarts."""
    calls = []
    attached = []

    def fake_copy(symbol, timeframe, start, count):
        calls.append(1)
        return None if len(calls) == 1 else _m15(count)

    monkeypatch.setattr(mt5_loader.mt5, "copy_rates_from_pos", fake_copy)
    monkeypatch.setattr(
        mt5_loader.mt5, "last_error", lambda: (-10004, "No IPC connection")
    )
    monkeypatch.setattr(
        mt5_loader.mt5, "initialize", lambda **kw: attached.append(1) or True
    )
    monkeypatch.setattr(mt5_loader.mt5, "symbol_select", lambda *a, **kw: True)

    df = loader.fetch_timeframe("D1", count=300)

    assert len(df) == 300
    assert attached and len(calls) == 2  # one reattach, then a healing copy
