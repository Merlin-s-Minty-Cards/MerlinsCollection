# Terminal: Windows CMD

Workspace path: `c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary`

## Rules

1. **CMD only.** No `ls`, `export`, `grep`, `cat`, `rm`, `&&`, `$(...)`, heredocs. Use `dir`, `set`, `findstr`, `type`, `del`, `&`.
2. **Single-line commands only.** No multiline args. Git commits: `git commit -m "type(scope): short description"`
3. **Always use `-C` flag for git:** `git -C "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary" status`
4. **Exit code 1 is often fine.** Judge success by output content, not exit code.
5. **If a command fails once, stop.** Ask the user. Two failures = wrong approach.
6. **Quote paths** with spaces. Use `&` not `&&` for chaining (prefer separate tool calls).
7. **Forward slashes in git paths:** `git add .kiro/steering/file.md`
8. **The `execute_pwsh` tool has a hard ~10-15 second effective timeout** regardless of the `timeout` parameter you pass. Quick commands (`dir`, `git status`, `type`) work fine. Any command that takes longer (tests, builds, installs) will return early with partial/empty output and exit code 1. **Use background processes for anything that takes >10 seconds** — see "Running Tests" section below.

## Quick Reference

| Task | CMD |
|------|-----|
| List | `dir` |
| View file | `type file.txt` |
| Delete file | `del file.txt` |
| Delete dir | `rmdir /s /q dir` |
| Env var | `set VAR=value` |
| Find text | `findstr "text" file.txt` |
| Copy tree | `robocopy src dest /E` |

## Running Tests (IMPORTANT — Read This First)

The shell tool **cannot capture full test output** because tests take longer than the tool's effective timeout. You MUST use background processes (`control_pwsh_process`) instead.

### Working Pattern

**Step 1: Start tests as background processes.** Append `2>&1` to trick the tool into accepting non-watch commands.

For commands that run from the workspace root (no `cwd` issue):
```
control_pwsh_process start:
  command: "python -m pytest backend/tests -q --tb=short 2>&1"
  cwd: "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary"
```

For commands that need to run in a subdirectory, use `cmd /c "cd /d <path> & <command>"` because the `cwd` parameter injects `cd "..." ;` (PowerShell syntax that breaks CMD):
```
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\frontend & npx vitest run --reporter=verbose" 2>&1
```

```
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\mcp-server & npx vitest run --reporter=verbose" 2>&1
```

**Step 2: Wait, then poll output.** Tests take time (backend: ~10 min, frontend: ~25s, mcp-server: ~60s). Use `get_process_output` to check results. Do NOT spam-poll — wait at least 30 seconds between checks for backend, 15 seconds for frontend/mcp-server.

**Step 3: Look for final summary lines** in the output:
- pytest: `X passed, Y failed, Z skipped in Ns`
- vitest: `Test Files X passed (Y)` or `FAIL` lines with error details

### What NOT To Do

- Do NOT use `execute_pwsh` for test commands — you will only get partial output (dots or empty)
- Do NOT set `timeout` hoping it will help — the effective cap is ~10-15s regardless
- Do NOT use `cwd` parameter with `control_pwsh_process` for subdirectories — it generates broken `cd "..." ;` syntax. Use the `cmd /c "cd /d ... & ..."` wrapper instead.
- Do NOT use `npx vitest` without the `run` flag — that starts watch mode

### Alternative: File-Based Test Runner Script

A wrapper script at `scripts/run-tests.cmd` runs tests and writes all output to `test-results.txt` in the repo root. This avoids polling — just start it and read the file when done.

```
# Start it as a background process:
control_pwsh_process start:
  command: "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\scripts\run-tests.cmd frontend 2>&1"

# Or for all suites:
control_pwsh_process start:
  command: "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\scripts\run-tests.cmd all 2>&1"
```

Arguments: `all`, `backend`, `frontend`, `mcp`

When it finishes, read `test-results.txt` with the file read tool. Look for `[test-runner] Status: DONE` at the end to confirm completion.

### Runtimes (approximate)

| Suite | Duration | Notes |
|---|---|---|
| Backend (pytest) | ~10 minutes | 1050+ tests, many DynamoDB mocks |
| Frontend (vitest) | ~25 seconds | 41 test files, jsdom environment |
| MCP Server (vitest) | ~60 seconds | Smaller suite |
| Lint frontend | ~5 seconds | Usually fast enough for execute_pwsh |
| Lint backend | ~3 seconds | Usually fast enough for execute_pwsh |

## Test & Lint Commands (Reference)

| Scope | Command |
|---|---|
| All tests | `npm test` (root) |
| Frontend | `npm test --workspace=frontend` |
| MCP Server | `npm test --workspace=mcp-server` |
| Backend | `python -m pytest backend/tests -q --tb=short` |
| Lint frontend | `npm run lint --workspace=frontend` |
| Lint backend | `ruff check backend/src` |
| Frontend dev | `npm run dev --workspace=frontend` |
| Backend dev | `uvicorn merlins_collection.main:app --reload` (from backend/) |
