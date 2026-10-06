import pytest
from agent.state import SopViolation
from agent.tools import ToolGateway
from agent.verify import VerifyStatus, verify_identity


def verified_gateway(store, settings, consent, make_state, **factors):
    state = make_state(**factors)
    assert verify_identity(state, store, settings, consent).status == VerifyStatus.VERIFIED
    return state, ToolGateway(store, state)


def test_unverified_session_cannot_reach_any_claim_data(store, make_state):
    gateway = ToolGateway(store, make_state(full_name="Margaret Chen"))
    with pytest.raises(SopViolation, match="before identity verification"):
        gateway.list_cases()
    with pytest.raises(SopViolation):
        gateway.get_case("CL-2048")


def test_a_verified_flag_without_a_party_is_still_refused(store, make_state):
    state = make_state()
    state.verified = True  # tampering: flag set, but no verified party recorded
    with pytest.raises(SopViolation):
        ToolGateway(store, state).list_cases()


def test_verified_policyholder_sees_only_their_own_cases(store, settings, consent, make_state):
    _, gateway = verified_gateway(
        store,
        settings,
        consent,
        make_state,
        full_name="Margaret Chen",
        dob="1985-03-15",
        id_last4="4472",
    )
    assert [c.case_id for c in gateway.list_cases()] == [
        "CL-2048",
        "CL-2011",
        "CL-1899",
        "CL-2102",
    ]
    assert gateway.get_case("CL-2048").status == "denied"


def test_another_partys_case_is_indistinguishable_from_a_missing_one(
    store, settings, consent, make_state
):
    _, gateway = verified_gateway(
        store,
        settings,
        consent,
        make_state,
        full_name="Margaret Chen",
        dob="1985-03-15",
        id_last4="4472",
    )
    assert gateway.get_case("CL-3001") is None  # exists, but belongs to Ma Tian
    assert gateway.get_case("CL-9999") is None  # does not exist


def test_party_with_no_claims_gets_an_empty_list(store, settings, consent, make_state):
    _, gateway = verified_gateway(
        store,
        settings,
        consent,
        make_state,
        full_name="Ava Lopez",
        dob="1990-08-21",
        id_last4="9180",
    )
    assert gateway.list_cases() == []


def test_representative_reaches_the_policyholders_cases(store, settings, consent, make_state):
    state, gateway = verified_gateway(
        store,
        settings,
        consent,
        make_state,
        full_name="David Chen",
        dob="1985-03-15",
        id_last4="4472",
        phone="+16505212836",
    )
    assert state.verified_as == "representative"
    assert len(gateway.list_cases()) == 4


def test_tool_calls_are_audited(store, settings, consent, make_state):
    state, gateway = verified_gateway(
        store,
        settings,
        consent,
        make_state,
        full_name="Margaret Chen",
        dob="1985-03-15",
        id_last4="4472",
    )
    gateway.list_cases()
    gateway.get_case("CL-3001")
    calls = [e.data for e in state.events if e.type == "TOOL_CALL"]
    assert calls == [
        {"tool": "list_cases", "result_count": 4},
        {"tool": "get_case", "case_id": "CL-3001", "found": False},
    ]
