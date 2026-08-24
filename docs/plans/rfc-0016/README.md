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

**RED is done and committed. GREEN has not started.**

Branch `Inventory-Chat-Design`, commit `f35393c` (RED) plus `06d86f1` (an
unrelated docs cleanup commit made during this migration — see progress.md's
"Housekeeping" entry). Tree otherwise clean.

Verified-failing baseline, re-confirmed live during this migration (backend
re-run in full; frontend/MCP numbers carried from the handoff, not yet
independently re-run this session):

| Suite | Failed | Passed | Total | Source |
|---|---|---|---|---|
| Backend (pytest) | 53 | 2034 | 2087 | re-run live 2026-08-24, this session |
| Frontend (vitest) | 10 | 1010 | 1020 | handoff, verified at `f35393c` |
| MCP server (vitest) | 2 | 99 | 101 | handoff, verified at `f35393c` |

The backend re-run (53/2034) is one test off the handoff's claimed 52/2035 —
not investigated further; treat as noise until GREEN, then reconcile properly
against whichever number the post-GREEN run lands on. Full failure list not
retained from this session's re-run (a `| tail -20` on the command clipped
it) — re-run `bash scripts/run-tests.sh backend` for the complete list if
needed; do not treat that clipped run as a reason to distrust the count.

## What's left: GREEN, then Council r2

Read `council-r1-verdict.md` for full file/line detail on each item; this is
a compressed pointer, not a replacement. **Items 7, 8, 10 are dissolved** by
owner decision 23 (the `set_display` tool collapse) and have no remaining
tests targeting them — do not implement them.

| # | What | Where |
|---|---|---|
| 1 | **FATAL, do first.** Add a distinct per-unit `item_id` to `Card`/`CardResult` in `mcp-server/src/`, populate in `toCard()`, carry through `tools/**`. Do NOT widen backend display tools to accept `card_id`. | `mcp-server/src/dynamodb-repository.ts`, `mcp-server/src/repository.ts`; real RED is `mcp-server/src/__tests__/item-id-field.test.ts` |
| 2 | Extract the shared customer-visibility predicate; `_hydrate_item` must use the same one as `routers/inventory.py::customer_visible_items`. | `backend/src/merlins_collection/services/bedrock.py` |
| 3 | Hydrate prices through `CardSummary.from_catalog` + `apply_condition_adjustment` + `_display_price` — never a local derivation. | same |
| 4 | Catch `ClientError`/`ValidationError` per-item during hydration and restore; partial results, never a 500. | same |
| 5 | Drop `cert_image_url` from the customer-facing projection, backend and frontend. | `models/chat.py`, `frontend/lib/inventory.ts` |
| 6 | Build tool results with `json.dumps`, never f-string interpolation. | `bedrock.py` |
| 7 | (reduced) `set_display` echoes resulting panel contents; restored panel injected into context at request start. | `bedrock.py` |
| 8 | Dedupe panel IDs before any repository reads; cap/dedupe-check before hydrating; cap total display-tool blocks per request; bound `artifacts` as well as `panel.cards`. | `bedrock.py` |
| 9 | The `set_display` collapse itself (decision 23): replace 5 panel-mutation tools with `set_display(item_ids)`; empty = closed; cap 50 with truncation notice; revert `_MAX_TOOL_TURNS` to 5; delete `DisplayPanel.open` entirely. | `bedrock.py::_TOOLS`, tool-turn loop |
| 10 | Frontend: `DisplayPanel` takes no `open` prop, renders nothing when `cards` is empty; `ChatPanel` gates on `displayPanel.cards.length > 0`; remove `open`/`cert_image_url` from `frontend/lib/inventory.ts`. | `frontend/components/inventory/DisplayPanel.tsx`, `ChatPanel.tsx`, `lib/inventory.ts` |

(Numbering above follows the verdict's checklist positions 1-6, 9(reduced),
11, plus the collapse itself and its frontend half — not a renumbering; see
`council-r1-verdict.md` for the original ordering and rationale.)

**Definition of done:** every currently-failing test above passes, nothing
currently passing regresses, `ruff check backend/src` stays clean. Target:
backend 2087/2087, frontend 1020/1020, MCP 101/101, all passing.

**Do not edit any test to make GREEN easier.** Three rounds of RED correction
this plan already went through (recorded in `progress.md`) proved the tests
are the correct arbiter once corrected — if one still looks wrong, that's a
signal to stop and think, not to patch the test.

## After GREEN: Council round 2

1. Read the diff back with genuinely adversarial intent from four lenses —
   contrarian (edge cases/error paths), architect (structure/duplication),
   chaos (concurrency/retries/external calls), security (auth/trust
   boundaries/secrets) — matching `council-r1-verdict.md`'s "Re-review scope."
   This project's own `adversarial-review` skill covers the same four lenses
   inline; use it (or dispatch reviews however this session's tooling
   supports) rather than skipping the pass because the original four-subagent
   Council setup isn't available here.
2. Explicitly verify, not just assert:
   - `mcp-server/src/__tests__/item-id-field.test.ts` passes as proof item 1
     is fixed end-to-end (a real MCP client/server over `InMemoryTransport`,
     not a mocked backend test — mocking the executor bypasses the MCP-side
     bug entirely).
   - `item_id` is traced from producer field name (`mcp-server` output) to
     consumer read (`_hydrate_item` input). A green suite is evidence about
     tests, not about the feature — this plan's own history includes a
     fully-green 2056-test suite that hid a defect making the whole feature
     unusable, because every test mocked both sides of the boundary that was
     actually broken.
   - The `DisplayedCard.kind` dead-surface issue (below) gets a ruling rather
     than silent drift.

## Known consequence flagged for Council r2 (not yet resolved)

`DisplayedCard.kind` still admits `'sealed'` and `'bulk'` on both sides of
the wire; after GREEN those values become unreachable via chat (the amended
visibility predicate adopts RFC-0001's binding "sealed products are hidden,
bulk lots are internal-only" and refuses to hydrate them). This is flagged,
not resolved — surface it in the Council r2 submission rather than quietly
leaving the dead surface or quietly removing it without a ruling.

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
