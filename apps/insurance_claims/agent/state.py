"""Server-side conversation state.

The state is the single source of truth. Only code mutates it, and the guarded methods here
(`set_phase`, `mark_verified`) make the SOP's hard rules impossible to violate by accident:
no phase past VERIFY_ID without verification, no PROCESS_CASE without a resolved case,
no representative access without approved consent.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .audit import AuditEvent, scrub

FACTOR_NAMES = ("full_name", "dob", "phone", "email", "id_last4")


class SopViolation(RuntimeError):
    """An attempted state change that the SOP forbids."""


class Phase(StrEnum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    COMPLETE = "COMPLETE"


ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.VERIFY_ID: {Phase.RESOLVE_INTENT, Phase.COMPLETE},
    Phase.RESOLVE_INTENT: {Phase.PROCESS_CASE, Phase.COMPLETE},
    Phase.PROCESS_CASE: {Phase.POST_PROCESS, Phase.RESOLVE_INTENT, Phase.COMPLETE},
    Phase.POST_PROCESS: {Phase.PROCESS_CASE, Phase.RESOLVE_INTENT, Phase.COMPLETE},
    Phase.COMPLETE: set(),
}

_REQUIRES_VERIFICATION = {Phase.RESOLVE_INTENT, Phase.PROCESS_CASE, Phase.POST_PROCESS}


class ConsentState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class EmailState(StrEnum):
    NOT_OFFERED = "not_offered"
    OFFERED = "offered"
    ADDRESS_CONFIRM = "address_confirm"
    SENT = "sent"
    SKIPPED = "skipped"


CallerRole = Literal["policyholder", "representative", "unknown"]
VerifiedAs = Literal["policyholder", "representative"]


class CaseHints(BaseModel):
    """Details about the caller's claim, remembered from any phase."""

    case_type: str | None = None
    status: str | None = None  # normalized: denied | closed | open
    month: int | None = None
    year: int | None = None
    case_id: str | None = None

    def merge(self, other: CaseHints) -> bool:
        """Overlay non-empty values from `other`. Returns True if anything changed."""
        changed = False
        for name in type(self).model_fields:
            new = getattr(other, name)
            if new is not None and new != getattr(self, name):
                setattr(self, name, new)
                changed = True
        return changed


class CaseRecord(BaseModel):
    """Structured facts about the handled case. The email summary is built from this,
    never from the raw transcript."""

    case_id: str | None = None
    case_type: str | None = None
    status_outcome: str | None = None
    topics_discussed: list[str] = []
    documents_needed: list[str] = []
    appeal_deadline: date | None = None
    unavailable_documents: list[str] = []  # documents the caller said they cannot get
    human_review_offered: bool = False  # alternatives ran out and a human was offered
    facts_used: list[str] = []


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class State(BaseModel):
    session_id: str
    phase: Phase = Phase.VERIFY_ID

    # Captured account-holder factors (raw values; masked everywhere outside the matcher)
    factors: dict[str, str] = {}
    id_kind_hint: Literal["ssn", "national_id", "unspecified"] | None = None
    policy_number: str | None = None  # lookup key, never counts as a factor
    caller_role: CallerRole = "unknown"
    rep_name: str | None = None
    rep_relationship: str | None = None
    refused_fields: set[str] = set()

    # Verification
    candidate_party_id: str | None = None
    matched_factors: set[str] = set()  # inspector only; never spoken to the caller
    mismatch_count: int = 0
    counted_mismatches: set[str] = set()  # hashed (factor, value) pairs already counted
    verified: bool = False
    verified_party_id: str | None = None
    verified_as: VerifiedAs | None = None
    consent: ConsentState = ConsentState.NOT_REQUESTED
    consent_trail: list[str] = []
    consent_party_id: str | None = None  # party the consent request was issued for

    # Cross-phase memory: remembered when said, acted on only when the phase allows
    intent_hint: str | None = None
    case_hints: CaseHints = Field(default_factory=CaseHints)

    # Resolution and handled case
    resolved_case_id: str | None = None
    last_resolution: str | None = None  # unique | ambiguous | no_match | no_claims
    case_record: CaseRecord = Field(default_factory=CaseRecord)
    closed_cases: list[CaseRecord] = []  # notes on claims the caller moved away from

    # Emotion, scope and escalation counters
    emotion: str = "neutral"
    severity: int = 0
    refusal_count: int = 0
    frustration_streak: int = 0
    oos_strikes: int = 0
    oos_clear_turns: int = 0  # consecutive in-scope turns; two of them clear the strikes
    case_loops: int = 0
    doc_unavailable: set[str] = set()
    human_offered: bool = False
    human_transferred: bool = False

    # Post-process
    email_state: EmailState = EmailState.NOT_OFFERED
    email_address: str | None = None  # the address under discussion (pending or chosen)
    email_alt_attempts: int = 0  # different addresses the caller proposed and then rejected

    # Conversation
    last_expected_fields: list[str] = []
    history: list[Turn] = []
    events: list[AuditEvent] = []

    # ---- audit -------------------------------------------------------------------

    def record(self, type: str, **data: Any) -> AuditEvent:
        event = AuditEvent(seq=len(self.events) + 1, type=type, data=scrub(data))
        self.events.append(event)
        return event

    # ---- factors -----------------------------------------------------------------

    def set_factor(self, name: str, value: str) -> bool:
        """Store a captured factor. Returns True if the stored value changed."""
        if name not in FACTOR_NAMES:
            raise ValueError(f"unknown factor: {name}")
        value = value.strip()
        if not value:
            return False
        changed = self.factors.get(name) != value
        self.factors[name] = value
        return changed

    # ---- guarded transitions -----------------------------------------------------

    def mark_verified(self, party_id: str, as_: VerifiedAs, *, min_factors: int) -> None:
        if len(self.matched_factors) < min_factors:
            raise SopViolation(
                f"cannot verify: {len(self.matched_factors)} matched factors, need {min_factors}"
            )
        if as_ == "representative" and self.consent != ConsentState.APPROVED:
            raise SopViolation("cannot verify a representative without approved consent")
        self.verified = True
        self.verified_party_id = party_id
        self.verified_as = as_
        self.record(
            "IDENTITY_VERIFIED",
            matched_factor_count=len(self.matched_factors),
            verified_as=as_,
        )

    def set_phase(self, new: Phase, reason: str = "") -> None:
        old = self.phase
        if new == old:
            return
        if new not in ALLOWED_TRANSITIONS[old]:
            raise SopViolation(f"illegal transition {old.value} -> {new.value}")
        if new in _REQUIRES_VERIFICATION and not self.verified:
            raise SopViolation(f"cannot enter {new.value} before identity is verified")
        if new == Phase.PROCESS_CASE and not self.resolved_case_id:
            raise SopViolation("cannot enter PROCESS_CASE without a resolved case")
        self.phase = new
        self.record("PHASE_TRANSITION", **{"from": old.value, "to": new.value, "reason": reason})
