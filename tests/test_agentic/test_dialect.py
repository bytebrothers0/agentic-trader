"""The model-output <-> store-schema dialect wall (`agentic/_dialect.py`).

Pure translation functions, exercised at their edges. The motivation is a real
recorded proposal that the store rejected for one vocabulary word after the
model had read the chart correctly — ``bias: "short"``, ``entry:
"4184.55-4190.05 (sell zone)"`` — so the words and shapes a model actually
reaches for are pinned here, along with the refusal that must *not* be
translated away.
"""
import pytest

from agentic._dialect import coerce_bias, coerce_proposal, first_price


# --------------------------------------------------------------------------- #
# Bias vocabulary
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, expected", [
    ("bullish", "bullish"), ("bearish", "bearish"),          # already correct
    ("Bullish", "bullish"), ("BEARISH", "bearish"),          # case is not opinion
    ("short", "bearish"), ("sell", "bearish"), ("bear", "bearish"),
    ("long", "bullish"), ("buy", "bullish"), ("bull", "bullish"),
    (" none ", "none"), ("no-bias", "none"), ("flat", "none"), ("neutral", "neutral"),
])
def test_a_trade_side_word_maps_onto_the_store_vocabulary(given, expected):
    assert coerce_bias(given) == expected


@pytest.mark.parametrize("given", ["sideways", "", "short-term"])
def test_an_unmappable_bias_passes_through_untouched_to_be_refused(given):
    """Translation is not licence to invent an opinion: the store still refuses."""
    assert coerce_bias(given) == given


@pytest.mark.parametrize("given, expected", [
    ("neutral-lean-bearish (range-bound under an unconfirmed H4 bearish CRT)", "bearish"),
    ("neutral-lean-bullish", "bullish"),
    ("lean-bearish", "bearish"),
    ("not-bearish", "not-bearish"),          # a negated side is no side at all
    ("short-term", "short-term"),            # a horizon, not a trade side
    ("range-bound (choppy)", "range-bound (choppy)"),
])
def test_a_compound_stance_translates_by_its_conclusion_word(given, expected):
    """A replayed turn wrote `neutral-lean-bearish (...)` — a real, decided lean
    the exact-alias map cannot see. The rule is narrow: the leading hyphenated
    token must END in a directional word, with no negator in it."""
    assert coerce_bias(given) == expected


def test_a_non_string_bias_is_left_alone():
    assert coerce_bias(None) is None
    assert coerce_bias(0.55) == 0.55


# --------------------------------------------------------------------------- #
# Prices out of prose
# --------------------------------------------------------------------------- #

def test_a_zone_string_reads_back_as_its_first_edge():
    assert first_price("4184.55-4190.05 (sell zone; prefer confirmation)") == 4184.55


def test_a_target_ladder_reads_back_t1_not_the_ladder_marker():
    # "T1" must not contribute its "1" — the nearest target is the plan's first.
    assert first_price("T1 4172.84 (partial), T2 4169.14, T3 4154.65") == 4172.84


def test_a_stop_prefix_is_ignored():
    assert first_price("above 4190.05 padded by 0.25 ATR") == 4190.05


def test_a_numeric_value_passes_through_and_prose_without_a_number_is_none():
    assert first_price(4184.55) == 4184.55
    assert first_price("market on trigger") is None
    assert first_price(None) is None
    assert first_price(True) is None


# --------------------------------------------------------------------------- #
# The proposal translation (the shape `_apply_output` and the tool share)
# --------------------------------------------------------------------------- #

_PROPOSAL_KEYS = ("bias", "setup", "entry", "sl", "tp", "confidence")


def test_only_known_keys_are_picked_and_the_plan_fields_are_translated():
    plan = {
        "bias": "short",
        "setup": "CRT rejection",
        "entry": "4184.55-4190.05 (sell zone)",
        "sl": "above 4190.05 padded",
        "tp": 4172.84,
        "surprise_field": True,          # never forwarded to the store
        "confidence": 0.55,
    }

    out = coerce_proposal(plan, _PROPOSAL_KEYS)

    assert out == {
        "bias": "bearish",
        "setup": "CRT rejection",
        "entry": 4184.55,
        "sl": 4190.05,
        "tp": 4172.84,
        "confidence": 0.55,
    }


def test_a_field_the_model_left_out_stays_absent():
    assert coerce_proposal({"bias": "bullish"}, _PROPOSAL_KEYS) == {"bias": "bullish"}
