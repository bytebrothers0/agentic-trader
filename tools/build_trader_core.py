"""tools/build_trader_core.py — compose the trader-knowledge playbook.

Source of truth: ``strategies/knowledge/*.md`` (one dense file per topic;
``00-core.md`` is the ≤50-line prompt-engineering header). This script
concatenates them, in filename order, into ONE playbook file the agent's
strategy loader can activate — because ``agentic.strategy`` loads a single
markdown, the modular files must be assembled before the agent can wear them.

Budget guard: the core header must stay within ``CORE_MAX_LINES`` — the
operator's explicit requirement ("deep enough, not more than 50 lines") — and
the composed playbook is capped at ``TOTAL_MAX_LINES`` so the knowledge layer
can never silently bloat the agent's context.

Usage:
    python tools/build_trader_core.py            # build + print line budget
    python tools/build_trader_core.py --check    # CI mode: fail if over budget

Output: ``strategies/trader_core.md`` (never auto-activated: the operator
points STRATEGY_ACTIVE at it after reviewing it).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(ROOT, "strategies", "knowledge")
OUTPUT = os.path.join(ROOT, "strategies", "trader_core.md")

#: The operator's hard budget for the prompt-engineering header.
CORE_MAX_LINES = 50
#: The strategy loader's own hard cap (``agentic.strategy.MAX_STRATEGY_CHARS``):
#: the composed playbook must respect it or the agent cannot wear the file at
#: all. Enforced here so the failure is a build error, not a runtime surprise.
TOTAL_MAX_CHARS = 25_000
#: Hard ceiling for the composed playbook (anti-bloat guard). Raising this is a
#: conscious decision, not a default: the topic files are deliberately dense
#: (each ~24-30 lines) and compose to ~328 lines with 10 topics. The operator's
#: explicit ≤50-line budget applies to the CORE header (enforced above). The
#: composed playbook's real token cost is measured per turn in the interview
#: phase and recorded in docs/research/2026-11-11-trader-knowledge/findings.md.
TOTAL_MAX_LINES = 340


def _section_title(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    return name[3:] if name[:2].isdigit() and name[2] == "-" else name


def build() -> tuple[str, int, int]:
    """Compose the playbook; returns (text, core_lines, total_lines)."""
    files = sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, "*.md")))
    if not files:
        raise SystemExit(f"no knowledge files found in {KNOWLEDGE_DIR}")

    core_path = next((f for f in files if os.path.basename(f).startswith("00-")), None)
    if core_path is None:
        raise SystemExit("knowledge/00-core.md (the core header) is missing")

    core_lines = open(core_path, encoding="utf-8").read().rstrip().splitlines()
    if len(core_lines) > CORE_MAX_LINES:
        raise SystemExit(
            f"core header is {len(core_lines)} lines; the operator's budget is {CORE_MAX_LINES}"
        )

    parts = ["\n".join(core_lines).rstrip()]
    for path in files:
        if path == core_path:
            continue
        body = open(path, encoding="utf-8").read().strip()
        if body:
            # The topic file carries its own H1; add only a rule separator.
            parts.append(f"\n\n---\n\n{body}")

    text = "\n".join(parts) + "\n"
    total_lines = len(text.splitlines())
    if total_lines > TOTAL_MAX_LINES:
        raise SystemExit(
            f"composed playbook is {total_lines} lines; hard ceiling is {TOTAL_MAX_LINES}"
        )
    if len(text) > TOTAL_MAX_CHARS:
        raise SystemExit(
            f"composed playbook is {len(text)} chars; the strategy loader's cap is "
            f"{TOTAL_MAX_CHARS} (agentic.strategy.MAX_STRATEGY_CHARS) — condense the topic files"
        )
    return text, len(core_lines), total_lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="build and verify budgets only")
    args = parser.parse_args()

    text, core_lines, total_lines = build()
    if not args.check:
        with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(OUTPUT, ROOT)}")
    print(f"core header: {core_lines}/{CORE_MAX_LINES} lines | playbook: {total_lines}/{TOTAL_MAX_LINES} lines | topics: {len(glob.glob(os.path.join(KNOWLEDGE_DIR, '*.md'))) - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
