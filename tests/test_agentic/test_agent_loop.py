"""Tests for the agent loop (spec phase 4 acceptance criteria).

Every turn runs on a :class:`ScriptedAgent`, an injected :class:`FakeClock` and a
:class:`Feed` built from in-memory payloads, writing into ``tmp_path`` — zero API
spend, no MT5, no network. The renderer is real only in the tests that assert a
*manifest* (they prove the loop draws a PNG and threads the real tags); the loop's
mechanics run on a call-recording stub, because a real PNG costs seconds on CI.
The scenarios mirror the spec's turn algorithm: a full turn end-to-end, a resumed
boot turn with backfill, the leash, the caps, the kill switch, the note memory,
and the prompt / briefing contracts.
"""
from datetime import timedelta

import pytest
from pytest import approx

from _fixtures import (
    FakeClock,
    FakeRenderer,
    FeedStub,
    at,
    bars_rows,
    candles_payload,
    level as _level,
    snapshot as _snapshot,
    snapshot_payload,
    ts,
)
from agentic import prompts
from agentic.agent_loop import (
    MAX_TOOL_ROUNDS,
    AgentLoop,
    AgentReply,
    AgentRequest,
    ScriptedAgent,
)
from agentic.feed import Feed, InsufficientHistory
from agentic.models import SubscriptionKind, Trigger
from agentic.renderer import Renderer
from agentic.store import (
    MAX_PINS,
    MAX_RENDERS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    ContextStore,
)
from agentic.tools import ToolCall, ToolRegistry, render_current
from agentic.watchdog import Watchdog


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

class _AdvancingClock:
    """A clock that reads once and steps forward: proves a turn stamps one time."""

    def __init__(self, start, *, step_s=1):
        self.now = start
        self.step = timedelta(seconds=step_s)
        self.calls = 0

    def __call__(self):
        value = self.now
        self.calls += 1
        self.now = self.now + self.step
        return value


def _png_renderer(tmp_path, clock, name="renders"):
    # The real thing, used where the pixels and the manifest matter. A PNG costs
    # seconds on CI, so the rest of the loop's tests use the stub below.
    return Renderer(
        width=256, height=144, dpi=100, clock=clock, out_dir=str(tmp_path / name)
    )


def _renderer(tmp_path, clock, name="fake-renders"):
    # Renderer-shaped stub: same contract, no rasterisation, no manifest.
    return FakeRenderer(out_dir=str(tmp_path / name), clock=clock)


def _store(tmp_path, clock, *, enabled=True, timeframe="M15", bars=300):
    store = ContextStore("XAUUSDm", state_dir=str(tmp_path / "state"), clock=clock)
    store.set_view(timeframe=timeframe, bars=bars)
    store.set_enabled(enabled)
    return store


def _fvg_level(when=None, price=4160.0, timeframe="M15"):
    when = at(6, 30) if when is None else when
    return _level(
        "fvg",
        type="FVG (BULLISH)",
        price=price,
        time=ts(when),
        end_kind="active",
        box_top=price + 2.0,
        box_bottom=price - 2.0,
        desc="FVG bullish",
    )


def _stub_with_fvg(*, at_time=None):
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_levels([_fvg_level(at_time)], timeframe="M15")
    stub.set_candles(bars_rows(), timeframe="M15")
    return stub


def _m15_key(at_time=None):
    return _snapshot([_fvg_level(at_time)], timeframe="M15").levels[0].level_key


def _log_entry(record, name):
    return next(e for e in record.tool_calls if e["call"]["name"] == name)


# --------------------------------------------------------------------------- #
# Full turn end-to-end
# --------------------------------------------------------------------------- #

def test_full_turn_end_to_end(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    stub = _stub_with_fvg()
    feed = stub.build()
    key = _m15_key()

    reply1 = AgentReply(
        tool_calls=[
            ToolCall(call_id="c1", name="set_view", arguments={"bars": 120, "show_tags": False}),
            ToolCall(call_id="c2", name="render"),
            ToolCall(call_id="c3", name="level_lookup", arguments={"family": "fvg"}),
            ToolCall(call_id="c4", name="add_pin", arguments={"level_key": key, "reason": "HTF draw"}),
            ToolCall(
                call_id="c5",
                name="add_watch",
                arguments={
                    "condition": "level_forms",
                    "params": {"family": "fvg"},
                    "ttl_hours": 4.0,
                    "reason": "wait for the LTF fvg",
                },
            ),
        ],
        tokens={"prompt": 100, "completion": 20},
        cost_usd=0.01,
    )
    reply2 = AgentReply(
        output={
            "thesis": {
                "bias": "bullish",
                "storyline": "sweep then continuation",
                "invalidation": "below 4100",
                "confidence": 0.6,
            },
            "proposals": [
                {
                    "bias": "bullish",
                    "setup": "crt continuation",
                    "entry": 4160.0,
                    "sl": 4140.0,
                    "tp": 4180.0,
                    "confidence": 0.5,
                    "reason": "draw on liquidity",
                }
            ],
            "notes": [{"text": "watching the M15 fvg"}],
            "reasoning": "bullish continuation to the fvg",
        },
        tokens={"prompt": 80, "completion": 30},
        cost_usd=0.02,
    )

    agent = ScriptedAgent([reply1, reply2])
    loop = AgentLoop(store, feed, _png_renderer(tmp_path, clock), agent, clock=clock)
    outcome = loop.run_turn(trigger="request", detail="human asked")

    assert outcome.ok is True
    assert outcome.reason == ""
    assert outcome.trigger == "request"
    assert outcome.tool_calls == 5
    # initial render (#1) + the explicit render tool call (#2)
    assert outcome.renders == 2

    # the store reflects every mutation
    assert store.data.view.bars == 120
    assert store.data.view.show_tags is False
    assert len(store.open_subscriptions(SubscriptionKind.PIN)) == 1
    assert len(store.open_subscriptions(SubscriptionKind.WATCH)) == 1
    assert store.data.thesis.bias == "bullish"
    assert store.data.thesis.invalidation == "below 4100"
    assert len(store.data.proposals) == 1
    assert store.data.proposals[0].entry == approx(4160.0)

    # the turn log is complete
    assert len(store.data.turns) == 1
    record = store.data.turns[0]
    assert record.trigger is Trigger.REQUEST
    assert record.trigger_detail == "human asked"
    assert len(record.tool_calls) == 5
    assert [e["call"]["name"] for e in record.tool_calls] == [
        "set_view", "render", "level_lookup", "add_pin", "add_watch",
    ]
    assert record.renders == 2
    assert record.tokens == 230
    assert record.cost_usd == approx(0.03)
    assert record.output["notes"][0]["text"] == "watching the M15 fvg"
    assert record.output["notes"][0]["at"]

    # the lookup answered from the feed, not the image
    lookup = _log_entry(record, "level_lookup")["result"]
    assert lookup["ok"] is True
    assert lookup["result"]["matches"][0]["family"] == "fvg"

    # the outcome's image/manifest are the *final* render (the render tool call),
    # not the turn's initial perception render.
    final_render = _log_entry(record, "render")["result"]["result"]
    assert outcome.image_path == final_render["image_path"]
    assert outcome.manifest == final_render["manifest"]
    assert outcome.manifest["tags"], "the real renderer drew tags"


# --------------------------------------------------------------------------- #
# Boot on a resumed store
# --------------------------------------------------------------------------- #

def test_boot_turn_on_a_resumed_store(tmp_path):
    clock = FakeClock(at(6, 0))
    state_dir = str(tmp_path / "state")
    store = ContextStore("XAUUSDm", state_dir=state_dir, clock=clock)
    store.set_view(timeframe="M15")
    store.set_enabled(True)
    store.set_thesis(
        bias="bullish", storyline="resumed read", invalidation="below 4100", confidence=0.6
    )
    store.add_subscription("watch", "level_forms", {"family": "fvg"}, one_shot=False, now=clock())
    store.add_subscription("watch", "price_crosses", {"price": 9000.0}, now=clock())
    store.save()

    # downtime: a level forms while the process is down.
    stub = _stub_with_fvg(at_time=at(6, 30))
    feed = stub.build()
    clock.set(at(7, 0))
    resumed = ContextStore.load("XAUUSDm", state_dir=state_dir, clock=clock)
    assert len(resumed.data.subscriptions) == 2  # resumed, not reset

    agent = ScriptedAgent([AgentReply()])
    loop = AgentLoop(
        resumed,
        feed,
        _renderer(tmp_path, clock),
        agent,
        clock=clock,
        watchdog=Watchdog(feed, clock=clock),
    )
    outcome = loop.boot()

    assert outcome.ok is True
    assert outcome.trigger == Trigger.BOOT.value
    # the thesis survived the restart
    assert resumed.data.thesis.bias == "bullish"
    assert len(resumed.data.turns) == 1
    assert resumed.data.turns[0].trigger is Trigger.BOOT

    briefing = agent.requests[0].briefing
    assert briefing["thesis"]["bias"] == "bullish"
    assert len(briefing["subscriptions"]) == 2
    # the missed fire is reported, clearly marked not live
    assert len(briefing["retroactive"]) == 1
    retro = briefing["retroactive"][0]
    assert retro["live"] is False
    assert "not live" in retro["note"]


def test_boot_without_a_watchdog_still_runs(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    loop = AgentLoop(
        store, _stub_with_fvg().build(), _renderer(tmp_path, clock),
        ScriptedAgent([AgentReply()]), clock=clock,
    )
    outcome = loop.boot()
    assert outcome.ok is True and outcome.trigger == Trigger.BOOT.value
    assert loop.wake() is None  # no watchdog: nothing to wake


def test_wake_with_nothing_pending_is_a_noop(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    loop = AgentLoop(
        store, feed, _renderer(tmp_path, clock), ScriptedAgent([AgentReply()]),
        clock=clock, watchdog=Watchdog(feed, clock=clock),
    )
    assert loop.wake() is None
    assert store.data.turns == []


# --------------------------------------------------------------------------- #
# The leash and the gate
# --------------------------------------------------------------------------- #

def test_leash_refuses_a_second_turn_in_the_same_instant(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    agent = ScriptedAgent([AgentReply(), AgentReply()])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    first = loop.run_turn(trigger="request")
    assert first.ok is True

    second = loop.run_turn(trigger="request")
    assert second.ok is False
    assert second.reason.startswith("leash:")
    # a refused turn is never logged
    assert len(store.data.turns) == 1


def test_an_unknown_trigger_is_refused(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    loop = AgentLoop(
        store, _stub_with_fvg().build(), _renderer(tmp_path, clock),
        ScriptedAgent([AgentReply()]), clock=clock,
    )
    outcome = loop.run_turn(trigger="nonsense")
    assert outcome.ok is False and outcome.reason == "bad_trigger"
    assert store.data.turns == []


# --------------------------------------------------------------------------- #
# Caps
# --------------------------------------------------------------------------- #

def test_more_tool_calls_than_the_cap_are_truncated(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    calls = [
        ToolCall(call_id=f"c{i}", name="add_note", arguments={"text": f"note {i}"})
        for i in range(MAX_TOOL_CALLS_PER_TURN + 3)
    ]
    agent = ScriptedAgent([AgentReply(tool_calls=calls)])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    # every emitted call is logged; only the cap's worth ran
    assert outcome.tool_calls == MAX_TOOL_CALLS_PER_TURN + 3
    assert "tool_calls" in outcome.output["truncated"]
    assert "truncated" in outcome.reason
    assert len(store.data.turns[0].tool_calls) == MAX_TOOL_CALLS_PER_TURN + 3
    assert len(outcome.output["notes"]) == MAX_TOOL_CALLS_PER_TURN

    # the dropped calls are surfaced to the model, not silently discarded
    dropped = [
        entry for entry in store.data.turns[0].tool_calls
        if entry["result"]["ok"] is False
    ]
    assert len(dropped) == 3
    assert all("tool_cap" in entry["result"]["error"] for entry in dropped)


def test_more_renders_than_the_cap_are_truncated(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    calls = [ToolCall(call_id=f"c{i}", name="render") for i in range(MAX_RENDERS_PER_TURN + 2)]
    agent = ScriptedAgent([AgentReply(tool_calls=calls)])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    assert outcome.renders == MAX_RENDERS_PER_TURN
    assert "renders" in outcome.output["truncated"]
    refused = [
        entry["result"]
        for entry in store.data.turns[0].tool_calls
        if entry["result"]["ok"] is False
    ]
    assert refused and "render_cap" in refused[0]["error"]


def test_calling_exactly_the_tool_cap_is_not_truncated(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    calls = [
        ToolCall(call_id=f"c{i}", name="add_note", arguments={"text": f"note {i}"})
        for i in range(MAX_TOOL_CALLS_PER_TURN)
    ]
    loop = AgentLoop(
        store, feed, _renderer(tmp_path, clock),
        ScriptedAgent([AgentReply(tool_calls=calls)]), clock=clock,
    )
    outcome = loop.run_turn(trigger="request")
    assert outcome.tool_calls == MAX_TOOL_CALLS_PER_TURN
    assert "truncated" not in outcome.output
    assert outcome.reason == ""


def test_using_exactly_the_render_cap_is_not_truncated(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    # the initial render is #1, so the cap allows MAX_RENDERS_PER_TURN - 1 more.
    calls = [ToolCall(call_id=f"c{i}", name="render") for i in range(MAX_RENDERS_PER_TURN - 1)]
    loop = AgentLoop(
        store, feed, _renderer(tmp_path, clock),
        ScriptedAgent([AgentReply(tool_calls=calls)]), clock=clock,
    )
    outcome = loop.run_turn(trigger="request")
    assert outcome.renders == MAX_RENDERS_PER_TURN
    assert "truncated" not in outcome.output


def test_max_tool_rounds_is_enforced(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    # a model that never stops asking for tools runs out of *rounds*.
    script = [
        AgentReply(tool_calls=[ToolCall(call_id=f"c{i}", name="add_note", arguments={"text": "x"})])
        for i in range(MAX_TOOL_ROUNDS + 2)
    ]
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), ScriptedAgent(script), clock=clock)
    outcome = loop.run_turn(trigger="request")
    assert outcome.tool_calls == MAX_TOOL_ROUNDS  # one per round, then stopped
    assert outcome.output["truncated"] == ["rounds"]
    assert outcome.reason == "truncated: rounds"


def test_a_toolless_closing_call_recovers_the_structured_output(tmp_path):
    """A loop that never emits the object gets one last, tool-less ask.

    The local-provider failure mode: a vision model burns its rounds on tool calls
    (or its whole output budget on reasoning) and reaches the end with no
    structured object. Rather than bill the turn and record nothing, the loop makes
    exactly one more call — *without* tools and *without* the chart image, the
    shape these models reliably answer — carrying the tool evidence back as text.
    """
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()

    endless = AgentReply(
        tool_calls=[ToolCall(call_id="c1", name="add_note", arguments={"text": "saw an fvg"})],
        tokens={"prompt": 10, "completion": 5},
        cost_usd=0.01,
    )
    closing = AgentReply(
        output={"thesis": {"bias": "bullish", "storyline": "swept the low, fvg above",
                           "invalidation": "below 4100", "confidence": 0.6}},
        tokens={"prompt": 20, "completion": 10},
        cost_usd=0.02,
    )

    def client(request):
        return closing if not request.tools else endless  # no tools == the closing call

    agent = ScriptedAgent(client)
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)
    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    # The object the model never produced during the tool rounds was recovered.
    assert store.data.thesis.bias == "bullish"
    assert store.data.thesis.invalidation == "below 4100"
    # The cap still stands: one closing call, not a second tool phase.
    assert outcome.tool_calls == MAX_TOOL_ROUNDS

    closing_request = agent.requests[-1]
    assert closing_request.tools == []          # no tools: the model must answer now
    assert closing_request.image_path == ""     # the chart image is what provokes the runaway
    assert closing_request.briefing["closing"]  # the instruction to end the turn
    assert "add_note" in closing_request.briefing["evidence"]  # evidence survives as text

    # The closing call is billed like any other round (all MAX_TOOL_ROUNDS + 1 calls).
    record = store.data.turns[0]
    assert record.tokens == (10 + 5) * MAX_TOOL_ROUNDS + (20 + 10)
    assert record.cost_usd == approx(0.01 * MAX_TOOL_ROUNDS + 0.02)


# --------------------------------------------------------------------------- #
# Kill switch
# --------------------------------------------------------------------------- #

def test_disabled_refuses_fire_and_boot_but_allows_a_request(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock, enabled=False)
    feed = _stub_with_fvg().build()
    # make one fire pending so wake() has something to flush.
    store.add_subscription(
        "watch", "time_reached", {"at": at(6, 10).isoformat()}, ttl_hours=2, now=clock()
    )
    watchdog = Watchdog(feed, clock=clock)
    watchdog.scan(store, now=at(6, 10))

    agent = ScriptedAgent([AgentReply(), AgentReply(), AgentReply()])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock, watchdog=watchdog)

    assert loop.wake().reason == "disabled"
    assert loop.boot().reason == "disabled"
    assert store.data.turns == []

    # a human request is always allowed, even with the agent disabled.
    allowed = loop.run_turn(trigger="request", detail="human asks anyway")
    assert allowed.ok is True
    assert len(store.data.turns) == 1


def test_a_refused_wake_keeps_the_fire_buffered(tmp_path):
    """The gate runs before the flush, so a disabled wake never loses the event."""
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock, enabled=False)
    feed = _stub_with_fvg().build()
    store.add_subscription(
        "watch", "time_reached", {"at": at(6, 10).isoformat()}, ttl_hours=2, now=clock()
    )
    watchdog = Watchdog(feed, clock=clock)
    watchdog.scan(store, now=at(6, 10))
    assert watchdog.pending()  # the fire is buffered and waiting for a turn

    agent = ScriptedAgent([AgentReply(), AgentReply()])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock, watchdog=watchdog)

    refused = loop.wake()
    assert refused is not None and refused.reason == "disabled"
    assert watchdog.pending()  # still buffered — the flush never ran
    assert store.data.turns == []

    # re-enable: the event is still there, and now it wakes the agent.
    store.set_enabled(True)
    clock.set(at(6, 20))
    fired = loop.wake()
    assert fired is not None and fired.ok is True
    assert fired.trigger == Trigger.FIRE.value
    assert watchdog.pending() == []
    assert len(store.data.turns) == 1


# --------------------------------------------------------------------------- #
# Tool registry: never raises, and the render budget
# --------------------------------------------------------------------------- #

def test_execute_never_raises_and_reports_the_store_reason(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _renderer(tmp_path, clock), clock=clock)

    missing = registry.execute(ToolCall(name="add_pin", arguments={}))
    assert missing.ok is False and "missing_params" in missing.error

    unknown = registry.execute(ToolCall(name="place_order", arguments={}))
    assert unknown.ok is False and "unknown_tool" in unknown.error

    bad_view = registry.execute(ToolCall(name="set_view", arguments={"colour": "red"}))
    assert bad_view.ok is False and "unknown_view_field" in bad_view.error

    bad_watch = registry.execute(ToolCall(name="add_watch", arguments={"condition": "moon_phase"}))
    assert bad_watch.ok is False and "unknown_condition" in bad_watch.error


def test_a_store_cap_surfaces_through_execute(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _renderer(tmp_path, clock), clock=clock)

    for i in range(MAX_PINS):
        assert registry.execute(ToolCall(name="add_pin", arguments={"level_key": f"k{i}"})).ok

    overflow = registry.execute(ToolCall(name="add_pin", arguments={"level_key": "one-too-many"}))
    assert overflow.ok is False and "max_pins" in overflow.error


def test_an_internal_bug_is_labelled_distinctly(tmp_path, monkeypatch):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _renderer(tmp_path, clock), clock=clock)

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(store, "set_view", boom)
    result = registry.execute(ToolCall(name="set_view", arguments={"bars": 120}))
    assert result.ok is False
    assert result.error.startswith("internal_error: RuntimeError: kaboom")


def test_the_initial_render_counts_as_render_one(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _renderer(tmp_path, clock), clock=clock)

    assert registry.renders_used() == 0
    first = registry.initial_render()
    assert registry.renders_used() == 1  # the initial render is render #1
    assert first.image_path

    assert registry.execute(ToolCall(name="render")).ok
    assert registry.execute(ToolCall(name="render")).ok
    assert registry.renders_used() == MAX_RENDERS_PER_TURN

    refused = registry.execute(ToolCall(name="render"))
    assert refused.ok is False and "render_cap" in refused.error
    assert registry.render_refusals() == 1


def test_the_initial_render_fetches_the_view_snapshot_once(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    stub = _stub_with_fvg()
    registry = ToolRegistry(store, stub.build(), _renderer(tmp_path, clock), clock=clock)

    registry.initial_render()
    assert stub.snapshot_calls.count(("XAUUSDm", "M15")) == 1

    # a lookup right after the render re-uses the snapshot it seeded, not a re-fetch.
    registry.execute(ToolCall(name="level_lookup", arguments={"family": "fvg"}))
    assert stub.snapshot_calls.count(("XAUUSDm", "M15")) == 1


# --------------------------------------------------------------------------- #
# render_current: pin resolution (stub) and the real manifest
# --------------------------------------------------------------------------- #

def test_render_current_resolves_pins_and_thesis_levels(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    stub = _stub_with_fvg()
    feed = stub.build()
    key = _m15_key()
    store.add_subscription("pin", params={"level_key": key}, reason="hold it")
    store.set_thesis(levels_of_interest=[key])

    renderer = _renderer(tmp_path, clock)
    result = render_current(store, feed, renderer)

    assert result.image_path
    assert len(renderer.calls) == 1
    call = renderer.calls[0]
    # the open pin is resolved to a LevelRecord and passed as a pin...
    assert [p.level_key for p in call["pins"]] == [key]
    # ...and the thesis's levels_of_interest are passed for flagging.
    assert call["thesis_level_keys"] == [key]


def test_the_real_renderer_marks_the_pin_and_the_thesis_level(tmp_path):
    # The manifest fields are the *real* renderer's business, so this test uses it
    # (the stub above records the call but synthesises no manifest).
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    key = _m15_key()
    store.add_subscription("pin", params={"level_key": key}, reason="hold it")
    store.set_thesis(levels_of_interest=[key])

    result = render_current(store, feed, _png_renderer(tmp_path, clock))

    tags = result.manifest["tags"]
    assert list(tags) == ["F1*"]  # one fvg level, pinned -> the '*' suffix
    entry = tags["F1*"]
    assert entry["origin"] == "pinned"
    assert entry["is_thesis_level"] is True
    assert entry["level_key"] == key


# --------------------------------------------------------------------------- #
# Phase 6d: offset and split through the whole tool surface
# --------------------------------------------------------------------------- #

def test_set_view_offset_flows_into_the_rendered_manifest(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _png_renderer(tmp_path, clock), clock=clock)

    assert registry.execute(ToolCall(name="set_view", arguments={"offset": 17})).ok
    result = registry.execute(ToolCall(name="render"))
    assert result.ok
    manifest = result.result["manifest"]
    assert manifest["window"]["offset"] == 17
    assert manifest["window"]["from"] and manifest["window"]["to"]


def test_split_view_renders_two_panes_through_the_registry(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    registry = ToolRegistry(store, _stub_with_fvg().build(), _png_renderer(tmp_path, clock), clock=clock)

    ok = registry.execute(
        ToolCall(name="set_view", arguments={"layout": "split", "panes": ["H2", "M15"]})
    )
    assert ok.ok
    # the primary pane drives the timeframe everything else keys off
    assert store.data.view.timeframe == "H2"

    result = registry.execute(ToolCall(name="render"))
    assert result.ok
    manifest = result.result["manifest"]
    assert [pane["timeframe"] for pane in manifest["panes"]] == ["H2", "M15"]
    # the M15 pane's fvg is drawn on pane 2 with a pane-prefixed, globally-unique tag
    assert any(tag.startswith("P2:") for tag in manifest["tags"])


def _split_feed():
    """A feed whose two panes carry *different* price bases (H2 4150, M15 4155)."""
    h2 = [_level("crt", type="BEARISH (CLASSIC)", price=4185.0, time=ts(at(4)), end_kind="active")]
    m15 = [
        _level("fvg", type="FVG (BULLISH)", price=4155.0, time=ts(at(6, 30)),
               end_kind="active", box_top=4158.0, box_bottom=4152.0)
    ]
    levels = {"H2": h2, "M15": m15}
    prices = {"H2": 4150.0, "M15": 4155.0}
    counts = {"H2": 20, "M15": 40}

    def provider(*, symbol, timeframe, families=None, bars=300, offset=0, **kwargs):
        return snapshot_payload(
            levels.get(timeframe, []), symbol=symbol, timeframe=timeframe,
            price=prices.get(timeframe, 4150.0), atr=5.0,
        )

    def candles_provider(*, symbol, timeframe, bars=300, offset=0, **kwargs):
        return candles_payload(
            bars_rows(counts.get(timeframe, 20)), symbol=symbol, timeframe=timeframe
        )

    return Feed(provider=provider, candles_provider=candles_provider)


def test_level_lookup_measures_a_p2_tag_against_pane_two(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    store.set_view(layout="split", panes=["H2", "M15"])
    registry = ToolRegistry(store, _split_feed(), _png_renderer(tmp_path, clock), clock=clock)

    registry.initial_render()
    tag = next(t for t in registry.last_result.manifest["tags"] if t.startswith("P2:"))

    result = registry.execute(ToolCall(name="level_lookup", arguments={"tag": tag})).result

    match = result["matches"][0]
    assert match["family"] == "fvg"
    # pane 2's basis is 4155, so the fvg at 4155 is at distance 0 — measured
    # against the primary pane's 4150 it would read 5.0.
    assert result["current_price"] == approx(4155.0)
    assert match["distance_points"] == approx(0.0)


def test_level_lookup_searches_every_pane_by_family_and_near_price(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    store.set_view(layout="split", panes=["H2", "M15"])
    registry = ToolRegistry(store, _split_feed(), _png_renderer(tmp_path, clock), clock=clock)

    registry.initial_render()

    by_family = registry.execute(
        ToolCall(name="level_lookup", arguments={"family": "fvg"})
    ).result
    # the fvg lives only on pane 2; a primary-only search would return nothing.
    assert [m["family"] for m in by_family["matches"]] == ["fvg"]
    assert by_family["matches"][0]["timeframe"] == "M15"
    # the header is still the primary pane's basis; the match is pane 2's.
    assert by_family["current_price"] == approx(4150.0)
    assert by_family["matches"][0]["distance_points"] == approx(0.0)

    by_near = registry.execute(
        ToolCall(name="level_lookup", arguments={"near_price": 4156.0, "radius": 3.0})
    ).result
    assert [m["family"] for m in by_near["matches"]] == ["fvg"]


# --------------------------------------------------------------------------- #
# Phase 6d: a persisted bad offset degrades instead of bricking the loop (C1)
# --------------------------------------------------------------------------- #

def _historyless_feed(*, fail_when):
    """A feed that raises ``InsufficientHistory`` for offsets matching ``fail_when``."""

    def provider(*, symbol, timeframe, families=None, bars=300, offset=0, **kwargs):
        if fail_when(int(offset)):
            raise InsufficientHistory(f"offset {offset} is past the feed's history")
        return snapshot_payload([_fvg_level()], symbol=symbol, timeframe=timeframe,
                                price=4155.0, atr=5.0)

    def candles_provider(*, symbol, timeframe, bars=300, offset=0, **kwargs):
        if fail_when(int(offset)):
            raise InsufficientHistory(f"offset {offset} is past the feed's history")
        return candles_payload(bars_rows(), symbol=symbol, timeframe=timeframe)

    return Feed(provider=provider, candles_provider=candles_provider)


def test_a_persisted_offset_past_history_degrades_to_the_live_edge(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    store.set_view(offset=999)  # persisted: the feed holds nowhere near this
    feed = _historyless_feed(fail_when=lambda offset: offset > 0)
    agent = ScriptedAgent([AgentReply(output={"reasoning": "recovered"})])
    loop = AgentLoop(store, feed, _png_renderer(tmp_path, clock), agent, clock=clock)

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    assert store.data.view.offset == 0      # degraded to the live edge, so the view is usable
    assert outcome.image_path               # the retry rendered an image
    assert "render_error" not in outcome.output
    assert len(store.data.turns) == 1


def test_a_render_failure_is_recorded_and_the_turn_still_completes(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    store.set_view(offset=5)
    feed = _historyless_feed(fail_when=lambda offset: True)  # even the live edge fails
    agent = ScriptedAgent([AgentReply(output={"reasoning": "no image, carry on"})])
    loop = AgentLoop(store, feed, _png_renderer(tmp_path, clock), agent, clock=clock)

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    assert outcome.image_path == ""
    assert outcome.output["render_error"].startswith("InsufficientHistory")
    assert store.data.turns[0].output["render_error"].startswith("InsufficientHistory")


# --------------------------------------------------------------------------- #
# One turn, one instant
# --------------------------------------------------------------------------- #

def test_one_turn_stamps_one_time(tmp_path):
    clock = _AdvancingClock(at(6, 0))
    store = ContextStore("XAUUSDm", state_dir=str(tmp_path / "state"), clock=clock)
    store.set_view(timeframe="M15", bars=120)
    store.set_enabled(True)
    feed = _stub_with_fvg().build()
    key = _m15_key()

    agent = ScriptedAgent([
        AgentReply(tool_calls=[
            ToolCall(name="add_pin", arguments={"level_key": key}),
            ToolCall(
                name="add_watch",
                arguments={"condition": "level_forms", "params": {"family": "fvg"}, "ttl_hours": 4.0},
            ),
            ToolCall(name="set_thesis", arguments={"bias": "bullish"}),
            ToolCall(name="add_note", arguments={"text": "one instant"}),
        ]),
        AgentReply(output={"thesis": {"bias": "bearish"}}),
    ])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)
    outcome = loop.run_turn(trigger="request")

    turn = store.data.turns[0]
    stamp = turn.started_at
    assert turn.ended_at == stamp
    pin = store.open_subscriptions(SubscriptionKind.PIN)[0]
    watch = store.open_subscriptions(SubscriptionKind.WATCH)[0]
    assert pin.starts_at == stamp
    assert watch.starts_at == stamp
    assert store.data.thesis.updated_at == stamp
    assert outcome.output["notes"][0]["at"] == stamp.isoformat()


# --------------------------------------------------------------------------- #
# Notes as memory
# --------------------------------------------------------------------------- #

def test_a_note_written_this_turn_appears_in_the_next_briefing(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    first_agent = ScriptedAgent([
        AgentReply(tool_calls=[ToolCall(name="add_note", arguments={"text": "remember 4150"})]),
        AgentReply(output={"reasoning": "noted"}),
    ])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), first_agent, clock=clock)
    first = loop.run_turn(trigger="request")
    assert first.output["notes"][0]["text"] == "remember 4150"

    clock.advance(minutes=2)  # clear the min-turn interval
    second_agent = ScriptedAgent([AgentReply()])
    loop2 = AgentLoop(store, feed, _renderer(tmp_path, clock), second_agent, clock=clock)
    loop2.run_turn(trigger="request")
    notes = second_agent.requests[0].briefing["notes"]
    assert any(note["text"] == "remember 4150" for note in notes)


# --------------------------------------------------------------------------- #
# Applying the output
# --------------------------------------------------------------------------- #

def test_a_rejected_output_is_captured_not_raised(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    agent = ScriptedAgent([
        AgentReply(output={
            "thesis": {"bias": "sideways"},       # not a valid bias
            "proposals": [{"bias": "sideways"}],  # not a valid bias
        })
    ])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is True
    errors = outcome.output["apply_errors"]
    assert any(e.startswith("thesis:") for e in errors)
    assert any(e.startswith("proposal:") for e in errors)
    assert len(store.data.turns) == 1


def test_a_scripted_agent_falls_silent_when_the_script_runs_out():
    agent = ScriptedAgent([AgentReply(text="hello")])
    first = agent.complete(AgentRequest())
    assert first.text == "hello"
    second = agent.complete(AgentRequest())
    assert second.tool_calls == [] and second.output == {}  # the documented default


# --------------------------------------------------------------------------- #
# The system prompt contract
# --------------------------------------------------------------------------- #

def test_system_prompt_contains_the_contract():
    prompt = prompts.SYSTEM_PROMPT

    assert "PROPOSE-ONLY" in prompt  # role
    assert "CRT" in prompt and "Candle Range Theory" in prompt  # playbook
    assert "level_forms" in prompt  # condition vocabulary
    assert "level_lookup" in prompt  # truth rule
    assert "Never read a price off the image" in prompt
    assert "thesis" in prompt and "proposals" in prompt  # output contract
    assert "mode=propose" in prompt

    assert prompts.build_system_prompt() == prompt
    extended = prompts.build_system_prompt(playbook="Be patient.", extra="Symbol is gold.")
    assert extended.startswith(prompt)
    assert "Be patient." in extended and "Symbol is gold." in extended


# --------------------------------------------------------------------------- #
# The briefing
# --------------------------------------------------------------------------- #

def test_briefing_carries_the_memory(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    store.set_thesis(
        bias="bearish", storyline="rejection at the range high", invalidation="above 4200"
    )
    store.add_subscription("watch", "price_crosses", {"price": 9000.0}, now=clock())
    store.record_turn(
        "boot",
        output={"reasoning": "no setup yet", "notes": [{"at": "2026-10-15T06:00:00+00:00", "text": "remember 4150"}]},
        now=clock(),
    )
    clock.advance(minutes=5)

    briefing = prompts.build_briefing(store, trigger="request", detail="hi", now=clock())

    assert briefing["trigger"] == "request" and briefing["detail"] == "hi"
    assert briefing["thesis"]["bias"] == "bearish"
    assert len(briefing["subscriptions"]) == 1
    assert briefing["subscriptions"][0]["seconds_remaining"] is not None
    assert briefing["budget"]["turns_today"] == 1
    assert briefing["previous_turn"]["conclusion"] == "no setup yet"
    assert briefing["notes"][0]["text"] == "remember 4150"
    assert briefing["view"]["timeframe"] == "M15"
    assert briefing["fires"] == [] and briefing["retroactive"] == []
    assert briefing["now"] == clock().isoformat()


def test_briefing_refuses_without_an_instant(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    with pytest.raises(RuntimeError):
        prompts.build_briefing(store, trigger="request", now=None)


# --------------------------------------------------------------------------- #
# The request records the calls it fed back (phase 5)
# --------------------------------------------------------------------------- #

def test_run_turn_records_the_calls_whose_results_it_fed_back(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    agent = ScriptedAgent([
        AgentReply(tool_calls=[
            ToolCall(call_id="c1", name="add_note", arguments={"text": "hello"}),
            ToolCall(call_id="c2", name="render"),
        ]),
        AgentReply(output={"reasoning": "done"}),
    ])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    loop.run_turn(trigger="request")

    # the same object is handed to every round, so its tool activity accumulates
    # in order, alongside the results, for the wire layer to rebuild.
    request = agent.requests[0]
    assert [call.call_id for call in request.tool_calls_made] == ["c1", "c2"]
    assert [result.call_id for result in request.tool_results] == ["c1", "c2"]


def test_tool_calls_made_includes_calls_dropped_by_the_cap(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    feed = _stub_with_fvg().build()
    calls = [
        ToolCall(call_id=f"c{i}", name="add_note", arguments={"text": f"note {i}"})
        for i in range(MAX_TOOL_CALLS_PER_TURN + 2)
    ]
    agent = ScriptedAgent([AgentReply(tool_calls=calls), AgentReply()])
    loop = AgentLoop(store, feed, _renderer(tmp_path, clock), agent, clock=clock)

    loop.run_turn(trigger="request")

    request = agent.requests[0]
    # every emitted call has a result (executed or tool_cap-refused), and is recorded.
    assert len(request.tool_calls_made) == MAX_TOOL_CALLS_PER_TURN + 2
    assert len(request.tool_results) == MAX_TOOL_CALLS_PER_TURN + 2
    assert [r.call_id for r in request.tool_results] == [c.call_id for c in calls]
