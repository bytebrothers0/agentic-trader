"""Tests for wiring propose_trade to real MT5 execution.

Everything round-trips in-memory: the order-type selector is pure, and the
service's sync runs against a monkeypatched ``execute_proposal`` — no terminal
touched. The knobs (``AGENT_EXECUTE_TRADES``, ``AGENT_FIXED_LOT``…) are read
live per sync, so these tests retune them like the user would.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "test_agentic"))

from _fixtures import (  # noqa: E402
    FakeClock,
    FakeRenderer,
    FeedStub,
    at,
    bars_rows,
)

import agent_service  # noqa: E402
from agent_service import AgentService  # noqa: E402
from execution import agent_orders  # noqa: E402
from execution.agent_orders import (  # noqa: E402
    select_order_type,
    validate_proposal,
)
from agentic.models import Proposal, ProposalStatus  # noqa: E402


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

def _service(tmp_path, clock: FakeClock) -> AgentService:
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_candles(bars_rows(), timeframe="M15")
    config = agent_service.AgentConfig(
        symbol="XAUUSDm",
        timeframe="M15",
        bars=50,
        mode="mock",
        model="gpt-4o-mini",
        poll_s=3600.0,
        state_dir=str(tmp_path / "state"),
        out_dir=str(tmp_path / "renders"),
    )
    service = AgentService(
        config,
        feed=stub.build(),
        renderer=FakeRenderer(out_dir=config.out_dir, clock=clock),
        clock=clock,
        client=agent_service.ScriptedAgent([]),
    )
    return service


_FRESH = dict(bias="bullish", entry=4150.0, sl=4140.0, tp=4180.0)


@pytest.fixture()
def live_dispatch(monkeypatch):
    """The shipped settings as the user runs them: live mode, execute on."""
    import config.settings as settings

    monkeypatch.setattr(settings, "AGENT_MODE", "live", raising=False)
    monkeypatch.setattr(settings, "AGENT_EXECUTE_TRADES", True, raising=False)
    monkeypatch.setattr(settings, "AGENT_FIXED_LOT", 0.01, raising=False)
    monkeypatch.setattr(settings, "AGENT_MAX_OPEN_ORDERS", 2, raising=False)
    return settings


@pytest.fixture()
def placed(monkeypatch):
    """Execute_proposal stub: always succeeds with a fresh ticket; records calls."""
    calls = []

    def fake(proposal, *, symbol, fixed_lot, magic, style="auto"):
        calls.append({
            "proposal": proposal,
            "symbol": symbol,
            "fixed_lot": fixed_lot,
            "magic": magic,
            "style": style,
        })
        return {
            "success": True,
            "ticket": 1000 + len(calls),
            "order_type": "buy_limit" if proposal.bias == "bullish" else "sell_limit",
            "price": float(proposal.entry),
            "sl": float(proposal.sl),
            "tp": float(proposal.tp),
            "lots": fixed_lot,
        }

    monkeypatch.setattr(agent_service, "execute_proposal", fake)
    return calls


# --------------------------------------------------------------------------- #
# The pure layer
# --------------------------------------------------------------------------- #

def test_a_proposal_must_be_actionable():
    good = Proposal(id="p1", bias="bullish", entry=4150.0, sl=4140.0, tp=4180.0)
    assert validate_proposal(good) is None
    assert validate_proposal(Proposal(id="p2", bias="none")) == \
        "bad_bias: execute only bullish/bearish proposals"
    assert validate_proposal(Proposal(id="p3", bias="bearish", entry=4150.0)) == \
        "missing_sl: a proposal needs entry, sl and tp"
    assert validate_proposal(Proposal(id="p4", bias="bullish", entry=4150.0, sl=4160.0, tp=4180.0)) == \
        "crossed_levels: bullish needs sl < entry < tp"
    assert validate_proposal(Proposal(id="p5", bias="bearish", entry=4150.0, sl=4140.0, tp=4180.0)) == \
        "crossed_levels: bearish needs tp < entry < sl"


def test_the_entry_rests_on_the_right_side_of_the_market():
    # beyond the market: breakout entries are stop orders
    assert select_order_type("bullish", 4160.0, bid=4157.0, ask=4157.2) == "buy_stop"
    assert select_order_type("bearish", 4155.0, bid=4157.0, ask=4157.2) == "sell_stop"
    # behind the market: retracement entries are limit orders
    assert select_order_type("bullish", 4150.0, bid=4157.0, ask=4157.2) == "buy_limit"
    assert select_order_type("bearish", 4160.0, bid=4157.0, ask=4157.2) == "sell_limit"


# --------------------------------------------------------------------------- #
# The service sync
# --------------------------------------------------------------------------- #

def test_a_fresh_proposal_becomes_a_real_order(tmp_path, live_dispatch, placed):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    proposal = service.store.add_proposal(setup="crt continuation", **_FRESH)

    service._resolve_orders("request")

    assert len(placed) == 1
    call = placed[0]
    assert call["symbol"] == "XAUUSDm"
    assert call["fixed_lot"] == 0.01          # the fixed lot, not risk sizing
    assert call["proposal"].id == proposal.id

    stored = service.store.data.proposals[0]
    assert stored.executed and stored.order_ticket == 1001
    assert stored.execution_error == ""
    # the placement is visible on the panel's activity feed
    events = [e for e in service.activity_events_after() if e["type"] == "proposal_orders"]
    assert events and events[-1]["data"]["orders"][0]["ticket"] == 1001


def test_a_reproposed_plan_is_a_duplicate_never_a_second_order(tmp_path, live_dispatch, placed):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)
    service._resolve_orders("request")
    service.store.add_proposal(setup="crt continuation", **_FRESH)  # the next turn re-proposes

    service._resolve_orders("scan")

    assert len(placed) == 1                   # no second order sent
    duplicate = service.store.data.proposals[-1]
    assert not duplicate.executed
    assert "duplicate_plan" in duplicate.execution_error


def test_the_open_orders_cap_leaves_the_rest_unplaced(tmp_path, live_dispatch, placed):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="plan A", bias="bullish", entry=4150.0, sl=4140.0, tp=4180.0)
    service.store.add_proposal(setup="plan B", bias="bullish", entry=4160.0, sl=4150.0, tp=4190.0)
    service.store.add_proposal(setup="plan C", bias="bearish", entry=4170.0, sl=4180.0, tp=4140.0)

    service._resolve_orders("request")

    assert len(placed) == 2                   # cap AGENT_MAX_OPEN_ORDERS = 2
    capped = service.store.data.proposals[2]
    assert not capped.executed
    assert "open_orders_cap" in capped.execution_error


def test_a_refused_order_is_booked_and_retried_next_turn(tmp_path, live_dispatch, monkeypatch):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)
    attempts = []

    def refused(proposal, **kwargs):
        attempts.append(proposal.id)
        return {"success": False, "comment": "order_send failed: invalid stops"}

    monkeypatch.setattr(agent_service, "execute_proposal", refused)

    service._resolve_orders("request")
    stored = service.store.data.proposals[0]
    assert not stored.executed and stored.order_ticket == 0
    assert "invalid stops" in stored.execution_error

    service._resolve_orders("request")        # the next turn tries again
    assert len(attempts) == 2                 # unmarked, so still retried


def test_propose_only_when_the_switch_is_off(tmp_path, live_dispatch, placed, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "AGENT_EXECUTE_TRADES", False, raising=False)
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)

    service._resolve_orders("request")

    assert placed == []                       # no terminal touch
    stored = service.store.data.proposals[0]
    assert not stored.executed and stored.execution_error == ""


def test_mock_mode_never_places_orders(tmp_path, placed, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "AGENT_MODE", "mock", raising=False)
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)

    service._resolve_orders("request")

    assert placed == []                       # a scripted agent's ideas are not trades


def test_a_refused_order_reaches_the_next_briefing(tmp_path, live_dispatch, monkeypatch):
    """The model *sees* the broker's refusal and gets a chance to adapt.

    The retry is the service's job (an unmarked proposal is re-attempted every
    turn), but a blind retry of a doomed price is waste — so `build_briefing`
    reads the execution outcome back as the `orders` digest: refusal reason
    attached. Safe feedback, or the model would never learn.
    """
    from agentic import prompts as agent_prompts

    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)

    def refused(proposal, **kwargs):
        return {"success": False, "comment": "order_send failed: invalid stops"}

    monkeypatch.setattr(agent_service, "execute_proposal", refused)
    service._resolve_orders("request")

    briefing = agent_prompts.build_briefing(
        service.store, trigger="request", now=at(6, 0)
    )
    row = briefing["orders"][0]
    assert row["setup"] == "crt continuation"
    assert row["entry"] == 4150.0 and row["sl"] == 4140.0 and row["tp"] == 4180.0
    assert "invalid stops" in row["execution"] and row["execution"].startswith("NOT placed")


def test_an_executed_order_shows_its_ticket_in_the_briefing(tmp_path, live_dispatch, placed):
    from agentic import prompts as agent_prompts

    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    service.store.add_proposal(setup="crt continuation", **_FRESH)
    service._resolve_orders("request")

    briefing = agent_prompts.build_briefing(
        service.store, trigger="scan", now=at(6, 0)
    )
    row = briefing["orders"][0]
    assert "ticket 1001" in row["execution"]


def test_execution_state_round_trips_through_the_store(tmp_path, live_dispatch, placed):
    clock = FakeClock(at(6, 0))
    service = _service(tmp_path, clock)
    proposal = service.store.add_proposal(setup="crt continuation", **_FRESH)
    service._resolve_orders("request")
    service.store.save()

    fresh = service.load()
    stored = fresh.data.proposals[0]
    assert stored.id == proposal.id
    assert stored.executed and stored.order_ticket == 1001
