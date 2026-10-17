"""A self-contained render probe for the cross-process determinism test.

It deliberately does **not** import the test fixtures: the point is to render one
fixed scene in a *fresh* interpreter (with a different ``PYTHONHASHSEED``) and
print the PNG sha256, so the test can prove the bytes are stable across processes
rather than merely across calls in one process.
"""
import os
import sys
import tempfile
from datetime import datetime, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agentic.feed import parse_candles, parse_payload  # noqa: E402
from agentic.renderer import Renderer  # noqa: E402


def _scene():
    """A fixed bars + levels pair, built inline so the probe is standalone."""
    rows = []
    price = 4150.0
    for i in range(30):
        o = price
        c = price + (1.5 if i % 3 else -1.0)
        rows.append(
            {
                "time": 1_700_000_000 + i * 900,
                "open": o,
                "high": max(o, c) + 0.6,
                "low": min(o, c) - 0.6,
                "close": c,
            }
        )
        price = c

    bars = parse_candles({"symbol": "XAUUSDm", "timeframe": "M15", "candles": rows})
    snapshot = parse_payload(
        {
            "symbol": "XAUUSDm",
            "timeframe": "M15",
            "current_price": price,
            "atr": 3.0,
            "levels": [
                {
                    "category": "fvg", "type": "FVG (BULLISH)", "price": 4152.0,
                    "time": 1_700_000_000, "state": "FRESH",
                    "box_top": 4154.0, "box_bottom": 4151.0,
                },
                {
                    "category": "bos", "type": "BOS (BEARISH)", "price": 4144.0,
                    "time": 1_700_001_800, "state": "FRESH",
                },
                {
                    "category": "crt", "type": "BULLISH (CLASSIC)", "price": 4156.0,
                    "time": 1_700_003_600, "state": "FRESH",
                    "range_high": 4158.0, "range_low": 4153.0,
                },
            ],
        }
    )
    return snapshot, bars


def main():
    snapshot, bars = _scene()
    out_dir = tempfile.mkdtemp(prefix="agentic-render-probe-")
    renderer = Renderer(
        width=512,
        height=288,
        dpi=100,
        clock=lambda: datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc),
        out_dir=out_dir,
    )
    result = renderer.render(
        snapshot, bars, thesis_level_keys=[snapshot.levels[0].level_key]
    )
    print(result.image_sha256)


if __name__ == "__main__":
    main()
