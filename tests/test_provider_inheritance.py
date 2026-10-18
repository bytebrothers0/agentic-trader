"""The shared-provider inheritance seam (spec phase 6c).

``ai_agent.config.resolve_provider`` is a pure **addition** that mirrors the
provider selection ``ai_agent/agent_loop.py`` and ``ai_agent/ts_validator.py``
inline. This pins the rule in isolation, and then pins the *merge* that is the
actual phase-6c feature: ``server._resolve_agent_connection`` combines those
settings with the agent's ``AGENT_MODEL``/``AGENT_API_BASE``/``AGENT_API_KEY_ENV``
one field at a time. It deliberately does *not* import the legacy ``agent_loop`` to
compare (that module pulls ``msnr_snapshot``, whose imports are broken) — the
equivalence is to the rule, which is written down in both places.
"""
from __future__ import annotations

import pytest

from ai_agent import config as cfg


@pytest.fixture
def provider_env(monkeypatch):
    """Set the module constants ``resolve_provider`` reads, per case."""

    def _set(*, llm_provider, groq_key, xai_key):
        monkeypatch.setattr(cfg, "LLM_PROVIDER", llm_provider)
        monkeypatch.setattr(cfg, "GROQ_API_KEY", groq_key)
        monkeypatch.setattr(cfg, "XAI_API_KEY", xai_key)
        monkeypatch.setattr(cfg, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        monkeypatch.setattr(cfg, "GROQ_MODEL", "qwen/qwen3.8-27b")
        monkeypatch.setattr(cfg, "XAI_BASE_URL", "https://api.x.ai/v1")
        monkeypatch.setattr(cfg, "GROK_MODEL", "grok-4")
        monkeypatch.setattr(cfg, "LOCAL_BASE_URL", "http://localhost:8080/v1")
        monkeypatch.setattr(cfg, "LOCAL_MODEL", "deepseek-v4.1-flash-free")

    return _set


def test_groq_when_provider_is_groq(provider_env):
    provider_env(llm_provider="groq", groq_key="g", xai_key="x")
    assert cfg.resolve_provider() == (
        "groq", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "GROQ_API_KEY",
    )


def test_groq_when_only_a_groq_key_is_present(provider_env):
    provider_env(llm_provider="xai", groq_key="g", xai_key="")
    assert cfg.resolve_provider()[0] == "groq"


def test_xai_when_provider_is_xai(provider_env):
    provider_env(llm_provider="xai", groq_key="g", xai_key="x")
    assert cfg.resolve_provider() == (
        "xai", "https://api.x.ai/v1", "grok-4", "XAI_API_KEY",
    )


def test_xai_when_an_xai_key_is_present(provider_env):
    provider_env(llm_provider="other", groq_key="", xai_key="x")
    assert cfg.resolve_provider()[0] == "xai"


def test_groq_is_the_fallback_when_nothing_is_configured(provider_env):
    provider_env(llm_provider="other", groq_key="", xai_key="")
    provider, base, model, key_env = cfg.resolve_provider()
    assert provider == "groq"
    assert base and model and key_env == "GROQ_API_KEY"


def test_local_is_selected_and_keyless(provider_env):
    """LLM_PROVIDER=local returns the local base/model with NO key variable."""
    provider_env(llm_provider="local", groq_key="g", xai_key="x")
    assert cfg.resolve_provider() == (
        "local", "http://localhost:8080/v1", "deepseek-v4.1-flash-free", "",
    )


def test_local_wins_even_when_a_hosted_key_is_present(provider_env):
    """A pinned local provider must not be shadowed by the key heuristics."""
    provider_env(llm_provider="local", groq_key="g", xai_key="x")
    assert cfg.resolve_provider()[0] == "local"


def test_the_real_environment_resolves_to_a_usable_provider():
    """The local ``.env`` selection must resolve to a sane endpoint.

    Either a **keyed** hosted provider (the ``*_API_KEY`` variable *name*, never
    the key) or the **keyless** local provider (an empty name, meaning "send no
    Authorization header").
    """
    provider, base, model, key_env = cfg.resolve_provider()
    assert provider in {"groq", "xai", "local"}
    assert base.startswith("http")
    assert model
    if provider == "local":
        assert key_env == ""  # keyless by design
    else:
        assert key_env.endswith("_API_KEY")


# --------------------------------------------------------------------------- #
# The per-field merge in server.get_agent_service() (the actual phase 6c feature)
# --------------------------------------------------------------------------- #

def _merger():
    """The pure merge helper, imported lazily so this module stays collection-light."""
    from server import _resolve_agent_connection

    return _resolve_agent_connection


def _resolver(
    provider="groq",
    base="https://groq.test/openai/v1",
    model="qwen/qwen3.8-27b",
    key_env="GROQ_API_KEY",
):
    return lambda: (provider, base, model, key_env)


def test_mock_mode_passes_the_settings_straight_through():
    """Mock mode is a passthrough: it must not resolve (or even import) the provider."""
    called = {"n": 0}

    def must_not_run():
        called["n"] += 1
        raise AssertionError("mock mode must not resolve the shared provider")

    merge = _merger()
    assert merge("mock", "", "", "", resolver=must_not_run) == ("", "", "", "")
    assert merge("mock", "m", "b", "K", resolver=must_not_run) == ("", "m", "b", "K")
    assert called["n"] == 0


def test_live_mode_inherits_every_field_when_all_are_blank():
    """All three blank = inherit the whole connection from the shared provider."""
    provider, model, base, key_env = _merger()(
        "live", "", "", "", resolver=_resolver()
    )
    assert (provider, model, base, key_env) == (
        "groq", "qwen/qwen3.8-27b", "https://groq.test/openai/v1", "GROQ_API_KEY",
    )


def test_live_mode_pins_each_field_independently():
    """A non-empty setting pins just that field; the other two still inherit."""
    merge = _merger()
    resolver = _resolver()
    assert merge("live", "pinned-model", "", "", resolver=resolver) == (
        "groq", "pinned-model", "https://groq.test/openai/v1", "GROQ_API_KEY",
    )
    assert merge("live", "", "https://pinned.test/v1", "", resolver=resolver) == (
        "groq", "qwen/qwen3.8-27b", "https://pinned.test/v1", "GROQ_API_KEY",
    )
    assert merge("live", "", "", "PINNED_KEY", resolver=resolver) == (
        "groq", "qwen/qwen3.8-27b", "https://groq.test/openai/v1", "PINNED_KEY",
    )
    # All three pinned: nothing is resolved away.
    assert merge("live", "m", "b", "K", resolver=resolver) == ("groq", "m", "b", "K")


def test_live_mode_uses_the_real_resolver_by_default(provider_env):
    """Without an injected resolver, live mode calls ai_agent.config.resolve_provider."""
    provider_env(llm_provider="groq", groq_key="g", xai_key="")
    assert _merger()("live", "", "", "") == (
        "groq", "qwen/qwen3.8-27b", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
    )


def test_live_mode_raises_a_clear_error_when_resolution_fails():
    """C3: resolution failure must name the real cause, not fail later misleadingly."""

    def boom():
        raise RuntimeError("no provider configured")

    with pytest.raises(RuntimeError) as excinfo:
        _merger()("live", "", "", "", resolver=boom)
    message = str(excinfo.value)
    assert "resolve_provider" in message
    assert "no provider configured" in message


def test_live_mode_rejects_an_incomplete_connection():
    """A resolver that returns blanks is a hard error, naming the empty fields.

    ``api_key_env`` may legitimately be blank (a keyless endpoint), so it is not
    part of the completeness check — but a blank ``model`` or ``base`` is.
    """
    with pytest.raises(RuntimeError) as excinfo:
        _merger()("live", "", "", "", resolver=lambda: ("groq", "", "", ""))
    message = str(excinfo.value)
    assert "AGENT_MODEL" in message
    assert "AGENT_API_BASE" in message


def test_live_mode_accepts_a_keyless_provider():
    """A blank key variable means a keyless endpoint, not an incomplete one."""
    assert _merger()(
        "live", "", "", "",
        resolver=lambda: ("local", "http://localhost:8080/v1", "m", ""),
    ) == ("local", "m", "http://localhost:8080/v1", "")


def test_mock_mode_service_displays_a_non_blank_model(monkeypatch, tmp_path):
    """Live-only resolution leaves the model empty in mock mode; the panel must not."""
    import server

    monkeypatch.setattr(server, "AGENT_MODE", "mock")
    monkeypatch.setattr(server, "AGENT_MODEL", "")
    monkeypatch.setattr(server, "AGENT_API_BASE", "")
    monkeypatch.setattr(server, "AGENT_API_KEY_ENV", "")
    monkeypatch.setattr(server, "AGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(server, "AGENT_RENDER_DIR", str(tmp_path / "renders"))
    monkeypatch.setattr(server, "_agent_service", None)

    service = server.get_agent_service()
    assert service.config.model == server.AGENT_DEFAULT_MODEL
    assert service.status()["model"] == server.AGENT_DEFAULT_MODEL
    assert service.panel()["model"] == server.AGENT_DEFAULT_MODEL

