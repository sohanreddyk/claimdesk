"""Wording rules that came out of running the agent against a real model."""

from agent.acts import ActKind, act
from agent.llm.process_prompts import PROCESS_SYSTEM
from agent.llm.prompts import EXTRACTION_SYSTEM
from agent.templates import template

CASE = {
    "case_id": "CL-2048",
    "case_type": "healthcare",
    "created_at": "2026-01-12",
    "status": "denied",
}


def test_a_claim_is_confirmed_to_its_owner_as_theirs():
    text = template(act(ActKind.CONFIRM_CLAIM, case=CASE, representative=False))
    assert text.startswith("I found your healthcare claim CL-2048")


def test_a_claim_is_confirmed_to_a_representative_as_the_claim_not_their_claim():
    text = template(act(ActKind.CONFIRM_CLAIM, case=CASE, representative=True))
    assert text.startswith("I found the healthcare claim CL-2048")
    assert "your" not in text.split("Let me know")[0].lower()


def test_the_offer_after_a_privacy_notice_is_short_and_does_not_repeat_it():
    text = template(
        act(ActKind.OFFER_EMAIL_SUMMARY, masked="m***@email.com", restricted=True, brief=True)
    )
    assert text == (
        "Would you like me to email the summary to m***@email.com? You can say yes, or skip it."
    )


def test_the_full_offer_still_explains_the_restriction_when_it_comes_first():
    text = template(act(ActKind.OFFER_EMAIL_SUMMARY, masked="m***@email.com", restricted=True))
    assert text.count("For privacy") == 1 and "address on file" in text


# These pin the instructions that stop the real model from over-answering. The behavior
# itself can only be judged against the live model (scripts/smoke_llm.py and the demo).


def test_claim_answers_must_not_greet_or_reintroduce_the_claim():
    assert 'Do not open with a greeting such as "Hi" or "Hello"' in PROCESS_SYSTEM
    assert "Do not restate the claim number" in PROCESS_SYSTEM
    assert "Do not offer a human representative in any other case" in PROCESS_SYSTEM


def test_intents_are_limited_to_what_the_message_actually_asks():
    assert "leave intents empty" in EXTRACTION_SYSTEM
    assert "one or two that fit best" in EXTRACTION_SYSTEM
    assert "means denial_question" in EXTRACTION_SYSTEM
