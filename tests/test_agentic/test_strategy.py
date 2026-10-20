"""Tests for the strategy file loader (`agentic/strategy.py`)."""
from __future__ import annotations

import pytest

from agentic.strategy import MAX_STRATEGY_CHARS, StrategyError, load_strategy


def test_it_loads_the_shipped_active_strategy():
    """Whatever STRATEGY_ACTIVE names must load from the shipped strategies dir.

    Reads the setting instead of hard-coding a name, so the operator can swap
    the active playbook without touching this test.
    """
    from config.settings import STRATEGY_DIR, STRATEGY_ACTIVE

    strat = load_strategy(str(STRATEGY_DIR), STRATEGY_ACTIVE)

    assert strat.name == STRATEGY_ACTIVE
    assert strat.text.strip(), "the active strategy must not be empty"
    assert len(strat.text) <= MAX_STRATEGY_CHARS


def test_a_missing_directory_raises(tmp_path):
    with pytest.raises(StrategyError, match="directory"):
        load_strategy(str(tmp_path / "nope"), "default")


def test_a_missing_file_raises(tmp_path):
    (tmp_path / "other.md").write_text("hello", encoding="utf-8")
    with pytest.raises(StrategyError, match="default"):
        load_strategy(str(tmp_path), "default")


def test_an_empty_file_raises(tmp_path):
    (tmp_path / "mine.md").write_text("   \n\t \n", encoding="utf-8")
    with pytest.raises(StrategyError, match="empty"):
        load_strategy(str(tmp_path), "mine")


def test_an_oversized_file_raises(tmp_path):
    (tmp_path / "big.md").write_text("x" * (MAX_STRATEGY_CHARS + 1), encoding="utf-8")
    with pytest.raises(StrategyError, match="MAX_STRATEGY_CHARS|too long"):
        load_strategy(str(tmp_path), "big")


@pytest.mark.parametrize("bad", ["", "..", "sub/inner", r"back\\slash", "a/../b"])
def test_traversal_and_blank_names_are_refused(tmp_path, bad):
    with pytest.raises(StrategyError):
        load_strategy(str(tmp_path), bad)


def test_the_name_is_normalised_and_the_text_is_exact(tmp_path):
    target = tmp_path / "mine.md"
    target.write_text("Buy low.\n\nSell high.\n", encoding="utf-8")

    assert load_strategy(str(tmp_path), "mine.md").text == "Buy low.\n\nSell high.\n"
    # ".md" requested or not, same result — and the raw file bytes round-trip.
    again = load_strategy(str(tmp_path), "mine")
    assert again.name == "mine" and again.text == "Buy low.\n\nSell high.\n"
