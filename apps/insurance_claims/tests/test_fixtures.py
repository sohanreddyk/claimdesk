import json
from datetime import date
from decimal import Decimal

import pytest
from agent.fixtures import FixtureError, FixtureStore, localized, policy_key


def test_loads_starter_policyholders(store):
    assert [p.party_id for p in store.parties()] == ["P9", "P7", "P12", "P13"]


def test_id_types_differ_between_parties(store):
    assert store.get_party("P9").id_type == "ssn_last4"
    assert store.get_party("P12").id_type == "national_id_last4"
    assert store.get_party("P12").id_last4 == "6688"


def test_aliases_are_loaded(store):
    p13 = store.get_party("P13")
    assert p13.name_aliases == ["Yaven Li"]
    assert p13.email_aliases == ["yawen.li@example.com"]
    assert p13.phone_aliases == [p13.phone]  # duplicate alias in the fixture


def test_near_identical_phones_stay_distinct(store):
    assert store.get_party("P9").phone != store.get_party("P13").phone


def test_find_party_by_policy_normalizes(store):
    assert store.find_party_by_policy("POL-9921").party_id == "P9"
    assert store.find_party_by_policy("pol 9921").party_id == "P9"
    assert store.find_party_by_policy("POL-0000") is None
    assert policy_key("pol 9921") == "POL9921"


def test_cases_per_party(store):
    assert [c.case_id for c in store.cases_for_party("P9")] == [
        "CL-2048",
        "CL-2011",
        "CL-1899",
        "CL-2102",
    ]
    assert [c.case_id for c in store.cases_for_party("P12")] == ["CL-3001"]
    assert store.cases_for_party("P7") == []
    assert store.cases_for_party("P13") == []


def test_case_types_and_dates_are_parsed(store):
    denied = store.get_case("CL-2048")
    assert denied.created_at == date(2026, 1, 12)
    assert denied.appeal_deadline == date(2026, 3, 18)
    assert denied.documents_needed == ["pathology report", "office note"]
    assert denied.net_fee == Decimal("1450.00")


def test_only_denied_cases_have_denial_fields(store):
    closed = store.get_case("CL-2011")
    assert closed.status == "closed"
    assert closed.denial_reason is None
    assert closed.documents_needed == []
    assert closed.appeal_deadline is None


def test_open_case_amounts_follow_schema_semantics(store):
    open_case = store.get_case("CL-2102")
    assert open_case.net_pay == Decimal("0.00")
    assert open_case.expected_reimbursement_amount == Decimal("3200.00")


def test_representatives(store):
    reps = store.representatives_for_party("P9")
    assert [(r.rep_name, r.relationship) for r in reps] == [("David Chen", "son")]
    assert store.representatives_for_party("P12") == []


def test_consent_scenarios(store):
    assert store.consent_sequence("default") == ["pending", "approved"]
    assert store.consent_sequence("timeout") == ["pending"] * 5
    assert store.has_consent_scenario("default")
    with pytest.raises(FixtureError, match="unknown consent scenario"):
        store.consent_sequence("nope")


def test_guideline_topics_and_templates(store):
    rules = store.guidelines.claim_followup_guidance
    assert {r.topic for r in rules} == {
        "missing_required_material_alternatives",
        "submission_timing",
        "processing_time_after_submission",
        "submission_method",
        "file_format_requirements",
        "receipt_confirmation",
    }
    timing = next(r for r in rules if r.topic == "submission_timing")
    assert "{case_id}" in timing.text and "{documents}" in timing.text
    assert timing.requires_documents is True
    assert "how soon do i need to submit" in timing.match_any


def test_guideline_lookups(store):
    g = store.guidelines
    assert "original pathology report" in g.document_guidance
    assert "diagnosis report" not in g.document_guidance  # forces the fallback chain
    assert localized(g.claim_followup_settings["average_processing_time_after_submission"]) == (
        "usually less than a week"
    )
    assert localized(None) is None


def test_claim_schema_semantics(store):
    fields = store.claim_schema.field_descriptions
    assert set(fields) == {
        "expected_reimbursement_amount",
        "allowed_max_amount",
        "net_pay",
        "net_fee",
    }
    assert "finalized amount" in fields["net_pay"].description


# ---- resilience to swapped fixtures ----------------------------------------------


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_optional_files_and_unknown_fields_are_tolerated(tmp_path):
    _write(
        tmp_path / "policyholders.json",
        [{"party_id": "X1", "name": "Test Person", "future_field": "ignored"}],
    )
    _write(
        tmp_path / "claims.json",
        [{"case_id": "C1", "party_id": "X1", "case_type": "auto", "status": "open"}],
    )
    store = FixtureStore.load(tmp_path)
    assert store.get_party("X1").name == "Test Person"
    assert store.cases_for_party("X1")[0].created_at is None
    assert store.representatives_for_party("X1") == []
    assert store.guidelines.claim_followup_guidance == []


def test_missing_required_file_is_a_clear_error(tmp_path):
    _write(tmp_path / "claims.json", [])
    with pytest.raises(FixtureError, match="policyholders.json"):
        FixtureStore.load(tmp_path)


def test_missing_directory_is_a_clear_error(tmp_path):
    with pytest.raises(FixtureError, match="not found"):
        FixtureStore.load(tmp_path / "nope")


def test_invalid_json_is_a_clear_error(tmp_path):
    (tmp_path / "policyholders.json").write_text("{not json", encoding="utf-8")
    _write(tmp_path / "claims.json", [])
    with pytest.raises(FixtureError, match="not valid JSON"):
        FixtureStore.load(tmp_path)


def test_duplicate_party_ids_are_rejected(tmp_path):
    _write(
        tmp_path / "policyholders.json",
        [{"party_id": "A", "name": "One"}, {"party_id": "A", "name": "Two"}],
    )
    _write(tmp_path / "claims.json", [])
    with pytest.raises(FixtureError, match="duplicate party_id"):
        FixtureStore.load(tmp_path)
