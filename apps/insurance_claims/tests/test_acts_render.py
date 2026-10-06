import pytest
from agent.acts import (
    Act,
    ActKind,
    act,
    case_phrase,
    describe,
    format_date,
    join_words,
    labels,
)
from agent.guard import CLAIM_LEAK, PII_ECHO, find_violations
from agent.llm.client import LLMTimeout
from agent.llm.fake import ScriptedLLM
from agent.llm.render_prompts import RENDER_SYSTEM
from agent.render import MAX_REPLY_CHARS, render_reply
from agent.templates import _HUMAN_OFFER, render_templates, template

CASE = {
    "case_id": "CL-2048",
    "case_type": "healthcare",
    "created_at": "2026-01-12",
    "status": "denied",
}
CASE_2 = {
    "case_id": "CL-2011",
    "case_type": "healthcare",
    "created_at": "2025-01-28",
    "status": "closed",
}

SAMPLES = {
    ActKind.EMPTY_MESSAGE: {},
    ActKind.ACK_EMOTION: {"emotion": "frustrated", "severity": 2},
    ActKind.EXPLAIN_WHY_VERIFY: {},
    ActKind.ACK_FIELDS_PROVIDED: {"fields": ["full_name", "dob"]},
    ActKind.OFFER_ALT_FIELDS: {"fields": ["phone", "email"]},
    ActKind.REQUEST_FIELDS: {"fields": ["phone", "email"], "need": 1},
    ActKind.VERIFY_GENERIC_MISMATCH: {},
    ActKind.REQUEST_REP_IDENTITY: {},
    ActKind.CONSENT_RESULT: {"status": "approved"},
    ActKind.VERIFIED_OK: {},
    ActKind.CONFIRM_CLAIM: {"case": CASE},
    ActKind.ASK_DISAMBIGUATION: {"options": [CASE, CASE_2]},
    ActKind.NO_CLAIMS_FOUND: {},
    ActKind.DECLINE_OOS: {"level": 1},
    ActKind.DECLINE_INSTRUCTION: {},
    ActKind.ANSWER_GENERAL_INSURANCE: {"question": "What is a deductible?"},
    ActKind.OFFER_HUMAN: {"reason": "frustration"},
    ActKind.TRANSFER_HUMAN: {},
    ActKind.SESSION_ENDED: {},
    ActKind.TECH_FALLBACK: {},
    ActKind.ANSWER_FROM_FACTS: {
        "reply": "Your claim was denied.",
        "facts_used": ["case.status"],
        "source": "llm",
    },
    ActKind.ASK_ANYTHING_ELSE: {},
    ActKind.ASK_WHAT_NEEDED: {},
    ActKind.GOODBYE: {},
    ActKind.UNSUPPORTED_ACTION: {},
    ActKind.ASK_WHICH_DOCUMENT: {"options": ["pathology report", "office note"]},
}


# ---- acts and templates ---------------------------------------------------------------


def test_every_act_kind_has_a_sample_so_new_kinds_must_be_covered():
    assert set(SAMPLES) == set(ActKind)


@pytest.mark.parametrize("kind", list(ActKind))
def test_every_act_has_a_description_and_a_fallback_template(kind):
    sample = Act(kind, SAMPLES[kind])
    assert describe(sample).strip()
    assert template(sample).strip()


def test_helpers():
    assert join_words([]) == ""
    assert join_words(["a"]) == "a"
    assert join_words(["a", "b"]) == "a and b"
    assert join_words(["a", "b", "c"], "or") == "a, b or c"
    assert format_date("2026-01-12") == "January 12, 2026"
    assert format_date(None) == "an unknown date"
    assert case_phrase(CASE) == "healthcare claim CL-2048 from January 12, 2026 (denied)"
    assert labels(["dob", "weird"]) == ["your date of birth", "weird"]


def test_request_fields_wording_scales_with_what_is_needed():
    one = template(act(ActKind.REQUEST_FIELDS, fields=["dob"], need=1))
    assert one == "Could you share your date of birth?"
    one_of_many = template(act(ActKind.REQUEST_FIELDS, fields=["phone", "email"], need=1))
    assert "one more detail" in one_of_many and "or your email address" in one_of_many
    three = template(act(ActKind.REQUEST_FIELDS, fields=["phone", "email", "dob"], need=3))
    assert "3 more details" in three


def test_the_id_field_is_always_described_generically():
    wording = template(act(ActKind.REQUEST_FIELDS, fields=["id_last4"], need=1))
    assert "SSN or national ID" in wording


def test_every_human_offer_asks_a_question():
    for reason in _HUMAN_OFFER:
        text = template(act(ActKind.OFFER_HUMAN, reason=reason))
        assert text.endswith("?") and "connect you" in text


def test_unknown_reasons_and_emotions_still_render():
    assert template(act(ActKind.OFFER_HUMAN, reason="something new")).endswith("?")
    assert template(act(ActKind.ACK_EMOTION, emotion="mystified")).strip()


def test_templates_join_in_order():
    text = render_templates(
        [act(ActKind.VERIFIED_OK), act(ActKind.CONFIRM_CLAIM, case=CASE)]
    )
    assert text.startswith("Thank you, you're verified. I found your healthcare claim CL-2048")


def test_disambiguation_lists_every_option_and_notes_when_nothing_matched():
    plain = template(act(ActKind.ASK_DISAMBIGUATION, options=[CASE, CASE_2]))
    assert "CL-2048" in plain and "CL-2011" in plain and plain.endswith("Which one do you mean?")
    none = template(act(ActKind.ASK_DISAMBIGUATION, options=[CASE], none_matched=True))
    assert "couldn't find a claim that matches" in none


def test_descriptions_carry_the_facts_and_the_limits():
    assert "CL-2048" in describe(act(ActKind.CONFIRM_CLAIM, case=CASE))
    assert "Do not say whether any are correct" in describe(
        act(ActKind.ACK_FIELDS_PROVIDED, fields=["dob"])
    )
    assert "Do not answer it" in describe(act(ActKind.DECLINE_OOS, level=1))
    assert "claim status" in describe(act(ActKind.DECLINE_OOS, level=2))
    assert "Do not mention any claim details" in describe(act(ActKind.EXPLAIN_WHY_VERIFY))


# ---- renderer ---------------------------------------------------------------------------


@pytest.fixture
def llm():
    return ScriptedLLM()


async def test_the_llm_text_is_used_when_it_is_usable(llm, settings):
    llm.queue_text("Happy to help! Could you share your date of birth?")
    acts = [act(ActKind.REQUEST_FIELDS, fields=["dob"], need=1)]
    rendered = await render_reply(llm, settings, acts, caller_first_name="Margaret")
    assert rendered.used_llm and rendered.fallback_reason is None
    assert rendered.text == "Happy to help! Could you share your date of birth?"
    call = llm.calls[0]
    assert call.model == settings.llm_model and call.system == RENDER_SYSTEM
    assert "1. Ask for 1 more detail" in call.user
    assert "Caller's first name: Margaret" in call.user


async def test_surrounding_quotes_are_stripped(llm, settings):
    llm.queue_text('"Hello there."')
    rendered = await render_reply(llm, settings, [act(ActKind.VERIFIED_OK)])
    assert rendered.text == "Hello there."


async def test_instructions_are_numbered_in_act_order(llm, settings):
    llm.queue_text("ok")
    await render_reply(
        llm, settings, [act(ActKind.ACK_EMOTION, emotion="angry"), act(ActKind.EXPLAIN_WHY_VERIFY)]
    )
    user = llm.calls[0].user
    assert user.index("1. Acknowledge") < user.index("2. Explain")


@pytest.mark.parametrize("failure", [LLMTimeout("slow"), None])
async def test_llm_failure_falls_back_to_templates(llm, settings, failure):
    if failure is not None:
        llm.queue_text(failure)  # nothing queued at all also fails (LLMUnavailable)
    acts = [act(ActKind.VERIFIED_OK)]
    rendered = await render_reply(llm, settings, acts)
    assert not rendered.used_llm and rendered.fallback_reason
    assert rendered.text == render_templates(acts)


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_REPLY_CHARS + 1)])
async def test_unusable_llm_text_falls_back(llm, settings, bad):
    llm.queue_text(bad)
    rendered = await render_reply(llm, settings, [act(ActKind.VERIFIED_OK)])
    assert not rendered.used_llm and rendered.fallback_reason == "UnusableOutput"


async def test_no_acts_renders_the_safe_fallback(llm, settings):
    rendered = await render_reply(llm, settings, [])
    assert "haven't changed or guessed anything" in rendered.text


# ---- output guard -----------------------------------------------------------------------


def verified(state, party="P9"):
    state.verified = True
    state.verified_party_id = party
    return state


@pytest.mark.parametrize(
    "leak",
    [
        "Your claim CL-2048 was denied.",
        "It was denied because the pathology report was missing.",
        "You still need to send the office note.",
        "The allowed amount is 1450.00.",
        "That comes to $1,450.00 in total.",
        "Healthcare claim denied due to missing pathology report and office note",
    ],
)
def test_claim_details_are_blocked_before_verification(store, make_state, leak):
    assert find_violations(leak, make_state(), store) == [CLAIM_LEAK]


def test_clean_text_has_no_violations(store, make_state):
    text = "Thanks, Margaret. Could you share your date of birth?"
    assert find_violations(text, make_state(), store) == []


def test_claim_details_are_allowed_after_verification(store, make_state):
    state = verified(make_state())
    assert find_violations("Your claim CL-2048 was denied.", state, store) == []


def test_small_amounts_are_not_treated_as_claim_data(store, make_state):
    assert find_violations("That is $0.00 so far.", make_state(), store) == []


def test_typed_pii_is_never_echoed(store, make_state):
    state = make_state(
        id_last4="4472", dob="1985-03-15", phone="+16505212836", email="margaret@email.com"
    )
    for echo in (
        "I noted 4472.",
        "Born 1985-03-15, right?",
        "Is 650-521-2836 your number?",
        "I'll write to Margaret@Email.com.",
    ):
        assert find_violations(echo, state, store) == [PII_ECHO], echo


def test_an_id_inside_a_longer_number_is_not_an_echo(store, make_state):
    state = make_state(id_last4="4472")
    assert find_violations("Reference 144720 is noted.", state, store) == []


def test_on_file_pii_is_never_repeated_for_the_matched_account(store, make_state):
    state = make_state()
    state.candidate_party_id = "P9"
    assert find_violations("Your birthday is 1985-03-15.", state, store) == [PII_ECHO]
    assert find_violations("I'll email m***@email.com.", state, store) == []  # masked form is fine


def test_pii_of_other_accounts_is_not_tracked_for_this_caller(store, make_state):
    state = make_state()
    state.candidate_party_id = "P9"
    assert find_violations("Ava was born 1990-08-21.", state, store) == []
