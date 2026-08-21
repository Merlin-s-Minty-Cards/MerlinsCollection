#!/usr/bin/env bash
# Run tests and write results to test-results.txt
# Usage: bash scripts/run-tests.sh [all|backend|frontend|mcp]
# Output: test-results.txt in repo root

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/test-results.txt"
SUITE="${1:-all}"

echo "[test-runner] Starting $SUITE tests at $(date)" > "$OUT"
echo "[test-runner] Status: RUNNING" >> "$OUT"
echo "" >> "$OUT"

run_backend() {
  echo "[backend] Running pytest..." >> "$OUT"
  cd "$ROOT"
  python -m pytest backend/tests -q --tb=short >> "$OUT" 2>&1
  echo "[backend] Exit code: $?" >> "$OUT"
}

run_frontend() {
  echo "[frontend] Running vitest..." >> "$OUT"
  cd "$ROOT/frontend"
  npx vitest run --reporter=verbose >> "$OUT" 2>&1
  echo "[frontend] Exit code: $?" >> "$OUT"
}

run_mcp() {
  echo "[mcp-server] Running vitest..." >> "$OUT"
  cd "$ROOT/mcp-server"
  npx vitest run --reporter=verbose >> "$OUT" 2>&1
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
