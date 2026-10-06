"""Deterministic fallback wording for every dialogue act.

Used when the LLM is unavailable, returns something unusable, or has its reply blocked by the
output guard. The agent is plain but always correct, and never stuck.
"""

from __future__ import annotations

from collections.abc import Iterable

from .acts import (
    Act,
    ActKind,
    case_phrase,
    join_words,
    labels,
)

_EMOTION = {
    "frustrated": "I'm sorry for the frustration, and I want to get this sorted out for you.",
    "angry": "I'm sorry this has been so frustrating, and I want to help get it sorted out.",
    "anxious": "I understand this is worrying, and I'll help as best I can.",
    "confused": "I understand this can be confusing, so let me make it as clear as I can.",
    "sad": "I'm sorry you're dealing with this.",
    "distressed": "I'm so sorry you're going through this.",
}

_HUMAN_OFFER = {
    "refused_verification": (
        "I understand you'd rather not continue with verification. I can't share claim "
        "information without it, but a human representative can help instead. "
        "Would you like me to connect you?"
    ),
    "verification_locked": (
        "I wasn't able to complete verification here, but a human representative can help from "
        "this point. Would you like me to connect you?"
    ),
    "rep_not_authorized": (
        "I can't find authorization for you to act on this policy, so a human representative "
        "should help. Would you like me to connect you?"
    ),
    "consent_timed_out": (
        "The policyholder's approval didn't arrive in time, so I can't continue, but a human "
        "representative can help. Would you like me to connect you?"
    ),
    "consent_denied": (
        "The policyholder didn't approve access, so I can't continue, but a human "
        "representative can help. Would you like me to connect you?"
    ),
    "out_of_scope": (
        "That's outside what I can help with here, but a human representative may be able to "
        "help. Would you like me to connect you?"
    ),
    "frustration": (
        "I want to make sure you get the help you need, and a human representative is "
        "available. Would you like me to connect you?"
    ),
    "no_claims": (
        "A human representative can look into this with you. Would you like me to connect you?"
    ),
}

_CONSENT = {
    "approved": "The policyholder's approval has been confirmed.",
    "timed_out": "The policyholder's approval didn't arrive in time.",
    "denied": "The policyholder didn't approve access.",
}


def _request_fields(a: Act) -> str:
    fields = labels(a.data["fields"])
    need = a.data.get("need", 1)
    if need == 1 and len(fields) == 1:
        return f"Could you share {fields[0]}?"
    noun = "one more detail" if need == 1 else f"{need} more details"
    return f"Could you share {noun}, such as {join_words(fields, 'or')}?"


def template(a: Act) -> str:
    d = a.data
    kind = a.kind
    if kind == ActKind.ACK_EMOTION:
        return _EMOTION.get(d.get("emotion"), "I understand, and I want to help.")
    if kind == ActKind.EXPLAIN_WHY_VERIFY:
        return (
            "Your claim details are protected, so I need to verify your identity before I can "
            "discuss them."
        )
    if kind == ActKind.ACK_FIELDS_PROVIDED:
        return f"I have {join_words(labels(d['fields']))} from you."
    if kind == ActKind.OFFER_ALT_FIELDS:
        return f"You can use any of these instead: {join_words(labels(d['fields']), 'or')}."
    if kind == ActKind.REQUEST_FIELDS:
        return _request_fields(a)
    if kind == ActKind.VERIFY_GENERIC_MISMATCH:
        return "I wasn't able to match some of the details I have so far."
    if kind == ActKind.REQUEST_REP_IDENTITY:
        return (
            "Since you're calling on someone else's behalf, may I have your own full name and "
            "your relationship to the policyholder?"
        )
    if kind == ActKind.CONSENT_RESULT:
        return _CONSENT.get(d.get("status"), "The approval check has finished.")
    if kind == ActKind.VERIFIED_OK:
        return "Thank you, you're verified."
    if kind == ActKind.CONFIRM_CLAIM:
        return f"I found your {case_phrase(d['case'])}. Let me know if that's not the one."
    if kind == ActKind.ASK_DISAMBIGUATION:
        options = "; ".join(case_phrase(c) for c in d["options"])
        lead = (
            "I couldn't find a claim that matches exactly what you described"
            if d.get("none_matched")
            else "I found more than one possible claim"
        )
        return f"{lead}: {options}. Which one do you mean?"
    if kind == ActKind.NO_CLAIMS_FOUND:
        return "I don't see any claims on file for this policy."
    if kind == ActKind.DECLINE_OOS:
        text = "I can only help with your insurance policy and claim, so I can't help with that."
        if d.get("level", 1) >= 2:
            text += (
                " I can check a claim's status, explain why a claim was denied, go over required "
                "documents, and talk through next steps."
            )
        return text
    if kind == ActKind.DECLINE_INSTRUCTION:
        return (
            "I can't change how I handle your information, but I'm glad to keep helping with "
            "your claim."
        )
    if kind == ActKind.ANSWER_GENERAL_INSURANCE:
        return (
            "That's a general insurance question. Your policy documents are the most reliable "
            "source for definitions, and I can help with your own claim."
        )
    if kind == ActKind.OFFER_HUMAN:
        return _HUMAN_OFFER.get(d.get("reason"), _HUMAN_OFFER["frustration"])
    if kind == ActKind.TRANSFER_HUMAN:
        return "I'm connecting you with a human representative now."
    if kind == ActKind.SESSION_ENDED:
        return "This conversation has ended. Please start a new one if you need anything else."
    if kind == ActKind.EMPTY_MESSAGE:
        return "I didn't receive a message. How can I help you today?"
    return (
        "I'm having trouble with that right now. I haven't changed or guessed anything. I can try "
        "again, or connect you with a human representative."
    )


def render_templates(acts: Iterable[Act]) -> str:
    return " ".join(template(a) for a in acts)
