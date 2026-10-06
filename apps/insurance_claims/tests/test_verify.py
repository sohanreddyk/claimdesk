import json

import pytest
from agent.consent import ConsentGateway
from agent.state import ConsentState
from agent.verify import VerifyStatus, verify_identity

MARGARET = {
    "full_name": "Margaret Chen",
    "dob": "1985-03-15",
    "id_last4": "4472",
    "phone": "+16505212836",
    "email": "margaret@email.com",
}


@pytest.fixture
def run(store, settings, consent):
    def _run(state, gateway=None):
        return verify_identity(state, store, settings, gateway or consent)

    return _run


def pick(*names: str) -> dict[str, str]:
    return {name: MARGARET[name] for name in names}


# ---- the 3-factor rule ---------------------------------------------------------------


def test_three_matching_factors_verify_the_policyholder(make_state, run):
    state = make_state(**pick("full_name", "dob", "id_last4"))
    result = run(state)
    assert result.status == VerifyStatus.VERIFIED
    assert state.verified and state.verified_party_id == "P9"
    assert state.verified_as == "policyholder"
    assert state.consent == ConsentState.NOT_REQUESTED  # policyholders are not consent-gated


def test_two_matching_factors_do_not_verify(make_state, run):
    state = make_state(**pick("full_name", "dob"))
    result = run(state)
    assert result.status == VerifyStatus.NEED_MORE
    assert not state.verified
    assert state.mismatch_count == 0  # a partial answer is not a failure
    assert result.provided == ("full_name", "dob")
    assert result.missing == ("phone", "email", "id_last4")


def test_policy_number_never_counts_as_a_factor(make_state, run):
    state = make_state(**pick("full_name", "dob"))
    state.policy_number = "POL-9921"
    result = run(state)
    assert result.status == VerifyStatus.NEED_MORE
    assert not state.verified
    assert state.matched_factors == {"full_name", "dob"}


def test_incorrect_value_does_not_count(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="1985-03-15", id_last4="0000")
    result = run(state)
    assert result.status == VerifyStatus.MISMATCH
    assert not state.verified
    assert state.mismatch_count == 1
    assert state.matched_factors == {"full_name", "dob"}
    state.set_factor("phone", MARGARET["phone"])
    assert run(state).status == VerifyStatus.VERIFIED  # three correct factors are enough


def test_factors_spread_across_turns(make_state, run):
    state = make_state()
    for name, expected in (
        ("full_name", VerifyStatus.NEED_MORE),
        ("dob", VerifyStatus.NEED_MORE),
        ("id_last4", VerifyStatus.VERIFIED),
    ):
        state.set_factor(name, MARGARET[name])
        assert run(state).status == expected


def test_any_three_of_five_factors_work(make_state, run):
    state = make_state(**pick("phone", "email", "dob"))  # no name, no ID
    assert run(state).status == VerifyStatus.VERIFIED


def test_formats_are_normalized(make_state, run):
    state = make_state(full_name="Chen, Margaret", dob="March 15, 1985", phone="(650) 521-2836")
    assert run(state).status == VerifyStatus.VERIFIED


def test_unusable_values_are_not_provided_and_not_mismatches(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="banana", phone="2836")
    result = run(state)
    assert result.provided == ("full_name",)
    assert state.mismatch_count == 0


def test_refused_fields_are_not_requested_again(make_state, run):
    state = make_state(full_name="Margaret Chen")
    state.refused_fields = {"id_last4"}
    result = run(state)
    assert "id_last4" not in result.missing


def test_verification_is_idempotent(make_state, run):
    state = make_state(**pick("full_name", "dob", "id_last4"))
    run(state)
    assert run(state).status == VerifyStatus.VERIFIED
    assert [e.type for e in state.events].count("IDENTITY_VERIFIED") == 1


# ---- one party record, aliases, near-collisions -------------------------------------


def test_factors_from_different_people_never_combine(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="1990-08-21", id_last4="6688")
    result = run(state)  # name = Margaret, dob = Ava, id = Ma Tian
    assert result.status == VerifyStatus.MISMATCH
    assert not state.verified
    assert state.mismatch_count == 2


def test_near_identical_phone_does_not_cross_verify(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="1985-03-15", phone="+16505212830")
    assert run(state).status == VerifyStatus.MISMATCH
    assert not state.verified


def test_policy_number_binds_the_candidate(make_state, run):
    state = make_state(full_name="Ava Lopez", dob="1990-08-21", id_last4="9180")
    state.policy_number = "POL-9921"  # Margaret's policy, Ava's details
    result = run(state)
    assert not state.verified
    assert result.status == VerifyStatus.LOCKED  # three mismatches against Margaret's record


def test_alias_name_verifies(make_state, run):
    state = make_state(full_name="Yaven Li", dob="1989-12-03", id_last4="5317")
    state.id_kind_hint = "national_id"
    assert run(state).status == VerifyStatus.VERIFIED
    assert state.verified_party_id == "P13"


def test_duplicate_alias_counts_once(make_state, run):
    state = make_state(phone="+16505212830")  # primary and alias are identical in the fixture
    run(state)
    assert state.matched_factors == {"phone"}
    state.set_factor("email", "yawen.li@example.com")  # an email alias
    run(state)
    assert state.matched_factors == {"phone", "email"}
    assert not state.verified
    state.set_factor("dob", "1989-12-03")
    assert run(state).status == VerifyStatus.VERIFIED


# ---- ID type rules ---------------------------------------------------------------------


def ma_tian(make_state, hint=None, digits="6688"):
    state = make_state(full_name="Ma Tian", dob="1964-09-10", id_last4=digits)
    state.id_kind_hint = hint
    return state


@pytest.mark.parametrize("hint", [None, "unspecified", "national_id"])
def test_ma_tian_verifies_unless_a_conflicting_type_is_stated(make_state, run, hint):
    assert run(ma_tian(make_state, hint)).status == VerifyStatus.VERIFIED


def test_ma_tian_does_not_match_when_calling_it_an_ssn(make_state, run):
    state = ma_tian(make_state, "ssn")
    assert run(state).status == VerifyStatus.MISMATCH
    assert not state.verified
    assert state.matched_factors == {"full_name", "dob"}


def test_margaret_does_not_match_when_calling_it_a_national_id(make_state, run):
    state = make_state(**pick("full_name", "dob", "id_last4"))
    state.id_kind_hint = "national_id"
    assert run(state).status == VerifyStatus.MISMATCH
    assert not state.verified


def test_type_conflict_is_indistinguishable_from_wrong_digits(make_state, store, settings, consent):
    conflict = ma_tian(make_state, "ssn")
    wrong = ma_tian(make_state, None, digits="0000")
    r1 = verify_identity(conflict, store, settings, consent)
    r2 = verify_identity(wrong, store, settings, consent)
    assert (r1.status, r1.provided, r1.missing) == (r2.status, r2.provided, r2.missing)
    assert not hasattr(r1, "matched") and not hasattr(r1, "id_type")


# ---- lockout -------------------------------------------------------------------------


def test_three_mismatches_lock_automated_verification(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="1990-01-01", id_last4="0000")
    state.set_factor("phone", "+16505550000")
    assert run(state).status == VerifyStatus.LOCKED
    for name in ("dob", "id_last4", "phone"):  # now give the correct values
        state.set_factor(name, MARGARET[name])
    assert run(state).status == VerifyStatus.LOCKED
    assert not state.verified


def test_the_same_wrong_value_is_counted_once(make_state, run):
    state = make_state(full_name="Margaret Chen", dob="1985-03-15", id_last4="0000")
    run(state)
    run(state)
    run(state)
    assert state.mismatch_count == 1


# ---- invariant 1: verification never touches claim data -------------------------------


def test_verification_never_reads_claim_data(make_state, store, settings, consent, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("claim data was accessed during verification")

    monkeypatch.setattr(store, "cases_for_party", boom)
    monkeypatch.setattr(store, "get_case", boom)
    scenarios = [
        make_state(**pick("full_name", "dob", "id_last4")),
        make_state(**pick("full_name")),
        make_state(full_name="Margaret Chen", dob="1990-01-01", id_last4="0000"),
        make_state(full_name="Bob Nobody", dob="1970-01-01"),
    ]
    for state in scenarios:
        verify_identity(state, store, settings, consent)


def test_audit_trail_contains_no_raw_pii(make_state, run):
    state = make_state(**MARGARET)
    run(state)
    dumped = json.dumps([e.model_dump() for e in state.events])
    for secret in ("Margaret", "Chen", "1985", "4472", "6505212836", "margaret@"):
        assert secret not in dumped


# ---- representatives -------------------------------------------------------------------


def david_as_himself(make_state):
    return make_state(
        full_name="David Chen", dob="1985-03-15", id_last4="4472", phone="+16505212836"
    )


def test_representative_is_detected_by_name_and_cannot_verify_as_policyholder(make_state, run):
    state = david_as_himself(make_state)
    result = run(state)
    assert state.caller_role == "representative"
    assert state.rep_name == "David Chen"
    assert "full_name" not in state.factors
    assert state.verified_as == "representative"  # only after consent, never as the policyholder
    assert result.status == VerifyStatus.VERIFIED
    assert state.verified_party_id == "P9"


def test_representative_consent_default_scenario_approves(make_state, run):
    state = david_as_himself(make_state)
    run(state)
    assert state.consent == ConsentState.APPROVED
    assert state.consent_trail == ["pending", "approved"]


def test_representative_consent_timeout_blocks_access(make_state, run, consent_timeout):
    state = david_as_himself(make_state)
    result = run(state, consent_timeout)
    assert result.status == VerifyStatus.CONSENT_TIMED_OUT
    assert not state.verified
    assert state.consent == ConsentState.TIMED_OUT
    assert state.consent_trail == ["pending"] * 5
    # a second evaluation must not send another approval request
    assert run(state, consent_timeout).status == VerifyStatus.CONSENT_TIMED_OUT
    assert [e.type for e in state.events].count("CONSENT_REQUESTED") == 1


def test_representative_consent_denied_blocks_access(make_state, run):
    denied = ConsentGateway(["pending", "denied"], "custom", 5)
    state = david_as_himself(make_state)
    assert run(state, denied).status == VerifyStatus.CONSENT_DENIED
    assert not state.verified


def test_unlisted_representative_is_not_authorized(make_state, run):
    state = make_state(**pick("dob", "id_last4", "phone"))
    state.caller_role = "representative"
    state.rep_name = "Daniel Chen"  # e.g. a spouse who is not on file
    result = run(state)
    assert result.status == VerifyStatus.REP_NOT_AUTHORIZED
    assert not state.verified
    assert state.consent == ConsentState.NOT_REQUESTED  # no approval prompt is sent


def test_representative_without_a_name_is_asked_who_they_are(make_state, run):
    state = make_state(**pick("dob", "id_last4", "phone"))
    state.caller_role = "representative"
    assert run(state).status == VerifyStatus.NEED_REP_IDENTITY
    assert state.consent == ConsentState.NOT_REQUESTED


def test_no_consent_request_before_three_factors_match(make_state, run):
    state = make_state(full_name="David Chen", dob="1985-03-15")
    result = run(state)
    assert result.status == VerifyStatus.NEED_MORE
    assert state.consent == ConsentState.NOT_REQUESTED
    assert not state.verified
