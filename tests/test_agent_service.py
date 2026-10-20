"""Tests for the agent runtime service (spec phase 6a backend).

The whole runtime runs in-memory: a ``_fixtures``-style feed stub, a
``FakeRenderer``-equivalent, the zero-spend ``ScriptedAgent`` and an injected
``FakeClock``. ``agent_service`` is imported cheaply — it must not need ``server``,
MT5 or ``config.settings`` — so this file is a real check of that contract too.
"""
from __future__ import annotations

import email.utils
import io
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

# The shared fakes live beside the pure-core tests; make them importable without
# duplicating them here.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "test_agentic"))

from _fixtures import (  # noqa: E402
    FakeClock,
    FakeRenderer,
    FeedStub,
    at,
    bars_rows,
)

from agent_service import (  # noqa: E402
    TRANSPORT_MAX_RETRIES,
    TRANSPORT_RETRY_CAP_S,
    AgentConfig,
    AgentService,
    _chat_completions_url,
    _request_headers,
    build_client,
    make_transport,
)
from agentic.agent_loop import MAX_TOOL_ROUNDS, AgentLoop  # noqa: E402
from agentic.agent_loop import AgentReply, ScriptedAgent  # noqa: E402
from agentic.models import SubscriptionKind, SubscriptionState, Trigger  # noqa: E402
from agentic.store import ContextStore  # noqa: E402
from agentic.strategy import StrategyError  # noqa: E402


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

def _config(tmp_path, **over) -> AgentConfig:
    base = dict(
        symbol="XAUUSDm",
        timeframe="M15",
        bars=50,
        mode="mock",
        model="gpt-4o-mini",
        poll_s=3600.0,  # a huge cadence: a spawned thread never races the test
        state_dir=str(tmp_path / "state"),
        out_dir=str(tmp_path / "renders"),
    )
    base.update(over)
    return AgentConfig(**base)


def _service(tmp_path, clock, *, stub=None, **over) -> AgentService:
    stub = stub if stub is not None else FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    config = _config(tmp_path, **over)
    return AgentService(
        config,
        feed=stub.build(),
        renderer=FakeRenderer(out_dir=config.out_dir, clock=clock),
        clock=clock,
    )


def _due_watch(service: AgentService, clock: FakeClock, *, minute: int = 10):
    """Arm a ``time_reached`` watch that fires once the clock passes ``minute``."""
    service.store.add_subscription(
        "watch",
        "time_reached",
        {"at": at(6, minute).isoformat()},
        ttl_hours=2,
        now=clock(),
    )


def _watchdog_threads(symbol: str):
    """Every live watchdog thread for ``symbol`` (its name is unique per symbol)."""
    name = f"agent-watchdog-{symbol}"
    return [t for t in threading.enumerate() if t.name == name]


# --------------------------------------------------------------------------- #
# The strategy file
# --------------------------------------------------------------------------- #

def test_the_service_loads_the_configured_strategy(tmp_path):
    """AgentConfig(points at an md) -> the service carries its text and name."""
    dir_ = tmp_path / "strategies"
    dir_.mkdir()
    (dir_ / "s1.md").write_text("STRAT-ONE: buy everything.", encoding="utf-8")

    service = AgentService(
        _config(tmp_path, strategy_dir=str(dir_), strategy_name="s1"),
        renderer=FakeRenderer(out_dir=str(tmp_path / "renders"), clock=FakeClock(at(6, 0))),
        clock=FakeClock(at(6, 0)),
    )

    assert service._strategy.text == "STRAT-ONE: buy everything."
    assert service.status()["strategy_name"] == "s1"


def test_a_bad_strategy_refuses_the_service(tmp_path):
    dir_ = tmp_path / "strategies"
    dir_.mkdir()

    with pytest.raises(StrategyError):
        AgentService(
            _config(tmp_path, strategy_dir=str(dir_), strategy_name="missing"),
            renderer=FakeRenderer(out_dir=str(tmp_path / "renders"), clock=FakeClock(at(6, 0))),
            clock=FakeClock(at(6, 0)),
        )


def test_blank_strategy_fields_fall_back_to_settings():
    """Repository defaults: config.settings.STRATEGY_* names the shipped CRT md.

    Resolved lazily inside ``resolve_strategy`` — building a config never has to
    import config.settings.
    """
    directory, name = AgentConfig().resolve_strategy()

    assert name == "default"
    # The directory must actually hold the default file (loaded successfully below).
    from agentic.strategy import load_strategy
    loaded = load_strategy(directory, name)
    assert "CRT" in loaded.text


def test_the_strategy_reaches_the_loop_s_prompt(tmp_path):
    """strategies/*.md -> config -> service -> AgentLoop().run_turn's prompt."""
    dir_ = tmp_path / "strategies"
    dir_.mkdir()
    (dir_ / "mine.md").write_text("STRAT-MINE: scalp the dragon.", encoding="utf-8")

    clock = FakeClock(at(6, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    agent = ScriptedAgent([AgentReply()])
    service = AgentService(
        _config(tmp_path, strategy_dir=str(dir_), strategy_name="mine"),
        feed=stub.build(),
        renderer=FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        client=agent,
        clock=clock,
    )
    service.enable()
    outcome = service.run_now("what is the read")

    assert outcome.ok is True
    assert "STRAT-MINE: scalp the dragon." in agent.requests[0].system_prompt
    assert "PROPOSE-ONLY" in agent.requests[0].system_prompt


# --------------------------------------------------------------------------- #
# The panel reflects the store
# --------------------------------------------------------------------------- #

def test_panel_reflects_the_store(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.enable()
    try:
        outcome = service.run_now("what is the read")
        assert outcome.ok is True

        store = service.store
        key = "fvg:H2:bullish:4152.86:2026-10-16T14:00"
        store.add_subscription("pin", params={"level_key": key}, reason="hold the 2H draw")
        store.set_thesis(
            bias="bullish",
            storyline="range reclaimed, continuation expected",
            invalidation="below 4100",
            confidence=0.4,
        )
        store.add_proposal(bias="bullish", setup="crt continuation", entry=4160.0, confidence=0.4)

        panel = service.panel()

        assert panel["enabled"] is True
        assert panel["mode"] == "mock"
        assert panel["model"] == "gpt-4o-mini"
        assert panel["running"] is True
        assert panel["paused"] is False
        assert panel["view"]["timeframe"] == "M15"
        assert panel["thesis"]["bias"] == "bullish"
        assert panel["thesis"]["invalidation"] == "below 4100"

        subs = panel["subscriptions"]
        assert any(s["kind"] == "pin" for s in subs)
        pin = next(s for s in subs if s["id"] and s["kind"] == "pin")
        assert pin["seconds_remaining"] is not None and pin["seconds_remaining"] > 0
        # the mock turn armed a watch too
        assert any(s["kind"] == "watch" for s in subs)

        assert len(panel["pins"]) == 1
        assert panel["pins"][0]["level_key"] == key

        assert len(panel["proposals"]) == 1
        assert panel["proposals"][0]["bias"] == "bullish"
        assert panel["budget"]["turns_today"] >= 1

        assert len(panel["recent_turns"]) == 1
        assert panel["recent_turns"][0]["trigger"] == "request"
        assert panel["recent_turns"][0]["started_at"]

        assert panel["last_render"]["render_id"]
        assert panel["last_render"]["image_path"]
        assert service.status()["symbol"] == "XAUUSDm"
    finally:
        service.stop()


def test_turns_is_newest_first(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    try:
        assert service.run_now("first").ok
        clock.advance(minutes=5)
        assert service.run_now("second").ok
        rows = service.turns(limit=50)
        assert [r["id"] for r in rows] == list(reversed([t.id for t in service.store.data.turns]))
        assert len(service.turns(limit=1)) == 1
    finally:
        service.stop()


# --------------------------------------------------------------------------- #
# The kill switch: disable stops waking, request is always allowed
# --------------------------------------------------------------------------- #

def test_disable_blocks_scanning_and_enable_wakes(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    _due_watch(service, clock)
    store = service.store

    service.disable()
    assert service.enabled() is False

    # disabled: a scan is a no-op and nothing is logged
    assert service.scan_once() is None
    assert store.data.turns == []

    # enable: the watchdog can wake and a fire turn lands
    service.enable()
    assert service.enabled() is True
    clock.set(at(6, 15))  # past the watch's deadline
    assert service.scan_once() is None  # fire buffered; the coalesce window is open
    clock.set(at(6, 16))  # the 45s coalescing window has elapsed
    outcome = service.scan_once()
    assert outcome is not None and outcome.ok is True
    assert outcome.trigger == Trigger.FIRE.value
    assert len(store.data.turns) == 1
    assert store.data.turns[0].trigger is Trigger.FIRE

    # a request still works while disabled
    service.disable()
    assert service.enabled() is False
    clock.advance(minutes=5)
    allowed = service.run_now("human asks anyway")
    assert allowed.ok is True
    assert allowed.trigger == Trigger.REQUEST.value
    assert len(store.data.turns) == 2
    service.stop()


# --------------------------------------------------------------------------- #
# Pause keeps the state
# --------------------------------------------------------------------------- #

def test_pause_and_resume_keep_the_store(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    _due_watch(service, clock)
    store = service.store
    service.enable()
    clock.set(at(6, 15))

    service.pause()
    assert service.paused() is True
    assert service.scan_once() is None  # paused: no waking
    assert store.data.turns == []
    assert len(store.data.subscriptions) == 1  # state intact
    assert service.store.data.agent.enabled is True

    service.resume()
    assert service.paused() is False
    assert service.scan_once() is None  # detects the fire; the coalesce window opens
    clock.set(at(6, 16))
    outcome = service.scan_once()
    assert outcome is not None and outcome.ok is True
    assert len(store.data.turns) == 1
    service.stop()


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

def test_start_is_idempotent_and_disabled_starts_no_thread(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)

    assert service.enabled() is False  # a fresh store is off
    service.start()  # disabled -> no thread, no boot
    assert service.running() is False
    assert service._thread is None
    service.start()  # idempotent
    assert service.running() is False
    assert service.store.data.turns == []
    service.stop()
    assert service.running() is False


def test_start_when_enabled_boots_once_and_runs_a_thread(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.enable()  # arms the gate and spawns a (sleeping) thread
    service.stop()    # drop it so start() owns the lifecycle

    service.start()
    try:
        assert service.running() is True
        assert len(service.store.data.turns) == 1
        assert service.store.data.turns[0].trigger is Trigger.BOOT

        service.start()  # idempotent: no second boot turn
        assert len(service.store.data.turns) == 1
    finally:
        service.stop()
    assert service.running() is False


# --------------------------------------------------------------------------- #
# Render path safety
# --------------------------------------------------------------------------- #

def test_render_path_refuses_traversal_and_unknown(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    out_dir = service.config.out_dir
    os.makedirs(out_dir, exist_ok=True)
    good = os.path.join(out_dir, "r_deadbeef.png")
    with open(good, "wb") as handle:
        handle.write(b"png")

    assert service.render_path("r_deadbeef") == os.path.realpath(good)
    assert service.render_path("../escape") is None
    assert service.render_path("..\\escape") is None
    assert service.render_path("sub/escape") is None
    assert service.render_path("nope") is None
    assert service.render_path("") is None
    assert service.render_path("C:\\Windows\\system32") is None


def test_render_path_refuses_a_symlink_that_escapes(tmp_path):
    """A symlink planted inside the render dir must not leak a file outside it."""
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    out_dir = service.config.out_dir
    os.makedirs(out_dir, exist_ok=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.png"
    secret.write_bytes(b"png")

    link = os.path.join(out_dir, "r_link.png")
    try:
        os.symlink(str(secret), link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlinks are not available in this environment")

    # realpath resolves the link to the outside file -> containment fails
    assert service.render_path("r_link") is None


# --------------------------------------------------------------------------- #
# Mock client: a full, zero-spend turn
# --------------------------------------------------------------------------- #

def test_build_client_mock_performs_a_full_zero_spend_turn(tmp_path):
    clock = FakeClock(at(6, 0))
    config = _config(tmp_path)
    client = build_client(config)

    store = ContextStore.load_or_new(
        "XAUUSDm", state_dir=str(tmp_path / "state"), clock=clock
    )
    store.set_enabled(True)
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")

    loop = AgentLoop(
        store,
        stub.build(),
        FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        client,
        clock=clock,
    )
    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    assert store.data.thesis.bias == "bullish"
    assert store.data.thesis.invalidation  # an explicit invalidation
    assert store.data.thesis.confidence < 0.5  # low confidence

    watches = store.open_subscriptions(SubscriptionKind.WATCH)
    assert len(watches) >= 1
    assert watches[0].condition == "level_forms"

    assert len(store.data.turns) == 1
    record = store.data.turns[0]
    assert record.trigger is Trigger.REQUEST
    assert record.output["reasoning"]
    # zero spend: the mock bills nothing.
    assert record.cost_usd == 0.0
    assert record.tokens == 0
    assert store.data.budget.spend_usd_today == 0.0


def test_mock_client_is_repeatable_across_turns(tmp_path):
    """The mock script replays on every turn, not just the first (spec review)."""
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.enable()
    try:
        first = service.run_now("first")
        assert first.ok is True
        clock.advance(minutes=2)  # clear MIN_TURN_INTERVAL_S
        second = service.run_now("second")
        assert second.ok is True

        assert first.output.get("reasoning")
        assert second.output.get("reasoning")  # the old list-based mock went silent
        assert second.output.get("thesis", {}).get("bias") == "bullish"
        rows = service.turns()
        assert len(rows) == 2
        assert all(row["summary"] for row in rows)
    finally:
        service.stop()


# --------------------------------------------------------------------------- #
# Coalescing: a burst is one turn, and a refused poll loses nothing
# --------------------------------------------------------------------------- #

def test_two_fires_inside_the_coalesce_window_make_one_turn(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    store = service.store
    service.enable()
    try:
        # two watches that fire 30s apart — inside the 45s coalescing window
        store.add_subscription(
            "watch", "time_reached", {"at": at(6, 5, 0).isoformat()},
            ttl_hours=2, now=clock(),
        )
        store.add_subscription(
            "watch", "time_reached", {"at": at(6, 5, 30).isoformat()},
            ttl_hours=2, now=clock(),
        )
        clock.set(at(6, 5, 0))
        assert service.scan_once() is None  # fire #1 buffered; window opens
        clock.set(at(6, 5, 30))
        assert service.scan_once() is None  # fire #2 buffered; still inside 45s
        clock.set(at(6, 6, 0))              # 60s since the window opened
        outcome = service.scan_once()

        assert outcome is not None and outcome.trigger == Trigger.FIRE.value
        assert len(store.data.turns) == 1  # both fires coalesced into ONE turn
        assert "2 fire" in store.data.turns[0].trigger_detail
    finally:
        service.stop()


def test_leash_refused_poll_keeps_the_fire_for_the_next_poll(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    store = service.store
    service.enable()
    try:
        store.add_subscription(
            "watch", "time_reached", {"at": at(6, 0, 30).isoformat()},
            ttl_hours=2, now=clock(),
        )
        assert service.run_now("kick").ok is True  # last_turn_at = 6:00

        clock.set(at(6, 0, 30))  # within MIN_TURN_INTERVAL_S (60s) of the request
        assert service.scan_once() is None
        sub = store.data.subscriptions[0]
        assert sub.state is SubscriptionState.ARMED  # the fire was NOT consumed
        assert sub.fire_count == 0
        assert len(store.data.turns) == 1  # only the request turn

        # once the interval passes, the same fire is still there to be detected
        clock.set(at(6, 2, 0))
        assert service.scan_once() is None  # detected now; the window opens
        clock.set(at(6, 3, 0))
        outcome = service.scan_once()
        assert outcome is not None and outcome.trigger == Trigger.FIRE.value
        assert len(store.data.turns) == 2
    finally:
        service.stop()


# --------------------------------------------------------------------------- #
# The daemon thread: it wakes on its own, and really stops
# --------------------------------------------------------------------------- #

def test_daemon_thread_wakes_and_logs_a_turn(tmp_path):
    symbol = "AGENTTHREADT"
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock, symbol=symbol, poll_s=0.02)
    store = service.store
    store.add_subscription(
        "watch", "time_reached", {"at": at(6, 5).isoformat()}, ttl_hours=2, now=clock()
    )
    service.enable()
    try:
        assert service.running() is True
        assert len(_watchdog_threads(symbol)) == 1
        clock.advance(minutes=10)
        # Nudge the clock past the coalescing window while the thread polls.
        for _ in range(300):
            if store.data.turns:
                break
            clock.advance(seconds=30)
            time.sleep(0.02)
        assert store.data.turns, "the watchdog thread never woke"
        assert store.data.turns[0].trigger is Trigger.FIRE
    finally:
        service.disable()
    assert service.enabled() is False
    assert service.running() is False
    assert _watchdog_threads(symbol) == []


def test_disable_stops_thread_driven_waking(tmp_path):
    symbol = "AGENTTHREADD"
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock, symbol=symbol, poll_s=0.02)
    store = service.store
    # a repeating watch: a live thread would keep firing it
    store.add_subscription(
        "watch", "time_reached", {"at": at(6, 5).isoformat()},
        ttl_hours=2, one_shot=False, now=clock(),
    )
    service.enable()
    try:
        clock.advance(minutes=10)
        for _ in range(300):
            if store.data.turns:
                break
            clock.advance(seconds=30)
            time.sleep(0.02)
        assert store.data.turns

        service.disable()
        assert service.enabled() is False
        assert service.running() is False
        assert _watchdog_threads(symbol) == []
        logged = len(store.data.turns)

        clock.advance(hours=2)
        time.sleep(0.2)
        assert len(store.data.turns) == logged  # the killed thread woke nothing
    finally:
        service.stop()


def test_stop_joins_and_leaves_no_extra_threads(tmp_path):
    symbol = "AGENTTHREADS"
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock, symbol=symbol, poll_s=0.02)
    service.enable()
    assert service.running() is True
    assert len(_watchdog_threads(symbol)) == 1

    service.stop()
    assert service.running() is False
    assert _watchdog_threads(symbol) == []
    service.stop()  # idempotent
    assert service.running() is False


def test_no_duplicate_thread_after_stop_then_start(tmp_path):
    symbol = "AGENTTHREADR"
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock, symbol=symbol, poll_s=0.02)
    service.enable()
    service.stop()
    assert service.running() is False

    service.start()  # the gate is still armed: boots and re-spawns exactly one
    try:
        assert service.running() is True
        assert len(_watchdog_threads(symbol)) == 1
    finally:
        service.stop()
    assert _watchdog_threads(symbol) == []


def test_start_disabled_does_not_report_autostarted(tmp_path):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.start()  # a fresh store is off: nothing starts
    assert service.status()["autostarted"] is False
    assert service.panel()["autostarted"] is False
    assert service.running() is False
    service.stop()


# --------------------------------------------------------------------------- #
# Live transport: a missing key is a clear error, not a network call
# --------------------------------------------------------------------------- #

def test_make_transport_requires_the_key(monkeypatch):
    monkeypatch.delenv("AGENT_TEST_KEY", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        make_transport(AgentConfig(api_key_env="AGENT_TEST_KEY"))
    assert "AGENT_TEST_KEY" in str(excinfo.value)
    assert "key" in str(excinfo.value).lower()


# --------------------------------------------------------------------------- #
# Live transport: a keyless endpoint (LLM_PROVIDER=local) sends no auth header
# --------------------------------------------------------------------------- #

def test_request_headers_omit_authorization_when_keyless():
    """A blank key means keyless: no Authorization header at all (not "Bearer ")."""
    headers = _request_headers("", "ua/1.0")
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == "ua/1.0"


def test_chat_completions_url_does_not_double_a_full_endpoint():
    assert _chat_completions_url("http://localhost:8080/v1") == (
        "http://localhost:8080/v1/chat/completions"
    )
    # A pasted full endpoint is tolerated, not appended to.
    assert _chat_completions_url("http://localhost:8080/v1/chat/completions") == (
        "http://localhost:8080/v1/chat/completions"
    )
    assert _chat_completions_url("http://localhost:8080/v1/") == (
        "http://localhost:8080/v1/chat/completions"
    )


def test_make_transport_is_keyless_without_a_key(monkeypatch):
    """``api_key_env=""`` needs no key and POSTs to the local base with no auth."""
    captured = {}
    _install_urlopen(monkeypatch, captured)
    transport = make_transport(
        AgentConfig(api_key_env="", api_base="http://localhost:8080/v1")
    )

    assert transport({"model": "m", "messages": []}) == {"ok": True}

    headers = _headers_of(captured)
    assert "authorization" not in headers
    assert headers.get("user-agent") == "trading-bot-agent/1.0"
    assert captured["request"].full_url == "http://localhost:8080/v1/chat/completions"


# --------------------------------------------------------------------------- #
# Live transport: an explicit User-Agent, or Cloudflare blocks the request
# --------------------------------------------------------------------------- #

class _FakeResponse:
    """A minimal ``urlopen`` context manager returning a canned JSON body."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):  # pragma: no cover — trivial
        return False

    def read(self):
        return b'{"ok": true}'


def _install_urlopen(monkeypatch, captured):
    """Replace ``urllib.request.urlopen`` with a request recorder (no network)."""
    import urllib.request

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _headers_of(captured):
    return {key.lower(): value for key, value in captured["request"].headers.items()}


def test_make_transport_sends_an_explicit_user_agent(monkeypatch):
    """The request must carry a real UA — urllib's default is Cloudflare-1010 blocked."""
    captured = {}
    _install_urlopen(monkeypatch, captured)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}

    headers = _headers_of(captured)
    user_agent = headers.get("user-agent", "")
    assert user_agent, "the live request carried no User-Agent at all"
    assert "urllib" not in user_agent.lower(), f"urllib's default UA leaked: {user_agent!r}"
    assert user_agent == "trading-bot-agent/1.0"
    # Auth and content type are unchanged.
    assert headers.get("authorization") == "Bearer test-key"
    assert headers.get("content-type") == "application/json"


def test_make_transport_honours_a_custom_user_agent(monkeypatch):
    captured = {}
    _install_urlopen(monkeypatch, captured)
    transport = make_transport(
        AgentConfig(api_key_env="AGENT_UA_KEY", http_user_agent="my-agent/2.0")
    )
    transport({"model": "m", "messages": []})
    assert _headers_of(captured).get("user-agent") == "my-agent/2.0"


def test_make_transport_blank_user_agent_falls_back_to_the_default(monkeypatch):
    """A blank setting must fall back to the explicit default, not to urllib's."""
    captured = {}
    _install_urlopen(monkeypatch, captured)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY", http_user_agent="   "))
    transport({"model": "m", "messages": []})
    assert _headers_of(captured).get("user-agent") == "trading-bot-agent/1.0"


def _http_error(code, *, retry_after=None, headers=None, body=b'{"error": {"message": "slow down"}}'):
    import urllib.error

    merged = dict(headers or {})
    if retry_after is not None:
        merged["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://example.test/chat/completions", code, "err", merged, io.BytesIO(body)
    )


def test_make_transport_retries_a_rate_limit_then_succeeds(monkeypatch):
    """A 429 is retried after ``Retry-After``; a multi-round turn needs this."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, retry_after="3")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert calls["n"] == 2
    assert slept == [3.0]


def test_make_transport_gives_up_after_the_retry_budget(monkeypatch):
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    calls = {"n": 0}

    def always_429(request, timeout=None):
        calls["n"] += 1
        raise _http_error(429, retry_after="1")

    monkeypatch.setattr(urllib.request, "urlopen", always_429)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    with pytest.raises(RuntimeError) as excinfo:
        transport({"model": "m", "messages": []})
    assert "HTTP 429" in str(excinfo.value)
    assert calls["n"] == TRANSPORT_MAX_RETRIES + 1


def test_make_transport_does_not_retry_a_daily_quota(monkeypatch):
    """A 429 naming a *daily* quota is surfaced at once: no short wait clears it."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def daily_quota(request, timeout=None):
        calls["n"] += 1
        raise _http_error(
            429,
            retry_after="1",
            body=(
                b'{"error": {"message": "Rate limit reached for model on tokens '
                b'per day (TPD): Limit 200000, Used 200000, Requested 9000."}}'
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", daily_quota)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    with pytest.raises(RuntimeError) as excinfo:
        transport({"model": "m", "messages": []})
    assert "HTTP 429" in str(excinfo.value)
    assert calls["n"] == 1, "a daily quota must not be retried"
    assert slept == []


def test_make_transport_does_not_retry_a_client_error(monkeypatch):
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def bad_request(request, timeout=None):
        calls["n"] += 1
        raise _http_error(400, retry_after="30")

    monkeypatch.setattr(urllib.request, "urlopen", bad_request)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    with pytest.raises(RuntimeError) as excinfo:
        transport({"model": "m", "messages": []})
    assert "HTTP 400" in str(excinfo.value)
    assert calls["n"] == 1
    assert slept == []


def test_make_transport_retries_a_503(monkeypatch):
    """503 (Cloudflare not-ready) is retryable exactly like 429."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, retry_after="2")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert calls["n"] == 2
    assert slept == [2.0]


def test_make_transport_honours_x_ratelimit_reset_tokens(monkeypatch):
    """Groq's ``x-ratelimit-reset-tokens: "6.3s"`` is used when Retry-After is absent."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, headers={"x-ratelimit-reset-tokens": "6.3s"})
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert calls["n"] == 2
    assert slept == [6.3]


def test_make_transport_parses_an_http_date_retry_after(monkeypatch):
    """An RFC-7231 date ``Retry-After`` (Cloudflare 503) becomes seconds until it."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    when = datetime.now(timezone.utc) + timedelta(seconds=10)
    http_date = email.utils.format_datetime(when, usegmt=True)
    assert http_date.endswith("GMT")  # the RFC-7231 form Cloudflare sends

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503, retry_after=http_date)
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert calls["n"] == 2
    # ~10s out; allow scheduling slop but prove it did not fall back to the 5s default.
    assert len(slept) == 1
    assert 8.0 <= slept[0] <= 11.0


def test_make_transport_retries_a_per_minute_429_that_mentions_a_daily_prose(monkeypatch):
    """A per-minute 429 that merely *mentions* the daily category is still retried.

    Regression for C1: the bare phrases "tokens per day" / "requests per day" (and a
    prose ``(TPD)`` in an upsell) must not be read as a daily quota — that turned a
    retryable per-minute 429 into a terminal failure, the dangerous direction.
    """
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def tpm_body(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(
                429,
                retry_after="3",
                body=(
                    b'{"error": {"message": "Rate limit reached for model on tokens per '
                    b'minute (TPM): Limit 7000, Used 7050, Requested 9000. Please try '
                    b'again in 28.1s. Need a higher tokens per day (TPD) allowance? '
                    b'Upgrade your plan at https://example.test/billing."}}'
                ),
            )
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", tpm_body)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert calls["n"] == 2, "a per-minute 429 must be retried, not treated as terminal"
    assert slept == [3.0]


def test_make_transport_floors_a_zero_retry_after(monkeypatch):
    """``Retry-After: 0`` must not tight-loop: the wait is floored at a small positive."""
    import urllib.request

    monkeypatch.setenv("AGENT_UA_KEY", "test-key")
    slept = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, retry_after="0")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = make_transport(AgentConfig(api_key_env="AGENT_UA_KEY"))

    assert transport({"model": "m", "messages": []}) == {"ok": True}
    assert slept and slept[0] > 0


def test_join_budget_covers_a_worst_case_retried_turn(tmp_path):
    """C4: ``stop``'s join budget must include the transport's retry sleeps.

    One call can block for ``http_timeout_s`` *and* sleep up to
    ``TRANSPORT_MAX_RETRIES * TRANSPORT_RETRY_CAP_S`` between retries, so the old
    timeout-only budget could expire mid-turn and leave the service draining.
    """
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock, http_timeout_s=120.0, poll_s=15.0)

    worst_case_call = 120.0 + TRANSPORT_MAX_RETRIES * TRANSPORT_RETRY_CAP_S
    worst_case_turn = worst_case_call * (MAX_TOOL_ROUNDS + 1) + 15.0
    assert service._join_budget() >= worst_case_turn


def test_the_shipped_output_cap_leaves_room_for_a_reasoning_runaway():
    """A config floor, not a style choice — recorded replay evidence behind it.

    ``AGENT_MAX_TOKENS = 1500`` truncated the closing call mid-reasoning: the
    recovery call died at the cap on the very turns it exists to rescue, and the
    turn yielded nothing. The closing calls that did finish measured 2354 and
    8725 completion tokens, so the shipped default must clear both by a margin.
    """
    from config.settings import AGENT_MAX_TOKENS

    assert AGENT_MAX_TOKENS >= 8000


def test_the_shipped_view_default_is_a_screenshot_within_the_store_cap():
    """The boot view's bar count must fit inside the store's view bounds.

    The operator's spec: the default screenshot is 180 candles, 180 is the hard
    ceiling, and history is reached with ``offset`` — never a wider window. If
    the config and the store drift apart (config wider than the cap) the boot
    turn dies on its first ``set_view`` before any render happens.
    """
    from agentic.store import MAX_BARS, MIN_BARS
    from config.settings import AGENT_BARS

    assert MIN_BARS <= AGENT_BARS <= MAX_BARS

