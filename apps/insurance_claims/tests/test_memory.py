import json

from agent.llm.client import LLMTimeout
from agent.llm.fake import ScriptedLLM
from agent.memory import apply_understanding
from agent.state import Phase
from agent.understanding import TurnUnderstanding, understand_turn
from agent.verify import VerifyStatus, verify_identity

MARGARET_MSG = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my "
    "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472."
)
MARGARET_LLM = {
    "full_name": "Margaret Chen",
    "caller_role": "policyholder",
    "intents": ["denial_question"],
    "hint_case_type": "healthcare",
    "hint_status": "denied",
    "hint_month": 1,
}


def u(**fields) -> TurnUnderstanding:
    return TurnUnderstanding(**fields)


# ---- remembering (invariants 5 and 6) ----------------------------------------------------


def test_everything_said_is_remembered_but_nothing_advances(make_state):
    state = make_state()
    update = apply_understanding(
        state,
        u(
            full_name="Margaret Chen",
            dob="1985-03-15",
            id_last4="4472",
            id_kind_hint="ssn",
            policy_number="POL-9921",
            caller_role="policyholder",
            intents=["denial_question"],
            hint_case_type="healthcare",
            hint_status="denied",
            hint_month=1,
        ),
    )
    assert update.captured_factors == ("full_name", "dob", "id_last4")
    assert state.factors == {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}
    assert state.policy_number == "POL-9921"
    assert state.id_kind_hint == "ssn"
    assert state.caller_role == "policyholder"
    assert state.intent_hint == "denial_question"
    assert (state.case_hints.case_type, state.case_hints.status) == ("healthcare", "denied")
    assert state.case_hints.month == 1
    # remembered, not acted on
    assert state.phase == Phase.VERIFY_ID
    assert state.verified is False
    assert state.resolved_case_id is None


def test_hints_alone_never_unlock_anything(make_state):
    state = make_state()
    apply_understanding(state, u(intents=["denial_question"], hint_status="denied"))
    assert state.phase == Phase.VERIFY_ID and not state.verified
    assert state.factors == {}


def test_corrections_overwrite_and_unchanged_values_are_not_recaptured(make_state):
    state = make_state(dob="1985-03-14")
    assert apply_understanding(state, u(dob="1985-03-15")).captured_factors == ("dob",)
    assert state.factors["dob"] == "1985-03-15"
    assert apply_understanding(state, u(dob="1985-03-15")).captured_factors == ()


def test_later_mentions_fill_in_without_erasing_earlier_ones(make_state):
    state = make_state()
    apply_understanding(state, u(intents=["denial_question"], hint_case_type="healthcare"))
    apply_understanding(state, u(hint_status="denied"))
    apply_understanding(state, u())  # a message with no hints leaves memory alone
    assert state.intent_hint == "denial_question"
    assert (state.case_hints.case_type, state.case_hints.status) == ("healthcare", "denied")


def test_case_hints_are_normalized(make_state):
    state = make_state()
    apply_understanding(state, u(hint_case_type="Medical", hint_case_id=" cl-2048 "))
    assert state.case_hints.case_type == "healthcare"
    assert state.case_hints.case_id == "CL-2048"


# ---- ID kind, refusals, roles -------------------------------------------------------------


def test_id_kind_belongs_to_the_latest_id_value(make_state):
    state = make_state()
    apply_understanding(state, u(id_last4="6688", id_kind_hint="ssn"))
    assert state.id_kind_hint == "ssn"
    apply_understanding(state, u(id_last4="6688"))  # restated without naming a type
    assert state.id_kind_hint == "unspecified"
    apply_understanding(state, u(emotion="neutral"))  # no new ID value: unchanged
    assert state.id_kind_hint == "unspecified"


def test_id_kind_without_an_id_value_is_ignored(make_state):
    state = make_state()
    apply_understanding(state, u(id_kind_hint="ssn"))
    assert state.id_kind_hint is None


def test_a_refused_field_is_remembered_and_forgiven_when_given(make_state):
    state = make_state()
    apply_understanding(state, u(refused_fields=["id_last4"]))
    assert state.refused_fields == {"id_last4"}
    apply_understanding(state, u(id_last4="4472"))
    assert state.refused_fields == set()


def test_a_value_given_in_the_same_message_beats_a_refusal(make_state):
    state = make_state()
    apply_understanding(state, u(refused_fields=["dob"], dob="1985-03-15"))
    assert state.refused_fields == set()


def test_representative_role_is_sticky(make_state):
    state = make_state()
    apply_understanding(state, u(caller_role="representative", rep_name="David Chen"))
    apply_understanding(state, u(caller_role="policyholder"))
    assert state.caller_role == "representative"
    assert state.rep_name == "David Chen"


def test_unknown_role_never_overwrites(make_state):
    state = make_state()
    apply_understanding(state, u(caller_role="policyholder"))
    apply_understanding(state, u(caller_role="unknown"))
    assert state.caller_role == "policyholder"


def test_the_representatives_own_name_is_not_stored_as_the_account_holders(make_state):
    state = make_state()
    apply_understanding(
        state, u(caller_role="representative", rep_name="David Chen", full_name="David Chen")
    )
    assert "full_name" not in state.factors


def test_emotion_is_recorded_per_turn(make_state):
    state = make_state()
    apply_understanding(state, u(emotion="angry", severity=3))
    assert (state.emotion, state.severity) == ("angry", 3)
    apply_understanding(state, u())
    assert (state.emotion, state.severity) == ("neutral", 0)


# ---- audit ----------------------------------------------------------------------------------


def test_audit_events_record_fields_not_values(make_state):
    state = make_state()
    apply_understanding(
        state,
        u(
            full_name="Margaret Chen",
            dob="1985-03-15",
            id_last4="4472",
            intents=["denial_question"],
            hint_status="denied",
            dropped_fields=["phone"],
            fallback_reason="LLMTimeout",
        ),
    )
    assert [e.type for e in state.events] == [
        "PII_CAPTURED",
        "CASE_HINT_CAPTURED",
        "EXTRACTION_DROPPED",
        "LLM_FALLBACK",
    ]
    assert state.events[0].data == {"fields": ["full_name", "dob", "id_last4"]}
    dumped = json.dumps([e.model_dump() for e in state.events])
    for secret in ("Margaret", "1985", "4472"):
        assert secret not in dumped


# ---- the demo turn, end to end up to verification ------------------------------------------


async def test_margaret_demo_turn_understand_remember_verify(store, settings, consent, make_state):
    llm = ScriptedLLM()
    llm.queue_structured(MARGARET_LLM)
    state = make_state()

    understanding = await understand_turn(
        llm, settings, state, MARGARET_MSG, policy_prefixes=("POL",)
    )
    apply_understanding(state, understanding)
    result = verify_identity(state, store, settings, consent)

    assert result.status == VerifyStatus.VERIFIED
    assert state.verified and state.verified_party_id == "P9"
    # the case hint from the first message is still there for RESOLVE_INTENT to use
    assert state.intent_hint == "denial_question"
    assert (state.case_hints.case_type, state.case_hints.status) == ("healthcare", "denied")
    assert state.case_hints.month == 1
    # this layer never moves the phase; the controller does that
    assert state.phase == Phase.VERIFY_ID
    # and no claim data was needed or touched to get here
    assert all(e.type != "TOOL_CALL" for e in state.events)
    assert "CL-2048" not in llm.prompts[0]


async def test_demo_turn_still_verifies_when_the_llm_is_down(
    store, settings, consent, make_state
):
    """With the LLM down, the pre-pass supplies the DOB and ID. The name is the LLM's job, so
    one more factor is needed. Verification is not blocked, just asks for a third factor."""
    llm = ScriptedLLM()
    llm.queue_structured(LLMTimeout("down"))
    state = make_state()
    understanding = await understand_turn(
        llm, settings, state, MARGARET_MSG, policy_prefixes=("POL",)
    )
    apply_understanding(state, understanding)
    assert verify_identity(state, store, settings, consent).status == VerifyStatus.NEED_MORE

    follow_up = await understand_turn(
        ScriptedLLM(), settings, state, "my phone is (650) 521-2836", policy_prefixes=("POL",)
    )
    apply_understanding(state, follow_up)
    assert verify_identity(state, store, settings, consent).status == VerifyStatus.VERIFIED
