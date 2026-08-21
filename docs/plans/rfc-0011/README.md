# RFC 0011 — Task Plan Index

Execution plan for
[RFC 0011](../../rfcs/0011-inventory-column-controls-and-unmatched-queue.md).
Each task below is a **self-contained document** — hand exactly one to a fresh
conversation and it has everything it needs without re-reading the RFC.

**Branch:** all tasks land on `Polishing-For-Deployment` (one branch, many commits).

**Progress:** update [`progress.md`](progress.md) at the end of every task. That file is
the first thing a new conversation should read.

**Test discipline (owner decision, carried over from RFC 0008/0009/0010):** do NOT run
the full suite per task. Each task doc names the *narrow* test selection to run while
working. The full suite runs once, at the end, via T12.

**TDD gate (CLAUDE.md, binding):** each doc has an explicit RED section. Write those
tests, show the owner the failing output, **wait for confirmation**, then go GREEN. Never
combine phases.

**Out-of-scope findings:** append to [`follow-ups.md`](follow-ups.md). Do not fix them as
a side errand.

## Global constraints — these apply to EVERY task

Copied verbatim from the RFC and CLAUDE.md. A task's requirements implicitly include all
of these.

| Rule | Consequence if broken |
|---|---|
| **Money goes through `parseMoney` / `MoneyInput`. `parseFloat` is banned.** | `parseFloat("1,300")` is `1` and is **not** `NaN`, so it passes every `isNaN` guard and books a silent $1,299 loss. |
| **Never `type="number"` on a money field.** | A native number input refuses a comma, making the owner's input un-typeable. |
| **Dates go through `frontend/lib/dates.ts`.** Never `new Date()` on a date-only string; never `toISOString()` for "today". | `new Date('2026-08-10')` is UTC midnight → renders Aug 9. `todayLocal()` is the only correct "today". |
| **Tests that render a date pin a negative-offset TZ** via `frontend/lib/__tests__/_timezone.ts`, with `vi.useFakeTimers({ toFake: ['Date'] })`. | Full fake timers deadlock `waitFor`. |
| **In `beforeEach`, `mockReset()` — never `clearAllMocks()`.** | `clearAllMocks` does not drain a `mockResolvedValueOnce` queue; leftovers cascade into later tests. |
| **`userEvent.setup({ delay: null })` for any test typing more than a few characters.** | Default per-keystroke delay cost `ChatPanel.test.tsx` 3.3s and made it flaky under load. |
| **Never ship an admin control without `vault-field`.** | The admin theme is dark; an unstyled `<select>` renders light-green-on-white. |
| **A card picker shows name, image AND price.** Use `CardPickerRow`. | Owner rule 2026-08-10, absolute. Pokémon names collide across sets/printings/languages. |
| **Never write a bare `float` to DynamoDB.** `services/dynamodb._serialize` coerces `float` → `Decimal`. When testing a money path, send a JSON **number**, not a string. | boto3 rejects floats outright; this 500'd in production. |
| **Name resolution: `display_name_override` wins everywhere.** Call `adminItemName` / `admin_item_name`; never inline `display_name \|\| product_name`. | Four implementations kept deliberately in sync. |
| **A silent no-op filter is a bug. Unknown key → 422.** | Precedent: `_validate_triage_reason`. An ignored filter is indistinguishable from a broken one. |
| **Use `./.venv/Scripts/python.exe`, never bare `python`.** | Bare `python` resolves to an unrelated venv with no pytest. |

## Task index

| # | Task | Layer | Depends on | Blocks |
|---|---|---|---|---|
| [T1](t1-generic-sort-backend.md) | Generic server-side sort over one field registry | backend | — | T2 |
| [T2](t2-all-columns-sortable.md) | Every inventory column sortable | frontend | T1 | — |
| [T3](t3-generic-filter-backend.md) | Generic, validated filter layer | backend | — | T4 |
| [T4](t4-per-column-filters-frontend.md) | A dedicated filter per column | frontend | T3 | — |
| [T5](t5-no-catalog-match-model.md) | `no_catalog_match` + the triage predicate | backend | — | T6, T7, T8 |
| [T6](t6-triage-unlink-and-park.md) | Unlink-and-park + the park button | frontend | T5 | T8 |
| [T7](t7-pairing-suggestions-endpoint.md) | Ranked pairing suggestions | backend | T5 | T8, T10 |
| [T8](t8-unmatched-queue-page.md) | `/admin/unmatched` page + sidebar entry | frontend | T5, T6, T7 | T10 |
| [T9](t9-catalog-first-seen-and-sync.md) | `first_seen_at` + new cards in existing sets | backend | — | T10 |
| [T10](t10-dashboard-new-cards-widget.md) | "New from TCGdex" dashboard widget | frontend | T7, T9 | — |
| [T11](t11-shared-card-search-panel.md) | Shared card search + always-on manual entry | both | — | T14 |
| [T13](t13-graded-incoming-on-trades.md) | Slabs can come in through a trade | backend | — | T14, T15 |
| [T14](t14-deal-search-and-add-card.md) | One search, one add-card form, identity always visible | frontend | T11, T13 | T15 |
| [T15](t15-unified-deal-page.md) | One page, three modes | frontend | T13, T14 | T16 |
| [T16](t16-retire-buy-and-sell-routes.md) | Retire `/admin/buy` and `/admin/sell` | frontend | T15 | — |
| [T12](t12-docs-and-verification.md) | Docs, CLAUDE.md, full-suite verification | both | **all, incl. T13–T16** | — |

**T12 runs LAST**, after T16. It keeps its number because the task docs cross-reference it
and renumbering a doc that is already linked from `progress.md` buys nothing.

**Three tracks.** T1–T4 (the inventory table) and T5–T10 (the unmatched queue) share no
files. **T13–T16 (the unified deal surface, RFC Part 2) is the third**, and it is the only
one with a hard internal order — T13 → T14 → T15 → T16 — because each builds on the last.

**T11 sits across two tracks and was re-scoped when Part 2 landed.** It still builds
`CardSearchPanel`, but it no longer adopts it in Buy or Trade: Buy is deleted by T16 and
Trade is rebuilt by T15, which composes the component instead. See T11's own note.

## One task per conversation — and how each one ends

**Every task doc carries the same "Done means" contract, and it is binding.** A task
conversation is finished when, and only when:

1. the narrow test selection named in the doc **passes**, with the output shown;
2. `progress.md` is updated — status `DONE`, the commit sha, a Notes line if a later task
   needs to know something, and any surprising decision added to the Decisions table;
3. anything found but not fixed is appended to `follow-ups.md`.

Do not run the full suite. Do not merge. Do not push.
