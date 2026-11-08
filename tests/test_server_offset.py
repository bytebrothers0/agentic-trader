"""Phase 6d: the ``offset`` query parameter on the data endpoints.

Exercised through a real ``TestClient`` with a monkeypatched loader, so no MT5
terminal is touched but the query default and validation are the real ones.
"""
import pandas as pd
from fastapi.testclient import TestClient


class _FakeLoader:
    def __init__(self, symbol="XAUUSDm"):
        self.resolved_symbol = symbol
        self.calls = []

    def fetch_timeframe(self, tf_key, count=None, start=0):
        self.calls.append((tf_key, count, start))
        count = int(count or 0)
        rows = [
            {
                "time": 1_800_000_000 + i * 900,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 3.0,
            }
            for i in range(count)
        ]
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("datetime")
        return df[["time", "open", "high", "low", "close", "volume"]]


def _client(monkeypatch, fake):
    import server

    monkeypatch.setattr(server, "get_loader", lambda symbol: fake)
    return TestClient(server.app)


def test_candles_forwards_offset_and_echoes_it(monkeypatch):
    fake = _FakeLoader()
    client = _client(monkeypatch, fake)

    resp = client.get(
        "/api/candles",
        params={"symbol": "XAUUSDm", "timeframe": "M15", "bars": 40, "offset": 7},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert fake.calls == [("M15", 40, 7)]
    assert payload["offset"] == 7
    assert payload["count"] == 40
    assert len(payload["candles"]) == 40


def test_candles_default_offset_is_zero(monkeypatch):
    fake = _FakeLoader()
    client = _client(monkeypatch, fake)

    resp = client.get("/api/candles", params={"timeframe": "D1", "bars": 40})
    assert resp.status_code == 200
    payload = resp.json()
    assert fake.calls == [("D1", 40, 0)]
    assert payload["offset"] == 0


def test_candles_offset_is_validated(monkeypatch):
    fake = _FakeLoader()
    client = _client(monkeypatch, fake)

    assert client.get("/api/candles", params={"offset": -1}).status_code == 422
    assert client.get("/api/candles", params={"offset": 10_000}).status_code == 422
    assert fake.calls == []  # refused before the loader is touched


def test_candles_accept_chart_history_above_agent_window_limit(monkeypatch):
    from server import MAX_CANDLE_BARS

    fake = _FakeLoader()
    client = _client(monkeypatch, fake)

    assert client.get("/api/candles", params={"bars": 300}).status_code == 200
    assert client.get("/api/candles", params={"bars": MAX_CANDLE_BARS}).status_code == 200
    assert client.get("/api/candles", params={"bars": MAX_CANDLE_BARS + 1}).status_code == 422


class _HistorylessLoader:
    """A loader that refuses every non-trivial request — a window past history."""

    def __init__(self, symbol="XAUUSDm"):
        self.resolved_symbol = symbol

    def fetch_timeframe(self, tf_key, count=None, start=0):
        from data.mt5_loader import InsufficientHistory

        raise InsufficientHistory(f"requested {count} {tf_key} bar(s) at start={start}")


def test_candles_past_history_is_422_not_500(monkeypatch):
    client = _client(monkeypatch, _HistorylessLoader())
    resp = client.get("/api/candles", params={"timeframe": "M15", "bars": 40, "offset": 4999})
    assert resp.status_code == 422
    assert "requested 40 M15" in resp.json()["detail"]


def test_indicators_past_history_is_422_not_500(monkeypatch):
    import server

    # Force the detector branch so the endpoint actually reads the feed.
    monkeypatch.setattr(server, "TS_ENABLED", True)
    client = _client(monkeypatch, _HistorylessLoader())
    resp = client.get("/api/indicators", params={"timeframe": "M15", "bars": 40, "offset": 4999})
    assert resp.status_code == 422
    assert "requested 40 M15" in resp.json()["detail"]


class _TSShapedLoader:
    """Bars shaped so the TS detector fires a MULTIPLE_CANDLE signal: the
    variant path whose ``inside_bars`` used to leak a numpy scalar (which
    FastAPI could not serialize — the endpoint 500'd on the logger's exact
    request)."""

    _SETUP = (
        {"open": 100, "high": 105, "low": 99, "close": 103},      # anchor
        {"open": 103, "high": 104.5, "low": 99.5, "close": 102},  # inside bar
        {"open": 103, "high": 103.5, "low": 98, "close": 103},    # drift: NOT inside
        {"open": 104, "high": 107, "low": 100, "close": 102},     # sweep
    )

    def __init__(self, symbol="XAUUSDm"):
        self.resolved_symbol = symbol

    def fetch_timeframe(self, tf_key, count=None, start=0):
        count = max(int(count or 0), 4)
        setup = [dict(b, time=1_799_999_996 + i * 900)
                 for i, b in enumerate(self._SETUP)]
        calm = [dict(open=100, high=101, low=99, close=100,
                     time=1_799_999_996 - (n + 1) * 900)
                for n in range(count - 4)]
        rows = sorted(calm + setup, key=lambda r: r["time"])
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("datetime")
        df["volume"] = 3.0
        return df[["time", "open", "high", "low", "close", "volume"]]


def test_indicators_ts_payload_is_json_clean(monkeypatch):
    import json as _json

    import server
    monkeypatch.setattr(server, "get_loader", lambda symbol: _TSShapedLoader())
    # Only TS on: isolates the ts payload block exactly like the live failing
    # request from the log (show_ts=true, every other category false).
    for flag in ("SR_ENABLED", "QM_ENABLED", "OCL_ENABLED", "APEX_ENABLED",
                 "IDM_ENABLED", "BOS_ENABLED", "FVG_ENABLED", "IFVG_ENABLED",
                 "OB_ENABLED", "TL_ENABLED"):
        try:
            monkeypatch.setattr(server, flag, False)
        except AttributeError:
            pass
    monkeypatch.setattr(server, "TS_ENABLED", True)
    client = _client(monkeypatch, _TSShapedLoader())

    resp = client.get(
        "/api/indicators",
        params={"symbol": "XAUUSDm", "timeframe": "M15", "bars": 40,
                "show_ts": "true", "show_sr": "false",
                "freshness_filter": "all"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()          # jsonable_encoder survived
    _json.dumps(body)           # plain stdlib round-trip too

    ts_levels = [l for l in body["levels"] if l["category"] == "ts"]
    assert any(l.get("variant") == "multiple_candle" for l in ts_levels)
    for level in ts_levels:
        assert isinstance(level["inside_bars"], int)
        assert isinstance(level["state"], str)
        assert level["end_kind"] in ("active", "invalidated")


def test_import_server_keeps_37_routes():
    import server

    assert len(server.app.routes) == 40  # 37 pinned + proposal-orders routes + /health


def test_sr_render_levels_keeps_real_walls_only():
    """The V/A detector emits ~one level per candle. The render layer reduces
    that to real walls: no gap/hidden zones, no used-up (2-touch) levels, no
    broken corpse alongside its own SBR/RBS successor, and one representative
    per 0.05% price cluster (alive wins, then newest)."""
    from indicators.candle_analyzer import CandleLevel, LevelState, LevelType
    import server

    def _lv(kind, idx, price, state=LevelState.FRESH, gap=False, touches=0,
            derived_from=None):
        return CandleLevel(
            level_type=kind, price=price, candle_index=idx,
            candle_time=pd.Timestamp("2026-10-19 10:00", tz="UTC")
            + pd.Timedelta(minutes=15 * idx),
            state=state, is_gap=gap, touch_count=touches,
            derived_from=derived_from,
        )

    corpse = _lv(LevelType.SUPPORT, 0, 100.0, LevelState.BROKEN)
    flip = _lv(LevelType.SBR, 2, 100.0, derived_from=corpse)            # redraws it
    hidden = _lv(LevelType.SUPPORT, 3, 101.0, gap=True)                 # hidden zone
    used_up = _lv(LevelType.RESISTANCE, 4, 105.0, touches=2)            # web 2-use
    wall_a = _lv(LevelType.RESISTANCE, 6, 110.000)
    wall_b = _lv(LevelType.RESISTANCE, 8, 110.005)                      # same wall
    wall_c = _lv(LevelType.RESISTANCE, 9, 110.008, LevelState.UNFRESH)  # alive twin
    far = _lv(LevelType.SUPPORT, 11, 105.0)                             # distinct wall

    got = server.sr_render_levels(
        [corpse, flip, hidden, used_up, wall_a, wall_b, wall_c, far])
    # The corpse/hidden/used-up drop; the flip survives (it IS the redrawn
    # wall); 110.000/110.005/110.008 cluster to one alive representative.
    # Representatives come back in cluster (price) order.
    assert got == [flip, far, wall_c]

    # An all-dead cluster sends the newest member.
    d1 = _lv(LevelType.SUPPORT, 1, 90.0, LevelState.BROKEN)
    d2 = _lv(LevelType.RBS, 5, 90.000, LevelState.BROKEN)
    assert server.sr_render_levels([d1, d2]) == [d2]
