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

## Cost discipline (learned the expensive way)

A session once burned a quarter of a monthly credit budget on one plan. Almost none of it
went into the actual work. These are the specific causes.

### Never invoke a pager

**Always `git --no-pager <cmd>`** for `diff`, `log`, `show`, `branch` — anything that pages.

A bare `git diff` left `less` resident in the shell. It then swallowed every following
command as keystrokes: an `npm ci` "ran" for five minutes installing nothing, and several
later commands came back as garbled doubled characters or empty output. Recovering cost a
dozen calls. Symptoms to recognize: output full of `~` lines, `(END)`, `Pattern not found`,
`(press RETURN)`, or commands echoing back with every character doubled. Recovery: send a
lone `q`.

Do **not** fix this with `git config core.pager cat` — modifying the user's git config is
off-limits. Use the flag.

### Poll long jobs rarely, not eagerly

Each poll is a full round-trip and costs the same as real work. A 3-minute pytest run was
polled ~20 times with `tail -2`; that is ~19 wasted calls.

- Put the waiting **inside** the background command: have it write results to a file and
  append a done-marker, then read the file **once** when you expect it to be finished.
- `pytest -q` output is block-buffered, so percentages lag. A stalled-looking percentage is
  not evidence of a hang. Confirm liveness with `pgrep -fa pytest` **once**, not repeatedly.
- Budget by the known runtimes in the table above. Backend ~3-4 min: check at ~3 min, then
  every ~60s. Not every 5 seconds.

### Never re-run a suite that just ran

If a subagent reports suite results, **read its artifact** (`test-results.txt`, a log file)
instead of re-running the suite to confirm. Re-running the backend suite to verify a report
costs another 4 minutes for information already on disk.

Verify a subagent's claims cheaply instead:
- Reconcile the arithmetic. RED 1986 passed + 70 failed → GREEN 2056 passed proves no test
  was dropped or skipped.
- `git --no-pager diff --stat -- <test paths>` shows whether tests were weakened. A large
  deletion count in test files is the red flag; 21 insertions / 11 deletions is not.
- Read the diff of any pre-existing test file it modified.

Re-run a suite yourself only when the reconciliation is inconsistent or no artifact exists.

### Precheck the toolchain once, at session start

Before planning any work that ends in a test run, confirm the environment in **one** command:

```bash
test -x backend/.venv/bin/pytest && echo PY_OK; test -d node_modules && echo NM_OK
```

This clone had no venv and no `node_modules` at all, discovered only after dispatching two
agents and attempting a full suite. `python` does not exist on this host — only `python3`.
Backend deps: `python3 -m venv backend/.venv && backend/.venv/bin/python -m pip install -e "backend[dev]"`.
Node: `npm ci` at root (~1m, 1800 packages).

`npm ci` on this host appends `"packageManager": "yarn@1.22.22..."` to `package.json` and
reformats `workspaces`. **Revert it every time** (`git checkout -- package.json`) — this repo
is npm-workspaces with a `package-lock.json`. Check for it before every commit.

### Keep subagent briefs proportionate

A subagent brief is paid for on every dispatch. State the constraints, the files, and the
definition of done; do not restate the entire RFC that the agent is about to read anyway.
