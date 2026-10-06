"""Live check of the LLM setup. Run from the repo root: python scripts/smoke_llm.py

Reads .env, makes one real plain-text call and one real extraction call, and prints the
results, so the API key, model names and network are verified before anything depends on them.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "insurance_claims"))

from agent.config import Settings  # noqa: E402
from agent.llm.client import LLMError  # noqa: E402
from agent.llm.factory import build_llm  # noqa: E402
from agent.state import State  # noqa: E402
from agent.understanding import understand_turn  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

MESSAGE = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my "
    "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472."
)


async def main() -> int:
    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    if not settings.llm_configured:
        print("LLM_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 1

    llm = build_llm(settings)
    try:
        started = time.perf_counter()
        reply = await llm.generate(
            model=settings.llm_model,
            system="Reply with the single word OK.",
            user="ping",
            max_tokens=20,
        )
        elapsed = time.perf_counter() - started
        print(f"[{settings.llm_model}] generate -> {reply!r} ({elapsed:.1f}s)")

        started = time.perf_counter()
        state = State(session_id="smoke")
        result = await understand_turn(llm, settings, state, MESSAGE, policy_prefixes=("POL",))
        elapsed = time.perf_counter() - started
        print(f"[{settings.llm_model_fast}] extraction ({elapsed:.1f}s):")
        print(result.model_dump_json(exclude_defaults=True, indent=2))
        if not result.llm_used:
            print(f"Extraction fell back to the pre-pass: {result.fallback_reason}")
            return 1
    except LLMError as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 1
    print("LLM setup OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
