"""Agentic chart agent — self-directed perception, pins and watches.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md

Phase 0: the schemas and the durable context store (``models`` + ``store``).
Phase 1: ``feed.py``, the read-only bridge to the indicator suite, and
``strategy.py``, the strategy-file loader — the agent's playbook is an
operator-owned markdown file (``strategies/<active>.md``), not hard-coded
policy.
Phase 2 (part A): OHLC ``Bars`` on the feed, and ``subscriptions.py``, the
deterministic, edge-triggered condition evaluator the Watchdog will drive.
Phase 2 (part B): ``watchdog.py``, the LLM-free loop that drives the evaluator,
retires what fired and coalesces a burst of events into one turn.
Phase 3: ``lookup.py``, the numeric ground truth for anything the agent saw, and
``renderer.py``, the deterministic server-side PNG render plus its tag manifest.
Phase 4: ``tools.py`` (the tool surface, no order tool), ``prompts.py`` (the
system prompt and the per-turn briefing) and ``agent_loop.py`` (one turn: briefing
-> render -> LLM -> tools -> persist), with a zero-spend ``ScriptedAgent`` mock.
Phase 5: ``llm.py``, the OpenAI-compatible vision client — the request builder and
a tolerant reply parser over an **injected transport**, so a live HTTP call is
wired by the caller and the pure core still touches no network.

The pure core — ``models``, ``conditions``, ``store``, ``strategy``,
``subscriptions``, ``watchdog``, ``lookup``, ``tools``, ``prompts``,
``agent_loop``, ``llm`` — imports nothing from the running system. ``feed`` is the single
sanctioned bridge, and it reaches the indicator layer only lazily, so importing
this package stays cheap. ``renderer`` is the one module that needs the vision
stack, and it imports ``matplotlib``/``PIL`` inside its functions so the package
import stays cheap too. Nothing here places an order (``mode=propose``
throughout), and nothing caches detector output in the store: levels are
recomputed on every read. The panel and the real vision model remain later phases.
"""
from __future__ import annotations

from agentic.conditions import Condition, ConditionError, ConditionSpec, spec_for, validate
from agentic.strategy import (
    MAX_STRATEGY_CHARS,
    Strategy,
    StrategyError,
    load_strategy,
)
from agentic.feed import (
    KNOWN_FAMILIES,
    Bars,
    Feed,
    FeedSnapshot,
    LevelRecord,
    default_candles_provider,
    default_provider,
    family_of,
    parse_candles,
    parse_level,
    parse_payload,
    status_of,
)
from agentic.lookup import LookupRecord, LookupResult, level_lookup
from agentic.models import (
    SPEC_VERSION,
    AgentMeta,
    AgentMode,
    Budget,
    ChartType,
    Layout,
    LevelStatus,
    Proposal,
    ProposalStatus,
    StoreState,
    Subscription,
    SubscriptionKind,
    SubscriptionState,
    Thesis,
    Trigger,
    TurnRecord,
    View,
)
from agentic.renderer import FAMILY_INITIALS, RenderResult, Renderer, TagEntry
from agentic.store import (
    CapExceeded,
    ContextStore,
    LeashExceeded,
    StoreError,
)
from agentic.subscriptions import FireResult, evaluate, event_time
from agentic.watchdog import (
    COALESCE_WINDOW_S,
    PRICE_CHECK_S,
    BackfillResult,
    ScanResult,
    TurnRequest,
    Watchdog,
    bar_seconds,
)
from agentic.prompts import (
    SYSTEM_PROMPT,
    build_briefing,
    build_system_prompt,
    render_briefing_text,
    subscription_summary,
)
from agentic.tools import (
    TOOL_NAMES,
    TOOL_SCHEMAS,
    ToolCall,
    ToolRegistry,
    ToolResult,
    render_current,
)
from agentic.agent_loop import (
    MAX_TOOL_ROUNDS,
    AgentClient,
    AgentLoop,
    AgentReply,
    AgentRequest,
    ScriptedAgent,
    TurnOutcome,
)
from agentic.llm import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    PRICES,
    ResponseError,
    Transport,
    VisionClient,
    build_messages,
    encode_image,
    estimate_cost,
    parse_reply,
    to_openai_tools,
)

__all__ = [
    "SPEC_VERSION",
    "AgentMeta",
    "AgentMode",
    "BackfillResult",
    "Bars",
    "Budget",
    "COALESCE_WINDOW_S",
    "CapExceeded",
    "ChartType",
    "Condition",
    "ConditionError",
    "ConditionSpec",
    "MAX_STRATEGY_CHARS",
    "Strategy",
    "StrategyError",
    "ContextStore",
    "FAMILY_INITIALS",
    "Feed",
    "FeedSnapshot",
    "FireResult",
    "KNOWN_FAMILIES",
    "Layout",
    "LeashExceeded",
    "LevelRecord",
    "LevelStatus",
    "LookupRecord",
    "LookupResult",
    "PRICE_CHECK_S",
    "Proposal",
    "ProposalStatus",
    "RenderResult",
    "Renderer",
    "ScanResult",
    "StoreError",
    "StoreState",
    "Subscription",
    "SubscriptionKind",
    "SubscriptionState",
    "TagEntry",
    "Thesis",
    "Trigger",
    "TurnRecord",
    "TurnRequest",
    "View",
    "Watchdog",
    "bar_seconds",
    "default_candles_provider",
    "default_provider",
    "evaluate",
    "event_time",
    "family_of",
    "level_lookup",
    "parse_candles",
    "parse_level",
    "parse_payload",
    "spec_for",
    "status_of",
    "validate",
    # phase 4
    "AgentClient",
    "AgentLoop",
    "AgentReply",
    "AgentRequest",
    "MAX_TOOL_ROUNDS",
    "SYSTEM_PROMPT",
    "ScriptedAgent",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "TurnOutcome",
    "build_briefing",
    "build_system_prompt",
    "render_current",
    "subscription_summary",
    # phase 5
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "PRICES",
    "ResponseError",
    "Transport",
    "VisionClient",
    "build_messages",
    "encode_image",
    "estimate_cost",
    "parse_reply",
    "render_briefing_text",
    "to_openai_tools",
]
