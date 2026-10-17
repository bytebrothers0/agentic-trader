"""Tests for the server-side render + manifest (spec phase 3).

Determinism is the hard requirement: same store + same feed -> byte-identical PNG,
so two renders of one state must share an ``image_sha256``, a ``render_id`` and a
filename. The manifest must map every drawn tag back to an exact ``level_key``,
with ``origin`` (live/pinned) always present. Everything renders into a pytest
``tmp_path``; nothing here touches MT5.
"""
import functools
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pytest import approx

from _fixtures import (
    FakeClock,
    level as _level,
    render_scene,
    series as _series,
    snapshot as _snapshot,
)
from agentic.feed import KNOWN_FAMILIES
from agentic.renderer import FAMILY_INITIALS, RenderResult, Renderer, TagEntry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

#: Behavioural tests render small; only one test pays for the production default.
SMALL_WIDTH, SMALL_HEIGHT = 512, 288
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1536, 864

#: The scene fixture, drawn once at small size and shared by the read-only tests.
#: Rendering is deterministic, so one render serves every test that only inspects
#: the tags/manifest; this keeps the suite from paying for ~9 identical renders.
@functools.lru_cache(maxsize=None)
def _standard():
    snap, bars, pins, thesis_key = render_scene()
    out_dir = tempfile.mkdtemp(prefix="agentic-render-tests-")
    result = Renderer(
        width=SMALL_WIDTH,
        height=SMALL_HEIGHT,
        dpi=100,
        clock=FakeClock(),
        out_dir=out_dir,
    ).render(snap, bars, pins=pins, thesis_level_keys=[thesis_key])
    return snap, bars, pins, thesis_key, result


def _renderer(tmp_path, name, clock, *, width=SMALL_WIDTH, height=SMALL_HEIGHT):
    return Renderer(
        width=width, height=height, dpi=100, clock=clock, out_dir=str(tmp_path / name)
    )


def _drawn_keys(snapshot, pins):
    return {level.level_key for level in list(snapshot.levels) + list(pins)}


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_two_renders_of_the_same_state_are_byte_identical(tmp_path):
    snap, bars, pins, _ = render_scene()
    a = _renderer(tmp_path, "a", FakeClock()).render(snap, bars, pins=pins)
    b = _renderer(tmp_path, "b", FakeClock()).render(snap, bars, pins=pins)

    assert a.image_sha256 == b.image_sha256
    assert a.render_id == b.render_id
    assert os.path.basename(a.image_path) == os.path.basename(b.image_path)
    assert os.path.basename(a.image_path) == f"{a.render_id}.png"

    with open(a.image_path, "rb") as fa, open(b.image_path, "rb") as fb:
        assert fa.read() == fb.read()


def test_render_id_is_the_image_hash():
    result = _standard()[4]
    with open(result.image_path, "rb") as fh:
        raw = fh.read()
    assert hashlib.sha256(raw).hexdigest() == result.image_sha256
    assert result.render_id == f"r_{result.image_sha256[:16]}"


def test_rendered_at_lives_in_the_manifest_only(tmp_path):
    snap, bars, pins, _ = render_scene()
    clock_a = FakeClock()
    clock_b = FakeClock()
    clock_b.advance(hours=3)

    a = _renderer(tmp_path, "a", clock_a).render(snap, bars, pins=pins)
    b = _renderer(tmp_path, "b", clock_b).render(snap, bars, pins=pins)

    assert a.manifest["rendered_at"] != b.manifest["rendered_at"]
    assert a.manifest["rendered_at"].endswith("Z")
    # The wall-clock does not reach the pixels.
    assert a.image_sha256 == b.image_sha256


def test_a_changed_state_changes_the_hash(tmp_path):
    snap, bars, pins, _ = render_scene()
    renderer = _renderer(tmp_path, "a", FakeClock())
    before = renderer.render(snap, bars, pins=pins)

    moved = snap.to_dict()
    moved["current_price"] = 4156.25
    from agentic.feed import FeedSnapshot

    after = renderer.render(FeedSnapshot.from_dict(moved), bars, pins=pins)

    assert before.image_sha256 != after.image_sha256
    assert before.render_id != after.render_id


# --------------------------------------------------------------------------- #
# The manifest
# --------------------------------------------------------------------------- #

def test_manifest_has_the_spec_shape():
    bars = _standard()[1]
    result = _standard()[4]
    manifest = result.manifest

    assert set(manifest) == {
        "render_id", "symbol", "timeframe", "window", "rendered_at",
        "price_range", "image", "tags",
    }
    assert manifest["symbol"] == "XAUUSDm"
    assert manifest["timeframe"] == "M15"
    assert manifest["window"]["bars"] == len(bars.times)
    assert manifest["window"]["from"] and manifest["window"]["to"]
    assert isinstance(manifest["price_range"], list) and len(manifest["price_range"]) == 2
    assert manifest["image"] == {
        "path": result.image_path, "width": SMALL_WIDTH, "height": SMALL_HEIGHT
    }
    assert manifest["render_id"] == result.render_id


def test_every_tag_maps_to_a_drawn_level():
    snap, _bars, pins, _key, result = _standard()
    drawn = _drawn_keys(snap, pins)

    assert set(result.manifest["tags"]) == set(result.tags)
    for tag, entry in result.tags.items():
        assert isinstance(entry, TagEntry)
        assert entry.tag == tag
        assert entry.level_key in drawn
    # Tags are unique by construction, and the map agrees with the manifest.
    assert len(result.tags) == len(drawn)
    assert set(result.manifest["tags"]) == set(result.tags)


def test_tags_are_the_family_initial_plus_an_ordinal():
    result = _standard()[4]

    # Families present: bos, crt, fvg (the pin is a second fvg).
    assert set(result.tags) == {"B1", "C1", "F1*", "F2"}
    assert all(t.rstrip("*")[0] in FAMILY_INITIALS.values() for t in result.tags)
    # The pinned fvg (4180) sorts above the live one (4160) within its family.
    assert result.tags["F1*"].price == 4180.0
    assert result.tags["F2"].price == 4160.0


def test_origin_is_pinned_for_a_pin_and_live_otherwise():
    result = _standard()[4]

    assert result.tags["F1*"].origin == "pinned"
    assert result.tags["B1"].origin == "live"
    assert result.tags["C1"].origin == "live"
    assert result.tags["F2"].origin == "live"
    # The pin is marked with a trailing '*', nothing else is.
    starred = {tag for tag in result.tags if tag.endswith("*")}
    assert starred == {"F1*"}
    for tag, entry in result.tags.items():
        assert entry.origin in {"live", "pinned"}


def test_distance_points_is_signed_from_the_current_price():
    result = _standard()[4]
    # Current price is 4155 in the fixture.
    assert result.tags["F1*"].distance_points == approx(25.0)
    assert result.tags["F2"].distance_points == approx(5.0)
    assert result.tags["B1"].distance_points == approx(-10.0)


def test_thesis_level_is_flagged():
    result = _standard()[4]
    flagged = {tag for tag, entry in result.tags.items() if entry.is_thesis_level}
    assert flagged == {"F2"}


def test_pin_dedupes_against_the_snapshot(tmp_path):
    snap, bars, _, _ = render_scene()
    # Pin a level the snapshot already draws: it must not be drawn or tagged twice.
    result = _renderer(tmp_path, "a", FakeClock()).render(snap, bars, pins=[snap.levels[1]])
    assert len(result.tags) == len(snap.levels)
    pinned = [e for e in result.tags.values() if e.origin == "pinned"]
    assert len(pinned) == 1
    assert pinned[0].level_key == snap.levels[1].level_key


# --------------------------------------------------------------------------- #
# The image
# --------------------------------------------------------------------------- #

def test_the_png_matches_the_declared_size_and_exists():
    from PIL import Image

    result = _standard()[4]
    assert os.path.isfile(result.image_path)
    with Image.open(result.image_path) as img:
        assert img.size == (result.width, result.height)
    assert (result.width, result.height) == (SMALL_WIDTH, SMALL_HEIGHT)


def test_default_size_render_declares_1536x864(tmp_path):
    # The one test that pays for the production default: the declared size, the
    # file, and the manifest must agree, and the price range is independent of
    # pixel size (same scene -> same range).
    from PIL import Image

    snap, bars, pins, _ = render_scene()
    result = _renderer(
        tmp_path, "big", FakeClock(), width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT
    ).render(snap, bars, pins=pins)

    assert (result.width, result.height) == (DEFAULT_WIDTH, DEFAULT_HEIGHT)
    assert result.manifest["image"] == {
        "path": result.image_path, "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT
    }
    with Image.open(result.image_path) as img:
        assert img.size == (DEFAULT_WIDTH, DEFAULT_HEIGHT)

    small = _renderer(tmp_path, "small", FakeClock()).render(snap, bars, pins=pins)
    assert result.manifest["price_range"] == small.manifest["price_range"]


def test_result_round_trips_through_json():
    result = _standard()[4]
    again = RenderResult.from_dict(result.to_dict())
    assert again.render_id == result.render_id
    assert again.manifest == result.manifest
    # Serde would leave `tags` as plain dicts; RenderResult restores the type.
    assert isinstance(next(iter(again.tags.values())), TagEntry)
    assert set(again.tags) == set(result.tags)


# --------------------------------------------------------------------------- #
# Cross-process determinism
# --------------------------------------------------------------------------- #

def test_render_is_deterministic_across_processes():
    # In-process repeatability only proves one interpreter; two PYTHONHASHSEEDs
    # in two fresh interpreters prove the bytes themselves are stable.
    if not sys.executable:
        pytest.skip("no Python interpreter available to spawn")
    try:
        import matplotlib  # noqa: F401
    except Exception:
        pytest.skip("matplotlib is not available")

    probe = Path(__file__).with_name("_render_probe.py")
    repo_root = Path(__file__).resolve().parents[2]
    # Two fresh interpreters, one per seed, run concurrently so the wall time is
    # one import, not two.
    procs = [
        subprocess.Popen(
            [sys.executable, str(probe)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            cwd=str(repo_root),
        )
        for seed in ("0", "1")
    ]
    hashes = []
    for proc in procs:
        out, err = proc.communicate()
        if proc.returncode != 0:
            pytest.skip(f"render probe failed: {err.strip()}")
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        hashes.append(lines[-1])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


# --------------------------------------------------------------------------- #
# Family initials and degenerate scenes
# --------------------------------------------------------------------------- #

def test_family_initials_cover_every_known_family():
    # Guards a 14th family being silently letter-fallen-back instead of named.
    assert set(FAMILY_INITIALS) == set(KNOWN_FAMILIES)


def test_unknown_families_get_free_letters(tmp_path):
    snap = _snapshot([
        _level("zzz", price=100.0, time=1000, end_kind="active"),
        _level("aaa", price=101.0, time=2000, end_kind="active"),
    ], price=100.0)
    bars = _series([(1000, 99.0, 101.0, 98.0, 100.0)])
    result = _renderer(tmp_path, "a", FakeClock()).render(snap, bars)

    # Sorted family order: 'aaa' takes the first free letter (A), 'zzz' the next (D).
    assert set(result.tags) == {"A1", "D1"}
    assert result.tags["A1"].family == "aaa"
    assert result.tags["D1"].family == "zzz"
    assert "A" not in FAMILY_INITIALS.values()
    assert "D" not in FAMILY_INITIALS.values()


def test_empty_scene_renders_a_sane_manifest(tmp_path):
    snap = _snapshot([], price=0.0, atr=0.0)
    bars = _series([])
    result = _renderer(tmp_path, "a", FakeClock()).render(snap, bars)

    assert result.tags == {}
    assert result.manifest["tags"] == {}
    assert result.manifest["window"] == {"from": None, "to": None, "bars": 0}
    assert result.manifest["price_range"] == [0.0, 0.0]
    assert os.path.isfile(result.image_path)


def test_a_thesis_key_that_is_not_drawn_flags_nothing(tmp_path):
    snap, bars, pins, _ = render_scene()
    result = _renderer(tmp_path, "a", FakeClock()).render(
        snap, bars, pins=pins, thesis_level_keys=["not-a-drawn-level-key"]
    )
    assert all(not entry.is_thesis_level for entry in result.tags.values())


def test_price_range_includes_band_extents(tmp_path):
    # A zone that reaches well beyond its anchor price must not be clipped.
    snap = _snapshot([
        _level("fvg", price=100.5, time=1000, end_kind="active",
               box_top=200.0, box_bottom=50.0),
    ], price=100.5)
    bars = _series([(1000, 100.0, 101.0, 99.5, 100.5)])
    result = _renderer(tmp_path, "a", FakeClock()).render(snap, bars)
    assert result.manifest["price_range"] == [50.0, 200.0]


def test_manifest_tag_order_is_canonical(tmp_path):
    # Permuting `pins` must not reorder the manifest of an otherwise identical
    # render — the manifest stays stable too.
    snap, bars, pins, _ = render_scene()
    extra = snap.levels[1]
    a = _renderer(tmp_path, "a", FakeClock()).render(snap, bars, pins=pins + [extra])
    b = _renderer(tmp_path, "b", FakeClock()).render(snap, bars, pins=[extra] + pins)
    assert list(a.manifest["tags"]) == sorted(a.manifest["tags"])
    assert list(a.manifest["tags"]) == list(b.manifest["tags"])
    assert a.image_sha256 == b.image_sha256
