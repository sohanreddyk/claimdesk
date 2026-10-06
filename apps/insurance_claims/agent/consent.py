"""Consent gateway: simulated out-of-band approval from the policyholder.

Used for the representative flow. The status sequence comes from the consent scenario fixture:
each poll consumes the next status (the last one repeats). The first terminal status wins; if
the sequence is still pending after `max_polls`, the request times out. Failing closed is
deliberate: anything that is not an explicit approval never grants access.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fixtures import FixtureStore
from .state import ConsentState

_APPROVED = frozenset({"approved", "granted", "accepted"})
_DENIED = frozenset({"denied", "declined", "rejected", "refused"})


@dataclass(frozen=True)
class ConsentOutcome:
    state: ConsentState
    trail: list[str]  # raw statuses seen, one per poll


def classify(raw_status: str) -> ConsentState:
    status = raw_status.strip().lower()
    if status in _APPROVED:
        return ConsentState.APPROVED
    if status in _DENIED:
        return ConsentState.DENIED
    return ConsentState.PENDING


class ConsentGateway:
    def __init__(self, sequence: list[str], scenario: str, max_polls: int) -> None:
        self._sequence = list(sequence)
        self.scenario = scenario
        self.max_polls = max_polls

    @classmethod
    def from_store(cls, store: FixtureStore, scenario: str, max_polls: int) -> ConsentGateway:
        """Raises FixtureError at startup if the scenario does not exist."""
        return cls(store.consent_sequence(scenario), scenario, max_polls)

    def run(self, party_id: str) -> ConsentOutcome:
        """Issue one approval request for `party_id` and poll it to a terminal state."""
        trail: list[str] = []
        for index in range(self.max_polls):
            if self._sequence:
                raw = self._sequence[min(index, len(self._sequence) - 1)]
            else:
                raw = "pending"
            trail.append(raw)
            state = classify(raw)
            if state in (ConsentState.APPROVED, ConsentState.DENIED):
                return ConsentOutcome(state, trail)
        return ConsentOutcome(ConsentState.TIMED_OUT, trail)
