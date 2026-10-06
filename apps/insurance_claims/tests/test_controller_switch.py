from datetime import date

import pytest
from agent.acts import ActKind
from agent.clock import FixedClock
from agent.controller import _SWITCH_PHRASES, SopAgent
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
DENTAL = {"claim_switch_request": "my dental claim", "hint_case_type": "dental"}
AUTO = {"claim_switch_request": "my auto claim", "hint_case_type": "auto"}
OLDER_HEALTHCARE = {
    "claim_switch_request": "the older healthcare claim",
    "hint_case_type": "healthcare",
    "hint_year": 2025,
}


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
    """The demo turn, answered, leaving the caller on claim CL-2048 in PROCESS_CASE."""
    agent, llm = make_agent()
    llm.queue_structured(MARGARET_LLM, GOOD)
    state = agent.new_state("s1")
    await agent.handle(state, MARGARET_MSG)
    assert state.resolved_case_id == "CL-2048"
    return agent, llm, state


# ---- switching to another claim ---------------------------------------------------------------


async def test_switching_claims_answers_about_the_new_claim(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(
        {**DENTAL, "intents": ["status_inquiry"]},
        {"reply": "Your dental claim is closed.", "facts_used": ["case.status"]},
    )
    result = await agent.handle(state, "What about my dental claim?")

    assert kinds(result) == [K.CONFIRM_CLAIM, K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert result.phase == Phase.PROCESS_CASE and state.resolved_case_id == "CL-1899"
    assert state.case_loops == 1
    prompt = answer_prompt(llm)
    assert "Claim CL-1899" in prompt and "CL-2048" not in prompt


async def test_the_old_claims_notes_are_archived_and_the_new_record_starts_fresh(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(
        {**DENTAL, "intents": ["status_inquiry"]},
        {"reply": "Your dental claim is closed.", "facts_used": ["case.status"]},
    )
    await agent.handle(state, "What about my dental claim?")

    assert [r.case_id for r in state.closed_cases] == ["CL-2048"]
    assert state.closed_cases[0].topics_discussed == ["why the claim was denied"]
    assert state.case_record.case_id == "CL-1899"
    assert state.case_record.topics_discussed == ["claim status"]


async def test_the_new_description_replaces_the_old_hints(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    assert state.case_hints.status == "denied" and state.case_hints.month == 1
    llm.queue_structured(DENTAL)
    await agent.handle(state, "What about my dental claim?")
    assert state.case_hints.case_type == "dental"
    assert state.case_hints.status is None and state.case_hints.month is None


async def test_another_claim_with_no_details_lists_the_claims_and_asks_which(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured({"claim_switch_request": "another claim"})
    result = await agent.handle(state, "Can I ask about another claim?")
    assert kinds(result) == [K.ASK_DISAMBIGUATION]
    assert result.phase == Phase.RESOLVE_INTENT and state.resolved_case_id is None
    for case_id in ("CL-2048", "CL-2011", "CL-1899", "CL-2102"):
        assert case_id in result.reply
    assert state.case_loops == 1


async def test_a_claim_number_is_enough_even_with_the_llm_down(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    await agent.handle(state, "Can I ask about another claim?")  # nothing queued: LLM down
    assert state.phase == Phase.RESOLVE_INTENT
    result = await agent.handle(state, "CL-2102")
    assert kinds(result) == [K.CONFIRM_CLAIM, K.ASK_WHAT_NEEDED]
    assert state.resolved_case_id == "CL-2102"


async def test_naming_another_claim_number_switches_with_the_llm_down(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    result = await agent.handle(state, "what about CL-2102?")
    assert kinds(result) == [K.CONFIRM_CLAIM, K.ASK_WHAT_NEEDED]
    assert state.resolved_case_id == "CL-2102" and state.case_loops == 1


async def test_describing_the_claim_already_open_is_not_a_switch(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(
        {
            "claim_switch_request": "the denied one",
            "hint_status": "denied",
            "intents": ["denial_question"],
        },
        GOOD,
    )
    result = await agent.handle(state, "what about the denied one?")
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert state.case_loops == 0 and state.closed_cases == []
    assert state.resolved_case_id == "CL-2048"


# ---- the cap -------------------------------------------------------------------------


async def test_the_fourth_switch_offers_a_human_instead(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    expected = [("CL-1899", DENTAL), ("CL-2102", AUTO), ("CL-2011", OLDER_HEALTHCARE)]
    for case_id, request in expected:
        llm.queue_structured(request)
        result = await agent.handle(state, "what about another one?")
        assert kinds(result) == [K.CONFIRM_CLAIM, K.ASK_WHAT_NEEDED]
        assert state.resolved_case_id == case_id

    llm.queue_structured(DENTAL)
    result = await agent.handle(state, "and my dental claim again?")
    assert kinds(result) == [K.OFFER_HUMAN]
    assert result.acts[0].data["reason"] == "case_loop_limit"
    assert state.case_loops == 4
    assert state.resolved_case_id == "CL-2011"  # nothing was changed
    assert len(state.closed_cases) == 3


# ---- recognizing a request for another claim -------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Can I ask about another claim?", True),
        ("What about my dental claim?", True),
        ("what about the other claim", True),
        ("I have a different claim to discuss", True),
        ("What about my claim?", False),
        ("what about this claim?", False),
        ("Why was my claim denied?", False),
        ("How do I submit a claim?", False),
    ],
)
def test_switch_phrases(text, expected):
    assert bool(_SWITCH_PHRASES.search(text)) is expected


# ---- saying goodbye ------------------------------------------------------------------


async def test_thats_all_gets_a_goodbye(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured({"user_done": True})
    result = await agent.handle(state, "no thanks, that's all")
    assert kinds(result) == [K.GOODBYE]
    assert result.phase == Phase.PROCESS_CASE  # interim: the real closing step comes later


async def test_done_plus_a_question_is_still_answered(make_agent):
    agent, llm, state = await after_margaret(make_agent)
    llm.queue_structured(
        {"user_done": True, "intents": ["status_inquiry"]},
        {"reply": "It is currently denied.", "facts_used": ["case.status"]},
    )
    result = await agent.handle(state, "thanks, just one more thing: what's the status?")
    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
