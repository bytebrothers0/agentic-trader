"""tools/build_alchemist.py — compose the Alchemist MSNR playbook.

Fresh strategy library (strategies/alchemist/*.md, filename order) composed
into ONE loader-compatible playbook. The universal trader concepts are NOT in
these files — they live in the knowledge layer bound to the system prompt
(agentic/prompts.knowledge_layer), so the strategy stays thin and swappable.

Budgets: composed text must fit agentic.strategy.MAX_STRATEGY_CHARS (the
loader refuses oversized files); the operator's model carries a 1M-token
context, so the binding constraint is the loader cap, not tokens — enforced
here so the failure is a build error, not a runtime surprise.

Usage:
    python tools/build_alchemist.py           # build + print budget
    python tools/build_alchemist.py --check   # verify budgets only

Output: strategies/alchemist_mnsr_v2.md (never auto-activated).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATEGY_DIR = os.path.join(ROOT, "strategies", "alchemist")
OUTPUT = os.path.join(ROOT, "strategies", "alchemist_mnsr_v2.md")

#: The strategy loader's own hard cap (agentic.strategy.MAX_STRATEGY_CHARS).
MAX_CHARS = 25_000


def build() -> tuple[str, int]:
    files = sorted(glob.glob(os.path.join(STRATEGY_DIR, "*.md")))
    if not files:
        raise SystemExit(f"no strategy files found in {STRATEGY_DIR}")
    parts = []
    for path in files:
        body = open(path, encoding="utf-8").read().strip()
        if body:
            parts.append(body)
    text = "\n\n---\n\n".join(parts) + "\n"
    if len(text) > MAX_CHARS:
        raise SystemExit(
            f"composed playbook is {len(text)} chars; loader cap is {MAX_CHARS}"
        )
    return text, len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify budgets only")
    args = parser.parse_args()

    text, n_files = build()
    if not args.check:
        with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(OUTPUT, ROOT)}")
    print(f"playbook: {len(text)}/{MAX_CHARS} chars | files: {n_files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
