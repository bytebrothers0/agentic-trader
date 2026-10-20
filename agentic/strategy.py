"""agentic/strategy.py — the strategy file loader.

The agent's playbook is a markdown file owned by the operator, not code a
developer ships: one ``.md`` per strategy in the strategies directory, the
active one named by ``config.settings.STRATEGY_ACTIVE`` (default
``strategies/default.md``, the ported CRT model). The loaded text is injected
into the system prompt whole — ``prompts.build_system_prompt(playbook=...)`` —
so a strategy is whatever the file says, and nothing here parses, validates or
executes it beyond the safety checks below.

Pure: stdlib only, no repo imports, no clock. Deterministic: the same file
bytes give the same text every boot.

Failure is loud and specific — a service refuses to build without its strategy:
missing directory, missing file, an empty file, an oversized file, or a name
that would escape the directory. A vague failure here would ship silently as
"the agent ignored my strategy".
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Sanity cap for one strategy file, in characters. Roughly 5k tokens: this
#: bounds every turn's input (the strategy text rides in the system prompt) so
#: an innocent-looking 500-line .md cannot blow the token leash on every call.
MAX_STRATEGY_CHARS = 20_000


class StrategyError(ValueError):
    """A strategy file is missing, unreadable, empty, oversized or unsafe."""


@dataclass(frozen=True)
class Strategy:
    """One loaded strategy: the clock-stable form of an .md playbook."""

    name: str
    text: str


def _safe_name(name: str) -> str:
    """Normalise a strategy name, refusing anything that escapes the directory.

    The name may carry a trailing ``.md``. No separators, no traversal, no
    hidden empty names: a bad name is a configuration error, not a lookup miss.
    """
    cleaned = (name or "").strip()
    if cleaned.lower().endswith(".md"):
        cleaned = cleaned[:-3]
    if not cleaned:
        raise StrategyError("strategy name is empty")
    if any(part in cleaned for part in ("/", "\\",)) or ".." in cleaned:
        raise StrategyError(f"strategy name must be a plain file name: {name!r}")
    return cleaned


def load_strategy(directory: str, name: str) -> Strategy:
    """Load ``<directory>/<name>.md`` as this process's strategy.

    Raises :class:`StrategyError` — naming the file and the actual problem —
    for a missing directory, a missing file, whitespace-only text, text over
    :data:`MAX_STRATEGY_CHARS`, or a traversing name.
    """
    cleaned = _safe_name(name)

    base = os.path.realpath(str(directory or ""))
    if not os.path.isdir(base):
        raise StrategyError(f"strategy directory not found: {directory!r}")

    real_file = os.path.realpath(os.path.join(base, f"{cleaned}.md"))
    # Containment on the *real* paths, so a symlink planted under the directory
    # cannot point the loader outside it (same discipline as agent_service's
    # render-id traversal check).
    if real_file != os.path.join(base, f"{cleaned}.md") or not real_file.endswith(".md"):
        raise StrategyError(f"strategy path escapes the directory: {name!r}")
    if not os.path.isfile(real_file):
        raise StrategyError(
            f"strategy file not found: {os.path.join(directory, f'{cleaned}.md')}"
        )

    try:
        with open(real_file, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise StrategyError(f"strategy file unreadable: {real_file}: {exc}") from exc

    if not text.strip():
        raise StrategyError(f"strategy file is empty: {real_file}")
    if len(text) > MAX_STRATEGY_CHARS:
        raise StrategyError(
            f"strategy file too long: {real_file} is {len(text)} chars "
            f"(MAX_STRATEGY_CHARS = {MAX_STRATEGY_CHARS})"
        )

    return Strategy(name=cleaned, text=text)
