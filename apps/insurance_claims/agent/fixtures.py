"""Typed, read-only access to the synthetic backend fixtures.

This layer holds data only; business rules live elsewhere. It is deliberately generic:
nothing is hardcoded to the sample customers, unknown fields are ignored, and optional
files may be absent, because evaluators may swap in different fixtures.

Callers in the SOP code must reach claim data through the tool gateway, never directly.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Localized = dict[str, str]


class FixtureError(RuntimeError):
    """A fixture file is missing, unreadable or malformed."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Policyholder(_Model):
    party_id: str
    name: str
    policy_number: str | None = None
    dob: str | None = None
    id_type: str | None = None  # e.g. "ssn_last4" or "national_id_last4"
    id_last4: str | None = None
    phone: str | None = None
    email: str | None = None
    name_aliases: list[str] = []
    phone_aliases: list[str] = []
    email_aliases: list[str] = []


class Case(_Model):
    case_id: str
    party_id: str
    case_type: str
    status: str
    created_at: date | None = None
    summary: str | None = None
    denial_reason: str | None = None
    documents_needed: list[str] = []
    appeal_deadline: date | None = None
    expected_reimbursement_amount: Decimal | None = None
    allowed_max_amount: Decimal | None = None
    net_pay: Decimal | None = None
    net_fee: Decimal | None = None


class Representative(_Model):
    rep_name: str
    relationship: str | None = None
    buyer_name: str | None = None
    buyer_party_id: str


class ConsentScenario(_Model):
    status_sequence: list[str]


class FieldDescription(_Model):
    type: str | None = None
    example: str | None = None
    description: str | None = None


class ClaimSchema(_Model):
    notes: list[str] = []
    field_descriptions: dict[str, FieldDescription] = {}


class FollowupRule(_Model):
    topic: str
    intent_hints: list[str] = []
    requires_documents: bool = False
    match_any: list[str] = []
    text: str = Field(alias="en")  # template, e.g. "For claim {case_id}, ..."


class Guidelines(_Model):
    default_guidance: Localized = {}
    case_type_guidance: dict[str, Localized] = {}
    document_guidance: dict[str, Localized] = {}
    document_alternative_guidance: dict[str, Localized] = {}
    claim_followup_settings: dict[str, Localized] = {}
    claim_followup_guidance: list[FollowupRule] = []
    claim_followup_fallback: Localized = {}


def localized(entry: Localized | None, lang: str = "en") -> str | None:
    """Pick one language out of a {"en": "..."} entry."""
    if not entry:
        return None
    return entry.get(lang) or next(iter(entry.values()), None)


def policy_key(value: str) -> str:
    """Canonical form for comparing policy numbers: 'pol 9921' == 'POL-9921'."""
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


class FixtureStore:
    def __init__(
        self,
        parties: list[Policyholder],
        cases: list[Case],
        representatives: list[Representative] | None = None,
        consent_scenarios: dict[str, ConsentScenario] | None = None,
        guidelines: Guidelines | None = None,
        claim_schema: ClaimSchema | None = None,
    ) -> None:
        self._parties = list(parties)
        self._cases = list(cases)
        self._representatives = list(representatives or [])
        self._consent_scenarios = dict(consent_scenarios or {})
        self.guidelines = guidelines or Guidelines()
        self.claim_schema = claim_schema or ClaimSchema()

        self._by_id: dict[str, Policyholder] = {}
        self._by_policy: dict[str, Policyholder] = {}
        for party in self._parties:
            if party.party_id in self._by_id:
                raise FixtureError(f"duplicate party_id in policyholders: {party.party_id}")
            self._by_id[party.party_id] = party
            if party.policy_number:
                self._by_policy[policy_key(party.policy_number)] = party

        self._case_by_id: dict[str, Case] = {}
        for case in self._cases:
            if case.case_id in self._case_by_id:
                raise FixtureError(f"duplicate case_id in claims: {case.case_id}")
            self._case_by_id[case.case_id] = case

    # ---- loading -----------------------------------------------------------------

    @classmethod
    def load(cls, directory: Path | str) -> FixtureStore:
        base = Path(directory)
        if not base.is_dir():
            raise FixtureError(f"fixtures directory not found: {base}")

        parties = _parse_list(base / "policyholders.json", Policyholder, required=True)
        cases = _parse_list(base / "claims.json", Case, required=True)
        reps = _parse_list(base / "representatives.json", Representative, required=False)

        consent: dict[str, ConsentScenario] = {}
        raw_consent = _read_json(base / "consent_scenarios.json", required=False)
        if raw_consent is not None:
            consent = _validate(
                base / "consent_scenarios.json",
                lambda: {k: ConsentScenario.model_validate(v) for k, v in raw_consent.items()},
            )

        guidelines = None
        raw_guidelines = _read_json(base / "required_document_guideline.json", required=False)
        if raw_guidelines is not None:
            guidelines = _validate(
                base / "required_document_guideline.json",
                lambda: Guidelines.model_validate(raw_guidelines),
            )

        claim_schema = None
        raw_schema = _read_json(base / "claim_schema.json", required=False)
        if raw_schema is not None:
            claim_schema = _validate(
                base / "claim_schema.json", lambda: ClaimSchema.model_validate(raw_schema)
            )

        return cls(parties, cases, reps, consent, guidelines, claim_schema)

    # ---- policyholders -----------------------------------------------------------

    def parties(self) -> list[Policyholder]:
        return list(self._parties)

    def get_party(self, party_id: str) -> Policyholder | None:
        return self._by_id.get(party_id)

    def find_party_by_policy(self, policy_number: str) -> Policyholder | None:
        return self._by_policy.get(policy_key(policy_number))

    # ---- cases -------------------------------------------------------------------

    def cases_for_party(self, party_id: str) -> list[Case]:
        return [c for c in self._cases if c.party_id == party_id]

    def get_case(self, case_id: str) -> Case | None:
        return self._case_by_id.get(case_id)

    # ---- representatives and consent ---------------------------------------------

    def representatives_for_party(self, party_id: str) -> list[Representative]:
        return [r for r in self._representatives if r.buyer_party_id == party_id]

    def has_consent_scenario(self, name: str) -> bool:
        return name in self._consent_scenarios

    def consent_sequence(self, name: str) -> list[str]:
        scenario = self._consent_scenarios.get(name)
        if scenario is None:
            known = ", ".join(sorted(self._consent_scenarios)) or "none"
            raise FixtureError(f"unknown consent scenario {name!r} (available: {known})")
        return list(scenario.status_sequence)


def _read_json(path: Path, *, required: bool) -> Any:
    if not path.is_file():
        if required:
            raise FixtureError(f"missing required fixture file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"{path.name} is not valid JSON: {exc}") from exc


def _validate(path: Path, build):
    try:
        return build()
    except ValidationError as exc:
        raise FixtureError(f"{path.name} has an unexpected shape: {exc}") from exc


def _parse_list(path: Path, model: type[BaseModel], *, required: bool) -> list:
    raw = _read_json(path, required=required)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FixtureError(f"{path.name} must contain a JSON list")
    return _validate(path, lambda: [model.model_validate(item) for item in raw])
