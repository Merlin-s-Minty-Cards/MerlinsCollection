# Terminal: WSL2 Bash

Shell: `Linux EthansLaptop 6.18.33.1-microsoft-standard-WSL2`
Working directory: `/mnt/c/Users/ethar/.cursor/projects/MerlinsCollection` (the shell starts here)

## Rules

1. **Bash.** `ls`, `cat`, `grep`, `rm`, `&&`, `$(...)`, heredocs — all work. `findstr`/`del`/`robocopy` do not.
2. **Do not pass a `cwd` parameter** to `execute_pwsh` or `control_pwsh_process`. The tool rewrites forward slashes to backslashes (`cd "\mnt\c\..."`) which bash rejects. The shell already starts at the repo root — just use relative paths. For subdirectories, use `cd <subdir> &&` inside the command string.
3. **Path-style split.** Shell commands use Linux paths (`/mnt/c/...`). File-editing tools (`read_file`, `fs_write`, `str_replace`) resolve **Windows paths** (`c:\Users\ethar\.cursor\projects\MerlinsCollection\...`). The two are not interchangeable across tool families.
4. **Exit code 1 is often fine.** Judge success by output content, not exit code.
5. **If a command fails, stop and ask the user** before retrying a different approach.
6. **Forward slashes in git paths:** `git add .kiro/steering/file.md`
7. **The `execute_pwsh` tool has a hard ~10-15 second effective timeout** regardless of the `timeout` parameter you pass. Quick commands (`ls`, `git status`, `cat`) work fine. Any command that takes longer (tests, builds, installs) will return early with partial/empty output and exit code 1. **Use background processes for anything that takes >10 seconds** — see below.

## Running Tests

The shell tool cannot capture full test output because tests exceed the effective timeout. Use `control_pwsh_process` instead.

**Step 1: Start tests as background processes.**

```
control_pwsh_process start:
  command: "python -m pytest backend/tests -q --tb=short 2>&1"
```

```
control_pwsh_process start:
  command: "cd frontend && npx vitest run --reporter=verbose 2>&1"
```

```
control_pwsh_process start:
  command: "cd mcp-server && npx vitest run --reporter=verbose 2>&1"
```

**Step 2: Wait, then poll output.** Tests take time (backend: ~10 min, frontend: ~25s, mcp-server: ~60s). Use `get_process_output` to check results. Wait at least 30 seconds between checks for backend, 15 seconds for frontend/mcp-server.

**Step 3: Look for final summary lines** in the output:
- pytest: `X passed, Y failed, Z skipped in Ns`
- vitest: `Test Files X passed (Y)` or `FAIL` lines with error details

### Alternative: File-Based Test Runner Script

A wrapper script at `scripts/run-tests.sh` runs tests and writes all output to `test-results.txt` in the repo root. This avoids polling — just start it and read the file when done.

```
control_pwsh_process start:
  command: "bash scripts/run-tests.sh frontend 2>&1"
```

Arguments: `all`, `backend`, `frontend`, `mcp`

When it finishes, read `test-results.txt` with the file read tool (Windows path: `c:\Users\ethar\.cursor\projects\MerlinsCollection\test-results.txt`). Look for `[test-runner] Status: DONE` at the end to confirm completion.

### Runtimes (approximate)

| Suite | Duration | Notes |
|---|---|---|
| Backend (pytest) | ~10 minutes | 1050+ tests, many DynamoDB mocks |
| Frontend (vitest) | ~25 seconds | 41 test files, jsdom environment |
| MCP Server (vitest) | ~60 seconds | Smaller suite |
| Lint frontend | ~5 seconds | Usually fast enough for execute_pwsh |
| Lint backend | ~3 seconds | Usually fast enough for execute_pwsh |

## Test & Lint Commands

| Scope | Command |
|---|---|
| All tests | `npm test` (root) |
| Frontend | `npm test --workspace=frontend` |
| MCP Server | `npm test --workspace=mcp-server` |
| Backend | `python -m pytest backend/tests -q --tb=short` |
| Lint frontend | `npm run lint --workspace=frontend` |
| Lint backend | `ruff check backend/src` |
| Frontend dev | `npm run dev --workspace=frontend` |
| Backend dev | `cd backend && uvicorn merlins_collection.main:app --reload` |
