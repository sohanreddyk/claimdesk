from datetime import date

import pytest
from agent.acts import ActKind
from agent.clock import FixedClock
from agent.controller import SopAgent
from agent.llm.fake import ScriptedLLM

K = ActKind

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
GOOD = {
    "reply": (
        "Your claim was denied because the review file did not include the pathology report "
        "and the treating provider office note."
    ),
    "facts_used": ["case.status", "case.denial_reason"],
}
STATUS_ANSWER = {"reply": "It is currently denied.", "facts_used": ["case.status"]}


@pytest.fixture
def make_agent(store, settings, consent):
    def _make():
        llm = ScriptedLLM()
        agent = SopAgent(
            store=store,
            settings=settings,
            llm=llm,
            clock=FixedClock(date(2026, 3, 5)),
            consent=consent,
        )
        return agent, llm

    return _make


def kinds(result):
    return [a.kind for a in result.acts]


def act_of(result, kind):
    return next(a for a in result.acts if a.kind == kind)


def answer_prompt(llm):
    """The prompt of the most recent grounded-answer call, wherever it falls in the call log."""
    return [c for c in llm.calls if c.schema == "GroundedReply"][-1].user


async def margaret(agent, llm, *queued, extraction=MARGARET_LLM):
    """Run the demo message. `queued` are extra structured results for the answer calls."""
    llm.queue_structured(extraction, *queued)
    state = agent.new_state("s1")
    return state, await agent.handle(state, MARGARET_MSG)


# ---- the demo question is answered in the same turn -------------------------------------------


async def test_a_model_written_answer_is_inserted_as_written(make_agent):
    agent, llm = make_agent()
    state, result = await margaret(agent, llm, GOOD)

    assert kinds(result) == [
        K.VERIFIED_OK,
        K.CONFIRM_CLAIM,
        K.ANSWER_FROM_FACTS,
        K.ASK_ANYTHING_ELSE,
    ]
    assert GOOD["reply"] in result.reply
    assert result.reply.endswith("Is there anything else I can help you with?")
    assert result.used_llm is True
    assert [c.kind for c in llm.calls] == ["structured", "structured"]  # no rephrasing pass
    answer = act_of(result, K.ANSWER_FROM_FACTS).data
    assert answer["source"] == "llm"
    assert answer["facts_used"] == ["case.status", "case.denial_reason"]


async def test_two_ungrounded_answers_fall_back_to_the_facts(make_agent):
    agent, llm = make_agent()
    bad = {"reply": "You have 30 days to appeal.", "facts_used": ["case.status"]}
    state, result = await margaret(agent, llm, bad, bad)

    assert act_of(result, K.ANSWER_FROM_FACTS).data["source"] == "facts"
    assert "30 days" not in result.reply and "March 18, 2026" in result.reply
    assert result.used_llm is False
    event = next(e for e in state.events if e.type == "ANSWER_GENERATED")
    assert event.data == {
        "source": "facts",
        "cited": 5,
        "reason": "grounding_failed",
        "problems": ["day_count"],
    }


async def test_the_answer_prompt_has_this_claims_facts_and_no_identity_values(make_agent):
    agent, llm = make_agent()
    await margaret(agent, llm, GOOD)
    prompt = answer_prompt(llm)
    assert "[case.denial_reason]" in prompt and "Caller's first name: Margaret" in prompt
    assert "[redacted]" in prompt
    for secret in ("1985-03-15", "4472", "POL-9921"):
        assert secret not in prompt
    for other in ("CL-2011", "CL-1899", "CL-2102", "CL-3001"):
        assert other not in prompt


async def test_what_was_cited_and_discussed_is_recorded_for_the_summary(make_agent):
    agent, llm = make_agent()
    state, _ = await margaret(agent, llm, GOOD)
    record = state.case_record
    assert record.facts_used == ["case.status", "case.denial_reason"]
    assert record.topics_discussed == ["why the claim was denied"]
    assert record.documents_needed == ["pathology report", "office note"]
    assert record.appeal_deadline == date(2026, 3, 18)
    assert record.status_outcome == "denied"
    assert state.intent_hint is None  # the remembered request was answered


# ---- tone ----------------------------------------------------------------------------------------


async def test_a_model_answer_carries_the_tone_note_instead_of_a_separate_acknowledgment(
    make_agent,
):
    agent, llm = make_agent()
    angry = {**MARGARET_LLM, "emotion": "angry", "severity": 3}
    state, result = await margaret(agent, llm, GOOD, extraction=angry)
    assert "Tone note: The caller seems angry." in answer_prompt(llm)
    assert K.ACK_EMOTION not in kinds(result)


async def test_a_facts_only_answer_keeps_the_separate_acknowledgment(make_agent):
    agent, llm = make_agent()
    angry = {**MARGARET_LLM, "emotion": "angry", "severity": 3}
    state, result = await margaret(agent, llm, extraction=angry)  # no answer queued: LLM "down"
    assert kinds(result) == [
        K.ACK_EMOTION,
        K.VERIFIED_OK,
        K.CONFIRM_CLAIM,
        K.ANSWER_FROM_FACTS,
        K.ASK_ANYTHING_ELSE,
    ]


# ---- a request remembered from earlier ---------------------------------------------


async def test_a_remembered_request_is_answered_once_the_claim_is_chosen(make_agent):
    agent, llm = make_agent()
    state = agent.new_state("s1")
    message = "I'm Margaret Chen, DOB 1985-03-15, SSN last four 4472. What's my claim's status?"
    llm.queue_structured({"full_name": "Margaret Chen", "intents": ["status_inquiry"]})
    first = await agent.handle(state, message)
    assert kinds(first) == [K.VERIFIED_OK, K.ASK_DISAMBIGUATION]
    assert state.intent_hint == "status_inquiry"

    llm.queue_structured({"hint_status": "denied"}, STATUS_ANSWER)
    second = await agent.handle(state, "the denied one")
    assert kinds(second) == [K.CONFIRM_CLAIM, K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    prompt = answer_prompt(llm)
    assert "CALLER'S QUESTION:\nWhat is the status of this claim?" in prompt
    assert "Caller's first name: Margaret" in prompt
    assert state.intent_hint is None


# ---- questions after the first answer ----------------------------------------------


async def test_a_question_with_two_topics_is_answered_from_both(make_agent):
    agent, llm = make_agent()
    state, _ = await margaret(agent, llm, GOOD)
    two = {
        "intents": ["document_submission"],
        "followup_topics": ["submission_method", "processing_time_after_submission"],
    }
    answer = {
        "reply": (
            "You can use the member portal or the claim upload link, and the average "
            "processing time is usually less than a week."
        ),
        "facts_used": [
            "followup.submission_method",
            "followup.processing_time_after_submission",
        ],
    }
    llm.queue_structured(two, answer)
    question = "Where do I submit the pathology report, and how long will it take once I send it?"
    result = await agent.handle(state, question)

    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    prompt = answer_prompt(llm)
    assert "[followup.submission_method]" in prompt and "[guidance.doc.pathology_report]" in prompt
    assert state.case_record.topics_discussed == [
        "why the claim was denied",
        "document requirements and submission",
        "submission method",
        "processing time after submission",
    ]
    assert "followup.submission_method" in state.case_record.facts_used


async def test_a_message_with_no_question_asks_what_is_needed(make_agent):
    agent, llm = make_agent()
    state, _ = await margaret(agent, llm, GOOD)
    llm.queue_structured({})
    result = await agent.handle(state, "hmm ok")
    assert kinds(result) == [K.ASK_WHAT_NEEDED]
    assert result.reply == "What would you like to know about this claim?"


async def test_with_the_llm_down_a_followup_is_still_answered_from_the_facts(make_agent):
    agent, llm = make_agent()
    state, _ = await margaret(agent, llm, GOOD)
    result = await agent.handle(state, "how long does it take once I send it?")  # nothing queued
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert act_of(result, K.ANSWER_FROM_FACTS).data["source"] == "facts"
    assert "usually less than a week" in result.reply


async def test_repeated_anger_offers_a_human_in_place_of_the_closing_question(make_agent):
    agent, llm = make_agent()
    angry = {"emotion": "angry", "severity": 2, "intents": ["status_inquiry"]}
    state, _ = await margaret(agent, llm, extraction={**MARGARET_LLM, **angry})
    llm.queue_structured(angry)
    await agent.handle(state, "This is taking forever")
    llm.queue_structured(angry)
    third = await agent.handle(state, "Still waiting!")
    assert kinds(third) == [K.ACK_EMOTION, K.ANSWER_FROM_FACTS, K.OFFER_HUMAN]


# ---- safety --------------------------------------------------------------------------


async def test_a_tampered_case_id_fails_closed_without_revealing_anything(make_agent):
    agent, llm = make_agent()
    state, _ = await margaret(agent, llm, GOOD)
    state.resolved_case_id = "CL-3001"  # Ma Tian's claim
    llm.queue_structured({"intents": ["denial_question"]})
    result = await agent.handle(state, "why was it denied?")
    assert kinds(result) == [K.TECH_FALLBACK]
    assert "CL-3001" not in result.reply and "diagnosis" not in result.reply
    last_call = [e for e in state.events if e.type == "TOOL_CALL"][-1]
    assert last_call.data == {"tool": "get_case", "case_id": "CL-3001", "found": False}
