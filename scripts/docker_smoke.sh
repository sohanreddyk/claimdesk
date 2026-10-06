#!/usr/bin/env bash
# Build the image and check the PACKAGED app (not the source tree).
#
#   bash scripts/docker_smoke.sh                 build, run the test suite on the image's
#                                                Python, start the app, check it
#   SKIP_TESTS=1 bash scripts/docker_smoke.sh    skip the in-image test run (faster)
#
# Needs only Docker. Uses a spare local port and removes its containers when it finishes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-goaly-claims-agent:smoke}"
HOST_PORT="${HOST_PORT:-18000}"
STARTED=""

cleanup() {
  for name in $STARTED; do
    docker rm -f "$name" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

step() { printf '\n==> %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

start_container() { # start_container NAME [docker run options...]
  local name="$1"
  shift
  STARTED="$STARTED $name"
  docker run -d --name "$name" "$@" "$IMAGE" >/dev/null
}

wait_healthy() { # waits for the image's own HEALTHCHECK to pass
  local name="$1" status="" i
  for i in $(seq 1 60); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$name")"
    if [ "$status" = "healthy" ]; then
      echo "ok: $name is healthy"
      return 0
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$name")" != "true" ]; then
      docker logs "$name" >&2
      fail "$name exited before becoming healthy"
    fi
    sleep 1
  done
  docker logs "$name" >&2
  fail "$name did not become healthy (last status: $status)"
}

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  step "Running the Python test suite inside the image build"
  docker build --target test -t "${IMAGE}-tests" .
fi

step "Building the runtime image"
docker build -t "$IMAGE" .

step "Starting the default container (no configuration at all)"
DEFAULT="goaly-smoke-default-$$"
start_container "$DEFAULT" -p "127.0.0.1:${HOST_PORT}:8000"
wait_healthy "$DEFAULT"

step "What is in the image"
uid="$(docker exec "$DEFAULT" id -u)"
[ "$uid" != "0" ] || fail "the container runs as root"
echo "ok: runs as a non-root user (uid $uid)"
docker exec "$DEFAULT" sh -c '
  cd /app
  test -f apps/insurance_claims/ui/dist/index.html || { echo "missing: built UI" >&2; exit 1; }
  test -d apps/insurance_claims/fixtures || { echo "missing: fixtures" >&2; exit 1; }
  for path in .env .git docs apps/insurance_claims/tests apps/insurance_claims/ui/src \
              apps/insurance_claims/ui/node_modules; do
    if [ -e "$path" ]; then echo "unexpected in image: $path" >&2; exit 1; fi
  done
' || fail "the image contents are not as expected"
echo "ok: the image holds the app, fixtures and built UI, and none of the development files"

if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${HOST_PORT}/api/health" >/dev/null \
    || fail "the published port does not answer from the host"
  echo "ok: the published port answers from the host"
fi

step "API checks, inspector off (the default)"
docker exec -i "$DEFAULT" python - off < scripts/docker_smoke_checks.py

step "API checks, inspector on"
INSPECTOR="goaly-smoke-inspector-$$"
start_container "$INSPECTOR" -e ENABLE_DEBUG_INSPECTOR=true
wait_healthy "$INSPECTOR"
docker exec -i "$INSPECTOR" python - on < scripts/docker_smoke_checks.py

step "Done"
echo "image size: $(docker image ls "$IMAGE" --format '{{.Size}}')"
echo "All Docker smoke checks passed."
