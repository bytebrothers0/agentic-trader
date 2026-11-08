"""The real, opt-in live vision smoke test (spec phase 6c).

This is the one test in the suite that talks to a model and to MT5. It is
**skipped unless** ``AGENT_LIVE_TEST=1`` *and* a provider key resolves from the
shared ``/api/ai`` configuration (:func:`ai_agent.config.resolve_provider`), so
``pytest -q`` never calls out and never spends a cent.

It runs exactly one ``boot`` turn through :class:`agent_service.AgentService`
against the **real** feed (live MT5), the **real** renderer and the **real**
vision client, using a temp state dir, a temp render dir and a non-production
symbol alias so the runtime's real ``agentic/state`` / ``agentic/renders`` are
never touched. A small ``max_tokens`` bounds a single turn's spend, and the leash
is asserted to permit exactly one turn and refuse a second at the same instant.

Run it explicitly::

    AGENT_LIVE_TEST=1 python -m pytest tests/test_agent_live.py -q -s

The provider's per-request ceiling (hosted tier only)
-----------------------------------------------------
This section describes the **hosted Groq** tier. The keyless local provider
(``LLM_PROVIDER=local``, e.g. an opencode-proxy) has no such per-request cap, so
when it is configured the full-thesis contract at the end of the test runs
instead of skipping — which is exactly why the local provider exists.

The inherited vision provider (Groq, ``qwen/qwen3.8-27b`` on the ``on_demand``
service tier) allows only **7000 input tokens per request** (ITPM). That is a
*hard* per-request cap: a request larger than it is answered with ``HTTP 413``
("Request too large ... Requested N" where ``N > 7000``), and waiting cannot make
it fit.

A real boot turn is multi-round, and *every* round re-sends the whole fixed
prefix. Measured against the live API, that prefix is already:

==========================================  ======
part                                        tokens
==========================================  ======
system prompt (spec contract)                1177
tool schema, 11 tools (spec contract)        1478
user briefing (JSON)                          401
chart image                                  783
**fixed prefix, every round**               **~3839**
==========================================  ======

That leaves ~3161 tokens for *all* tool results. A ``render`` tool result carries
the full tag manifest (the manifest is how tags resolve; see the spec) and is
measured at **2314 tokens** for the leanest useful view (M15, 20 bars,
crt+bos) up to **5936 tokens** for the view the model actually prefers (M15,
crt+bos+fvg). Any of those pushes the next request past 7000 and the provider
refuses it. The turn's model calls still succeed and are billed; only the round
that would carry the manifest is refused.

So this test asserts the whole live contract and, when the provider refuses a
round purely on a documented quota (the per-request ceiling above, or the
account's daily token cap), records the fact and skips. When at least one round
ran before the refusal, a half-run vision turn (real image in, a real parsed
reply out, billed) is still proven before the skip; when the very first round is
refused, nothing ran and nothing was billed, and the skip says so.
"""
from __future__ import annotations

import json
import os

import pytest

LIVE_ENABLED = os.environ.get("AGENT_LIVE_TEST") == "1"

#: The symbol the live turn runs against. A *non-production symbol alias* distinct
#: from the production ``XAUUSDm`` so no production store is read or written; MT5
#: resolves it to the same gold instrument (loader alias), so the feed is genuinely live.
LIVE_SYMBOL = os.environ.get("AGENT_LIVE_SYMBOL", "XAUUSD")

#: A hard per-turn output cap: the vision turn's spend is bounded by it. It is
#: generous because the local provider's strong models are **reasoning** models —
#: the hidden reasoning counts against this cap, so a small value truncates the
#: turn before the structured object is ever written (300-1300 visible tokens, but
#: 600 was not enough; see the provider subsection of the spec).
MAX_OUTPUT_TOKENS = 8000

#: The render size for the smoke test. The renderer is real; only the size is
#: dialled down so the image is not the thing that overflows (image tokens are a
#: flat ~783 at every size we measured, so this mainly bounds disk/CPU).
RENDER_WIDTH = 896
RENDER_HEIGHT = 504

#: A lean seeded perception. Fewer drawn levels means a smaller ``render``
#: manifest, which is the binding constraint on this tier — though the fixed
#: prompt/tool/image prefix means even a lean manifest does not fit here.
INITIAL_FAMILIES = ["crt", "bos", "fvg"]
INITIAL_BARS = 120

#: Substrings that identify a provider *quota* refusal (per-request or per-day),
#: as opposed to a wiring fault. Matched against ``TurnOutcome.reason``.
PROVIDER_LIMIT_MARKERS = (
    "HTTP 413",
    "HTTP 429",
    "Request too large",
    "input tokens per minute",
    "tokens per day",
    "rate_limit_exceeded",
)


def _key_ready() -> bool:
    """Whether the provider is usable. Does not import the provider when not live.

    A keyless provider (``LLM_PROVIDER=local``, ``key_env == ""``) is ready as soon
    as it names a base URL — no key is needed for it.
    """
    if not LIVE_ENABLED:
        return False  # keep a normal suite run free of the provider config
    try:
        from ai_agent import config as cfg

        _provider, base, _model, key_env = cfg.resolve_provider()
        if not key_env:
            return bool(base)  # keyless endpoint: nothing to resolve
        return bool(os.environ.get(key_env))
    except Exception:
        return False


def _is_provider_limit(reason: str) -> bool:
    """Whether a refused turn was refused by a provider quota, not a wiring fault."""
    text = str(reason or "")
    return any(marker in text for marker in PROVIDER_LIMIT_MARKERS)


_RUN_LIVE = _key_ready()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _RUN_LIVE,
        reason="live smoke test: set AGENT_LIVE_TEST=1 with a resolved provider key to run",
    ),
]


def test_live_boot_turn_reads_the_real_chart(tmp_path):
    from ai_agent import config as cfg
    from agent_service import AgentConfig, AgentService
    from agentic.llm import PRICES, estimate_cost
    from agentic.models import VALID_BIAS, Trigger
    from agentic.renderer import Renderer
    from agentic.store import MAX_SPEND_PER_DAY_USD, LeashExceeded
    from agentic.tools import TOOL_NAMES, ToolCall, ToolRegistry

    provider, base, model, key_env = cfg.resolve_provider()
    # A keyless provider (LLM_PROVIDER=local) has no key variable by design.
    assert (not key_env) or os.environ.get(key_env), "no provider key resolved"

    # --- the hard cost cap: one turn's worst-case spend is under the leash -----
    # Zero is valid (the local keyless provider is free); the leash still has to
    # permit the turn and refuse a second at the same instant.
    worst_case = estimate_cost(model, 20_000, MAX_OUTPUT_TOKENS)
    assert 0 <= worst_case < MAX_SPEND_PER_DAY_USD

    state_dir = tmp_path / "state"
    render_dir = tmp_path / "renders"

    config = AgentConfig(
        symbol=LIVE_SYMBOL,
        timeframe="M15",
        bars=INITIAL_BARS,
        mode="live",
        model=model,
        api_base=base,
        api_key_env=key_env,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.0,
        poll_s=3600.0,          # the spawned watchdog thread sleeps through the test
        http_timeout_s=180.0,
        state_dir=str(state_dir),
        out_dir=str(render_dir),
    )
    # A *real* renderer, only smaller than the default (see RENDER_WIDTH/HEIGHT).
    renderer = Renderer(width=RENDER_WIDTH, height=RENDER_HEIGHT, out_dir=str(render_dir))
    service = AgentService(config, renderer=renderer)  # real Feed() + real VisionClient
    service.enable()                 # arm the gate: a boot turn only runs when armed
    try:
        store = service.store
        # Seed the agent's lean starting perception (a fresh store seeds only
        # timeframe/bars from config; the families are the agent's own dial).
        store.set_view(families=INITIAL_FAMILIES, bars=INITIAL_BARS)
        store.save()

        # The leash permits this one turn...
        store.check_leash()

        outcome = service.boot()
        assert outcome is not None, "the boot turn returned no outcome"
        assert outcome.trigger == Trigger.BOOT.value

        # --- the provider refused the very first round: nothing ran, nothing billed
        # A turn whose *first* model call is refused records no turn and bills
        # nothing (agent_loop's `not (tokens or cost)` path). If that refusal is a
        # provider quota, the wiring is simply untestable on this account right
        # now — say so rather than red-failing.
        if not outcome.ok and not store.data.turns:
            print("\n=== LIVE BOOT TURN (no round ran) ===")
            print(json.dumps({
                "provider": provider, "model": model, "base": base,
                "symbol": LIVE_SYMBOL, "ok": outcome.ok,
                "reason": (outcome.reason or "")[:300],
            }, indent=2))
            if _is_provider_limit(outcome.reason):
                pytest.skip(
                    "provider refused the first round on an account quota "
                    f"({outcome.reason[:160]}) — no round ran, so no live turn could "
                    "be exercised on this account right now"
                )
            pytest.fail(f"boot turn failed for a non-quota reason: {outcome.reason}")

        # --- wiring invariants that hold once a real round has been billed -----
        # Even a turn the provider cuts short bills the rounds that succeeded
        # (agent_loop bills a partial turn rather than dropping the spend).
        assert len(store.data.turns) == 1, "the turn was not logged"
        record = store.data.turns[0]
        assert record.trigger is Trigger.BOOT
        assert int(record.tokens or 0) > 0, "no tokens billed"
        # A real round is billed; the *cost* is only non-zero for a priced model.
        # The local keyless provider's free model legitimately costs nothing, so in
        # that case assert the accounting is exact rather than positive.
        assert store.data.budget.spend_usd_today < 0.25, "spend exceeded the hard cap"
        assert store.data.budget.spend_usd_today == pytest.approx(record.cost_usd)
        if PRICES.get(model, (0.0, 0.0)) != (0.0, 0.0):
            assert store.data.budget.spend_usd_today > 0, "a priced round must cost money"

        # --- propose-only: no order tool exists, and one would be refused -------
        assert not any(
            word in name for name in TOOL_NAMES for word in ("order", "place", "execute")
        )
        registry = ToolRegistry(store, service._feed, Renderer(out_dir=str(render_dir)))
        refused = registry.execute(ToolCall(name="place_order", arguments={}))
        assert refused.ok is False
        assert "unknown_tool" in refused.error
        # every call the model made this turn went through the eleven-tool surface
        made = [entry["call"]["name"] for entry in record.tool_calls]
        assert all(name in TOOL_NAMES for name in made), f"off-surface call: {made}"

        # --- the leash permits at most one turn: a second is refused ------------
        with pytest.raises(LeashExceeded) as excinfo:
            store.check_leash(record.started_at)
        assert excinfo.value.reason in {
            "min_turn_interval", "max_turns_per_hour", "max_turns_per_day", "max_spend_per_day",
        }

        thesis = store.data.thesis
        manifest = outcome.manifest or {}

        # --- the real output, for the phase report ------------------------------
        print("\n=== LIVE BOOT TURN ===")
        print(json.dumps({
            "provider": provider,
            "model": model,
            "base": base,
            "symbol": LIVE_SYMBOL,
            "ok": outcome.ok,
            "reason": (outcome.reason or "")[:200],
            "render_id": manifest.get("render_id"),
            "tag_count": len(manifest.get("tags") or {}),
            "price_range": manifest.get("price_range"),
            "bias": thesis.bias,
            "storyline": thesis.storyline,
            "invalidation": thesis.invalidation,
            "confidence": thesis.confidence,
            "tool_calls": made,
            "tokens": record.tokens,
            "cost_usd": record.cost_usd,
            "spend_usd_today": store.data.budget.spend_usd_today,
        }, indent=2))

        if not outcome.ok:
            # A turn the provider cut short still ran real rounds; require that
            # evidence before deciding whether the refusal was a quota or a bug.
            assert made, "the model made no tool call before the turn failed"
            if _is_provider_limit(outcome.reason):
                # The model read the real chart and its calls were billed; the
                # provider then refused a round on an account quota. The per-request
                # form is the 7000 input-token/minute ceiling: the fixed system
                # prompt (1177) + tool schema (1478) + image (783) + briefing (401)
                # alone leave ~3161 tokens for tool results, and a real render
                # manifest is 2314-5936 tokens, so the round that carries it cannot
                # fit. The per-day form is the account's daily token cap. Neither is
                # a wiring fault. See the module docstring.
                pytest.skip(
                    "provider refused a round on an account quota "
                    f"({outcome.reason[:160]}) — this account tier cannot carry a "
                    "real render manifest alongside the fixed prompt+tools+image; "
                    "the live vision rounds before it succeeded and were billed"
                )
            pytest.fail(f"boot turn failed for a non-quota reason: {outcome.reason}")

        # --- full-thesis contract, asserted whenever the tier lets it through ---
        assert thesis.bias in VALID_BIAS, f"bias {thesis.bias!r} not in {sorted(VALID_BIAS)}"
        assert thesis.storyline.strip(), "the live turn wrote no storyline"
        assert thesis.invalidation.strip(), "the live turn wrote no invalidation"
    finally:
        service.stop()
