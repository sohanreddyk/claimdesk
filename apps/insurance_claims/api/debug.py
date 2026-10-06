"""The evaluator inspector view. Only reachable when ENABLE_DEBUG_INSPECTOR=true.

Even then it never shows a raw identity value: factors, policy number and addresses are masked,
audit events are scrubbed when they are created, and the caller's messages are not included
(only how many turns there have been).
"""

from __future__ import annotations

from typing import Any

from agent.audit import scrub
from agent.masking import mask_email, mask_policy, mask_value

from .sessions import Session


def debug_view(session: Session) -> dict[str, Any]:
    state = session.state
    last = session.last_result
    return {
        "session_id": state.session_id,
        "phase": state.phase.value,
        "ended": session.ended,
        "turns": session.turns,
        "verification": {
            "verified": state.verified,
            "verified_as": state.verified_as,
            "caller_role": state.caller_role,
            "rep_name": mask_value("rep_name", state.rep_name) if state.rep_name else None,
            "factors": {name: mask_value(name, value) for name, value in state.factors.items()},
            "policy_number": mask_policy(state.policy_number) if state.policy_number else None,
            "matched_factors": sorted(state.matched_factors),
            "mismatch_count": state.mismatch_count,
            "refused_fields": sorted(state.refused_fields),
        },
        "consent": {"state": state.consent.value, "trail": list(state.consent_trail)},
        "memory": {
            "intent_hint": state.intent_hint,
            "case_hints": state.case_hints.model_dump(mode="json", exclude_none=True),
        },
        "case": {
            "resolved_case_id": state.resolved_case_id,
            "last_resolution": state.last_resolution,
            "record": state.case_record.model_dump(mode="json"),
            "closed_cases": [c.model_dump(mode="json") for c in state.closed_cases],
        },
        "counters": {
            "emotion": state.emotion,
            "severity": state.severity,
            "refusal_count": state.refusal_count,
            "frustration_streak": state.frustration_streak,
            "oos_strikes": state.oos_strikes,
            "case_loops": state.case_loops,
            "human_offered": state.human_offered,
            "human_transferred": state.human_transferred,
        },
        "email": {
            "state": state.email_state.value,
            "address": mask_email(state.email_address) if state.email_address else None,
            "rejected_alternatives": state.email_alt_attempts,
        },
        "last_turn": (
            None
            if last is None
            else {
                "acts": [{"kind": a.kind.value, "data": scrub(a.data)} for a in last.acts],
                "used_llm": last.used_llm,
                "guard_violations": list(last.guard_violations),
            }
        ),
        "tool_calls": [e.model_dump(mode="json") for e in state.events if e.type == "TOOL_CALL"],
        "events": [e.model_dump(mode="json") for e in state.events],
        "outbox": [email.public_view() for email in session.outbox.sent()],
        "history_length": len(state.history),
    }
