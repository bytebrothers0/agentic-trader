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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pytest import approx

from _fixtures import (
    FakeClock,
    day,
    level as _level,
    bars_rows,
    render_scene,
    series as _series,
    snapshot as _snapshot,
    ts,
)
from agentic.feed import KNOWN_FAMILIES, Bars
from agentic.renderer import (
    FAMILY_INITIALS,
    Pane,
    RenderResult,
    Renderer,
    TagEntry,
    _bos_label,
    _sr_label,
)


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
        "price_range", "hidden_levels", "image", "tags",
    }
    assert manifest["hidden_levels"] == 0   # nothing below the ray budget here
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


def test_crt_levels_paint_the_dashboard_word_with_a_label_bridge(tmp_path):
    """The image text for a CRT level is the dashboard's own word.

    The operator's screenshot shows plain ``CRT``/``CRT-IB`` text on each
    solid line — no ordinals. The manifest tag stays the *unique* lookup key,
    and the entry's ``label`` bridges the (possibly repeated) image word back
    to exactly one level for the closing digest.
    """
    levels = [
        _level("crt", type="BEARISH (CLASSIC)", price=4170.0, time=ts(day(16, 8)),
               end_kind="active", range_high=4175.0, range_low=4165.0),
        _level("crt", type="BULLISH (INSIDE_BAR)", price=4152.0, time=ts(day(16, 12)),
               end_kind="active", variant="inside_bar"),
        _level("bos", type="I-CHOCH (BEARISH)", price=4160.0, time=ts(day(16, 14)),
               end_kind="active"),
    ]
    result = _renderer(tmp_path, "crt-labels", FakeClock()).render(
        _snapshot(levels, price=4155.0, atr=2.0),
        _series(bars_rows(price=4155.0, step_s=900)),
    )

    by_price = {entry.price: entry for entry in result.tags.values()}
    assert by_price[4170.0].label == "CRT"
    assert by_price[4152.0].label == "CRT-IB"
    # BOS paints its structural kind too — bridged the same way.
    assert by_price[4160.0].label == "I-CHoCH"
    # ...and the labels ride the manifest dict, not just the typed entry.
    labelled = [e for e in result.manifest["tags"].values() if e.get("label")]
    assert sorted(e["label"] for e in labelled) == ["CRT", "CRT-IB", "I-CHoCH"]



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
    assert result.manifest["window"] == {"from": None, "to": None, "bars": 0, "offset": 0}
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


# --------------------------------------------------------------------------- #
# Offset (phase 6d)
# --------------------------------------------------------------------------- #

def test_offset_shifts_the_window_but_not_the_pixels(tmp_path):
    renderer = _renderer(tmp_path, "o", FakeClock())

    # A longer series so a shifted window overlaps but has different from/to.
    rows = [
        (ts(day(16, 0)) + i * 900, 4150.0 + i, 4151.0 + i, 4149.0 + i, 4150.5 + i)
        for i in range(50)
    ]
    all_bars = _series(rows)
    empty_snap = _snapshot([], price=4155.0, atr=5.0)

    def _slice(lo, hi):
        return Bars(
            symbol=all_bars.symbol,
            timeframe=all_bars.timeframe,
            times=all_bars.times[lo:hi],
            open=all_bars.open[lo:hi],
            high=all_bars.high[lo:hi],
            low=all_bars.low[lo:hi],
            close=all_bars.close[lo:hi],
        )

    full = renderer.render(empty_snap, _slice(10, 50))
    assert full.manifest["window"]["offset"] == 0

    # A *shifted* window reports its own offset and its own from/to.
    off = renderer.render(empty_snap, _slice(7, 47), offset=3)
    assert off.manifest["window"]["offset"] == 3
    assert off.manifest["window"]["bars"] == 40
    assert off.manifest["window"]["to"] != full.manifest["window"]["to"]
    assert off.manifest["window"]["from"] != full.manifest["window"]["from"]

    # But offset is *metadata*: the caller (the loop) does the slicing, so the
    # same bars rendered at a different offset must give the same pixels. This is
    # the regression guard that the old test's "different offset -> different
    # hash" claim was tautological (it was really the different slice).
    same = renderer.render(empty_snap, _slice(10, 50), offset=3)
    assert same.manifest["window"]["offset"] == 3
    assert same.manifest["window"]["to"] == full.manifest["window"]["to"]
    assert same.image_sha256 == full.image_sha256
    assert same.render_id == full.render_id


def test_single_render_has_no_panes_and_layout_single_is_unchanged(tmp_path):
    snap, bars, pins, _ = render_scene()
    default = _renderer(tmp_path, "a", FakeClock()).render(snap, bars, pins=pins)
    explicit = _renderer(tmp_path, "b", FakeClock()).render(
        snap, bars, pins=pins, layout="single", offset=0
    )
    assert "panes" not in default.manifest
    assert default.image_sha256 == explicit.image_sha256
    assert default.render_id == explicit.render_id


def test_single_layout_ignores_panes(tmp_path):
    # A stray `panes` alongside layout="single" must not silently split the
    # figure: single rendering is byte-identical with or without the panes.
    htf, ltf = _split_scene()
    plain = _renderer(tmp_path, "a", FakeClock()).render(htf.snapshot, htf.bars)
    stray = _renderer(tmp_path, "b", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="single"
    )
    assert "panes" not in stray.manifest
    assert stray.image_sha256 == plain.image_sha256
    assert stray.render_id == plain.render_id


# --------------------------------------------------------------------------- #
# Split layout (phase 6d)
# --------------------------------------------------------------------------- #

def _pane(timeframe, levels, *, price=4150.0, atr=5.0, count=30, step_s=900):
    start = ts(day(16, 12))
    rows = []
    current = float(price)
    for i in range(count):
        o = current
        c = current + (1.5 if i % 3 else -1.0)
        rows.append((start + i * step_s, o, max(o, c) + 0.5, min(o, c) - 0.5, c))
        current = c
    return Pane(
        _snapshot(levels, timeframe=timeframe, price=price, atr=atr),
        _series(rows, timeframe=timeframe),
        [],
    )


def _split_scene():
    htf = _pane(
        "H2",
        [
            _level("crt", type="BEARISH (CLASSIC)", price=4185.0, time=ts(day(16, 8)),
                   end_kind="active", range_high=4190.0, range_low=4180.0),
        ],
        price=4150.0,
        count=20,
        step_s=7200,
    )
    ltf = _pane(
        "M15",
        [
            _level("fvg", type="FVG (BULLISH)", price=4155.0, time=ts(day(16, 12)),
                   end_kind="active", box_top=4158.0, box_bottom=4152.0),
        ],
        price=4150.0,
        count=40,
    )
    return htf, ltf


def test_split_render_has_two_panes_and_globally_unique_tags(tmp_path):
    htf, ltf = _split_scene()
    result = _renderer(tmp_path, "split", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="split"
    )
    manifest = result.manifest

    # top-level keys describe the *primary* pane (back-compat)
    assert manifest["timeframe"] == "H2"
    assert manifest["price_range"] == manifest["panes"][0]["price_range"]
    # the panes array describes each pane, top -> bottom
    assert [p["timeframe"] for p in manifest["panes"]] == ["H2", "M15"]
    assert manifest["panes"][0]["window"]["bars"] == len(htf.bars.times)
    assert manifest["panes"][1]["window"]["bars"] == len(ltf.bars.times)
    # tags are globally unique: the primary pane keeps the raw tags, pane 2 is prefixed
    tags = list(manifest["tags"])
    assert len(tags) == len(set(tags))
    assert not any(tag.startswith("P1:") for tag in tags)
    assert "C1" in tags and "P2:F1" in tags
    assert set(tags) == set(result.tags)
    # every pane's tags resolve through result.tags
    assert result.tags["P2:F1"].timeframe == "M15"
    assert result.tags["C1"].timeframe == "H2"


def test_split_pane_manifest_records_each_panes_price_basis(tmp_path):
    htf, ltf = _split_scene()
    htf.snapshot.price_basis = "window_end"
    ltf.snapshot.price_basis = "live"
    result = _renderer(tmp_path, "s", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="split"
    )
    first, second = result.manifest["panes"]
    assert first["current_price"] == htf.snapshot.current_price
    assert first["atr"] == htf.snapshot.atr
    assert first["price_basis"] == "window_end"
    assert second["current_price"] == ltf.snapshot.current_price
    assert second["atr"] == ltf.snapshot.atr
    assert second["price_basis"] == "live"


def test_split_merges_top_level_pins_into_the_primary_pane(tmp_path):
    htf, ltf = _split_scene()
    already_drawn = htf.snapshot.levels[0]
    extra = _snapshot(
        [_level("bos", type="BOS (BULLISH)", price=4175.0,
                time=ts(day(16, 9)), end_kind="active")],
        timeframe="H2", price=4150.0,
    ).levels[0]
    result = _renderer(tmp_path, "s", FakeClock()).render(
        htf.snapshot, htf.bars, pins=[extra, already_drawn], panes=[htf, ltf], layout="split"
    )

    # both pins are merged into pane 1, kept unprefixed (pane 2's tags are P2:...)
    pinned = {tag for tag, entry in result.tags.items() if entry.origin == "pinned"}
    assert pinned == {"B1*", "C1*"}
    assert not any(tag.startswith("P2:") for tag in pinned)
    assert "P2:F1" in result.tags  # pane 2 is still prefixed
    # the pin that pane 1 already drew is deduped, not drawn a second time
    assert len(result.tags) == len(htf.snapshot.levels) + len(ltf.snapshot.levels) + 1
    drawn_crt = [e for e in result.tags.values() if e.level_key == already_drawn.level_key]
    assert len(drawn_crt) == 1 and drawn_crt[0].origin == "pinned"


def test_split_panes_have_independent_price_ranges(tmp_path):
    low = _pane("M15", [_level("fvg", type="FVG (BULLISH)", price=101.0,
                               time=ts(day(16, 12)), end_kind="active")], price=100.0)
    high = _pane("H2", [_level("crt", type="BEARISH (CLASSIC)", price=200.0,
                               time=ts(day(16, 8)), end_kind="active")], price=200.0)
    result = _renderer(tmp_path, "s", FakeClock()).render(
        low.snapshot, low.bars, panes=[low, high], layout="split"
    )
    p0 = result.manifest["panes"][0]["price_range"]
    p1 = result.manifest["panes"][1]["price_range"]
    assert p0 != p1
    assert result.manifest["price_range"] == p0


def test_split_render_is_deterministic(tmp_path):
    htf, ltf = _split_scene()
    a = _renderer(tmp_path, "a", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="split"
    )
    b = _renderer(tmp_path, "b", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="split"
    )
    assert a.image_sha256 == b.image_sha256
    assert a.render_id == b.render_id
    with open(a.image_path, "rb") as fa, open(b.image_path, "rb") as fb:
        assert fa.read() == fb.read()


def test_split_render_draws_into_each_pane_band(tmp_path):
    from PIL import Image

    htf, ltf = _split_scene()
    result = _renderer(tmp_path, "s", FakeClock()).render(
        htf.snapshot, htf.bars, panes=[htf, ltf], layout="split"
    )
    with Image.open(result.image_path) as img:
        assert img.size == (SMALL_WIDTH, SMALL_HEIGHT)
        rgb = img.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        mid = height // 2

        def dark_ink(lo, hi):
            # The paper theme draws candles in black/white only: bear bodies,
            # wicks and borders are near-black ink on the white ground, while
            # the grid/spines stay light gray. Every family now uses black or
            # gray ink, so dark pixels mark candles and active indicator lines.
            return sum(
                1
                for y in range(lo, hi)
                for x in range(width)
                if max(pixels[x, y]) < 100
            )

        top = dark_ink(0, mid)
        bottom = dark_ink(mid, height)

    assert top > 0, "the top (HTF) pane drew no candles"
    assert bottom > 0, "the bottom (LTF) pane drew no candles"


# --------------------------------------------------------------------------- #
# The ray budget (dashboard parity): a busy family can never flood the chart
# --------------------------------------------------------------------------- #

def _many_ts(count):
    """``count`` live TS levels, one per bar, oldest first."""
    base = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    return [
        _level(
            "ts",
            type="TS HIGH" if i % 2 else "TS LOW",
            price=100.0 + (i % 20) * 0.5,
            time=ts(base + timedelta(minutes=15 * i)),
        )
        for i in range(count)
    ]


def test_a_busy_family_never_starves_the_others_or_itself(tmp_path):
    """The dashboard's per-category cap: 80 newest rays win, the rest are hidden
    — and counted, so the manifest can say why a level is absent."""
    snap = _snapshot(_many_ts(85) + [
        _level("crt", type="BEARISH", price=99.0,
               time=ts(datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)))
    ])
    bars = _series(bars_rows(40))
    result = _renderer(tmp_path, "cap", FakeClock()).render(snap, bars)

    assert result.manifest["hidden_levels"] == 5
    ts_tags = [t for t, e in result.tags.items() if e.family == "ts"]
    assert len(ts_tags) == 80
    assert len(result.tags) == 81          # 80 ts + the 1 crt run


def test_a_pinned_level_is_never_hidden(tmp_path):
    snap = _snapshot(_many_ts(85))
    bars = _series(bars_rows(40))
    old = min(snap.levels, key=lambda lvl: (lvl.formed_at, lvl.level_key))
    result = _renderer(tmp_path, "pin", FakeClock()).render(snap, bars, pins=[old])

    assert result.manifest["hidden_levels"] == 4
    keys = {e.level_key for e in result.tags.values()}
    assert old.level_key in keys           # a 45th hidden ts would be exactly wrong
    ts_tags = [t for t, e in result.tags.items() if e.family == "ts"]
    assert len(ts_tags) == 81              # 80 budget + the exempt pin


# --------------------------------------------------------------------------- #
# The TS ray: a three-step event drawn from the anchor, never to the break
# --------------------------------------------------------------------------- #

def test_ts_ray_starts_at_the_anchor_and_never_reaches_the_break():
    """The ts payload's ``time`` is the sweep bar and ``start_time`` the anchor;
    the agent's PNG must draw anchor -> sweep -> one bar right, PLUS the
    operator's +3 expansion — NOT from the sweep bar, and never out to the
    invalidation bar."""
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    anchor = ts(start + timedelta(minutes=15 * 5))
    sweep = ts(start + timedelta(minutes=15 * 7))
    far_break = ts(start + timedelta(minutes=15 * 30))

    record = _snapshot([
        _level("ts", type="TS HIGH (BEARISH)", price=105.0,
               time=sweep, start_time=anchor, end_time=far_break,
               end_kind="invalidated"),
    ]).levels[0]
    assert record.attrs.get("start_time") == anchor

    bars = _series(bars_rows(40, start=ts(start)))
    ray_start, ray_end = Renderer._span(record, bars)

    assert ray_start == 5                          # the anchor candle
    assert ray_end == 11                           # sweep (idx 7) + 1 + the +3 expansion
    assert ray_end < bars.index_at_or_before(far_break)   # never the break


def test_ts_ray_survives_an_anchor_that_fell_off_the_window():
    """An anchor older than the visible window degrades to the window's left
    edge; the sweep segment still draws to sweep + four bars."""
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    ghost_anchor = ts(start - timedelta(minutes=15 * 10))   # before the window
    sweep = ts(start + timedelta(minutes=15 * 4))

    record = _snapshot([
        _level("ts", type="TS LOW (BULLISH)", price=98.0,
               time=sweep, start_time=ghost_anchor),
    ]).levels[0]
    bars = _series(bars_rows(40, start=ts(start)))
    ray_start, ray_end = Renderer._span(record, bars)

    assert ray_start == 0                          # clamped to the left edge
    assert ray_end == bars.index_at_or_before(sweep) + 4   # the +3 expansion included


# --------------------------------------------------------------------------- #
# The 2026-10-20 span & naming rules: CRT's both boundaries + the event +3,
# IDM's full life, QM's +3, the trendline's sloped truth, BOS's real names
# --------------------------------------------------------------------------- #

def test_crt_ray_spans_anchor_to_sweep_plus_four_and_shows_both_boundaries():
    # CRT payload convention is family-INVERTED: ``time`` is the anchor (where
    # the level was formed) and ``start_time`` is the manipulation bar.
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    anchor_at = ts(start + timedelta(minutes=15 * 5))
    sweep_at = ts(start + timedelta(minutes=15 * 7))
    record = _snapshot([
        _level("crt", type="BEARISH (INSIDE_BAR)", price=105.0,
               time=anchor_at, start_time=sweep_at,
               range_high=105.0, range_low=99.0),
    ]).levels[0]
    bars = _series(bars_rows(40, start=ts(start)))
    ray_start, ray_end = Renderer._span(record, bars)

    assert ray_start == 5                          # the anchor candle
    assert ray_end == 11                           # sweep (idx 7) + 4
    lo, hi = Renderer._price_range(bars, [record])
    assert lo <= 99.0 and hi >= 105.0              # both boundaries autoscale


def test_idm_draws_its_full_life_and_fresh_ids_get_the_plus3():
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    formed = ts(start + timedelta(minutes=15 * 5))
    swept = ts(start + timedelta(minutes=15 * 20))
    bars = _series(bars_rows(40, start=ts(start)))

    dead = _snapshot([_level("idm", type="IDM (BULLISH)", price=100.0,
                             time=formed, end_time=swept, end_kind="swept")]).levels[0]
    assert Renderer._span(dead, bars) == (5, 20)   # formation -> the sweep bar

    fresh = _snapshot([_level("idm", type="IDM (BULLISH)", price=101.0,
                              time=formed, end_kind="active")]).levels[0]
    assert Renderer._span(fresh, bars) == (5, 11)  # default span (3) + the +3


def test_qm_draws_the_broken_twice_arc_plus_five():
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    formed = ts(start + timedelta(minutes=15 * 5))
    broke = ts(start + timedelta(minutes=15 * 10))     # the QM birth candle
    bars = _series(bars_rows(40, start=ts(start)))

    # Primary payload form: break_time = the second break. The arc is
    # origin -> second break -> +5, whatever the lifecycle did after.
    live = _snapshot([_level("qm", type="FTQM (BULLISH)", price=100.0,
                             time=formed, break_time=broke,
                             end_kind="active")]).levels[0]
    assert Renderer._span(live, bars) == (5, 15)       # break (10) + 5

    # Older stores without break_time fall back to the lifecycle event +5.
    legacy = _snapshot([_level("qm", type="FTQM (BULLISH)", price=100.0,
                               time=formed, end_time=ts(start + timedelta(minutes=15 * 20)),
                               end_kind="mitigated")]).levels[0]
    assert Renderer._span(legacy, bars) == (5, 25)     # event (20) + 5

    # Neither -> the open span (+3).
    bare = _snapshot([_level("qm", type="FTQM (BULLISH)", price=100.0,
                             time=formed, end_kind="active")]).levels[0]
    assert Renderer._span(bare, bars) == (5, 11)


def test_trendline_runs_pivot_to_end_uncapped_with_its_sloped_price():
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    pivot = ts(start + timedelta(minutes=15 * 5))
    end_bar = ts(start + timedelta(minutes=15 * 25))
    record = _snapshot([
        _level("trendline", type="TL_SUPPORT", price=100.0,
               time=pivot, end_time=end_bar, end_kind="broken",
               price_end=95.0),
    ]).levels[0]

    assert record.attrs["price_end"] == 95.0       # the slope rides the feed
    bars = _series(bars_rows(40, start=ts(start)))
    assert Renderer._span(record, bars) == (5, 25) # pivot -> end bar, never capped


def test_bos_labels_carry_the_structural_kind_name():
    bos = _snapshot([_level("bos", type="BOS (BULLISH)", price=100.0)]).levels[0]
    ichoch = _snapshot([_level("bos", type="I-CHOCH (BEARISH)", price=100.0)]).levels[0]
    ibos = _snapshot([_level("bos", type="I-BOS (BULLISH)", price=100.0)]).levels[0]

    assert _bos_label(bos) == "BOS"
    assert _bos_label(ibos) == "I-BOS"
    assert _bos_label(ichoch) == "I-CHoCH"


def test_sr_labels_are_the_dashboard_words():
    support = _snapshot([_level("sr", desc="SUPPORT (fresh)", price=100.0)]).levels[0]
    resistance = _snapshot([_level("sr", desc="RESISTANCE (unfresh)", price=102.0)]).levels[0]
    sbr = _snapshot([_level("sr", desc="SBR (fresh)", price=105.0)]).levels[0]
    assert _sr_label(support) == "S"
    assert _sr_label(resistance) == "R"
    assert _sr_label(sbr) == "SBR"


def test_sr_spans_its_full_life_and_fresh_gets_the_dashboard_pose():
    start = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    formed = ts(start + timedelta(minutes=15 * 5))
    broke = ts(start + timedelta(minutes=15 * 20))
    bars = _series(bars_rows(40, start=ts(start)))

    dead = _snapshot([_level("sr", type="SUPPORT", price=100.0,
                             time=formed, end_time=broke, end_kind="broken")]).levels[0]
    assert Renderer._span(dead, bars) == (5, 20)   # held until the break bar

    fresh = _snapshot([_level("sr", type="RESISTANCE", price=102.0,
                              time=formed, end_kind="active")]).levels[0]
    assert Renderer._span(fresh, bars) == (5, 13)  # the dashboard's open +8 pose


# --------------------------------------------------------------------------- #
# The paper theme: monochrome candles and lines, with restrained zone fills.
# --------------------------------------------------------------------------- #

def _style_of(family, *, type="BULLISH", status=None):
    lv = _snapshot(
        [_level(family, type=type, time=ts(day(19, 12)), end_kind="active")],
        symbol="XAUUSDm", timeframe="M15", price=4150.0, atr=5.0,
    ).levels[0]
    if status is not None:
        lv.status = status
    return Renderer._level_style(lv, False, 4150.0)


def test_paper_theme_uses_monochrome_candles_and_indicator_lines():
    from agentic.models import LevelStatus

    import agentic.renderer as paper

    assert paper._BG == "#ffffff"
    assert paper._UP == "#ffffff" and paper._DOWN == "#000000"
    assert paper._CANDLE_EDGE == "#000000"
    assert paper._PRICE == "#000000"
    assert paper._LEVEL_LINEWIDTH == 1.0  # pixel target, converted using renderer DPI
    assert paper._WICK_LINEWIDTH == 1.0
    assert paper._LEVEL_STYLE == "-"
    assert paper._TAG_FONTSIZE == 8
    assert Renderer(dpi=100)._line_width(1.0) == approx(0.72)
    assert Renderer(dpi=200)._line_width(1.0) == approx(0.36)
    for family in ("crt", "bos", "ts", "liquidity", "fvg", "ob", "ifvg"):
        color, alpha = _style_of(family)
        assert (color, alpha) == ("#000000", 1.0), family
    assert _style_of("bos", status=LevelStatus.BROKEN) == ("#7a828e", 1.0)
    assert _style_of("crt", status=LevelStatus.FILLED) == ("#000000", 0.35)


def test_zone_styles_match_the_requested_paper_chart():
    import agentic.renderer as paper

    assert paper.Renderer._zone_style("ob") == (
        "#ffe56b", 0.22, "#000000", 0.16,
    )
    assert paper.Renderer._zone_style("fvg") == (
        "#000000", 0.08, None, 0.0,
    )
    assert paper.Renderer._zone_style("ifvg") == (
        "#000000", 0.08, None, 0.0,
    )


def test_agent_chart_keeps_eight_bars_of_clear_space_on_the_right():
    from agentic.renderer import Renderer

    assert Renderer._x_limits(50) == (-1, 57)
