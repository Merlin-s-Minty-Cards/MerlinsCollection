# Terminal: WSL2 Bash

Shell: `Linux EthansLaptop 6.18.33.1-microsoft-standard-WSL2`
Working directory: `/home/ethar/kiro/projects/MerlinsCollection` (the shell starts here)

Tools: `execute_bash` for short commands. **`control_bash_process` is effectively
off-limits** — see "Running Tests" below; long jobs belong to the owner.

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
7. **`execute_bash` has a hard ~10-15 second effective timeout** regardless of the `timeout` parameter you pass. Quick commands (`ls`, `git status`, `cat`, linters) are fine. Anything longer (tests, builds, installs) returns early with partial or empty output. **Do not reach for `control_bash_process` instead — hand the command to the owner.** See "Running Tests" below: there is no way to wait for a background job, only to poll it, and polling is what burned a quarter of a month's budget.
8. **Avoid `/mnt/c/` entirely.** Reading the Windows filesystem from WSL is slow enough to blow the timeout on its own — a bare `git status` against a `/mnt/c/` clone timed out twice. Combined with rule 5, treat a `/mnt/c/` timeout as a signal you are in the wrong clone, not as a command to retry.
9. **Long loops over many files will time out.** `for f in $(git ls-files); do file "$f"; done` never returned. Narrow the scope (`git ls-files .kiro`) rather than backgrounding it.

## Line endings

`.gitattributes` pins authored file types to LF (`text eol=lf`). Before it existed, Windows-side edits rewrote whole files to CRLF and produced phantom diffs where every line showed as changed but content was byte-identical — 13 agent files, 4 skill files, and `scripts/run-tests.sh` were all hit.

If you see a diff whose `--numstat` is symmetrical (`26  26`, `68  68`), suspect line endings before content. Confirm with:

```bash
diff -q <(git show HEAD:<path> | tr -d '\r') <(tr -d '\r' < <path>)
```

Silence means the change is pure EOL churn and can be discarded.

## Running Tests — THE OWNER RUNS THEM. NOT YOU.

**No agent in this repo starts a test suite. Not the orchestrator, not `test-qa`, not
`code-writer`. The owner runs suites and tells you when they are finished.**

This is not a style preference. It is a hard capability limit with a direct cost:

- There is **no sleep-and-resume primitive.** Nothing can suspend an agent for four
  minutes and wake it when a process exits.
- `execute_bash` has a hard ~10-15s effective timeout, so it cannot host a suite.
- `control_bash_process` + `get_process_output` **is polling.** Every check is a full
  billed round-trip. An agent that believes it is "waiting 60 seconds" is in fact
  emitting a poll per second. This was observed live and aborted twice by the owner:
  the intent to wait does not produce waiting, it produces a poll storm.

There is no phrasing of "wait patiently" that fixes this, because the agent has no
mechanism to wait. Do not try to engineer one — not `sleep && cat`, not a done-marker
file you check "just once", not a longer `timeout` parameter. The instruction that
works is the one that never starts the job.

### The protocol

1. Write the tests and/or the code. Report what you changed and **what you expect the
   result to be** (which tests should fail and on which missing symbol, for RED; or
   which should now pass, for GREEN).
2. **Stop. Hand back to the owner** with the exact command to run, e.g.
   `bash scripts/run-tests.sh backend`. Arguments: `all`, `backend`, `frontend`, `mcp`.
3. The owner runs it. `scripts/run-tests.sh` writes everything to `test-results.txt`
   in the repo root, ending with `[test-runner] Status: DONE`.
4. When the owner says it is done, **read `test-results.txt` once** with the file read
   tool (workspace-relative path: `test-results.txt`). One read. Confirm the
   `Status: DONE` marker is present so you know you are not reading a stale or partial
   file, then reconcile the numbers.

Summary lines to look for: pytest `X passed, Y failed, Z skipped in Ns`; vitest
`Test Files X passed (Y)` or `FAIL` blocks.

`test-results.txt` is a single shared file, so suites cannot run concurrently.

### The two exceptions

Linters are fast enough for `execute_bash` and may be run directly:
`ruff check backend/src` (~3s), `npm run lint --workspace=frontend` (~5s).

### Reading results you did not produce

Never re-run a suite whose artifact is already on disk. If a prior session or a
subagent reports results, read the artifact and verify the claim cheaply instead:

- Reconcile the arithmetic (RED 1986 passed + 70 failed → GREEN 2056 proves nothing
  was dropped or skipped).
- `git --no-pager diff --stat -- <test paths>` shows whether tests were weakened; a
  large deletion count in test files is the red flag.
- Read the diff of any pre-existing test file that was modified.

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

### Do not poll long jobs at all — do not start them

Each poll is a full round-trip and costs the same as real work. A 3-minute pytest run was
polled ~20 times with `tail -2`; that is ~19 wasted calls.

An earlier version of this section said "poll rarely, budget by the known runtimes." That
was wrong, and it failed in practice: an agent cannot pace itself, because it has no way to
wait. Told to check "at ~3 min, then every ~60s," it polls every second. The rule is
therefore not *poll less* but **do not start the job.** See "Running Tests" above — the
owner runs suites.

This applies to any job longer than the ~10-15s `execute_bash` window, not just tests:
installs, builds, `cdk deploy`. Hand the command to the owner and stop.

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
