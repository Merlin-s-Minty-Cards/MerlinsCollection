#!/usr/bin/env bash
# Run tests and write results to test-results.txt
# Usage: bash scripts/run-tests.sh [all|backend|frontend|mcp]
# Output: test-results.txt in repo root

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/test-results.txt"
SUITE="${1:-all}"

# Prefer the project venv; fall back to whatever python is on PATH. Bare `python`
# does not exist on this WSL host (only python3), which silently exited 127 and
# reported zero tests rather than failing loudly.
PY="$ROOT/backend/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || command -v python)"
fi

echo "[test-runner] Starting $SUITE tests at $(date)" > "$OUT"
echo "[test-runner] Status: RUNNING" >> "$OUT"
echo "" >> "$OUT"

run_backend() {
  echo "[backend] Running pytest with $PY..." >> "$OUT"
  cd "$ROOT"
  if [ -z "$PY" ]; then
    echo "[backend] FATAL: no python interpreter found" >> "$OUT"
    return 1
  fi
  "$PY" -m pytest backend/tests -q --tb=short >> "$OUT" 2>&1
  echo "[backend] Exit code: $?" >> "$OUT"
}

run_frontend() {
  echo "[frontend] Running vitest..." >> "$OUT"
  cd "$ROOT/frontend"
  # --no-install: never fetch vitest from the network. A bare `npx vitest` tried to
  # download 4.x against this workspace's pinned 3.x and hung on an interactive prompt.
  npx --no-install vitest run --reporter=verbose >> "$OUT" 2>&1
  echo "[frontend] Exit code: $?" >> "$OUT"
}

run_mcp() {
  echo "[mcp-server] Running vitest..." >> "$OUT"
  cd "$ROOT/mcp-server"
  npx --no-install vitest run --reporter=verbose >> "$OUT" 2>&1
  echo "[mcp-server] Exit code: $?" >> "$OUT"
}

case "$SUITE" in
  backend)
    run_backend
    ;;
  frontend)
    run_frontend
    ;;
  mcp)
    run_mcp
    ;;
  all)
    run_backend
    echo "" >> "$OUT"
    echo "============================================" >> "$OUT"
    echo "" >> "$OUT"
    run_frontend
    echo "" >> "$OUT"
    echo "============================================" >> "$OUT"
    echo "" >> "$OUT"
    run_mcp
    ;;
  *)
    echo "[test-runner] Unknown suite: $SUITE" >> "$OUT"
    echo "[test-runner] Status: ERROR" >> "$OUT"
    exit 1
    ;;
esac

echo "" >> "$OUT"
echo "============================================" >> "$OUT"
echo "[test-runner] Completed at $(date)" >> "$OUT"
echo "[test-runner] Status: DONE" >> "$OUT"
