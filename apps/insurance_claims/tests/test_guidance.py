import pytest
from agent.guidance import (
    alternative_guidance,
    document_guidance,
    fill_template,
    match_document_key,
    match_followups,
)

DOC_KEYS = [
    "supplemental accident scene photos",
    "repair estimate",
    "original pathology report",
    "treating provider office note",
]


# ---- matching a claim's document name to a guideline key --------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ("pathology report", "original pathology report"),
        ("Pathology Report", "original pathology report"),
        ("office note", "treating provider office note"),
        ("repair estimate", "repair estimate"),
        ("accident photos", "supplemental accident scene photos"),
        ("diagnosis report", None),
        ("", None),
        ("insurance card", None),
    ],
)
def test_document_names_match_guideline_keys(doc, expected):
    assert match_document_key(doc, DOC_KEYS) == expected


def test_a_tie_between_two_keys_is_no_match():
    keys = ["alpha beta report", "gamma beta report"]
    assert match_document_key("beta report", keys) is None


def test_the_closer_key_wins_over_a_longer_one():
    keys = ["pathology report", "original pathology report from lab"]
    assert match_document_key("pathology report", keys) == "pathology report"


def test_a_more_generic_key_still_matches_a_more_specific_document():
    assert match_document_key("original pathology report from the lab", ["pathology report"]) == (
        "pathology report"
    )


# ---- the fallback chain: document, then claim type, then default ----------------------------


def test_a_document_with_its_own_guidance_uses_it(store):
    guidance = document_guidance("pathology report", "healthcare", store.guidelines)
    assert guidance.level == "document" and guidance.key == "original pathology report"
    assert "specimen details" in guidance.text


def test_a_document_without_guidance_falls_back_to_its_claim_type(store):
    guidance = document_guidance("diagnosis report", "healthcare", store.guidelines)
    assert guidance.level == "case_type" and guidance.key == "healthcare"
    assert "treating provider or facility name" in guidance.text


def test_claim_type_matching_ignores_case(store):
    guidance = document_guidance("diagnosis report", "Healthcare", store.guidelines)
    assert guidance.level == "case_type"


def test_with_no_claim_type_guidance_the_default_is_used(store):
    guidance = document_guidance("diagnosis report", "dental", store.guidelines)
    assert guidance.level == "default" and guidance.key is None
    assert "member portal" in guidance.text
    assert document_guidance("diagnosis report", None, store.guidelines).level == "default"


def test_alternatives_use_the_documents_own_advice_or_the_default(store):
    own = alternative_guidance("pathology report", store.guidelines)
    assert own.level == "document" and own.key == "original pathology report"
    assert "replacement copy" in own.text
    default = alternative_guidance("diagnosis report", store.guidelines)
    assert default.level == "default" and "replacement copy" in default.text


# ---- follow-up rules ---------------------------------------------------------------------


def topics_of(matches):
    return [m.rule.topic for m in matches]


@pytest.fixture
def rules(store):
    return store.guidelines.claim_followup_guidance


def test_the_most_specific_phrase_wins_an_overlap(rules):
    question = "How soon do I need to submit the pathology report?"
    matches = match_followups(rules, question, intents=["document_submission"], has_documents=True)
    assert topics_of(matches) == ["submission_timing"]
    assert matches[0].via == "phrase" and matches[0].phrase == "how soon do i need to submit"


def test_two_independent_topics_in_one_question_are_both_selected(rules):
    question = "Where do I submit the pathology report, and how long will it take once I send it?"
    matches = match_followups(rules, question, intents=["document_submission"], has_documents=True)
    assert topics_of(matches) == ["submission_method", "processing_time_after_submission"]


def test_a_topic_the_phrases_miss_can_come_from_the_llm(rules):
    question = "Where do I upload the pathology report, and how long will it take once I send it?"
    matches = match_followups(
        rules,
        question,
        intents=["document_submission"],
        topics=["submission_method", "processing_time_after_submission"],
        has_documents=True,
    )
    assert topics_of(matches) == ["processing_time_after_submission", "submission_method"]
    assert [m.via for m in matches] == ["phrase", "semantic"]


def test_a_topic_beaten_by_a_longer_phrase_is_not_revived_by_the_llm(rules):
    question = "How soon do I need to submit it?"
    matches = match_followups(
        rules,
        question,
        intents=["document_submission"],
        topics=["processing_time_after_submission"],
        has_documents=True,
    )
    assert topics_of(matches) == ["submission_timing"]


def test_each_topic_appears_once_however_it_is_found(rules):
    matches = match_followups(
        rules,
        "How long does it take? Also, how long until it is reviewed?",
        topics=["processing_time_after_submission", "processing_time_after_submission"],
        has_documents=True,
    )
    assert topics_of(matches) == ["processing_time_after_submission"]


def test_document_rules_need_a_claim_with_requested_documents(rules):
    matches = match_followups(rules, "How long does it take?", has_documents=False)
    assert matches == []


def test_the_callers_intent_must_allow_the_rule(rules):
    question = "How long does it take?"
    assert match_followups(rules, question, intents=["denial_question"], has_documents=True) == []
    assert topics_of(
        match_followups(rules, question, intents=["next_steps"], has_documents=True)
    ) == ["processing_time_after_submission"]


def test_with_no_known_intent_the_phrase_alone_is_enough(rules):
    matches = match_followups(rules, "How long does it take?", intents=[], has_documents=True)
    assert topics_of(matches) == ["processing_time_after_submission"]


def test_unknown_llm_topics_are_ignored(rules):
    matches = match_followups(rules, "hello", topics=["made_up"], has_documents=True)
    assert matches == []


def test_matching_ignores_case_and_punctuation(rules):
    matches = match_followups(rules, "HOW LONG?!", has_documents=True)
    assert topics_of(matches) == ["processing_time_after_submission"]


def test_a_rule_without_phrases_is_reachable_only_through_the_llm(rules):
    assert match_followups(rules, "I can't find it anywhere", has_documents=True) == []
    matches = match_followups(
        rules,
        "I can't find it anywhere",
        topics=["missing_required_material_alternatives"],
        has_documents=True,
    )
    assert topics_of(matches) == ["missing_required_material_alternatives"]
    assert matches[0].via == "semantic"


def test_a_phrase_inside_a_longer_word_does_not_match(rules):
    assert match_followups(rules, "that was nonportalish", has_documents=True) == []


# ---- templates ---------------------------------------------------------------------------


def test_templates_are_filled_from_the_given_values(rules):
    timing = next(r for r in rules if r.topic == "submission_timing")
    text = fill_template(
        timing.text, {"case_id": "CL-2048", "documents": "pathology report and office note"}
    )
    assert text == (
        "For claim CL-2048, please submit pathology report and office note within a week."
    )


def test_a_placeholder_without_a_value_stays_visible_rather_than_being_guessed():
    assert fill_template("Claim {case_id} takes {duration}.", {"case_id": "CL-1"}) == (
        "Claim CL-1 takes {duration}."
    )


def test_malformed_templates_are_returned_unchanged():
    assert fill_template("broken {", {}) == "broken {"
