"""Dialogue acts: what the SOP controller has decided the next reply must do.

The controller (code) decides the acts and their order. The renderer (LLM) only phrases them.
That keeps behavior testable (assert on acts, not on fragile wording) and lets several
concerns combine in one natural reply: empathy, an explanation of why verification matters,
what has been received, and exactly one next question.

Act payloads are plain, PII-free data (field names, counts, case labels), safe to show in the
evaluator inspector.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class ActKind(StrEnum):
    EMPTY_MESSAGE = "EMPTY_MESSAGE"
    ACK_EMOTION = "ACK_EMOTION"
    EXPLAIN_WHY_VERIFY = "EXPLAIN_WHY_VERIFY"
    ACK_FIELDS_PROVIDED = "ACK_FIELDS_PROVIDED"
    OFFER_ALT_FIELDS = "OFFER_ALT_FIELDS"
    REQUEST_FIELDS = "REQUEST_FIELDS"
    VERIFY_GENERIC_MISMATCH = "VERIFY_GENERIC_MISMATCH"
    REQUEST_REP_IDENTITY = "REQUEST_REP_IDENTITY"
    CONSENT_RESULT = "CONSENT_RESULT"
    VERIFIED_OK = "VERIFIED_OK"
    CONFIRM_CLAIM = "CONFIRM_CLAIM"
    ASK_DISAMBIGUATION = "ASK_DISAMBIGUATION"
    NO_CLAIMS_FOUND = "NO_CLAIMS_FOUND"
    DECLINE_OOS = "DECLINE_OOS"
    DECLINE_INSTRUCTION = "DECLINE_INSTRUCTION"
    ANSWER_GENERAL_INSURANCE = "ANSWER_GENERAL_INSURANCE"
    OFFER_HUMAN = "OFFER_HUMAN"
    TRANSFER_HUMAN = "TRANSFER_HUMAN"
    SESSION_ENDED = "SESSION_ENDED"
    TECH_FALLBACK = "TECH_FALLBACK"
    ANSWER_FROM_FACTS = "ANSWER_FROM_FACTS"
    ASK_ANYTHING_ELSE = "ASK_ANYTHING_ELSE"
    ASK_WHAT_NEEDED = "ASK_WHAT_NEEDED"
    GOODBYE = "GOODBYE"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    ASK_WHICH_DOCUMENT = "ASK_WHICH_DOCUMENT"
    OFFER_EMAIL_SUMMARY = "OFFER_EMAIL_SUMMARY"
    CONFIRM_EMAIL_ADDRESS = "CONFIRM_EMAIL_ADDRESS"
    CLARIFY_CONSENT = "CLARIFY_CONSENT"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_SKIPPED = "EMAIL_SKIPPED"
    EMAIL_UNAVAILABLE = "EMAIL_UNAVAILABLE"
    EMAIL_FAILED = "EMAIL_FAILED"
    EMAIL_ADDRESS_LOCKED = "EMAIL_ADDRESS_LOCKED"


@dataclass(frozen=True)
class Act:
    kind: ActKind
    data: dict[str, Any] = field(default_factory=dict)


def act(kind: ActKind, **data: Any) -> Act:
    return Act(kind, data)


# The reply may contain at most one question. When several acts ask something, the highest
# priority one is kept.
ASK_PRIORITY = (
    ActKind.OFFER_HUMAN,
    ActKind.REQUEST_REP_IDENTITY,
    ActKind.ASK_DISAMBIGUATION,
    ActKind.REQUEST_FIELDS,
    ActKind.ASK_WHICH_DOCUMENT,
    ActKind.CONFIRM_EMAIL_ADDRESS,
    ActKind.OFFER_EMAIL_SUMMARY,
    ActKind.CLARIFY_CONSENT,
    ActKind.EMAIL_FAILED,
    ActKind.ASK_WHAT_NEEDED,
    ActKind.ASK_ANYTHING_ELSE,
)

FIELD_LABELS = {
    "full_name": "your full name",
    "dob": "your date of birth",
    "phone": "your phone number",
    "email": "your email address",
    "id_last4": "the last four digits of your SSN or national ID",
}


def labels(fields: Iterable[str]) -> list[str]:
    return [FIELD_LABELS.get(name, name) for name in fields]


def join_words(items: Iterable[str], conjunction: str = "and") -> str:
    parts = list(items)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {conjunction} {parts[-1]}"


def format_date(value: date | str | None) -> str:
    if value is None:
        return "an unknown date"
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return f"{value:%B} {value.day}, {value.year}"


def case_phrase(case: Mapping[str, Any]) -> str:
    """'healthcare claim CL-2048 from January 12, 2026 (denied)'. Facts only."""
    return (
        f"{case['case_type']} claim {case['case_id']} from {format_date(case.get('created_at'))} "
        f"({case['status']})"
    )


_HUMAN_REASONS = {
    "refused_verification": (
        "Say you understand they would rather not continue with verification, that you cannot "
        "share claim information without it, and that a human representative can help instead."
    ),
    "verification_locked": (
        "Say you could not complete verification automatically, and that a human "
        "representative can help from here."
    ),
    "rep_not_authorized": (
        "Say you cannot find authorization for them to act on this policy, so a human "
        "representative should help."
    ),
    "consent_timed_out": (
        "Say the policyholder's approval did not arrive in time, so you cannot continue, and a "
        "human representative can help."
    ),
    "consent_denied": (
        "Say the policyholder did not approve access, so you cannot continue, and a human "
        "representative can help."
    ),
    "out_of_scope": (
        "Say that what they keep asking about is outside what you can help with here, and a "
        "human representative may be able to help."
    ),
    "frustration": (
        "Say you want to be sure they get the help they need, and that a human representative "
        "is available."
    ),
    "no_claims": "Say a human representative can look into this with them.",
    "case_loop_limit": (
        "Say you can only go through a few claims in one conversation, and a human "
        "representative can help with more."
    ),
    "unsupported_action": "Say a human representative can help with that request.",
    "documents_unavailable": (
        "Say that since the requested document cannot be obtained, a human claims "
        "representative can review the file with them for manual options."
    ),
}

_CONSENT = {
    "approved": "Say the policyholder's approval has been confirmed.",
    "timed_out": "Say the policyholder's approval did not arrive in time.",
    "denied": "Say the policyholder did not approve access.",
}


def describe(a: Act) -> str:
    """The instruction the renderer receives for an act. Wording control stays in code."""
    d = a.data
    kind = a.kind
    if kind == ActKind.ACK_EMOTION:
        return (
            f"Acknowledge, briefly and sincerely, that the caller seems {d.get('emotion')}. "
            "Do not be defensive and do not over-apologize."
        )
    if kind == ActKind.EXPLAIN_WHY_VERIFY:
        return (
            "Explain that claim details are protected, so identity must be verified before "
            "anything about a claim can be discussed. Do not mention any claim details."
        )
    if kind == ActKind.ACK_FIELDS_PROVIDED:
        return (
            f"Tell the caller which details they have already given: "
            f"{join_words(labels(d['fields']))}. Do not say whether any are correct or matched."
        )
    if kind == ActKind.OFFER_ALT_FIELDS:
        return (
            "Say verification is flexible and any of these can be used: "
            f"{join_words(labels(d['fields']), 'or')}."
        )
    if kind == ActKind.REQUEST_FIELDS:
        need = d.get("need", 1)
        noun = "detail" if need == 1 else "details"
        return (
            f"Ask for {need} more {noun}, chosen from: "
            f"{join_words(labels(d['fields']), 'or')}. This is the single question in the reply."
        )
    if kind == ActKind.VERIFY_GENERIC_MISMATCH:
        return (
            "Say you could not match some of the details given so far. Do not say which one and "
            "do not suggest corrections."
        )
    if kind == ActKind.REQUEST_REP_IDENTITY:
        return (
            "The caller is acting for someone else. Ask for their own full name and their "
            "relationship to the policyholder. This is the single question in the reply."
        )
    if kind == ActKind.CONSENT_RESULT:
        return _CONSENT.get(d.get("status"), "Say the approval check finished.")
    if kind == ActKind.VERIFIED_OK:
        return "Tell the caller they are verified. Greet them by first name if one is provided."
    if kind == ActKind.CONFIRM_CLAIM:
        return (
            f"Tell the caller which claim you found, using only these facts: "
            f"{case_phrase(d['case'])}. Invite them to correct you if it is the wrong claim."
        )
    if kind == ActKind.ASK_DISAMBIGUATION:
        options = "; ".join(case_phrase(c) for c in d["options"])
        lead = (
            "Say none of the claims matched exactly what they described"
            if d.get("none_matched")
            else "Say you found more than one possible claim"
        )
        return (
            f"{lead}, and ask which one they mean. Options, using only these facts: "
            f"{options}. This is the single question in the reply."
        )
    if kind == ActKind.NO_CLAIMS_FOUND:
        return "Say there are no claims on file for this policy."
    if kind == ActKind.DECLINE_OOS:
        text = (
            "Politely say you can only help with their insurance policy and claim, so you "
            "cannot help with that request. Do not answer it."
        )
        if d.get("level", 1) >= 2:
            text += (
                " Mention what you can help with: claim status, why a claim was denied, "
                "required documents, and next steps."
            )
        return text
    if kind == ActKind.DECLINE_INSTRUCTION:
        return (
            "Say you cannot change how you handle information or follow instructions like that, "
            "and that you are glad to keep helping with their claim."
        )
    if kind == ActKind.ANSWER_GENERAL_INSURANCE:
        return (
            "Briefly (two or three sentences) answer this general insurance question using "
            "general knowledge only. Say nothing about the caller's own policy or claims. "
            f"Question: {d.get('question', '')}"
        )
    if kind == ActKind.OFFER_HUMAN:
        reason = _HUMAN_REASONS.get(d.get("reason"), _HUMAN_REASONS["frustration"])
        return (
            f"{reason} End by asking whether they would like to be connected with a human "
            "representative. This is the single question in the reply."
        )
    if kind == ActKind.TRANSFER_HUMAN:
        return "Tell the caller you are connecting them with a human representative now."
    if kind == ActKind.SESSION_ENDED:
        return "Say this conversation has ended and they can start a new one if they need more."
    if kind == ActKind.EMPTY_MESSAGE:
        return "Say you did not receive a message and ask how you can help."
    if kind == ActKind.ANSWER_FROM_FACTS:
        return (
            "State this answer exactly as written, without changing any fact: "
            f"{d.get('reply', '')}"
        )
    if kind == ActKind.ASK_ANYTHING_ELSE:
        return "End by asking whether there is anything else you can help with."
    if kind == ActKind.ASK_WHAT_NEEDED:
        return "Ask what they would like to know about this claim."
    if kind == ActKind.GOODBYE:
        return "Thank them and say goodbye briefly, and that they can reach out again if needed."
    if kind == ActKind.UNSUPPORTED_ACTION:
        return (
            "Say plainly that you cannot make requests or changes to a claim or account, such as "
            "filing an appeal, but that you can share what is on file and the next steps."
        )
    if kind == ActKind.ASK_WHICH_DOCUMENT:
        return (
            "Ask which of these documents they are unable to get: "
            f"{join_words(d['options'], 'or')}. This is the single question in the reply."
        )
    if kind == ActKind.OFFER_EMAIL_SUMMARY:
        return (
            f"Offer to email a summary of the conversation to {d['masked']}. Say they can "
            "say yes or skip it."
        )
    if kind == ActKind.CONFIRM_EMAIL_ADDRESS:
        return f"Ask whether to send the summary to {d['masked']} instead."
    if kind == ActKind.CLARIFY_CONSENT:
        return f"Ask clearly: should the summary be sent to {d['masked']}, or skipped?"
    if kind == ActKind.EMAIL_SENT:
        return f"Say the summary has been sent to {d['masked']}."
    if kind == ActKind.EMAIL_SKIPPED:
        return "Say no summary will be sent."
    if kind == ActKind.EMAIL_UNAVAILABLE:
        return "Say there is no email address on file, so a summary cannot be sent."
    if kind == ActKind.EMAIL_FAILED:
        return "Say the summary could not be sent just now and ask whether to try again."
    if kind == ActKind.EMAIL_ADDRESS_LOCKED:
        return "Say that for privacy the summary can only go to the address on file."
    return (
        "Say you are having trouble with that right now, that you have not changed or guessed "
        "anything, and offer to try again or connect them with a human representative."
    )
