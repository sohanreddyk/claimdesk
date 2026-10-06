"""Output guard: the last line of defense on every reply, run in code after the LLM has spoken.

The LLM is never given claim data before verification and never given on-file PII, so these
checks should never fire. They exist because "should never" is not a guarantee: if one ever
does fire, the reply is replaced with deterministic wording and the event is audited.

Checks:
- before verification, no claim detail (case numbers, denial reasons, summaries, document
  names, amounts) may appear in a reply;
- at any time, no ID last-four, date of birth, phone number or email address belonging to the
  caller (as typed) or to the matched account (on file) may be repeated back.
"""

from __future__ import annotations

import re

from .fixtures import FixtureStore
from .normalize import normalize_dob, normalize_email, normalize_id_last4, normalize_phone
from .state import State

CLAIM_LEAK = "claim_data_before_verification"
PII_ECHO = "pii_echo"


def _claim_strings(store: FixtureStore) -> set[str]:
    strings: set[str] = set()
    for case in store.all_cases():
        strings.add(case.case_id)
        for text in (case.summary, case.denial_reason):
            if text and len(text) >= 10:
                strings.add(text)
        strings.update(doc for doc in case.documents_needed if len(doc) >= 6)
        for amount in (
            case.expected_reimbursement_amount,
            case.allowed_max_amount,
            case.net_pay,
            case.net_fee,
        ):
            if amount is not None and amount >= 100:
                strings.update({f"{amount:.2f}", f"{amount:,.2f}"})
    return {s.casefold() for s in strings}


def _pii_values(state: State, store: FixtureStore) -> dict[str, set[str]]:
    """Canonical PII values to keep out of replies: what the caller typed and what is on file
    for the account they are being matched to."""
    values: dict[str, set[str]] = {"id": set(), "dob": set(), "phone": set(), "email": set()}

    def add(id_value: str | None, dob: str | None, phone: str | None, email: str | None) -> None:
        if id_value and (id4 := normalize_id_last4(id_value)):
            values["id"].add(id4)
        if dob and (iso := normalize_dob(dob)):
            values["dob"].add(iso)
        if phone and (digits := normalize_phone(phone)):
            values["phone"].add(digits)
        if email and (mail := normalize_email(email)):
            values["email"].add(mail)

    f = state.factors
    add(f.get("id_last4"), f.get("dob"), f.get("phone"), f.get("email"))
    party = store.get_party(state.verified_party_id or state.candidate_party_id or "")
    if party is not None:
        add(party.id_last4, party.dob, party.phone, party.email)
    return values


def find_violations(text: str, state: State, store: FixtureStore) -> list[str]:
    low = text.casefold()
    violations: list[str] = []

    if not state.verified and any(s in low for s in _claim_strings(store)):
        violations.append(CLAIM_LEAK)

    pii = _pii_values(state, store)
    digits_only = re.sub(r"\D", "", text)
    echoed = (
        any(re.search(rf"(?<!\d){re.escape(v)}(?!\d)", text) for v in pii["id"])
        or any(v in text for v in pii["dob"])
        or any(v in digits_only for v in pii["phone"])
        or any(v in low for v in pii["email"])
    )
    if echoed:
        violations.append(PII_ECHO)
    return violations
