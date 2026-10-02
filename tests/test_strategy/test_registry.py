"""Tests for the strategy entry-module registry."""
import json
import os

import pytest

import strategy.registry as reg


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    path = str(tmp_path / "entry_modules.json")
    monkeypatch.setenv("MSNR_MODULES_FILE", path)
    yield path


def test_defaults_all_off(isolated_state):
    mods = reg.list_modules()
    assert len(mods) == 6
    assert {m["id"] for m in mods} == {
        "msnr_mn", "msnr_w1", "msnr_d1", "msnr_14b", "msnr_d1w4", "ts_m15",
    }
    assert not reg.any_enabled()
    assert reg.enabled_model_values() == set()
    assert reg.enabled_model_values("ts_m15") == set()


def test_enable_disable_roundtrip(isolated_state):
    assert reg.set_enabled("msnr_d1", True) is True
    assert reg.is_enabled("msnr_d1") is True
    assert reg.enabled_model_values() == {"D1_STORY_H4_ENTRY", "D1_STORY_D1_ENTRY"}
    assert reg.any_enabled() is True
    assert reg.set_enabled("msnr_d1", False) is True
    assert reg.is_enabled("msnr_d1") is False
    assert not reg.any_enabled()


def test_unknown_module_rejected(isolated_state):
    assert reg.set_enabled("nope", True) is False
    assert reg.is_enabled("nope") is False


def test_state_persists_to_file(isolated_state):
    reg.set_enabled("msnr_14b", True)
    with open(isolated_state, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == {"msnr_14b": True}
    # Fresh read picks it up.
    assert reg.is_enabled("msnr_14b") is True
    assert reg.enabled_model_values() == {"MODEL_B_14B"}


def test_ts_module_registers_its_model(isolated_state):
    assert reg.set_enabled("ts_m15", True) is True
    assert reg.enabled_model_values("ts_m15") == {"TS_M15_ENTRY"}
    assert reg.enabled_model_values() == set()  # msnr engine unaffected


def test_corrupt_file_falls_back_to_defaults(isolated_state):
    with open(isolated_state, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert reg.list_modules()
    assert not reg.any_enabled()
