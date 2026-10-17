"""Agentic chart agent — self-directed perception, pins and watches.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md

Phase 0: the schemas and the durable context store (``models`` + ``store``).
Phase 1: ``feed.py``, the read-only bridge to the indicator suite, and
``crt_strategy.py``, the top-down CRT playbook the agent runs (HTF bias from
D1/W1/MN1 CRT, LTF confirmation, a propose-only plan).
Phase 2 (part A): OHLC ``Bars`` on the feed, and ``subscriptions.py``, the
deterministic, edge-triggered condition evaluator the Watchdog will drive.
Phase 2 (part B): ``watchdog.py``, the LLM-free loop that drives the evaluator,
retires what fired and coalesces a burst of events into one turn.
Phase 3: ``lookup.py``, the numeric ground truth for anything the agent saw, and
``renderer.py``, the deterministic server-side PNG render plus its tag manifest.
Phase 4: ``tools.py`` (the tool surface, no order tool), ``prompts.py`` (the
system prompt and the per-turn briefing) and ``agent_loop.py`` (one turn: briefing
-> render -> LLM -> tools -> persist), with a zero-spend ``ScriptedAgent`` mock.

The pure core — ``models``, ``conditions``, ``store``, ``crt_strategy``,
``subscriptions``, ``watchdog``, ``lookup``, ``tools``, ``prompts``,
``agent_loop`` — imports nothing from the running system. ``feed`` is the single
sanctioned bridge, and it reaches the indicator layer only lazily, so importing
this package stays cheap. ``renderer`` is the one module that needs the vision
stack, and it imports ``matplotlib``/``PIL`` inside its functions so the package
import stays cheap too. Nothing here places an order (``mode=propose``
throughout), and nothing caches detector output in the store: levels are
recomputed on every read. The panel and the real vision model remain later phases.
"""
from __future__ import annotations

from agentic.conditions import Condition, ConditionError, ConditionSpec, spec_for, validate
from agentic.crt_strategy import (
    HTF_BIAS_TIMEFRAMES,
    LTF_EXECUTION_TIMEFRAMES,
    OPTIONAL_FAMILIES,
    REQUIRED_FAMILIES,
    Confirmation,
    CrtAnalysis,
    CrtPlan,
    HtfBias,
    analyze,
    build_plan,
    derive_htf_bias,
    find_confirmation,
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
    "Confirmation",
    "ContextStore",
    "CrtAnalysis",
    "CrtPlan",
    "FAMILY_INITIALS",
    "Feed",
    "FeedSnapshot",
    "FireResult",
    "HTF_BIAS_TIMEFRAMES",
    "HtfBias",
    "KNOWN_FAMILIES",
    "LTF_EXECUTION_TIMEFRAMES",
    "Layout",
    "LeashExceeded",
    "LevelRecord",
    "LevelStatus",
    "LookupRecord",
    "LookupResult",
    "OPTIONAL_FAMILIES",
    "PRICE_CHECK_S",
    "Proposal",
    "ProposalStatus",
    "REQUIRED_FAMILIES",
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
    "analyze",
    "bar_seconds",
    "build_plan",
    "default_candles_provider",
    "default_provider",
    "derive_htf_bias",
    "evaluate",
    "event_time",
    "family_of",
    "find_confirmation",
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
]
