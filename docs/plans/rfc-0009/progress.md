# RFC 0009 — Slab intake + graded pricing: PROGRESS

**Read this first.** It is the state of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.txt`.** That one is
gitignored (`.gitignore:60`), so it is local-only and your edits to it will never
appear in `git status` or reach anyone else. It now carries a pointer block sending
readers here. Record all RFC 0009 status **in this file**.

**Last updated:** 2026-08-08 (**T1 DONE** — `0b21de2`. T0 still blocked on the owner, see below)
**Branch:** `Polishing-For-Deployment`
**RFC:** [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](../../rfcs/0009-slab-intake-and-graded-pricing.md)
**Task index:** [`README.md`](README.md)

## Status

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | Provider spike | **BLOCKED** | — | **Gate: T2 and T6 must not start until this passes. No verdict yet — neither API key nor any cert number was available, so zero authenticated calls were made and no fixtures exist.** Partial findings + the ready-to-run script: [`spike-findings.md`](spike-findings.md) |
| T1 | Slab model + cert index | **DONE** | `0b21de2` | **Stale-pointer strategy: READER-SIDE verification** (`get_item_id_by_cert` re-reads the item and confirms it still claims the cert) — so T4 can trust `owned: true` **completely**; the residual risk is a rare false *negative*, first row of [`follow-ups.md`](follow-ups.md) T1. Endpoint is `GET /admin/slabs/certs/{cert}?company=PSA`, `200` either way |
| T2 | PSA lookup + quota guard | NOT STARTED | — | blocked on T0 (**T1 is done**). Its mapper writes the four new fields; `cert_lookup_failed` is already in `MACHINE_REVIEW_REASONS` |
| T3 | Buy session → graded | NOT STARTED | — | **unblocked — T1 is done.** Note `cert_number` is still an unbounded `str` on the model; T1 guarded only the read path, see follow-ups |
| T4 | Slabs tab (scan → commit) | NOT STARTED | — | blocked on T2, T3. **Milestone: usable product** |
| T5 | Camera scan fallback | NOT STARTED | — | blocked on T4. Droppable |
| T6 | Pricing provider + slab list | NOT STARTED | — | blocked on T0, T4 |
| T7 | Nightly sync + refresh fix | NOT STARTED | — | blocked on T6 |
| T8 | Docs + ops | NOT STARTED | — | blocked on T7 |
| T-FINAL | Verification + PR | NOT STARTED | — | blocked on all |

Statuses: `NOT STARTED` → `RED (awaiting owner confirmation)` → `IN PROGRESS` → `DONE`,
plus `BLOCKED` for a task that was started and cannot finish without the owner.

## How to update this file

At the **end** of your task conversation, and only then:

1. Set your row's status to `DONE` and paste the commit sha.
2. Add one line to the Notes column if a later task needs to know something.
3. Add anything surprising to the **Decisions made during execution** table below.
4. Append out-of-scope findings to [`follow-ups.md`](follow-ups.md) — not here.

Do **not** mark a task `DONE` without the narrow test selection passing. Evidence
before assertions.

## Blocked / needs the owner

**All four T0 blockers below were checked on 2026-08-07 and are still outstanding.**
`backend/.env` exists and holds 20 other settings, but **neither provider key is in
it**, and neither is set in the environment. T0 stopped there, as its prerequisites
require, without making a single authenticated call.

| Item | Needed from owner | Blocks |
|---|---|---|
| `PSA_API_KEY` in `backend/.env` | Owner has the key; it must be placed in the gitignored `.env` (verified gitignored: `.gitignore:12`), never committed and not pasted into chat | T0, T2 |
| `POKEMONPRICETRACKER_API_KEY` in `backend/.env` | Same | T0, T6 |
| ~20 real cert numbers off the shelf, **including at least 5 Japanese slabs** and a spread of grades | Needed to measure coverage in T0. Invented certs return not-found and burn quota for nothing | T0 |
| *(nice to have)* one cert known **not** to be in PSA's database | For T0's not-found probe; the script otherwise guesses `10000001` | T0 |
| Rotate both keys | Both were pasted into a chat transcript on 2026-08-07. Rotate once the integration is confirmed working | T8 |

Once the keys and certs land, T0 resumes with the script already written and
verified (`spike_slabs.py`, session scratchpad): `check` → `psa --execute` →
`pricing --execute` → `match` → `report`, costing ~22 PSA calls and ~40 pricing
credits. **The script is in a session scratchpad, so a new session must re-check it
still exists and re-create it from [`spike-findings.md`](spike-findings.md) §2 if not.**

## Decisions made during execution

| Date | Task | Decision | Why |
|---|---|---|---|
| 2026-08-07 | T0 | **Stopped rather than substituting invented certs or a mocked provider.** No authenticated call was made and no fixture was written | T0's prerequisites say to stop. A fixture recorded from a guessed shape is worse than none — T2 and T6 are mappers, and a plausible wrong shape looks like it works |
| 2026-08-07 | T0 | Ran **four unauthenticated probes** against both endpoints (no key sent, nothing charged) and recorded them | They cost no quota and settled real questions: PSA cannot distinguish a bad key from a spent quota, and it returns `Retry-After` on 429. See follow-ups.md |
| 2026-08-07 | T0 | Fixtures will be **body-only in `cert_<n>.json`, with status and headers in a `cert_<n>.headers.json` sidecar** | T0 requires the body be recorded unmodified, but the findings also need status codes and headers. A sidecar keeps both without editing the body |
| 2026-08-07 | T0 | `card_id` matching will **reuse `build_catalog_index` + `_match_card`**, not a new matcher | `card_text.py`'s docstring records what two matchers that normalize differently already cost this codebase. `_match_card` returning `None` is also already the correct route into Triage's `missing_card_id` |
| 2026-08-08 | T1 | **Stale cert pointers are handled on the READ side**, not by sweeping on write. `get_item_id_by_cert` re-reads the item and confirms it still claims that cert/company before returning it | The write-path sweep (mirroring `put_show`) would need the item's OLD cert, so it puts an extra `get_item` on **every** inventory write including the bulk import loop — and it still would not cover `delete_inventory_item`, which knows nothing about pointers. Reader verification costs one point read on a low-frequency admin path and makes an orphan harmless by construction. **T4 can trust `owned: true` fully** — a stale pointer can produce a false *negative* (see follow-ups) but never a false positive |
| 2026-08-08 | T1 | `put_inventory_item` writes the **item first, then the pointer**, and lets a pointer failure propagate rather than swallowing it | The reverse order lets an advisory index write block a real inventory write. This way a crash between them leaves a *missing* pointer (a missed warning, which the RFC already allows an admin to override) rather than a wrong one, and the retry is an idempotent upsert of both |

## Baseline at planning time (2026-08-07)

Measured, not assumed — so a later task can tell a regression from a pre-existing
failure:

- Backend suite: **1369 tests / 52 files, ~2 min**. Two pre-existing `test_auth.py`
  failures are known and are **not** yours to fix.
  - **Re-measured at the end of T1 (2026-08-08): 1407 passed, 0 failed, 2m21s.**
    That is 1369 + T1's 38 new tests, and the two `test_auth.py` failures **did
    not reproduce** — nothing in T1 touches auth, so treat the "two known
    failures" line above as stale rather than as something T1 fixed. A later task
    seeing an auth failure should not assume it is pre-existing.
- Frontend: **545 tests / 73 files, ~31 s**.
- MCP: **98 tests / 7 files, ~1 s**.
- Lint: ruff on `backend/src` and `npm run lint --workspace=frontend` both have
  known pre-existing findings. Compare counts; do not chase them to zero.

Use `./.venv/Scripts/python.exe`, never bare `python` — the bare form resolves to an
unrelated venv with no pytest. If results look impossible, this checkout is a git
worktree and a global editable install can shadow it with the sibling repo's
backend; verify which package loaded before debugging anything else (CLAUDE.md).
