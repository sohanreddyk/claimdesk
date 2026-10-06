"""Request and response shapes. The customer-facing responses are deliberately tiny: the reply
text and whether the conversation has ended. Phase, acts and state never leave the server
except through the (default-off) debug inspector."""

from __future__ import annotations

from agent.understanding import MAX_MESSAGE_CHARS
from pydantic import BaseModel, Field, field_validator


class CreateSessionRequest(BaseModel):
    # Honored only when the debug inspector is enabled; ignored otherwise.
    consent_scenario: str | None = Field(default=None, max_length=50)


class CreateSessionResponse(BaseModel):
    session_id: str
    greeting: str


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=MAX_MESSAGE_CHARS)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class ChatResponse(BaseModel):
    reply: str
    ended: bool
