"""Builds the configured LLM client."""

from __future__ import annotations

from ..config import Settings
from .client import LLMClient, NotConfiguredClient


def build_llm(settings: Settings) -> LLMClient:
    """Return a real client when a key is configured, otherwise a stand-in that raises a clear
    LLMNotConfigured on first use. The app itself must still boot without a key."""
    if not settings.llm_configured:
        return NotConfiguredClient()
    provider = settings.llm_provider.lower()
    if provider != "anthropic":
        return NotConfiguredClient(f"LLM_PROVIDER={provider!r} is not supported (use 'anthropic')")

    from .anthropic_client import AnthropicClient

    assert settings.llm_api_key is not None  # llm_configured guarantees this
    return AnthropicClient(settings.llm_api_key)
