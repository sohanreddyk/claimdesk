from datetime import date

import pytest
from agent.acts import ActKind
from agent.clock import FixedClock
from agent.controller import SopAgent
from agent.llm.fake import ScriptedLLM
from agent.outbox import EmailSendError, Outbox
from agent.state import EmailState, Phase
from agent.summary import SUBJECT

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
    "reply": "You can ask the hospital or lab for a replacement copy.",
    "facts_used": ["guidance.alt.pathology_report"],
}
REVIEW = {
    "reply": "A human claims representative can review the file with you.",
    "facts_used": ["policy.human_review"],
}
NO_PATHOLOGY = {"cannot_obtain_documents": ["pathology report"]}
DENTAL = {"claim_switch_request": "my dental claim", "hint_case_type": "dental"}
YES = {"email_consent": "yes"}
NO = {"email_consent": "no"}
ON_FILE = "m***@email.com"


class FlakySender:
    """Fails the first time, then works."""

    def __init__(self):
        self.calls = 0
        self.sent = []

    def send(self, email):
        self.calls += 1
        if self.calls == 1:
            raise EmailSendError("the mail service is down")
        self.sent.append(email)


@pytest.fixture
def make_agent(store, settings, consent):
    def _make(sender=None):
        llm = ScriptedLLM()
        outbox = Outbox()
        agent = SopAgent(
            store=store,
            settings=settings,
            llm=llm,
            clock=FixedClock(date(2026, 3, 5)),
            consent=consent,
            sender=sender or outbox,
        )
        return agent, llm, outbox

    return _make


def kinds(result):
    return [a.kind for a in result.acts]


def transitions(state):
    return [(e.data["from"], e.data["to"]) for e in state.events if e.type == "PHASE_TRANSITION"]


async def after_margaret(make_agent, sender=None):
    agent, llm, outbox = make_agent(sender)
    llm.queue_structured(MARGARET_LLM, GOOD)
    state = agent.new_state("s1")
    await agent.handle(state, MARGARET_MSG)
    return agent, llm, state, outbox


async def offer(agent, llm, state):
    llm.queue_structured({"user_done": True})
    return await agent.handle(state, "no thanks, that's all")


async def say(agent, llm, state, text, extraction=None):
    if extraction is not None:
        llm.queue_structured(extraction)
    return await agent.handle(state, text)


# ---- the offer -----------------------------------------------------------------------------------


async def test_thats_all_offers_the_summary_at_the_masked_address_on_file(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    result = await offer(agent, llm, state)

    assert kinds(result) == [K.OFFER_EMAIL_SUMMARY] and result.phase == Phase.POST_PROCESS
    assert ON_FILE in result.reply and "margaret@email.com" not in result.reply
    assert result.reply.endswith("You can say yes, skip it, or give me a different address.")
    assert state.email_state == EmailState.OFFERED
    assert outbox.sent() == []
    assert result.used_llm is False  # consent wording is fixed, never model-phrased


# ---- yes sends, no skips -------------------------------------------------------------------------


async def test_an_explicit_yes_sends_the_summary_and_ends_the_session(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await say(agent, llm, state, "yes please", YES)

    assert kinds(result) == [K.EMAIL_SENT, K.GOODBYE] and result.phase == Phase.COMPLETE
    assert result.reply.startswith(f"I've sent the summary to {ON_FILE}.")
    assert state.email_state == EmailState.SENT

    (email,) = outbox.sent()
    assert email.to == "margaret@email.com" and email.subject == SUBJECT
    assert email.body.startswith("Hello Margaret,")
    assert "Claim CL-2048 (healthcare)" in email.body and "Status: denied" in email.body
    assert "- why the claim was denied" in email.body
    assert "- Submit the requested documents: pathology report and office note." in email.body
    assert "13 days remaining" in email.body
    for secret in ("1985-03-15", "4472", "6505212836", "margaret@email.com"):
        assert secret not in email.body


async def test_an_explicit_no_skips_it(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await say(agent, llm, state, "no thanks", NO)
    assert kinds(result) == [K.EMAIL_SKIPPED, K.GOODBYE] and result.phase == Phase.COMPLETE
    assert state.email_state == EmailState.SKIPPED and outbox.sent() == []


async def test_after_the_session_ends_nothing_more_happens(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    await say(agent, llm, state, "yes", YES)
    result = await agent.handle(state, "wait, one more thing")
    assert kinds(result) == [K.SESSION_ENDED] and len(outbox.sent()) == 1


# ---- anything unclear is asked again, and never sends --------------------------------------------


async def test_a_bare_okay_is_not_consent_even_when_the_model_says_yes(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await say(agent, llm, state, "okay", YES)
    assert kinds(result) == [K.CLARIFY_CONSENT]
    assert result.reply == f"Just to be sure: should I send the summary to {ON_FILE}, or skip it?"
    assert outbox.sent() == [] and state.email_state == EmailState.OFFERED

    sent = await say(agent, llm, state, "yes please", YES)
    assert kinds(sent) == [K.EMAIL_SENT, K.GOODBYE] and len(outbox.sent()) == 1


@pytest.mark.parametrize("model_says", [None, YES, {"email_consent": "unclear"}, {}])
async def test_hedges_and_questions_never_send_whatever_the_model_or_outage_does(
    make_agent, model_says
):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    for text in ("okay", "sure", "fine", "mm-hmm", "what does it include?"):
        result = await say(agent, llm, state, text, model_says)
        assert kinds(result) == [K.CLARIFY_CONSENT]
    assert outbox.sent() == [] and state.phase == Phase.POST_PROCESS


async def test_with_the_llm_down_explicit_phrases_still_work(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    assert kinds(await agent.handle(state, "sure")) == [K.CLARIFY_CONSENT]
    result = await agent.handle(state, "send it")
    assert kinds(result) == [K.EMAIL_SENT, K.GOODBYE] and len(outbox.sent()) == 1


async def test_with_the_llm_down_no_thanks_skips(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await agent.handle(state, "no thanks")
    assert kinds(result) == [K.EMAIL_SKIPPED, K.GOODBYE] and outbox.sent() == []


# ---- a different address ----------------------------------------------------------


async def test_a_different_address_is_read_back_and_needs_a_second_yes(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await say(
        agent,
        llm,
        state,
        "please send it to work@example.com instead",
        {"alt_email": "work@example.com", "email_consent": "yes"},
    )
    assert kinds(result) == [K.CONFIRM_EMAIL_ADDRESS]
    assert result.reply == "I'll send it to w***@example.com instead. Is that right?"
    assert state.email_state == EmailState.ADDRESS_CONFIRM and outbox.sent() == []

    sent = await say(agent, llm, state, "yes", YES)
    assert kinds(sent) == [K.EMAIL_SENT, K.GOODBYE]
    assert outbox.sent()[0].to == "work@example.com"
    assert "work@example.com" not in sent.reply  # only the masked form is ever spoken


async def test_rejecting_a_proposed_address_returns_to_the_one_on_file(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    await say(agent, llm, state, "send it to work@example.com", {"alt_email": "work@example.com"})
    result = await say(agent, llm, state, "no", NO)
    assert kinds(result) == [K.OFFER_EMAIL_SUMMARY] and ON_FILE in result.reply
    assert state.email_alt_attempts == 1 and state.email_state == EmailState.OFFERED

    sent = await say(agent, llm, state, "yes", YES)
    assert outbox.sent()[0].to == "margaret@email.com" and kinds(sent)[0] == K.EMAIL_SENT


async def test_after_two_rejected_alternatives_only_the_address_on_file_is_offered(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    for address in ("one@example.com", "two@example.com"):
        await say(agent, llm, state, f"send it to {address}", {"alt_email": address})
        await say(agent, llm, state, "no", NO)
    assert state.email_alt_attempts == 2

    result = await say(
        agent,
        llm,
        state,
        "send it to three@example.com",
        {"alt_email": "three@example.com"},
    )
    assert kinds(result) == [K.EMAIL_ADDRESS_LOCKED, K.OFFER_EMAIL_SUMMARY]
    assert "For privacy, I can only send the summary to the address on file." in result.reply
    assert result.reply.count("For privacy") == 1
    assert state.email_state == EmailState.OFFERED and outbox.sent() == []

    await say(agent, llm, state, "yes", YES)
    assert [e.to for e in outbox.sent()] == ["margaret@email.com"]


async def test_an_unclear_answer_to_a_proposed_address_names_that_address(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    await say(agent, llm, state, "send it to work@example.com", {"alt_email": "work@example.com"})
    result = await say(agent, llm, state, "hmm", {"email_consent": "unclear"})
    assert kinds(result) == [K.CLARIFY_CONSENT] and "w***@example.com" in result.reply
    assert outbox.sent() == []


# ---- a representative --------------------------------------------------------------


async def test_a_representative_can_only_use_the_address_on_file(make_agent):
    agent, llm, outbox = make_agent()
    state = agent.new_state("s1")
    rep_message = (
        "I'm David Chen, Margaret's son. Her DOB is 1985-03-15, SSN last four 4472, "
        "and her phone is 650-521-2836."
    )
    llm.queue_structured(
        {"caller_role": "representative", "rep_name": "David Chen", "rep_relationship": "son"}
    )
    await agent.handle(state, rep_message)
    picked = await agent.handle(state, "CL-2048")  # picks the claim by number, no LLM needed
    assert state.verified_as == "representative" and state.resolved_case_id == "CL-2048"
    assert "I found the healthcare claim CL-2048" in picked.reply  # it is not their claim
    assert "I found your" not in picked.reply

    first = await offer(agent, llm, state)
    assert kinds(first) == [K.OFFER_EMAIL_SUMMARY] and ON_FILE in first.reply
    assert "For privacy, I can only send it to the address on file." in first.reply

    other = await say(
        agent,
        llm,
        state,
        "send it to me at david@example.com",
        {"alt_email": "david@example.com"},
    )
    assert kinds(other) == [K.EMAIL_ADDRESS_LOCKED, K.OFFER_EMAIL_SUMMARY]
    assert other.reply.count("For privacy") == 1  # the notice is not repeated by the offer
    assert state.email_state == EmailState.OFFERED

    await say(agent, llm, state, "yes", YES)
    (email,) = outbox.sent()
    assert email.to == "margaret@email.com" and email.body.startswith("Hello Margaret,")


# ---- no address, and failures -------------------------------------------------------


async def test_with_no_address_on_file_the_agent_says_so_and_ends(make_agent, store, monkeypatch):
    monkeypatch.setattr(store.get_party("P9"), "email", None)
    agent, llm, state, outbox = await after_margaret(make_agent)
    result = await offer(agent, llm, state)
    assert kinds(result) == [K.EMAIL_UNAVAILABLE, K.GOODBYE] and result.phase == Phase.COMPLETE
    assert "can't send a summary" in result.reply and outbox.sent() == []


async def test_a_failed_send_keeps_the_offer_open_and_a_retry_works(make_agent):
    flaky = FlakySender()
    agent, llm, state, _ = await after_margaret(make_agent, sender=flaky)
    await offer(agent, llm, state)

    failed = await say(agent, llm, state, "yes", YES)
    assert kinds(failed) == [K.EMAIL_FAILED] and failed.phase == Phase.POST_PROCESS
    assert failed.reply == "I couldn't send the summary just now. Would you like me to try again?"
    assert state.email_state == EmailState.OFFERED

    again = await say(agent, llm, state, "yes", YES)
    assert kinds(again) == [K.EMAIL_SENT, K.GOODBYE] and len(flaky.sent) == 1


# ---- going back to the claim --------------------------------------------------------


async def test_a_question_about_this_claim_returns_to_process_case_without_reconfirming_it(
    make_agent,
):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    llm.queue_structured(
        {"intents": ["next_steps"]},
        {
            "reply": "You can appeal until the deadline on file.",
            "facts_used": ["case.appeal_deadline"],
        },
    )
    result = await agent.handle(state, "Actually, how long do I have to appeal?")

    assert kinds(result) == [K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert K.CONFIRM_CLAIM not in kinds(result)
    assert result.phase == Phase.PROCESS_CASE and state.resolved_case_id == "CL-2048"
    assert ("POST_PROCESS", "PROCESS_CASE") in transitions(state)
    assert ("POST_PROCESS", "RESOLVE_INTENT") not in transitions(state)
    assert state.email_state == EmailState.NOT_OFFERED and outbox.sent() == []

    again = await offer(agent, llm, state)  # when they are done again, it is offered again
    assert kinds(again) == [K.OFFER_EMAIL_SUMMARY] and again.phase == Phase.POST_PROCESS


async def test_another_claim_goes_through_resolution(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    llm.queue_structured(
        {**DENTAL, "intents": ["status_inquiry"]},
        {"reply": "Your dental claim is closed.", "facts_used": ["case.status"]},
    )
    result = await agent.handle(state, "what about my dental claim?")

    assert transitions(state)[-3:] == [
        ("PROCESS_CASE", "POST_PROCESS"),
        ("POST_PROCESS", "RESOLVE_INTENT"),
        ("RESOLVE_INTENT", "PROCESS_CASE"),
    ]
    assert kinds(result) == [K.CONFIRM_CLAIM, K.ANSWER_FROM_FACTS, K.ASK_ANYTHING_ELSE]
    assert state.resolved_case_id == "CL-1899" and state.email_state == EmailState.NOT_OFFERED


async def test_another_claim_with_no_details_waits_in_resolution(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    await offer(agent, llm, state)
    result = await say(
        agent, llm, state, "can I ask about another claim?", {"claim_switch_request": "another"}
    )
    assert kinds(result) == [K.ASK_DISAMBIGUATION] and result.phase == Phase.RESOLVE_INTENT


# ---- what the email contains --------------------------------------------------------


async def test_every_claim_discussed_is_in_the_summary(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    llm.queue_structured(
        {**DENTAL, "intents": ["status_inquiry"]},
        {"reply": "Your dental claim is closed.", "facts_used": ["case.status"]},
    )
    await agent.handle(state, "what about my dental claim?")
    await offer(agent, llm, state)
    await say(agent, llm, state, "yes", YES)

    body = outbox.sent()[0].body
    assert "about your claims." in body
    assert body.index("Claim CL-2048 (healthcare)") < body.index("Claim CL-1899 (dental)")
    assert "- claim status" in body


async def test_missing_documents_and_the_human_review_option_reach_the_summary(make_agent):
    agent, llm, state, outbox = await after_margaret(make_agent)
    llm.queue_structured(NO_PATHOLOGY, ALTERNATIVES)
    await agent.handle(state, "I can't get the pathology report")
    llm.queue_structured(NO_PATHOLOGY, REVIEW)
    await agent.handle(state, "I still can't get the pathology report")
    await offer(agent, llm, state)
    await say(agent, llm, state, "yes", YES)

    body = outbox.sent()[0].body
    assert "- You mentioned you could not get: pathology report." in body
    review = "- A human claims representative can review the file with you for manual options."
    assert review in body


# ---- ending without a claim ---------------------------------------------------------


async def test_finishing_before_any_claim_was_chosen_just_says_goodbye(make_agent):
    agent, llm, outbox = make_agent()
    state = agent.new_state("s1")
    message = "I'm Margaret Chen, DOB 1985-03-15, SSN last four 4472. What's my claim's status?"
    llm.queue_structured({"full_name": "Margaret Chen", "intents": ["status_inquiry"]})
    first = await agent.handle(state, message)
    assert kinds(first) == [K.VERIFIED_OK, K.ASK_DISAMBIGUATION]

    result = await say(agent, llm, state, "never mind, that's all", {"user_done": True})
    assert kinds(result) == [K.GOODBYE] and result.phase == Phase.COMPLETE
    assert outbox.sent() == []
