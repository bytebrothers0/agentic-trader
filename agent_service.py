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

import email.utils
import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from agentic._time import as_aware
from agentic.agent_loop import (
    MAX_TOOL_ROUNDS,
    AgentLoop,
    AgentReply,
    ChatTurnResult,
    ScriptedAgent,
    TurnOutcome,
)
from agentic.feed import Feed
from agentic.llm import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, Transport, VisionClient
from agentic.models import Proposal, ProposalStatus, Thesis
from agentic.prompts import subscription_briefing, turn_conclusion
from agentic.renderer import DEFAULT_RENDER_DIR, Renderer
from agentic.store import (
    ContextStore,
    LeashExceeded,
    MAX_RENDERS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_TURNS_PER_DAY,
    MAX_TURNS_PER_HOUR,
    MIN_TURN_INTERVAL_S,
)
from agentic.strategy import load_strategy
from agentic.tools import ToolCall
from agentic.watchdog import Watchdog
from execution.agent_orders import execute_proposal

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


#: The default ``User-Agent`` for the live transport.
#:
#: **Do not remove.** ``urllib.request`` sends ``Python-urllib/3.x`` unless told
#: otherwise, and some providers front their chat API with Cloudflare, which
#: rejects that signature at the edge with ``HTTP 403`` and Cloudflare
#: ``error code: 1010`` — *before* authentication is ever evaluated. Any explicit
#: UA gets past it; this is the one we send. Configurable via
#: ``AGENT_HTTP_USER_AGENT`` (``AgentConfig.http_user_agent``), but never allowed
#: to fall back to the urllib default. Defined **before** :class:`AgentConfig` so
#: the dataclass default and :func:`_request_headers` share this one literal; the
#: ``AGENT_HTTP_USER_AGENT`` constant in :mod:`config.settings` must match it.
DEFAULT_USER_AGENT = "trading-bot-agent/1.0"


def _settings_leash() -> Dict[str, int]:
    """Read the agent's turn leash from ``config.settings`` — live, per turn.

    The user retunes ``AGENT_MAX_TOOL_CALLS`` / ``AGENT_MAX_TOOL_ROUNDS`` /
    ``AGENT_MAX_RENDERS_PER_TURN`` there (the shipped defaults live in
    :mod:`agentic.store` / ``agent_loop``); an edit applies to the very next turn
    with no restart. The loop itself must stay a pure module, so this settings
    read lives here and is injected as a callable.
    """
    from config import settings

    def count(name: str, fallback: int) -> int:
        try:
            value = int(getattr(settings, name, fallback))
        except (TypeError, ValueError):
            return fallback
        return value if value >= 1 else fallback

    return {
        "tool_calls": count("AGENT_MAX_TOOL_CALLS", MAX_TOOL_CALLS_PER_TURN),
        "rounds": count("AGENT_MAX_TOOL_ROUNDS", MAX_TOOL_ROUNDS),
        "renders": count("AGENT_MAX_RENDERS_PER_TURN", MAX_RENDERS_PER_TURN),
    }


def _settings_turn_limits() -> Dict[str, float]:
    """Read the store's turn-rate leash from ``config.settings`` — live, per check.

    Injected into the :class:`~agentic.store.ContextStore` (``set_leash_limits``):
    the store is a pure module, so this settings read lives here. Raises inside
    the injected callable degrade in the store to the shipped constants, so a
    broken settings edit can never unbound the store.
    """
    from config import settings

    def num(name: str, fallback: float) -> float:
        try:
            value = float(getattr(settings, name, fallback))
        except (TypeError, ValueError):
            return fallback
        return value if value >= 0.0 else fallback

    return {
        "min_turn_interval_s": num("AGENT_MIN_TURN_INTERVAL_S", MIN_TURN_INTERVAL_S),
        "max_turns_per_hour": num("AGENT_MAX_TURNS_PER_HOUR", MAX_TURNS_PER_HOUR),
        "max_turns_per_day": num("AGENT_MAX_TURNS_PER_DAY", MAX_TURNS_PER_DAY),
    }


def _settings_families() -> List[str]:
    """Read the operator's enabled indicator families — live, per turn.

    Injected into the :class:`~agentic.agent_loop.AgentLoop` (``families=``):
    the loop is a pure module, so this settings-tab read lives here. A failure
    in the registry degrades in the loop to *all* families, so a broken
    ``config/families_state.json`` can never silence the agent entirely.
    """
    try:
        from strategy.families_registry import enabled_families
        return enabled_families()
    except Exception:  # noqa: BLE001 — degrade to the shipped default
        from agentic.feed import KNOWN_FAMILIES
        return list(KNOWN_FAMILIES)


@dataclass
class AgentConfig:
    """Everything the runtime needs, decoupled from ``config.settings``.

    Mirrors the ``AGENT_*`` block in :mod:`config.settings` one-for-one; the
    server builds one of these from those constants, and a test builds one
    directly.
    """

    symbol: str = "XAUUSDm"
    timeframe: str = "M15"
    bars: int = 180
    mode: str = "mock"
    model: str = "gpt-4o-mini"
    api_base: str = "https://api.openai.com/v1"
    #: Name of the environment variable holding the key. A **blank** value means a
    #: keyless endpoint (e.g. ``LLM_PROVIDER=local``): no key is read, none is
    #: required, and no ``Authorization`` header is sent.
    api_key_env: str = "OPENAI_API_KEY"
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.0
    poll_s: float = 15.0
    http_timeout_s: float = 120.0
    #: The ``User-Agent`` every live request carries. Never blank in practice:
    #: :func:`make_transport` falls back to :data:`DEFAULT_USER_AGENT`, because
    #: urllib's built-in ``Python-urllib/3.x`` is blocked at the edge by
    #: Cloudflare (HTTP 403 / error code 1010) before authentication.
    http_user_agent: str = DEFAULT_USER_AGENT
    state_dir: Optional[str] = None
    out_dir: Optional[str] = None
    # The strategy (see agentic/strategy.py). A blank field defers to
    # config.settings.STRATEGY_* at resolve time (see `resolve_strategy`), so
    # building a config never needs to import config.settings.
    strategy_dir: str = ""
    strategy_name: str = ""

    def resolve_strategy(self) -> tuple:
        """The **(directory, name)** the strategy is loaded from.

        An explicit field wins; a blank falls back, lazily, to
        ``config.settings.STRATEGY_DIR`` / ``STRATEGY_ACTIVE`` (which ship
        ``strategies`` / ``default``). A repo-relative directory is resolved
        against the repo root — the settings file's grandparent — so the default
        not being cwd-dependent is a property of the resolution, not a habit of
        whoever launched the process.
        """
        directory = str(self.strategy_dir or "").strip()
        name = str(self.strategy_name or "").strip()
        if (not directory) or (not name):
            import config.settings as settings
            from pathlib import Path

            if not name:
                name = str(settings.STRATEGY_ACTIVE or "").strip() or "default"
            if not directory:
                strategy_dir = str(settings.STRATEGY_DIR or "").strip() or "strategies"
                if not os.path.isabs(strategy_dir):
                    strategy_dir = str(
                        Path(settings.__file__).resolve().parent.parent / strategy_dir
                    )
                directory = strategy_dir
        return directory, name


# --------------------------------------------------------------------------- #
# Transports and clients
# --------------------------------------------------------------------------- #

def _request_headers(api_key: str, user_agent: str) -> Dict[str, str]:
    """The HTTP headers every live request carries.

    Factored out of :func:`make_transport` so a test can prove the built request
    carries a non-default ``User-Agent`` **without any network call**. An empty
    or whitespace ``user_agent`` falls back to :data:`DEFAULT_USER_AGENT`; the
    urllib default is blocked by Cloudflare 1010, so blank must never win.

    A blank ``api_key`` means a **keyless** endpoint (e.g. a local proxy that
    injects its own upstream credential): the ``Authorization`` header is omitted
    entirely rather than sent as a bare ``"Bearer "``.
    """
    ua = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    headers = {"Content-Type": "application/json", "User-Agent": ua}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


#: HTTP statuses that mean "slow down" and are worth a bounded retry.
_RETRYABLE_STATUS = frozenset({429, 503})

#: How many times a live request is retried when the provider asks us to slow down.
#:
#: A multi-round vision turn re-sends the whole conversation on every round, so on
#: a low per-minute token tier (Groq's on-demand ``qwen/qwen3.8-27b`` allows 7000
#: input tokens/minute) a turn legitimately needs the minute to roll over between
#: rounds. Without a retry the turn fails *mid-way* with HTTP 429 even though the
#: request itself is small enough — the wave of the previous rounds is what tipped
#: the window. Bounded so a persistent failure still surfaces.
TRANSPORT_MAX_RETRIES = 4

#: Hard ceiling on a single retry wait, so a malformed ``Retry-After`` cannot stall a turn.
TRANSPORT_RETRY_CAP_S = 75.0

#: How many times a live request is retried on connection-level failure (DNS,
#: TCP refused, TLS handshake, transient network hiccup) — separate from the
#: provider rate-limit (429/503) retry above.
TRANSPORT_CONNECT_RETRIES = 3

#: Base delay (seconds) for connect-retry exponential backoff: 1s, 2s, 4s ...
#: Capped at :data:`TRANSPORT_RETRY_CAP_S`.
TRANSPORT_CONNECT_BACKOFF_S = 1.0

#: Regex for a ``429`` body that *reports* a daily quota.
#:
#: A per-minute window rolls over in seconds, so retrying is right. A per-day
#: quota (Groq writes ``... on tokens per day (TPD): Limit ...`` / ``... on
#: requests per day (RPD): Limit ...``) does not: retrying just stalls the turn
#: for minutes and then fails anyway. We match the provider's own rate-limit
#: *category token* — ``(TPD)``/``(RPD)`` **immediately followed by its limit
#: separator** (the ``:`` Groq puts before ``Limit``).
#:
#: Deliberately anchored to that reported form: the bare phrases ``"tokens per
#: day"``/``"requests per day"`` and a *prose* mention of ``"(TPD)"`` (e.g. an
#: upsell sentence inside a per-**minute** 429) must **not** be read as a daily
#: quota. Misreading a retryable per-minute 429 as terminal is the dangerous
#: direction; the reverse merely retries (and then still fails safely).
_DAILY_QUOTA_RE = re.compile(r"\((?:tpd|rpd)\)\s*:", re.I)


def _is_daily_quota(detail: str) -> bool:
    """Whether a ``429`` body *reports* a daily quota (so retrying cannot help)."""
    return bool(_DAILY_QUOTA_RE.search(str(detail or "")))


def _parse_seconds(value: Any) -> Optional[float]:
    """Parse a delay into seconds, or ``None``.

    Handles a bare number (``"35"``), Groq's suffixed form (``"28.148s"``) and an
    RFC-7231 HTTP-date ``Retry-After`` (``"Wed, 21 Oct 2015 07:28:00 GMT"``), which
    a Cloudflare-fronted ``503`` returns: the date becomes the seconds until that
    instant. A missing/unparseable value returns ``None``.
    """
    text = str(value or "").strip()
    if not text:
        return None
    numeric = text.rstrip("s").strip()
    try:
        return float(numeric)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed - datetime.now(timezone.utc)).total_seconds()


def _header_value(headers: Any, name: str) -> Any:
    """A case-insensitive header read that works for a dict and a Message alike."""
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return value
    target = str(name).lower()
    try:
        items = headers.items()
    except AttributeError:
        return None
    for key, value in items:
        if str(key).lower() == target:
            return value
    return None


def _retry_after_seconds(headers: Any, detail: str = "") -> float:
    """How long the provider asked us to wait after a 429/503.

    Prefers ``Retry-After`` (seconds or an HTTP-date), then Groq's
    ``x-ratelimit-reset-tokens`` (e.g. ``"28.148s"``), then the ``... try again in
    35.7s`` hint in the body; defaults to 5s. Header lookup is case-insensitive.
    Capped at :data:`TRANSPORT_RETRY_CAP_S`, and floored at a small positive value
    so a ``Retry-After: 0`` cannot tight-loop the retry.
    """
    wait = _parse_seconds(_header_value(headers, "Retry-After"))
    if wait is None:
        wait = _parse_seconds(_header_value(headers, "x-ratelimit-reset-tokens"))
    if wait is None and detail:
        match = re.search(r"try again in ([\d.]+)\s*s", detail, re.I)
        if match:
            wait = float(match.group(1))
    if wait is None:
        wait = 5.0
    return max(0.25, min(float(wait), TRANSPORT_RETRY_CAP_S))


def _probe_endpoint(api_base: str, *, timeout_s: float = 5.0) -> bool:
    """Lightweight reachability heartbeat for the OpenAI-compatible endpoint.

    GETs ``{base}/`` and returns True if the server answers with any HTTP status.
    Used as a pre-flight check so a dead endpoint is surfaced quickly instead of
    burning a full model-turn timeout. Non-fatal: a failed probe is logged and the
    caller proceeds to the actual call, which is covered by connect retry.
    """
    import urllib.error
    import urllib.request

    base = str(api_base or "").strip().rstrip("/")
    probe_url = f"{base}/"
    try:
        req = urllib.request.Request(probe_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            response.read()
        return True
    except Exception as exc:  # noqa: BLE001 — probe is best-effort, never fatal
        logger.warning("agent endpoint heartbeat probe failed (%s): %s", probe_url, exc)
        return False


def _chat_completions_url(api_base: str) -> str:
    """The chat-completions endpoint for ``api_base``.

    ``api_base`` is normally a *base* (``.../v1``) and the path is appended. A
    caller that pastes the full endpoint (``.../v1/chat/completions``) is
    tolerated: the tail is stripped first so the path is never doubled.
    """
    base = str(api_base or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/chat/completions"


def make_transport(config: AgentConfig) -> Transport:
    """A stdlib-only OpenAI-compatible chat transport for ``config.api_base``.

    Reads the API key from ``os.environ[config.api_key_env]`` and raises a clear
    :class:`RuntimeError` when it is absent *and* on every call, so a missing key
    is reported before any bytes go on the wire. A **blank** ``api_key_env`` means
    a *keyless* endpoint (a local proxy that injects its own credential, e.g.
    ``LLM_PROVIDER=local``): no key is read, none is required, and no
    ``Authorization`` header is sent. Deliberately stdlib-only
    (``urllib.request``): the live path is the one impure edge and it must not pull
    a third-party HTTP client into the import graph. Only call this in live mode.

    A ``429``/``503`` is retried (bounded, honouring ``Retry-After``): see
    :data:`TRANSPORT_MAX_RETRIES` for why a multi-round vision turn needs the token
    window to roll over between rounds. A ``429`` that names a **daily** quota
    (:func:`_is_daily_quota`) is *not* retried — no short wait clears it.
    """
    import urllib.error
    import urllib.request

    url = _chat_completions_url(config.api_base)
    key_env = str(config.api_key_env or "").strip()
    timeout_s = float(config.http_timeout_s or 120.0)
    # The UA is normalised in exactly one place (_request_headers): a blank or
    # whitespace setting falls back to DEFAULT_USER_AGENT there, so a test can
    # prove it via the built request without any network call.
    user_agent = str(getattr(config, "http_user_agent", "") or "")

    def _key() -> str:
        if not key_env:
            return ""  # keyless endpoint: no Authorization header
        key = os.environ.get(key_env)
        if not key or not key.strip():
            raise RuntimeError(
                f"agent live mode needs the {key_env} environment variable set "
                f"(AGENT_API_KEY_ENV); refusing to POST {url} without a key. "
                f"For a keyless endpoint, blank AGENT_API_KEY_ENV / api_key_env."
            )
        return key

    _key()  # fail fast at construction, before any turn can be attempted

    def _transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        # Heartbeat probe: surface a dead endpoint quickly without burning a
        # full model-turn timeout. Non-fatal — the actual call below is covered
        # by connect retry regardless of probe outcome.
        _probe_endpoint(config.api_base, timeout_s=min(timeout_s, 10.0))

        api_key = _key()
        body = json.dumps(payload).encode("utf-8")

        connect_attempts = 0
        while True:
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers=_request_headers(api_key, user_agent),
            )
            attempts = 0
            while True:
                try:
                    with urllib.request.urlopen(request, timeout=timeout_s) as response:
                        raw = response.read().decode("utf-8")
                    return json.loads(raw)
                except urllib.error.HTTPError as exc:
                    detail = ""
                    try:
                        detail = exc.read().decode("utf-8", "replace")
                    except (OSError, AttributeError, ValueError):
                        pass
                    if (
                        exc.code in _RETRYABLE_STATUS
                        and attempts < TRANSPORT_MAX_RETRIES
                        and not _is_daily_quota(detail)
                    ):
                        attempts += 1
                        wait = _retry_after_seconds(exc.headers, detail)
                        logger.info(
                            "agent transport HTTP %s; retry %d/%d in %.1fs",
                            exc.code, attempts, TRANSPORT_MAX_RETRIES, wait,
                        )
                        time.sleep(wait)
                        continue
                    raise RuntimeError(
                        f"agent transport HTTP {exc.code}: {detail[:400]}"
                    ) from exc
                except urllib.error.URLError as exc:  # pragma: no cover — live only
                    connect_attempts += 1
                    if connect_attempts > TRANSPORT_CONNECT_RETRIES:
                        raise RuntimeError(
                            f"agent transport connect failed after {connect_attempts} retries: {exc.reason}"
                        ) from exc
                    wait = min(
                        TRANSPORT_CONNECT_BACKOFF_S * (2.0 ** (connect_attempts - 1)),
                        TRANSPORT_RETRY_CAP_S,
                    )
                    logger.info(
                        "agent transport connect error; retry %d/%d in %.1fs",
                        connect_attempts, TRANSPORT_CONNECT_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue

    return _transport


def _mock_script(config: AgentConfig) -> List[AgentReply]:
    """The deterministic, zero-spend script a mock turn replays.

    Follow the same two-timeframe perception, render, liquidity lookup and
    watch-or-proposal workflow as live strategy turns, then write the thesis.
    :func:`_mock_agent` replays this zero-spend sequence once per turn.
    """
    timeframe = str(config.timeframe or "M15")
    context_timeframe = "H4" if timeframe == "H1" else "H1"
    round_one = AgentReply(tool_calls=[ToolCall(
        call_id="mock-set-view",
        name="set_view",
        arguments={
            "layout": "split",
            "panes": [context_timeframe, timeframe],
            "families": ["liquidity", "bos", "ob"],
            "bars": min(180, max(20, int(config.bars or 50))),
        },
    )])
    round_two = AgentReply(tool_calls=[ToolCall(call_id="mock-render", name="render")])
    round_three = AgentReply(tool_calls=[ToolCall(
        call_id="mock-liquidity-lookup", name="level_lookup", arguments={"family": "liquidity"}
    )])
    round_four = AgentReply(tool_calls=[ToolCall(
        call_id="mock-add-watch",
        name="add_watch",
        arguments={
            "condition": "bos_forms",
            "params": {"timeframe": timeframe, "direction": "bullish"},
            "ttl_hours": 12.0,
            "reason": "wait for structure confirmation before proposing a trade",
        },
    )])
    round_five = AgentReply(
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
    return [round_one, round_two, round_three, round_four, round_five]


def _mock_agent(config: AgentConfig) -> ScriptedAgent:
    """A ``ScriptedAgent`` that replays the mock script on *every* turn.

    ``ScriptedAgent`` consumes a plain list once, so only the very first turn
    would have content and every later turn would fall silent. Driving it from a
    callable that resets the round counter whenever ``request.turn_id`` changes
    makes each turn yield the same five-round workflow — consecutive mock turns
    are identical, and still zero-spend.
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
        # The strategy is loaded once, here: a service cannot exist without its
        # playbook, so a bad file raises *now* (loud) instead of silently running
        # a contract with no strategy text. The prompt is frozen per boot —
        # changing STRATEGY_ACTIVE takes effect on the next build.
        directory, name = config.resolve_strategy()
        self._strategy = load_strategy(directory, name)
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
        self._activity_lock = threading.Lock()
        self._activity_seq = 0
        self._activity_events = deque(maxlen=500)

    def emit_activity(self, event: str, payload: Dict[str, Any]) -> None:
        """Append one bounded, JSON-safe event for the panel's SSE feed."""
        item_payload = json.loads(json.dumps(payload or {}, default=str))
        with self._activity_lock:
            self._activity_seq += 1
            self._activity_events.append({
                "id": self._activity_seq,
                "type": str(event),
                "at": as_aware(self._clock()).isoformat(),
                "data": item_payload,
            })

    def activity_events_after(self, event_id: int = 0) -> List[Dict[str, Any]]:
        """Return buffered events newer than an SSE cursor."""
        with self._activity_lock:
            return [dict(item) for item in self._activity_events if item["id"] > int(event_id)]

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
            store.set_leash_limits(_settings_turn_limits)
            self._store = store
        return self._store

    def load(self) -> ContextStore:
        """Explicitly (re)load the store for this symbol."""
        self._store = ContextStore.load_or_new(
            self.config.symbol, state_dir=self.config.state_dir, clock=self._clock
        )
        self._store.set_leash_limits(_settings_turn_limits)
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
            playbook=self._strategy.text,
            activity=self.emit_activity,
            leash=_settings_leash,
            families=_settings_families,
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
        """How long ``stop`` waits for a thread: a worst-case turn plus a poll margin.

        One model call can block for ``http_timeout_s`` *and*, on a throttled turn,
        sleep up to ``TRANSPORT_MAX_RETRIES * TRANSPORT_RETRY_CAP_S`` between
        retries (the transport retries a 429/503 in-place). The budget must cover
        that ceiling, or a ``stop()``/``disable()`` during a throttled turn gives up
        too early and leaves the service *draining*.
        """
        per_call = max(1.0, float(self.config.http_timeout_s)) + (
            TRANSPORT_MAX_RETRIES * TRANSPORT_RETRY_CAP_S
        )
        rounds = _settings_leash().get("rounds", MAX_TOOL_ROUNDS)
        return per_call * (rounds + 1) + max(1.0, float(self.config.poll_s))

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
                self.emit_activity("turn_failed", {"trigger": "boot", "reason": str(exc)})
                return None
            self._remember_render(outcome)
            if outcome is not None:
                self.emit_activity("turn_finished", self._turn_finished_payload(outcome))
            self._resolve_orders("boot")
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
                self.emit_activity("turn_failed", {"trigger": "fire", "reason": str(exc)})
                return None
            self._remember_render(outcome)
            self.emit_activity("turn_finished", self._turn_finished_payload(outcome))
            self._resolve_orders("scan")
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
                outcome = TurnOutcome(trigger="request", ok=False, reason=str(exc))
            self._remember_render(outcome)
            self.emit_activity("turn_finished", self._turn_finished_payload(outcome))
            self._resolve_orders("request")
        return outcome

    def chat_turn(self, message: str, emit: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """A free-form chat turn: the human asks, the agent answers using tools.

        Same prompt, same tools as the autonomous agent — no order tool, no
        forced workflow. Returns the assistant's text response plus any tool
        calls and renders so a chat UI can show a straight conversation.

        ``emit`` (optional) receives live progress events from the loop
        (``turn_started``/``model_call_started``/``model_response``/
        ``tool_call``/``tool_result``/``chat_render``) while the turn runs.
        """
        with self._turn_lock:
            try:
                result = self._loop().chat_turn(
                    str(message or "").strip(), activity=emit,
                )
            except Exception as exc:  # noqa: BLE001 — report, never raise out
                self._record_failure("chat_turn", exc)
                return {
                    "ok": False,
                    "reason": str(exc),
                    "response": "",
                    "turn_id": "",
                    "render_id": "",
                    "tool_calls": [],
                    "renders": 0,
                    "image_path": "",
                    "manifest": {},
                    "output": {},
                }
            self._remember_render_from_chat(result)
            self.emit_activity(
                "chat_turn_finished",
                {
                    "turn_id": result.turn_id,
                    "ok": result.ok,
                    "reason": result.reason,
                    "renders": result.renders,
                    "tool_calls": len(result.tool_calls),
                },
            )
            return {
                "ok": result.ok,
                "reason": result.reason,
                "response": result.response,
                "turn_id": result.turn_id,
                "render_id": (result.manifest or {}).get("render_id", ""),
                "tool_calls": list(result.tool_calls or []),
                "renders": result.renders,
                "image_path": result.image_path,
                "manifest": dict(result.manifest or {}),
                "output": dict(result.output or {}),
            }

    def chat_stream(self, message: str):
        """Yield ``(event, payload)`` pairs for one chat turn, live.

        The turn runs on a daemon thread (it can take a minute or more at a
        slow provider); loop progress events — ``turn_started``,
        ``model_call_started``, ``model_response``, ``tool_call``,
        ``tool_result``, ``chat_render`` — arrive as they happen, and the
        stream ends with a ``done`` event carrying the full chat payload
        (response text, tool log, render id) — or an ``error`` event when the
        turn itself raised. Server-Sent Events wire format is applied in
        ``server.py``; this generator deals in domain events only.
        """
        import queue as _queue
        import threading as _threading

        q: _queue.Queue = _queue.Queue()

        def emit(event: str, data: Optional[Dict[str, Any]] = None) -> None:
            try:
                q.put((str(event), dict(data or {})))
            except Exception:  # noqa: BLE001 — an SSE hiccup must not kill the turn
                pass

        def run() -> None:
            try:
                emit("start", {"message": str(message or ""), "mode": str(self.config.mode)})
                result = self.chat_turn(message, emit=emit)
                emit("done", result)
            except Exception as exc:  # noqa: BLE001 — every stream must end
                self._record_failure("chat_stream", exc)
                emit("done", {
                    "ok": False, "reason": str(exc) or "chat failed",
                    "response": "", "turn_id": "", "render_id": "",
                    "tool_calls": [], "renders": 0, "image_path": "",
                    "manifest": {}, "output": {},
                })
            q.put(None)  # sentinel: stream over

        worker = _threading.Thread(target=run, name="agent-chat-turn", daemon=True)
        worker.start()
        while True:
            item = q.get()
            if item is None:
                return
            yield item

    def _remember_render_from_chat(self, result: ChatTurnResult) -> None:
        """Cache the last chat render so the panel can serve it."""
        if result.image_path and result.manifest:
            self._last_render = {
                "render_id": result.manifest.get("render_id", ""),
                "image_path": result.image_path,
                "manifest": dict(result.manifest or {}),
            }

    def _resolve_orders(self, source: str) -> None:
        """Execute fresh proposals (``AGENT_EXECUTE_TRADES``) and feed the panel.

        Never raises: a broken terminal is a booked proposal error, and a fault
        outside the executor lands in the failures log like every other piece
        of the runtime.
        """
        try:
            outcomes = self._sync_proposal_orders()
        except Exception as exc:  # noqa: BLE001
            self._record_failure("orders", exc)
            return
        if not outcomes:
            return
        self.emit_activity(
            "proposal_orders",
            {"source": source, "orders": outcomes},
        )

    def _turn_finished_payload(self, outcome: TurnOutcome) -> Dict[str, Any]:
        """Send a compact, useful outcome summary to the live panel feed."""
        record = next(
            (turn for turn in reversed(self.store.data.turns) if turn.id == outcome.turn_id),
            None,
        ) if outcome.turn_id else None
        calls = list(getattr(record, "tool_calls", []) or [])
        names = [str((entry.get("call") or {}).get("name") or "") for entry in calls]
        output = dict(outcome.output or {})
        proposals = len(output.get("proposals") or [])
        proposals += names.count("propose_trade")
        return {
            "trigger": outcome.trigger,
            "turn_id": outcome.turn_id,
            "ok": outcome.ok,
            "reason": outcome.reason,
            "tool_calls": outcome.tool_calls,
            "analysis_status": output.get("analysis_status", "complete" if outcome.ok else "incomplete"),
            "proposals": proposals,
            "pins": names.count("add_pin"),
            "watches": names.count("add_watch"),
            "workflow_missing": list(output.get("workflow_missing") or []),
        }

    # ------------------------------------------------------------------ execution

    def _proposal_plan(self, proposal: Proposal) -> tuple:
        """The dedupe key of a proposal: the levels a re-proposed plan repeats."""
        return (
            proposal.bias,
            round(float(proposal.entry or 0.0), 1),
            round(float(proposal.sl or 0.0), 1),
            round(float(proposal.tp or 0.0), 1),
        )

    def _sync_proposal_orders(self) -> List[Dict[str, Any]]:
        """Execute fresh proposals as real MT5 orders. Called after every turn.

        Runs under the turn lock. The settings are re-read on **every** call, so
        flipping ``AGENT_EXECUTE_TRADES``, changing ``AGENT_FIXED_LOT`` or the
        cap in ``config/settings.py`` applies from the next proposal with no
        restart. Mock mode never places orders (a scripted agent's ideas are
        not trades). Every outcome — placed, refused, duplicate — is booked on
        the proposal itself and reported back for the activity feed.
        """
        from config import settings as live

        if not bool(getattr(live, "AGENT_EXECUTE_TRADES", False)):
            return []
        mode = str(getattr(live, "AGENT_MODE", "") or "").lower()
        if mode != "live":
            return []
        fixed_lot = float(getattr(live, "AGENT_FIXED_LOT", 0.01) or 0.01)
        magic = int(getattr(live, "AGENT_ORDER_MAGIC", 999777))
        style = str(getattr(live, "AGENT_ORDER_STYLE", "auto") or "auto").lower()
        max_open = max(1, int(getattr(live, "AGENT_MAX_OPEN_ORDERS", 2)))

        data = self.store.data
        executed_keys = {
            self._proposal_plan(p)
            for p in data.proposals
            if p.executed
        }
        # A slot stays busy while its proposal is "working": placed within the
        # last day. Proposal statuses never flip on their own, so this time
        # window (not a status) keeps the cap from wedging after old trades hit.
        cutoff = as_aware(self._clock()) - timedelta(hours=24)
        open_orders = sum(
            1 for p in data.proposals
            if p.executed and not p.execution_error
            and (p.created_at is None or as_aware(p.created_at) >= cutoff)
        )
        outcomes: List[Dict[str, Any]] = []
        for proposal in list(data.proposals):
            if proposal.executed or proposal.status is not ProposalStatus.PROPOSED:
                continue
            try:
                # duplicate? a re-proposed plan whose entry/SL/TP already live in
                # the terminal is noted, never re-placed
                plan = self._proposal_plan(proposal)
                if plan in executed_keys:
                    self.store.record_proposal_execution(
                        proposal.id, ok=False,
                        error="duplicate_plan: the same entry/sl/tp already or previously placed",
                    )
                    outcomes.append({"proposal_id": proposal.id, "success": False,
                                     "comment": "duplicate_plan"})
                    continue
                if open_orders >= max_open:
                    self.store.record_proposal_execution(
                        proposal.id, ok=False,
                        error=f"open_orders_cap: {open_orders} pending agent order(s), cap {max_open}",
                    )
                    outcomes.append({"proposal_id": proposal.id, "success": False,
                                     "comment": "open_orders_cap"})
                    continue
                result = execute_proposal(
                    proposal,
                    symbol=self.config.symbol,
                    fixed_lot=fixed_lot,
                    magic=magic,
                    style=style,
                )
            except Exception as exc:  # noqa: BLE001 — an MT5 fault must never kill the turn bookkeeping
                result = {"success": False, "comment": f"execution_error: {exc}"}
            if result.get("success"):
                self.store.record_proposal_execution(
                    proposal.id, ok=True, ticket=int(result.get("ticket") or 0)
                )
                executed_keys.add(plan)
                open_orders += 1
            else:
                self.store.record_proposal_execution(
                    proposal.id, ok=False,
                    error=str(result.get("comment") or "order not placed"),
                )
            outcomes.append({"proposal_id": proposal.id, **result})
        return outcomes

    def reset_context(self) -> Dict[str, Any]:
        """Clear analysis memory while preserving the operator's view and leash.

        Serialize with turns so a model response cannot repopulate the context
        immediately after the reset. Replacing the watchdog also drops pending
        coalesced fires from subscriptions that no longer exist.
        """
        with self._turn_lock:
            store = self.store
            store.data.subscriptions.clear()
            store.data.thesis = Thesis()
            store.data.turns.clear()
            store.data.proposals.clear()
            store.data.agent.last_evaluated_at = None
            store.save()
            self._watchdog_obj = Watchdog(self._feed, clock=self._clock)
            self._last_render = {}
            return {
                "ok": True,
                "cleared": ["thesis", "subscriptions", "proposals", "turn_history", "last_render"],
                "status": self.status(),
            }

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
            "strategy_name": str(self._strategy.name),
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
            "strategy_name": str(self._strategy.name),
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

    def chat_turns(self, limit: int = DEFAULT_TURNS_LIMIT) -> List[dict]:
        """The chat conversation for the chat panel, newest first.

        Only ``request`` turns recorded *after* the operator's last "clear
        context" (``agent.chat_cleared_at``). The turn log is append-only
        audit and is never deleted — but a cleared conversation must not come
        back, neither in the UI nor in the agent's briefing memory
        (``prompts.chat_history_rows`` applies the same marker).
        """
        cleared_raw = getattr(self.store.data.agent, "chat_cleared_at", None)
        cleared = as_aware(cleared_raw) if cleared_raw is not None else None
        kept = []
        for turn in list(self.store.data.turns):
            trigger = getattr(turn, "trigger", "")
            trigger = trigger.value if hasattr(trigger, "value") else str(trigger)
            if trigger != "request":
                continue
            if cleared is not None:
                started = getattr(turn, "started_at", None)
                if started is None or as_aware(started) <= cleared:
                    continue
            kept.append(turn)
        if limit and limit > 0:
            kept = kept[-int(limit):]
        return [self._turn_row(turn) for turn in reversed(kept)]

    def chat_clear(self) -> Dict[str, Any]:
        """Clear the chat conversation — the chat panel's "clear context".

        The turn log is append-only audit and is never touched; instead the
        store's ``agent.chat_cleared_at`` marker moves to now. Both readers of
        the conversation — ``chat_turns`` (the panel's history) and
        ``chat_history_rows`` (the briefing's chat memory) — only see turns
        after the marker, so the UI *and* the agent's memory start fresh, and
        the marker persists across restarts.
        """
        store = self.store
        store.data.agent.chat_cleared_at = as_aware(self._clock())
        store.save()
        return {
            "ok": True,
            "cleared_at": store.data.agent.chat_cleared_at.isoformat(),
        }

    def _turn_row(self, turn: Any) -> Dict[str, Any]:
        """One turn record -> the row the panel and chat history show."""
        conclusion = turn_conclusion(turn)
        calls = list(getattr(turn, "tool_calls", []) or [])
        output = dict(getattr(turn, "output", {}) or {})
        thesis = output.get("thesis") if isinstance(output.get("thesis"), dict) else {}
        refused = sum(
            1 for entry in calls
            if not ((entry or {}).get("result") or {}).get("ok", True)
        )
        return {
            "id": conclusion["turn_id"],
            "trigger": conclusion["trigger"],
            "started_at": conclusion["at"],
            "output": output,
            "summary": conclusion["conclusion"],
            # what the model actually did (the dashboard shows real
            # activity; the full call log stays in the state file)
            "calls": len(calls),
            "refused": refused,
            "renders": int(getattr(turn, "renders", 0) or 0),
            "tokens": int(getattr(turn, "tokens", 0) or 0),
            "cost_usd": float(getattr(turn, "cost_usd", 0.0) or 0.0),
            "first_call": (
                ((calls[0] or {}).get("call") or {}).get("name", "") if calls else ""
            ),
            "thesis_bias": thesis.get("bias", ""),
            # Durable chat fields: the UI rebuilds the conversation
            # after a server restart from exactly these — the operator's
            # message, the agent's chat wording, and the render id of
            # the chart the turn drew.
            "message": str(getattr(turn, "trigger_detail", "") or ""),
            "chat_response": str(output.get("chat_response") or ""),
            "render_id": str(output.get("render_id") or ""),
        }

    def _turn_rows(self, limit: int) -> List[Dict[str, Any]]:
        turns = list(self.store.data.turns)
        if limit and limit > 0:
            turns = turns[-int(limit):]
        return [self._turn_row(turn) for turn in reversed(turns)]

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
