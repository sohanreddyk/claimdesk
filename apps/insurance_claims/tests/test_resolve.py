from agent.resolve import case_option, has_hints, resolve_case
from agent.state import CaseHints


def ids(resolution):
    return [c.case_id for c in resolution.options]


def test_all_three_hints_pick_the_one_denied_january_healthcare_claim(store):
    hints = CaseHints(case_type="healthcare", status="denied", month=1)
    res = resolve_case(store.cases_for_party("P9"), hints)
    assert res.kind == "unique" and res.case.case_id == "CL-2048"


def test_month_and_type_alone_are_ambiguous_across_years(store):
    hints = CaseHints(case_type="healthcare", month=1)
    res = resolve_case(store.cases_for_party("P9"), hints)
    assert res.kind == "ambiguous" and res.case is None
    assert ids(res) == ["CL-2048", "CL-2011"]  # January 2026 first, then January 2025


def test_a_denial_question_breaks_the_tie_toward_the_only_denied_claim(store):
    hints = CaseHints(case_type="healthcare", month=1)
    res = resolve_case(store.cases_for_party("P9"), hints, intent="denial_question")
    assert res.kind == "unique" and res.case.case_id == "CL-2048"


def test_other_intents_do_not_break_the_tie(store):
    hints = CaseHints(case_type="healthcare", month=1)
    res = resolve_case(store.cases_for_party("P9"), hints, intent="status_inquiry")
    assert res.kind == "ambiguous"


def test_no_hints_and_several_claims_lists_them_newest_first(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints())
    assert res.kind == "ambiguous"
    assert ids(res) == ["CL-2102", "CL-2048", "CL-1899", "CL-2011"]


def test_no_hints_but_a_denial_question_picks_the_only_denied_claim(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints(), intent="denial_question")
    assert res.kind == "unique" and res.case.case_id == "CL-2048"


def test_status_alone_can_be_enough(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints(status="denied"))
    assert res.kind == "unique" and res.case.case_id == "CL-2048"


def test_claim_type_alone_can_be_enough(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints(case_type="dental"))
    assert res.kind == "unique" and res.case.case_id == "CL-1899"


def test_year_separates_claims_from_the_same_month(store):
    hints = CaseHints(case_type="healthcare", month=1, year=2025)
    res = resolve_case(store.cases_for_party("P9"), hints)
    assert res.kind == "unique" and res.case.case_id == "CL-2011"


def test_a_claim_number_is_matched_case_insensitively(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints(case_id="cl-2102"))
    assert res.kind == "unique" and res.case.case_id == "CL-2102"


def test_hints_that_match_nothing_list_everything_on_file(store):
    res = resolve_case(store.cases_for_party("P9"), CaseHints(case_type="auto", status="denied"))
    assert res.kind == "no_match" and res.case is None
    assert len(res.options) == 4


def test_a_party_with_one_claim_resolves_without_hints(store):
    res = resolve_case(store.cases_for_party("P12"), CaseHints())
    assert res.kind == "unique" and res.case.case_id == "CL-3001"


def test_a_party_with_no_claims(store):
    for party in ("P7", "P13"):
        res = resolve_case(store.cases_for_party(party), CaseHints(status="denied"))
        assert res.kind == "no_claims" and res.options == ()


def test_only_the_cases_it_is_given_are_considered(store):
    """Margaret's hints against Ma Tian's list: her January claim is not in it."""
    hints = CaseHints(case_type="healthcare", status="denied", month=1)
    res = resolve_case(store.cases_for_party("P12"), hints)
    assert res.kind == "no_match"
    assert ids(res) == ["CL-3001"]


def test_has_hints():
    assert not has_hints(CaseHints())
    assert has_hints(CaseHints(month=1))
    assert has_hints(CaseHints(case_id="CL-1"))


def test_case_option_is_plain_and_pii_free(store):
    assert case_option(store.get_case("CL-2048")) == {
        "case_id": "CL-2048",
        "case_type": "healthcare",
        "created_at": "2026-01-12",
        "status": "denied",
    }
