"""OpenAI adapter (Chat Completions). Structured output uses a forced function call, the same
approach as the Anthropic adapter: the model must return JSON for the Pydantic schema, and the
result is validated again in code. A malformed answer becomes LLMBadOutput, so the caller falls
back deterministically exactly as it does for any other provider."""

from __future__ import annotations

import json
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

# Reasoning-style models (the gpt-5 family and the o-series) count their hidden reasoning tokens
# against the output cap, so a small cap can be used up entirely on reasoning and leave an empty
# answer. These models get extra room; other models are capped exactly as asked.
_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
_REASONING_HEADROOM = 2048


def is_reasoning_model(model: str) -> bool:
    return model.lower().startswith(_REASONING_PREFIXES)


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 45.0,
        reasoning_effort: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            import openai

            client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self._client = client
        self._reasoning_effort = reasoning_effort

    def _params(self, model: str, max_tokens: int) -> dict[str, Any]:
        reasoning = is_reasoning_model(model)
        params: dict[str, Any] = {
            "model": model,
            # `max_completion_tokens` is accepted by every current chat model; the older
            # `max_tokens` is rejected by the reasoning models.
            "max_completion_tokens": max_tokens + (_REASONING_HEADROOM if reasoning else 0),
        }
        if reasoning and self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        return params

    async def structured(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 1024
    ) -> T:
        tool = {
            "type": "function",
            "function": {
                "name": _TOOL_NAME,
                "description": "Record the extracted result.",
                "parameters": schema.model_json_schema(),
            },
        }
        response = await self._call(
            **self._params(model, max_tokens),
            messages=_messages(system, user),
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
        )
        choice = _first_choice(response)
        for call in getattr(choice.message, "tool_calls", None) or []:
            function = getattr(call, "function", None)
            if function is None or getattr(function, "name", None) != _TOOL_NAME:
                continue
            try:
                payload = json.loads(function.arguments)
            except (TypeError, ValueError) as exc:
                raise LLMBadOutput("model returned arguments that are not valid JSON") from exc
            try:
                return schema.model_validate(payload)
            except ValidationError as exc:
                raise LLMBadOutput(f"structured output failed validation: {exc}") from exc
        raise LLMBadOutput("model returned no structured result")

    async def generate(
        self, *, model: str, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        response = await self._call(
            **self._params(model, max_tokens), messages=_messages(system, user)
        )
        choice = _first_choice(response)
        text = (getattr(choice.message, "content", None) or "").strip()
        if not text:
            truncated = getattr(choice, "finish_reason", None) == "length"
            raise LLMBadOutput(
                "model returned no text" + (" (stopped at the token limit)" if truncated else "")
            )
        return text

    async def _call(self, **kwargs: Any) -> Any:
        try:
            return await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Classify by name so we do not depend on the SDK's exception hierarchy. The first
            # 200 characters keep the provider's own explanation (an unknown model, a billing
            # or quota problem) visible to whoever runs the smoke script.
            name = type(exc).__name__
            detail = f"{name}: {str(exc)[:200]}"
            if "Timeout" in name:
                raise LLMTimeout(detail) from exc
            if "Authentication" in name or "PermissionDenied" in name:
                raise LLMAuthError(
                    "The LLM provider rejected the API key. Check LLM_API_KEY and the model name."
                ) from exc
            raise LLMUnavailable(detail) from exc


def _messages(system: str, user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _first_choice(response: Any) -> Any:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise LLMBadOutput("model returned no choices")
    return choices[0]
