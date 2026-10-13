import logging

from ..config import Config, ConfigError
from .anthropic import AnthropicProvider
from .base import LLMError, LLMProvider, LLMResponse, ToolCall, ToolSpec
from .fallback import FallbackProvider
from .openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def create_single(cfg: Config, name: str) -> LLMProvider | None:
    """Build one provider, or None if its key is missing."""
    if name == "gemini":
        if not cfg.gemini_api_key:
            return None
        return OpenAICompatProvider("gemini", GEMINI_BASE_URL, cfg.gemini_api_key, cfg.gemini_model)
    if name == "groq":
        if not cfg.groq_api_key:
            return None
        return OpenAICompatProvider("groq", GROQ_BASE_URL, cfg.groq_api_key, cfg.groq_model)
    if name == "ollama":
        return OpenAICompatProvider("ollama", cfg.ollama_base_url, "", cfg.ollama_model, timeout=180)
    if name == "anthropic":
        if not cfg.anthropic_api_key:
            return None
        return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model)
    raise ConfigError(f"Unknown LLM provider: {name}")


def create_provider(cfg: Config) -> LLMProvider:
    """Main provider first, then LLM_FALLBACKS (skipping ones without a key)."""
    primary = create_single(cfg, cfg.llm_provider)
    if primary is None:
        raise ConfigError(f"API key for LLM_PROVIDER={cfg.llm_provider} is missing in .env")
    chain = [primary]
    for name in cfg.llm_fallbacks:
        p = create_single(cfg, name)
        if p is None:
            log.info("Fallback LLM %s skipped (no API key)", name)
        else:
            chain.append(p)
    return chain[0] if len(chain) == 1 else FallbackProvider(chain)


__all__ = [
    "create_provider", "create_single", "LLMProvider", "LLMResponse", "LLMError", "ToolCall",
    "ToolSpec", "OpenAICompatProvider", "AnthropicProvider", "FallbackProvider",
]
