import re
from datetime import date

import pytest
from agent.clock import FixedClock
from agent.state import CaseRecord
from agent.summary import SUBJECT, build_summary, has_content

TODAY = FixedClock(date(2026, 3, 5))


def denied(**overrides) -> CaseRecord:
    fields = {
        "case_id": "CL-2048",
        "case_type": "healthcare",
        "status_outcome": "denied",
        "topics_discussed": ["why the claim was denied", "document requirements and submission"],
        "documents_needed": ["pathology report", "office note"],
        "appeal_deadline": date(2026, 3, 18),
    }
    fields.update(overrides)
    return CaseRecord(**fields)


# ---- what the email says ---------------------------------------------------------------------


def test_a_denied_claim_summary_has_status_topics_and_next_steps():
    summary = build_summary([denied()], first_name="Margaret", clock=TODAY)
    assert summary.subject == SUBJECT
    assert summary.claim_ids == ("CL-2048",)
    assert summary.body == "\n".join(
        [
            "Hello Margaret,",
            "",
            "Here is a summary of today's conversation about your claim.",
            "",
            "Claim CL-2048 (healthcare)",
            "Status: denied",
            "What we discussed:",
            "- why the claim was denied",
            "- document requirements and submission",
            "Next steps:",
            "- Submit the requested documents: pathology report and office note.",
            "- The appeal deadline on file is March 18, 2026 (13 days remaining as of today).",
            "",
            "This summary reflects the information on file. It is not a decision on coverage.",
            "",
            "Thank you,",
            "Claims Support",
        ]
    )


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 3, 17), "(1 day remaining as of today)"),
        (date(2026, 3, 18), "which is today."),
        (date(2026, 3, 19), "and it has passed."),
    ],
)
def test_the_deadline_wording_follows_the_clock(today, expected):
    summary = build_summary([denied()], first_name=None, clock=FixedClock(today))
    assert expected in summary.body


def test_days_remaining_are_counted_when_the_email_is_built_not_when_it_was_discussed():
    early = build_summary([denied()], first_name=None, clock=FixedClock(date(2026, 3, 5)))
    later = build_summary([denied()], first_name=None, clock=FixedClock(date(2026, 3, 10)))
    assert "13 days remaining" in early.body and "8 days remaining" in later.body


def test_a_claim_with_nothing_pending_says_so_instead_of_inventing_steps():
    closed = CaseRecord(
        case_id="CL-2011",
        case_type="healthcare",
        status_outcome="closed",
        topics_discussed=["claim status"],
    )
    body = build_summary([closed], first_name="Margaret", clock=TODAY).body
    assert "Status: closed" in body
    assert "Next steps:\n- None are on file for this claim." in body


def test_a_claim_with_no_recorded_topic_still_gets_a_sensible_line():
    body = build_summary([denied(topics_discussed=[])], first_name=None, clock=TODAY).body
    assert "What we discussed:\n- a general overview of the claim" in body


def test_missing_documents_and_the_human_review_option_are_mentioned_when_they_apply():
    record = denied(unavailable_documents=["pathology report"], human_review_offered=True)
    body = build_summary([record], first_name=None, clock=TODAY).body
    assert "- You mentioned you could not get: pathology report." in body
    review = "- A human claims representative can review the file with you for manual options."
    assert review in body
    plain = build_summary([denied()], first_name=None, clock=TODAY).body
    assert "could not get" not in plain and "human claims representative" not in plain


def test_three_documents_are_listed_naturally():
    record = denied(documents_needed=["a report", "a note", "a photo"])
    body = build_summary([record], first_name=None, clock=TODAY).body
    assert "Submit the requested documents: a report, a note and a photo." in body


# ---- several claims ------------------------------------------------------------------------------


def test_each_claim_discussed_gets_its_own_section_in_order():
    first = denied()
    second = CaseRecord(
        case_id="CL-1899",
        case_type="dental",
        status_outcome="closed",
        topics_discussed=["claim status"],
    )
    summary = build_summary([first, second], first_name="Margaret", clock=TODAY)
    assert summary.claim_ids == ("CL-2048", "CL-1899")
    assert "about your claims." in summary.body
    assert summary.body.index("Claim CL-2048") < summary.body.index("Claim CL-1899")
    assert "Claim CL-1899 (dental)\nStatus: closed" in summary.body


def test_a_claim_the_caller_left_and_came_back_to_appears_once_with_everything_combined():
    earlier = denied(topics_discussed=["why the claim was denied"])
    later = denied(
        topics_discussed=["why the claim was denied", "next steps"],
        unavailable_documents=["office note"],
    )
    summary = build_summary([earlier, later], first_name=None, clock=TODAY)
    assert summary.claim_ids == ("CL-2048",)
    assert summary.body.count("Claim CL-2048") == 1
    assert summary.body.count("- why the claim was denied") == 1
    assert "- next steps" in summary.body and "could not get: office note" in summary.body


def test_building_a_summary_does_not_change_the_records_it_was_given():
    earlier = denied(topics_discussed=["why the claim was denied"])
    later = denied(topics_discussed=["next steps"])
    build_summary([earlier, later], first_name=None, clock=TODAY)
    assert earlier.topics_discussed == ["why the claim was denied"]
    assert later.topics_discussed == ["next steps"]


# ---- when there is nothing to summarize ---------------------------------------------


def test_records_without_a_claim_are_skipped_and_an_empty_set_is_refused():
    assert has_content([denied()]) is True
    assert has_content([CaseRecord()]) is False
    assert has_content([]) is False
    with pytest.raises(ValueError, match="nothing to summarize"):
        build_summary([CaseRecord()], first_name=None, clock=TODAY)


def test_empty_records_mixed_in_do_not_add_sections():
    summary = build_summary([CaseRecord(), denied()], first_name=None, clock=TODAY)
    assert summary.claim_ids == ("CL-2048",)


# ---- tone and safety ----------------------------------------------------------------


def test_the_greeting_adapts_to_whether_a_name_is_known():
    assert build_summary([denied()], first_name=None, clock=TODAY).body.startswith("Hello,\n")
    named = build_summary([denied()], first_name="Margaret", clock=TODAY).body
    assert named.startswith("Hello Margaret,\n")


def test_the_body_is_plain_text_with_no_addresses_or_phone_like_numbers():
    body = build_summary([denied()], first_name="Margaret", clock=TODAY).body
    assert "@" not in body and "<" not in body and "**" not in body
    assert not re.search(r"\d{9,}", body)
