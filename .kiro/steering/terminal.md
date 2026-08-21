# Terminal: WSL2 Bash

Shell: `Linux EthansLaptop 6.18.33.1-microsoft-standard-WSL2`
Working directory: `/home/ethar/kiro/projects/MerlinsCollection` (the shell starts here)

Tools: `execute_bash` and `control_bash_process`.

## Which clone you are in

**Three clones of this repo exist on this machine. `/home/ethar/kiro/projects/MerlinsCollection` (WSL native) is the authoritative one** — it is what the IDE opens as the workspace, and file tools resolve it as `//wsl.localhost/Ubuntu/home/ethar/kiro/projects/MerlinsCollection`.

The other two are stale. Do not read from or write to them:

- `/mnt/c/Users/ethar/.cursor/projects/MerlinsCollection` — a merge behind `main`, on an already-merged branch, with its own unrelated `.kiro/plans/0001-*`.
- `/mnt/c/Users/ethar/.cursor/projects/MerlinsCollection-Secondary`

All three share the same `origin`, so `git log` alone will not tell you which one you are in. If a path starts with `/mnt/c/`, you are in the wrong place.

## Rules

1. **Bash.** `ls`, `cat`, `grep`, `rm`, `&&`, `$(...)`, heredocs — all work. `findstr`/`del`/`robocopy` do not.
2. **Do not pass a `cwd` parameter.** The shell already starts at the repo root — use relative paths, or `cd <subdir> &&` inside the command string, which is verified to work. (The historical reason given was that the tool rewrote forward slashes to backslashes; that was observed on the old PowerShell tools and has not been retested on `execute_bash`. The `cd <subdir> &&` form avoids the question entirely.)
3. **Path-style split.** Shell commands use Linux paths (`/home/ethar/...`). File tools (`read_file`, `fs_write`, `str_replace`) take **workspace-relative** paths — `.kiro/steering/terminal.md`, not an absolute path. Absolute Windows paths (`c:\Users\ethar\...`) do **not** resolve and will fail with a path-does-not-exist error.
4. **Exit code 1 is often fine.** Judge success by output content, not exit code. Every command in this workspace tends to return 1 regardless.
5. **If a command fails, stop and ask the user** before retrying a different approach.
6. **Forward slashes in git paths:** `git add .kiro/steering/file.md`
7. **`execute_bash` has a hard ~10-15 second effective timeout** regardless of the `timeout` parameter you pass. Quick commands (`ls`, `git status`, `cat`) are fine. Anything longer (tests, builds, installs) returns early with partial or empty output. **Use `control_bash_process` for anything over ~10 seconds.**
8. **Avoid `/mnt/c/` entirely.** Reading the Windows filesystem from WSL is slow enough to blow the timeout on its own — a bare `git status` against a `/mnt/c/` clone timed out twice. Combined with rule 5, treat a `/mnt/c/` timeout as a signal you are in the wrong clone, not as a command to retry.
9. **Long loops over many files will time out.** `for f in $(git ls-files); do file "$f"; done` never returned. Narrow the scope (`git ls-files .kiro`) or run it through `control_bash_process`.

## Line endings

`.gitattributes` pins authored file types to LF (`text eol=lf`). Before it existed, Windows-side edits rewrote whole files to CRLF and produced phantom diffs where every line showed as changed but content was byte-identical — 13 agent files, 4 skill files, and `scripts/run-tests.sh` were all hit.

If you see a diff whose `--numstat` is symmetrical (`26  26`, `68  68`), suspect line endings before content. Confirm with:

```bash
diff -q <(git show HEAD:<path> | tr -d '\r') <(tr -d '\r' < <path>)
```

Silence means the change is pure EOL churn and can be discarded.

## Running Tests

The shell tool cannot capture full test output because tests exceed the effective timeout. Use `control_bash_process` instead.

**Step 1: Start tests as background processes.**

```
control_bash_process start:
  command: "python -m pytest backend/tests -q --tb=short 2>&1"
```

```
control_bash_process start:
  command: "cd frontend && npx vitest run --reporter=verbose 2>&1"
```

```
control_bash_process start:
  command: "cd mcp-server && npx vitest run --reporter=verbose 2>&1"
```

**Step 2: Wait, then poll output.** Tests take time (backend: ~10 min, frontend: ~25s, mcp-server: ~60s). Use `get_process_output` to check results. Wait at least 30 seconds between checks for backend, 15 seconds for frontend/mcp-server.

**Step 3: Look for final summary lines** in the output:
- pytest: `X passed, Y failed, Z skipped in Ns`
- vitest: `Test Files X passed (Y)` or `FAIL` lines with error details

### Alternative: File-Based Test Runner Script

A wrapper script at `scripts/run-tests.sh` runs tests and writes all output to `test-results.txt` in the repo root. This avoids polling — just start it and read the file when done.

```
control_bash_process start:
  command: "bash scripts/run-tests.sh frontend 2>&1"
```

Arguments: `all`, `backend`, `frontend`, `mcp`

When it finishes, read `test-results.txt` with the file read tool (workspace-relative path: `test-results.txt`). Look for `[test-runner] Status: DONE` at the end to confirm completion.

### Runtimes (approximate)

| Suite | Duration | Notes |
|---|---|---|
| Backend (pytest) | ~10 minutes | 1050+ tests, many DynamoDB mocks |
| Frontend (vitest) | ~25 seconds | 41 test files, jsdom environment |
| MCP Server (vitest) | ~60 seconds | Smaller suite |
| Lint frontend | ~5 seconds | Usually fast enough for `execute_bash` |
| Lint backend | ~3 seconds | Usually fast enough for `execute_bash` |

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
