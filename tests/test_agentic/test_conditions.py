"""Tests for the condition vocabulary (spec phase 2 schema).

A condition that cannot be evaluated deterministically cannot wake the agent, so
the vocabulary is closed: unknown names and unusable parameters are rejected at
creation time, with a reason the agent can act on.
"""
import pytest

from agentic.conditions import (
    ALL_CONDITIONS,
    CONDITION_SPECS,
    Condition,
    ConditionError,
    default_timeframe,
    describe,
    is_timeframe_scoped,
    spec_for,
    validate,
    validate_pin_query,
)


def test_every_condition_enum_value_has_a_spec():
    assert set(ALL_CONDITIONS) == {c.value for c in Condition}
    assert set(CONDITION_SPECS) == {c.value for c in Condition}


def test_unknown_condition_is_rejected():
    with pytest.raises(ConditionError) as exc:
        spec_for("vibes_are_good")
    assert exc.value.reason == "unknown_condition"


def test_price_crosses_needs_a_price():
    with pytest.raises(ConditionError) as exc:
        validate("price_crosses", {})
    assert exc.value.reason == "missing_params"


def test_price_crosses_coerces_to_float():
    assert validate("price_crosses", {"price": "4152.86"})["price"] == 4152.86


def test_level_swept_accepts_a_level_key():
    key = "fvg:H2:bullish:4152.86:2026-10-16T14:00"
    assert validate("level_swept", {"level_key": key})["level_key"] == key


def test_level_swept_accepts_family_and_price():
    assert validate("level_swept", {"family": "fvg", "price": 4152.86})["price"] == 4152.86


def test_level_swept_needs_some_identity():
    with pytest.raises(ConditionError) as exc:
        validate("level_swept", {"family": "fvg"})
    assert exc.value.reason == "missing_params"


def test_extra_params_are_rejected():
    with pytest.raises(ConditionError) as exc:
        validate("price_crosses", {"price": 1.0, "vibes": True})
    assert exc.value.reason == "unknown_params"


def test_level_forms_rejects_a_bad_direction():
    with pytest.raises(ConditionError) as exc:
        validate("level_forms", {"family": "fvg", "direction": "sideways"})
    assert exc.value.reason == "invalid_param"


def test_zone_rejects_an_inverted_band():
    with pytest.raises(ConditionError) as exc:
        validate("price_enters_zone", {"low": 4200, "high": 4100})
    assert exc.value.reason == "invalid_param"


def test_range_expands_defaults_to_atr_and_rejects_junk():
    assert validate("range_expands", {"multiple": 1.5})["reference"] == "ATR"
    with pytest.raises(ConditionError) as exc:
        validate("range_expands", {"multiple": 1.5, "reference": "vibes"})
    assert exc.value.reason == "invalid_param"


def test_sessions_are_lowercased_and_validated():
    assert validate("session_opens", {"session": "LONDON"})["session"] == "london"
    with pytest.raises(ConditionError):
        validate("session_closes", {"session": "mars"})


def test_time_reached_needs_an_iso_timestamp():
    assert validate("time_reached", {"at": "2026-10-17T16:00:00Z"})["at"] == "2026-10-17T16:00:00Z"
    with pytest.raises(ConditionError) as exc:
        validate("time_reached", {"at": "next tuesday"})
    assert exc.value.reason == "invalid_param"


def test_structural_conditions_reject_a_bad_timeframe():
    with pytest.raises(ConditionError) as exc:
        validate("bos_forms", {"timeframe": "15 minutes"})
    assert exc.value.reason == "invalid_timeframe"


def test_pin_query_accepts_family_and_price():
    out = validate_pin_query({"family": "fvg", "timeframe": "H2", "price": "4152.86", "tolerance": 0.5})
    assert out["price"] == 4152.86
    assert out["timeframe"] == "H2"


def test_pin_query_needs_some_identity():
    with pytest.raises(ConditionError) as exc:
        validate_pin_query({"timeframe": "H2"})
    assert exc.value.reason == "missing_params"


def test_scope_flags():
    assert is_timeframe_scoped("bos_forms") is True
    assert is_timeframe_scoped("session_opens") is False
    assert is_timeframe_scoped("time_reached") is False


def test_default_timeframe_falls_back_to_active():
    assert default_timeframe("bos_forms", {}, "M15") == "M15"
    assert default_timeframe("bos_forms", {"timeframe": "H1"}, "M15") == "H1"


def test_describe_lists_every_condition():
    text = describe()
    for name in ALL_CONDITIONS:
        assert name in text
