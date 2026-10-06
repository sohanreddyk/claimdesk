"""Case resolution: which of the verified caller's claims are they asking about?

Works only on the list of cases it is given (the verified party's own, obtained through the
tool gateway). Uses everything remembered from earlier turns, including hints given before
verification, so the caller is not asked from scratch.

Rules:
- All hinted details must match (claim type, status, month, year, claim number).
- Exactly one match: proceed with it, stating it so the caller can correct it.
- Several matches (for example "healthcare in January" fits two years): ask one targeted
  question that lists them.
- Nothing matches: say so and list the claims on file.
- No hints at all and several claims: list them. A "why was it denied" question breaks a tie
  toward the only denied claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from .fixtures import Case
from .state import CaseHints
from .understanding import normalize_case_type

ResolutionKind = Literal["unique", "ambiguous", "no_match", "no_claims"]


@dataclass(frozen=True)
class Resolution:
    kind: ResolutionKind
    case: Case | None  # set when kind == "unique"
    options: tuple[Case, ...]  # candidates, newest first


def has_hints(hints: CaseHints) -> bool:
    return any(
        value is not None
        for value in (hints.case_type, hints.status, hints.month, hints.year, hints.case_id)
    )


def _matches(case: Case, hints: CaseHints) -> bool:
    if hints.case_id and case.case_id.upper() != hints.case_id.upper():
        return False
    if hints.case_type and normalize_case_type(case.case_type) != hints.case_type:
        return False
    if hints.status and case.status.casefold() != hints.status:
        return False
    if hints.month is not None or hints.year is not None:
        if case.created_at is None:
            return False
        if hints.month is not None and case.created_at.month != hints.month:
            return False
        if hints.year is not None and case.created_at.year != hints.year:
            return False
    return True


def _newest_first(cases: Sequence[Case]) -> tuple[Case, ...]:
    return tuple(sorted(cases, key=lambda c: c.created_at or date.min, reverse=True))


def resolve_case(cases: Sequence[Case], hints: CaseHints, intent: str | None = None) -> Resolution:
    if not cases:
        return Resolution("no_claims", None, ())

    everything = _newest_first(cases)
    if has_hints(hints):
        matches = _newest_first([c for c in cases if _matches(c, hints)])
        if len(matches) == 1:
            return Resolution("unique", matches[0], matches)
        if not matches:
            return Resolution("no_match", None, everything)
        candidates = matches
    else:
        if len(cases) == 1:
            return Resolution("unique", cases[0], everything)
        candidates = everything

    if intent == "denial_question":
        denied = [c for c in candidates if c.status.casefold() == "denied"]
        if len(denied) == 1:
            return Resolution("unique", denied[0], candidates)
    return Resolution("ambiguous", None, candidates)


def case_option(case: Case) -> dict[str, Any]:
    """Plain, PII-free description of a case, for dialogue-act payloads."""
    return {
        "case_id": case.case_id,
        "case_type": case.case_type,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "status": case.status,
    }
