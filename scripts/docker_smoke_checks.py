"""Checks run INSIDE the packaged container, against the live app (standard library only).

Used by scripts/docker_smoke.sh:

    docker exec -i <container> python - <off|on> < scripts/docker_smoke_checks.py

"off" is the default image (inspector disabled); "on" is a container started with
ENABLE_DEBUG_INSPECTOR=true. Exits non-zero on the first failed check.
"""

import json
import re
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
# Internals that must never appear in a customer-facing chat response.
FORBIDDEN_KEYS = ("phase", "acts", "state", "matched_factors", "tool_calls")


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, response.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Content-Type", ""), err.read().decode()


def check(condition, message):
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)
    print(f"ok: {message}")


def main(mode):
    inspector_on = mode == "on"

    status, content_type, page = call("GET", "/")
    check(
        status == 200 and "text/html" in content_type and 'id="root"' in page,
        "the UI is served at /",
    )

    status, _, raw = call("GET", "/api/health")
    check(
        status == 200 and json.loads(raw) == {"status": "ok", "llm_configured": False},
        "health answers, and no LLM key is configured in this container",
    )

    status, _, raw = call("POST", "/api/session", {})
    session = json.loads(raw)
    check(
        status == 200 and set(session) == {"session_id", "greeting"},
        "a session opens with only an id and a greeting",
    )
    greeting = session["greeting"]
    check(
        "verify your identity" in greeting and not re.search(r"\d", greeting),
        "the greeting asks for verification and contains no customer data",
    )
    session_id = session["session_id"]

    status, _, raw = call("POST", "/api/chat", {"session_id": session_id, "message": "hello"})
    reply = json.loads(raw)
    check(
        status == 200 and set(reply) == {"reply", "ended"},
        "chat returns only reply and ended",
    )
    check(
        isinstance(reply["reply"], str) and reply["reply"] and reply["ended"] is False,
        "the reply is text and the conversation is still open",
    )
    leaked = [word for word in FORBIDDEN_KEYS if word in reply or f'"{word}"' in raw]
    check(not leaked, "chat exposes no phase, acts, state, matched_factors or tool_calls")

    status, _, _ = call("POST", "/api/chat", {"session_id": "no-such-session", "message": "hi"})
    check(status == 404, "an unknown session is a 404")

    status, _, _ = call("POST", "/api/session", {"consent_scenario": "no-such-scenario"})
    check(
        status == (400 if inspector_on else 200),
        "the consent scenario switch is honored only when the inspector is on",
    )

    debug_status, _, raw = call("GET", f"/api/session/{session_id}/debug")
    docs_status, _, _ = call("GET", "/api/docs")
    if inspector_on:
        view = json.loads(raw)
        check(debug_status == 200 and view["phase"] == "VERIFY_ID", "the inspector answers")
        check(view["tool_calls"] == [], "an unverified session has touched no claim data")
        check(docs_status == 200, "the API docs exist when the inspector is on")
    else:
        check(debug_status == 404, "the inspector is off by default: debug is a 404")
        check(docs_status == 404, "the API docs are off by default")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "off")
