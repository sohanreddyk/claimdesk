#!/usr/bin/env bash
# Run every automated check and print one summary.
#
#   bash scripts/check_all.sh                     Python tests + lint, UI tests + build
#   WITH_DOCKER=1 bash scripts/check_all.sh       ...and the Docker smoke test as well
#   WITH_DOCKER=1 SKIP_TESTS=1 bash scripts/check_all.sh
#                                                 ...skipping the in-image test run (faster)
#
# Run it from anywhere with the Python virtual environment active.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAILED=""

run() { # run "label" command...
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  if "$@"; then
    echo "PASS: $label"
  else
    echo "FAIL: $label"
    FAILED="${FAILED}
  - ${label}"
  fi
}

run "Python tests" python -m pytest -q
run "Python lint (ruff)" ruff check .
run "Requirements matrix references" python scripts/check_matrix.py
run "UI tests" npm --prefix apps/insurance_claims/ui test
run "UI type-check and build" npm --prefix apps/insurance_claims/ui run build

if [ "${WITH_DOCKER:-0}" = "1" ]; then
  run "Docker smoke test" bash scripts/docker_smoke.sh
else
  echo
  echo "(Docker smoke test skipped. Add WITH_DOCKER=1 to include it.)"
fi

echo
if [ -n "$FAILED" ]; then
  echo "SOME CHECKS FAILED:${FAILED}"
  exit 1
fi
echo "All checks passed."
