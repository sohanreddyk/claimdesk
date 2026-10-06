"""The SOP controller: the one place that decides what happens on every turn.

The LLM interprets (understanding) and phrases (renderer, grounded answers). Everything in
between is code:

    understand -> remember -> plan acts (escalation, empathy, scope, phase work) -> render -> guard

Phase transitions happen only here, through `State.set_phase`, which itself refuses illegal
moves. Handlers return whether they advanced the phase, and the controller keeps running
handlers until one needs the caller's input, so a single message can carry the caller from
VERIFY_ID through RESOLVE_INTENT into PROCESS_CASE and answer their question.

A grounded claim answer (ANSWER_FROM_FACTS) is never re-phrased: a second model pass could
reintroduce content the grounding guard already ruled out. Turns that contain one use the fixed
wording for their other acts and insert the answer as written.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .acts import ASK_PRIORITY, Act, ActKind, act
from .clock import Clock
from .config import Settings
from .consent import ConsentGateway
from .context import build_case_context
from .fixtures import Case, FixtureStore
from .guard import find_violations
from .llm.client import LLMClient
from .memory import MemoryUpdate, apply_understanding
from .prepass import redact
from .process import ProcessAnswer, generate_answer, tone_note
from .render import render_reply
from .resolve import case_option, has_hints, resolve_case
from .state import CaseHints, CaseRecord, Phase, State, Turn
from .templates import render_templates
from .tools import ToolGateway
from .understanding import TurnUnderstanding, understand_turn
from .verify import VerifyResult, VerifyStatus, verify_identity

NEGATIVE_EMOTIONS = frozenset({"frustrated", "angry", "anxious", "confused", "sad"})
ANGRY_EMOTIONS = frozenset({"frustrated", "angry"})

# When a caller's request was remembered from earlier, this is what the model is asked.
_INTENT_QUESTIONS = {
    "denial_question": "Why was this claim denied, and what does the denial mean?",
    "status_inquiry": "What is the status of this claim?",
    "next_steps": "What are the next steps for this claim?",
    "document_submission": "Which documents are needed, and how do I submit them?",
    "general_claim_question": "Can you tell me about this claim?",
}
_INTENT_LABELS = {
    "denial_question": "why the claim was denied",
    "status_inquiry": "claim status",
    "next_steps": "next steps",
    "document_submission": "document requirements and submission",
    "general_claim_question": "general questions about the claim",
}

# Phrases that clearly ask about a different claim. Works without the LLM.
_SWITCH_PHRASES = re.compile(
    r"\b(?:another|different|other)\s+claim\b"
    r"|\bwhat about (?:my|the|that)\s+(?:[\w']+\s+){1,3}claim\b",
    re.IGNORECASE,
)


def _mentions(message: str, case_id: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(case_id)}(?![A-Za-z0-9])"
    return re.search(pattern, message, re.IGNORECASE) is not None


@dataclass(frozen=True)
class TurnResult:
    reply: str
    acts: tuple[Act, ...]
    phase: Phase
    used_llm: bool  # the reply text was written by the LLM (not templates or facts)
    guard_violations: tuple[str, ...] = ()


@dataclass
class _Ctx:
    state: State
    u: TurnUnderstanding
    update: MemoryUpdate
    message: str
    start_phase: Phase
    switched: bool = False  # the caller moved to another claim during this turn


@dataclass
class _Outcome:
    acts: list[Act]
    advance: bool = False


_Handler = Callable[[_Ctx], Awaitable[_Outcome]]


class SopAgent:
    def __init__(
        self,
        *,
        store: FixtureStore,
        settings: Settings,
        llm: LLMClient,
        clock: Clock,
        consent: ConsentGateway,
    ) -> None:
        self._store = store
        self._settings = settings
        self._llm = llm
        self._clock = clock
        self._consent = consent
        self._policy_prefixes = store.policy_prefixes()
        self._topics = store.followup_topics()
        self._vocabulary = store.document_vocabulary()
        self._handlers: dict[Phase, _Handler] = {
            Phase.VERIFY_ID: self._verify,
            Phase.RESOLVE_INTENT: self._resolve,
            Phase.PROCESS_CASE: self._process,
            Phase.POST_PROCESS: self._post,
        }

    def new_state(self, session_id: str) -> State:
        return State(session_id=session_id)

    # ---- one turn ---------------------------------------------------------------------

    async def handle(self, state: State, message: str) -> TurnResult:
        state.history.append(Turn(role="user", content=message))
        if state.phase == Phase.COMPLETE:
            acts = [act(ActKind.SESSION_ENDED)]
        elif not message.strip():
            acts = [act(ActKind.EMPTY_MESSAGE)]
        else:
            understanding = await understand_turn(
                self._llm,
                self._settings,
                state,
                message,
                allowed_topics=self._topics,
                policy_prefixes=self._policy_prefixes,
            )
            update = apply_understanding(state, understanding)
            acts = await self._plan(_Ctx(state, understanding, update, message, state.phase))
        return await self._finish(state, acts)

    async def _finish(self, state: State, acts: list[Act]) -> TurnResult:
        grounded = [a for a in acts if a.kind == ActKind.ANSWER_FROM_FACTS]
        if grounded:
            # Fixed wording around the grounded text, inserted as written. No second model pass.
            text = render_templates(acts)
            used_llm = grounded[0].data.get("source") in ("llm", "retry")
        else:
            rendered = await render_reply(
                self._llm, self._settings, acts, caller_first_name=self._first_name(state)
            )
            text, used_llm = rendered.text, rendered.used_llm

        violations = find_violations(text, state, self._store)
        if violations:
            state.record("OUTPUT_GUARD_BLOCKED", violations=violations, used_llm=used_llm)
            used_llm = False
            text = render_templates(acts)
            if find_violations(text, state, self._store):
                text = render_templates([act(ActKind.TECH_FALLBACK)])
        state.history.append(Turn(role="assistant", content=text))
        return TurnResult(
            reply=text,
            acts=tuple(acts),
            phase=state.phase,
            used_llm=used_llm,
            guard_violations=tuple(violations),
        )

    def _first_name(self, state: State) -> str | None:
        if not state.verified:
            return None
        if state.verified_as == "representative":
            name = state.rep_name
        else:
            party = self._store.get_party(state.verified_party_id or "")
            name = party.name if party else None
        parts = name.split() if name else []
        return parts[0] if parts else None

    # ---- planning ---------------------------------------------------------------------

    async def _plan(self, ctx: _Ctx) -> list[Act]:
        state, u, settings = ctx.state, ctx.u, self._settings

        # 1. Safety and explicit human requests come first, and end the automated session.
        if u.distress_or_emergency:
            self._transfer(state, "distress")
            return [
                act(ActKind.ACK_EMOTION, emotion="distressed", severity=3),
                act(ActKind.TRANSFER_HUMAN, reason="distress"),
            ]
        if u.wants_human or u.accepts_human_offer:
            self._transfer(state, "requested")
            return [act(ActKind.TRANSFER_HUMAN, reason="requested")]
        state.human_offered = False  # an offer only stays open for the very next message

        # 2. Empathy before pushing the workflow forward.
        acts: list[Act] = []
        negative = state.emotion in NEGATIVE_EMOTIONS and state.severity >= 1
        angry = state.emotion in ANGRY_EMOTIONS and state.severity >= 2
        state.frustration_streak = state.frustration_streak + 1 if angry else 0
        if negative:
            acts.append(act(ActKind.ACK_EMOTION, emotion=state.emotion, severity=state.severity))

        # 3. Scope, then 4. the phase work. Neither returns early, so a mixed message gets its
        # in-scope part handled while the rest is declined.
        acts += self._scope_acts(ctx)
        acts += await self._run_phases(ctx)

        # A model-written grounded answer already received the tone note, so a separate
        # acknowledgment would repeat it. A facts-only answer keeps the acknowledgment.
        if any(
            a.kind == ActKind.ANSWER_FROM_FACTS and a.data.get("source") in ("llm", "retry")
            for a in acts
        ):
            acts = [a for a in acts if a.kind != ActKind.ACK_EMOTION]

        if state.frustration_streak >= settings.max_frustration_streak and not any(
            a.kind == ActKind.OFFER_HUMAN for a in acts
        ):
            acts.append(self._offer_human(state, "frustration"))
        return self._one_ask(state, acts)

    def _scope_acts(self, ctx: _Ctx) -> list[Act]:
        state, u = ctx.state, ctx.u
        if u.scope in ("in_scope", "insurance_general"):
            state.oos_clear_turns += 1
            if state.oos_clear_turns >= 2:
                state.oos_strikes = 0
            if u.scope == "insurance_general":
                return [act(ActKind.ANSWER_GENERAL_INSURANCE, question=ctx.message[:300])]
            return []
        state.oos_clear_turns = 0
        if u.scope == "injection_attempt":
            state.record("INJECTION_ATTEMPT")
            return [act(ActKind.DECLINE_INSTRUCTION)]
        state.oos_strikes += 1
        if state.oos_strikes > self._settings.max_oos_strikes:
            return [self._offer_human(state, "out_of_scope")]
        return [act(ActKind.DECLINE_OOS, level=state.oos_strikes)]

    async def _run_phases(self, ctx: _Ctx) -> list[Act]:
        acts: list[Act] = []
        for _ in range(len(Phase)):
            before = ctx.state.phase
            handler = self._handlers.get(before)
            if handler is None:
                break
            outcome = await handler(ctx)
            acts += outcome.acts
            if not outcome.advance or ctx.state.phase == before:
                break
        return acts

    def _one_ask(self, state: State, acts: list[Act]) -> list[Act]:
        """A reply asks at most one thing. Keep the highest-priority question."""
        asks = [a for a in acts if a.kind in ASK_PRIORITY]
        keep = min(asks, key=lambda a: ASK_PRIORITY.index(a.kind), default=None)
        if keep is None or keep.kind != ActKind.REQUEST_FIELDS:
            state.last_expected_fields = []
        return [a for a in acts if a.kind not in ASK_PRIORITY or a is keep]

    # ---- escalation helpers -------------------------------------------------------------

    def _offer_human(self, state: State, reason: str) -> Act:
        state.human_offered = True
        state.record("HUMAN_OFFERED", reason=reason)
        return act(ActKind.OFFER_HUMAN, reason=reason)

    def _transfer(self, state: State, reason: str) -> None:
        state.human_transferred = True
        state.last_expected_fields = []
        state.record("HUMAN_TRANSFER", reason=reason)
        state.set_phase(Phase.COMPLETE, f"human transfer: {reason}")

    # ---- VERIFY_ID (strict) -------------------------------------------------------------

    async def _verify(self, ctx: _Ctx) -> _Outcome:
        state = ctx.state
        events_before = len(state.events)
        result = verify_identity(state, self._store, self._settings, self._consent)
        ran_consent = any(e.type == "CONSENT_RESULT" for e in state.events[events_before:])
        status = result.status

        if status == VerifyStatus.VERIFIED:
            acts: list[Act] = []
            if ran_consent:
                acts.append(act(ActKind.CONSENT_RESULT, status=state.consent.value))
            acts.append(act(ActKind.VERIFIED_OK))
            state.set_phase(Phase.RESOLVE_INTENT, "identity verified")
            state.last_expected_fields = []
            return _Outcome(acts, advance=True)

        if status == VerifyStatus.LOCKED:
            return _Outcome([self._offer_human(state, "verification_locked")])
        if status == VerifyStatus.REP_NOT_AUTHORIZED:
            return _Outcome([self._offer_human(state, "rep_not_authorized")])
        if status in (VerifyStatus.CONSENT_TIMED_OUT, VerifyStatus.CONSENT_DENIED):
            timed_out = status == VerifyStatus.CONSENT_TIMED_OUT
            reason = "consent_timed_out" if timed_out else "consent_denied"
            acts = []
            if ran_consent:
                acts.append(act(ActKind.CONSENT_RESULT, status=state.consent.value))
            acts.append(self._offer_human(state, reason))
            return _Outcome(acts)
        if status == VerifyStatus.NEED_REP_IDENTITY:
            state.last_expected_fields = []
            return _Outcome([act(ActKind.REQUEST_REP_IDENTITY)])
        return _Outcome(self._ask_for_more(ctx, result))

    def _ask_for_more(self, ctx: _Ctx, result: VerifyResult) -> list[Act]:
        """Not verified yet. Acknowledge, explain, persuade within limits, and ask for exactly
        what is still missing, never something the caller has already given."""
        state, u, settings = ctx.state, ctx.u, self._settings
        if not result.missing:
            return [self._offer_human(state, "verification_locked")]

        negative = state.emotion in NEGATIVE_EMOTIONS and state.severity >= 1
        wants_info = bool(u.intents) or u.asks_why_verification
        if u.refuses_verification:
            state.refusal_count += 1
            if state.refusal_count >= settings.max_verification_refusals:
                return [self._offer_human(state, "refused_verification")]

        acts: list[Act] = []
        if u.refuses_verification or wants_info or negative:
            acts.append(act(ActKind.EXPLAIN_WHY_VERIFY))
        if result.status == VerifyStatus.MISMATCH:
            acts.append(act(ActKind.VERIFY_GENERIC_MISMATCH))
        if result.provided and (
            ctx.update.captured_factors or negative or wants_info or u.refuses_verification
        ):
            acts.append(act(ActKind.ACK_FIELDS_PROVIDED, fields=list(result.provided)))
        if u.refuses_verification or u.refused_fields:
            acts.append(act(ActKind.OFFER_ALT_FIELDS, fields=list(result.missing)))
        if result.status == VerifyStatus.MISMATCH:
            need = 1
        else:
            need = max(1, settings.min_factors - len(result.provided))
        acts.append(act(ActKind.REQUEST_FIELDS, fields=list(result.missing), need=need))
        state.last_expected_fields = list(result.missing)
        return acts

    # ---- RESOLVE_INTENT (bounded) -------------------------------------------------------

    async def _resolve(self, ctx: _Ctx) -> _Outcome:
        state = ctx.state
        # Hints given after a failed attempt replace the stale ones that led nowhere.
        if state.last_resolution == "no_match":
            fresh = ctx.u.to_case_hints()
            if has_hints(fresh):
                state.case_hints = fresh

        tools = ToolGateway(self._store, state)
        cases = tools.list_cases()
        mentioned = [c.case_id for c in cases if _mentions(ctx.message, c.case_id)]
        if len(mentioned) == 1:  # the caller typed one of their own claim numbers
            state.case_hints.case_id = mentioned[0]
        resolution = resolve_case(cases, state.case_hints, state.intent_hint)
        state.last_resolution = resolution.kind
        state.record("CASE_RESOLUTION", kind=resolution.kind, candidates=len(resolution.options))

        if resolution.kind == "unique" and resolution.case is not None:
            case = resolution.case
            state.resolved_case_id = case.case_id
            state.case_record.case_id = case.case_id
            state.case_record.case_type = case.case_type
            state.case_record.status_outcome = case.status
            state.set_phase(Phase.PROCESS_CASE, "case resolved")
            state.last_expected_fields = []
            return _Outcome([act(ActKind.CONFIRM_CLAIM, case=case_option(case))], advance=True)
        if resolution.kind == "no_claims":
            return _Outcome([act(ActKind.NO_CLAIMS_FOUND), self._offer_human(state, "no_claims")])
        state.last_expected_fields = []
        return _Outcome(
            [
                act(
                    ActKind.ASK_DISAMBIGUATION,
                    options=[case_option(c) for c in resolution.options],
                    none_matched=resolution.kind == "no_match",
                )
            ]
        )

    # ---- PROCESS_CASE (grounded) --------------------------------------------------------

    async def _process(self, ctx: _Ctx) -> _Outcome:
        """Answer from the facts of the resolved claim.

        The claim is re-fetched through the ownership-checked gateway on every turn. The model
        sees the facts and the caller's question with identity values blanked out."""
        state, u = ctx.state, ctx.u
        case = ToolGateway(self._store, state).get_case(state.resolved_case_id or "")
        if case is None:  # should not happen; fail closed rather than guess
            return _Outcome([act(ActKind.TECH_FALLBACK, reason="case_unavailable")])

        # Interim: a plain goodbye. Step 7 replaces this with the real POST_PROCESS phase.
        asking = u.intents or u.followup_topics or u.claim_switch_request
        if u.user_done and not asking:
            return _Outcome([act(ActKind.GOODBYE)])

        # A request about another claim goes back to resolution (switches happen at most once
        # per turn, and the number of them per conversation is capped).
        if ctx.start_phase == Phase.PROCESS_CASE and not ctx.switched:
            target = self._switch_target(ctx, case)
            if target is not None:
                return self._switch_claim(ctx, target)
        just_arrived = ctx.start_phase != Phase.PROCESS_CASE or ctx.switched

        intents = list(u.intents)
        shown = redact(ctx.message, self._policy_prefixes)
        question: str | None = shown  # also used to match the follow-up rules
        if intents or u.followup_topics:
            asked = shown
        elif just_arrived and state.intent_hint:
            # Just reached the claim, and the caller had said what they wanted earlier.
            intents = [state.intent_hint]
            general = _INTENT_QUESTIONS["general_claim_question"]
            asked = _INTENT_QUESTIONS.get(state.intent_hint, general)
            question = None
        elif not just_arrived and u.fallback_reason is not None and not u.user_done:
            asked = shown  # the LLM is down, so treat the message as a question
        else:
            return _Outcome([act(ActKind.ASK_WHAT_NEEDED)])

        context = build_case_context(
            case,
            guidelines=self._store.guidelines,
            claim_schema=self._store.claim_schema,
            clock=self._clock,
            question=question,
            intents=intents,
            topics=u.followup_topics,
        )
        answer = await generate_answer(
            self._llm,
            self._settings,
            context=context,
            question=asked,
            intents=intents,
            known_documents=self._vocabulary,
            caller_first_name=self._first_name(state),
            tone=tone_note(state.emotion, state.severity),
        )
        self._record_answer(state, case, intents, context.followup_topics, answer)
        state.intent_hint = None  # the remembered request has now been answered
        return _Outcome(
            [
                act(
                    ActKind.ANSWER_FROM_FACTS,
                    reply=answer.reply,
                    facts_used=list(answer.facts_used),
                    source=answer.source,
                    fallback_reason=answer.fallback_reason,
                ),
                act(ActKind.ASK_ANYTHING_ELSE),
            ]
        )

    def _switch_target(self, ctx: _Ctx, current: Case) -> CaseHints | None:
        """The description of another claim the caller wants, or None if they are not asking
        for one. Describing the claim that is already open is not a switch."""
        u, message = ctx.u, ctx.message
        cases = ToolGateway(self._store, ctx.state).list_cases()
        other = [
            c.case_id
            for c in cases
            if c.case_id != current.case_id and _mentions(message, c.case_id)
        ]
        asked = bool(u.claim_switch_request) or bool(_SWITCH_PHRASES.search(message))
        if not asked and not other:
            return None
        fresh = u.to_case_hints()
        if len(other) == 1:
            fresh.case_id = other[0]
        if has_hints(fresh):
            match = resolve_case(cases, fresh)
            if match.kind == "unique" and match.case is not None:
                if match.case.case_id == current.case_id:
                    return None
        return fresh

    def _switch_claim(self, ctx: _Ctx, fresh: CaseHints) -> _Outcome:
        """Archive the current claim's notes, forget its hints, and resolve the new request."""
        state = ctx.state
        state.case_loops += 1
        if state.case_loops > self._settings.max_case_loops:
            return _Outcome([self._offer_human(state, "case_loop_limit")])
        state.record("CLAIM_SWITCH", count=state.case_loops)
        if state.case_record.case_id:
            state.closed_cases.append(state.case_record)
        state.case_record = CaseRecord()
        state.resolved_case_id = None
        state.last_resolution = None
        state.case_hints = fresh  # the old hints described the old claim
        state.intent_hint = ctx.u.intents[0] if ctx.u.intents else None
        ctx.switched = True
        state.set_phase(Phase.RESOLVE_INTENT, "caller asked about another claim")
        return _Outcome([], advance=True)

    def _record_answer(
        self,
        state: State,
        case: Case,
        intents: list[str],
        followup_topics: tuple[str, ...],
        answer: ProcessAnswer,
    ) -> None:
        """Keep what was discussed and which facts were cited, for the summary email later."""
        record = state.case_record
        topics = [_INTENT_LABELS.get(i, i) for i in intents]
        topics += [topic.replace("_", " ") for topic in followup_topics]
        for topic in topics:
            if topic not in record.topics_discussed:
                record.topics_discussed.append(topic)
        for fact_id in answer.facts_used:
            if fact_id not in record.facts_used:
                record.facts_used.append(fact_id)
        record.documents_needed = list(case.documents_needed)
        record.appeal_deadline = case.appeal_deadline
        state.record(
            "ANSWER_GENERATED",
            source=answer.source,
            cited=len(answer.facts_used),
            reason=answer.fallback_reason,
            problems=[v.kind for v in answer.violations],
        )

    # ---- POST_PROCESS: built in a later step ---------------------------------------------

    async def _post(self, ctx: _Ctx) -> _Outcome:
        if ctx.start_phase == Phase.POST_PROCESS:
            return _Outcome([act(ActKind.TECH_FALLBACK, reason="post_process_not_built")])
        return _Outcome([])
