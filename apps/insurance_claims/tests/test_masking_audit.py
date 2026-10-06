import json

from agent.audit import scrub
from agent.masking import (
    mask_dob,
    mask_email,
    mask_id_last4,
    mask_name,
    mask_phone,
    mask_policy,
    mask_value,
)
from agent.state import State


def test_individual_masks():
    assert mask_id_last4("4472") == "****"
    assert mask_dob("1985-03-15") == "****-**-**"
    assert mask_phone("+16505212836") == "***-***-2836"
    assert mask_email("margaret@email.com") == "m***@email.com"
    assert mask_name("Margaret Chen") == "M*** C***"
    assert mask_policy("POL-9921") == "POL-****"


def test_mask_value_dispatch_and_unknown_key():
    assert mask_value("full_name", "Ma Tian") == "M*** T***"
    assert mask_value("something_else", "secret") == "***"


def test_scrub_masks_nested_and_listed_pii():
    out = scrub(
        {
            "full_name": "Margaret Chen",
            "nested": {"phone": "+16505212836"},
            "emails": [{"email": "margaret@email.com"}],
            "matched_factor_count": 3,
        }
    )
    assert out["full_name"] == "M*** C***"
    assert out["nested"]["phone"] == "***-***-2836"
    assert out["emails"][0]["email"] == "m***@email.com"
    assert out["matched_factor_count"] == 3


def test_audit_events_never_store_raw_pii():
    state = State(session_id="s1")
    state.record(
        "PII_CAPTURED",
        full_name="Margaret Chen",
        dob="1985-03-15",
        id_last4="4472",
        phone="+16505212836",
        email="margaret@email.com",
        policy_number="POL-9921",
    )
    dumped = json.dumps([e.model_dump() for e in state.events])
    for secret in ("Margaret", "1985-03-15", "4472", "6505212836", "margaret@", "9921"):
        assert secret not in dumped
