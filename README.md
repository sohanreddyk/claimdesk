# ClaimDesk

**Guided insurance claims support.** A conversational insurance claims agent that follows a fixed
four-phase SOP while still talking naturally:

```
VERIFY_ID  ->  RESOLVE_INTENT  ->  PROCESS_CASE  ->  POST_PROCESS
```

**The LLM interprets language and phrases replies. Deterministic code controls the workflow,
verification, what data the model can see, and every side effect.** A confused or jailbroken model
has nothing to leak: no claim data is loaded, or placed in any prompt, before identity is verified.

> **All customer, policy, claim and PII data in this repository is synthetic test data.**

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (the frozen design, with an "as built" section
listing where the implementation differs).
Requirements: [docs/requirements-matrix.md](docs/requirements-matrix.md) maps every requirement in
the brief to the mechanism that meets it and the tests that prove it.

## Quick start (Docker)

Needs Docker only.

```bash
cp .env.example .env        # then edit .env: see "Choosing an LLM" below
docker compose up --build
```

Open <http://127.0.0.1:8000>. One container serves the API and the UI on one port.

`.env.example` ships an **evaluator profile**: the workflow inspector and scenario buttons are on,
and "today" is fixed to 2026-03-05 so the sample appeal deadlines are live (CL-2048's deadline,
2026-03-18, is 13 days away). Remove `AS_OF_DATE` to use the real date. The code defaults are the
opposite: inspector off, real date.

### Choosing an LLM

Set these in `.env`. The model names must belong to the provider you choose.

| Provider | `LLM_PROVIDER` | `LLM_MODEL` / `LLM_MODEL_FAST` (examples) |
|---|---|---|
| Anthropic (default) | `anthropic` | `claude-sonnet-5-5` / `claude-haiku-4-5-20251001` |
| OpenAI | `openai` | `gpt-5.4-mini` / `gpt-5.4-mini` |

Put the key in `LLM_API_KEY`. Check the setup with `python scripts/smoke_llm.py`: it makes one real
call and one real extraction and prints the results. `LLM_REASONING_EFFORT` (OpenAI reasoning models
only, for example `low`) trades some depth for speed.

**Without a key the app still starts.** SOP gates run in plain code, so verification from dates,
phone numbers, emails and ID digits works, and answers come from the claim facts through fixed
templates. Understanding free-form language (names, intent, emotion, scope) needs the model.

### Try it

With the inspector on, the right-hand pane (the "SOP inspector", marked evaluator-only) shows the
agent's workings as structured sections: Workflow, Identity, Current Case, Remembered Context,
Safety and Activity, with the raw internals collapsed under Technical details. The overflow menu
(the ⋯ button in the top bar) holds the **Demo scenarios**: choosing one starts a fresh conversation
and fills the message box; press **Send** to run it. Answers read from the claim record are marked
"Grounded in claim record". On narrow screens the inspector opens from a "Workflow inspector"
button.

| Scenario | What it shows |
|---|---|
| Margaret demo | Verification from a single message, then the denial explained |
| Frustrated caller | Acknowledges the frustration, then verifies; repeated anger offers a human |
| Out-of-scope retries | Polite declines, then a human offer at the limit |
| SSN refusal | Offers phone or email instead; repeated refusals offer a human |
| Representative approved | A son calling for his mother: needs policyholder consent, then verifies |
| Representative timeout | Consent never arrives: no claim details, human offered |

Then try: "how long do I have to appeal?", "what documents do I need?", "I can't get the pathology
report", "what about my dental claim?", and "that's all" (which offers a summary email).

## How it works

### The turn pipeline

```
user message
  -> EXTRACT     regex/spoken-form pre-pass + LLM structured extraction (the model only extracts)
  -> VALIDATE    normalize and format-check in code; merge into state (remembering is not acting)
  -> PLAN        the SOP controller picks an ordered list of dialogue acts
  -> PHASE WORK  verify | resolve | process | post   (loops while a phase advances)
  -> RENDER      acts + permitted facts -> reply, with a deterministic template for every act
  -> GUARD       grounding literals, pre-verification leak check, PII-echo check
```

| Phase | Control | What the LLM does |
|---|---|---|
| VERIFY_ID | Strict: pure code decides | Extracts fields, phrases replies |
| RESOLVE_INTENT | Bounded: closed intent set, the verified caller's claims only | Interprets messy language |
| PROCESS_CASE | Grounded: code assembles the facts | Explains and answers from those facts only |
| POST_PROCESS | Consent-gated | Understands yes/no/unclear (code has the final say) |

Margaret's single opening message passes through the first three phases in one turn.

### What is enforced in code, not by prompting

- **Verification needs three matching factors on one record.** Factors are name, date of birth,
  phone, email and the last four digits of an SSN or national ID. A policy number selects a
  candidate but never counts. Matching is exact after normalization (aliases supported). A stated
  ID type must agree with the stored type. Replies never reveal which supplied value failed or the
  stored ID type, so there is no oracle for guessing.
- **Representatives** need three factors of the account holder, an authorization record, and the
  policyholder's consent (simulated from `consent_scenarios.json`) before any access. The consent
  request only happens after the first two checks pass.
- **The tool gateway re-checks `verified` on every call** and takes the party from state, never
  from model output. A claim belonging to someone else is indistinguishable from one that does
  not exist.
- **Answers are grounded.** Every claim number, date, amount, day count and document name in a
  reply must appear in the supplied facts after normalization. A violation is regenerated once
  with specific feedback, then replaced by a reply built straight from the facts. Deadline
  arithmetic is done by code from an injectable clock; the model never computes it.
- **Email is consent-gated.** Nothing is sent without an explicit yes. A bare "okay", "sure" or any
  question never counts, even if the model says it does. A different address (policyholders only)
  is read back masked and needs a second yes; a representative can only use the address on file.
  The summary is built by a template from structured case data, not by the LLM.
- **Escalation is bounded.** Out-of-scope, frustration, refusals, mismatches, consent timeouts and
  document dead-ends all lead to a human offer after a configured limit.
- **Privacy.** Identity values are masked everywhere outside the matcher (an ID's last four digits
  appear only as `****`). Logs contain phases and act names, never message text.

### The inspector (evaluators only)

`ENABLE_DEBUG_INSPECTOR=true` enables `GET /api/session/{id}/debug`, the API docs, the Demo
scenarios menu and the SOP inspector (workflow, identity, current claim, remembered context,
safety, activity, and a collapsed technical-details section). Everything in it is masked. With it off (the code default) the
endpoint returns 404 and no internals appear in any customer-facing response: `/api/chat` returns
only `{reply, ended}`, enforced server-side.

## Configuration

All settings are environment variables (see `.env.example`). Thresholds live in config, never in
prompts; `MIN_FACTORS` below 3 is rejected at startup.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER`, `LLM_API_KEY` | `anthropic`, unset | Provider and key |
| `LLM_MODEL`, `LLM_MODEL_FAST` | Claude models | Replies and answers / per-turn extraction |
| `LLM_REASONING_EFFORT` | unset | OpenAI reasoning models only |
| `FIXTURES_DIR` | `apps/insurance_claims/fixtures` | Where the data comes from |
| `AS_OF_DATE` | real date | Fixed "today" for demos and tests |
| `ENABLE_DEBUG_INSPECTOR` | `false` | Inspector, scenario buttons, API docs |
| `CONSENT_SCENARIO` | `default` | `default` approves, `timeout` never arrives |
| `MIN_FACTORS` | 3 | Matching factors required (minimum 3) |
| `MAX_MISMATCHES` | 3 | Wrong values before verification locks |
| `MAX_VERIFICATION_REFUSALS` | 2 | Refusals before a human is offered |
| `MAX_OOS_STRIKES` | 2 | Out-of-scope requests before a human is offered |
| `MAX_FRUSTRATION_STREAK` | 3 | Frustrated turns before a human is offered |
| `MAX_CONSENT_POLLS` | 5 | Polls of the consent gateway per turn |
| `MAX_CASE_LOOPS` | 3 | Claim switches per conversation |
| `MAX_EMAIL_ADDRESS_ATTEMPTS` | 2 | Rejected alternate addresses |

The data is read from fixtures and never hardcoded, so the fixtures can be swapped
(`FIXTURES_DIR`). Missing optional fields are tolerated.

## HTTP API

| Endpoint | |
|---|---|
| `POST /api/session` | Returns `{session_id, greeting}`. The greeting is fixed text with no customer data. |
| `POST /api/chat` | `{session_id, message}` returns `{reply, ended}`. |
| `GET /api/session/{id}/debug` | Inspector view. 404 unless the inspector is enabled. |
| `GET /api/health` | `{status, llm_configured}`. Never returns the key. |

Sessions are in memory, with unguessable ids, an idle timeout, a cap on live sessions and a cap on
turns per session. One turn runs at a time per session. Request bodies and messages are size
limited. There is no CORS: the API and UI share one origin.

## Testing

```bash
bash scripts/check_all.sh                 # Python tests + lint, UI tests + type-check + build
WITH_DOCKER=1 bash scripts/check_all.sh   # ...plus the Docker smoke test
python scripts/smoke_llm.py               # live check of your LLM key and models
```

- **Python** (`pytest`, 670+ tests): a scripted fake LLM drives every flow deterministically.
  Includes the design's invariants, the fixture-derived scenarios, the grounding guard, the API,
  and tests that real claim details never appear in the extraction prompt or in any reply before
  verification.
- **Requirements matrix** (`scripts/check_matrix.py`): fails if any test or file named in
  `docs/requirements-matrix.md` no longer exists, so the matrix cannot go stale.
- **UI** (Vitest and React Testing Library, about 120 tests): the conversation, error handling, the
  SOP inspector and its view-model adapters, the scenario menu, the drawer and the grounded indicator.
- **Docker smoke test** (`scripts/docker_smoke.sh`): builds the image (running the Python suite on
  the image's Python 3.12), starts the packaged app, and checks the contents (non-root user, no
  `.env`/tests/sources), the served UI, the greeting, that chat exposes only `reply` and `ended`,
  and the inspector gating in both modes.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q && ruff check .

# Backend (reads .env)
uvicorn api.main:app --app-dir apps/insurance_claims --reload

# UI with hot reload (proxies /api to port 8000)
cd apps/insurance_claims/ui && npm install && npm run dev      # http://localhost:5173
```

Python 3.12 is what the Docker image runs; development was done on 3.14. The UI needs Node 22.
`npm run build` writes `apps/insurance_claims/ui/dist`, which the API serves automatically.

## Project layout

```
Dockerfile  docker-compose.yml  .env.example  requirements*.txt  pyproject.toml
docs/ARCHITECTURE.md
scripts/   check_all.sh  check_matrix.py  clean_room.sh  docker_smoke.sh  docker_smoke_checks.py
           smoke_llm.py  package.sh
apps/insurance_claims/
  fixtures/        the starter data, unmodified
  agent/           the SOP engine
    controller.py    turn loop, phases, escalation
    state.py         conversation state with guarded transitions
    verify.py        three-factor verification, representative flow
    consent.py       simulated policyholder consent
    tools.py         ownership-checked tool gateway
    understanding.py extraction (pre-pass + LLM) -> TurnUnderstanding
    resolve.py       picks the claim from remembered hints
    context.py       builds the grounded facts for a claim
    guidance.py      document and follow-up guidance
    process.py       grounded answers, one guarded retry, facts-only fallback
    grounding.py     literal-grounding guard
    acts.py templates.py render.py guard.py    dialogue acts, fallbacks, output checks
    summary.py outbox.py                       email summary and simulated outbox
    llm/             provider interface; Anthropic, OpenAI and scripted-test clients; prompts
  api/             FastAPI app: sessions, chat, debug view
  ui/              React + TypeScript + Vite: chat, inspector, scenario buttons
  tests/
```

## Limits and honest notes

- The email "send" writes to a visible in-memory outbox. There is no SMTP.
- Sessions live in memory: a restart clears them. This is a single-instance demo, not a deployment.
- The grounding guard checks literals (numbers, dates, amounts, ids, document names). A sentence
  that states a reason with no literal in it can pass the guard; prompt rules and the bounded
  fact set cover that gap, and the known cases are pinned by tests.
- Consent for representatives is a fixture-driven simulation, not a real notification system.
- **What the LLM provider sees.** The caller's own messages, including any identity details they
  type, are sent to the configured provider so it can extract fields and intent. What is never
  sent: stored identity values (the extraction prompt carries field names only), and any claim
  data before verification. After verification, a claim answer's prompt holds only the verified
  caller's own claim facts, with identity values blanked out.
- **Which provider was exercised live.** The live wording and extraction checks during development
  used OpenAI (`gpt-5.4-mini`). The Anthropic adapter, the default provider, is covered by unit
  tests against a fake client; run `python scripts/smoke_llm.py` with your key to check it live.
- **Dependencies** are bounded to the next major version (`requirements*.txt`) but not locked
  exactly, apart from the UI's `package-lock.json`.
- Where the built system differs from the frozen design (for example, no in-UI key field and no
  send/skip chips), the "as built" section at the end of `docs/ARCHITECTURE.md` says so.
