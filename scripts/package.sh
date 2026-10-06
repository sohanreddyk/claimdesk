#!/usr/bin/env bash
# Build the submission zip: includes .git history, excludes dependencies and secrets.
# Usage: scripts/package.sh [output.zip]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$(basename "$ROOT")"
OUT="${1:-$ROOT/../${NAME}-submission.zip}"
LIMIT_BYTES=52428800   # 50 MB submission limit

cd "$ROOT"

# 1. Refuse to package if anything that looks like an API key is tracked.
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git grep -nE "sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}" -- . ':!scripts/package.sh'; then
    echo "ERROR: possible API key found in tracked files. Aborting." >&2
    exit 1
  fi
  if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: working tree has uncommitted changes." >&2
  fi
fi

# 2. Zip the project folder.
cd "$ROOT/.."
rm -f "$OUT"
zip -qr "$OUT" "$NAME" \
  -x "*/node_modules/*" "*/.venv/*" "*/venv/*" "*/__pycache__/*" \
     "*/.pytest_cache/*" "*/.ruff_cache/*" "*/dist/*" "*/outbox/*" \
     "*/playwright-report/*" "*/test-results/*" "*/.DS_Store" "*/.env" "*.zip"

# 3. Verify the archive.
if unzip -l "$OUT" | grep -E "(^|/)\.env$"; then
  echo "ERROR: .env is inside the archive." >&2
  exit 1
fi
if unzip -l "$OUT" | grep -E "node_modules/|/\.venv/"; then
  echo "ERROR: installed dependencies are inside the archive." >&2
  exit 1
fi
SIZE=$(wc -c < "$OUT")
if [ "$SIZE" -gt "$LIMIT_BYTES" ]; then
  echo "ERROR: archive is $SIZE bytes, over the 50 MB limit." >&2
  exit 1
fi
echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
