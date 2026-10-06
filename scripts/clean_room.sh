#!/usr/bin/env bash
# Prove the submission works from nothing, the way an evaluator would use it: unzip it into a
# fresh folder, check what is (and is not) inside, build it with Docker, and exercise it.
#
#   bash scripts/clean_room.sh [path/to/submission.zip]    keyless run + automated API checks
#   ENV_FILE=.env bash scripts/clean_room.sh               use your real key for a live click-through
#   NO_PAUSE=1 bash scripts/clean_room.sh                  do not wait for Enter at the end
#
# Needs Docker, curl, unzip and git. It uses port 8000 (the compose file's port), so stop anything
# already running there first. Everything it creates is removed when it finishes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-$ROOT/../$(basename "$ROOT")-submission.zip}"
PROJECT="goaly-cleanroom"
KEY_PATTERN='sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{32,}'

step() { printf '\n==> %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

[ -f "$ZIP" ] || fail "no zip at $ZIP (build it first with: bash scripts/package.sh)"

if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then
  fail "something is already listening on port 8000. Stop it (docker compose down, or Ctrl+C a running server) and retry."
fi

WORK="$(mktemp -d)"
DIR=""
cleanup() {
  if [ -n "$DIR" ] && [ -d "$DIR" ]; then
    (cd "$DIR" && docker compose -p "$PROJECT" down -v --remove-orphans >/dev/null 2>&1) || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

step "Unpacking $(basename "$ZIP") into a fresh folder"
unzip -q "$ZIP" -d "$WORK"
DIR="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$DIR" ] || fail "the zip is empty"
ok "unpacked to a temporary folder"

step "What is inside"
for path in README.md Dockerfile docker-compose.yml .env.example .dockerignore requirements.txt \
            requirements-dev.txt pyproject.toml docs/ARCHITECTURE.md docs/requirements-matrix.md \
            scripts/package.sh scripts/docker_smoke.sh scripts/check_all.sh \
            apps/insurance_claims/ui/package-lock.json apps/insurance_claims/fixtures/claims.json; do
  [ -e "$DIR/$path" ] || fail "missing from the submission: $path"
done
ok "the files an evaluator needs are all there"

for path in .env apps/insurance_claims/ui/node_modules apps/insurance_claims/ui/dist .venv; do
  [ ! -e "$DIR/$path" ] || fail "should not be in the submission: $path"
done
ok "no .env, node_modules, .venv or build output"

if grep -rEIl "$KEY_PATTERN" "$DIR" --exclude-dir=.git >/dev/null 2>&1; then
  fail "something that looks like an API key is in the working files"
fi
# Redirect instead of -q so the left side of the pipe is never cut off early (pipefail).
if git -C "$DIR" log --all -p | grep -E "$KEY_PATTERN" >/dev/null; then
  fail "something that looks like an API key is in the git history"
fi
ok "no API-key-like strings in the files or in any commit"

if [ -d "$DIR/.git" ]; then
  if [ -n "$(git -C "$DIR" status --short)" ]; then
    git -C "$DIR" status --short >&2
    fail "the zip does not match the last commit (uncommitted or stray files, listed above)"
  fi
  ok "the zip is exactly the last commit ($(git -C "$DIR" rev-list --count HEAD) commits of history)"
else
  fail "no .git folder in the zip, so the commit history is missing"
fi

KEYLESS=1
if [ -n "${ENV_FILE:-}" ]; then
  [ -f "$ENV_FILE" ] || fail "ENV_FILE=$ENV_FILE does not exist"
  cp "$ENV_FILE" "$DIR/.env"
  KEYLESS=0
  ok "using $ENV_FILE (a real key: the API checks are skipped, you click through instead)"
else
  ok "no .env: this is the first-run experience before a key is added"
fi

step "Building and starting it with docker compose"
(cd "$DIR" && docker compose -p "$PROJECT" up --build -d)

step "Waiting for it to answer"
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    ok "the app answers on http://127.0.0.1:8000 after about ${i}s"
    break
  fi
  if [ "$i" = "90" ]; then
    (cd "$DIR" && docker compose -p "$PROJECT" logs --tail 40) >&2
    fail "the app did not start within 90 seconds"
  fi
  sleep 1
done

if [ "$KEYLESS" = "1" ]; then
  step "Automated API checks (no key, inspector off)"
  (cd "$DIR" && docker compose -p "$PROJECT" exec -T claims-agent python - off \
    < scripts/docker_smoke_checks.py)
else
  step "Health check with your key"
  curl -fsS "http://127.0.0.1:8000/api/health"
  echo
fi

step "Clean-room checks passed"
if [ "${NO_PAUSE:-0}" != "1" ] && [ -t 0 ]; then
  echo "The app is running from the unzipped copy: open http://127.0.0.1:8000 and click through it."
  [ "$KEYLESS" = "1" ] || echo "Try the Margaret demo, a follow-up question, then 'that's all' and the email."
  printf 'Press Enter to shut it down and delete the temporary copy... '
  read -r _
fi
echo "Done. Everything this script created has been (or is being) removed."
