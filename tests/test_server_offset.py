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


def test_import_server_keeps_37_routes():
    import server

    assert len(server.app.routes) == 37
