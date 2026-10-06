"""Turn understanding: one customer message in, validated and grounded structured facts out.

The LLM proposes; code decides what to believe:
- Identity values found by the deterministic pre-pass win over the LLM's.
- An LLM-only value is kept only if it is a usable instance of that factor and is actually
  grounded in the message text. A hallucinated value could otherwise cost a genuine caller a
  verification strike, or worse.
- Which kind of ID the caller named (SSN or national ID) is derived from keywords in code; the
  LLM is not asked and cannot influence it.
- Escalation does not depend on the LLM: a regex catches plain requests for a human.
- If the LLM is unavailable the pre-pass facts are still returned, so verification keeps
  working and the caller is never stuck.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from .config import Settings
from .llm.client import LLMBadOutput, LLMClient, LLMError
from .llm.prompts import EXTRACTION_SYSTEM, build_extraction_user
from .normalize import (
    fold,
    name_tokens,
    normalize_dob,
    normalize_email,
    normalize_id_last4,
    normalize_phone,
)
from .prepass import IdKind, Prepass, has_loose_id_cue, prepass, spoken_to_written
from .state import CallerRole, CaseHints, EmailState, State

Intent = Literal[
    "status_inquiry",
    "denial_question",
    "document_submission",
    "next_steps",
    "general_claim_question",
]
Emotion = Literal["neutral", "frustrated", "angry", "anxious", "confused", "sad"]
Scope = Literal["in_scope", "insurance_general", "out_of_scope", "injection_attempt"]
FactorName = Literal["full_name", "dob", "phone", "email", "id_last4"]
CaseStatus = Literal["denied", "closed", "open"]

MAX_MESSAGE_CHARS = 4000


class LLMExtraction(BaseModel):
    """What the LLM is asked to return. Flat on purpose: simple schemas are followed reliably."""

    # identity of the ACCOUNT HOLDER, values as the caller said them
    full_name: str | None = Field(default=None, description="Account holder's full name")
    dob: str | None = Field(default=None, description="ISO yyyy-mm-dd, only if complete")
    phone: str | None = None
    email: str | None = None
    id_last4: str | None = Field(default=None, description="Last 4 digits of SSN/national ID")
    policy_number: str | None = None
    caller_role: CallerRole = "unknown"
    rep_name: str | None = Field(default=None, description="Speaker's name if calling for another")
    rep_relationship: str | None = None
    refused_fields: list[FactorName] = Field(default_factory=list)
    refuses_verification: bool = False
    asks_why_verification: bool = False

    # the case
    intents: list[Intent] = Field(default_factory=list)
    hint_case_type: str | None = None
    hint_status: CaseStatus | None = None
    hint_month: int | None = Field(default=None, ge=1, le=12)
    hint_year: int | None = None
    hint_case_id: str | None = None
    followup_topics: list[str] = Field(default_factory=list)
    cannot_obtain_documents: list[str] = Field(default_factory=list)
    claim_switch_request: str | None = None

    # tone, scope and control
    emotion: Emotion = "neutral"
    severity: int = Field(default=0, ge=0, le=3)
    scope: Scope = "in_scope"
    wants_human: bool = False
    distress_or_emergency: bool = False
    user_done: bool = False
    human_offer_response: Literal["yes", "no", "not_applicable"] = "not_applicable"
    email_consent: Literal["yes", "no", "unclear", "not_applicable"] = "not_applicable"
    alt_email: str | None = None


class TurnUnderstanding(LLMExtraction):
    """The validated result the rest of the system uses. Adds code-derived fields."""

    id_kind_hint: IdKind | None = None  # from keywords in the message, never from the LLM
    accepts_human_offer: bool = False  # said yes to a human transfer the agent just offered
    llm_used: bool = True
    fallback_reason: str | None = None
    dropped_fields: list[str] = Field(default_factory=list)  # LLM values rejected as ungrounded

    def to_case_hints(self) -> CaseHints:
        case_id = (self.hint_case_id or "").strip().upper() or None
        return CaseHints(
            case_type=normalize_case_type(self.hint_case_type),
            status=self.hint_status,
            month=self.hint_month,
            year=self.hint_year,
            case_id=case_id,
        )


_CASE_TYPE_ALIASES = {
    "health": "healthcare",
    "health care": "healthcare",
    "healthcare": "healthcare",
    "medical": "healthcare",
    "medicine": "healthcare",
    "doctor": "healthcare",
    "hospital": "healthcare",
    "dental": "dental",
    "dentist": "dental",
    "auto": "auto",
    "car": "auto",
    "vehicle": "auto",
    "automobile": "auto",
}


def normalize_case_type(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().casefold()
    if not key:
        return None
    return _CASE_TYPE_ALIASES.get(key, key)


# ---- grounding checks ---------------------------------------------------------------

_MONTHS = (
    "january february march april may june july august september october november december"
).split()
_ORDINALS = (
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth "
    "twenty-first twenty-second twenty-third twenty-fourth twenty-fifth twenty-sixth "
    "twenty-seventh twenty-eighth twenty-ninth thirtieth thirty-first"
).split()
_SPOKEN_YEAR = re.compile(r"\b(?:nineteen|twenty|two thousand)\b")
_NOT_ID_CONTEXT = re.compile(r"\b(?:phone|cell|mobile|policy|claim|zip)\b", re.IGNORECASE)
_ID_WORDS = re.compile(r"\bssn\b|social|national|\bid\b", re.IGNORECASE)
_AFFIRM = re.compile(r"\s*(?:yes|yeah|yep|sure|please|ok|okay)\b", re.IGNORECASE)
_HUMAN_REQUEST = re.compile(
    r"(?:speak|talk|connect|transfer|put me)\b[^.?!]{0,40}\b"
    r"(?:human|person|representative|rep|agent|supervisor|manager|someone)\b"
    r"|\breal person\b|\bhuman being\b|\bliving person\b",
    re.IGNORECASE,
)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _dob_supported(iso: str, written: str) -> bool:
    """A spoken or oddly formatted DOB from the LLM must show its month, day and year in the
    message, so a hallucinated day cannot become a verification strike."""
    year, month, day = (int(part) for part in iso.split("-"))
    low = written.casefold()
    has_month = re.search(rf"\b{_MONTHS[month - 1][:3]}[a-z]*\b", low) is not None
    ordinal = _ORDINALS[day - 1]
    day_forms = {ordinal, ordinal.replace("-", " ")}
    has_day = re.search(rf"(?<!\d){day}(?:st|nd|rd|th)?(?!\d)", low) is not None or any(
        form in low for form in day_forms
    )
    has_year = re.search(rf"(?<!\d){year}(?!\d)", low) is not None or bool(_SPOKEN_YEAR.search(low))
    return has_month and has_day and has_year


def _id_context_blocks(id4: str, written: str) -> bool:
    """True if these four digits sit right after words like 'phone' or 'policy' and nothing
    names an ID, so they are probably not an ID last-four."""
    match = re.search(rf"(?<!\d){id4}(?!\d)", written)
    if match is None:
        return False
    context = written[max(0, match.start() - 45) : match.start()]
    return bool(_NOT_ID_CONTEXT.search(context)) and not _ID_WORDS.search(context)


def _llm_dob(value: str | None, written: str, dropped: list[str]) -> str | None:
    if not value:
        return None
    iso = normalize_dob(value)
    if iso is None or not _dob_supported(iso, written):
        dropped.append("dob")
        return None
    return iso


def _llm_phone(value: str | None, written: str, dropped: list[str]) -> str | None:
    if not value:
        return None
    phone = normalize_phone(value)
    if phone is None or phone not in _digits(written):
        dropped.append("phone")
        return None
    return phone


def _llm_email(
    value: str | None, written: str, dropped: list[str], label: str = "email"
) -> str | None:
    if not value:
        return None
    email = normalize_email(value)
    if email is None or email not in written.casefold():
        dropped.append(label)
        return None
    return email


def _llm_policy(value: str | None, written: str, dropped: list[str]) -> str | None:
    if not value:
        return None
    digits = _digits(value)
    letters = re.sub(r"[^A-Za-z]", "", value)
    low = written.casefold()
    grounded = (
        len(digits) >= 3
        and digits in _digits(written)
        and (not letters or letters.lower() in low)
    )
    if not grounded:
        dropped.append("policy_number")
        return None
    return f"{letters.upper()}-{digits}" if letters else digits


def _llm_id(
    value: str | None,
    written: str,
    expected: Sequence[str],
    phone: str | None,
    dob: str | None,
    dropped: list[str],
) -> str | None:
    if not value:
        return None
    id4 = normalize_id_last4(value)
    asked = "id_last4" in expected
    ok = id4 is not None and id4 in _digits(written)
    if ok and not asked:
        ok = has_loose_id_cue(written)
        if ok and ((phone and id4 in _digits(phone)) or (dob and id4 in _digits(dob))):
            ok = False
        if ok and id4 is not None and _id_context_blocks(id4, written):
            ok = False
    if not ok:
        dropped.append("id_last4")
        return None
    return id4


def _llm_name(value: str | None, folded: str, dropped: list[str], label: str) -> str | None:
    if not value:
        return None
    tokens = name_tokens(value)
    if len(tokens) < 2 or not all(token in folded for token in tokens):
        dropped.append(label)
        return None
    return value.strip()


# ---- merge --------------------------------------------------------------------------


def _merge(
    extraction: LLMExtraction | None,
    fallback_reason: str | None,
    pre: Prepass,
    message: str,
    expected: Sequence[str],
    topics: Sequence[str],
    human_offered: bool,
) -> TurnUnderstanding:
    llm = extraction or LLMExtraction()
    written = spoken_to_written(message)
    folded = fold(written).replace("'", "").replace("\u2019", "")
    dropped: list[str] = []

    dob = pre.dob or _llm_dob(llm.dob, written, dropped)
    phone = pre.phone or _llm_phone(llm.phone, written, dropped)
    email = pre.email or _llm_email(llm.email, written, dropped)
    policy = pre.policy_number or _llm_policy(llm.policy_number, written, dropped)
    id_last4 = pre.id_last4 or _llm_id(llm.id_last4, written, expected, phone, dob, dropped)

    data = llm.model_dump()
    # A plain "yes" to a human-transfer offer must work even when the LLM is down.
    affirmed = llm.human_offer_response == "yes" or (
        extraction is None and _AFFIRM.match(message) is not None
    )
    data.update(
        full_name=_llm_name(llm.full_name, folded, dropped, "full_name"),
        rep_name=_llm_name(llm.rep_name, folded, dropped, "rep_name"),
        dob=dob,
        phone=phone,
        email=email,
        policy_number=policy,
        id_last4=id_last4,
        alt_email=_llm_email(llm.alt_email, written, dropped, "alt_email"),
        followup_topics=list(dict.fromkeys(t for t in llm.followup_topics if t in topics)),
        wants_human=llm.wants_human or bool(_HUMAN_REQUEST.search(message)),
        accepts_human_offer=human_offered and affirmed,
        id_kind_hint=pre.id_kind_hint if id_last4 else None,
        llm_used=extraction is not None,
        fallback_reason=fallback_reason,
        dropped_fields=sorted(set(dropped)),
    )
    return TurnUnderstanding(**data)


# ---- entry point --------------------------------------------------------------------


async def _extract(
    llm: LLMClient, settings: Settings, user_prompt: str
) -> tuple[LLMExtraction | None, str | None]:
    """One retry on malformed output; any other LLM failure falls back immediately."""
    last_failure = "LLMBadOutput"
    for _attempt in range(2):
        try:
            result = await llm.structured(
                model=settings.llm_model_fast,
                system=EXTRACTION_SYSTEM,
                user=user_prompt,
                schema=LLMExtraction,
                max_tokens=900,
            )
            return result, None
        except LLMBadOutput:
            continue
        except LLMError as exc:
            last_failure = type(exc).__name__
            return None, last_failure
    return None, last_failure


def _last_agent_message(state: State) -> str | None:
    for turn in reversed(state.history):
        if turn.role == "assistant":
            return turn.content[:500]
    return None


async def understand_turn(
    llm: LLMClient,
    settings: Settings,
    state: State,
    message: str,
    *,
    allowed_topics: Sequence[str] = (),
    policy_prefixes: Sequence[str] = (),
) -> TurnUnderstanding:
    """Understand one customer message. Never raises for LLM trouble; see `fallback_reason`.

    Only the message, the last agent reply and field-name flags go to the model. No stored PII
    values and, before verification, no claim data and no follow-up topic list."""
    message = message[:MAX_MESSAGE_CHARS]
    expected = tuple(state.last_expected_fields)
    pre = prepass(message, expected_fields=expected, policy_prefixes=policy_prefixes)
    topics = tuple(allowed_topics) if state.verified else ()
    prompt = build_extraction_user(
        phase=state.phase.value,
        last_agent_message=_last_agent_message(state),
        expected_fields=expected,
        provided_fields=tuple(sorted(state.factors)),
        allowed_topics=topics,
        email_offered=state.email_state in (EmailState.OFFERED, EmailState.ADDRESS_CONFIRM),
        human_offered=state.human_offered,
        message=message,
    )
    extraction, reason = await _extract(llm, settings, prompt)
    return _merge(extraction, reason, pre, message, expected, topics, state.human_offered)
