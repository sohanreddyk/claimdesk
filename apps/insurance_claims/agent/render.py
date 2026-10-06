"""Renderer: turns the controller's dialogue acts into one natural reply.

The LLM phrases; the acts decide. If the LLM fails or returns something unusable, the
deterministic templates produce the reply, so the agent is never stuck.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .acts import Act, ActKind, describe
from .config import Settings
from .llm.client import LLMClient, LLMError
from .llm.render_prompts import RENDER_SYSTEM, build_render_user
from .templates import render_templates

MAX_REPLY_CHARS = 1500


@dataclass(frozen=True)
class Rendered:
    text: str
    used_llm: bool
    fallback_reason: str | None = None


def _clean(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


async def render_reply(
    llm: LLMClient,
    settings: Settings,
    acts: Sequence[Act],
    *,
    caller_first_name: str | None = None,
) -> Rendered:
    acts = list(acts) or [Act(ActKind.TECH_FALLBACK)]
    prompt = build_render_user(
        instructions=[describe(a) for a in acts], caller_first_name=caller_first_name
    )
    try:
        text = _clean(
            await llm.generate(
                model=settings.llm_model, system=RENDER_SYSTEM, user=prompt, max_tokens=500
            )
        )
    except LLMError as exc:
        return Rendered(render_templates(acts), False, type(exc).__name__)
    if not text or len(text) > MAX_REPLY_CHARS:
        return Rendered(render_templates(acts), False, "UnusableOutput")
    return Rendered(text, True)
