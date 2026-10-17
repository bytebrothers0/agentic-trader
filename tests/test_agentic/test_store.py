"""Tests for the durable context store (spec phase 0 acceptance criteria).

Round-trip, atomic persistence, caps, expiries, dedupe and the leash. Plus the
structural guard: the store holds intent and metadata, never detector output.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agentic import store as store_mod
from agentic.models import StoreState, SubscriptionKind, SubscriptionState
from agentic.store import (
    DEFAULT_STATE_DIR,
    CapExceeded,
    ContextStore,
    LeashExceeded,
    StoreError,
)

ROOT_FIELDS = {
    "version",
    "symbol",
    "created_at",
    "updated_at",
    "view",
    "subscriptions",
    "thesis",
    "turns",
    "proposals",
    "budget",
    "agent",
}


class FakeClock:
    def __init__(self, start: str = "2026-10-17T06:00:00+00:00"):
        self.now = datetime.fromisoformat(start)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> datetime:
        self.now = self.now + timedelta(**kw)
        return self.now


def _store(tmp_path=None, clock=None) -> ContextStore:
    state_dir = str(tmp_path) if tmp_path is not None else None
    return ContextStore("XAUUSDm", state_dir=state_dir, clock=clock or FakeClock())


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #

def test_round_trips_through_json(tmp_path):
    store = _store(tmp_path)
    store.set_view(timeframe="H2", bars=200)
    store.add_subscription("pin", params={"family": "fvg", "timeframe": "H2", "price": 4152.86})
    store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    store.set_thesis(bias="bullish", storyline="continuation", invalidation="below 4130")
    store.add_proposal(bias="bullish", entry=4152.0, sl=4140.0, tp=4180.0)
    store.record_turn("boot")

    raw = store.to_dict()
    assert json.loads(json.dumps(raw)) == raw  # every value is JSON-safe
    assert StoreState.from_dict(raw).to_dict() == raw


def test_saves_and_reloads_atomically(tmp_path):
    store = _store(tmp_path)
    store.set_view(timeframe="H2", bars=200)
    store.add_subscription("pin", params={"family": "fvg", "timeframe": "H2", "price": 4152.86})
    path = store.save()
    assert Path(path).name == "XAUUSDm.json"
    assert not Path(path + ".tmp").exists()

    again = ContextStore.load("XAUUSDm", state_dir=str(tmp_path))
    assert again.to_dict() == store.to_dict()


def test_load_or_new_starts_fresh_when_absent(tmp_path):
    fresh = ContextStore.load_or_new("XAUUSDm", state_dir=str(tmp_path))
    assert fresh.data.symbol == "XAUUSDm"
    assert fresh.data.subscriptions == []


def test_default_state_dir_is_inside_the_package():
    assert DEFAULT_STATE_DIR.endswith("state")
    assert Path(DEFAULT_STATE_DIR).parent.name == "agentic"


def test_store_holds_intent_not_detector_output(tmp_path):
    """Guard for P1: levels are recomputed by the feed, never stored here."""
    assert set(_store(tmp_path).to_dict()) == ROOT_FIELDS


def test_missing_symbol_is_rejected():
    with pytest.raises(StoreError) as exc:
        ContextStore("   ")
    assert exc.value.reason == "missing_symbol"


# --------------------------------------------------------------------------- #
# caps and expiries
# --------------------------------------------------------------------------- #

def test_pins_are_capped(tmp_path):
    store = _store(tmp_path)
    for i in range(store_mod.MAX_PINS):
        _, created = store.add_subscription(
            "pin", params={"family": "fvg", "timeframe": "H2", "price": 4000.0 + i, "tolerance": 0.5}
        )
        assert created
    with pytest.raises(CapExceeded) as exc:
        store.add_subscription("pin", params={"family": "fvg", "timeframe": "H2", "price": 9999.0})
    assert exc.value.reason == "max_pins"


def test_open_subscriptions_are_capped(tmp_path):
    store = _store(tmp_path)
    for i in range(store_mod.MAX_OPEN_SUBSCRIPTIONS):
        store.add_subscription("watch", "price_crosses", {"price": 4100.0 + i})
    with pytest.raises(CapExceeded) as exc:
        store.add_subscription("watch", "price_crosses", {"price": 9999.0})
    assert exc.value.reason == "max_open_subscriptions"


def test_released_subscriptions_free_a_slot(tmp_path):
    store = _store(tmp_path)
    for i in range(store_mod.MAX_OPEN_SUBSCRIPTIONS):
        store.add_subscription("watch", "price_crosses", {"price": 4100.0 + i})
    first = store.open_subscriptions()[0]
    store.release_subscription(first.id)
    sub, created = store.add_subscription("watch", "price_crosses", {"price": 9999.0})
    assert created and sub.state is SubscriptionState.ARMED


def test_every_subscription_gets_an_expiry(tmp_path):
    store = _store(tmp_path)
    pin, _ = store.add_subscription("pin", params={"family": "fvg", "timeframe": "H2", "price": 4152.86})
    assert pin.expires_at - pin.starts_at == timedelta(hours=store_mod.PIN_TTL_DEFAULT_HOURS)

    watch, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0}, ttl_hours=1.5)
    assert watch.expires_at - watch.starts_at == timedelta(hours=1.5)


def test_ttl_must_be_positive_and_within_cap(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(StoreError) as exc:
        store.add_subscription("watch", "price_crosses", {"price": 1.0}, ttl_hours=0)
    assert exc.value.reason == "invalid_ttl"

    with pytest.raises(StoreError) as exc:
        store.add_subscription(
            "watch", "price_crosses", {"price": 2.0}, ttl_hours=store_mod.WATCH_TTL_MAX_HOURS + 1
        )
    assert exc.value.reason == "ttl_beyond_max"


def test_duplicate_subscriptions_dedupe(tmp_path):
    store = _store(tmp_path)
    first, created = store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    second, created_again = store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert len(store.open_subscriptions()) == 1


def test_expire_due_retires_and_reports_once(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    watch, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0}, ttl_hours=1)

    clock.advance(hours=2)
    expired = store.expire_due()
    assert [s.id for s in expired] == [watch.id]
    assert store.get_subscription(watch.id).state is SubscriptionState.EXPIRED
    assert store.expire_due() == []


def test_expired_subscription_cannot_be_released(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    watch, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0}, ttl_hours=1)
    clock.advance(hours=2)
    store.expire_due()
    with pytest.raises(StoreError) as exc:
        store.release_subscription(watch.id)
    assert exc.value.reason == "not_releasable"


def test_one_shot_watch_retires_on_fire_but_repeating_stays_armed(tmp_path):
    store = _store(tmp_path)
    one_shot, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    store.mark_fired(one_shot.id)
    assert store.get_subscription(one_shot.id).state is SubscriptionState.FIRED

    repeating, _ = store.add_subscription("watch", "bos_forms", {"timeframe": "M15"}, one_shot=False)
    store.mark_fired(repeating.id)
    refreshed = store.get_subscription(repeating.id)
    assert refreshed.state is SubscriptionState.ARMED
    assert refreshed.fire_count == 1


def test_mark_evaluated_advances_the_window_for_armed_subs(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    created = clock()

    first, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    second, _ = store.add_subscription("watch", "price_crosses", {"price": 4161.0})
    assert first.last_evaluated_at == created

    clock.advance(minutes=5)
    store.mark_evaluated(second.id)  # a single id is accepted
    assert store.get_subscription(second.id).last_evaluated_at == clock()
    assert store.get_subscription(first.id).last_evaluated_at == created

    clock.advance(minutes=5)
    store.mark_evaluated([first.id, second.id])  # an iterable of ids
    assert store.get_subscription(first.id).last_evaluated_at == clock()
    assert store.get_subscription(second.id).last_evaluated_at == clock()

    store.mark_evaluated("sub_nope")  # unknown ids are ignored, not an error


def test_mark_evaluated_leaves_a_fired_subscription_alone(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    watch, _ = store.add_subscription("watch", "price_crosses", {"price": 4160.0})

    store.mark_fired(watch.id)
    fired_at = clock()
    clock.advance(hours=1)
    store.mark_evaluated(watch.id)

    marked = store.get_subscription(watch.id)
    assert marked.state is SubscriptionState.FIRED
    assert marked.last_evaluated_at == fired_at


def test_pin_starts_live_with_its_key(tmp_path):
    store = _store(tmp_path)
    key = "fvg:H2:bullish:4152.86:2026-10-16T14:00"
    pin, _ = store.add_subscription("pin", params={"level_key": key})
    assert pin.kind is SubscriptionKind.PIN
    assert pin.condition == "level_alive"
    assert pin.level_key == key
    assert pin.status.value == "live"


# --------------------------------------------------------------------------- #
# view
# --------------------------------------------------------------------------- #

def test_view_rejects_unknown_dials(tmp_path):
    with pytest.raises(StoreError) as exc:
        _store(tmp_path).set_view(colour="red")
    assert exc.value.reason == "unknown_view_field"


def test_view_validates_its_values(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(StoreError) as exc:
        store.set_view(timeframe="fifteen minutes")
    assert exc.value.reason == "invalid_timeframe"

    with pytest.raises(StoreError) as exc:
        store.set_view(layout="grid")
    assert exc.value.reason == "invalid_layout"

    with pytest.raises(StoreError) as exc:
        store.set_view(chart_type="heikin")
    assert exc.value.reason == "invalid_chart_type"

    with pytest.raises(StoreError) as exc:
        store.set_view(bars=5)
    assert exc.value.reason == "invalid_bars"


def test_view_accepts_a_derived_timeframe_and_coerces_enums(tmp_path):
    view = _store(tmp_path).set_view(
        timeframe="H2", chart_type="line", layout="split", panes=["H2", "M15"], bars=200
    )
    assert view.timeframe == "H2"
    assert view.chart_type.value == "line"
    assert view.layout.value == "split"
    assert view.panes == ["H2", "M15"]


def test_view_symbol_defaults_to_the_store_symbol(tmp_path):
    assert _store(tmp_path).data.view.symbol == "XAUUSDm"


def test_view_rejects_a_foreign_symbol(tmp_path):
    """One store per symbol, so bias and pins cannot leak across instruments."""
    store = _store(tmp_path)
    assert store.set_view(symbol="XAUUSDm").symbol == "XAUUSDm"
    with pytest.raises(StoreError) as exc:
        store.set_view(symbol="EURUSDm")
    assert exc.value.reason == "symbol_mismatch"


def test_open_subscriptions_accepts_a_string_kind(tmp_path):
    store = _store(tmp_path)
    store.add_subscription("pin", params={"family": "fvg", "timeframe": "H2", "price": 4152.86})
    store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    assert len(store.open_subscriptions("pin")) == 1
    assert len(store.open_subscriptions(SubscriptionKind.PIN)) == 1
    assert len(store.open_subscriptions()) == 2


# --------------------------------------------------------------------------- #
# thesis, proposals
# --------------------------------------------------------------------------- #

def test_thesis_validates_bias(tmp_path):
    store = _store(tmp_path)
    thesis = store.set_thesis(bias="bullish", storyline="sweep then continuation", confidence=0.6)
    assert thesis.bias == "bullish"
    assert thesis.confidence == 0.6
    with pytest.raises(StoreError) as exc:
        store.set_thesis(bias="moon")
    assert exc.value.reason == "invalid_bias"


def test_proposal_lifecycle(tmp_path):
    store = _store(tmp_path)
    proposal = store.add_proposal(
        bias="bullish",
        setup="sweep + choch",
        entry=4152.0,
        sl=4140.0,
        tp=4180.0,
        provenance=["fvg:H2:bullish:4152.86"],
    )
    assert proposal.status.value == "proposed"
    assert store.set_proposal_status(proposal.id, "invalidated").status.value == "invalidated"

    with pytest.raises(StoreError) as exc:
        store.set_proposal_status("prop_nope", "expired")
    assert exc.value.reason == "unknown_proposal"

    with pytest.raises(StoreError) as exc:
        store.set_proposal_status(proposal.id, "vibes")
    assert exc.value.reason == "invalid_status"


# --------------------------------------------------------------------------- #
# the leash
# --------------------------------------------------------------------------- #

def test_leash_enforces_the_minimum_turn_interval(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    store.record_turn("boot")
    with pytest.raises(LeashExceeded) as exc:
        store.record_turn("fire")
    assert exc.value.reason == "min_turn_interval"

    clock.advance(seconds=store_mod.MIN_TURN_INTERVAL_S + 1)
    assert store.record_turn("fire").trigger.value == "fire"


def test_leash_caps_turns_per_hour(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    for _ in range(store_mod.MAX_TURNS_PER_HOUR):
        store.record_turn("schedule")
        clock.advance(seconds=store_mod.MIN_TURN_INTERVAL_S + 1)
    with pytest.raises(LeashExceeded) as exc:
        store.record_turn("schedule")
    assert exc.value.reason == "max_turns_per_hour"


def test_leash_caps_daily_spend(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    store.record_turn("schedule", cost_usd=store_mod.MAX_SPEND_PER_DAY_USD)
    clock.advance(seconds=store_mod.MIN_TURN_INTERVAL_S + 1)
    with pytest.raises(LeashExceeded) as exc:
        store.record_turn("schedule")
    assert exc.value.reason == "max_spend_per_day"


def test_turn_record_bills_and_snapshots(tmp_path):
    store = _store(tmp_path)
    store.add_subscription("watch", "price_crosses", {"price": 4160.0})
    record = store.record_turn(
        "fire", trigger_detail="price_crosses fired at 4160.00", renders=2, tokens=1234, cost_usd=0.01
    )
    assert record.trigger.value == "fire"
    assert record.trigger_detail.startswith("price_crosses")
    assert len(record.subscriptions) == 1
    assert record.subscriptions[0]["condition"] == "price_crosses"

    budget = store.data.budget
    assert (budget.turns_today, budget.turns_this_hour) == (1, 1)
    assert budget.renders_today == 2
    assert round(budget.spend_usd_today, 4) == 0.01
    assert budget.last_turn_at is not None


def test_unknown_trigger_is_rejected(tmp_path):
    with pytest.raises(StoreError) as exc:
        _store(tmp_path).record_turn("because_i_felt_like_it")
    assert exc.value.reason == "invalid_trigger"
