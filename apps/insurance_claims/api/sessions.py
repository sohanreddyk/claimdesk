"""In-memory sessions for the HTTP layer.

Each session owns its own agent, state and outbox, so one caller's data (and the emails sent
to them) can never appear in another session. Ids are unguessable, idle sessions expire, and
the number of sessions and turns is capped so memory and cost cannot grow without bound.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from agent.clock import Clock
from agent.config import Settings
from agent.consent import ConsentGateway
from agent.controller import SopAgent, TurnResult
from agent.fixtures import FixtureError, FixtureStore
from agent.llm.client import LLMClient
from agent.outbox import Outbox
from agent.state import Phase, State, Turn

log = logging.getLogger("claims.api")

# Fixed opening. It names no one and shows nothing from the claim data: it only says what the
# agent can help with and what it needs to verify, including that any two of the listed
# details are enough (plus the name), so the three-factor rule is clear from the first turn.
GREETING = (
    "Hi, I’m the insurance claims support assistant. I can help with claim status, denials, "
    "documents, and next steps. Before I can discuss claim details, I’ll need to verify your "
    "identity. Please share your full name and any two of the following: date of birth, phone "
    "number, email, or the last four digits of your SSN or national ID. You can also include "
    "your policy number if you have it."
)

TURN_LIMIT_REPLY = (
    "This conversation has reached its length limit, so I can't continue it. Please start a "
    "new conversation if you need more help."
)


class SessionLimitError(RuntimeError):
    """Too many live sessions."""


class UnknownScenarioError(ValueError):
    """The requested consent scenario does not exist."""


@dataclass(frozen=True)
class SessionLimits:
    idle_seconds: float = 2 * 60 * 60
    max_sessions: int = 200
    max_turns: int = 100


@dataclass
class Session:
    state: State
    agent: SopAgent
    outbox: Outbox
    last_seen: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one turn at a time per session
    turns: int = 0
    last_result: TurnResult | None = None
    turn_limit_reached: bool = False

    @property
    def ended(self) -> bool:
        return self.state.phase == Phase.COMPLETE or self.turn_limit_reached


class SessionStore:
    def __init__(
        self,
        *,
        store: FixtureStore,
        settings: Settings,
        llm: LLMClient,
        clock: Clock,
        limits: SessionLimits,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._settings = settings
        self._llm = llm
        self._clock = clock
        self.limits = limits
        self._now = now
        self._sessions: dict[str, Session] = {}
        # Built once. A bad CONSENT_SCENARIO fails at startup, not on the first caller.
        self._consents: dict[str, ConsentGateway] = {
            settings.consent_scenario: ConsentGateway.from_store(
                store, settings.consent_scenario, settings.max_consent_polls
            )
        }

    def __len__(self) -> int:
        return len(self._sessions)

    def _gateway(self, scenario: str) -> ConsentGateway:
        gateway = self._consents.get(scenario)
        if gateway is None:
            try:
                gateway = ConsentGateway.from_store(
                    self._store, scenario, self._settings.max_consent_polls
                )
            except FixtureError as exc:
                raise UnknownScenarioError(scenario) from exc
            self._consents[scenario] = gateway
        return gateway

    def _purge_expired(self) -> None:
        now = self._now()
        stale = [
            sid
            for sid, session in self._sessions.items()
            if now - session.last_seen > self.limits.idle_seconds
        ]
        for sid in stale:
            del self._sessions[sid]

    def create(self, scenario: str | None = None) -> tuple[str, Session]:
        """Start a session. Nothing here reads claim data: the new state is empty, and the only
        thing added is the fixed greeting."""
        self._purge_expired()
        if len(self._sessions) >= self.limits.max_sessions:
            raise SessionLimitError("too many active sessions")
        gateway = self._gateway(scenario or self._settings.consent_scenario)
        session_id = secrets.token_urlsafe(16)
        outbox = Outbox()
        agent = SopAgent(
            store=self._store,
            settings=self._settings,
            llm=self._llm,
            clock=self._clock,
            consent=gateway,
            sender=outbox,
        )
        state = agent.new_state(session_id)
        state.history.append(Turn(role="assistant", content=GREETING))
        session = Session(state=state, agent=agent, outbox=outbox, last_seen=self._now())
        self._sessions[session_id] = session
        log.info("session created id=%s", session_id[:8])
        return session_id, session

    def get(self, session_id: str, *, touch: bool = True) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._now() - session.last_seen > self.limits.idle_seconds:
            del self._sessions[session_id]
            return None
        if touch:
            session.last_seen = self._now()
        return session
