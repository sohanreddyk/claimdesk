from datetime import date

import pytest
from agent.acts import ActKind
from agent.clock import FixedClock
from agent.controller import SopAgent
from agent.llm.fake import ScriptedLLM
from agent.state import Phase

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
ALTERNATIVES = {
    "reply": (
        "You can ask the hospital or lab for a replacement copy, or send a readable scan "
        "for now."
    ),
    "facts_used": ["guidance.alt.pathology_report"],
}
NO_PATHOLOGY = {"cannot_obtain_documents": ["pathology report"]}


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


def answer_prompt(llm):
    return [c for c in llm.calls if c.schema == "GroundedReply"][-1].user


async def after_margaret(make_agent):
    agent, llm = make_agent()
    llm.queue_structured(MARGARET_LLM, GOOD)
    state = agent.new_state("s1")
    await agent.handle(state, MARGARET_MSG)
    return agent, llm, state


# ---- "I can't get that document" -----------------------------------------------------------------


async def test_the_first_time_the_guideline_alternatives_are_given(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY, ALTERNATIVES)
    result = await agent.handle(state, "I can't get the pathology report")

    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert ALTERNATIVES["reply"] in result.reply
    assert state.doc_unavailable == {"pathology report"}
    prompt = answer_prompt(llm)
    assert "[guidance.alt.pathology_report]" in prompt and "replacement copy" in prompt
    assert "[policy.human_review]" not in prompt  # not yet: alternatives come first


async def test_the_second_time_for_the_same_document_goes_to_a_human(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY, ALTERNATIVES)
    await agent.handle(state, "I can't get the pathology report")

    llm.queue_structured(
        NO_PATHOLOGY,
        {
            "reply": "A human claims representative can review the file with you.",
            "facts_used": ["policy.human_review"],
        },
    )
    result = await agent.handle(state, "I still can't get the pathology report")

    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.OFFER_HUMAN]
    assert result.acts[1].data["reason"] == "documents_unavailable"
    assert "[policy.human_review]" in answer_prompt(llm)
    assert state.human_offered is True
    assert result.reply.endswith("Would you like me to connect you?")


async def test_a_different_document_still_gets_its_own_alternatives_first(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY, ALTERNATIVES)
    await agent.handle(state, "I can't get the pathology report")
    llm.queue_structured({"cannot_obtain_documents": ["office note"]})  # answer from the facts
    result = await agent.handle(state, "and I can't get the office note either")
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert state.doc_unavailable == {"pathology report", "office note"}


async def test_the_facts_only_answer_covers_alternatives_and_then_the_review_rule(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY)  # no answer queued: built from the facts
    first = await agent.handle(state, "I can't get the pathology report")
    assert "replacement copy" in first.reply and "human claims representative" not in first.reply

    llm.queue_structured(NO_PATHOLOGY)
    second = await agent.handle(state, "I really can't get the pathology report")
    assert "human claims representative" in second.reply
    assert kinds(second) == [K.ANSWER_FROM_FACTS, K.OFFER_HUMAN]


async def test_which_document_is_asked_when_it_is_unclear(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured({"cannot_obtain_documents": ["it"]})
    result = await agent.handle(state, "I can't get it")
    assert kinds(result) == [K.ASK_WHICH_DOCUMENT]
    assert "pathology report" in result.reply and "office note" in result.reply

    llm.queue_structured({"cannot_obtain_documents": ["the office note"]})
    answer = await agent.handle(state, "the office note")
    assert kinds(answer) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert state.doc_unavailable == {"office note"}


async def test_with_one_requested_document_an_unclear_reference_means_that_one(make_agent):
    agent, llm = make_agent()
    state = agent.new_state("s1")
    llm.queue_structured(
        {"full_name": "Ma Tian", "cannot_obtain_documents": ["it"]},
    )
    message = (
        "I'm Ma Tian, DOB 1964-09-10, national ID last four 6688. I can't get the report."
    )
    result = await agent.handle(state, message)
    assert kinds(result) == [
        K.VERIFIED_OK,
        K.CONFIRM_CLAIM,
        K.ANSWER_FROM_FACTS,
        K.ASK_ANYTHING_ELSE,
    ]
    assert state.doc_unavailable == {"diagnosis report"}
    assert "replacement copy" in result.reply  # the default alternatives: no entry for this one


async def test_something_the_claim_never_asked_for_is_ignored(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured({"cannot_obtain_documents": ["insurance card"]})
    result = await agent.handle(state, "I can't find my insurance card")
    assert kinds(result) == [K.ASK_WHAT_NEEDED]
    assert state.doc_unavailable == set()


async def test_with_the_llm_down_a_phrase_and_a_document_name_are_enough(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    result = await agent.handle(state, "I can't find the pathology report")  # nothing queued
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert "replacement copy" in result.reply
    assert state.doc_unavailable == {"pathology report"}


async def test_with_the_llm_down_a_general_complaint_is_not_mistaken_for_a_missing_document(
    make_agent,
):
    agent, llm, state = await after_margaret(make_agent)
    result = await agent.handle(state, "I can't believe how slow this is")
    assert "replacement copy" not in result.reply
    assert state.doc_unavailable == set()


async def test_leaving_the_claim_clears_the_unavailable_documents(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY, ALTERNATIVES)
    await agent.handle(state, "I can't get the pathology report")
    assert state.doc_unavailable == {"pathology report"}
    llm.queue_structured({"claim_switch_request": "my dental claim", "hint_case_type": "dental"})
    await agent.handle(state, "What about my dental claim?")
    assert state.resolved_case_id == "CL-1899" and state.doc_unavailable == set()


# ---- "I can't do that here" -----------------------------------------------------------


async def test_filing_an_appeal_is_declined_with_the_facts_and_a_human_offer(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured({"requests_action": True})
    result = await agent.handle(state, "Please file an appeal for me")

    assert kinds(result) == [K.UNSUPPORTED_ACTION, K.ANSWER_FROM_FACTS, K.OFFER_HUMAN]
    assert "not able to make requests or changes" in result.reply
    assert "March 18, 2026" in result.reply and "pathology report and office note" in result.reply
    assert result.reply.endswith("Would you like me to connect you?")
    assert "file an appeal for me" not in result.reply  # the request is never echoed back
    assert [c.kind for c in llm.calls[-1:]] == ["structured"]  # extraction only: no answer call


async def test_an_action_request_is_declined_even_with_the_llm_down(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    result = await agent.handle(state, "Please cancel my claim")
    assert kinds(result) == [K.UNSUPPORTED_ACTION, K.ANSWER_FROM_FACTS, K.OFFER_HUMAN]


async def test_how_to_questions_are_answered_not_declined(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    result = await agent.handle(state, "How do I file an appeal?")  # LLM down: still a question
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert K.UNSUPPORTED_ACTION not in kinds(result)


async def test_an_action_request_in_the_first_message_is_declined_after_verification(make_agent):
    agent, llm = make_agent()
    state = agent.new_state("s1")
    llm.queue_structured({**MARGARET_LLM, "requests_action": True})
    result = await agent.handle(state, MARGARET_MSG + " Please file an appeal.")
    assert kinds(result) == [
        K.VERIFIED_OK,
        K.CONFIRM_CLAIM,
        K.UNSUPPORTED_ACTION,
        K.ANSWER_FROM_FACTS,
        K.OFFER_HUMAN,
    ]
    assert result.phase == Phase.PROCESS_CASE


async def test_accepting_the_offer_after_a_declined_request_transfers_to_a_human(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    await agent.handle(state, "Please file an appeal for me")
    result = await agent.handle(state, "yes please")
    assert kinds(result) == [K.TRANSFER_HUMAN]
    assert result.phase == Phase.COMPLETE
