# RFC 0012 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify admin page widths, let graded slabs be manually entered on Buy/Sell/Trade regardless of catalog match, and add per-cosigner visibility (inventory filter + assignment UI) to the admin panel.

**Architecture:** Three independent workstreams sharing no files with each other (A: layout CSS, B: relax a Trade validation rule, C: a new `CosignorPicker` component reused by an inventory filter, `CardDetailModal`, and `IncomingCardForm`). Every task is TDD (RED → GREEN → REFACTOR); the owner has waived the pause-and-confirm-red checkpoint for this batch only.

**Tech Stack:** Next.js 14 / TypeScript / vitest (`frontend/`), FastAPI / Python / pytest (`backend/`).

**Spec:** [docs/rfcs/0012-layout-width-graded-manual-entry-consignment-ui.md](../../rfcs/0012-layout-width-graded-manual-entry-consignment-ui.md)

## Global Constraints

- Money fields go through `MoneyInput`/`parseMoney` — never `parseFloat`, never `type="number"` (CLAUDE.md, "MONEY INPUT").
- Card pickers must always show name + image + price, never behind a hover (CLAUDE.md, "A CARD IS NEVER IDENTIFIED BY NAME ALONE") — `CosignorPicker` is a *person* picker, not a card picker, so this rule doesn't apply to it, but any card-context UI touched in these tasks must keep satisfying it.
- An unknown `sort` or `filter` field is a 422; an unknown *value* for a known field is not (CLAUDE.md, inventory filters section).
- TDD is mandatory: write the failing test, confirm it fails, then implement minimally, then refactor with tests green. The owner has explicitly waived the "pause and wait for confirmation that the test is red" human checkpoint for this batch — still perform the RED step and note the failure, just don't stop and ask.
- Each task runs its own layer's test command from CLAUDE.md's Test Commands table before being marked done: backend `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`, frontend `npm test --workspace=frontend`.
- Use `./.venv/Scripts/python.exe` explicitly for all backend commands — never a bare `python`.
- After ALL tasks land, run the full suite (`npm test` from repo root, which covers both workspaces) once before calling the branch done — full-suite-only-at-the-end is this repo's established pattern from prior RFC executions.

---

## Task Index

| Task | File | Depends on | Touches |
|---|---|---|---|
| A | [a-layout-width.md](a-layout-width.md) | none | ~15 admin page files (frontend) |
| B1 | [b1-trades-backend.md](b1-trades-backend.md) | none | `trades.py`, backend tests |
| B2 | [b2-incoming-form-frontend.md](b2-incoming-form-frontend.md) | none (parallel with B1) | `IncomingCardForm.tsx`, `trade/page.tsx`, frontend tests |
| C1 | [c1-cosignor-picker.md](c1-cosignor-picker.md) | none | new `CosignorPicker.tsx` + test |
| C2 | [c2-inventory-filter.md](c2-inventory-filter.md) | C1 | `inventory_filters.py`, admin inventory router, `admin-inventory-columns.tsx`, `ColumnFilter.tsx`, backend+frontend tests |
| C3 | [c3-card-detail-assign.md](c3-card-detail-assign.md) | C1 | `CardDetailModal.tsx`, frontend tests |
| C4 | [c4-buy-trade-assign.md](c4-buy-trade-assign.md) | C1 | `IncomingCardForm.tsx`, `trade-incoming-form.ts`, `deal-session.ts`, `purchases.py` (maybe), tests |
| D | [d-lesson-capture.md](d-lesson-capture.md) | A, B1, B2, C1-C4 done | CLAUDE.md or a skill file |

A, B1, B2, and C1 have no dependencies and can all start immediately in parallel. C2/C3/C4 each depend only on C1 (the picker component's exported props/hook shape), not on each other — they touch different files and can also run in parallel with each other and with A/B1/B2. D is the only task that must run last.

Progress tracking: [progress.md](progress.md).
