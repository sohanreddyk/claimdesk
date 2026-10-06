"""Provider-agnostic LLM interface.

The SOP code only ever depends on this Protocol. Two operations are enough:
- `structured`: get a validated Pydantic object back (used for turn understanding);
- `generate`: get plain text back (used for phrasing replies).

Every failure is mapped to an `LLMError` subclass so callers can fall back deterministically.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Base class for every LLM failure."""


class LLMNotConfigured(LLMError):
    """No usable API key or provider. The app still boots; the UI asks for a key."""


class LLMAuthError(LLMError):
    """The provider rejected the credentials."""


class LLMTimeout(LLMError):
    """The provider did not answer in time."""


class LLMUnavailable(LLMError):
    """The provider failed or could not be reached."""


class LLMBadOutput(LLMError):
    """The model answered, but not with usable structured output."""


class LLMClient(Protocol):
    async def structured(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 1024
    ) -> T: ...

    async def generate(
        self, *, model: str, system: str, user: str, max_tokens: int = 1024
    ) -> str: ...


class NotConfiguredClient:
    """Stands in when no API key is set, so the rest of the app can run and report clearly."""

    def __init__(self, reason: str = "LLM_API_KEY is not set") -> None:
        self._reason = reason

    async def structured(
        self, *, model: str, system: str, user: str, schema: type[T], max_tokens: int = 1024
    ) -> T:
        raise LLMNotConfigured(self._reason)

    async def generate(
        self, *, model: str, system: str, user: str, max_tokens: int = 1024
    ) -> str:
        raise LLMNotConfigured(self._reason)
