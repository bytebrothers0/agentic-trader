"""Agentic chart agent — self-directed perception, pins and watches.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md

Phase 0: the schemas and the durable context store (``models`` + ``store``).
Phase 1: ``feed.py``, the read-only bridge to the indicator suite, and
``crt_strategy.py``, the top-down CRT playbook the agent runs (HTF bias from
D1/W1/MN1 CRT, LTF confirmation, a propose-only plan).

The pure core — ``models``, ``conditions``, ``store``, ``crt_strategy`` — imports
nothing from the running system. ``feed`` is the single sanctioned bridge, and it
reaches the indicator layer only lazily, so importing this package stays cheap.
Nothing here places an order (``mode=propose`` throughout), and nothing caches
detector output in the store: levels are recomputed on every read. The agent
loop, the renderer, the panel and the LLM remain later phases.
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
    Feed,
    FeedSnapshot,
    LevelRecord,
    default_provider,
    family_of,
    parse_level,
    parse_payload,
    status_of,
)
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
from agentic.store import (
    CapExceeded,
    ContextStore,
    LeashExceeded,
    StoreError,
)

__all__ = [
    "SPEC_VERSION",
    "AgentMeta",
    "AgentMode",
    "Budget",
    "CapExceeded",
    "ChartType",
    "Condition",
    "ConditionError",
    "ConditionSpec",
    "Confirmation",
    "ContextStore",
    "CrtAnalysis",
    "CrtPlan",
    "Feed",
    "FeedSnapshot",
    "HTF_BIAS_TIMEFRAMES",
    "HtfBias",
    "KNOWN_FAMILIES",
    "LTF_EXECUTION_TIMEFRAMES",
    "Layout",
    "LeashExceeded",
    "LevelRecord",
    "LevelStatus",
    "OPTIONAL_FAMILIES",
    "Proposal",
    "ProposalStatus",
    "REQUIRED_FAMILIES",
    "StoreError",
    "StoreState",
    "Subscription",
    "SubscriptionKind",
    "SubscriptionState",
    "Thesis",
    "Trigger",
    "TurnRecord",
    "View",
    "analyze",
    "build_plan",
    "default_provider",
    "derive_htf_bias",
    "family_of",
    "find_confirmation",
    "parse_level",
    "parse_payload",
    "spec_for",
    "status_of",
    "validate",
]
