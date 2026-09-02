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

**RED, GREEN, and an independent Council r2 review are all done.** All
three suites pass in full: backend 2090/2090, frontend 1022/1022, MCP
101/101. `ruff check backend/src` clean, `tsc --noEmit` (frontend and
mcp-server) clean, `next lint` 0 errors (2 pre-existing warnings, unrelated
files). This is the plan's stated "Definition of done," met in full, with a
genuine second opinion behind it — see "Council r2 — done" below.

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
| 5+ | Council r2: also dropped `finish` and `CardSummary`'s `set_id`/`rarity`/`image_large`/`market_price` — same rationale, zero readers on either display surface (advisor-architect M5). | same | DONE (2026-08-24) |
| 6 | Build tool results with `json.dumps`, never f-string interpolation. | `bedrock.py` | DONE |
| 9 (reduced) | `set_display` echoes resulting panel contents; restored panel injected into context at request start. | `bedrock.py` | DONE |
| 11 | Dedupe panel IDs before any repository reads; cap/dedupe-check before hydrating; cap total display-tool blocks per request; bound `artifacts` as well as `panel.cards`. | `bedrock.py` | DONE |
| — | The `set_display` collapse itself (decision 23): 5 panel-mutation tools → `set_display(item_ids)`; empty = closed; cap 50 with truncation notice; `_MAX_TOOL_TURNS` reverted to 5; `DisplayPanel.open` deleted entirely. | `bedrock.py::_TOOLS`, tool-turn loop, `models/chat.py` | DONE |
| — | Frontend: `DisplayPanel` takes no `open` prop, renders nothing when `cards` is empty; `ChatPanel` gates on `displayPanel.cards.length > 0`; `open`/`cert_image_url` removed from `frontend/lib/inventory.ts`. | `DisplayPanel.tsx`, `ChatPanel.tsx`, `lib/inventory.ts` | DONE |

**Definition of done — met (updated after Council r2):** backend
2090/2090, frontend 1022/1022, MCP 101/101, all passing. `ruff check
backend/src` clean, `tsc --noEmit` (frontend and mcp-server) clean,
`next lint` 0 errors.

No test was edited to make GREEN easier. Where a test file needed a change,
it was a fixture-construction bug (a nonexistent field name, a missing
required field, a mock response queue one short) unrelated to the behavior
under test — see `progress.md`'s "Fixture bugs found and fixed" for the
full list.

## Council r2 — done 2026-08-24

A genuinely independent re-review (a fresh session with no memory of
writing the GREEN code), not the self-review `council-r2-self-review.md`
records — that document is kept as a record of the self-review, not
mistaken for this pass. This session re-read every touched file from
source, cross-referenced `follow-ups.md` and `council-r1-verdict.md`'s
appendix against the actual current code, and used the
`adversarial-review` skill formally for a second sweep over the resulting
fix diff — matching `council-r1-verdict.md`'s "Re-review scope" (all four
lenses: contrarian, architect, chaos, security).

Explicitly verified rather than assumed:
- `mcp-server/src/__tests__/item-id-field.test.ts` still passes — item 1
  is fixed end-to-end (a real MCP client/server over `InMemoryTransport`,
  not a mocked backend test).
- The sole production call site of `DisplayedCard(...)` (inside
  `_hydrate_item`'s try/except) — confirms the kind-narrowing fix below is
  fully contained.
- The sole real caller of `BedrockChatService.chat()` (`routers/chat.py`) —
  confirms removing the dead string-compatibility branch (M6) couldn't
  affect anything else.
- Every trimmed field's readers, by grep across both the backend and
  frontend trees, before removal — not just the original claim.

**Both "known consequences" below are now resolved, and three more
follow-ups were picked up in the same pass** — five fixes total. Full
detail, including the fix-diff adversarial review's verdict (PASS, no
blocking findings) and the mid-pass regression it caught and fixed (a
third bare-string bedrock test double, in `test_rate_limit.py`, missed on
the first full-suite run), is in `progress.md`'s Council r2 item under
"Items" and in `follow-ups.md`.

1. **`DisplayedCard.kind` narrowed** from
   `Literal["raw","graded","sealed","bulk"]` to `Literal["raw","graded"]`
   (backend `models/chat.py`, mirrored in `frontend/lib/inventory.ts`) —
   `is_customer_visible`'s `CUSTOMER_KINDS` is `{"raw","graded"}` and
   `_hydrate_item` returns `None` before ever constructing a
   `DisplayedCard` of another kind, so the wider literal admitted
   provably-unreachable values. Narrowing turns that invariant into a
   second, independent enforcement layer (a future gate regression now
   fails closed via `ValidationError` instead of silently leaking a
   `DisplayedCard` of the wrong kind). Two now-dead branches removed as a
   direct consequence: `bedrock.py::_display_name`'s sealed/bulk checks,
   and a `card.kind === 'sealed'` ternary in both `DisplayPanel.tsx` and
   `ChatPanel.tsx` (would have been a TypeScript "no overlap" error
   against the narrowed type regardless).

2. **Frontend price-precedence bug fixed.** `DisplayPanel.tsx` and
   `ChatPanel.tsx` now read `card.listed_price ?? card.current_market_value
   ?? 'Price N/A'` (was the reverse) — `listed_price` is the resolved,
   condition-adjusted figure since checklist item 3;
   `current_market_value` is kept only as a fallback for the real case
   where `listed_price` is null. New/updated tests in both
   `DisplayPanel.test.tsx` and `ChatPanel.test.tsx` pin the corrected
   precedence, including an explicit negative assertion that the stale
   figure no longer renders when both are present.

**Three more follow-ups fixed in the same pass** (all pre-existing, filed
in `follow-ups.md`'s Council r1 appendix, picked up rather than left for a
third round):

3. **JP badge fixed for uncatalogued items** (advisor-architect M4 /
   advisor-contrarian) — added `DisplayedCard.language`, populated from
   `item.language` independent of any catalog match; both frontend
   components' `isJapanese` now reads it directly instead of inferring
   from a nested catalog field that doesn't exist without a catalog match.
4. **Dead wire fields trimmed** (advisor-architect M5) — `CardSummary`
   lost `set_id`, `rarity`, `image_large`, and a `market_price` that
   duplicated `DisplayedCard.listed_price`'s exact value for a raw item;
   `DisplayedCard` lost `finish`. All confirmed dead by grep before
   removal. The wire payload's lack of an enforceable byte ceiling (M5's
   other half) is still open.
5. **Dead `isinstance(result, str)` branch removed** (advisor-architect
   M6) from `routers/chat.py` — no real `chat()` implementation has
   returned a bare string since GREEN landed; the branch was kept alive
   only by test doubles, which were fixed to return the real contract
   shape instead.

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
