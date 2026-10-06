"""Deterministic stand-in for an LLM, for tests and offline development.

Queue the structured results and texts it should return; every call is recorded so tests can
assert on exactly what was sent (for example, that no claim data ever reached a prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from .client import LLMUnavailable, T


@dataclass(frozen=True)
class LLMCall:
    kind: Literal["structured", "generate"]
    model: str
    system: str
    user: str
    schema: str | None = None


class ScriptedLLM:
    def __init__(self) -> None:
        self.calls: list[LLMCall] = []
        self._structured: list[BaseModel | dict | Exception] = []
        self._texts: list[str | Exception] = []

    def queue_structured(self, *items: BaseModel | dict | Exception) -> None:
        self._structured.extend(items)

    def queue_text(self, *items: str | Exception) -> None:
        self._texts.extend(items)

    @property
    def prompts(self) -> list[str]:
        """Everything that was sent to the model, system and user parts together."""
        return [f"{call.system}\n{call.user}" for call in self.calls]

    async def structured(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 1024
    ) -> T:
        self.calls.append(LLMCall("structured", model, system, user, schema.__name__))
        if not self._structured:
            raise LLMUnavailable("ScriptedLLM has no queued structured result")
        item = self._structured.pop(0)
        if isinstance(item, Exception):
            raise item
        data = item.model_dump() if isinstance(item, BaseModel) else item
        return schema.model_validate(data)

    async def generate(
        self, *, model: str, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        self.calls.append(LLMCall("generate", model, system, user))
        if not self._texts:
            raise LLMUnavailable("ScriptedLLM has no queued text")
        item = self._texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
