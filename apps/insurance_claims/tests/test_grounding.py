from datetime import date

import pytest
from agent.clock import FixedClock
from agent.context import CaseContext, Fact, build_case_context
from agent.grounding import check_grounding


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
def check(store, make_context):
    """check(reply) against the denied January claim, with the data's document vocabulary."""

    def _check(reply, facts=(), context=None):
        context = context or make_context(intents=["document_submission"])
        return check_grounding(reply, facts, context, store.document_vocabulary())

    return _check


def kinds(result):
    return [v.kind for v in result.violations]


# ---- replies that are supported --------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Your claim CL-2048 was denied because the review file did not include the pathology "
        "report and the treating provider office note.",
        "The maximum allowed amount is $1,450.00 and the net pay is $0.00.",
        "That is $1450, or 1,450 dollars, or 1450.00 in total.",
        "The appeal deadline is March 18, 2026.",
        "The deadline is March 18.",
        "The deadline is 18 March.",
        "The deadline is the 18th of March 2026.",
        "The deadline is 3/18/2026.",
        "The deadline is 2026-03-18.",
        "The claim was created on January 12, 2026.",
        "You have 13 days left.",
        "Please use the member portal or the claim upload link.",
        "Your claim from 2026 is denied.",
        "The allowed amount was about 1,450.",
        "Send the original pathology report from the lab.",
        "Claim cl-2048 is the one.",
        "",
    ],
)
def test_supported_replies_pass(check, reply):
    result = check(reply)
    assert result.ok, result.violations


# ---- concrete values that are not supported ----------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("The allowed amount is $1,540.", ["amount"]),
        ("The difference is $20.", ["amount"]),
        ("That is 20.00 in total.", ["amount"]),
        ("The deadline is March 19, 2026.", ["date"]),
        ("The deadline is March 18, 2027.", ["date"]),
        ("The deadline is March 19.", ["date"]),
        ("The deadline is February 30, 2026.", ["date"]),
        ("The deadline is 3/19/2026.", ["date"]),
        ("This is about claim CL-3001.", ["claim_id"]),
        ("Your policy POL-9921 covers it.", ["claim_id"]),
        ("You have 30 days to appeal.", ["day_count"]),
        ("Please send the repair estimate.", ["document"]),
        ("Please send the diagnosis report.", ["document"]),
        ("You have 7 appeals left.", ["number"]),
        ("This will be settled in 2027.", ["number"]),
    ],
)
def test_unsupported_concrete_values_are_flagged(check, reply, expected):
    assert kinds(check(reply)) == expected


def test_several_problems_are_all_reported(check):
    result = check("CL-3001 was denied for $20 on March 19.")
    assert kinds(result) == ["claim_id", "date", "amount"]


def test_a_derived_amount_is_flagged_even_though_its_parts_are_real(store, make_context):
    context = make_context("CL-2011")  # allowed 800.00, paid 780.00
    vocabulary = store.document_vocabulary()
    assert check_grounding("$780.00 was paid.", [], context, vocabulary).ok
    derived = check_grounding("The difference is $20.", [], context, vocabulary)
    assert kinds(derived) == ["amount"]


# ---- dates without a year: never invent one ------------------------------------------------------


def test_a_date_without_a_year_needs_exactly_one_matching_date_in_the_facts():
    context = CaseContext(
        "X",
        (Fact("a", "first", ("2025-03-18",)), Fact("b", "second", ("2026-03-18",))),
        (),
    )
    assert kinds(check_grounding("It is March 18.", [], context)) == ["ambiguous_date"]
    assert check_grounding("It is March 18, 2026.", [], context).ok
    assert kinds(check_grounding("It is March 18, 2024.", [], context)) == ["date"]
    assert kinds(check_grounding("It is June 5.", [], context)) == ["date"]


# ---- document names ----------------------------------------------------------------------------


def test_documents_are_checked_only_against_the_vocabulary_it_is_given(make_context):
    context = make_context()
    assert check_grounding("Send the repair estimate.", [], context).ok  # no vocabulary given


# ---- fact references (provenance) ----------------------------------------------------------------


def test_cited_fact_ids_must_exist(check):
    ok = check("It was denied.", ["case.status", "case.denial_reason"])
    assert ok.ok and ok.facts_used == ("case.status", "case.denial_reason")

    bad = check("It was denied.", ["case.status", "made.up"])
    assert kinds(bad) == ["fact_id"] and bad.violations[0].detail == "made.up"


def test_cited_ids_are_deduplicated_in_order(check):
    result = check("ok", ["case.status", "case.status", "case.summary"])
    assert result.facts_used == ("case.status", "case.summary")


def test_citations_are_optional(check):
    assert check("It was denied.", []).facts_used == ()


# ---- feedback for a retry ------------------------------------------------------------


def test_feedback_names_each_problem_specifically(check):
    text = check("The difference is $20 and the deadline is March 19.").feedback()
    assert "an amount that is not in the facts: '$20'" in text
    assert "a date that is not in the facts: 'March 19'" in text
    assert text.endswith("Use only the facts provided.")


# ---- limits, pinned so they are documented behavior ----------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Please submit within a week.",
        "You have thirty days to appeal.",
        "It usually takes a couple of days.",
    ],
)
def test_known_limit_durations_in_words_are_not_caught(check, reply):
    """No digits means nothing to check. The prompt and the bounded context cover this."""
    assert check(reply).ok


def test_known_limit_an_invented_reason_with_no_literals_is_not_caught(check):
    """Fact references prove nothing about a sentence: the model can cite a real fact and still
    misstate it. This is why they are provenance metadata, not enforcement."""
    reply = "The claim was denied because the provider submitted the wrong billing code."
    result = check(reply, ["case.denial_reason"])
    assert result.ok
