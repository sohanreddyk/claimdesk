from datetime import date
from itertools import product

import pytest
from agent.clock import FixedClock
from agent.context import build_case_context
from agent.grounding import check_grounding
from agent.llm.client import LLMBadOutput, LLMTimeout, NotConfiguredClient
from agent.llm.fake import ScriptedLLM
from agent.process import (
    GroundedReply,
    facts_only_answer,
    generate_answer,
    tone_note,
)

GOOD = {
    "reply": (
        "Your claim was denied because the review file did not include the pathology report "
        "and the treating provider office note."
    ),
    "facts_used": ["case.status", "case.denial_reason"],
}
CASES = ["CL-2048", "CL-2011", "CL-1899", "CL-2102", "CL-3001"]
INTENTS = [
    "denial_question",
    "status_inquiry",
    "next_steps",
    "document_submission",
    "general_claim_question",
]


@pytest.fixture
def make_context(store):
    def _make(case_id="CL-2048", **kwargs):
        return build_case_context(
            store.get_case(case_id),
            guidelines=store.guidelines,
            claim_schema=store.claim_schema,
            clock=FixedClock(date(2026, 3, 5)),
            **kwargs,
        )

    return _make


@pytest.fixture
def llm():
    return ScriptedLLM()


async def ask(llm, settings, context, store, question="Why was my claim denied?", **kwargs):
    kwargs.setdefault("intents", ["denial_question"])
    return await generate_answer(
        llm,
        settings,
        context=context,
        question=question,
        known_documents=store.document_vocabulary(),
        **kwargs,
    )


# ---- the model's answer, when it is grounded ---------------------------------------------------


async def test_a_grounded_answer_is_used_as_written(llm, settings, store, make_context):
    llm.queue_structured(GOOD)
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "llm" and answer.fallback_reason is None
    assert answer.reply == GOOD["reply"]
    assert answer.facts_used == ("case.status", "case.denial_reason")
    call = llm.calls[0]
    assert call.model == settings.llm_model and call.schema == "GroundedReply"


async def test_the_model_sees_only_this_claims_facts_and_the_question(
    llm, settings, store, make_context
):
    llm.queue_structured(GOOD)
    await ask(llm, settings, make_context(), store)
    prompt = llm.calls[0].user
    assert "[case.denial_reason] Denial reason on file:" in prompt
    assert "CALLER'S QUESTION:\nWhy was my claim denied?" in prompt
    for other in ("CL-2011", "CL-1899", "CL-2102", "CL-3001"):
        assert other not in prompt
    assert "Caller's first name" not in prompt and "Tone note" not in prompt
    assert "rejected" not in prompt


async def test_name_and_tone_are_passed_along_when_given(llm, settings, store, make_context):
    llm.queue_structured(GOOD)
    await ask(
        llm,
        settings,
        make_context(),
        store,
        caller_first_name="Margaret",
        tone=tone_note("angry", 3),
    )
    prompt = llm.calls[0].user
    assert "Caller's first name: Margaret" in prompt
    assert "Tone note: The caller seems angry." in prompt


async def test_repeated_citations_are_collapsed(llm, settings, store, make_context):
    llm.queue_structured({**GOOD, "facts_used": ["case.status", "case.status"]})
    answer = await ask(llm, settings, make_context(), store)
    assert answer.facts_used == ("case.status",)


# ---- one retry with specific feedback ------------------------------------------------------------


async def test_an_unsupported_amount_gets_one_retry_with_feedback(
    llm, settings, store, make_context
):
    llm.queue_structured({"reply": "You were short by $20.", "facts_used": ["case.status"]}, GOOD)
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "retry" and answer.reply == GOOD["reply"]
    assert len(llm.calls) == 2
    second = llm.calls[1].user
    assert "Your previous reply was rejected." in second
    assert "an amount that is not in the facts: '$20'" in second


async def test_a_made_up_fact_id_is_rejected_and_retried(llm, settings, store, make_context):
    llm.queue_structured({"reply": "It was denied.", "facts_used": ["made.up"]}, GOOD)
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "retry"
    assert "a fact id that does not exist: 'made.up'" in llm.calls[1].user


async def test_an_empty_reply_is_retried(llm, settings, store, make_context):
    llm.queue_structured({"reply": "   ", "facts_used": []}, GOOD)
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "retry" and "The reply was empty." in llm.calls[1].user


async def test_malformed_output_is_retried_once(llm, settings, store, make_context):
    llm.queue_structured(LLMBadOutput("bad"), GOOD)
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "retry" and len(llm.calls) == 2
    assert "not valid structured output" in llm.calls[1].user


# ---- when the model cannot be trusted, the facts speak -----------------------------


async def test_two_ungrounded_answers_fall_back_to_the_facts(llm, settings, store, make_context):
    bad = {"reply": "You have 30 days to appeal.", "facts_used": ["case.status"]}
    llm.queue_structured(bad, bad)
    context = make_context()
    answer = await ask(llm, settings, context, store)
    assert answer.source == "facts" and answer.fallback_reason == "grounding_failed"
    assert [v.kind for v in answer.violations] == ["day_count"]
    assert len(llm.calls) == 2
    assert "30 days" not in answer.reply
    assert check_grounding(answer.reply, answer.facts_used, context, store.document_vocabulary()).ok


async def test_malformed_output_twice_falls_back_with_its_own_reason(
    llm, settings, store, make_context
):
    llm.queue_structured(LLMBadOutput("a"), LLMBadOutput("b"))
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "facts" and answer.fallback_reason == "LLMBadOutput"


async def test_an_outage_goes_straight_to_the_facts_without_a_retry(
    llm, settings, store, make_context
):
    llm.queue_structured(LLMTimeout("slow"))
    answer = await ask(llm, settings, make_context(), store)
    assert answer.source == "facts" and answer.fallback_reason == "LLMTimeout"
    assert len(llm.calls) == 1


async def test_no_api_key_still_answers_from_the_facts(settings, store, make_context):
    answer = await ask(NotConfiguredClient(), settings, make_context(), store)
    assert answer.source == "facts" and answer.fallback_reason == "LLMNotConfigured"
    assert "pathology report" in answer.reply


# ---- the facts-only answer ----------------------------------------------------------


def only(answer):
    return list(answer.facts_used)


def test_a_denial_question_gets_the_reason_documents_and_deadline(store, make_context):
    answer = facts_only_answer(make_context(), ["denial_question"], "why?", reason="x")
    assert only(answer) == [
        "case.status",
        "case.denial_reason",
        "case.documents_needed",
        "case.appeal_deadline",
        "deadline.status",
    ]
    assert "The claim's status is denied." in answer.reply
    assert "March 18, 2026" in answer.reply and "13 days remain" in answer.reply
    assert "$" not in answer.reply


def test_a_status_question_gets_status_and_summary_only(make_context):
    answer = facts_only_answer(make_context(), ["status_inquiry"], "where is it?", reason="x")
    assert only(answer) == ["case.status", "case.summary"]


def test_a_denial_question_about_a_claim_that_is_not_denied_says_so(make_context):
    answer = facts_only_answer(make_context("CL-2011"), ["denial_question"], "why?", reason="x")
    assert only(answer) == ["case.status", "case.not_denied"]
    assert "not denied" in answer.reply


def test_next_steps_on_a_claim_that_is_not_denied(make_context):
    answer = facts_only_answer(make_context("CL-2011"), ["next_steps"], "what now?", reason="x")
    assert only(answer) == ["case.status", "case.not_denied"]


def test_a_document_question_gets_documents_and_guidance(make_context):
    context = make_context(intents=["document_submission"])
    answer = facts_only_answer(context, ["document_submission"], "what do I send?", reason="x")
    assert only(answer) == [
        "case.documents_needed",
        "guidance.doc.pathology_report",
        "guidance.doc.office_note",
        "guidance.case_type",
        "guidance.default",
    ]


def test_no_intent_gets_the_general_picture(make_context):
    answer = facts_only_answer(make_context(), [], "hmm", reason="x")
    assert only(answer) == ["case.identity", "case.status", "case.summary"]


def test_a_question_about_payment_adds_the_amount_facts(make_context):
    question = "How much was I paid?"
    answer = facts_only_answer(make_context(), ["status_inquiry"], question, reason="x")
    assert only(answer) == [
        "case.status",
        "case.summary",
        "amount.expected_reimbursement_amount",
        "amount.allowed_max_amount",
        "amount.net_pay",
        "amount.net_fee",
    ]


def test_matched_followup_rules_are_always_included(make_context):
    question = "How long does it take once I send it?"
    context = make_context(question=question, intents=["document_submission"])
    answer = facts_only_answer(context, ["status_inquiry"], question, reason="x")
    assert "followup.processing_time_after_submission" in only(answer)
    assert "usually less than a week" in answer.reply


@pytest.mark.parametrize(("case_id", "intent"), list(product(CASES, INTENTS + [None])))
def test_the_facts_only_answer_is_grounded_by_construction(store, make_context, case_id, intent):
    """For every claim and intent, the plain fallback passes the same guard the model faces."""
    question = "How much was I paid, and how long does it take?"
    intents = [intent] if intent else []
    context = make_context(case_id, question=question, intents=intents)
    answer = facts_only_answer(context, intents, question, reason="x")
    assert answer.reply
    result = check_grounding(answer.reply, answer.facts_used, context, store.document_vocabulary())
    assert result.ok, (case_id, intent, result.violations)


# ---- small pieces -------------------------------------------------------------------


def test_tone_note_only_when_the_caller_sounds_upset():
    assert tone_note("frustrated", 2) == (
        "The caller seems frustrated. Open with one brief, sincere acknowledgment, then answer."
    )
    assert tone_note("neutral", 3) is None
    assert tone_note("angry", 0) is None


def test_the_reply_schema_defaults():
    assert GroundedReply(reply="hi").facts_used == []
