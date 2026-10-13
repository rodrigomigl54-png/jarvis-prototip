from ..config import Config, ConfigError
from .anthropic import AnthropicProvider
from .base import LLMError, LLMProvider, LLMResponse, ToolCall, ToolSpec
from .openai_compat import OpenAICompatProvider

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def create_provider(cfg: Config) -> LLMProvider:
    p = cfg.llm_provider
    if p == "gemini":
        if not cfg.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is missing in .env")
        return OpenAICompatProvider("gemini", GEMINI_BASE_URL, cfg.gemini_api_key, cfg.gemini_model)
    if p == "groq":
        if not cfg.groq_api_key:
            raise ConfigError("GROQ_API_KEY is missing in .env")
        return OpenAICompatProvider("groq", GROQ_BASE_URL, cfg.groq_api_key, cfg.groq_model)
    if p == "ollama":
        return OpenAICompatProvider("ollama", cfg.ollama_base_url, "", cfg.ollama_model, timeout=180)
    if p == "anthropic":
        if not cfg.anthropic_api_key:
            raise ConfigError("ANTHROPIC_API_KEY is missing in .env")
        return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model)
    raise ConfigError(f"Unknown LLM_PROVIDER: {p}")


__all__ = [
    "create_provider", "LLMProvider", "LLMResponse", "LLMError", "ToolCall", "ToolSpec",
    "OpenAICompatProvider", "AnthropicProvider",
]
