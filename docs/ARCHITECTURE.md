# Insurance Claims SOP Agent: Frozen Design (v1)

Status: frozen before implementation. Changes require updating this file and the matching tests.

All customer, policy, claim and PII data in this repository is synthetic test data.

## 1. Principle

**LLM interprets. Code decides. Tools provide facts. State remembers.**

- The LLM understands messy language (structured extraction) and phrases replies.
- Code owns phase transitions, verification, what data enters the LLM context, and every side effect.
- Claim data is never loaded, and never placed in any prompt, before verification succeeds. A confused or jailbroken model has nothing to leak.

## 2. Inputs we were given (fixtures, never modified)

`apps/insurance_claims/fixtures/`: `policyholders.json`, `claims.json`, `representatives.json`, `consent_scenarios.json`, `required_document_guideline.json`, `claim_schema.json`.

Rules that follow from the data:

- Code is fully data-driven. No hardcoded names, IDs or fields. `FIXTURES_DIR` is configurable. Missing optional fields are tolerated (graders may swap fixtures).
- Naming follows the starter: `party_id`, `case_id`, `case_type`, `created_at`.
- The fifth PII factor is `id_last4`. The on-file `id_type` (`ssn_last4` or `national_id_last4`) is never revealed to the caller. Prompts ask for "last four of your SSN or national ID". If the caller explicitly names a type, it must agree with the stored `id_type` (section 7).
- Intent catalog is the starter's: `status_inquiry`, `denial_question`, `document_submission`, `next_steps`, `general_claim_question`.
- No write actions exist. Side effects are only: consent request, email summary, human handoff.

## 3. Phases and control level

```
VERIFY_ID -> RESOLVE_INTENT -> PROCESS_CASE -> POST_PROCESS -> COMPLETE
```

| Phase | Control | LLM role |
|---|---|---|
| VERIFY_ID | Strict. Pure code decides. | Extract fields, phrase replies |
| RESOLVE_INTENT | Bounded. Closed intent set, verified party's claims only. | Interpret messy language, rank hints |
| PROCESS_CASE | Grounded. Code assembles context. | Explain, answer follow-ups from context only |
| POST_PROCESS | Consent-gated. | Understand yes/no/unclear, phrase |

A handler returns `NEEDS_INPUT` or `ADVANCE`. The controller loops handlers until one needs input, so Margaret's single message passes VERIFY_ID -> RESOLVE_INTENT -> PROCESS_CASE in one turn. Every transition is audited. Only code mutates `phase`.

Allowed back-edge: POST_PROCESS -> RESOLVE_INTENT for another question (already verified; bounded by `MAX_CASE_LOOPS`).

## 4. Per-turn pipeline

```
user msg
 -> EXTRACT    regex/spoken-form pre-pass + LLM structured output (given expected_fields from last agent message)
 -> VALIDATE   normalize + format-check in code, merge into state (remember != act)
 -> PLAN       SOP controller -> TurnPlan: ordered dialogue acts
 -> PHASE WORK verify | resolve | process | post   (loop while ADVANCE)
 -> RENDER     one LLM call: acts + permitted facts -> reply; deterministic template fallback per act
 -> GUARD      grounding literals, pre-verification leak check, PII-echo check
 -> PERSIST    state + masked audit events
```

Act priority within a turn: safety/human > emotion acknowledgment > out-of-scope decline > phase work > exactly one next ask. Mixed messages answer the in-scope part and decline the rest. Controller never early-returns past extraction and memory merge.

### Dialogue acts (closed set)

`ACK_EMOTION`, `EXPLAIN_WHY_VERIFY`, `REQUEST_FIELDS(fields)`, `ACK_FIELDS_PROVIDED(fields)`, `VERIFY_GENERIC_MISMATCH`, `OFFER_ALT_FIELDS`, `REQUEST_ROLE`, `REQUEST_CONSENT_WAIT`, `CONSENT_RESULT(status)`, `VERIFIED_OK`, `CONFIRM_CLAIM(case)`, `ASK_DISAMBIGUATION(options)`, `NO_CLAIMS_FOUND`, `ANSWER_FROM_FACTS(facts)`, `UNKNOWN_NOT_IN_FILE`, `UNSUPPORTED_ACTION`, `DECLINE_OOS(level)`, `OFFER_HUMAN(reason)`, `TRANSFER_HUMAN`, `OFFER_EMAIL_SUMMARY`, `CONFIRM_EMAIL_ADDRESS`, `EMAIL_SENT`, `EMAIL_SKIPPED`, `ASK_ANYTHING_ELSE`, `CLARIFY_CONSENT`, `TECH_FALLBACK`.

## 5. State (server-side only; client sends session_id + message)

```python
class Phase(str, Enum): VERIFY_ID, RESOLVE_INTENT, PROCESS_CASE, POST_PROCESS, COMPLETE

class State(BaseModel):
    session_id: str
    phase: Phase = Phase.VERIFY_ID
    # captured (account-holder values), raw; masked everywhere outside the matcher
    factors: dict[str, str] = {}            # full_name, dob, phone, email, id_last4
    policy_number: str | None = None        # lookup key, NOT a factor
    caller_role: Literal["policyholder","representative","unknown"] = "unknown"
    rep_name: str | None = None
    rep_relationship: str | None = None
    refused_fields: set[str] = set()
    # verification
    candidate_party_id: str | None = None
    matched_factors: set[str] = set()       # inspector only; never spoken
    mismatch_count: int = 0
    verified: bool = False
    verified_party_id: str | None = None
    verified_as: Literal["policyholder","representative"] | None = None
    consent: ConsentState = NOT_REQUESTED   # NOT_REQUESTED|PENDING|APPROVED|TIMED_OUT
    consent_trail: list[str] = []
    # cross-phase memory
    intent_hint: str | None = None          # one of the 5 intents
    case_hints: dict = {}                   # case_type, status, month, year, case_id
    # resolution / case
    resolved_case_id: str | None = None
    case_record: CaseRecord                 # topics, status, follow_ups, docs, facts_used (feeds email)
    # emotion / scope / escalation counters
    emotion: str = "neutral"; severity: int = 0
    refusal_count: int = 0; frustration_streak: int = 0
    oos_strikes: int = 0; case_loops: int = 0
    doc_unavailable: set[str] = set()       # drives "alternatives exhausted -> human"
    human_offered: bool = False; human_transferred: bool = False
    # post-process
    email_state: Literal["not_offered","offered","address_confirm","sent","skipped"] = "not_offered"
    email_address: str | None = None
    last_expected_fields: list[str] = []
    events: list[AuditEvent] = []           # masked
```

## 6. Turn understanding (LLM structured output, Pydantic-validated)

```python
class TurnUnderstanding(BaseModel):
    factors: dict[FactorName, str]           # only those present; values as the caller said them
    policy_number: str | None
    caller_role: Literal["policyholder","representative","unknown"]
    rep_name: str | None; rep_relationship: str | None
    refused_fields: list[FactorName]         # "I won't give my SSN"
    refuses_verification: bool               # "I won't verify at all"
    asks_why_verification: bool
    id_kind_hint: Literal["ssn","national_id","unspecified"] | None   # set only when the caller's own words name the type
    intents: list[Intent]                    # closed set of 5
    case_hints: CaseHints                    # case_type, status (normalized), month, year, case_id
    emotion: Literal["neutral","frustrated","angry","anxious","confused","sad"]
    severity: int                            # 0-3
    scope: Literal["in_scope","insurance_general","out_of_scope","injection_attempt"]
    wants_human: bool; distress_or_emergency: bool
    user_done: bool                          # "that's all", "no thanks"
    cannot_obtain_documents: list[str]       # docs the caller says they cannot get
    claim_switch_request: str | None
    followup_topics: list[str]               # multi-label; closed set = topic names in the guideline fixture
    email_consent: Literal["yes","no","unclear","not_applicable"]
    alt_email: str | None
```

Never parse prose for safety decisions. The regex pre-pass (email, 4-digit run after "last four", phone, ISO/US dates, `POL-\d+`, number words to digits, "at/dot" to `@`/`.`) is merged with LLM output. Code format-validation wins on conflict. If the LLM times out, VERIFY_ID still works from the pre-pass.

### Implementation notes (extraction and memory, as built)

- The LLM-facing schema is the flat `LLMExtraction`. `TurnUnderstanding` extends it with code-derived fields. The ID-type hint (`ssn` / `national_id` / `unspecified`) is derived from keywords in the message by code; the LLM is not asked for it. This supersedes `id_kind_hint` in the schema above.
- A deterministic pre-pass (email, phone, DOB with a cue like "DOB is" or "born", ID last-four with a cue, policy number by known prefix, spoken digits and spoken emails) runs first and wins over the LLM on any identity value.
- An LLM-only identity value is kept only if it is a usable instance of the factor **and** grounded in the message text (a spoken DOB must show month, day and year; an ID that looks like a phone fragment or a DOB year is dropped; names must appear in the message). Dropped values are audited as `EXTRACTION_DROPPED`. This prevents a hallucinated value from costing a genuine caller a verification strike.
- Requests for a human are also caught by regex, so escalation does not depend on the LLM.
- Only the message, the last agent reply and field-name flags go to the model: never stored PII values, never claim data, and the follow-up topic list only once verified.
- On LLM failure: one retry for malformed output, then fall back to a pre-pass-only understanding with `fallback_reason` set. Verification keeps working.
- Memory (`apply_understanding`) records facts only. It never changes phase, verifies anyone or touches claims. The representative role is sticky, and the ID-type hint belongs to the most recent ID value.

## 7. VERIFY_ID (strict)

Factors: `full_name`, `dob`, `phone`, `email`, `id_last4`. Need at least `MIN_FACTORS = 3` matching **the same party record**. `policy_number` selects a candidate but never counts.

Normalization (exact, no fuzzy):
- name: casefold, strip punctuation/diacritics, token-reorder ("Chen, Margaret"); match primary or any `name_aliases`
- dob: parse to ISO; ambiguous `03/04/1985` read as US month/day
- phone: digits, drop leading country code 1, compare 10 digits exactly; match primary or `phone_aliases`
- email: lowercase; match primary or `email_aliases`
- id_last4: 4 digits, plus `id_kind_hint` (`ssn` | `national_id` | `unspecified`). The hint is set only when the caller's own words name the type, never inferred from the agent's question. Regex keywords (ssn, social security, national id) cross-check the LLM; code wins on conflict.
  - `unspecified` ("the last four of my ID are 6688"): compare digits only.
  - `ssn`: the stored `id_type` must be `ssn_last4` for the factor to match. `national_id`: the stored `id_type` must be `national_id_last4`.
  - A stated type that conflicts with the stored type means the factor does not count, and the supplied value counts toward `mismatch_count`.
  - Replies stay generic: never reveal the stored `id_type` or which part mismatched.
- each factor counts once even if several aliases are supplied

Candidate selection: if `policy_number` resolves, bind to that party. Otherwise pick the party with the most matched factors. All matches must be to one party.

Rules:
- Replies speak only of fields **provided**, never **matched**. Mismatches get a generic reply. This prevents an oracle for guessing.
- `mismatch_count` counts supplied values that did not match. Fewer than 3 provided is not a failure. At `MAX_MISMATCHES = 3` -> offer human, stop automated verification.
- Corrections overwrite earlier values. History kept for audit only.
- Refusing one field -> `OFFER_ALT_FIELDS`, no strike. `refuses_verification` -> persuade once, then at `MAX_VERIFICATION_REFUSALS = 2` -> `OFFER_HUMAN`.
- Early hints (intent, case hints, rep name) are stored. Phase stays VERIFY_ID. The reply never confirms that any claim exists.

### Implementation notes (as built)

- Usable formats: a full name needs 2+ name tokens (titles and middle initials are ignored); DOB must be a complete date with a 4-digit year; phone needs 10+ digits; email must parse; ID last-four is exactly 4 digits. An unusable value counts as *not provided*, never as a mismatch.
- Candidate selection: a resolvable policy number binds the candidate. Otherwise the party matching the most supplied factors wins, with fixture order breaking ties. Mixed-record guesses are therefore charged as mismatches against one record. An unresolvable policy number is ignored (no oracle, since a policy number alone never verifies).
- Each distinct wrong value is counted once (stored hashed), however many turns it stays in the state.
- `VerifyResult` exposes only `provided` and `missing`. Matched factors live in state for the evaluator inspector only.
- Consent is bound to the party it was issued for and is never re-requested after a terminal result.

### Representative sub-flow (assumption: consent_scenarios.json = representative approval)

1. `caller_role = representative`, or a stated full name matching a rep record for the candidate party but not the party's own name -> treated as a representative (David giving Margaret's data as himself must not verify as Margaret).
2. Need 3 factors of the account holder (rep's own name is not one) **and** `rep_name` matches `representatives.json` for that `buyer_party_id`. Unlisted people (e.g. a spouse) cannot proceed -> `OFFER_HUMAN`.
3. Only then `request_consent(party_id)` runs, so attackers cannot spam approval prompts. State `PENDING`.
4. Poll up to `MAX_CONSENT_POLLS = 5` within the turn, following the scenario's `status_sequence`. `approved` -> `verified_as = representative`. Sequence ends still pending -> `TIMED_OUT`: no access, offer human.
5. Email summary for a representative goes only to the address on file.

Scenario (`default` / `timeout`) comes from session config or a demo button. Policyholders are not gated on consent.

## 8. Tool gateway (defense in depth)

Read-only, controller-invoked functions: `lookup_party`, `list_cases(party_id)`, `get_case(case_id)`, `get_doc_guidance(case)`, `get_followup_guidance(case, intent, utterance)`, `request_consent`, `poll_consent`, `send_email`, `transfer_to_human`.

- Every claim-touching call re-checks `state.verified` and takes `party_id` from state, never from model output.
- `get_case` verifies `case.party_id == state.verified_party_id` (ownership check).
- The model never supplies a customer or claim ID to a tool.
- Tool output free-text is treated as data, never instructions.

## 9. RESOLVE_INTENT

- Input: stored `intent_hint` + `case_hints`, run against `list_cases(verified_party_id)`.
- Score all hints together. Normalize status synonyms (rejected/turned down -> denied; settled/paid/completed -> closed; in progress/pending -> open). Month without year matches any year.
- One clear match with all hint dimensions -> `CONFIRM_CLAIM` states the claim inline and proceeds (correctable). Partial match with 2+ candidates -> one targeted `ASK_DISAMBIGUATION`. Zero claims -> `NO_CLAIMS_FOUND` + human.
- Margaret demo: healthcare + January matches CL-2048 (2026) and CL-2011 (2025). "denied" resolves to CL-2048.

## 10. PROCESS_CASE (grounded)

Context pack, assembled by code, one render call:
1. the resolved case record (only fields that exist)
2. `claim_schema.json` field semantics (expected_reimbursement_amount, allowed_max_amount, net_pay, net_fee)
3. document guidance via `DocGuidanceResolver`: token-subset match of each `documents_needed` entry to guideline keys, with fallback chain document -> case-type -> default, plus alternative guidance when `cannot_obtain_documents` is set
4. follow-up rules matched by `intent_hints` + `match_any`; multiple independent topics per utterance (see Follow-up matching); `requires_documents` rules apply only when the case has documents needed; otherwise `claim_followup_fallback`
5. code-computed derived facts: `days_until_appeal_deadline`, `deadline_passed` (from the injected `Clock`, see section 14)

Rules:
- Use only the context pack. Absent info -> `UNKNOWN_NOT_IN_FILE`.
- No derived amounts, no speculation about outcomes of appeal or reconsideration, no invented policy terms.
- "File my appeal" etc. -> `UNSUPPORTED_ACTION` + human offer.
- Document alternatives exhausted (`human_review_after_document_alternatives_exhausted`) -> `OFFER_HUMAN`.
- `claim_switch_request` re-enters RESOLVE_INTENT (bounded by `MAX_CASE_LOOPS`).
- Output schema: `{reply, facts_used[]}`.

### Follow-up matching

Supports multiple independent topics in the same utterance. Candidates come from two merged sources:
- phrase match: every `match_any` phrase found in the utterance, with its character span
- semantic match: `TurnUnderstanding.followup_topics`, a multi-label choice from the closed topic list in the guideline fixture (covers messy wording the phrases miss)

Rules:
- Longest/specific phrase wins when phrase spans overlap or refer to the same semantic topic ("how soon do i need to submit" beats "how soon").
- Non-overlapping follow-up topics may all be selected.
- Deduplicate topics before building the context pack.
- Only include guidance for topics that match both the utterance and the allowed conditions: any of the turn's `intents` is in the topic's `intent_hints`, and `requires_documents` is satisfied. A multi-topic utterance can straddle intents, which is why `intents` is a list.
- If nothing is eligible, use `claim_followup_fallback`.

### Grounding guard (code, post-render)

Two complementary checks, both in plain code (`agent/grounding.py`):

1. **Literal grounding (enforcement).** Every claim number, date, amount, day count and document name in the reply must be supported by a fact, after normalization (`$1,450` = `1450.00` = `1,450 dollars`; `March 18, 2026` = `3/18/2026` = `2026-03-18`). Any other number left over is also flagged, so an invented "30 days to appeal" cannot pass as a stray digit. A date written without a year is accepted only if exactly one date in the facts has that month and day; with none or several it is a violation, and the guard never supplies a year to make a reply pass.
2. **Fact references (provenance).** The model returns `{reply, facts_used}`. Code checks only that every cited id is a real fact id. This is coarse provenance and debugging visibility, not proof that a sentence is correct, and it is not treated as a security boundary.

Failure -> regenerate once with the guard's specific feedback -> template built from the facts.

**Known limits** (covered by prompt rules and the bounded context, not by the guard; each is pinned by a test):
- Durations in words have no digits to check: "within a week", "thirty days", "a couple of days".
- A claim about *why* or *what* with no literal in it ("denied because the provider used the wrong billing code") passes, and citing a real fact does not prevent it. The Tier 2 live scenarios probe this.
- Document names are recognized only from the vocabulary the data contains.

## 11. Scope guard

Labels: `in_scope`, `insurance_general` (definitions like "what is a deductible?", allowed, no personal data pre-verification), `out_of_scope`, `injection_attempt`.

- Strike 1: polite decline + redirect. Strike 2: firmer + examples of what I can do. Strike 3 (`MAX_OOS_STRIKES = 2` before offering): `OFFER_HUMAN`. Consecutive-ish: strikes reset after 2 in-scope turns.
- Injection attempts get a neutral decline and never change behavior.

## 12. Emotion and recovery (bonus)

Emotion modifies acts, never gates. Order inside a reply: acknowledge -> explain why the gate exists -> offer options -> one next ask.

- "I already told you who I am": acknowledge, say which fields were *provided* (not matched), state that claim details are protected until verification, list remaining accepted fields, never re-ask provided fields.
- Persuasion is capped: explain, offer alternatives, escalate.
- Immediate human triggers: explicit request, abuse, legal threat, `distress_or_emergency`.
- `frustration_streak >= MAX_FRUSTRATION_STREAK (3)` at severity >= 2 after recovery attempts -> `OFFER_HUMAN`.

## 13. POST_PROCESS

1. After the case answer, `ASK_ANYTHING_ELSE`. `user_done` (or loop cap) -> POST_PROCESS.
2. `OFFER_EMAIL_SUMMARY`. yes -> confirm address (on file, masked; alternative only with read-back, never for representatives) -> send. no -> skip. unclear -> `CLARIFY_CONSENT`. A bare "okay" is never consent.
3. UI send/skip chips write to the same consent state as natural language.
4. Summary is generated from the structured `case_record` (topics discussed, claim status/outcome, follow-ups, documents needed, deadline, processing time), not the transcript, and passes the same grounding guard. "Sending" writes to a visible outbox (optional SMTP).
5. Another question after summary -> back to RESOLVE_INTENT; otherwise COMPLETE.

## 14. Configuration (thresholds live in config, not prompts)

`MIN_FACTORS=3`, `MAX_MISMATCHES=3`, `MAX_VERIFICATION_REFUSALS=2`, `MAX_OOS_STRIKES=2`, `MAX_FRUSTRATION_STREAK=3`, `MAX_CONSENT_POLLS=5`, `MAX_CASE_LOOPS=3`, `AS_OF_DATE` (optional, see Clock), `ENABLE_DEBUG_INSPECTOR=false`, `CONSENT_SCENARIO=default|timeout`, `FIXTURES_DIR`, `LLM_PROVIDER=anthropic`, `LLM_MODEL_FAST`, `LLM_MODEL`, `LLM_API_KEY`.

### Clock

`AS_OF_DATE` is optional and injectable.

- If `AS_OF_DATE` is provided, use it as the deterministic current date for tests/demo scenarios.
- If `AS_OF_DATE` is not provided, use the real system date.
- Deadline-derived facts such as `days_until_appeal_deadline` and `deadline_passed` must use this clock abstraction, and no other code calls `date.today()`.
- Unit tests use a `FixedClock` so deadline behavior is deterministic.
- `deadline_passed` is true only when today is after the deadline. On the deadline day it is false and `days_until_appeal_deadline` is 0.

```python
class Clock(Protocol):
    def today(self) -> date: ...

class SystemClock:
    def today(self) -> date:
        return date.today()

class FixedClock:
    def __init__(self, value: date):
        self.value = value
    def today(self) -> date:
        return self.value
```

Implemented in `agent/clock.py` and injected into the controller and context-pack builder. Relative dates in caller language ("last month") use the same clock.

### Debug inspector (evaluator/development only)

The workflow inspector is development/evaluator instrumentation and is never part of the normal customer-facing interface.

`ENABLE_DEBUG_INSPECTOR=false` by default.

When enabled:
- `GET /api/session/{id}/debug` is available.
- The UI may show phase, memory, matched factors, dialogue acts, tool calls, consent trail, and outbox state.
- All PII remains masked.

When disabled:
- The debug endpoint is unavailable (404).
- The customer UI never reveals matched factors, internal tool calls, candidate party IDs, claim-selection scores, or verification internals.
- `/api/chat` responses carry only the reply and customer-facing hints (transfer indicator, email send/skip chips). Phase and other internals are not included, so the gate is enforced server-side, not just hidden in the UI.

The inspector exists only so evaluators can verify the SOP implementation and must not weaken the production privacy boundary.

## 15. Errors and safety

- Missing API key: app boots, UI shows a key field (memory only, never logged).
- LLM timeout or malformed output: retry once, then deterministic template per act. Verification still works from the pre-pass.
- Backend failure: `TECH_FALLBACK` ("I haven't changed or guessed anything. I can retry or connect you to a representative.").
- Logs and debug endpoint mask PII (an ID last-four is shown only as `****`, since four digits is the entire secret; audit events are scrubbed on creation). Renderer prompts receive field-provided flags, never raw PII values.
- State is server-side. Client cannot set phase or verification.

## 16. Invariants (each is a test ID)

1. No claim data loaded or prompted before verification.
2. `verified` iff at least 3 factors match one party.
3. `policy_number` never counts.
4. LLM cannot change phase.
5. Later-phase information is remembered early.
6. Remembered information never advances a phase by itself.
7. Every PROCESS_CASE fact comes from the context pack (guard).
8. Out-of-scope requests receive no unrelated answer.
9. Repeated out-of-scope -> human offered.
10. Email never sent without explicit consent.
11. A tool call cannot return another party's case.
12. A representative is not verified without rep authorization and consent approval.
13. Replies never reveal which supplied field mismatched or the stored ID type.
14. A stated ID type that conflicts with the stored type never counts as a match.
15. With `ENABLE_DEBUG_INSPECTOR=false`, the debug endpoint is unavailable and no internals appear in any customer-facing response.

## 17. Tests

Tier 1, deterministic, scripted mock LLM (pytest): all invariants, plus fixture-derived cases:
- Margaret demo in one turn (ends PROCESS_CASE, CL-2048)
- January ambiguity without "denied" -> targeted question
- Margaret's name + Ava's DOB + Ma Tian's ID -> not verified
- Near-identical phones (…2836 vs …2830) never cross-verify
- Ya Wen Li verifies via alias ("Yaven Li"), duplicate alias counts once
- Ma Tian verifies with "the last four of my ID are 6688"
- Ma Tian verifies when explicitly saying "national ID"
- Ma Tian does not receive a match when explicitly calling it an SSN
- Margaret (stored SSN) does not receive a match when explicitly saying "national ID"
- The reply stays generic and does not reveal the stored ID type
- Ava and Ya Wen Li -> no-claims path
- CL-3001 "diagnosis report" -> fallback guidance, nothing invented
- "how soon do I need to submit" -> submission_timing, not processing_time
- Multi-topic, semantic path (mock LLM returns topics): "Where do I upload the pathology report, and how long will it take once I send it?" -> submission_method + processing_time_after_submission, each once
- Multi-topic, phrase-only baseline (no LLM topics): "Where do I submit the pathology report, and how long will it take once I send it?" -> both topics (the fixture phrases do not include "upload")
- Deadline facts under FixedClock: before, on and after the deadline (CL-2048: 2026-03-18)
- Closed claim denial question -> "not denied", no denial fields invented
- Derived amount (allowed minus paid) rejected by guard
- David Chen as himself with Margaret's data -> not verified as Margaret
- Representative: consent default approves; consent timeout -> human
- Canary test: unique strings planted in claim fixtures never appear in any prompt or reply before verification

Tier 2, live-LLM scenario script (~10): Margaret, frustrated caller, three out-of-scope retries, SSN refusal, injection, ambiguity, email yes/no/unclear.

Tier 3, one Playwright smoke test.

## 18. Delivery

```
goaly/
  README.md  Dockerfile  docker-compose.yml  .env.example  .dockerignore
  docs/ARCHITECTURE.md  docs/requirements-matrix.md
  apps/insurance_claims/
    fixtures/            (untouched)
    agent/  controller.py  state.py  verify.py  resolve.py  process.py  post.py
            acts.py  render.py  guard.py  extract.py  consent.py  tools.py  config.py
            llm/ (client protocol, anthropic adapter, prompts)
    api/    (FastAPI: POST /api/session, POST /api/chat, GET /api/session/{id}/debug)
    ui/     (React + TS + Vite: chat, inspector, scenario buttons, outbox)
    tests/
  scripts/package.sh     (zip excluding node_modules, venvs, .env)
```

- Single container: multi-stage Docker build, UI served by FastAPI, one port. `cp .env.example .env`, add key, `docker compose up --build`.
- Optional evaluator inspector, enabled only with `ENABLE_DEBUG_INSPECTOR=true`, shows phase, masked factors, memory, dialogue acts, tool calls, consent trail, and outbox state. It is disabled in the default customer-facing configuration.
- Scenario buttons: Margaret demo, frustrated caller, out-of-scope retries, SSN refusal, representative approved, representative timeout. Shown only when `ENABLE_DEBUG_INSPECTOR=true`, since consent-scenario switching is a test hook.
- `.env.example` ships an evaluator demo profile: `ENABLE_DEBUG_INSPECTOR=true` and `AS_OF_DATE=2026-03-05` (fixture-era date so appeal deadlines are live). Code defaults stay inspector off and real system date.
- `docs/requirements-matrix.md` maps every sentence of the brief to a mechanism and a test.

## 19. Build order

1. Fixtures loader, state, config, tool gateway.
2. Normalizers and verification (pure code), representative sub-flow, consent gateway. Tests green.
3. Extractor (pre-pass, then LLM) and cross-phase memory.
4. Controller loop, dialogue acts, renderer with template fallbacks.
5. Resolver and PROCESS_CASE (context pack, guidance resolver, guard).
6. Scope guard, emotion layer, human escalation.
7. POST_PROCESS, email consent, outbox.
8. API, UI, inspector, scenario buttons.
9. Tier 2 scenarios, Playwright smoke, Docker, README, requirements matrix, package script.

## 20. Open assumptions

- `consent_scenarios.json` is for representative approval. If it turns out to mean email consent, only sections 7 and 13 change.
- Demo `.env.example` pins `AS_OF_DATE` to a fixture-era date; the code default is the real system date.
- Anthropic is the default provider behind the client protocol.
