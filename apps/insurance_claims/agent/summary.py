"""The summary email, built from the structured case record, never from the transcript.

Deterministic on purpose. The body is assembled by code from what was recorded about each claim
(status, topics discussed, requested documents, deadline), so it cannot invent a figure, cannot
drift from what was actually said, and carries no identity values: no DOB, ID digits, phone
number or email address ever enter the record it is built from.

Content, as the brief asks: what was discussed, the claim status or outcome, and the major
follow-up items. Days remaining are computed here from the injected clock, at the moment the
email is built, so they are right even if the conversation ran long.

If the caller looked at several claims, the summary has one section per claim, in the order
they were discussed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from .acts import format_date, join_words
from .clock import Clock, deadline_facts
from .state import CaseRecord

SUBJECT = "Summary of your claim conversation"
_NOTHING_DISCUSSED = "a general overview of the claim"
_REVIEW_LINE = "A human claims representative can review the file with you for manual options."


@dataclass(frozen=True)
class EmailSummary:
    subject: str
    body: str
    claim_ids: tuple[str, ...]


def has_content(records: Iterable[CaseRecord]) -> bool:
    """A summary only makes sense once at least one claim was actually discussed."""
    return any(record.case_id for record in records)


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _deadline_line(deadline: date, clock: Clock) -> str:
    timing = deadline_facts(deadline, clock)
    when = format_date(deadline)
    if timing is None:
        return f"The appeal deadline on file is {when}."
    if timing.deadline_passed:
        return f"The appeal deadline on file was {when}, and it has passed."
    if timing.days_until_appeal_deadline == 0:
        return f"The appeal deadline on file is {when}, which is today."
    remaining = _days(timing.days_until_appeal_deadline or 0)
    return f"The appeal deadline on file is {when} ({remaining} remaining as of today)."


def _merge(records: Iterable[CaseRecord]) -> list[CaseRecord]:
    """One record per claim, in the order first discussed. A claim the caller left and came
    back to is merged, not listed twice."""
    merged: dict[str, CaseRecord] = {}
    for record in records:
        if not record.case_id:
            continue
        existing = merged.get(record.case_id)
        if existing is None:
            merged[record.case_id] = record.model_copy(deep=True)
            continue
        for topic in record.topics_discussed:
            if topic not in existing.topics_discussed:
                existing.topics_discussed.append(topic)
        for doc in record.unavailable_documents:
            if doc not in existing.unavailable_documents:
                existing.unavailable_documents.append(doc)
        existing.documents_needed = existing.documents_needed or list(record.documents_needed)
        existing.appeal_deadline = existing.appeal_deadline or record.appeal_deadline
        existing.status_outcome = record.status_outcome or existing.status_outcome
        existing.human_review_offered = existing.human_review_offered or record.human_review_offered
    return list(merged.values())


def _next_steps(record: CaseRecord, clock: Clock) -> list[str]:
    steps: list[str] = []
    if record.documents_needed:
        steps.append(f"Submit the requested documents: {join_words(record.documents_needed)}.")
    if record.appeal_deadline:
        steps.append(_deadline_line(record.appeal_deadline, clock))
    if record.unavailable_documents:
        steps.append(
            f"You mentioned you could not get: {join_words(record.unavailable_documents)}."
        )
    if record.human_review_offered:
        steps.append(_REVIEW_LINE)
    return steps


def _section(record: CaseRecord, clock: Clock) -> list[str]:
    heading = f"Claim {record.case_id}"
    if record.case_type:
        heading += f" ({record.case_type})"
    lines = [heading]
    if record.status_outcome:
        lines.append(f"Status: {record.status_outcome}")
    lines.append("What we discussed:")
    lines += [f"- {topic}" for topic in record.topics_discussed or [_NOTHING_DISCUSSED]]
    lines.append("Next steps:")
    steps = _next_steps(record, clock) or ["None are on file for this claim."]
    lines += [f"- {step}" for step in steps]
    return lines


def build_summary(
    records: Sequence[CaseRecord], *, first_name: str | None, clock: Clock
) -> EmailSummary:
    claims = _merge(records)
    if not claims:
        raise ValueError("nothing to summarize: no claim was discussed")

    intro = (
        "Here is a summary of today's conversation about your claim."
        if len(claims) == 1
        else "Here is a summary of today's conversation about your claims."
    )
    lines = [f"Hello {first_name}," if first_name else "Hello,", "", intro, ""]
    for claim in claims:
        lines += _section(claim, clock)
        lines.append("")
    lines += [
        "This summary reflects the information on file. It is not a decision on coverage.",
        "",
        "Thank you,",
        "Claims Support",
    ]
    ids = tuple(claim.case_id for claim in claims if claim.case_id)
    return EmailSummary(SUBJECT, "\n".join(lines), ids)
