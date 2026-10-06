# One image, one port: FastAPI serves the API and the built UI.
#
#   docker build -t goaly-claims-agent .
#   docker run --rm -p 127.0.0.1:8000:8000 --env-file .env goaly-claims-agent
#
# No secrets are baked in: configuration (LLM key, inspector, demo date) arrives at run time.
# Without any configuration the app still starts, with the inspector off and the LLM in its
# built-in fallback mode.

# ---- 1. Build the UI ------------------------------------------------------------------
FROM node:22-slim AS ui-build
WORKDIR /ui
COPY apps/insurance_claims/ui/package.json apps/insurance_claims/ui/package-lock.json ./
RUN npm ci
COPY apps/insurance_claims/ui/ ./
RUN npm run build

# ---- 2. Python base: runtime dependencies only ------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---- 3. Tests: a build target only, never part of the shipped image ---------------------
#   docker build --target test .   fails the build if any test fails on this Python version.
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY apps/insurance_claims/agent apps/insurance_claims/agent
COPY apps/insurance_claims/api apps/insurance_claims/api
COPY apps/insurance_claims/fixtures apps/insurance_claims/fixtures
COPY apps/insurance_claims/tests apps/insurance_claims/tests
RUN python -m pytest -q

# ---- 4. Runtime (the default target, so it must stay last) -------------------------------
FROM base AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# Explicit copies only: the image holds the agent, the API, the fixtures and the built UI.
COPY apps/insurance_claims/agent apps/insurance_claims/agent
COPY apps/insurance_claims/api apps/insurance_claims/api
COPY apps/insurance_claims/fixtures apps/insurance_claims/fixtures
COPY --from=ui-build /ui/dist apps/insurance_claims/ui/dist

USER app
EXPOSE 8000

# Python's standard library, so the image needs no curl.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "api.main:app", "--app-dir", "apps/insurance_claims", "--host", "0.0.0.0", "--port", "8000"]
