"""The FastAPI app. `create_app` takes everything it depends on as arguments, so tests inject a
scripted LLM, a fixed clock and a fake time source; production wiring comes from the environment.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.clock import Clock, clock_from_settings
from agent.config import Settings
from agent.fixtures import FixtureStore
from agent.llm.client import LLMClient
from agent.llm.factory import build_llm
from agent.state import Phase
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .debug import debug_view
from .schemas import ChatRequest, ChatResponse, CreateSessionRequest, CreateSessionResponse
from .sessions import (
    GREETING,
    TURN_LIMIT_REPLY,
    SessionLimitError,
    SessionLimits,
    SessionStore,
    UnknownScenarioError,
)

log = logging.getLogger("claims.api")

DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "dist"
MAX_BODY_BYTES = 32 * 1024  # a 4,000-character message is at most ~24 KB even fully JSON-escaped


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    clock: Clock | None = None,
    store: FixtureStore | None = None,
    limits: SessionLimits | None = None,
    static_dir: Path | None = None,
    now: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or Settings.from_env()
    inspector = settings.enable_debug_inspector
    sessions = SessionStore(
        store=store or FixtureStore.load(settings.fixtures_dir),
        settings=settings,
        llm=llm or build_llm(settings),
        clock=clock or clock_from_settings(settings),
        limits=limits or SessionLimits(),
        now=now,
    )

    # API docs are an evaluator convenience, so they follow the inspector switch.
    app = FastAPI(
        title="Insurance claims SOP agent",
        docs_url="/api/docs" if inspector else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if inspector else None,
    )
    app.state.sessions = sessions

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next: Callable[..., Any]) -> Any:
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "llm_configured": settings.llm_configured}

    @app.post("/api/session", response_model=CreateSessionResponse)
    async def create_session(body: CreateSessionRequest | None = None) -> CreateSessionResponse:
        # The scenario switch is a test hook: honored only with the inspector on.
        scenario = body.consent_scenario if body and inspector else None
        try:
            session_id, _ = sessions.create(scenario)
        except UnknownScenarioError:
            raise HTTPException(status_code=400, detail="unknown consent scenario") from None
        except SessionLimitError:
            raise HTTPException(status_code=503, detail="too many active sessions") from None
        return CreateSessionResponse(session_id=session_id, greeting=GREETING)

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest) -> ChatResponse:
        session = sessions.get(body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        async with session.lock:  # a double-click can never interleave two turns
            over_limit = session.turns >= sessions.limits.max_turns
            if over_limit and session.state.phase != Phase.COMPLETE:
                session.turn_limit_reached = True
            if session.turn_limit_reached:
                return ChatResponse(reply=TURN_LIMIT_REPLY, ended=True)
            session.turns += 1
            try:
                result = await session.agent.handle(session.state, body.message)
            except Exception as exc:
                # Log the kind of failure only: messages and exception text can hold caller data.
                log.error("turn failed id=%s error=%s", body.session_id[:8], type(exc).__name__)
                raise HTTPException(status_code=500, detail="internal error") from None
            session.last_result = result
            log.info(
                "turn id=%s phase=%s acts=%s",
                body.session_id[:8],
                result.phase.value,
                ",".join(a.kind.value for a in result.acts),
            )
            return ChatResponse(reply=result.reply, ended=session.ended)

    @app.get("/api/session/{session_id}/debug")
    async def debug(session_id: str) -> dict[str, Any]:
        if not inspector:
            raise HTTPException(status_code=404, detail="not found")
        session = sessions.get(session_id, touch=False)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        async with session.lock:
            return debug_view(session)

    # Registered last so it never shadows an API route.
    dist = static_dir if static_dir is not None else DEFAULT_STATIC_DIR
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app
