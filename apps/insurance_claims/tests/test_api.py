import asyncio
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
from agent.clock import FixedClock
from agent.config import Settings
from agent.controller import SopAgent, TurnResult
from agent.llm.fake import ScriptedLLM
from agent.state import ConsentState
from agent.tools import ToolGateway
from agent.understanding import MAX_MESSAGE_CHARS
from api.app import MAX_BODY_BYTES, create_app
from api.sessions import GREETING, TURN_LIMIT_REPLY, SessionLimits

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

MARGARET_MSG = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my "
    "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472."
)
MARGARET_LLM = {
    "full_name": "Margaret Chen",
    "caller_role": "policyholder",
    "intents": ["denial_question"],
    "hint_case_type": "healthcare",
    "hint_status": "denied",
    "hint_month": 1,
}
GOOD = {
    "reply": (
        "Your claim was denied because the review file did not include the pathology report "
        "and the treating provider office note."
    ),
    "facts_used": ["case.status", "case.denial_reason"],
}
REP_MSG = (
    "I'm David Chen, Margaret's son. Her DOB is 1985-03-15, SSN last four 4472, "
    "and her phone is 650-521-2836."
)
REP_LLM = {"caller_role": "representative", "rep_name": "David Chen", "rep_relationship": "son"}
RAW_IDENTITY_VALUES = (
    "1985-03-15",
    "4472",
    "6505212836",
    "650-521-2836",
    "margaret@email.com",
    "Margaret Chen",
    "POL-9921",
)


# ---- helpers -------------------------------------------------------------------------------


@pytest.fixture
def make_app(store):
    def _make(*, inspector=False, llm=None, limits=None, now=None, static_dir=None, **settings):
        return create_app(
            Settings(enable_debug_inspector=inspector, **settings),
            llm=llm or ScriptedLLM(),
            clock=FixedClock(date(2026, 3, 5)),
            store=store,
            limits=limits,
            now=now or time.monotonic,
            static_dir=static_dir or FIXTURES / "no-ui-build-here",
        )

    return _make


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def start(c, **body):
    response = await c.post("/api/session", json=body)
    assert response.status_code == 200
    return response.json()["session_id"]


async def say(c, sid, message):
    response = await c.post("/api/chat", json={"session_id": sid, "message": message})
    assert response.status_code == 200, response.text
    return response.json()


async def debug(c, sid):
    response = await c.get(f"/api/session/{sid}/debug")
    assert response.status_code == 200
    return response.json()


# ---- health ----------------------------------------------------------------------------------


async def test_health_reports_llm_configuration_without_exposing_the_key(make_app):
    async with client(make_app()) as c:
        assert (await c.get("/api/health")).json() == {"status": "ok", "llm_configured": False}
    async with client(make_app(llm_api_key="sk-secret-value")) as c:
        response = await c.get("/api/health")
        assert response.json() == {"status": "ok", "llm_configured": True}
        assert "sk-secret-value" not in response.text


# ---- the greeting and session creation ------------------------------------------------------


async def test_a_new_session_gets_an_unguessable_id_and_the_fixed_greeting(make_app):
    async with client(make_app()) as c:
        response = await c.post("/api/session")
        body = response.json()
        assert response.status_code == 200
        assert set(body) == {"session_id", "greeting"} and body["greeting"] == GREETING
        assert len(body["session_id"]) >= 20
        ids = {await start(c) for _ in range(30)}
        assert len(ids) == 30 and body["session_id"] not in ids


def test_the_greeting_explains_the_three_factor_rule_and_the_flexible_choices():
    text = GREETING.lower()
    for phrase in (
        "claim status, denials, documents, and next steps",
        "before i can discuss claim details",
        "verify your identity",
        "full name",
        "any two of the following",
        "date of birth",
        "phone number",
        "email",
        "last four digits of your ssn or national id",
        "policy number if you have it",
    ):
        assert phrase in text, phrase
    # Policy number is optional and comes last, never the headline request.
    assert text.index("any two of the following") < text.index("policy number")


def _leaves(node, skip=("id_type", "relationship")):
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in skip:
                yield from _leaves(value, skip)
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value, skip)
    else:
        yield str(node)


def test_the_greeting_contains_nothing_derived_from_the_fixtures():
    secrets = set()
    for name in ("policyholders.json", "representatives.json"):
        for leaf in _leaves(json.loads((FIXTURES / name).read_text())):
            if len(leaf) >= 4:
                secrets.add(leaf.lower())
            if "@" not in leaf and not re.search(r"\d", leaf):  # names, not emails or ids
                secrets.update(t.lower() for t in re.split(r"\W+", leaf) if len(t) >= 4)
    raw_claims = (FIXTURES / "claims.json").read_text()
    secrets.update(m.lower() for m in re.findall(r"\b[A-Z]{2,}-\d{3,}\b", raw_claims))

    greeting = GREETING.lower()
    assert secrets, "the fixture scan found nothing, so this test would prove nothing"
    assert [s for s in secrets if s in greeting] == []
    assert not re.search(r"\d", GREETING)  # no ids, dates, phone numbers or amounts at all


async def test_creating_a_session_never_touches_claim_tools(make_app, store, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("claim data was touched while creating a session")

    monkeypatch.setattr(ToolGateway, "list_cases", forbidden)
    monkeypatch.setattr(ToolGateway, "get_case", forbidden)
    monkeypatch.setattr(store, "cases_for_party", forbidden)
    monkeypatch.setattr(store, "get_case", forbidden)

    async with client(make_app(inspector=True)) as c:
        sid = await start(c)
        view = await debug(c, sid)
    assert view["phase"] == "VERIFY_ID" and view["verification"]["verified"] is False
    assert view["tool_calls"] == [] and view["events"] == []


# ---- chat ------------------------------------------------------------------------------------


async def test_the_customer_response_is_only_a_reply_and_an_ended_flag(make_app):
    async with client(make_app()) as c:
        sid = await start(c)
        body = await say(c, sid, "hello there")  # no LLM script: the fallback path still replies
    assert set(body) == {"reply", "ended"} and body["ended"] is False and body["reply"]


async def test_margaret_demo_end_to_end_over_http_including_the_email(make_app):
    llm = ScriptedLLM()
    async with client(make_app(inspector=True, llm=llm)) as c:
        sid = await start(c)

        llm.queue_structured(MARGARET_LLM, GOOD)
        first = await say(c, sid, MARGARET_MSG)
        assert "pathology report" in first["reply"] and first["ended"] is False

        llm.queue_structured({"user_done": True})
        offer = await say(c, sid, "no thanks, that's all")
        assert "m***@email.com" in offer["reply"] and "margaret@email.com" not in offer["reply"]

        llm.queue_structured({"email_consent": "yes"})
        sent = await say(c, sid, "yes please")
        assert sent["reply"].startswith("I've sent the summary to m***@email.com.")
        assert sent["ended"] is True

        view = await debug(c, sid)
        assert view["phase"] == "COMPLETE" and view["email"]["state"] == "sent"
        (email,) = view["outbox"]
        assert email["to"] == "m***@email.com" and "Claim CL-2048" in email["body"]
        assert "margaret@email.com" not in json.dumps(view)


async def test_a_message_after_the_session_ends_is_answered_as_ended(make_app):
    llm = ScriptedLLM()
    async with client(make_app(llm=llm)) as c:
        sid = await start(c)
        llm.queue_structured(MARGARET_LLM, GOOD)
        await say(c, sid, MARGARET_MSG)
        llm.queue_structured({"user_done": True})
        await say(c, sid, "that's all")
        llm.queue_structured({"email_consent": "no"})
        assert (await say(c, sid, "no thanks"))["ended"] is True
        again = await say(c, sid, "wait, one more thing")
    assert again["ended"] is True and again["reply"]


# ---- input checks -----------------------------------------------------------------------------


async def test_an_unknown_session_is_a_404(make_app):
    async with client(make_app()) as c:
        response = await c.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "x", "message": ""},
        {"session_id": "x", "message": "   \n\t "},
        {"session_id": "x", "message": "a" * (MAX_MESSAGE_CHARS + 1)},
        {"session_id": "", "message": "hi"},
        {"message": "hi"},
        {"session_id": "x"},
    ],
)
async def test_bad_chat_payloads_are_rejected_before_the_agent_runs(make_app, payload):
    llm = ScriptedLLM()
    async with client(make_app(llm=llm)) as c:
        response = await c.post("/api/chat", json=payload)
    assert response.status_code == 422 and llm.calls == []


async def test_an_oversized_request_body_is_refused(make_app):
    async with client(make_app()) as c:
        response = await c.post(
            "/api/chat", json={"session_id": "x", "message": "a" * (MAX_BODY_BYTES + 1)}
        )
    assert response.status_code == 413


# ---- the debug inspector ------------------------------------------------------------------------


async def test_debug_and_api_docs_do_not_exist_unless_the_inspector_is_on(make_app):
    async with client(make_app(inspector=False)) as c:
        sid = await start(c)
        assert (await c.get(f"/api/session/{sid}/debug")).status_code == 404
        assert (await c.get("/api/docs")).status_code == 404
        assert (await c.get("/api/openapi.json")).status_code == 404
    async with client(make_app(inspector=True)) as c:
        assert (await c.get("/api/session/unknown/debug")).status_code == 404


async def test_the_debug_view_masks_every_identity_value_and_shows_the_workings(make_app):
    llm = ScriptedLLM()
    async with client(make_app(inspector=True, llm=llm)) as c:
        sid = await start(c)
        llm.queue_structured(MARGARET_LLM, GOOD)
        await say(c, sid, MARGARET_MSG)
        response = await c.get(f"/api/session/{sid}/debug")

    view = response.json()
    for raw in RAW_IDENTITY_VALUES:
        assert raw not in response.text, raw
    assert view["phase"] == "PROCESS_CASE" and view["verification"]["verified"] is True
    assert view["verification"]["factors"]["dob"] == "****-**-**"
    assert view["verification"]["factors"]["id_last4"] == "****"
    assert view["case"]["resolved_case_id"] == "CL-2048"
    kinds = [a["kind"] for a in view["last_turn"]["acts"]]
    assert "ANSWER_FROM_FACTS" in kinds
    assert {call["data"]["tool"] for call in view["tool_calls"]} >= {"list_cases", "get_case"}
    assert "history" not in view and view["history_length"] >= 3


async def test_the_scenario_hook_is_honored_only_with_the_inspector_on(make_app):
    llm = ScriptedLLM()
    on = make_app(inspector=True, llm=llm)
    async with client(on) as c:
        sid = await start(c, consent_scenario="timeout")
        llm.queue_structured(REP_LLM)
        await say(c, sid, REP_MSG)
        assert (await debug(c, sid))["consent"]["state"] == ConsentState.TIMED_OUT.value

    llm = ScriptedLLM()
    off = make_app(inspector=False, llm=llm)
    async with client(off) as c:
        sid = await start(c, consent_scenario="timeout")  # ignored: the default scenario runs
        llm.queue_structured(REP_LLM)
        await say(c, sid, REP_MSG)
    session = off.state.sessions.get(sid, touch=False)
    assert session.state.consent == ConsentState.APPROVED


async def test_an_unknown_scenario_is_rejected_when_the_inspector_is_on(make_app):
    async with client(make_app(inspector=True)) as c:
        response = await c.post("/api/session", json={"consent_scenario": "does-not-exist"})
    assert response.status_code == 400


# ---- isolation, locking and limits ---------------------------------------------------------------


async def test_sessions_and_outboxes_are_isolated(make_app):
    llm = ScriptedLLM()
    async with client(make_app(inspector=True, llm=llm)) as c:
        a, b = await start(c), await start(c)
        llm.queue_structured(MARGARET_LLM, GOOD)
        await say(c, a, MARGARET_MSG)
        llm.queue_structured({"user_done": True})
        await say(c, a, "that's all")
        llm.queue_structured({"email_consent": "yes"})
        await say(c, a, "yes please")

        view_a, view_b = await debug(c, a), await debug(c, b)
    assert len(view_a["outbox"]) == 1 and view_b["outbox"] == []
    assert view_b["phase"] == "VERIFY_ID" and view_b["verification"]["verified"] is False
    assert view_b["case"]["resolved_case_id"] is None and view_b["tool_calls"] == []


def _slow_handle(monkeypatch):
    stats = {"active": 0, "max_active": 0, "calls": 0}

    async def handle(self, state, message):
        stats["calls"] += 1
        stats["active"] += 1
        stats["max_active"] = max(stats["max_active"], stats["active"])
        await asyncio.sleep(0.02)
        stats["active"] -= 1
        return TurnResult(reply="ok", acts=(), phase=state.phase, used_llm=False)

    monkeypatch.setattr(SopAgent, "handle", handle)
    return stats


async def test_turns_in_one_session_run_one_at_a_time(make_app, monkeypatch):
    stats = _slow_handle(monkeypatch)
    async with client(make_app()) as c:
        sid = await start(c)
        await asyncio.gather(*(say(c, sid, f"message {i}") for i in range(4)))
    assert stats["calls"] == 4 and stats["max_active"] == 1


async def test_different_sessions_do_not_block_each_other(make_app, monkeypatch):
    stats = _slow_handle(monkeypatch)
    async with client(make_app()) as c:
        a, b = await start(c), await start(c)
        await asyncio.gather(say(c, a, "hi"), say(c, b, "hi"))
    assert stats["max_active"] == 2


async def test_an_unhandled_error_is_a_generic_500_that_leaks_nothing(
    make_app, monkeypatch, caplog
):
    async def explode(self, state, message):
        raise RuntimeError("secret detail: SSN 4472 for Margaret Chen")

    monkeypatch.setattr(SopAgent, "handle", explode)
    caplog.set_level(logging.INFO)
    async with client(make_app()) as c:
        sid = await start(c)
        response = await c.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert response.status_code == 500 and response.json() == {"detail": "internal error"}
    assert "4472" not in response.text and "Margaret" not in response.text
    assert "4472" not in caplog.text and "Margaret" not in caplog.text
    assert "RuntimeError" in caplog.text  # the kind of failure is logged, nothing more


async def test_logs_name_the_phase_and_acts_but_never_the_message(make_app, caplog):
    llm = ScriptedLLM()
    caplog.set_level(logging.INFO)
    async with client(make_app(llm=llm)) as c:
        sid = await start(c)
        llm.queue_structured(MARGARET_LLM, GOOD)
        await say(c, sid, MARGARET_MSG)
    assert "phase=PROCESS_CASE" in caplog.text and "ANSWER_FROM_FACTS" in caplog.text
    for raw in (*RAW_IDENTITY_VALUES, "pathology", "Chen", "denied"):
        assert raw not in caplog.text, raw


async def _status(c, sid):
    response = await c.post("/api/chat", json={"session_id": sid, "message": "hi"})
    return response.status_code


async def test_idle_sessions_expire(make_app):
    clock = {"t": 1000.0}
    app = make_app(limits=SessionLimits(idle_seconds=60), now=lambda: clock["t"])
    async with client(app) as c:
        sid = await start(c)
        clock["t"] += 30
        assert await _status(c, sid) == 200
        clock["t"] += 61  # idle longer than the limit since the last message
        assert await _status(c, sid) == 404
        await start(c)
    assert len(app.state.sessions) == 1


async def test_the_number_of_live_sessions_is_capped(make_app):
    clock = {"t": 0.0}
    app = make_app(limits=SessionLimits(idle_seconds=60, max_sessions=2), now=lambda: clock["t"])
    async with client(app) as c:
        await start(c)
        await start(c)
        assert (await c.post("/api/session")).status_code == 503
        clock["t"] += 61  # the old ones expire, so there is room again
        assert (await c.post("/api/session")).status_code == 200


async def test_a_session_has_a_turn_limit(make_app, monkeypatch):
    stats = _slow_handle(monkeypatch)
    async with client(make_app(limits=SessionLimits(max_turns=2))) as c:
        sid = await start(c)
        await say(c, sid, "one")
        await say(c, sid, "two")
        third = await say(c, sid, "three")
    assert third == {"reply": TURN_LIMIT_REPLY, "ended": True} and stats["calls"] == 2


# ---- serving the UI ---------------------------------------------------------------


async def test_the_ui_is_served_only_when_a_build_exists(make_app, tmp_path):
    build = tmp_path / "dist"
    build.mkdir()
    (build / "index.html").write_text("<html><body>claims ui marker</body></html>")

    async with client(make_app(static_dir=build)) as c:
        page = await c.get("/")
        assert page.status_code == 200 and "claims ui marker" in page.text
        assert (await c.get("/api/health")).status_code == 200  # the API is not shadowed
        assert (await c.post("/api/session")).status_code == 200
    async with client(make_app(static_dir=tmp_path / "missing")) as c:
        assert (await c.get("/")).status_code == 404
        assert (await c.get("/api/health")).status_code == 200
