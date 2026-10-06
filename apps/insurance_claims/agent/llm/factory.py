"""Builds the configured LLM client."""

from __future__ import annotations

from ..config import Settings
from .client import LLMClient, NotConfiguredClient

SUPPORTED_PROVIDERS = ("anthropic", "openai")


def _model_mismatch(provider: str, settings: Settings) -> str | None:
    """A clear message when the model names belong to the other provider, which is the easiest
    mistake to make when switching (the defaults are Claude models)."""
    names = (settings.llm_model, settings.llm_model_fast)
    if provider == "openai" and any(n.lower().startswith("claude") for n in names):
        return (
            "LLM_PROVIDER=openai but LLM_MODEL / LLM_MODEL_FAST name a Claude model. "
            "Set both to OpenAI models (for example gpt-5.4-mini)."
        )
    if provider == "anthropic" and any(n.lower().startswith("gpt-") for n in names):
        return (
            "LLM_PROVIDER=anthropic but LLM_MODEL / LLM_MODEL_FAST name an OpenAI model. "
            "Set both to Claude models, or set LLM_PROVIDER=openai."
        )
    return None


def build_llm(settings: Settings) -> LLMClient:
    """Return a real client when a key is configured, otherwise a stand-in that raises a clear
    LLMNotConfigured on first use. The app itself must still boot without a key."""
    if not settings.llm_configured:
        return NotConfiguredClient()
    provider = settings.llm_provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        return NotConfiguredClient(
            f"LLM_PROVIDER={provider!r} is not supported (use 'anthropic' or 'openai')"
        )
    mismatch = _model_mismatch(provider, settings)
    if mismatch is not None:
        return NotConfiguredClient(mismatch)

    assert settings.llm_api_key is not None  # llm_configured guarantees this
    if provider == "openai":
        from .openai_client import OpenAIClient

        return OpenAIClient(settings.llm_api_key, reasoning_effort=settings.llm_reasoning_effort)

    from .anthropic_client import AnthropicClient

    return AnthropicClient(settings.llm_api_key)
