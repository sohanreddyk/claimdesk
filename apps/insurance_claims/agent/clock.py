"""Injectable clock. No other module may call date.today(); deadline facts come from here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .config import Settings


class Clock(Protocol):
    def today(self) -> date: ...


class SystemClock:
    def today(self) -> date:
        return date.today()


class FixedClock:
    def __init__(self, value: date) -> None:
        self.value = value

    def today(self) -> date:
        return self.value


def clock_from_settings(settings: Settings) -> Clock:
    if settings.as_of_date is not None:
        return FixedClock(settings.as_of_date)
    return SystemClock()


@dataclass(frozen=True)
class DeadlineFacts:
    """Code-computed facts handed to the LLM, so it never does date arithmetic itself."""

    deadline: date
    deadline_passed: bool
    days_until_appeal_deadline: int | None  # None once the deadline has passed
    days_past_deadline: int | None  # None while the deadline is still open


def deadline_facts(deadline: date | None, clock: Clock) -> DeadlineFacts | None:
    """On the deadline day itself the deadline has not passed (0 days remaining)."""
    if deadline is None:
        return None
    delta = (deadline - clock.today()).days
    if delta >= 0:
        return DeadlineFacts(deadline, False, delta, None)
    return DeadlineFacts(deadline, True, None, -delta)
