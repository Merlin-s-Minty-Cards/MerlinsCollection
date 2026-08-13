# RFC 0011: Inventory Column Controls & the Unmatched Queue

**Status:** Draft
**Author:** brainstorming (main thread)
**Date:** 2026-08-13
**Scope:** Four owner asks from 2026-08-13 — sort every inventory column, give every
column its own filter, split "no TCGdex match" out of Triage into its own queue, and
surface newly-catalogued cards on the dashboard — plus two additions the owner raised
during design: manual entry must always be available in card pickers, and catalog search
must accept a card number and a set. Design only; nothing here is implemented yet.

## Summary

The owner's report, in their words: *"There is a feature where I can select which columns
I want to see in the inventory. This works, but I should also be able to sort every
column… Also, each column should have a dedicated filter that shows up and disappears
when the column is selected or unselected."* And separately: *"Since a lot of cards don't
have matches in the catalog… instead of forcing it to be the wrong card just because it
is close, there should be a new tab that is just for cards that do not have a match in
TCGdex."*

Read against the code these are **five root causes**, of which two are half-built
mechanisms and three are missing capability:

- **(A) The column registry already declares both halves of the relationship — sorting
  was never wired to it.** RFC 0008 T6 built `INVENTORY_COLUMNS` (33 columns) and
  `INVENTORY_FILTERS` (12 filters, each bound to the column it follows). But
  `_sort_admin_results` still hardcodes an if/elif chain over **eight** field names, so
  25 of 33 columns render a header nobody can click. → §A.
- **(B) The filter panel is registry-driven and the registry is two-thirds empty.**
  `isFilterVisible` already implements "filters follow the visible columns" exactly as
  the owner describes it. The behavior they are asking for is the behavior that ships —
  it simply has no entry for 21 of the columns. → §B.
- **(C) `missing_card_id` is a DERIVED triage reason, so a card TCGdex does not carry can
  never leave Triage.** There is no stored state meaning *"we looked, and there is no
  match"*, so the queue that is designed to reach zero is permanently floored by cards
  that are not errors. The owner's workaround — pointing a card at a close-but-wrong
  promo — attaches a materially wrong price, which the nightly sync then keeps refreshing.
  → §C, §D.
- **(D) Nothing records when a catalog card was first seen, and the incremental sync
  cannot see a new card inside a set we already hold.** `CatalogCard.last_synced_at` is
  bumped by *any* write, and `_sync_new_sets` skips every set with even one existing row.
  So "show me what TCGdex added" is unanswerable today at both the card and the set
  level. → §E, §F.
- **(E) Manual entry is a consolation prize and catalog search takes one field.** Buy's
  "Enter manually instead" appears only after a search fails; and although
  `GET /admin/market/search` has accepted `name`, `set_id` **and** `number` since it was
  written, every one of the five frontend pickers sends `name` alone. → §G.

## Motivation

(A) and (B) are the cheap half: the mechanism exists, is documented, and has tests. What
is missing is coverage, and the fix is to make coverage **structural** — a registry the
tests can assert is total — rather than a longer hand-written list that will be
two-thirds empty again after the next field is added.

(C) is the one that costs money. The owner is explicit: *"There are cards that are close
to the right card but are actually a promo so the price is completely wrong."* Today the
only two options are to leave the card in Triage forever or to link it to the wrong
catalog row. The second is worse than it looks: `card_id` drives pricing, so a wrong link
is not a cosmetic mislabel, it is a wrong number on a customer-facing surface that the
nightly denormalizer will keep re-asserting. This RFC adds the third option — record that
there is no match, park the card, and revisit it when the catalog changes.

(D) exists only to serve (C). A parked card is parked *until TCGdex catches up*, and a
queue you must remember to check by hand is a queue that rots. The owner: *"if there
could be some kind of widget on the dashboard to show any new cards from TCGdex, that
would be great, and then we can look at the new tab to see which card can now be paired."*

## Owner decisions recorded during design (2026-08-13)

These reverse or constrain what the code does today and are not open for re-litigation
during implementation:

1. **Sorting and filtering stay SERVER-side.** One code path, `total` stays honest, and
   the endpoint keeps the `sort` param every other admin page shares.
2. **Unlinking a card automatically parks it** in the new queue. Cards that *already*
   have no match get a separate, explicit button to move them there.
3. **The new queue ships EMPTY.** Nothing is backfilled or auto-migrated: *"all cards
   that go there should only be moved under admin supervision."* This is pinned by a test.
4. **Unlinking clears the inherited market value** and offers the hand-value tool.
5. **Ranked pairing suggestions are not a cage.** Every parked row must also offer a
   full-catalog search *"if none of those candidates match."*
6. **One shared card-search component**, adopted across all five pickers, rather than a
   sixth local variation.

## Detailed Design

### A. Every column is sortable (owner ask 1)

`_sort_admin_results` (`routers/admin/inventory.py:1149`) becomes a **typed value
extractor over one field registry** instead of an if/elif chain. The wire format is
unchanged — `{field}_{direction}`, parsed with `rsplit("_", 1)`, which is why
`Column.key` and the backend sort field must stay the same string (CLAUDE.md already
records this trap).

Extraction by field type:

| Type | Fields | Sort value |
|---|---|---|
| Money | `cost_basis`, `current_market_value`, `sticker_price`, `listed_price`, `market_value_at_purchase` | `float` |
| Numeric | `grade` | `float` |
| Timestamp | `acquired_at`, `reviewed_at`, `no_catalog_match_at` | epoch seconds |
| Boolean | `needs_review`, `factory_sealed`, `no_catalog_match`, `consignment` (present/absent) | `bool` |
| Effective name | `display_name` / `name` (alias) | `admin_item_name(item)` — override-first |
| **Condition** | `condition` + `condition_modifier` | **ordinal rank**, see below |
| String | everything else | `str(...).lower()` |

**One missing-value rule for every type: absent sorts LAST in both directions.** This
generalizes the behavior money fields already have (`+inf` ascending, `-inf` descending)
to the other 25 columns, instead of letting `""` sort first for strings and last for
numbers. A column where the blanks bunch at whichever end you are not looking at is the
column you stop clicking.

**Condition gains a real ordering.** Today `str(cond)` sorts alphabetically, which makes
`LP+` and `LP-` indistinguishable — the exact distinction RFC 0008 T2 went to trouble to
store separately. The rank is the display order: `NM > LP+ > LP > LP- > MP > HP > DMG`.
This is a behavior change on an existing sortable column and is called out as such.

**An unknown sort field becomes a 422.** Today an unparseable or unrecognised `sort`
returns the list *unsorted*, which is indistinguishable from "this column has no order"
and is the same silent-no-op class that `_validate_triage_reason` was written to
eliminate. The `price` → `current_market_value` alias is retained for compatibility.

Frontend: every `INVENTORY_COLUMNS` entry except `_image` and `_actions` gets
`sortable: true`. First-click direction stays `desc` — CLAUDE.md pins that as a
deliberate page-level disagreement with Prep Queue, and this RFC does not reopen it.

### B. Every column gets a dedicated filter (owner ask 2)

The showing/hiding behavior is already correct: `isFilterVisible(filter, visible,
showAllFilters)` returns true only when the filter's `columnKey` is on screen. Nothing
about that changes. What changes is that **`INVENTORY_FILTERS` becomes total over
`INVENTORY_COLUMNS`**, and the control for each is chosen from a declared kind rather
than hand-written per filter.

`InventoryFilterDef` gains `kind` and, where relevant, an option source:

```ts
kind: 'text' | 'select' | 'range' | 'dateRange' | 'presence'
```

Per-column analysis — this is the "analyzed for whether they should be a max/min filter,
a dropdown, a text input" deliverable:

| Kind | Columns |
|---|---|
| **range** (min/max) | Price Paid, Market, Sticker, Listed Price, Market at Purchase, Grade |
| **dateRange** | Acquired, Reviewed |
| **select** | Status, Kind, Condition, Location, Language, Finish, Ownership, Grading Co., Factory Sealed, Review, Acquired Show |
| **presence** | **Card ID → Any / Linked / Unlinked** |
| **text** (contains) | Review Reason, Cert #, Product Type, Description, Sticker Notes, Notes, Value Note, Name Override, TCGplayer URL, Lineage ID, Predecessor, Item ID |
| *(none)* | Image |

Two of those need justification:

- **Card ID is a `presence` control, not a text box.** Nobody types
  `en:sv3pt5-158` from memory; the question actually being asked at that column is
  *"which of my cards are unlinked"*, which is one dropdown.
- **Acquired Show is a `select` sourced from `GET /admin/shows`**, not free text, for the
  same reason the Location filter is a dropdown: the values are a managed list, and a
  substring match across show names is not a question anyone has.

The three existing filter-only entries (`set_id`, `card_number`, `artist`) keep
`columnKey: null` and their current behavior — the admin search carries no catalog join,
so they would render an em dash on every row as columns.

**Page state.** Thirteen `useState` filter values become one keyed record
(`Record<string, FilterValue>`) with one setter. At 33 columns the per-filter `useState`
approach is untenable, and the existing `filters-cover-every-id` test generalizes into a
stronger one: *every non-pinned column has exactly one filter, and every filter names a
real column or is explicitly filter-only.*

**Wire protocol.** A repeatable `filter` query parameter carrying
`{field}:{op}:{value}`, validated against a server-side `FILTERABLE_FIELDS` registry —
**422 on an unknown field or an op the field does not support**, never a silent no-op.
Ops: `contains`, `eq`, `gte`, `lte`, `isnull`, `notnull`.

The twelve existing named params (`status`, `condition`, `min_price`, …) are **kept and
re-expressed as sugar that constructs the same filter objects**, evaluated by the same
code. Two spellings of one filter is exactly the "two definitions of countability"
failure CLAUDE.md warns about under the ledger; the mitigation is that there is only ever
one *evaluator*, and a test asserts the named form and the generic form of the same
filter return identical sets.

### C. `no_catalog_match` — the stored fact Triage is missing (owner ask 3)

Two fields on `InventoryItem`:

| Field | Type | Notes |
|---|---|---|
| `no_catalog_match` | `bool = False` | **Internal.** MUST stay out of `_CUSTOMER_ITEM_FIELDS`, same rule as `review_reason`. |
| `no_catalog_match_at` | `datetime \| None` | Server-stamped when the flag is set; never client-supplied. Drives "parked 3 weeks ago". |

**One line in the single authority does the work.** `services/triage.is_missing_card_id`
gains `and not item.no_catalog_match`. Because `GET /admin/inventory/search?triage=true`
and `GET /admin/triage/counts` both route through that function, the list and the sidebar
badge cannot disagree about it — which is the property that whole module exists to
guarantee.

A parked item that is *also* `flagged` or `missing_english_name` **stays in Triage**,
carrying its remaining chips. That is correct and deliberate: those are real errors, and
"no catalog match" is not.

**The invariant, enforced in the model:** `no_catalog_match=True` implies
`card_id is None`.

- Setting the flag on an item that still carries a `card_id` is a **422** telling the
  admin to unlink first. A card that is matched is not unmatched, and allowing both to be
  true creates a row that is in two queues' worth of states at once.
- Writing a `card_id` **clears** `no_catalog_match` and `no_catalog_match_at`
  automatically. Pairing is the exit condition; requiring a second write to leave the
  queue is how rows get stranded in it.
- Sealed and bulk items have no `card_id` field at all. The park action guards with
  `hasattr` exactly as `is_missing_card_id` already does, so a sealed box can never be
  parked.

**Nothing is backfilled.** No migration, no script, no auto-migration on read. The queue
ships empty and fills only by admin action — the owner's requirement, pinned by a test
asserting that a fresh table with unmatched inventory yields an empty unmatched list.

### D. The two entry points, and the way back

Per the owner's decision, unlinking parks automatically, and already-unmatched cards get
their own button.

**1. Re-point dialog → "Unlink — no match in TCGdex".** The existing `RepointDialog` is
already the codebase's most carefully guarded write (`card_id` drives pricing, images and
set membership, and it shows a before/after diff). The unlink path joins it there rather
than becoming a bare row button, and writes in one `PUT /inventory/{item_id}`:

```json
{ "card_id": null, "no_catalog_match": true, "current_market_value": null }
```

`current_market_value` is cleared because it is the *wrong promo's* figure — the whole
complaint. The hand-value tool (`ValueDialog`, already gated on `missing_card_id`) is
offered immediately afterwards and is skippable. The item then carries the existing
`HandValuedBadge`, whose tooltip already says exactly the right thing: *"Not in the
catalog — no sync will ever price this card, so its value is set by hand."*

**2. Row action "No TCGdex match"** on a Triage row that already has no `card_id`. Sets
the flag only — there is nothing to unlink and no inherited price to clear.

**Both directions exist.** A "Back to Triage" action on the unmatched queue clears the
flag, on the same reasoning as `unarchive` in the archiving contract: *parking that
cannot be undone is just a slower delete.* Pairing a card clears it implicitly, per §C.

### E. `/admin/unmatched` — the queue page (owner ask 3)

Sidebar: **Back office group, directly after Triage.** Route `/admin/unmatched`. Vault
design system throughout (`vault-panel`, `vault-field`, `text-pine-*`) — CLAUDE.md's
"never ship an admin control without `vault-field`" applies, and the Slabs page is the
cautionary tale.

Shape follows Triage, because it is the same kind of work: `DataTable`, **art always on
with no toggle** (the list is short by construction and identifying the card *is* the
task), search, and row-level tools.

| Column | Contents |
|---|---|
| Card | `CardImage` + effective name + the item's own set/number text |
| Parked | `no_catalog_match_at`, via `formatISODate` — never `new Date()` on a date-only string |
| Value | Hand-typed value, inline `MoneyInput` (`parseMoney`, never `parseFloat`) |
| Suggestions | Ranked candidates — see below |
| *(actions)* | Pair · Search catalog · Back to Triage |

**Suggestions are computed server-side on list load.** The matcher is the existing
conservative one (`spreadsheet_import._match_card`'s normalized name/number index),
relaxed to return *ranked candidates* rather than the single-or-nothing answer the
importer needs. This is affordable because the whole catalog is already resident in
`catalog_cache` and the parked list is tens of rows, not thousands.

Each candidate renders through `CardPickerRow` — **image + name + set · #number +
price**, per the absolute owner rule from 2026-08-10. A candidate list without art and a
price is precisely the list a person cannot choose from, and this page is nothing but
choosing.

**"Search the whole catalog" is on every row**, per the owner's answer, opening the
shared panel from §G. Ranked suggestions are a shortcut, never the only door.

The list sorts rows **with candidates to the top**, which is the *"which card can now be
paired"* view the owner described.

**Pairing** confirms with a before/after diff (same discipline as re-point), writes
`card_id`, clears the flag per §C, and drops the row without a refetch — the
"Priced → removed" pattern Prep Queue and Triage already share.

### F. Knowing what TCGdex added (owner ask 4)

Two gaps, both real:

**F.1 — `CatalogCard.first_seen_at: datetime | None = None`.** Written with a conditional
`attribute_not_exists(first_seen_at)` write, so:

- a full reseed cannot reset it (the breadth seed rewrites every row);
- an existing row is never re-stamped by an ordinary price refresh.

All 31,603 existing rows carry `null`, meaning **"predates this feature"** — not "new".
The widget counts only non-null values, so it reads `0` at first and becomes more useful
with every sync. That is the honest answer and matches how `detail: brief|full` already
preserves "we have never fetched" as distinct from "there is nothing".

**F.2 — `_sync_new_sets` must notice new cards inside sets we already hold.** Today it
early-outs on `missing_set_ids` and walks `client.iter_brief_cards(language)` only when
some set is entirely absent. A promo that finally gets catalogued into an existing set —
the exact case driving this RFC — is invisible to it.

The change: always walk the brief cards, comparing each id against the in-memory catalog
index, and write identity-only rows for ids we have never seen. Prices stay out of it,
as they already do; `refresh_held_prices` owns those once a card is actually held. The
run summary gains `cards_added_to_existing_sets`.

**This is the one real cost increase in the RFC** — one full brief-card walk per language
per run, on every run rather than only on runs that find a new set. It is a button and a
monthly job, and the walk is the same endpoint the breadth seed already uses. Recorded in
Risks.

**F.3 — the dashboard widget.** A "New from TCGdex" panel in the *Needs attention*
region, reading `GET /admin/catalog/new-cards?since_days=30`:

- **N cards first seen in the last 30 days**, from `/admin/catalog/new-cards`;
- **M of your parked cards now have a candidate** — the number that actually prompts
  action. It comes from `/admin/unmatched/suggestions`, the same endpoint the queue page
  uses, so the widget and the page can never quote different figures;
- links to `/admin/unmatched`.

Soft-failed through the existing `soft()` helper like every other panel, so a dead
endpoint costs one card and not the dashboard.

### G. One card search, everywhere, with manual entry always available (owner ask 5)

The owner: *"There is no way to manually enter a card for buys, trades, etc, when you
search for a Pokemon that exists, but there is not correct catalog card. There should
always be an option for manual entry, not just when the catalog search returns no
results."* And: *"this same search feature could really benefit from having more ways to
search like also entering the card number along with the name. Maybe even adding a place
to enter a set too (this should be a searchable dropdown menu)."*

**The backend already supports all three fields.** `GET /admin/market/search` takes
`name`, `set_id` and `number` (`routers/admin/market.py:83`), and the `set_id` branch
uses the GSI rather than the catalog scan. All five frontend callers send `name` alone.
So this is a frontend consolidation with one small backend fix.

**New `components/admin/shared/CardSearchPanel.tsx`:**

- **Name** — text, debounced, as today;
- **Card number** — text;
- **Set** — `SetCombobox`, the searchable dropdown already used by the inventory Set
  filter and backed by `useCatalogSets()`;
- results as `CardPickerRow` (image + name + set · #number + price);
- **"Enter manually"** — a permanent control on the surfaces where creating an
  off-catalog item is meaningful.

**Backend fix:** `number` is an exact string match today, so `182` misses a card stored
as `182/167`. Both sides get normalized through the existing `normalize_number` /
`number_keys` helpers, which already solve this for the importer.

**Manual entry applies to Buy, Trade and Slabs**, where creating an item that is not in
the catalog is a real outcome. It does **not** apply to Triage's re-point (which must
select a genuine catalog row — its "no match" answer is §D's park action) or to the
Market page (a browse tool). Buy's existing "Unknown card — not found in catalog" hint
stays as an additional nudge; it stops being the only door.

Adopted in: **Buy · Trade · Slabs intake · Triage re-point · Unmatched · Market.**

## Data Schemas

```python
# models/inventory.py — InventoryItem (raw and graded kinds)
no_catalog_match: bool = False           # INTERNAL: never in _CUSTOMER_ITEM_FIELDS
no_catalog_match_at: datetime | None = None   # server-stamped only

# Model validator: no_catalog_match=True implies card_id is None (422 otherwise);
# assigning card_id clears both fields.
```

```python
# models/catalog.py — CatalogCard
first_seen_at: datetime | None = None    # None == predates this feature, NOT "new"
```

No new entity types and no new DynamoDB item shapes. `no_catalog_match` rows are ordinary
inventory rows; the queue is a filter, not a table.

## API Contracts

| Method | Path | Change |
|---|---|---|
| `GET` | `/admin/inventory/search` | `sort` accepts every registry field; **422** on unknown. New repeatable `filter={field}:{op}:{value}`; **422** on unknown field/op. New named `no_catalog_match: bool`. |
| `PUT` | `/admin/inventory/{item_id}` | Accepts `no_catalog_match`; stamps `no_catalog_match_at`; enforces the §C invariant. |
| `GET` | `/admin/unmatched/suggestions` | Ranked catalog candidates for the parked cohort. Reuses the normalized matcher; served from `catalog_cache`. |
| `GET` | `/admin/catalog/new-cards` | `?since_days=30` → count + a few cards with image, name, set, number, price. |
| `GET` | `/admin/market/search` | Unchanged signature; `number` matching normalized via `number_keys`. |

No new list endpoint for the unmatched queue — it is
`GET /admin/inventory/search?no_catalog_match=true`, on the same "reuse before adding"
rule that keeps Triage on the shared search. The dashboard count reads that call's
`total`, exactly as the Prep Queue count already does.

## Testing

Outside-in TDD per CLAUDE.md — RED first, wait for confirmation that tests fail, then
GREEN, then REFACTOR. Never combine phases.

**Backend (pytest):** per-type sort extraction and the missing-last rule; condition rank
including modifiers; 422 on an unknown sort field; the `price` alias still resolves; each
filter op; 422 on unknown field and on a valid field with an unsupported op; **the named
param and the generic form of one filter return identical sets**; `is_missing_card_id`
respects `no_catalog_match`; list and counts agree; the §C invariant in both directions;
sealed/bulk cannot be parked; **the unmatched queue is empty on a table nobody has
touched**; `first_seen_at` is not re-stamped on update and survives a reseed; the sync
detects a new card in an existing set.

**Frontend (vitest):** every non-pinned column is sortable; **every column has exactly
one filter** (the generalized `filters-cover-every-id`); each filter kind renders its
declared control; a filter disappears with its column and the hidden-active-filter notice
still fires; unmatched page pair/park/back-to-triage flows; suggestions render image and
price; full-catalog search is reachable from every row; the dashboard widget soft-fails;
`CardSearchPanel` sends all three params; manual entry is reachable on Buy, Trade and
Slabs **before** any search runs. Any test rendering a date pins a negative-offset TZ via
`_timezone.ts`.

## Alternatives Considered

**Client-side sorting and filtering.** The endpoint is unpaginated, so every row is
already in the browser and both would be instant and free. Rejected by the owner: it
splits "what a filter is" into two mental models, makes the header's `(total)` disagree
with what is on screen, and would have to be rebuilt the day inventory outgrows a single
fetch.

**Twenty-five new named query parameters** instead of a generic `filter`. Explicit and
self-documenting, but it puts a 40-parameter signature on the endpoint and requires a new
parameter, a new test and a new frontend branch for every field added — which is how the
filter panel ended up two-thirds empty in the first place.

**A second boolean beside `needs_review`, or a new `triage_reason` predicate.** Rejected:
a new *reason* keeps the card in Triage, which is the opposite of the ask. The point is
that these cards are **not errors** and must leave the queue that is meant to reach zero.

**Auto-parking every `missing_card_id` item on deploy.** Rejected by the owner
explicitly — *"make sure that the new tab is empty right now."* An automatic migration
would move hundreds of cards, including ones that genuinely are mismatches a human should
look at, and would make the new queue exactly as undrainable as Triage is today.

**A `catalog_sync_run` log instead of `first_seen_at`.** Less schema churn, but it cannot
answer "is *this* card new", which the pairing suggestions want, and it makes the widget's
window a function of run cadence rather than of time.

**Set-level newness only** (first-seen on the `catalog_set` registry). Cheapest, and it
misses new cards added to sets we already hold — which is most promos, and therefore most
of the parked cohort.

## Risks & Mitigations

1. **The 422-on-unknown-sort change may break existing tests** that assert a silent
   fallback to unsorted. Mitigation: audit and update those tests deliberately as part of
   the task, not incidentally — the silent form is the bug.
2. **Always walking brief cards** in `_sync_new_sets` is one extra full upstream walk per
   language per run. Mitigation: it is a button/monthly job on the same endpoint the
   breadth seed uses, the comparison is against an in-memory index, and the run summary
   reports what the extra walk bought.
3. **Two spellings of one filter** (named params + generic) for a release. Mitigation: one
   evaluator, and a test asserting the two forms return identical sets. Named params are
   not deprecated in this RFC — other pages depend on them.
4. **`first_seen_at` is null on all 31,603 rows**, so the widget reads `0` until the next
   sync. This is correct, not a defect, and the panel copy must not imply otherwise.
5. **Clearing `current_market_value` on unlink removes those cards from the dashboard's
   market-value total** until they are hand-valued. Deliberate — an inherited promo price
   is a wrong number, and a wrong number in a total is worse than a missing one. The
   hand-value prompt immediately afterwards is the mitigation.
6. **Registry drift between the frontend column list and the backend filter/sort
   registries.** Mitigation: `Column.key` is already the backend's sort field (CLAUDE.md
   records the `rsplit` trap), and totality tests on both sides fail loudly rather than
   degrading into a dead header or a no-op filter.

## Open Questions

None blocking. Two deliberately deferred:

- **Bulk park** ("move these six cards to unmatched") is not in scope. The owner's rule is
  admin supervision per card, and a bulk action on a destructive write that clears prices
  is not the first version of this feature.
- **Notifying on a new candidate** (as opposed to showing one on the dashboard) is
  deferred. The widget answers the question; a push channel is a separate decision.

---

# Part 2 — The unified deal surface (owner asks, 2026-08-13, second round)

**Added after T1–T4 shipped.** The owner asked for slabs to move through trades, and in the
same message asked for Buy, Sell and Trade to become one tab with a mode toggle, on a
layout they explicitly do not want preserved. Recorded here rather than as a separate RFC
because it lands on the same branch, in the same round, and shares a component with §G.

## Summary

Owner, verbatim: *"There needs to be a way for slabs to be going in and out of the trade
menu… I want to combine them all into one big tab, with a toggle between buying, selling,
or trading… I really do not like the layout, so you do not need to feel the need to keep
the layout the same. I don't like the show image on hover, because card image, name, and
price should all be shown when searching for cards, as well as when added to coming in or
going out."*

Four root causes:

- **(H) `trades.py` hardcodes `"kind": "raw"`** on every incoming leg
  (`routers/admin/trades.py:792`), plus `ItemCategory.RAW` on the transaction. A slab
  acquired in a trade is therefore written as a raw card and loses its company, grade and
  cert entirely. **Trading a slab OUT already works** — outgoing legs reference an existing
  `item_id` and never inspect `kind` — so this is an incoming-only gap. → §H.
- **(I) Three pages run one workflow.** Buy, Sell and Trade are 707, 687 and 914 lines of
  substantially parallel state: a session id, a cart, cash components, a balance, a
  customer view, a date, a confirm dialog. The owner works all three at one table and wants
  one surface. → §I.
- **(J) Card identity is behind a hover, and absent entirely in two places.** Sell renders
  its image from `onMouseEnter` into a side panel captioned *"Hover or select a card"*
  (`sell/page.tsx:390, 508`), and Trade's Going Out picker shows name + price with **no
  image at all** (`trade/page.tsx:713`) while its Coming In picker uses `CardPickerRow` and
  does. → §J.
- **(K) Manual entry is still a consolation prize on the surfaces being rebuilt.** Same
  defect §G records for Buy, restated by the owner for the new page: manual entry must be
  permanently available and **put away by default**. → §K.

## Owner decisions, 2026-08-13 (second round)

| # | Decision | Consequence |
|---|---|---|
| 10 | **One route: `/admin/trade`.** `/admin/buy` and `/admin/sell` are **removed**, not redirected. | Departs from the `/admin/outgoing` precedent — but that precedent was about *renaming* a page that still existed. These two pages genuinely stop existing. The dashboard quick actions, the sidebar and `mobileItems` are rewritten in the same task. |
| 11 | Sidebar label **"Buy / Sell / Trade"** | Spells out all three modes, so nothing has to be learned. Costs a longer nav label. |
| 12 | **Full-width search on top; Coming In / Going Out side by side; summary rail** | Gives result rows the whole page width, which is what stops image + name + set + price being squished — the owner's stated objection. |
| 13 | Search source **auto-locked by mode**, switchable only in Trade | A control settable one way is noise on two modes of three, and a mis-set source in Sell would search 31,603 catalog rows for a card you are trying to sell. |
| 14 | **Incoming is ALWAYS a catalog pick first**, then Raw or Graded | Owner: *"regardless you should be picking a card from the catalog, it's just that graded cards have more values."* |
| 15 | **Condition and grade are never on screen together** | They are alternatives, not companions. Showing both invites entering both. |
| 16 | **Keep three session APIs**; merge only the UI | These are the highest-risk money paths in the repo. RFC 0010 T0 exists because a partial write in one of them created real inventory and then reported "Nothing was created". |

## Detailed Design

### H. Slabs through a trade (owner ask)

Incoming legs gain optional `kind` (`"raw"` default, or `"graded"`), `company`, `grade`,
`cert_number` and `grade_label`. When `kind == "graded"` the committed item is a
`GradedInventoryItem` and the transaction carries `ItemCategory.GRADED`.

**A graded incoming leg still requires the same catalog `card_id` a raw one does**
(decision 14). Graded pricing joins on `(card_id, company, grade)`, so a slab with no
`card_id` is unpriceable by construction — exactly the state RFC 0009 documents for
free-text slabs, and not one to create by accident from a trade.

`GET /admin/slabs/certs/{cert}` supplies the already-owned warning, reused rather than
reimplemented. It stays a **warning with override, never a gate**: a slab sold and bought
back is legitimate re-entry (RFC 0009).

Validation is symmetric with the model: a graded leg missing `company`, `grade` or
`cert_number` is a **422**, and a raw leg carrying them is a 422 too — silently dropping
fields is how a slab becomes a raw card, which is the defect being fixed.

### I. One surface, three modes

`/admin/trade?mode=buy|sell|trade`. `mode` lives in the query string so the toggle is
bookmarkable, a refresh keeps the mode, and the dashboard keeps **three** distinct quick
actions pointing at one page.

| mode | Coming In | Going Out | search source | session API |
|---|---|---|---|---|
| buy | shown | hidden | catalog (locked) | `purchases.py` |
| sell | hidden | shown | inventory (locked) | `sales.py` |
| trade | shown | shown | toggle | `trades.py` |

**Everything the owner named as keeping, keeps:** customer view, cost-basis mode, cash
components, balance, profit and date. Each renders where it applies — cost-basis mode is a
trade concept and shows in trade mode only; profit is meaningless on a pure buy.

**Switching mode with a session in progress must not silently discard it.** A started
session belongs to one API, and there is no migration between them. The toggle therefore
confirms before abandoning a non-empty session, on the same reasoning as every other
destructive confirm in this codebase.

### J. Card identity is never behind a hover

**Three fields — image, name, price — everywhere a card appears**: in search results, in
Coming In, and in Going Out. This extends §L's picker rule (RFC 0010) to **staged lists**,
which it did not previously cover.

The hover preview is **deleted, not restyled**. A hover is not a way of showing an image:
it needs a mouse, it shows one card at a time, it shows nothing to a person reading the
list, and it vanishes. The owner is standing at a table comparing several physical cards
against several rows at once.

Rows use the shared `CardPickerRow` shape and `TABLE_THUMB_SIZE`, so art never shrinks,
never grows, keeps 5:7 proportions and renders the placeholder on a card-less or failed
id — a row that changes height as art loads makes the list jump under the cursor mid-click.

### K. Adding a card, in one shape

```
pick a catalog card  ──or──  open manual entry (put away by default)
          │
          ▼
   [ Raw ] [ Graded ]      ← kind toggle
          │
          ├── raw:    condition, finish, language, location, cost
          └── graded: company, grade, cert #, grade label, language, location, cost
```

**Condition renders for raw only; company/grade/cert for graded only** (decision 15).

Manual entry is a **disclosure that is put away by default and stays open across adds**,
exactly as `/admin/slabs`' "Manual entry" button behaves — intake is a batch workflow, and
a control that closes after every add fights the person using it.

## API Contracts (Part 2)

| Method | Path | Change |
|---|---|---|
| `POST` | `/admin/trades/{id}/incoming` | Accepts `kind`, `company`, `grade`, `cert_number`, `grade_label`. 422 on a graded leg missing cert fields, and on a raw leg carrying them. |
| `GET` | `/admin/slabs/certs/{cert}` | Unchanged; reused by the trade incoming form. |

No other endpoint changes. `purchases.py` and `sales.py` are untouched (decision 16).

## Risks & Mitigations (Part 2)

7. **Deleting two routes breaks anything pointing at them.** Mitigation: the sidebar,
   `mobileItems`, the dashboard's three quick actions and every test referencing
   `/admin/buy` or `/admin/sell` are updated in the same task, and a test asserts neither
   path resolves.
8. **Rebuilding three money-entry surfaces at once is the largest single UI change in this
   RFC.** Mitigation: the session APIs are untouched (decision 16), so a bug has one
   possible home; and the three modes are separately testable against unchanged endpoints.
9. **A graded leg that silently loses its cert fields recreates the exact defect.**
   Mitigation: 422 in both directions rather than dropping unknown fields.
