"""The substrate must stay standalone: no repo imports, no network (spec P7).

Phase 0 kept the *whole* package isolated. Phase 1 intentionally introduces one
bridge — :mod:`agentic.feed` — because the user asked for the agent to be wired
to the CRT indicator. That bridge is **read-only** and **lazy**: it reaches into
``server``/``indicators`` only from inside a function, so importing ``agentic``
(or ``agentic.feed``) never drags in FastAPI or the MT5 loader, and the pure core
(``models``/``conditions``/``store``/``crt_strategy``) still imports nothing from
the running system.

If this test fails, either the pure core has started reaching out, or the bridge
has become eager enough to couple package import to the server.
"""
import ast
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

#: Modules that must import nothing from the running system, at any depth.
PURE_MODULES = (
    "models.py",
    "conditions.py",
    "store.py",
    "crt_strategy.py",
    "subscriptions.py",
    "watchdog.py",
    "__init__.py",
)
#: The single sanctioned bridge. It may reach into the system, but only lazily.
BRIDGE_MODULES = ("feed.py",)

BANNED = BANNED_ROOT_MODULES | BANNED_LIBS


def _root_names(node: ast.AST):
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level:  # relative import -> intra-package
            return []
        return [(node.module or "").split(".")[0]]
    return []


def _module_level_imports(tree: ast.AST):
    names = []
    for node in tree.body:
        names.extend(_root_names(node))
    return names


def _all_imports(tree: ast.AST):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(_root_names(node))
    return names


def _files():
    root = Path(agentic.__file__).parent
    return {path.name: path for path in sorted(root.glob("*.py"))}


def _offenders(modules, banned, *, module_level_only: bool):
    found = []
    for name, path in _files().items():
        if name not in modules:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _module_level_imports(tree) if module_level_only else _all_imports(tree)
        for module in names:
            if module in banned:
                found.append(f"{name} imports {module}")
    return found


def test_pure_core_imports_nothing_from_the_rest_of_the_repo():
    assert _offenders(PURE_MODULES, BANNED_ROOT_MODULES, module_level_only=False) == []


def test_pure_core_has_no_network_dependency():
    assert _offenders(PURE_MODULES, BANNED_LIBS, module_level_only=False) == []


def test_feed_is_a_lazy_bridge():
    # Importing the feed must stay cheap: no banned import at module level...
    assert _offenders(BRIDGE_MODULES, BANNED, module_level_only=True) == []
    # ...but the bridge must actually exist, or it is not wired at all.
    feed = _files()["feed.py"]
    deep = set(_all_imports(ast.parse(feed.read_text(encoding="utf-8"))))
    assert deep & BANNED_ROOT_MODULES, "feed.py no longer reaches the indicator layer"


def test_the_package_exposes_its_surface():
    assert agentic.SPEC_VERSION == "0.1.0"
    assert agentic.ContextStore is not None
    assert agentic.Condition.LEVEL_FORMS.value == "level_forms"
    # phase 1 wiring: the feed adapter and the CRT playbook are part of the API.
    assert agentic.Feed is not None
    assert agentic.LevelRecord is not None
    assert "crt" in agentic.REQUIRED_FAMILIES
