"""Where summary emails go. Simulated: an in-memory outbox the UI and inspector can show.

The sender is a small interface, so a real SMTP sender could replace the outbox without
touching the rest of the code. The outbox keeps the full recipient server-side; anything shown
to a person goes through `public_view`, which masks it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .masking import mask_email


class EmailSendError(RuntimeError):
    """Sending failed. The caller is told, and the offer stays open."""


@dataclass(frozen=True)
class SentEmail:
    session_id: str
    to: str
    subject: str
    body: str

    def public_view(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "to": mask_email(self.to),
            "subject": self.subject,
            "body": self.body,
        }


class EmailSender(Protocol):
    def send(self, email: SentEmail) -> None: ...


class Outbox:
    """Collects sent emails in memory."""

    def __init__(self) -> None:
        self._sent: list[SentEmail] = []

    def send(self, email: SentEmail) -> None:
        self._sent.append(email)

    def sent(self, session_id: str | None = None) -> list[SentEmail]:
        if session_id is None:
            return list(self._sent)
        return [email for email in self._sent if email.session_id == session_id]


class FailingSender:
    """Always fails. For exercising the failure path in tests and demos."""

    def send(self, email: SentEmail) -> None:
        raise EmailSendError("the mail service is unavailable")
