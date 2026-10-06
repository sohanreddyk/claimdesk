"""Identity verification. Pure, deterministic code; the LLM never decides who is verified.

Rules (see docs/ARCHITECTURE.md section 7):
- Need `min_factors` (3) matching factors of the SAME party record, from: full_name, dob,
  phone, email, id_last4. The policy number picks a candidate but never counts.
- Matching is exact after normalization, against the primary value or any alias.
- Callers are only ever told which factors they have *provided*, never which *matched*.
- Only supplied values that fail to match count as mismatches (partial answers are not
  failures). At `max_mismatches` automated verification stops and a human is offered.
- A caller whose name matches a registered representative of the candidate party is treated
  as a representative, and cannot verify as the policyholder. Representatives additionally
  need an authorized rep record and approved consent from the policyholder, and consent is
  requested only after three factors match so attackers cannot spam approval prompts.
- Verification never reads claim data.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .config import Settings
from .consent import ConsentGateway
from .fixtures import FixtureStore, Policyholder
from .normalize import name_key, normalize_factor
from .state import FACTOR_NAMES, ConsentState, State

ID_KIND_TO_TYPE = {"ssn": "ssn_last4", "national_id": "national_id_last4"}


class VerifyStatus(StrEnum):
    VERIFIED = "verified"
    NEED_MORE = "need_more"  # nothing wrong so far, fewer than the required factors
    MISMATCH = "mismatch"  # a supplied value did not match; still below the threshold
    LOCKED = "locked"  # too many mismatches; automated verification has stopped
    NEED_REP_IDENTITY = "need_rep_identity"  # representative, but no name given yet
    REP_NOT_AUTHORIZED = "rep_not_authorized"
    CONSENT_TIMED_OUT = "consent_timed_out"
    CONSENT_DENIED = "consent_denied"


@dataclass(frozen=True)
class VerifyResult:
    """What the rest of the system may know. Deliberately has no matched-factor detail."""

    status: VerifyStatus
    provided: tuple[str, ...]  # factors the caller has given in a usable form
    missing: tuple[str, ...]  # accepted factors not yet given (and not refused)
    new_mismatches: int = 0


# ---- factor matching ---------------------------------------------------------------


def supplied_keys(factors: Mapping[str, str]) -> dict[str, str]:
    """Canonical keys of the usable captured factors. Unusable values are 'not provided'."""
    out: dict[str, str] = {}
    for name in FACTOR_NAMES:
        raw = factors.get(name)
        if raw:
            key = normalize_factor(name, raw)
            if key is not None:
                out[name] = key
    return out


def party_keys(party: Policyholder, factor: str) -> set[str]:
    """Every acceptable canonical value for a factor, including aliases."""
    raw: list[str | None]
    if factor == "full_name":
        raw = [party.name, *party.name_aliases]
    elif factor == "dob":
        raw = [party.dob]
    elif factor == "phone":
        raw = [party.phone, *party.phone_aliases]
    elif factor == "email":
        raw = [party.email, *party.email_aliases]
    else:  # id_last4
        raw = [party.id_last4]
    keys: set[str] = set()
    for value in raw:
        if value:
            key = normalize_factor(factor, value)
            if key is not None:
                keys.add(key)
    return keys


def _id_kind_conflicts(party: Policyholder, hint: str | None) -> bool:
    """True when the caller explicitly named an ID type that differs from the stored one."""
    expected = ID_KIND_TO_TYPE.get(hint or "")
    return expected is not None and party.id_type is not None and party.id_type != expected


def match_party(
    party: Policyholder, supplied: Mapping[str, str], id_kind_hint: str | None
) -> tuple[set[str], set[str]]:
    """Split supplied factors into (matched, mismatched) for one party."""
    matched: set[str] = set()
    mismatched: set[str] = set()
    for factor, key in supplied.items():
        ok = key in party_keys(party, factor)
        if ok and factor == "id_last4" and _id_kind_conflicts(party, id_kind_hint):
            ok = False
        (matched if ok else mismatched).add(factor)
    return matched, mismatched


def _select_candidate(
    store: FixtureStore, state: State, supplied: Mapping[str, str]
) -> Policyholder | None:
    """A resolvable policy number binds the candidate. Otherwise the party matching the most
    supplied factors wins, with fixture order breaking ties deterministically."""
    if state.policy_number:
        bound = store.find_party_by_policy(state.policy_number)
        if bound is not None:
            return bound
    best: Policyholder | None = None
    best_count = 0
    for party in store.parties():
        count = len(match_party(party, supplied, state.id_kind_hint)[0])
        if count > best_count:
            best, best_count = party, count
    return best


# ---- representatives ---------------------------------------------------------------


def _detect_representative(
    state: State, store: FixtureStore, candidate: Policyholder, supplied: Mapping[str, str]
) -> bool:
    """If the stated name is a registered representative of the candidate (and not the
    candidate's own name), the caller is a representative: the name is moved out of the
    account-holder factors so it cannot count toward, or against, the policyholder."""
    key = supplied.get("full_name")
    if key is None or key in party_keys(candidate, "full_name"):
        return False
    for rep in store.representatives_for_party(candidate.party_id):
        if name_key(rep.rep_name) == key:
            state.caller_role = "representative"
            state.rep_name = state.factors.pop("full_name")
            state.record("REPRESENTATIVE_DETECTED", reason="name_matches_rep_record")
            return True
    return False


def _rep_authorized(store: FixtureStore, party_id: str, rep_name: str) -> bool:
    key = name_key(rep_name)
    if key is None:
        return False
    return any(name_key(r.rep_name) == key for r in store.representatives_for_party(party_id))


def _ensure_consent(
    state: State, party_id: str, consent: ConsentGateway
) -> None:
    """Request policyholder approval once per party. Never re-requested after a result."""
    if state.consent_party_id != party_id:
        state.consent = ConsentState.NOT_REQUESTED
        state.consent_trail = []
        state.consent_party_id = None
    if state.consent != ConsentState.NOT_REQUESTED:
        return
    state.consent_party_id = party_id
    state.consent = ConsentState.PENDING
    state.record("CONSENT_REQUESTED", party_id=party_id, scenario=consent.scenario)
    outcome = consent.run(party_id)
    state.consent = outcome.state
    state.consent_trail = list(outcome.trail)
    state.record("CONSENT_RESULT", status=outcome.state.value, polls=len(outcome.trail))


# ---- orchestration -----------------------------------------------------------------


def _count_new_mismatches(
    state: State, supplied: Mapping[str, str], mismatched: set[str]
) -> int:
    """Count each distinct wrong value once, however many turns it stays in the state."""
    new = 0
    for factor in sorted(mismatched):
        token = hashlib.sha256(f"{factor}:{supplied[factor]}".encode()).hexdigest()[:16]
        if token not in state.counted_mismatches:
            state.counted_mismatches.add(token)
            new += 1
    state.mismatch_count += new
    return new


def _result(status: VerifyStatus, state: State, new_mismatches: int = 0) -> VerifyResult:
    supplied = supplied_keys(state.factors)
    provided = tuple(name for name in FACTOR_NAMES if name in supplied)
    missing = tuple(
        name for name in FACTOR_NAMES if name not in supplied and name not in state.refused_fields
    )
    return VerifyResult(status, provided, missing, new_mismatches)


def verify_identity(
    state: State, store: FixtureStore, settings: Settings, consent: ConsentGateway
) -> VerifyResult:
    """Evaluate the captured factors. Safe to call every turn; it is idempotent."""
    if state.verified:
        return _result(VerifyStatus.VERIFIED, state)
    if state.mismatch_count >= settings.max_mismatches:
        return _result(VerifyStatus.LOCKED, state)

    supplied = supplied_keys(state.factors)
    candidate = _select_candidate(store, state, supplied)
    if candidate is not None and _detect_representative(state, store, candidate, supplied):
        supplied = supplied_keys(state.factors)

    if candidate is None:
        matched: set[str] = set()
        mismatched = set(supplied)
    else:
        matched, mismatched = match_party(candidate, supplied, state.id_kind_hint)

    new = _count_new_mismatches(state, supplied, mismatched)
    state.candidate_party_id = candidate.party_id if candidate else None
    state.matched_factors = matched
    state.record(
        "VERIFICATION_EVALUATED",
        provided_count=len(supplied),
        matched_count=len(matched),
        new_mismatches=new,
    )

    if candidate is not None and len(matched) >= settings.min_factors:
        return _complete(state, store, settings, consent, candidate, new)

    if state.mismatch_count >= settings.max_mismatches:
        state.record("VERIFICATION_LOCKED", mismatch_count=state.mismatch_count)
        return _result(VerifyStatus.LOCKED, state, new)
    return _result(VerifyStatus.MISMATCH if mismatched else VerifyStatus.NEED_MORE, state, new)


def _complete(
    state: State,
    store: FixtureStore,
    settings: Settings,
    consent: ConsentGateway,
    candidate: Policyholder,
    new: int,
) -> VerifyResult:
    """Enough factors matched one party. Finish as policyholder, or run the rep checks."""
    if state.caller_role != "representative":
        state.mark_verified(candidate.party_id, "policyholder", min_factors=settings.min_factors)
        return _result(VerifyStatus.VERIFIED, state, new)

    if not state.rep_name:
        return _result(VerifyStatus.NEED_REP_IDENTITY, state, new)
    if not _rep_authorized(store, candidate.party_id, state.rep_name):
        state.record("REPRESENTATIVE_NOT_AUTHORIZED")
        return _result(VerifyStatus.REP_NOT_AUTHORIZED, state, new)

    _ensure_consent(state, candidate.party_id, consent)
    if state.consent == ConsentState.APPROVED:
        state.mark_verified(candidate.party_id, "representative", min_factors=settings.min_factors)
        return _result(VerifyStatus.VERIFIED, state, new)
    if state.consent == ConsentState.DENIED:
        return _result(VerifyStatus.CONSENT_DENIED, state, new)
    return _result(VerifyStatus.CONSENT_TIMED_OUT, state, new)  # fail closed
