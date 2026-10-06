"""Anthropic adapter. Structured output uses a forced tool call, so the model must return JSON
matching the Pydantic schema; the result is then validated again in code."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .client import (
    LLMAuthError,
    LLMBadOutput,
    LLMTimeout,
    LLMUnavailable,
    T,
)

_TOOL_NAME = "record_result"


class AnthropicClient:
    def __init__(self, api_key: str, *, timeout: float = 30.0, client: Any | None = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self._client = client

    async def structured(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 1024
    ) -> T:
        tool = {
            "name": _TOOL_NAME,
            "description": "Record the extracted result.",
            "input_schema": schema.model_json_schema(),
        }
        response = await self._call(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                try:
                    return schema.model_validate(block.input)
                except ValidationError as exc:
                    raise LLMBadOutput(f"structured output failed validation: {exc}") from exc
        raise LLMBadOutput("model returned no structured result")

    async def generate(
        self, *, model: str, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        response = await self._call(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise LLMBadOutput("model returned no text")
        return text

    async def _call(self, **kwargs: Any) -> Any:
        try:
            return await self._client.messages.create(**kwargs)
        except Exception as exc:
            # Classify by name so we do not depend on the SDK's exception hierarchy.
            name = type(exc).__name__
            detail = f"{name}: {str(exc)[:200]}"
            if "Timeout" in name:
                raise LLMTimeout(detail) from exc
            if "Authentication" in name or "PermissionDenied" in name:
                raise LLMAuthError(
                    "The LLM provider rejected the API key. Check LLM_API_KEY and the model name."
                ) from exc
            raise LLMUnavailable(detail) from exc
