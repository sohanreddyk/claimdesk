"""Grounding guard: checks that a claim reply stays inside the facts it was given.

Two complementary checks, both in plain code:

1. Literal grounding (the enforcement). Every concrete value in the reply must be supported by
   a fact: claim numbers, dates, amounts, day counts and document names. Anything numeric left
   over after those are accounted for is also flagged, so an invented "30 days to appeal" or
   "within 7 days" cannot slip through as a stray digit.

2. Fact references (provenance). The model lists the fact ids it relied on. Code only checks
   that every id is real. This is coarse provenance and debugging visibility, NOT proof that a
   sentence is correct, and it is not treated as a security boundary.

Formatting is normalized, so "$1,450", "1450.00" and "1,450 dollars" are the same amount, and
"March 18, 2026", "3/18/2026" and "2026-03-18" are the same date. A date written without a
year ("March 18") is accepted only if exactly one date in the facts has that month and day.
The guard never supplies a year to make a reply pass: with none or several candidates it is a
violation.

Known limits, stated plainly. They are covered by the prompt rules and the bounded context (the
only durations the model is given are the ones in the facts), not by this guard:
- Durations written in words have no digits to check: "within a week", "thirty days", "a couple
  of days" all pass.
- A claim about WHY or WHAT with no literal in it ("denied because the provider used the wrong
  billing code") passes. Fact references cannot catch this, because the model can cite a fact
  and still misstate it.
- Document names are recognized only from the vocabulary the data contains.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .context import CaseContext

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MONTH_NUMBER = {
    name: number
    for number, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}

_ID = re.compile(r"\b([A-Za-z]{2,5})-(\d{2,8})\b")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_US = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_MONTH_DAY = re.compile(
    rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE
)
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\.?(?:,?\s+(\d{{4}}))?\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)"
    r"|(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(?:dollars?|usd)\b"
    r"|(?<![\d.,])(\d[\d,]*\.\d{2})(?!\d)",
    re.IGNORECASE,
)
_DAYS = re.compile(r"(?<![\d.,])(\d+)\s+(?:calendar\s+|business\s+)?days?\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

_ID_VALUE = re.compile(r"[A-Z]{2,5}-\d{2,8}")
_AMOUNT_VALUE = re.compile(r"\d+\.\d{2}")
_ISO_VALUE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Violation:
    kind: str  # claim_id | date | ambiguous_date | amount | day_count | document | number | fact_id
    detail: str


@dataclass(frozen=True)
class GroundingResult:
    violations: tuple[Violation, ...]
    facts_used: tuple[str, ...]  # the cited fact ids, de-duplicated, in order

    @property
    def ok(self) -> bool:
        return not self.violations

    def feedback(self) -> str:
        """Short, specific text to hand back to the model when asking it to try again."""
        reasons = {
            "claim_id": "a claim number that is not this claim's",
            "date": "a date that is not in the facts",
            "ambiguous_date": "a date without a year that could mean more than one date",
            "amount": "an amount that is not in the facts",
            "day_count": "a number of days that is not in the facts",
            "document": "a document that is not part of this claim",
            "number": "a number that is not in the facts",
            "fact_id": "a fact id that does not exist",
        }
        parts = [f"{reasons.get(v.kind, v.kind)}: '{v.detail}'" for v in self.violations]
        return "The reply contained " + "; ".join(parts) + ". Use only the facts provided."


def _allowed_dates(values: Iterable[str]) -> set[date]:
    dates: set[date] = set()
    for value in values:
        if _ISO_VALUE.fullmatch(value):
            try:
                dates.add(date.fromisoformat(value))
            except ValueError:
                continue
    return dates


def _date_problem(month: int, day: int, year: int | None, allowed: set[date]) -> str | None:
    """None if supported, otherwise 'date' or 'ambiguous_date'."""
    if year is not None:
        try:
            return None if date(year, month, day) in allowed else "date"
        except ValueError:
            return "date"
    candidates = [d for d in allowed if (d.month, d.day) == (month, day)]
    if len(candidates) == 1:
        return None
    return "ambiguous_date" if len(candidates) > 1 else "date"


def _blank(pattern: re.Pattern[str], text: str, check) -> str:
    """Run `check` on every match and remove the match so later checks do not see it again."""

    def replace(match: re.Match[str]) -> str:
        check(match)
        return " "

    return pattern.sub(replace, text)


def check_grounding(
    reply: str,
    facts_used: Sequence[str],
    context: CaseContext,
    known_documents: Iterable[str] = (),
) -> GroundingResult:
    allowed = context.allowed_values
    allowed_dates = _allowed_dates(allowed)
    allowed_ids = {v.upper() for v in allowed if _ID_VALUE.fullmatch(v.upper())}
    allowed_amounts = {v for v in allowed if _AMOUNT_VALUE.fullmatch(v)}
    allowed_ints = {v for v in allowed if v.isdigit()}
    violations: list[Violation] = []

    def flag(kind: str, detail: str) -> None:
        violations.append(Violation(kind, detail.strip()))

    text = reply

    # claim numbers
    def check_id(match: re.Match[str]) -> None:
        if f"{match.group(1).upper()}-{match.group(2)}" not in allowed_ids:
            flag("claim_id", match.group(0))

    text = _blank(_ID, text, check_id)

    # dates, in every written form
    def check_ymd(match: re.Match[str]) -> None:
        year, month, day = (int(g) for g in match.groups())
        problem = _date_problem(month, day, year, allowed_dates)
        if problem:
            flag(problem, match.group(0))

    def check_us(match: re.Match[str]) -> None:
        month, day, year = (int(g) for g in match.groups())
        problem = _date_problem(month, day, year, allowed_dates)
        if problem:
            flag(problem, match.group(0))

    def check_month_day(match: re.Match[str]) -> None:
        month = _MONTH_NUMBER[match.group(1)[:3].lower()]
        year = int(match.group(3)) if match.group(3) else None
        problem = _date_problem(month, int(match.group(2)), year, allowed_dates)
        if problem:
            flag(problem, match.group(0))

    def check_day_month(match: re.Match[str]) -> None:
        month = _MONTH_NUMBER[match.group(2)[:3].lower()]
        year = int(match.group(3)) if match.group(3) else None
        problem = _date_problem(month, int(match.group(1)), year, allowed_dates)
        if problem:
            flag(problem, match.group(0))

    text = _blank(_ISO, text, check_ymd)
    text = _blank(_US, text, check_us)
    text = _blank(_MONTH_DAY, text, check_month_day)
    text = _blank(_DAY_MONTH, text, check_day_month)

    # amounts
    def check_amount(match: re.Match[str]) -> None:
        raw = next(g for g in match.groups() if g is not None)
        try:
            normalized = f"{Decimal(raw.replace(',', '')):.2f}"
        except InvalidOperation:
            flag("amount", match.group(0))
            return
        if normalized not in allowed_amounts:
            flag("amount", match.group(0))

    text = _blank(_AMOUNT, text, check_amount)

    # day counts
    def check_days(match: re.Match[str]) -> None:
        if match.group(1) not in allowed_ints:
            flag("day_count", match.group(0))

    text = _blank(_DAYS, text, check_days)

    # document names: longest first, so "original pathology report" is seen before its
    # shorter relative "pathology report"
    vocabulary = sorted({d.casefold() for d in known_documents if d.strip()}, key=len, reverse=True)
    allowed_documents = {d for d in vocabulary if d in {v.casefold() for v in allowed}}
    for term in vocabulary:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)

        def check_document(match: re.Match[str], term: str = term) -> None:
            if not any(a in term or term in a for a in allowed_documents):
                flag("document", match.group(0))

        text = _blank(pattern, text, check_document)

    # anything numeric still left over must be supported on its own
    allowed_years = {d.year for d in allowed_dates}
    for token in _NUMBER.findall(text):
        clean = token.rstrip(".,")
        if clean in allowed_ints:
            continue
        try:
            if f"{Decimal(clean.replace(',', '')):.2f}" in allowed_amounts:
                continue
        except InvalidOperation:
            pass
        if clean.isdigit() and len(clean) == 4 and int(clean) in allowed_years:
            continue
        flag("number", clean)

    # provenance: every cited fact must exist
    known_ids = context.by_id()
    cited: list[str] = []
    for fact_id in facts_used:
        if fact_id in cited:
            continue
        cited.append(fact_id)
        if fact_id not in known_ids:
            flag("fact_id", fact_id)

    return GroundingResult(tuple(violations), tuple(cited))
