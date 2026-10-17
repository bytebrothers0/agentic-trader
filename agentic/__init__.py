"""Agentic chart agent — self-directed perception, pins and watches.

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md

This package is deliberately **standalone and unwired**: nothing in it is imported
by ``server.py``, the indicator suite, the web front-end, or the legacy
``ai_agent`` package. It is built in isolation so it can be developed and tested
in parallel with indicator work, and so that wiring it up later is a one-file
adapter rather than a refactor.

Phase 0 (this code): schemas + the durable context store.

The store is the state of record. It holds *intent* (what the agent wants to look
at) and *agent metadata* (what it pinned, what it is waiting for, what it thinks)
— never detector output. Levels are recomputed by the feed on every render, so a
bug in here can never change a level's price.
"""
from __future__ import annotations

from agentic.conditions import Condition, ConditionError, ConditionSpec, spec_for, validate
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
    "ContextStore",
    "Layout",
    "LeashExceeded",
    "LevelStatus",
    "Proposal",
    "ProposalStatus",
    "StoreError",
    "StoreState",
    "Subscription",
    "SubscriptionKind",
    "SubscriptionState",
    "Thesis",
    "Trigger",
    "TurnRecord",
    "View",
    "spec_for",
    "validate",
]
