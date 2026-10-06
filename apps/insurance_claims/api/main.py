"""Production entry point: `uvicorn api.main:app --app-dir apps/insurance_claims`.

Reads `.env` from the repository root (real environment variables win over the file). Kept
separate from `create_app` so tests never depend on a developer's local `.env`.
"""

from pathlib import Path

from dotenv import load_dotenv

from .app import create_app

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

app = create_app()
