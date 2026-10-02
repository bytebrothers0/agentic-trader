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

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
REGISTRY_PATH = os.path.join(STATE_DIR, "indicator_registry.json")
PROPOSAL_PATH = os.path.join(STATE_DIR, "ai_proposal.json")
JOURNAL_PATH = os.path.join(STATE_DIR, "ai_journal.jsonl")
