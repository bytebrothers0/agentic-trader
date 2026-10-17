"""The substrate must stay standalone: no repo imports, no network (spec P7).

If this test ever fails, the agent has started reaching into the running system
before it was meant to. Phases 0-2 are supposed to be buildable and testable with
nothing else present.
"""
import re
from pathlib import Path

import agentic

BANNED_ROOT_MODULES = {
    "indicators",
    "strategy",
    "execution",
    "data",
    "config",
    "server",
    "ai_agent",
}
BANNED_LIBS = {
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "openai",
    "groq",
    "fastapi",
    "aiohttp",
    "websockets",
}

_IMPORT = re.compile(r"^(?:import|from)\s+([A-Za-z_][\w.]*)")


def _root_modules(text: str):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("from .") or stripped.startswith("import ."):
            continue  # intra-package
        match = _IMPORT.match(stripped)
        if match:
            yield match.group(1).split(".")[0]


def _offenders(banned):
    root = Path(agentic.__file__).parent
    found = []
    for path in sorted(root.glob("*.py")):
        for module in _root_modules(path.read_text(encoding="utf-8")):
            if module in banned:
                found.append(f"{path.name} imports {module}")
    return found


def test_agentic_does_not_import_the_rest_of_the_repo():
    assert _offenders(BANNED_ROOT_MODULES) == []


def test_agentic_has_no_network_dependency():
    assert _offenders(BANNED_LIBS) == []


def test_the_package_exposes_its_surface():
    assert agentic.SPEC_VERSION == "0.1.0"
    assert agentic.ContextStore is not None
    assert agentic.Condition.LEVEL_FORMS.value == "level_forms"
