"""Central config for the AI trader. Keys come from .env — never hardcode."""
from __future__ import annotations
import os

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        # ai_agent/../.env  (repo root of the bot)
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        load_dotenv(os.path.join(root, ".env"))
    except Exception:
        pass

_load_dotenv()

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4")
# Groq-hosted LLM (OpenAI-compatible). Used when LLM_PROVIDER=groq or XAI key absent.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq" if os.getenv("GROQ_API_KEY") else "xai").lower()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
AI_MODE = os.getenv("AI_MODE", "propose").lower()  # propose only for now
AI_MOCK = os.getenv("AI_MOCK", "false").lower() == "true"
MIN_CONFIDENCE = float(os.getenv("AI_MIN_CONFIDENCE", "55"))
MAX_RISK_PERCENT = float(os.getenv("AI_MAX_RISK_PERCENT", "1.0"))
SYMBOL_DEFAULT = os.getenv("AI_SYMBOL", "XAUUSD")


def resolve_provider() -> tuple[str, str, str, str]:
    """The shared LLM endpoint the ``/api/ai`` layer already uses.

    Returns ``(provider, base_url, model, key_env)``. This is a **pure addition**:
    it mirrors the provider selection that ``agent_loop._llm_creds`` and
    ``ts_validator._creds`` inline, but those two call sites are deliberately left
    untouched so the legacy path stays byte-identical. New consumers (the agentic
    layer's live mode, via ``server.get_agent_service``) call this instead of
    copying the rule a third time.

    Selection: Groq wins when ``LLM_PROVIDER == "groq"`` or when a Groq key is
    present and no xAI key is; xAI wins when ``LLM_PROVIDER == "xai"`` or an xAI
    key is set; otherwise Groq is the default. ``key_env`` is the *name* of the
    environment variable holding the key — never the key itself.
    """
    if LLM_PROVIDER == "groq" or (GROQ_API_KEY and not XAI_API_KEY):
        return "groq", GROQ_BASE_URL, GROQ_MODEL, "GROQ_API_KEY"
    if LLM_PROVIDER == "xai" or XAI_API_KEY:
        return "xai", XAI_BASE_URL, GROK_MODEL, "XAI_API_KEY"
    return "groq", GROQ_BASE_URL, GROQ_MODEL, "GROQ_API_KEY"


STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
REGISTRY_PATH = os.path.join(STATE_DIR, "indicator_registry.json")
PROPOSAL_PATH = os.path.join(STATE_DIR, "ai_proposal.json")
JOURNAL_PATH = os.path.join(STATE_DIR, "ai_journal.jsonl")
