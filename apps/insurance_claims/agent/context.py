"""The context pack: the only claim information a PROCESS_CASE reply may rely on.

Everything the agent may say about a claim is turned into short, labeled facts, built by code
from the resolved claim and the guideline files. The LLM is given these facts and nothing else
about the claim, and the grounding guard later checks that its reply stays inside them.

Design choices:
- A fact exists only if the data has it. Absence is never papered over. A claim that is not
  denied gets an explicit fact saying there is no denial reason, document request or deadline.
- Dates relative to today ("13 days remain") are computed here, from the injected clock. The
  LLM never does date arithmetic.
- Amounts are shown exactly as stored, with the meaning given in the claim schema. No derived
  amounts are ever produced (no "allowed minus paid"), so none can be quoted.
- Every fact lists the literal values it supports (ids, ISO dates, amounts, document names,
  day counts). The guard allows a figure in a reply only if some fact supports it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .acts import format_date, join_words
from .clock import Clock, deadline_facts
from .fixtures import Case, ClaimSchema, Guidelines, localized
from .guidance import alternative_guidance, document_guidance, fill_template, match_followups

_AMOUNT_LABELS = {
    "expected_reimbursement_amount": "Expected reimbursement",
    "allowed_max_amount": "Maximum allowed amount",
    "net_pay": "Net pay",
    "net_fee": "Net fee",
}


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    values: tuple[str, ...] = ()  # canonical literals this fact supports


@dataclass(frozen=True)
class CaseContext:
    case_id: str
    facts: tuple[Fact, ...]
    followup_topics: tuple[str, ...]  # follow-up rules that applied, for the case record

    def by_id(self) -> dict[str, Fact]:
        return {fact.id: fact for fact in self.facts}

    @property
    def allowed_values(self) -> frozenset[str]:
        return frozenset(value for fact in self.facts for value in fact.values)


def facts_block(context: CaseContext) -> str:
    """The facts as the renderer receives them, one labeled line each."""
    return "\n".join(f"[{fact.id}] {fact.text}" for fact in context.facts)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def build_case_context(
    case: Case,
    *,
    guidelines: Guidelines,
    claim_schema: ClaimSchema,
    clock: Clock,
    question: str | None = None,
    intents: Sequence[str] = (),
    topics: Sequence[str] = (),
    unavailable_docs: Sequence[str] = (),
    include_human_review: bool = False,
) -> CaseContext:
    facts: list[Fact] = []

    def add(fact_id: str, text: str, *values: str) -> None:
        facts.append(Fact(fact_id, text, tuple(v for v in values if v)))

    # ---- the claim itself -------------------------------------------------------------
    created = case.created_at
    when = f" created on {format_date(created)}" if created else ""
    article = "an" if case.case_type[:1].casefold() in "aeiou" else "a"
    add(
        "case.identity",
        f"Claim {case.case_id} is {article} {case.case_type} claim{when}.",
        case.case_id,
        created.isoformat() if created else "",
    )
    add("case.status", f"The claim's status is {case.status}.")
    if case.summary:
        add("case.summary", f"Summary on file: {case.summary.rstrip('.')}.")

    denied = case.status.casefold() == "denied"
    if case.denial_reason:
        add("case.denial_reason", f"Denial reason on file: {case.denial_reason.rstrip('.')}.")
    elif denied:
        add("case.no_denial_reason", "No denial reason is on file for this claim.")
    if case.documents_needed:
        add(
            "case.documents_needed",
            f"Documents requested for review: {join_words(case.documents_needed)}.",
            *case.documents_needed,
        )
    if case.appeal_deadline:
        deadline = case.appeal_deadline
        add(
            "case.appeal_deadline",
            f"The appeal deadline on file is {format_date(deadline)}.",
            deadline.isoformat(),
        )
        today = clock.today()
        timing = deadline_facts(deadline, clock)
        if timing is not None and timing.deadline_passed:
            count = timing.days_past_deadline or 0
            text = f"As of {format_date(today)}, that deadline passed {_days(count)} ago."
        elif timing is not None and timing.days_until_appeal_deadline == 0:
            count = 0
            text = f"As of {format_date(today)}, that deadline is today."
        else:
            count = timing.days_until_appeal_deadline if timing is not None else 0
            verb = "remains" if count == 1 else "remain"
            text = f"As of {format_date(today)}, {_days(count)} {verb} until that deadline."
        add("deadline.status", text, today.isoformat(), str(count))
    if not denied and not (case.denial_reason or case.documents_needed or case.appeal_deadline):
        add(
            "case.not_denied",
            "This claim is not denied, so there is no denial reason, requested documents or "
            "appeal deadline on file for it.",
        )

    # ---- amounts, exactly as stored, with their meaning from the schema ---------------
    for field, label in _AMOUNT_LABELS.items():
        amount = getattr(case, field)
        if amount is None:
            continue
        described = claim_schema.field_descriptions.get(field)
        meaning = ""
        if described is not None and described.description:
            meaning = f" ({described.description.rstrip('.')})"
        add(f"amount.{field}", f"{label}{meaning} is {_money(amount)}.", f"{amount:.2f}")

    # ---- guidance, only when the conversation is about documents ----------------------
    matches = match_followups(
        guidelines.claim_followup_guidance,
        question or "",
        intents=intents,
        topics=topics,
        has_documents=bool(case.documents_needed),
    )
    if "document_submission" in intents or matches or unavailable_docs:
        for doc in case.documents_needed:
            guidance = document_guidance(doc, case.case_type, guidelines)
            if guidance is not None and guidance.level == "document":
                add(f"guidance.doc.{_slug(doc)}", f"Guidance for the {doc}: {guidance.text}", doc)
        by_type = {key.casefold(): key for key in guidelines.case_type_guidance}
        type_key = by_type.get(case.case_type.casefold())
        type_text = localized(guidelines.case_type_guidance[type_key]) if type_key else None
        if type_text:
            add("guidance.case_type", f"Guidance for {case.case_type} claims: {type_text}")
        default_text = localized(guidelines.default_guidance)
        if default_text:
            add("guidance.default", f"General guidance: {default_text}")

    for doc in unavailable_docs:
        alternative = alternative_guidance(doc, guidelines)
        if alternative is not None:
            add(
                f"guidance.alt.{_slug(doc)}",
                f"If the {doc} cannot be obtained: {alternative.text}",
                doc,
            )
    if include_human_review:
        key = "human_review_after_document_alternatives_exhausted"
        review = localized(guidelines.claim_followup_settings.get(key))
        if review:
            add("policy.human_review", f"Escalation rule: {review}")

    # ---- follow-up rules that matched the question ------------------------------------
    settings = guidelines.claim_followup_settings
    values = {name: localized(entry) or "" for name, entry in settings.items()}
    values.update(case_id=case.case_id, documents=join_words(case.documents_needed))
    for match in matches:
        add(
            f"followup.{match.rule.topic}",
            fill_template(match.rule.text, values),
            case.case_id,
            *case.documents_needed,
        )
    # The guideline's catch-all is about documents and what happens next. It is added only
    # for that kind of question about a claim that has requested documents, so a plain denial
    # or status question never picks up an irrelevant "no separate rule" sentence.
    about_documents = "document_submission" in intents or "next_steps" in intents
    if question and not matches and case.documents_needed and about_documents:
        fallback = localized(guidelines.claim_followup_fallback)
        if fallback:
            add("followup.fallback", fallback)

    return CaseContext(case.case_id, tuple(facts), tuple(m.rule.topic for m in matches))
