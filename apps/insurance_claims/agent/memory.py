"""Cross-phase memory: remember what the caller says, whenever they say it.

Remembering is not acting. This module only records facts in the state. It never changes the
phase, never verifies anyone and never touches claim data, so a caller can mention their
"denied healthcare claim from January" while still unverified and have it waiting for later,
without that unlocking anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from .normalize import name_key
from .state import FACTOR_NAMES, State
from .understanding import TurnUnderstanding


@dataclass(frozen=True)
class MemoryUpdate:
    captured_factors: tuple[str, ...]  # identity factors newly stored or changed this turn
    case_hints_changed: bool
    intent_remembered: bool


def apply_understanding(state: State, understanding: TurnUnderstanding) -> MemoryUpdate:
    u = understanding

    # Refusals first, so a value given in the same message wins over a refusal.
    state.refused_fields.update(u.refused_fields)

    # A name equal to the representative's own is not the account holder's name.
    rep_key = name_key(u.rep_name) if u.rep_name else None

    captured: list[str] = []
    for factor in FACTOR_NAMES:
        value = getattr(u, factor)
        if not value:
            continue
        if factor == "full_name" and rep_key is not None and name_key(value) == rep_key:
            continue
        if state.set_factor(factor, value):
            captured.append(factor)
        state.refused_fields.discard(factor)  # they changed their mind

    # The ID-type hint belongs to the most recent ID value the caller gave.
    if u.id_last4:
        state.id_kind_hint = u.id_kind_hint or "unspecified"

    if u.policy_number:
        state.policy_number = u.policy_number

    # Representative is sticky: it can only get stricter, never be talked back to policyholder.
    if u.caller_role == "representative":
        state.caller_role = "representative"
    elif u.caller_role == "policyholder" and state.caller_role == "unknown":
        state.caller_role = "policyholder"
    if u.rep_name:
        state.rep_name = u.rep_name
    if u.rep_relationship:
        state.rep_relationship = u.rep_relationship

    intent_remembered = False
    if u.intents:
        intent_remembered = state.intent_hint != u.intents[0]
        state.intent_hint = u.intents[0]
    hints_changed = state.case_hints.merge(u.to_case_hints())

    state.emotion = u.emotion
    state.severity = u.severity

    if captured:
        state.record("PII_CAPTURED", fields=captured)
    if hints_changed or intent_remembered:
        state.record(
            "CASE_HINT_CAPTURED",
            intent=state.intent_hint,
            case_type=state.case_hints.case_type,
            status=state.case_hints.status,
            month=state.case_hints.month,
            year=state.case_hints.year,
        )
    if u.dropped_fields:
        state.record("EXTRACTION_DROPPED", fields=u.dropped_fields)
    if u.fallback_reason:
        state.record("LLM_FALLBACK", stage="understand", reason=u.fallback_reason)

    return MemoryUpdate(tuple(captured), hints_changed, intent_remembered)
