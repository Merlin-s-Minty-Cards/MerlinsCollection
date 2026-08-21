# RFC 0008 — Task Plan Index

Execution plan for [RFC 0008](../../rfcs/0008-search-catalog-and-admin-ux-fixes.md).
Each task below is a **self-contained document** — hand exactly one (or a compatible
pair) to a fresh conversation and it has everything it needs without re-reading
the RFC.

**Branch:** all tasks land on `Polishing-For-Deployment` (one branch, many commits).

**Test discipline (owner decision):** do NOT run the full suite per task — backend
alone is ~10 minutes. Each task doc names the *narrow* test selection to run while
working. The full suite runs once, at the end, via T-FINAL below.

**TDD gate (owner decision):** each doc has an explicit RED section. Write those
tests, show the owner the failing output, wait for confirmation, then go GREEN.

**Out-of-scope findings:** append them to [`follow-ups.md`](follow-ups.md) — the
shared ledger the owner triages once every task is done. Do **not** fix items
listed there as a side errand; they are recorded precisely because they were
judged out of scope. That file's header explains the row format and the rules.

## Owner decisions locked in during planning

| RFC Q | Decision |
|---|---|
| Q1/Q2/Q3 — JP names | **All three obsolete.** Owner redirected 2026-08-05 to a hands-on approach; the whole automated `dexId`/`name_en` pipeline is dropped. You own **17 JP cards, 9 with a `card_id`** — the pipeline would have resolved ~6 names. See T10 + T11 |
| Q4 — §E fix direction | **Diagnosed 2026-08-05.** Not an empty table, not bad rows, not a matching bug — an 11.2s full-table scan per request. See T9; one fix option still needs an owner pick |
| Q5 — condition adjustment in MCP total | **No** — resolved from code, `/inventory/summary` doesn't adjust |
| Q6 — show deletion | **Archive flag**, not hard delete, not 409-block |
| Q7 — vendor mode | **Delete** |
| Q8 — admin set list source | **Whole catalog**, not inventory facets — so the owner can spot sets with zero owned cards |
| Q9 — filters vs columns | **Literal reading + escape hatch**: filters follow visible columns, plus a "show all filters" toggle |

## Owner decisions outside the RFC (Triage — T10/T11)

Added 2026-08-05, after the RFC was written. Framing, in the owner's words:
*"get rid of the assumption that all data in the system, as well as future data, is
100% accurate."*

| Decision | Detail |
|---|---|
| JP names are **hands-on**, not automated | An admin-authored `display_name_override`, resolved ahead of the catalog name. The automated pipeline is dropped |
| An **override**, not a materialized field | Recommended by us and accepted: English cards then need no migration, and no sync can clobber a typed name |
| Triage **is** the `needs_review` queue | Not a new flag. `needs_review` already exists and is already set by the importer and the Buy flow |
| **"Send to Triage" on every tab** | Any card, from any admin page, can be flagged for review |
| Tab is named **Triage** | Chosen over the owner's alternative "Workshop" — it says *"needs fixing"* and implies the list should drain |
| Editing a name must **never** change `card_id` | The owner's core requirement. Re-pointing a card is a separate, confirmed, warned action |

## Tasks

| # | Doc | Scope | Depends on |
|---|---|---|---|
| T1 | [t1-price-filter.md](t1-price-filter.md) | §A — price filter compares the displayed price | — |
| T2 | [t2-condition-facets.md](t2-condition-facets.md) | §B — `LP+`/`LP-` reach the filter dropdown | — |
| T3 | [t3-mcp-price-order.md](t3-mcp-price-order.md) | §D — MCP chat total matches the dashboard | — |
| T4 | [t4-sidebar-and-vendor-mode.md](t4-sidebar-and-vendor-mode.md) | §F2 + §F3 — sidebar stays put; vendor toggle removed | — |
| T5 | [t5-detail-modal.md](t5-detail-modal.md) | §F6 — full field coverage, real notes textarea | — |
| T6 | [t6-column-registry.md](t6-column-registry.md) | §F5 — configurable columns, filters follow them | — |
| T7 | [t7-shows-crud.md](t7-shows-crud.md) | §F1 — shows CRUD with archive | — |
| T8 | [t8-admin-set-combobox.md](t8-admin-set-combobox.md) | §F4 — admin set combobox over the whole catalog | — |
| T9 | [t9-catalog-search.md](t9-catalog-search.md) | §E — fix the dead catalog search (**diagnosis done**) | — |
| T10 | [t10-jp-english-names.md](t10-jp-english-names.md) | §C — `display_name_override` + display precedence | — |
| T11 | [t11-triage-tab.md](t11-triage-tab.md) | **New feature** — Triage tab (= the `needs_review` queue) + "Send to Triage" on every tab | **T9, T10** |
| — | [t-final-verification.md](t-final-verification.md) | Full suite, lint, docs, PR | all |

**T8's dependency on T10 is gone** — T10 no longer touches the catalog sync
mapper, so the two no longer collide.

### Cross-task couplings worth knowing before you start one

| Tasks | Coupling |
|---|---|
| T1 ↔ T2 | Same file (`routers/inventory.py`). Run together |
| T5 → T11 | T11 puts its "Send to Triage" button in `CardDetailModal`, on the strength of that file's claim to open from *any* admin page. **T5 verifies that claim** while it's already in there — if some page has a bespoke detail view, T11 must learn it early |
| T9 → T11 | T11's card lookup *is* catalog search |
| T10 → T11 | T11 edits the `display_name_override` T10 adds |
| T6 ↔ T8 | Both touch the admin inventory page (column registry / set combobox) |
| T4 ↔ T7 | Both touch `AdminShell.tsx` (height cap / new nav item) |
| T7 ↔ T11 | Both add a sidebar nav item — T11's also carries a count badge |

## Recommended order

Ordered by *unblocks-the-most* first, then *cheapest confidence-builders*, then
size. Only two real dependencies exist (T11 needs T9 and T10); everything else is
free to reorder.

| # | Conversation | Why here |
|---|---|---|
| 1 | **T9** — catalog search | Unblocks T11, and it's the worst live defect: four admin surfaces are effectively dead. Diagnosis is already done, so this is straight implementation |
| 2 | **T10** — display-name override | Small, unblocks T11. Turns issue #3 from a pipeline into a one-field change |
| 3 | **T1 + T2** — price filter + condition facets | Same file. Both are customer-facing correctness bugs — wrong prices and a broken filter — and both are self-contained |
| 4 | **T3** — MCP price order | Smallest context in the set (mcp-server only), and the last customer-facing correctness bug |
| 5 | **T4 + T5** — sidebar + vendor + detail modal | Cheap, visible, satisfying. T5 also widens `CardDetailModal`, which T11 reuses |
| 6 | **T11** — Triage tab | Now unblocked. Biggest item; give it a fresh conversation with room |
| 7 | **T7** — shows CRUD | Self-contained full-stack; nothing depends on it |
| 8 | **T6** — column registry | Large, pure ergonomics, zero blast radius. Safe to defer or drop if you run out of appetite |
| 9 | **T8** — admin set combobox | Needs a new `catalog_set` registry; lowest urgency of the set |
| 10 | **T-FINAL** | Full suite, docs, PR |

Rationale for the shape: **correctness before ergonomics** (a wrong price reaches a
customer; a missing column annoys you), **unblockers before blocked**, and the two
biggest items — T11 and T6 — deliberately placed after several small wins so the
branch has visible progress before the heavy lifting.

If you want to stop early at any point, the natural cut lines are after step 4
(every correctness bug fixed) or after step 6 (correctness + the new tooling).

## Do not

- Do not run `npm test` or the full pytest suite inside a task conversation.
- Do not combine RED and GREEN phases (CLAUDE.md).
- Do not hardcode a location list — use `useLocations()`.
- Do not build a combined `"LP+"` `Condition` enum value — tier and modifier are
  always two stored fields.
- Do not build the RFC's `name_en` / `dex_number` / Pokédex-map pipeline. It was
  superseded — see T10's "Why the RFC's plan was dropped".
- Do not build T11 before T9. Its card-lookup tool *is* catalog search, which
  currently takes 11.2s per request.
- Do not invent a second "needs attention" flag alongside `needs_review`. Triage
  reuses it.
- Do not put a triage reason in `value_note` — that field is **customer-visible**
  by design. `review_reason` is internal and must stay out of
  `_CUSTOMER_ITEM_FIELDS`.
- Do not let a name edit change `card_id`. Ever.
