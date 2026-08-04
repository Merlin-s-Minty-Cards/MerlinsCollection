# Round 3 Orchestrator Prompt

You are the orchestrator for Round 3 of the database-interface-enhancements branch on the Merlin's Minty Cards project. Follow the orchestrator rules in .kiro/agents/orchestrator.md.

## Context

- Branch: database-interface-enhancements
- progress.txt is current at the repo root — read it first for full roadmap state
- RFC 0007 (`docs/rfcs/0007-database-interface-enhancements-data-layer.md`) has the approved schema and API design for A1-A5
- Round 1 (planning) and Round 2 (RFC + A6/A7) are complete. This is Round 3.
- A6 (condition LP+/LP-) and A7 (location standardization) are done and tested.
- Frontend Vitest has a pre-existing environment issue ("Vitest failed to find the runner") — all 42 test files fail on this machine. Backend tests (pytest) work fine.

## Your tasks this round

Implement the five backend feature tasks from Phase A using the designs in RFC 0007. Each requires the Council Loop since they change application behavior.

1. **A1: Advanced Trade Engine** — Replace single `cash` component with `cash_components` list supporting multiple payment methods. Add `margin_split` for vendor mode. Update balance endpoint. Maintain backward compat with old `cash` key.

2. **A2: Cosigner Management** — Extend `Consignor` model with `payout_percent`, `email`, `phone`, `active`. Create `/admin/cosigners` router with CRUD + assets + link + analytics endpoints.

3. **A3: Transaction History & Lineage** — Add `TIMELINE` records under `INV#` partition. Add `lineage_id` and `predecessor_item_id` to `_ItemBase`. Add `/admin/inventory/{item_id}/timeline` and `/admin/inventory/{item_id}/lineage` endpoints. Write timeline events on trade confirm.

4. **A4: Show Analytics Data Layer** — Add `ShowAnalyticsSnapshot` model. Store at `PK=SHOW#{id}, SK=ANALYTICS`. Add generate + get + list-by-date endpoints under `/admin/shows/` and `/admin/analytics/`.

5. **A5: Enhanced Inventory Search** — Add `card_number`, `artist`, `location`, `min_price`, `max_price` query params to admin inventory search endpoint.

## Sequencing

Per progress.txt Round 3 notes:
- A2 + A5 are independent (can be done in parallel or any order)
- A1 depends on existing trade model (do first or second)
- A3 depends on transaction model (do after A1 since A1 touches trade confirm)
- A4 depends on A3 (uses transaction/timeline data)

Recommended order: A5 → A1 → A2 → A3 → A4

Each task requires:
1. TDD: Write failing tests first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor
4. Council Loop (mandatory for behavior-changing code)
5. Commit after PASS

## Rules to carry forward

- TDD process: RED then GREEN then REFACTOR, never combined
- Council Loop is mandatory for behavior-changing code (code-writer submissions)
- The orchestrator owns git (commits, staging). Specialists never touch git.
- Use background processes for tests (see terminal rules in workspace steering files)
- CMD-only terminal. No bash syntax (no ls, grep, cat, rm, &&, export, heredocs)
- Conventional commits: type(scope): description
- Read .kiro/agents/ roster and dispatch to existing agents. Never improvise roles.
- Backend tests: `python -m pytest backend/tests -q --tb=short` (use background process)
- Keep `location` field as `str | None` for backward compat (validated in UI, not model)
- Existing 144 admin+model tests must continue to pass (regression gate)
