"""Grounded answers for PROCESS_CASE: the model words an answer, code decides if it may be said.

Flow for one question:
1. The model gets only the facts for the resolved claim and returns `{reply, facts_used}`.
2. The grounding guard checks the reply. If it fails, the model gets one more try with the
   guard's specific feedback.
3. If it fails again, or the LLM is unavailable, the reply is built directly from the facts'
   own texts. That text is grounded by construction: plainer, but always correct.

An LLM outage is not retried (the second call would just wait again); only unusable output is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .config import Settings
from .context import CaseContext, facts_block
from .grounding import Violation, check_grounding
from .llm.client import LLMBadOutput, LLMClient, LLMError
from .llm.process_prompts import PROCESS_SYSTEM, build_process_user


class GroundedReply(BaseModel):
    """What the model returns. Flat and small so the schema is followed reliably."""

    reply: str = Field(description="The message to the caller, plain text")
    facts_used: list[str] = Field(
        default_factory=list, description="Ids of the facts the reply relies on"
    )


@dataclass(frozen=True)
class ProcessAnswer:
    reply: str
    facts_used: tuple[str, ...]
    source: Literal["llm", "retry", "facts"]
    violations: tuple[Violation, ...] = ()  # why the last model attempt was rejected, if it was
    fallback_reason: str | None = None  # set when source == "facts"


def tone_note(emotion: str, severity: int) -> str | None:
    """A one-line instruction for the model when the caller sounds upset, else None."""
    if severity < 1 or emotion == "neutral":
        return None
    return f"The caller seems {emotion}. Open with one brief, sincere acknowledgment, then answer."


# ---- the answer built straight from the facts -----------------------------------------------

_BY_INTENT: dict[str, tuple[str, ...]] = {
    "denial_question": (
        "case.status",
        "case.denial_reason",
        "case.no_denial_reason",
        "case.not_denied",
        "case.documents_needed",
        "case.appeal_deadline",
        "deadline.status",
    ),
    "status_inquiry": ("case.status", "case.summary"),
    "next_steps": (
        "case.status",
        "case.not_denied",
        "case.documents_needed",
        "case.appeal_deadline",
        "deadline.status",
    ),
    "document_submission": ("case.documents_needed", "guidance."),
    "general_claim_question": ("case.identity", "case.status", "case.summary"),
}
_PAYMENT_WORDS = re.compile(
    r"\b(paid|pay|payment|payments|amount|reimburs\w*|owe|cost|fee|price|refund)\b", re.IGNORECASE
)


def _select_facts(context: CaseContext, intents: Sequence[str], question: str):
    wanted: list[str] = []
    for intent in intents or ("general_claim_question",):
        wanted += _BY_INTENT.get(intent, _BY_INTENT["general_claim_question"])
    wanted.append("followup.")  # matched follow-up rules are direct answers: always included
    if _PAYMENT_WORDS.search(question):
        wanted.append("amount.")

    def wanted_fact(fact_id: str) -> bool:
        return any(fact_id == w or (w.endswith(".") and fact_id.startswith(w)) for w in wanted)

    chosen = [fact for fact in context.facts if wanted_fact(fact.id)]
    return chosen or [f for f in context.facts if f.id in ("case.identity", "case.status")]


def facts_only_answer(
    context: CaseContext,
    intents: Sequence[str],
    question: str,
    *,
    reason: str,
    violations: tuple[Violation, ...] = (),
) -> ProcessAnswer:
    chosen = _select_facts(context, intents, question)
    return ProcessAnswer(
        reply=" ".join(fact.text for fact in chosen),
        facts_used=tuple(fact.id for fact in chosen),
        source="facts",
        violations=violations,
        fallback_reason=reason,
    )


# ---- the model-written answer, checked ----------------------------------------------------------


async def generate_answer(
    llm: LLMClient,
    settings: Settings,
    *,
    context: CaseContext,
    question: str,
    intents: Sequence[str] = (),
    known_documents: Iterable[str] = (),
    caller_first_name: str | None = None,
    tone: str | None = None,
) -> ProcessAnswer:
    block = facts_block(context)
    documents = list(known_documents)
    feedback: str | None = None
    violations: tuple[Violation, ...] = ()
    failure = "grounding_failed"

    for attempt in range(2):
        prompt = build_process_user(
            facts=block,
            question=question,
            caller_first_name=caller_first_name,
            tone_note=tone,
            feedback=feedback,
        )
        try:
            output = await llm.structured(
                model=settings.llm_model,
                system=PROCESS_SYSTEM,
                user=prompt,
                schema=GroundedReply,
                max_tokens=700,
            )
        except LLMBadOutput:
            feedback = "It was not valid structured output. Return a reply and facts_used."
            failure = "LLMBadOutput"
            continue
        except LLMError as exc:
            return facts_only_answer(context, intents, question, reason=type(exc).__name__)

        reply = output.reply.strip()
        result = check_grounding(reply, output.facts_used, context, documents)
        if reply and result.ok:
            return ProcessAnswer(reply, result.facts_used, "llm" if attempt == 0 else "retry")
        feedback = result.feedback() if reply else "The reply was empty."
        violations = result.violations
        failure = "grounding_failed"

    return facts_only_answer(context, intents, question, reason=failure, violations=violations)
