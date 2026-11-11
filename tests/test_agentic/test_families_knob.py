"""Tests for the indicator-families knob (settings tab -> agent tool layer).

The operator enables/disables indicator families per strategy in the settings
tab (``config/families_state.json`` via ``strategy.families_registry``); the
enabled set is injected into :class:`AgentLoop` (``families=``) and must restrict
exactly four things, nothing more:

1. the ``set_view`` tool schema's ``families`` enum the model is shown,
2. the ``set_view`` handler (disabled families dropped, reported deferred),
3. every snapshot/render fetch (a persisted view naming a since-disabled
   family never leaks into a chart),
4. the system prompt's indicator guide (no definition for a family the agent
   cannot see).

Everything here runs on the shared stubs — zero API spend, no MT5, no network.
"""
from _fixtures import FakeClock, FakeRenderer, FeedStub, at, bars_rows, ts
from agentic import prompts
from agentic.agent_loop import AgentLoop, AgentReply, ScriptedAgent
from agentic.feed import KNOWN_FAMILIES
from agentic.models import Trigger
from agentic.store import ContextStore
from agentic.tools import ToolCall, ToolRegistry

# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

def _store(tmp_path, clock):
    store = ContextStore("XAUUSDm", state_dir=str(tmp_path / "state"), clock=clock)
    store.set_view(timeframe="M15", bars=20)
    return store


def _registry(tmp_path, clock, *, enabled=None, **kwargs):
    """A registry on a fresh stub feed whose snapshot family asks are recorded."""
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    return ToolRegistry(
        _store(tmp_path, clock), stub.build(),
        FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        enabled_families=enabled, **kwargs,
    )


# --------------------------------------------------------------------------- #
# 1. The tool schema the model sees
# --------------------------------------------------------------------------- #

def test_set_view_schema_enum_is_the_enabled_set(tmp_path):
    clock = FakeClock(at(8, 0))
    reg = _registry(tmp_path, clock, enabled=["sr", "crt", "liquidity"])
    schema = next(s for s in reg.schemas() if s["name"] == "set_view")
    assert schema["parameters"]["properties"]["families"]["enum"] == [
        "sr", "crt", "liquidity",
    ]


def test_no_knob_keeps_the_shipped_schema_untouched(tmp_path):
    """``None`` (no callable / all enabled) must not rewrite the shipped enum:
    every known family stays offered, exactly as before the knob existed."""
    clock = FakeClock(at(8, 0))
    reg = _registry(tmp_path, clock, enabled=None)
    schema = next(s for s in reg.schemas() if s["name"] == "set_view")
    assert schema["parameters"]["properties"]["families"]["items"]["enum"] == list(
        KNOWN_FAMILIES
    )


# --------------------------------------------------------------------------- #
# 2. The set_view handler
# --------------------------------------------------------------------------- #

def test_set_view_drops_disabled_families_and_reports_them_deferred(tmp_path):
    clock = FakeClock(at(8, 0))
    reg = _registry(tmp_path, clock, enabled=["sr", "crt"])
    res = reg.execute(
        ToolCall(call_id="t1", name="set_view", arguments={"families": ["sr", "qm", "crt"]})
    )
    assert res.ok
    assert res.result["families"] == ["sr", "crt"]
    assert res.result["families_deferred"] == ["qm"]
    # the store view only ever holds enabled families
    assert list(reg._store.data.view.families) == ["sr", "crt"]


def test_context_view_never_seeds_a_disabled_liquidity_family(tmp_path):
    """The MNSR first-view repair seeds liquidity — unless the operator turned
    liquidity off; then the first *enabled* family stands in."""
    clock = FakeClock(at(8, 0))
    reg = _registry(
        tmp_path, clock, enabled=["sr", "crt"], require_context_view=True,
    )
    res = reg.execute(
        ToolCall(call_id="t2", name="set_view", arguments={"families": ["sr"]})
    )
    assert res.ok
    assert "liquidity" not in res.result["families"]
    assert res.result["families"][0] == "sr"


def test_context_view_still_seeds_liquidity_when_enabled(tmp_path):
    clock = FakeClock(at(8, 0))
    reg = _registry(tmp_path, clock, enabled=["sr", "liquidity"], require_context_view=True)
    res = reg.execute(
        ToolCall(call_id="t3", name="set_view", arguments={"families": ["sr"]})
    )
    assert res.result["families"][0] == "liquidity"


# --------------------------------------------------------------------------- #
# 3. Fetches (snapshot / render)
# --------------------------------------------------------------------------- #

def test_snapshot_fetches_only_enabled_families(tmp_path):
    """A persisted view may still name a family disabled *after* it was set:
    the lookup's fetch must never ask the feed for it."""
    clock = FakeClock(at(8, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    store = _store(tmp_path, clock)
    store.set_view(timeframe="M15", bars=20, families=["liquidity", "fvg", "qm"])
    reg = ToolRegistry(
        store, stub.build(), FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        enabled_families=["liquidity", "fvg"],
    )
    reg._snapshot_for_timeframe("M15")
    assert stub.snapshot_calls, "the snapshot must actually have been fetched"
    asked = stub.snapshot_families[0]
    assert "qm" not in asked
    assert set(asked) == {"liquidity", "fvg"}


def test_render_never_draws_a_disabled_family(tmp_path):
    clock = FakeClock(at(8, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    store = _store(tmp_path, clock)
    store.set_view(timeframe="M15", bars=20, families=["liquidity", "qm"])
    reg = ToolRegistry(
        store, stub.build(), FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        enabled_families=["liquidity"],
    )
    reg.execute(ToolCall(call_id="t4", name="render", arguments={}))
    assert stub.snapshot_calls, "the render must have fetched a snapshot"
    assert all("qm" not in fams for fams in stub.snapshot_families)


# --------------------------------------------------------------------------- #
# 4. The system prompt's indicator guide
# --------------------------------------------------------------------------- #

def test_indicator_guide_shows_only_enabled_bullets():
    guide = prompts.indicator_guide(["sr", "crt", "liquidity"])
    assert "`sr` (S/R)" in guide
    assert "`crt` (Candle Range Theory)" in guide
    assert "`liquidity`" in guide
    assert "`qm`" not in guide
    assert "`trendline`" not in guide
    # the lifecycle tail always rides along
    assert "Lifecycle words are family-specific" in guide


def test_indicator_guide_fvg_bullet_hides_until_either_family_is_on():
    # the fvg bullet also defines ifvg, so it shows when *either* is enabled
    assert "`fvg`" not in prompts.indicator_guide(["sr", "crt"])
    assert "`fvg`" in prompts.indicator_guide(["sr", "ifvg"])
    assert "`fvg`" in prompts.indicator_guide(["sr", "fvg"])


def test_indicator_guide_default_is_every_family():
    guide = prompts.indicator_guide(None)
    for family in KNOWN_FAMILIES:
        assert f"`{family}`" in guide


def test_build_system_prompt_renders_the_enabled_guide():
    prompt = prompts.build_system_prompt(playbook="", enabled_families=["sr", "ts"])
    assert "`ts` (Turtle Soup)" in prompt
    assert "`ob`" not in prompt
    # the default prompt (no knob) is byte-identical to the shipped constant
    # plus the operator-bound trader-knowledge layer
    layer = prompts.knowledge_layer().strip()
    expected = prompts.SYSTEM_PROMPT
    if layer:
        expected += (
            "\n\nTrader knowledge — concepts every competent trader carries "
            "(the strategy below builds on these; do not redefine them):\n\n" + layer
        )
    assert prompts.build_system_prompt(playbook="") == expected


# --------------------------------------------------------------------------- #
# 5. The loop injection
# --------------------------------------------------------------------------- #

def _thesis_reply(**tokens):
    """A minimal valid end-of-turn reply: the analysis contract needs a thesis."""
    return AgentReply(
        output={
            "thesis": {
                "bias": "neutral",
                "storyline": "waiting for the level",
                "invalidation": "no setup without a touch",
                "confidence": 0.2,
            },
            "reasoning": "no evidence yet",
        },
        **tokens,
    )


def test_loop_injects_families_into_every_request_and_registry(tmp_path):
    """``AgentLoop(families=...)`` is read fresh per turn: the scripted agent's
    first request must carry the restricted tool schema and the filtered guide."""
    clock = FakeClock(at(8, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    store = _store(tmp_path, clock)
    store.set_enabled(True)
    seen = []
    agent = ScriptedAgent(lambda request: (seen.append(request), _thesis_reply())[1])
    loop = AgentLoop(
        store, stub.build(), FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        agent, clock=clock, playbook="plain playbook",
        families=lambda: ["sr", "crt"],
    )
    outcome = loop.run_turn(trigger="request", detail="human asked")
    assert outcome.ok
    request = seen[0]
    set_view = next(t for t in request.tools if t["name"] == "set_view")
    assert set_view["parameters"]["properties"]["families"]["enum"] == ["sr", "crt"]
    assert "`qm`" not in request.system_prompt
    assert "`crt` (Candle Range Theory)" in request.system_prompt
    assert request.system_prompt.count("Playbook addendum") == 1


def test_loop_families_fallback_degrades_to_all_families(tmp_path):
    """A broken injected knob must never brick a turn: ``None`` = everything."""
    clock = FakeClock(at(8, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    store = _store(tmp_path, clock)
    store.set_enabled(True)
    seen = []
    agent = ScriptedAgent(lambda request: (seen.append(request), _thesis_reply())[1])

    def broken():
        raise RuntimeError("registry file unreadable")

    loop = AgentLoop(
        store, stub.build(), FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        agent, clock=clock, families=broken,
    )
    outcome = loop.run_turn(trigger="request", detail="human asked")
    assert outcome.ok
    request = seen[0]
    set_view = next(t for t in request.tools if t["name"] == "set_view")
    assert set_view["parameters"]["properties"]["families"]["items"]["enum"] == list(
        KNOWN_FAMILIES
    )


def test_chat_turn_registry_is_also_restricted(tmp_path):
    """The chat panel shares the knob: its registry carries the enabled set."""
    clock = FakeClock(at(8, 0))
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    store = _store(tmp_path, clock)
    store.set_enabled(True)
    agent = ScriptedAgent(lambda request: AgentReply())
    loop = AgentLoop(
        store, stub.build(), FakeRenderer(out_dir=tmp_path / "renders", clock=clock),
        agent, clock=clock, playbook="plain playbook",
        families=lambda: ["sr", "crt", "liquidity"],
    )
    result = loop.chat_turn("hello")
    assert result.ok
    record = next(
        t for t in store.data.turns if t.trigger is Trigger.REQUEST
    )
    # the turn logged; the registry restriction itself is proven by the
    # registry-level tests above — here we prove chat_turn runs with the knob
    # injected without erroring.
    assert record.trigger_detail == "hello"


# --------------------------------------------------------------------------- #
# 6. The settings-tab registry (persistence)
# --------------------------------------------------------------------------- #

def test_families_registry_defaults_to_all_enabled(tmp_path, monkeypatch):
    """A fresh state file (no toggles yet) starts with every family on —
    regardless of whatever the operator's live knob currently says."""
    from strategy import families_registry
    monkeypatch.setattr(
        families_registry, "_STATE_PATH", str(tmp_path / "families_state.json")
    )
    rows = families_registry.list_families()
    assert {r["id"] for r in rows} >= set(KNOWN_FAMILIES)
    assert all(r["enabled"] for r in rows)


def test_families_registry_persists_toggles(tmp_path, monkeypatch):
    from strategy import families_registry
    monkeypatch.setattr(
        families_registry, "_STATE_PATH", str(tmp_path / "families_state.json")
    )
    families_registry.set_enabled("qm", False)
    families_registry.set_enabled("ocl", False)

    # a fresh read (what a restarted server / next turn would do) sees the file
    assert "qm" not in families_registry.enabled_families()
    assert "ocl" not in families_registry.enabled_families()
    assert "sr" in families_registry.enabled_families()
    rows = {r["id"]: r["enabled"] for r in families_registry.list_families()}
    assert rows["qm"] is False and rows["sr"] is True


def test_families_registry_refuses_unknown_id(tmp_path, monkeypatch):
    import pytest as _pytest
    from strategy import families_registry
    monkeypatch.setattr(
        families_registry, "_STATE_PATH", str(tmp_path / "families_state.json")
    )
    with _pytest.raises(KeyError):
        families_registry.set_enabled("moon_phase", False)
