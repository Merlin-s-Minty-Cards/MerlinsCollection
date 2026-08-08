# RFC 0009 — Slab intake + graded pricing: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never
appear in `git status` or reach anyone else. It now carries a pointer block sending
readers here. Record all RFC 0009 status **in this file**.

**Last updated:** 2026-08-07 (planning complete, nothing implemented)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](../../rfcs/0009-slab-intake-and-graded-pricing.md)
**Task index:** [`README.md`](README.md)

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | Provider spike | NOT STARTED | — | **Gate: T2 and T6 must not start until this passes** |
| T1 | Slab model + cert index | NOT STARTED | — | |
| T2 | PSA lookup + quota guard | NOT STARTED | — | blocked on T0, T1 |
| T3 | Buy session → graded | NOT STARTED | — | blocked on T1 |
| T4 | Slabs tab (scan → commit) | NOT STARTED | — | blocked on T2, T3. **Milestone: usable product** |
| T5 | Camera scan fallback | NOT STARTED | — | blocked on T4. Droppable |
| T6 | Pricing provider + slab list | NOT STARTED | — | blocked on T0, T4 |
| T7 | Nightly sync + refresh fix | NOT STARTED | — | blocked on T6 |
| T8 | Docs + ops | NOT STARTED | — | blocked on T7 |
| T-FINAL | Verification + PR | NOT STARTED | — | blocked on all |

Statuses: `NOT STARTED` → `RED (awaiting owner confirmation)` → `IN PROGRESS` → `DONE`

## How to update this file

At the **end** of your task conversation, and only then:

1. Set your row's status to `DONE` and paste the commit sha.
2. Add one line to the Notes column if a later task needs to know something.
3. Add anything surprising to the **Decisions made during execution** table below.
4. Append out-of-scope findings to [`follow-ups.md`](follow-ups.md) — not here.

Do **not** mark a task `DONE` without the narrow test selection passing. Evidence
before assertions.

## Blocked / needs the owner

| Item | Needed from owner | Blocks |
|---|---|---|
| `PSA_API_KEY` in `backend/.env` | Owner has the key; it must be placed in the gitignored `.env`, never committed | T0, T2 |
| `POKEMONPRICETRACKER_API_KEY` in `backend/.env` | Same | T0, T6 |
| ~20 real cert numbers off the shelf, **including Japanese slabs** | Needed to measure coverage in T0 | T0 |
| Rotate both keys | Both were pasted into a chat transcript on 2026-08-07. Rotate once the integration is confirmed working | T8 |

## Decisions made during execution

*(empty — append as tasks land, newest last)*

| Date | Task | Decision | Why |
|---|---|---|---|

## Baseline at planning time (2026-08-07)

Measured, not assumed — so a later task can tell a regression from a pre-existing
failure:

- Backend suite: **1369 tests / 52 files, ~2 min**. Two pre-existing `test_auth.py`
  failures are known and are **not** yours to fix.
- Frontend: **545 tests / 73 files, ~31 s**.
- MCP: **98 tests / 7 files, ~1 s**.
- Lint: ruff on `backend/src` and `npm run lint --workspace=frontend` both have
  known pre-existing findings. Compare counts; do not chase them to zero.

Use `./.venv/Scripts/python.exe`, never bare `python` — the bare form resolves to an
unrelated venv with no pytest. If results look impossible, this checkout is a git
worktree and a global editable install can shadow it with the sibling repo's
backend; verify which package loaded before debugging anything else (CLAUDE.md).
