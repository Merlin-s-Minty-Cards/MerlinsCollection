# RFC 0016 — Task Plan Index

Execution plan for [RFC 0016](../../rfcs/0016-chat-display-artifacts.md) (Chat
Display Artifacts), Phase 1 of the three-phase chat-experience plan.

**This directory replaces `.kiro/plans/0001-chat-experience/` as the plan of
record for RFC-0016 going forward.** That directory was Kiro's local
coordination state (gitignored, tool-specific) and is not deleted by this
migration, but treat this directory — tracked in git, readable by any tool —
as authoritative from here on. See "Where this came from" below for exactly
what was and wasn't carried over.

**Progress:** update [`progress.md`](progress.md) at the end of every work
session. That file is the first thing a new conversation should read.

**Council review record:** [`council-r1-verdict.md`](council-r1-verdict.md) —
the closed round-1 verdict (FAIL, 11-item blocking checklist). Read it before
touching `_hydrate_item`, `_DisplayState`, or the display-tool dispatch in
`backend/src/merlins_collection/services/bedrock.py` — those checklist items
are the actual spec for the remaining work, in more detail than this README
repeats.

**Non-blocking items:** [`follow-ups.md`](follow-ups.md) — append-only, do not
fix these as a side errand while doing GREEN.

## Status (as of 2026-08-24)

**RED and GREEN are both done. All three suites pass in full: backend
2087/2087, frontend 1020/1020, MCP 101/101.** `ruff check backend/src`
clean, `tsc --noEmit` (mcp-server) clean, `next lint` 0 errors (2
pre-existing warnings, unrelated files). This is the plan's stated
"Definition of done," met in full.

**What's NOT done: an independent Council r2 review.** This session did a
systematic self-review while implementing (`council-r2-self-review.md`) —
required by the TDD skill's own post-change adversarial-review step — but
that is not the same as a second opinion from someone who didn't just write
the code. See "After GREEN: Council round 2" below.

Branch `Inventory-Chat-Design`, commit `f35393c` (RED) plus `06d86f1` (an
unrelated docs cleanup commit made during this migration — see progress.md's
"Housekeeping" entry). Tree otherwise clean.

**RED baseline this GREEN pass closed** (backend re-confirmed live at the
start of this session, before implementation; frontend/MCP numbers carried
from the handoff, consistent with what GREEN then closed to 0):

| Suite | Failed | Passed | Total |
|---|---|---|---|
| Backend (pytest) | 53 | 2034 | 2087 |
| Frontend (vitest) | 10 | 1010 | 1020 |
| MCP server (vitest) | 2 | 99 | 101 |

## GREEN — done 2026-08-24

Read `council-r1-verdict.md` for the original file/line detail on each item,
and `council-r2-self-review.md` for a per-item verification walkthrough
against the actual diff. **Items 7, 8, 10 were dissolved** by owner decision
23 (the `set_display` collapse) and had no remaining tests targeting them —
not implemented, as intended.

| # | What | Where | Status |
|---|---|---|---|
| 1 | FATAL. Distinct per-unit `item_id` on `Card`/`CardResult`, populated in `toCard()`, carried through `tools/**`. | `mcp-server/src/dynamodb-repository.ts`, `repository.ts` | DONE |
| 2 | Shared customer-visibility predicate; `_hydrate_item` uses the same one as `routers/inventory.py::customer_visible_items`. | `services/customer_visibility.py` (new), `bedrock.py`, `routers/inventory.py` | DONE |
| 3 | Hydrate prices mirroring `CardSummary.from_catalog` + `apply_condition_adjustment` + `_display_price` — never a local derivation. | `bedrock.py::_hydrate_item` | DONE |
| 4 | Catch repository/validation errors per-item during hydration and restore; partial results, never a 500. | same | DONE |
| 5 | Drop `cert_image_url` from the customer-facing projection, backend and frontend. | `models/chat.py`, `frontend/lib/inventory.ts` | DONE |
| 6 | Build tool results with `json.dumps`, never f-string interpolation. | `bedrock.py` | DONE |
| 9 (reduced) | `set_display` echoes resulting panel contents; restored panel injected into context at request start. | `bedrock.py` | DONE |
| 11 | Dedupe panel IDs before any repository reads; cap/dedupe-check before hydrating; cap total display-tool blocks per request; bound `artifacts` as well as `panel.cards`. | `bedrock.py` | DONE |
| — | The `set_display` collapse itself (decision 23): 5 panel-mutation tools → `set_display(item_ids)`; empty = closed; cap 50 with truncation notice; `_MAX_TOOL_TURNS` reverted to 5; `DisplayPanel.open` deleted entirely. | `bedrock.py::_TOOLS`, tool-turn loop, `models/chat.py` | DONE |
| — | Frontend: `DisplayPanel` takes no `open` prop, renders nothing when `cards` is empty; `ChatPanel` gates on `displayPanel.cards.length > 0`; `open`/`cert_image_url` removed from `frontend/lib/inventory.ts`. | `DisplayPanel.tsx`, `ChatPanel.tsx`, `lib/inventory.ts` | DONE |

**Definition of done — met:** backend 2087/2087, frontend 1020/1020, MCP
101/101, all passing. `ruff check backend/src` clean, `tsc --noEmit`
(mcp-server) clean, `next lint` 0 errors.

No test was edited to make GREEN easier. Where a test file needed a change,
it was a fixture-construction bug (a nonexistent field name, a missing
required field, a mock response queue one short) unrelated to the behavior
under test — see `progress.md`'s "Fixture bugs found and fixed" for the
full list.

## After GREEN: Council round 2 — still open

This session's own implementation work included a systematic self-review
(`council-r2-self-review.md`), required by the TDD skill's own post-change
adversarial-review step — but that is not an independent second opinion,
and the plan calls for a genuine re-review:

1. Read the diff back with genuinely adversarial intent from four lenses —
   contrarian (edge cases/error paths), architect (structure/duplication),
   chaos (concurrency/retries/external calls), security (auth/trust
   boundaries/secrets) — matching `council-r1-verdict.md`'s "Re-review scope."
   This project's own `adversarial-review` skill covers the same four lenses
   inline; use it (or dispatch reviews however the session doing this
   supports) rather than skipping the pass because the original
   four-subagent Council setup isn't available here.
2. Explicitly verify, not just assert:
   - `mcp-server/src/__tests__/item-id-field.test.ts` passes as proof item 1
     is fixed end-to-end (a real MCP client/server over `InMemoryTransport`,
     not a mocked backend test — mocking the executor bypasses the MCP-side
     bug entirely). It does, as of this session.
   - `item_id` is traced from producer field name (`mcp-server` output) to
     consumer read (`_hydrate_item` input). A green suite is evidence about
     tests, not about the feature — this plan's own history includes a
     fully-green 2056-test suite that hid a defect making the whole feature
     unusable, because every test mocked both sides of the boundary that was
     actually broken. `council-r2-self-review.md` records this trace.
   - Both findings below get a ruling rather than silent drift.

## Known consequences flagged for Council r2 (not resolved)

1. **`DisplayedCard.kind` still admits `'sealed'` and `'bulk'`** on both
   sides of the wire; those values are now unreachable via chat (the amended
   visibility predicate adopts RFC-0001's binding "sealed products are
   hidden, bulk lots are internal-only" and refuses to hydrate them). Carried
   forward unresolved from Council r1.

2. **New, found during this session's own review:** the frontend's price
   display (`card.current_market_value ?? card.listed_price`, in both
   `DisplayPanel.tsx` and `ChatPanel.tsx`) now has its precedence backwards
   relative to what checklist item 3 just fixed on the backend. `listed_price`
   is now the resolved, condition-adjusted display price (mirroring
   `_display_price`); `current_market_value` is a separate, potentially
   stale, unadjusted pass-through. The frontend still prefers the stale one
   whenever both are present. Not fixed here — no current test pins the
   correct precedence, and fixing it means changing a `DisplayPanel.test.tsx`
   assertion that predates this remediation. See
   `council-r2-self-review.md`'s "Findings surfaced" for the full reasoning.

## Future phases (not this RFC, recorded so they aren't lost)

Phase 1 (this RFC) is one of three. Phases 2 and 3 have owner decisions
already recorded from the original planning pass but no RFC written yet and
no work started — see `progress.md`'s "Decisions on record" for the full
list (History: RFC-0017; Admin analyst: RFC-0018). When either starts, give
it its own `docs/plans/rfc-0017/` / `docs/plans/rfc-0018/` directory
following this same convention, and carry its decisions-on-record over from
this directory's `progress.md` rather than re-deriving them.

## Where this came from

This plan was originally tracked in Kiro (a different tool) under
`.kiro/plans/0001-chat-experience/`, which is gitignored and not visible to
other tools. That session ran out of credits mid-task and left a
self-contained handoff (`HANDOFF-to-claude-code.md`, repo root, itself
untracked) instructing the next session to read the Kiro plan state and
carry on. This directory is that migration, done 2026-08-24: the roadmap,
decisions, RED-correction history, and Council r1 verdict were read from the
Kiro plan files and transcribed here in this project's normal
`docs/plans/rfc-NNNN/` shape so they're visible in git and to any tool, not
just Kiro. Nothing in the underlying feature plan (scope, decisions, checklist
items) was changed in the transcription — only the storage location and
surrounding process framing (e.g. Kiro's "owner runs all tests" constraint,
which is a Kiro `execute_bash` timeout workaround, not a rule for every tool;
Claude Code can run and wait for suites directly, as this migration's own
backend re-run demonstrated).
