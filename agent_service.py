"""agent_service.py — the runnable agent runtime for one symbol (spec phase 6a).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The Agent Loop",
"Human surface", "Economics and the leash" and "Integration points".

This is the wiring seam the pure ``agentic`` core deliberately does not own: one
:class:`AgentService` holds the store, the watchdog and the loop for a single
symbol, starts a daemon watchdog thread, and exposes the read/toggle surface the
HTTP layer mounts. It is intentionally importable with **only** ``agentic.*`` and
the standard library at module level — no ``server``, no ``config.settings``, no
``strategy.registry``, no ``requests`` — so a test can exercise the whole runtime
in-memory, with a fake feed, a fake renderer, a fake clock and zero spend.

Two switches, not one
---------------------
The service's store gate (``store.data.agent.enabled``) is the *runtime* gate.
It is separate from ``config.settings.AGENT_ENABLED`` (the *autostart* switch):
``start()`` is the autostart path and honours the gate, ``enable()``/``disable()``
flip the gate at runtime. A brand-new store is disabled, so ``start()`` on a fresh
symbol does nothing until something arms it — which is why ``enable()`` also makes
sure the watchdog thread is running.

Mock and live
-------------
:func:`build_client` returns a zero-spend :class:`~agentic.agent_loop.ScriptedAgent`
in ``mock`` mode and a :class:`~agentic.llm.VisionClient` in ``live`` mode. The live
transport (:func:`make_transport`) is the only place this module touches the
network, and it is stdlib-only (``urllib.request``) and reads its key from the
environment, so ``import agent_service`` stays cheap and a missing key fails with a
clear message rather than at import time.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agentic._time import as_aware
from agentic.agent_loop import (
    MAX_TOOL_ROUNDS,
    AgentLoop,
    AgentReply,
    ScriptedAgent,
    TurnOutcome,
)
from agentic.feed import Feed
from agentic.llm import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, Transport, VisionClient
from agentic.prompts import subscription_briefing, turn_conclusion
from agentic.renderer import DEFAULT_RENDER_DIR, Renderer
from agentic.store import ContextStore, LeashExceeded
from agentic.tools import ToolCall
from agentic.watchdog import Watchdog

logger = logging.getLogger("agent_service")

#: How many turn ids the panel reads back by default.
DEFAULT_TURNS_LIMIT = 50
#: How many recent turns the panel embeds.
PANEL_TURNS = 20
#: How many failures the service remembers for diagnostics.
MAX_FAILURE_LOG = 20


def _utcnow() -> datetime:
    """The real UTC clock. Tests inject their own via ``clock=``."""
    return datetime.now(timezone.utc)


@dataclass
class AgentConfig:
    """Everything the runtime needs, decoupled from ``config.settings``.

    Mirrors the ``AGENT_*`` block in :mod:`config.settings` one-for-one; the
    server builds one of these from those constants, and a test builds one
    directly.
    """

    symbol: str = "XAUUSDm"
    timeframe: str = "M15"
    bars: int = 300
    mode: str = "mock"
    model: str = "gpt-4o-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.0
    poll_s: float = 15.0
    http_timeout_s: float = 120.0
    state_dir: Optional[str] = None
    out_dir: Optional[str] = None


# --------------------------------------------------------------------------- #
# Transports and clients
# --------------------------------------------------------------------------- #

def make_transport(config: AgentConfig) -> Transport:
    """A stdlib-only OpenAI-compatible chat transport for ``config.api_base``.

    Reads the API key from ``os.environ[config.api_key_env]`` and raises a clear
    :class:`RuntimeError` when it is absent *and* on every call, so a missing key
    is reported before any bytes go on the wire. Deliberately stdlib-only
    (``urllib.request``): the live path is the one impure edge and it must not pull
    a third-party HTTP client into the import graph. Only call this in live mode.
    """
    import urllib.error
    import urllib.request

    base = str(config.api_base or "").rstrip("/")
    url = f"{base}/chat/completions"
    key_env = str(config.api_key_env or "OPENAI_API_KEY")
    timeout_s = float(config.http_timeout_s or 120.0)

    def _key() -> str:
        key = os.environ.get(key_env)
        if not key:
            raise RuntimeError(
                f"agent live mode needs the {key_env} environment variable set "
                f"(AGENT_API_KEY_ENV); refusing to POST {url} without a key"
            )
        return key

    _key()  # fail fast at construction, before any turn can be attempted

    def _transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        api_key = _key()
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # pragma: no cover — live only
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise RuntimeError(f"agent transport HTTP {exc.code}: {detail[:400]}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover — live only
            raise RuntimeError(f"agent transport failed: {exc.reason}") from exc
        return json.loads(raw)

    return _transport


def _mock_script(config: AgentConfig) -> List[AgentReply]:
    """The deterministic, zero-spend script a mock turn replays.

    Round 1 arms a watch and sets the view; round 2 writes a thesis (with an
    explicit invalidation and low confidence), a note and a one-line reasoning —
    a plausible, repeatable analyst turn that spends nothing and touches no
    network. It is a *list of replies*; :func:`_mock_agent` replays it once per
    turn (see there), so the script is not consumed by the first turn alone.
    """
    timeframe = str(config.timeframe or "M15")
    round_one = AgentReply(
        tool_calls=[
            ToolCall(
                call_id="mock-set-view",
                name="set_view",
                arguments={"timeframe": timeframe, "bars": int(config.bars or 300)},
            ),
            ToolCall(
                call_id="mock-add-watch",
                name="add_watch",
                arguments={
                    "condition": "level_forms",
                    "params": {
                        "family": "fvg",
                        "direction": "bullish",
                        "timeframe": timeframe,
                    },
                    "ttl_hours": 12.0,
                    "reason": "wait for the next bullish FVG in the active timeframe",
                },
            ),
        ],
        tokens={"prompt": 0, "completion": 0},
        cost_usd=0.0,
    )
    round_two = AgentReply(
        output={
            "thesis": {
                "bias": "bullish",
                "storyline": (
                    "Higher-timeframe structure is constructive; expecting a "
                    "continuation into the nearest unmitigated bullish FVG."
                ),
                "levels_of_interest": [],
                "invalidation": (
                    "a close back below the most recent higher low invalidates the "
                    "bullish read"
                ),
                "confidence": 0.35,
            },
            "notes": [
                {"text": "mock turn: leaning bullish, but confidence is low"}
            ],
            "reasoning": "bullish lean, waiting for a confirming FVG before any plan",
        },
        tokens={"prompt": 0, "completion": 0},
        cost_usd=0.0,
    )
    return [round_one, round_two]


def _mock_agent(config: AgentConfig) -> ScriptedAgent:
    """A ``ScriptedAgent`` that replays the mock script on *every* turn.

    ``ScriptedAgent`` consumes a plain list once, so only the very first turn
    would have content and every later turn would fall silent. Driving it from a
    callable that resets the round counter whenever ``request.turn_id`` changes
    makes each turn yield the same two-round script (round 1 arms a watch, round 2
    writes the thesis) — consecutive mock turns are identical, and still zero-spend.
    """
    script = _mock_script(config)
    state: Dict[str, Any] = {"turn_id": None, "round": 0}

    def reply(request: Any) -> AgentReply:
        turn_id = getattr(request, "turn_id", None)
        if turn_id != state["turn_id"]:
            state["turn_id"] = turn_id
            state["round"] = 0
        index = state["round"]
        state["round"] += 1
        if index < len(script):
            return script[index]
        return AgentReply()  # nothing more to say this turn

    return ScriptedAgent(reply)


def build_client(config: AgentConfig, transport: Optional[Transport] = None):
    """The client for ``config.mode``: a mock ``ScriptedAgent`` or a ``VisionClient``.

    ``mock`` (the default) spends nothing. ``live`` wraps the injected
    ``transport`` — or builds one with :func:`make_transport` — so a test can drive
    the real client with a canned transport and no network.
    """
    mode = str(config.mode or "mock").strip().lower()
    if mode != "live":
        return _mock_agent(config)
    return VisionClient(
        transport if transport is not None else make_transport(config),
        model=str(config.model or DEFAULT_MODEL),
        temperature=float(config.temperature),
        max_tokens=int(config.max_tokens or DEFAULT_MAX_TOKENS),
    )


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #

class AgentService:
    """One symbol's agent runtime: store + watchdog + loop + a watchdog thread.

    Everything is injectable (``feed``, ``renderer``, ``client``, ``clock``) so
    the whole thing runs in a test with a fake feed, a fake renderer and a fake
    clock. The default clock is a real UTC clock; the default feed/renderer/client
    are the live ones, but all three are lazy about the outside world (the feed's
    providers import the server only when called).
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        feed: Optional[Feed] = None,
        renderer: Optional[Renderer] = None,
        client: Optional[Any] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config
        self._clock = clock or _utcnow
        self._feed = feed if feed is not None else Feed()
        self._renderer = renderer if renderer is not None else Renderer(
            clock=self._clock, out_dir=config.out_dir
        )
        self._client = client if client is not None else build_client(config)

        self._store: Optional[ContextStore] = None
        self._watchdog_obj: Optional[Watchdog] = None
        self._thread: Optional[threading.Thread] = None
        self._thread_stop: Optional[threading.Event] = None
        self._lock = threading.RLock()        # guards the service's own bookkeeping
        self._turn_lock = threading.RLock()   # serialises whole turns (read-modify-write)

        self._paused = False
        self._started = False       # the boot turn has run this process
        self._autostarted = False   # start() actually armed the gate and ran a thread
        self._draining = False      # a stop() timed out: the old thread is still alive
        self._last_render: Dict[str, Any] = {}
        self._failures: List[str] = []

    # ------------------------------------------------------------------ store

    @property
    def store(self) -> ContextStore:
        """The symbol's store, loaded once from ``state_dir`` and cached.

        A *new* store is seeded with the config's timeframe/bars (a resumed store
        keeps the view the agent chose — a restart must not lobotomise it).
        """
        if self._store is None:
            state_dir = self.config.state_dir
            is_new = not os.path.isfile(
                ContextStore.path_for(self.config.symbol, state_dir)
            )
            store = ContextStore.load_or_new(
                self.config.symbol, state_dir=state_dir, clock=self._clock
            )
            if is_new:
                try:
                    store.set_view(
                        timeframe=str(self.config.timeframe),
                        bars=int(self.config.bars),
                    )
                except Exception as exc:  # a bad config must not brick the runtime
                    self._record_failure("seed", exc)
                store.save()
            self._store = store
        return self._store

    def load(self) -> ContextStore:
        """Explicitly (re)load the store for this symbol."""
        self._store = ContextStore.load_or_new(
            self.config.symbol, state_dir=self.config.state_dir, clock=self._clock
        )
        return self._store

    # ------------------------------------------------------------------ internals

    def _watchdog(self) -> Watchdog:
        """A persistent watchdog so its coalescing buffers survive between polls."""
        if self._watchdog_obj is None:
            self._watchdog_obj = Watchdog(self._feed, clock=self._clock)
        return self._watchdog_obj

    def _loop(self) -> AgentLoop:
        return AgentLoop(
            self.store,
            self._feed,
            self._renderer,
            self._client,
            clock=self._clock,
            watchdog=self._watchdog(),
        )

    def _record_failure(self, where: str, exc: BaseException) -> None:
        message = f"{where}: {type(exc).__name__}: {exc}"
        with self._lock:
            self._failures.append(message)
            del self._failures[:-MAX_FAILURE_LOG]
        logger.warning("agent service (%s) %s", self.config.symbol, message)

    def _remember_render(self, outcome: Optional[TurnOutcome]) -> None:
        if outcome is None:
            return
        manifest = outcome.manifest or {}
        image_path = outcome.image_path or (manifest.get("image") or {}).get("path", "")
        render_id = manifest.get("render_id", "") or ""
        if not render_id and image_path:
            # A renderer that returns no manifest (a test stub) still names its
            # file after the render id; fall back to the filename stem.
            render_id = os.path.splitext(os.path.basename(image_path))[0]
        if not (image_path or render_id):
            return
        self._last_render = {
            "render_id": render_id,
            "image_path": image_path,
            "manifest": _manifest_summary(manifest),
        }

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Autostart: boot (if armed) then run the watchdog thread. Idempotent.

        Never raises: a boot failure is recorded and the service stays stopped
        rather than taking the server down with it. When the store gate is off,
        ``start()`` starts no thread at all — the runtime gate wins, and
        ``autostarted`` stays false because nothing started.
        """
        try:
            if not self.enabled():
                return  # disabled: do not autostart, do not spawn
            if not self._started:
                self.boot()
                self._started = True
            self._ensure_thread()
            self._autostarted = self.running()
        except Exception as exc:  # noqa: BLE001 — must not break the server
            self._record_failure("start", exc)

    def stop(self) -> None:
        """Stop the watchdog thread (state is kept). Joins; never raises.

        The stop signal is **per thread**: the event is created by
        :meth:`_ensure_thread` and handed to :meth:`_watch`, so a later
        ``start``/``enable`` can never resurrect a thread already being asked to
        stop (which is what clearing one shared event did). ``self._thread`` is
        cleared only once the join confirms the thread exited; if the join times
        out — a turn can outlast the join budget — the thread is kept (so
        ``running()`` stays true) and the service is marked draining, and
        :meth:`_ensure_thread` refuses to spawn a second one while it lives.
        """
        with self._lock:
            thread = self._thread
            stop_event = self._thread_stop
        if stop_event is not None:
            stop_event.set()
        if thread is None:
            return
        if thread is threading.current_thread():
            return  # cannot join ourselves; the loop exits after the current turn
        if thread.is_alive():
            thread.join(timeout=self._join_budget())
        with self._lock:
            if self._thread is thread and not thread.is_alive():
                self._thread = None
                self._thread_stop = None
                self._draining = False
            elif self._thread is thread:
                self._draining = True

    def _join_budget(self) -> float:
        """How long ``stop`` waits for a thread: a full turn plus a poll margin."""
        per_call = max(1.0, float(self.config.http_timeout_s))
        return per_call * (MAX_TOOL_ROUNDS + 1) + max(1.0, float(self.config.poll_s))

    def pause(self) -> None:
        """Keep the state but stop waking: the watchdog still runs, it just idles."""
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def enable(self) -> Dict[str, Any]:
        """Arm the runtime gate and make sure the watchdog thread is running."""
        with self._turn_lock:
            self.store.set_enabled(True, now=as_aware(self._clock()))
            self.store.save()
        self._ensure_thread()
        return self.status()

    def disable(self) -> Dict[str, Any]:
        """Disarm the runtime gate and stop the thread (the kill switch)."""
        with self._turn_lock:
            self.store.set_enabled(False, now=as_aware(self._clock()))
            self.store.save()
        self.stop()
        return self.status()

    def _ensure_thread(self) -> None:
        """Start the watchdog thread if — and only if — none is alive.

        A live thread is never doubled: if a previous ``stop`` timed out and left
        its thread draining, this refuses to spawn a second scanner.
        """
        with self._lock:
            thread = self._thread
            if thread is not None:
                if thread.is_alive():
                    return
                # It exited since we last looked: reap it and start clean.
                self._thread = None
                self._thread_stop = None
                self._draining = False
            stop_event = threading.Event()
            self._thread_stop = stop_event
            self._thread = threading.Thread(
                target=self._watch,
                args=(stop_event,),
                name=f"agent-watchdog-{self.config.symbol}",
                daemon=True,
            )
            self._thread.start()

    def _watch(self, stop_event: threading.Event) -> None:
        """The watchdog loop: poll, scan when armed, and never die silently.

        It waits *before* its first scan, so a thread spawned and then immediately
        stopped (or a test that drives :meth:`scan_once` directly) never races the
        first tick. The whole body — the gate check, the wait and the scan — is
        inside the ``try``, so even a corrupt state file raises into
        ``_record_failure`` rather than killing the thread without a trace.
        """
        while not stop_event.is_set():
            try:
                if stop_event.wait(max(0.0, float(self.config.poll_s))):
                    break
                if self.enabled() and not self.paused():
                    self.scan_once()
            except Exception as exc:  # noqa: BLE001 — the thread must never die
                self._record_failure("watchdog", exc)

    # ------------------------------------------------------------------ work

    def boot(self) -> Optional[TurnOutcome]:
        """The mandatory boot turn (armed only). Backfills the downtime first."""
        if not self.enabled():
            return None
        with self._turn_lock:
            try:
                outcome = self._loop().boot()
            except Exception as exc:  # noqa: BLE001 — a boot failure must not crash
                self._record_failure("boot", exc)
                return None
        self._remember_render(outcome)
        return outcome

    def scan_once(self) -> Optional[TurnOutcome]:
        """One watchdog scan; run the turn the watchdog itself emitted.

        Returns ``None`` when the watchdog emitted no turn yet. The watchdog owns
        the coalescing window, so a burst of fires becomes **one** turn: an early
        fire buffers, the window opens, and nothing runs until it elapses — this
        method never force-flushes.

        The leash is checked *before* the scan. On refusal the scan does not run,
        so nothing is consumed (the subscription's evaluation window does not
        advance) and the next poll re-detects the event rather than losing it.
        The whole turn runs under the turn lock, so a watchdog poll and a human
        request can never interleave their store read-modify-write.
        """
        if not self.enabled() or self.paused():
            return None
        with self._turn_lock:
            now = as_aware(self._clock())
            try:
                self.store.check_leash(now)
            except LeashExceeded:
                return None  # do not scan: leave the fire for the next poll
            try:
                watchdog = self._watchdog()
                loop = self._loop()
                result = watchdog.scan(self.store, now=now)
                if result.turn is None:
                    return None  # still inside the coalescing window
                turn = result.turn
                outcome = loop.run_turn(
                    trigger=turn.trigger,
                    detail=turn.reason,
                    fires=turn.fires,
                    expired=turn.expired,
                )
            except Exception as exc:  # noqa: BLE001 — a poll must never raise out
                self._record_failure("scan", exc)
                return None
        self._remember_render(outcome)
        return outcome

    def run_now(self, message: str = "") -> TurnOutcome:
        """A human ``request`` turn. Always allowed, even when disabled or paused."""
        with self._turn_lock:
            try:
                outcome = self._loop().run_turn(
                    trigger="request", detail=str(message or "human request")
                )
            except Exception as exc:  # noqa: BLE001 — report, never raise out
                self._record_failure("run_now", exc)
                return TurnOutcome(trigger="request", ok=False, reason=str(exc))
        self._remember_render(outcome)
        return outcome

    # ------------------------------------------------------------------ read surface

    def status(self) -> Dict[str, Any]:
        """A small, JSON-safe snapshot of the service's own state.

        ``autostarted`` is true only when :meth:`start` actually armed the gate and
        ran a thread — never merely because ``start`` was called. ``enabled`` is
        read from the store gate, which is the authoritative on/off.
        """
        with self._lock:
            failures = list(self._failures)
            autostarted = bool(self._autostarted)
            draining = bool(self._draining)
        return {
            "enabled": self.enabled(),
            "autostarted": autostarted,
            "running": self.running(),
            "paused": self.paused(),
            "draining": draining,
            "mode": str(self.config.mode),
            "model": str(self.config.model),
            "symbol": str(self.config.symbol),
            "failures": failures,
        }

    def panel(self) -> Dict[str, Any]:
        """A JSON-safe read of the store — the Agent Panel's whole data source.

        It never duplicates the store: every subscription is projected fresh with
        the **shared** :func:`agentic.prompts.subscription_briefing` (so the panel
        and a turn's briefing cannot drift), and the turn log is summarised with
        :func:`agentic.prompts.turn_conclusion`. ``mode``/``model`` come from the
        config (the store has no field for them); ``enabled`` is the store gate —
        the authoritative on/off — and ``autostarted`` says whether the server
        autostarted this service as opposed to a panel toggle.
        """
        store = self.store
        now = as_aware(self._clock())
        with self._lock:
            autostarted = bool(self._autostarted)
        subscriptions: List[Dict[str, Any]] = []
        pins: List[Dict[str, Any]] = []
        for sub in store.open_subscriptions():
            brief = subscription_briefing(sub, now)
            row = {
                "id": brief["id"],
                "kind": brief["kind"],
                "condition": brief["condition"],
                "params": dict(getattr(sub, "params", {}) or {}),
                "state": brief["state"],
                "summary": brief["summary"],
                "expires_at": brief["expires_at"],
                "seconds_remaining": brief["seconds_remaining"],
                "reason": brief["reason"],
            }
            subscriptions.append(row)
            if brief["kind"] == "pin":
                pins.append(
                    {
                        "id": sub.id,
                        "level_key": sub.level_key,
                        "status": sub.status.value if sub.status else None,
                        "query": dict(sub.params or {}),
                        "state": brief["state"],
                        "expires_at": brief["expires_at"],
                        "seconds_remaining": brief["seconds_remaining"],
                        "note": sub.note,
                    }
                )
        return {
            "enabled": bool(store.data.agent.enabled),
            "autostarted": autostarted,
            "mode": str(self.config.mode),
            "model": str(self.config.model),
            "running": self.running(),
            "paused": self.paused(),
            "view": store.data.view.to_dict(),
            "thesis": store.data.thesis.to_dict(),
            "subscriptions": subscriptions,
            "pins": pins,
            "proposals": [p.to_dict() for p in store.data.proposals],
            "budget": store.data.budget.to_dict(),
            "recent_turns": self._turn_rows(PANEL_TURNS),
            "last_render": dict(self._last_render),
        }

    def turns(self, limit: int = DEFAULT_TURNS_LIMIT) -> List[dict]:
        """The turn log, newest first: id, trigger, started_at and the output."""
        return self._turn_rows(limit)

    def _turn_rows(self, limit: int) -> List[Dict[str, Any]]:
        turns = list(self.store.data.turns)
        if limit and limit > 0:
            turns = turns[-int(limit):]
        rows: List[Dict[str, Any]] = []
        for turn in reversed(turns):
            conclusion = turn_conclusion(turn)
            rows.append(
                {
                    "id": conclusion["turn_id"],
                    "trigger": conclusion["trigger"],
                    "started_at": conclusion["at"],
                    "output": dict(getattr(turn, "output", {}) or {}),
                    "summary": conclusion["conclusion"],
                }
            )
        return rows

    def render_path(self, render_id: str) -> Optional[str]:
        """Resolve a render id to its PNG, refusing traversal and unknown ids.

        A render id is validated by *containment* on the **real** paths: the
        candidate must resolve inside ``config.out_dir`` (or ``agentic/renders``)
        and the file must exist. Using ``realpath`` + ``commonpath`` (not
        ``abspath`` + ``startswith``) means a symlink planted inside the render
        directory cannot point outside it and leak another file.
        """
        if not render_id:
            return None
        out_dir = os.path.realpath(str(self.config.out_dir or DEFAULT_RENDER_DIR))
        candidate = os.path.realpath(os.path.join(out_dir, f"{render_id}.png"))
        try:
            inside = os.path.commonpath([out_dir, candidate]) == out_dir
        except ValueError:  # e.g. different drives on Windows
            return None
        if not inside or candidate == out_dir:
            return None
        return candidate if os.path.isfile(candidate) else None

    # ------------------------------------------------------------------ flags

    def running(self) -> bool:
        with self._lock:
            thread = self._thread
        return thread is not None and thread.is_alive()

    def paused(self) -> bool:
        with self._lock:
            return bool(self._paused)

    def enabled(self) -> bool:
        return bool(self.store.data.agent.enabled)


def _manifest_summary(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A small, JSON-safe digest of a render manifest for the panel."""
    manifest = manifest or {}
    if not manifest:
        return {}
    tags = manifest.get("tags") or {}
    image = manifest.get("image") or {}
    return {
        "render_id": manifest.get("render_id", ""),
        "symbol": manifest.get("symbol", ""),
        "timeframe": manifest.get("timeframe", ""),
        "rendered_at": manifest.get("rendered_at"),
        "window": manifest.get("window"),
        "price_range": manifest.get("price_range"),
        "tag_count": len(tags) if isinstance(tags, dict) else 0,
        "image": {
            "path": image.get("path", ""),
            "width": image.get("width"),
            "height": image.get("height"),
        },
    }
