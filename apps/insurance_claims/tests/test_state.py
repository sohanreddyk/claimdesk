import pytest
from agent.state import (
    CaseHints,
    ConsentState,
    Phase,
    SopViolation,
    State,
)

THREE = {"full_name", "dob", "id_last4"}


def verified_state() -> State:
    s = State(session_id="s1")
    s.matched_factors = set(THREE)
    s.mark_verified("P9", "policyholder", min_factors=3)
    return s


def test_new_state_starts_unverified_in_verify_id():
    s = State(session_id="s1")
    assert s.phase == Phase.VERIFY_ID
    assert s.verified is False


def test_cannot_leave_verify_id_without_verification():
    s = State(session_id="s1")
    for target in (Phase.RESOLVE_INTENT, Phase.PROCESS_CASE, Phase.POST_PROCESS):
        with pytest.raises(SopViolation):
            s.set_phase(target)
    assert s.phase == Phase.VERIFY_ID


def test_mark_verified_needs_enough_matched_factors():
    s = State(session_id="s1")
    s.matched_factors = {"full_name", "dob"}
    with pytest.raises(SopViolation, match="need 3"):
        s.mark_verified("P9", "policyholder", min_factors=3)
    assert s.verified is False


def test_policy_number_is_not_a_factor():
    s = State(session_id="s1")
    s.policy_number = "POL-9921"
    s.matched_factors = {"full_name", "dob"}
    with pytest.raises(SopViolation):
        s.mark_verified("P9", "policyholder", min_factors=3)
    with pytest.raises(ValueError):
        s.set_factor("policy_number", "POL-9921")


def test_representative_needs_approved_consent():
    s = State(session_id="s1")
    s.matched_factors = set(THREE)
    with pytest.raises(SopViolation, match="consent"):
        s.mark_verified("P9", "representative", min_factors=3)
    s.consent = ConsentState.PENDING
    with pytest.raises(SopViolation):
        s.mark_verified("P9", "representative", min_factors=3)
    s.consent = ConsentState.APPROVED
    s.mark_verified("P9", "representative", min_factors=3)
    assert s.verified_as == "representative"


def test_happy_path_transitions_are_audited():
    s = verified_state()
    s.set_phase(Phase.RESOLVE_INTENT, "verified")
    with pytest.raises(SopViolation, match="resolved case"):
        s.set_phase(Phase.PROCESS_CASE)
    s.resolved_case_id = "CL-2048"
    s.set_phase(Phase.PROCESS_CASE, "case resolved")
    s.set_phase(Phase.POST_PROCESS, "user done")
    s.set_phase(Phase.COMPLETE, "finished")
    types = [e.type for e in s.events]
    assert types == [
        "IDENTITY_VERIFIED",
        "PHASE_TRANSITION",
        "PHASE_TRANSITION",
        "PHASE_TRANSITION",
        "PHASE_TRANSITION",
    ]
    assert s.events[1].data == {"from": "VERIFY_ID", "to": "RESOLVE_INTENT", "reason": "verified"}
    assert [e.seq for e in s.events] == [1, 2, 3, 4, 5]


def test_phases_cannot_be_skipped_or_reversed():
    s = verified_state()
    with pytest.raises(SopViolation):
        s.set_phase(Phase.POST_PROCESS)  # VERIFY_ID -> POST_PROCESS skips phases
    s.set_phase(Phase.RESOLVE_INTENT)
    with pytest.raises(SopViolation):
        s.set_phase(Phase.POST_PROCESS)  # RESOLVE_INTENT -> POST_PROCESS skips PROCESS_CASE
    with pytest.raises(SopViolation):
        s.set_phase(Phase.VERIFY_ID)  # no way back to VERIFY_ID


def test_allowed_back_edges_and_terminal_complete():
    s = verified_state()
    s.set_phase(Phase.RESOLVE_INTENT)
    s.resolved_case_id = "CL-2048"
    s.set_phase(Phase.PROCESS_CASE)
    s.set_phase(Phase.RESOLVE_INTENT, "claim switch")  # PROCESS_CASE -> RESOLVE_INTENT
    s.set_phase(Phase.PROCESS_CASE)
    s.set_phase(Phase.POST_PROCESS)
    s.set_phase(Phase.RESOLVE_INTENT, "another question")  # POST_PROCESS -> RESOLVE_INTENT
    s.set_phase(Phase.COMPLETE)
    with pytest.raises(SopViolation):
        s.set_phase(Phase.RESOLVE_INTENT)


def test_unverified_session_can_still_end_for_human_transfer():
    s = State(session_id="s1")
    s.set_phase(Phase.COMPLETE, "human transfer")
    assert s.phase == Phase.COMPLETE


def test_same_phase_is_a_noop():
    s = State(session_id="s1")
    s.set_phase(Phase.VERIFY_ID)
    assert s.events == []


def test_set_factor_validates_and_reports_change():
    s = State(session_id="s1")
    assert s.set_factor("dob", " 1985-03-15 ") is True
    assert s.factors["dob"] == "1985-03-15"
    assert s.set_factor("dob", "1985-03-15") is False
    assert s.set_factor("dob", "   ") is False
    with pytest.raises(ValueError):
        s.set_factor("shoe_size", "9")


def test_case_hints_merge_overlays_only_new_values():
    hints = CaseHints(case_type="healthcare", month=1)
    assert hints.merge(CaseHints(status="denied")) is True
    assert (hints.case_type, hints.status, hints.month) == ("healthcare", "denied", 1)
    assert hints.merge(CaseHints(status="denied")) is False
    assert hints.merge(CaseHints()) is False


def test_state_round_trips_through_json():
    s = verified_state()
    restored = State.model_validate_json(s.model_dump_json())
    assert restored.verified and restored.matched_factors == THREE
