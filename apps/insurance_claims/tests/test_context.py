from datetime import date

import pytest
from agent.clock import FixedClock
from agent.context import build_case_context, facts_block
from agent.fixtures import Case

TODAY = date(2026, 3, 5)


@pytest.fixture
def build(store):
    def _build(case_id, clock=None, **kwargs):
        return build_case_context(
            store.get_case(case_id),
            guidelines=store.guidelines,
            claim_schema=store.claim_schema,
            clock=clock or FixedClock(TODAY),
            **kwargs,
        )

    return _build


def ids(context):
    return [fact.id for fact in context.facts]


def texts(context):
    return {fact.id: fact.text for fact in context.facts}


# ---- a denied claim ---------------------------------------------------------------------


def test_a_denied_claim_becomes_these_facts_in_this_order(build):
    assert ids(build("CL-2048")) == [
        "case.identity",
        "case.status",
        "case.summary",
        "case.denial_reason",
        "case.documents_needed",
        "case.appeal_deadline",
        "deadline.status",
        "amount.expected_reimbursement_amount",
        "amount.allowed_max_amount",
        "amount.net_pay",
        "amount.net_fee",
    ]


def test_the_claim_facts_state_exactly_what_is_on_file(build):
    t = texts(build("CL-2048"))
    assert t["case.identity"] == "Claim CL-2048 is a healthcare claim created on January 12, 2026."
    assert t["case.status"] == "The claim's status is denied."
    assert t["case.denial_reason"] == (
        "Denial reason on file: the review file did not include the pathology report and the "
        "treating provider office note."
    )
    assert t["case.documents_needed"] == (
        "Documents requested for review: pathology report and office note."
    )
    assert t["case.appeal_deadline"] == "The appeal deadline on file is March 18, 2026."


def test_deadline_timing_is_computed_by_code_from_the_clock(build):
    assert texts(build("CL-2048"))["deadline.status"] == (
        "As of March 5, 2026, 13 days remain until that deadline."
    )
    one_day = texts(build("CL-2048", clock=FixedClock(date(2026, 3, 17))))["deadline.status"]
    assert one_day == "As of March 17, 2026, 1 day remains until that deadline."
    today = texts(build("CL-2048", clock=FixedClock(date(2026, 3, 18))))["deadline.status"]
    assert today == "As of March 18, 2026, that deadline is today."
    passed = build("CL-2048", clock=FixedClock(date(2026, 3, 20)))
    assert texts(passed)["deadline.status"] == (
        "As of March 20, 2026, that deadline passed 2 days ago."
    )
    assert "2" in passed.by_id()["deadline.status"].values


def test_amounts_carry_the_meaning_given_in_the_claim_schema(build):
    t = texts(build("CL-2048"))
    assert t["amount.net_pay"] == (
        "Net pay (The finalized amount the insurer paid for the claim) is $0.00."
    )
    assert t["amount.net_fee"].endswith("is $1,450.00.")
    assert "maximum amount an in-network insurer will pay" in t["amount.allowed_max_amount"]
    assert t["amount.expected_reimbursement_amount"].endswith("is $0.00.")


def test_each_fact_lists_the_literal_values_it_supports(build):
    context = build("CL-2048")
    assert context.allowed_values >= {
        "CL-2048",
        "2026-01-12",
        "pathology report",
        "office note",
        "2026-03-18",
        "2026-03-05",
        "13",
        "0.00",
        "1450.00",
    }
    assert context.by_id()["case.identity"].values == ("CL-2048", "2026-01-12")


def test_only_the_resolved_claim_appears(build):
    everything = " ".join(texts(build("CL-2048")).values())
    for other in ("CL-2011", "CL-1899", "CL-2102", "CL-3001"):
        assert other not in everything


# ---- claims that are not denied ------------------------------------------------------------


def test_a_closed_claim_says_plainly_that_there_is_no_denial(build):
    context = build("CL-2011")
    assert ids(context) == [
        "case.identity",
        "case.status",
        "case.summary",
        "case.not_denied",
        "amount.expected_reimbursement_amount",
        "amount.allowed_max_amount",
        "amount.net_pay",
        "amount.net_fee",
    ]
    assert "no denial reason, requested documents or appeal deadline" in texts(context)[
        "case.not_denied"
    ]


def test_derived_amounts_are_never_offered(build):
    context = build("CL-2011")  # allowed 800.00, paid 780.00: the 20.00 difference is not a fact
    assert {"780.00", "800.00"} <= context.allowed_values
    assert "20.00" not in context.allowed_values
    assert "$20.00" not in " ".join(texts(context).values())


def test_an_open_claim_with_nothing_paid_is_stated_as_stored(build):
    t = texts(build("CL-2102"))
    assert t["amount.expected_reimbursement_amount"].endswith("is $3,200.00.")
    assert t["amount.net_pay"].endswith("is $0.00.")
    assert "case.not_denied" in t


def test_optional_fields_that_are_absent_produce_no_facts(store):
    bare = Case(case_id="X-1", party_id="P1", case_type="auto", status="open")
    context = build_case_context(
        bare,
        guidelines=store.guidelines,
        claim_schema=store.claim_schema,
        clock=FixedClock(TODAY),
    )
    assert ids(context) == ["case.identity", "case.status", "case.not_denied"]
    assert texts(context)["case.identity"] == "Claim X-1 is an auto claim."
    assert context.by_id()["case.identity"].values == ("X-1",)


def test_a_denied_claim_with_no_reason_on_file_says_so(store):
    odd = Case(case_id="X-2", party_id="P1", case_type="dental", status="denied")
    context = build_case_context(
        odd,
        guidelines=store.guidelines,
        claim_schema=store.claim_schema,
        clock=FixedClock(TODAY),
    )
    assert "case.no_denial_reason" in ids(context)
    assert "case.not_denied" not in ids(context)


# ---- guidance only when the conversation is about documents --------------------------------


def test_no_guidance_is_included_unless_documents_come_up(build):
    assert not [i for i in ids(build("CL-2048")) if i.startswith("guidance")]
    assert not [i for i in ids(build("CL-2048", intents=["denial_question"])) if "guidance" in i]


def test_a_document_question_brings_the_documents_own_guidance_then_general_guidance(build):
    context = build("CL-2048", intents=["document_submission"])
    guidance = [i for i in ids(context) if i.startswith("guidance")]
    assert guidance == [
        "guidance.doc.pathology_report",
        "guidance.doc.office_note",
        "guidance.case_type",
        "guidance.default",
    ]
    t = texts(context)
    assert t["guidance.doc.pathology_report"].startswith("Guidance for the pathology report:")
    assert "specimen details" in t["guidance.doc.pathology_report"]
    assert t["guidance.case_type"].startswith("Guidance for healthcare claims:")
    assert t["guidance.default"].startswith("General guidance: Use the member portal")


def test_a_document_with_no_guidance_falls_back_without_inventing_any(build):
    context = build("CL-3001", intents=["document_submission"])
    guidance = [i for i in ids(context) if i.startswith("guidance")]
    assert guidance == ["guidance.case_type", "guidance.default"]  # nothing for "diagnosis report"
    assert texts(context)["deadline.status"] == (
        "As of March 5, 2026, 41 days remain until that deadline."
    )


def test_alternatives_and_the_human_review_rule_appear_only_when_asked_for(build):
    plain = build("CL-2048", intents=["document_submission"])
    assert not [i for i in ids(plain) if i.startswith(("guidance.alt", "policy"))]

    context = build(
        "CL-2048", unavailable_docs=["pathology report"], include_human_review=True
    )
    t = texts(context)
    assert "replacement copy" in t["guidance.alt.pathology_report"]
    assert t["guidance.alt.pathology_report"].startswith(
        "If the pathology report cannot be obtained:"
    )
    assert "human claims representative" in t["policy.human_review"]
    assert "guidance.doc.pathology_report" in t  # the document's own guidance comes along


# ---- follow-up questions ---------------------------------------------------------------------

TWO_TOPICS = "Where do I submit the pathology report, and how long will it take once I send it?"


def test_a_question_with_two_topics_gets_both_filled_in(build):
    context = build("CL-2048", question=TWO_TOPICS, intents=["document_submission"])
    assert context.followup_topics == ("submission_method", "processing_time_after_submission")
    t = texts(context)
    assert "member portal" in t["followup.submission_method"]
    assert "pathology report and office note stay attached" in t["followup.submission_method"]
    assert "CL-2048" in t["followup.processing_time_after_submission"]
    assert "usually less than a week" in t["followup.processing_time_after_submission"]


def test_a_followup_template_is_filled_from_the_claim(build):
    context = build("CL-2048", question="When should I submit the documents?")
    assert texts(context)["followup.submission_timing"] == (
        "For claim CL-2048, please submit pathology report and office note within a week."
    )


def test_a_topic_proposed_by_the_llm_is_used_when_eligible(build):
    context = build("CL-2048", question="Where do I upload it?", topics=["submission_method"])
    assert context.followup_topics == ("submission_method",)


def test_a_question_no_rule_covers_gets_the_honest_fallback(build):
    context = build("CL-2048", question="What about my cat?", intents=["next_steps"])
    assert context.followup_topics == ()
    assert texts(context)["followup.fallback"].startswith(
        "I do not see a separate claim-specific rule for that follow-up."
    )


def test_a_denial_or_status_question_never_gets_the_followup_fallback(build):
    for intent in ("denial_question", "status_inquiry", "general_claim_question"):
        context = build("CL-2048", question="Why was it denied?", intents=[intent])
        assert "followup.fallback" not in ids(context)
    assert "followup.fallback" not in ids(build("CL-2048", question="Why was it denied?"))


def test_no_question_means_no_fallback(build):
    assert "followup.fallback" not in ids(build("CL-2048"))


def test_document_rules_do_not_apply_to_a_claim_without_requested_documents(build):
    context = build("CL-2011", question="How long does it take?", intents=["next_steps"])
    assert context.followup_topics == ()
    assert "followup.fallback" not in ids(context)  # there are no requested documents to discuss


# ---- rendering for the prompt ----------------------------------------------------------------


def test_facts_are_rendered_one_labeled_line_each(build):
    context = build("CL-2048")
    block = facts_block(context)
    lines = block.splitlines()
    assert len(lines) == len(context.facts)
    assert "[case.status] The claim's status is denied." in lines
    assert lines[0].startswith("[case.identity] Claim CL-2048")
