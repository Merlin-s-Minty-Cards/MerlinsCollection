# RFC 0010: Admin Round 8 — Ledger Corrections, Triage Discipline & Slab Manual-Only

**Status:** Draft
**Author:** design-doc (main thread)
**Date:** 2026-08-10
**Scope:** 12 owner-reported issues from `The plan.pdf`, one owner-reported money-input
bug raised in review, one live merge blocker carried over from RFC 0009's T-FINAL, and
one strategy reversal — **PSA is now a paid API and is dropped entirely**. Bug-fix +
UX/API design only; nothing here is implemented yet.

## Summary

The owner drove the live admin panel and reported twelve issues. Read against the code
they group into **seven root causes**, of which five are single confirmed defects and
two are missing capabilities that need real schema work:

- **(A) A generation-scoped sort key with no sweep** forks a consignor into two rows the
  moment an admin edits one the import created — the *identical* defect `put_show` was
  fixed for in RFC 0008 T7, in a function that never got the same treatment. Everything
  else the owner reported about the Cosigners tab (edit duplicates, delete does nothing,
  "the new 85% one went to Sold") falls out of that one fork plus a status badge that
  renders a deactivated *person* with the vocabulary of a sold *card*. → §A, doc item 1.
- **(B) Triage is doing exactly what it was built to do, and that is the problem.** The
  266 rows are not a query bug: they are import-time machine flags. The queue was
  designed to reach zero and was then filled by automation with hundreds of rows a human
  cannot drain, and the reason chips are computed *twice* — once in Python to decide
  membership, once in TypeScript to decide what to display — so they can disagree. → §B,
  doc items 2 & 4.
- **(C) `CardDetailModal` renders a stale prop and its parents refetch whole lists.**
  An edit's own response — which already contains the updated item — is discarded, so
  the field the admin just changed keeps showing the old value until a refetch replaces
  the list and resets the scroll position. → §C, doc item 3.
- **(D) The same modal's layout is viewport-driven where it needed to be
  container-driven.** A `flex-shrink-0` image at `md:h-full` inside a `max-w-4xl` shell
  cannot yield space, so at higher zoom the field column collapses until an input is
  narrower than its own label and visually overlaps the next cell. → §D, doc items 5 & 7.
- **(E) `new Date("2026-08-10")` parses as UTC midnight and renders in local time**, so
  every derived date on Show Analytics is a day early while the `<input type="date">`
  beside it — which never round-trips through `Date` — is correct. → §E, doc item 8.
- **(F) The ledger has no sign, no grouping key and no correction path.** A sale and a
  purchase render identically; a five-card purchase is five unrelated rows because
  `Transaction` carries `trade_id` but nothing equivalent for a sale or buy session; and
  no endpoint anywhere can undo a recorded transaction. → §F, doc items 9, 10 & 11.
- **(G) Money inputs reject what a human types.** Raised by the owner in review: `1300`
  commits and `1,300` breaks. This is the live RFC 0009 merge blocker seen from the
  operator's side, and the naive fix is worse than the bug — `parseFloat("1,300")` is
  **`1`**, so a $1,300 slab silently books as $1. → §G.

Plus two non-defect changes: **PSA is dropped** (the cert API went paid, so the two
disabled placeholder buttons and the whole deferred lookup track become dead weight —
§H), and the **16 flat sidebar tabs get grouped** (§I, doc item 12).

## Motivation

Round 8 differs from RFC 0008 in kind. Those were mostly *absent* features. These are
mostly **things the owner tried to do and could not**, on a branch that is already
feature-complete and waiting to deploy. Two of them are money-correctness defects on
live inventory (§A forks a consignor's payout percentage; §G writes a wrong cost or
half a batch), and one — §F's missing void path — means a mis-rung sale currently has
**no correction available at all**: the item is sold, the ledger says so, and the only
recourse is editing DynamoDB by hand.

The owner also corrected the plan document during review, which is recorded here
because it changes §B's design: *"Triage is not for stickers that need updating, it is
for cards with correctness issues that need manual fixing from an admin."* The written
ask for a `sticker_needs_update` reason is therefore **withdrawn** — see §B.4.

## Detailed Design

### A. Editing a consignor forks the row (doc item 1)

**Confirmed root cause, and it is a known pattern this function missed.**
`put_consignor` (`backend/src/merlins_collection/services/dynamodb.py:1363-1370`):

```python
def put_consignor(self, consignor: Consignor):
    body = _serialize(consignor.model_dump(mode="python"))
    self._table.put_item(Item={
        "PK": "CONSIGNORLIST",
        "SK": self._gen_sk(f"CONSIGNOR#{consignor.consignor_id}"),
        "entity": "consignor", **self._gen(), **body,
    })
```

`_gen_sk` (`dynamodb.py:398-410`) suffixes the SK with the import generation, so a
consignor written by `import_consignments` lives at
`CONSIGNOR#<id>#<gen>`. An admin edit runs with **no** generation set and writes
`CONSIGNOR#<id>` — a *different* sort key in the *same* partition. The row does not
update; a second one appears.

This is verbatim the bug `put_show` documents in its own docstring
(`dynamodb.py:1232-1263`): *"every show the spreadsheet import wrote keeps its `#<gen>`
suffix after `finalize_import` commits, while an admin edit runs with no generation set.
Without the sweep below either edit forks the show into two rows."* `put_show` got the
sweep in RFC 0008 T7. `put_consignor` — same partition-with-generation-scoped-SK shape,
same admin edit path — did not.

The consignor id itself is stable and therefore **not** the fork axis:
`import_consignments` assigns `deterministic_id("Consignor", {"name": person})`
(`services/spreadsheet_import.py:756`), so re-importing Harry re-uses Harry's id. Only
the generation moves.

**Every other symptom the owner reported follows from the fork:**

1. *"editing one of the consignors creates a duplicate Harry."* Two rows, one
   `consignor_id`. The frontend does call `PATCH`, correctly
   (`frontend/app/(admin)/admin/cosigners/page.tsx:180`) — this is not a POST-instead-of-PATCH
   bug, which is the obvious wrong guess.
2. *"I can't delete the extra name."* `DELETE /admin/cosigners/{id}` is a **soft**
   delete (`routers/admin/cosigners.py:94-108`) — it sets `active=False` and writes the
   row back through `put_consignor`, which lands on the *current-generation* key. The
   import-generation row is untouched and stays in the list. `repo.delete_consignor`
   (`dynamodb.py:1384-1391`) does a real delete but **no route calls it**.
3. *"it set the new 85% one to 'Sold'."* Two causes stacked. The soft delete hit the
   row the admin's own edit created (the current-gen one, i.e. the 85% copy), and
   `StatusBadge status={item.active ? 'available' : 'sold'}`
   (`cosigners/page.tsx:317`, again at `:459`) renders a deactivated **person** using the
   inventory status vocabulary. A consignor is not sold.
4. `get_consignor` and `delete_consignor` both return/act on the **first** matching row
   in partition order (`dynamodb.py:1376-1391`), so with a fork present which Harry the
   API answers about is arbitrary.

**Fix.**

- **`put_consignor` sweeps superseded rows**, mirroring `put_show` exactly, including
  its ordering rule (write first, then delete — a crash between leaves a visible
  duplicate the next write cleans up, rather than deleting the only copy) and its
  skip-mid-import guard (coexisting generations are load-then-swap's whole point).
- **Duplicate-name guard.** `POST` and `PATCH` reject a name that case-insensitively
  matches another consignor with **409**. Explicitly per the owner's ask; scoped to
  *another* consignor so renaming Harry to "Harry" is not an error.
- **Delete is an ARCHIVE, hidden by default** (owner refinement, 2026-08-10: *"If a
  cosignor is deleted, then it is okay to archive them, but those cosignors should be
  hidden by default, and their value should be displayed as archived instead of sold.
  Maybe add a view archived button."*). `DELETE /admin/cosigners/{id}` sets
  `archived=True`; `GET /admin/cosigners` omits archived rows unless
  `?include_archived=true`; `POST /admin/cosigners/{id}/unarchive` restores. This mirrors
  `Show.archived` exactly — the house rule CLAUDE.md already documents — and **there is no
  hard delete**: the earlier draft's `purge` route is dropped, because once the fork is
  swept there is no orphan row that needs destroying. **No 409 in-use guard**, for the same
  reason shows have none.
- **`Consignor.archived`, migrated on read from `active`.** `active` already means this but
  is read almost nowhere (written at create and by the soft delete; rendered by two badges;
  no filter, no business logic). Add `archived: bool = False`, stop writing `active`, and
  map a legacy `active: False` → `archived: True` in a before-validator. The mapping is not
  hypothetical: **the owner has already soft-deleted a Harry**, so a production row carrying
  `active: False` must render as archived.
- **A one-time reconcile** for rows already forked in production. The sweep fixes the
  cause; it does not merge the two Harrys that exist today. A script, dry-run by
  default, keyed on `consignor_id`, keeping the **highest-generation** row.
- **Status vocabulary.** `Active` / **`Archived`**, not `AVAILABLE` / `SOLD`.

### B. Triage pulls 266 rows, and its filter does not narrow (doc items 2, 4)

**The query is correct.** The predicates were probed directly against the model
(`services/triage.py`, run 2026-08-10): an ordinary EN raw item with a `card_id` returns
`triage=False`; sealed and bulk return `False`; only a missing `card_id`, a non-EN item
with no `display_name_override`, or a stored `needs_review` return `True`. There is no
"pulls everything" bug in `needs_triage`.

**The 266 rows are the spreadsheet import's own flags.** `import_singles` sets
`needs_review = True` for every row where the matcher's confidence was anything but
`high`, and separately for every row with a blank condition
(`services/spreadsheet_import.py:475-484, 498-502`), stamping `review_reason` from
`MACHINE_REVIEW_REASONS` — `low_match_confidence`, `no_catalog_link`, `blank_condition`.
On a bulk import of a hand-kept spreadsheet that is most of the sheet.

So Triage is behaving as designed and the **design is wrong for how it is used**: a
queue whose stated goal is to reach zero was seeded with hundreds of machine flags and
has never been drainable. The owner's phrasing is the correct fix — *"fix so that these
cards aren't pulled unless they have a why reason"* — because what they are seeing is
rows whose reason is either invisible or not actionable.

**Four changes.**

**B.1 — The server emits the reasons it used.** Today membership is decided in Python
(`services/triage.py:66-75`) and the chips are recomputed in TypeScript
(`frontend/lib/triage.ts:60-68`) from a hand-mirrored copy of the same three rules. The
mirror is *currently* faithful — that was verified, not assumed — but it is a permanent
opportunity for a row to appear with no chip, which is exactly what the owner describes.

Fix: `GET /admin/inventory/search?triage=true` sets `triage_reasons: list[str]` on every
serialized row, alongside the `card` join it already attaches (`admin/inventory.py:255-256`).
The page renders **that array**. `reasonsFor()` stops being the display authority and is
kept only for optimistic local row updates, with a comment saying so. A row can then
never be in the list without a visible reason: the list and the chips read one value.

**B.2 — One filter parameter, not three.** The page currently maps its dropdown onto
three separate query params — `needs_review`, `missing_card_id`, `missing_english_name`
(`triage/page.tsx:67-69`) — each a distinct backend filter (`admin/inventory.py:101-107,
164-182`). Two problems: `flagged` narrows by the **stored** boolean rather than by the
predicate that produced the chip, and a **new** reason has no param at all, so the
dropdown silently cannot filter by it.

Fix: `triage_reason=<key>`, validated against `TRIAGE_REASONS` (422 on an unknown key),
applied with the same predicate that built the union. Adding a reason then means adding
one row to `TRIAGE_REASONS` and nothing else. The three existing params stay for
backward compatibility but the Triage page stops using them.

**B.3 — Machine reason keys get human labels.** `flagged` renders `item.review_reason`
raw (`triage/page.tsx:153-155`), so a row from the import reads `low_match_confidence`.
A label map over `MACHINE_REVIEW_REASONS` ("The matcher wasn't sure", "No condition on
the imported row", …) with free-text admin notes still passed through verbatim.

**B.4 — NO sticker reason. Owner decision, 2026-08-10.** The plan document asks for an
additional reason, "sticker needs to be updated". Asked to choose between a stored and a
derived form, the owner reframed the question: *"Triage is not for stickers that need
updating, it is for cards with correctness issues that need manual fixing from an
admin."* The reason is therefore **not built**, and Triage's reason set stays at the
three correctness reasons. The need it described is already served by **Prep Queue**,
which *is* the unstickered-inventory list, and which §J makes filterable by location.

**B.4a — `blank_condition` is a MONEY defect, not queue noise.** Found while planning: the
importer defaults a missing condition to `Condition.NM` and flags the row
(`services/spreadsheet_import.py:437-443`, *"default NM but flag it rather than drop"*). NM is
the **most expensive** tier, and every customer-facing price is scaled down from it
(`services/condition_pricing.py` — LP ×0.82, MP ×0.58, HP ×0.33, DMG ×0.15). So a card whose
real condition is LP is shown to a buyer at **1.22×** its value, an MP card at **1.72×** —
wrong in the business's favour, which is the precise failure the condition-pricing work
exists to prevent.

So this reason must be **easy to filter to and easy to fix in place** (a third repair tool: an
inline condition control beside "Assign English name" and "Re-point"), and it must be
**excluded from any bulk clear**. Clearing it in bulk would silently ratify an NM price on
every card nobody has checked.

**B.4b — The importer will not run again.** Owner, 2026-08-10: *"We will most likely never run
the importer again. That was a one time thing, but we are actively reviewing and adding cards
to match the sheet until we will eventually drop the sheet altogether."*

Two consequences: **nothing refills the queue**, so a cleared flag stays cleared and draining
Triage is a one-way job rather than a treadmill; and **Triage is now the primary
reconciliation workflow** rather than a janitorial afterthought. That closes the RFC's original
open question about changing the importer's flagging — **do not touch the importer**, it would
be dead code with a live blast radius — and it shifts the emphasis of §B.5 from bulk clearing
toward filtering, searching (§B.6) and fixing in place.

**B.5 — Making the queue drainable.** Two supporting changes, both needed for "reaches
zero" to be a real goal rather than a slogan:

- **Status scope.** `triage=true` applies no status filter, so a `sold` card's data
  quality sits in a worklist forever. Default to non-terminal statuses with an
  "include sold" toggle.
- **Bulk clear of machine flags, with `blank_condition` excluded.** A single action clearing
  `needs_review` for a filtered cohort whose only reason is `flagged` with a
  `MACHINE_REVIEW_REASONS` value — **except `blank_condition`**, per §B.4a. The existing
  per-item clear already stamps `reviewed_at` server-side and `_apply_review_transition`
  (`admin/inventory.py:1103-1147`) already prevents automation re-flagging a reviewed item, so
  the bulk path inherits the anti-rot guarantee for free.

**B.6 — Search bar (doc item 4).** `GET /admin/inventory/search` already takes `name`
(`admin/inventory.py:93`) and already matches display name, product name, description
and notes (`_matches_name`, `admin/inventory.py:1010-1028`). Frontend-only: a debounced
`SearchInput` (the shared component the other admin lists use) added to the existing
`params` record. Nothing new on the backend.

### C. Edits do not appear until a reload (doc item 3)

**Confirmed root cause: the response is thrown away and the prop is stale.**
`CardDetailModal.saveEdit` (`frontend/components/admin/shared/CardDetailModal.tsx:202-205`):

```ts
await api.put(`/inventory/${item.item_id}`, payload)   // ← return value discarded
setEditingField(null)
onUpdated?.()
```

`PUT /admin/inventory/{item_id}` returns the **full updated item**
(`admin/inventory.py:312-...`, via `_serialize_item`). The modal discards it and renders
`item`, which is a prop — and every parent passes an object out of its *list* state
(`triage/page.tsx:51, 287`; the same shape on inventory, outgoing, sell, show-prep,
vault). `onUpdated` triggers a whole-list refetch, which replaces the array but **not**
the `detailItem` the modal is rendering. So the edited field shows its old value until
the modal is closed and re-opened — and the refetch re-mounts the table, which is the
"resets you to the top of the menu" half of the report.

**Fix — two changes, both small, and they fix the scroll reset as a side effect.**

1. The modal keeps the item in local state, seeded from the prop and **replaced by the
   PUT response**. The displayed value updates from the server's own answer, so it can
   never claim a save that did not land.
2. `onUpdated` gains the updated item: `onUpdated?.(updated)`. Parents patch the one row
   in place instead of refetching the list, which keeps scroll position and list order.
   All six mounting pages are updated; the parameter is optional so a parent that still
   wants a refetch is not broken.

### D. The detail modal is unusable at higher zoom (doc items 5, 7)

**Confirmed root cause: an unyielding image column in a fixed-width shell.**
`CardDetailModal.tsx`:

- the shell is `max-w-4xl h-[90vh]` (line 271) — capped at 896px however large the
  display, so zooming in shrinks the *available* width without the modal ever growing;
- the image column is `flex-shrink-0` (line 405) holding an `img` at
  `h-64 md:h-full w-auto object-contain` (line 410). At `h-full` inside a 90vh shell a
  5:7 card claims ≈0.71 × 90vh of **width**, and `flex-shrink-0` means it never gives any
  of it back. The details column gets the remainder;
- the fields grid is `grid-cols-1 sm:grid-cols-2` (line 466) keyed off the **viewport**,
  not the column, so it stays two-up no matter how narrow the column gets, and each cell
  carries a fixed `w-24` label (line 489). Once a cell is under ≈200px the label owns
  most of it and the input is squeezed to near-zero width.

That is the reported symptom precisely: *"when I try to edit the finish field it puts
characters into the factory sealed label and the box to add text is very small."* The
input has not moved into the neighbouring cell — it has been compressed until it renders
beside the adjacent label.

Doc item 7 (Show Prep) is the **same component** — `/admin/show-prep` mounts
`CardDetailModal` like the other five pages — at a different zoom level, not a second
bug. There is no show-prep-specific modal.

**Fix.**

- **Widen the shell and let it scale:** `max-w-6xl xl:max-w-7xl`, `h-[92vh]`.
- **Cap the image, and let it yield.** Give the image column an explicit upper bound
  (`md:max-w-[min(34%,20rem)]`) and drop `flex-shrink-0` in favour of `min-w-0` on both
  columns, so the details column has a floor.
- **Make the field grid container-driven, not viewport-driven.**
  `[grid-template-columns:repeat(auto-fit,minmax(17rem,1fr))]` — the grid collapses to
  one column whenever a cell would be narrower than 17rem, at any zoom, with no
  breakpoint to tune.
- **Stack label over value in a narrow cell** instead of a fixed `w-24` beside it.

Verified at 100 / 150 / 200% zoom on **triage, show-prep and inventory** before it is
called done. A test can assert the classes; only a human can confirm the field is
typeable.

### E. Show Analytics dates are one day early (doc item 8)

**Confirmed root cause: the UTC-midnight parse.**
`frontend/app/(admin)/admin/analytics/page.tsx:78-84`:

```ts
function formatDate(dateStr: string): string {
  const d = new Date(dateStr)                       // "2026-08-10" → UTC midnight
  return d.toLocaleDateString('en-US', { … })       // rendered in LOCAL time
}
```

ECMA-262 requires a bare `YYYY-MM-DD` to be parsed as **UTC**; `toLocaleDateString`
formats in the browser's zone. At any negative UTC offset — every US timezone — UTC
2026-08-10T00:00Z is the evening of **Aug 9** locally. Hence "Aug 10 shows as Aug 9",
while the `<input type="date">` next to it (line 498) is correct because it binds the ISO
string directly and never constructs a `Date`.

`formatDate` renders the transaction date (line 106), the selected show (line 376) and
every show in the archive list (line 685) — so **every** date on that page is a day
early. The same construct is duplicated in
`frontend/app/(admin)/admin/card/[id]/page.tsx:86` and
`frontend/components/admin/shared/PriceChart.tsx:90`.

**A second, live bug, found while answering the timezone question.**
`new Date().toISOString().split('T')[0]` — the default date on Buy (`buy/page.tsx:50, 274`),
Sell (`sell/page.tsx:62, 239`), Trade (`trade/page.tsx:80`) and the dashboard (`page.tsx:69`) —
returns the **UTC** date. Measured: at 6:30pm Pacific on Aug 10 it yields **`2026-08-11`**. So
**every transaction entered after 5pm Pacific defaults to tomorrow**, landing in the wrong day's
analytics and potentially against the wrong show. For a business that sells at evening card
shows, that is most transactions. It is in scope for the same task — same root cause, a date
derived through a UTC boundary.

**Owner's rule, 2026-08-10:** *"use the local time if possible, but otherwise default to PST
time as that is where we are all located."*

**Fix.** One shared module, `frontend/lib/dates.ts`, keeping the three cases distinct because
they barely interact:

| case | rule |
|---|---|
| **date-only** (`"2026-08-10"`) | Carries no timezone at all once you stop routing it through `new Date()`. `formatISODate` splits the string and formats the parts — correct in every zone |
| **timestamps** (`voided_at`, slab `updated_at`) | Real instants. Pass no `timeZone` so the browser uses its own; name a fallback zone only where there is no browser (SSR, tests) |
| **"what is today"** | `todayLocal()` — the user's zone, falling back to Pacific. Never `toISOString()` |

**`BUSINESS_TIME_ZONE = 'America/Los_Angeles'` — an IANA name, never a fixed `-08:00`.**
Measured: Pacific is **PDT (−7)** in August and **PST (−8)** in January, so a hardcoded −8 would
be wrong from March to November — roughly eight months a year, including every summer show.

Every call site above uses the helper; a comment records why `new Date(isoDateString)` is banned
for date-only values. `SlabList`'s `new Date(iso)`
(`components/admin/slabs/SlabList.tsx:32`) is a **timestamp** and stays as it is.

The regression tests **must pin a negative-offset timezone** (`process.env.TZ` / `vi.stubEnv`)
and, for `todayLocal`, **fake the clock** — otherwise they pass in UTC CI while both bugs are
live in Portland.

### F. The ledger has no sign, no grouping and no undo (doc items 9, 10, 11)

#### F.1 Signed amounts (doc item 9)

`amount` renders through `PriceDisplay value={t.amount}` with no sign
(`analytics/page.tsx:120-127`), and `Transaction.amount` is stored unsigned with
direction carried by `type` (`models/business.py:36-48`). A $200 purchase and a $200
sale are visually identical.

**Fix.** A shared signed-money renderer keyed on `TransactionType`: sale → `+$200.00`
in mint, purchase → `−$200.00` in red/amber, with the sign as **text** and not colour
alone (colour is not an accessible carrier). Applied to the analytics transaction table
and the History page. Stored data is unchanged — this is a presentation rule, and
inverting it in storage would silently change every existing aggregate.

Trade cash legs need care: `is_trade_cash_leg` already exists
(`routers/admin/analytics.py`, used at line 366) and the daily dashboard already excludes
them from sell-through. The archive shows them by design, so their sign follows their
`type` like any other row.

#### F.2 Grouping a multi-card transaction (doc item 10)

**Confirmed: there is no grouping key to group by.** `Transaction`
(`models/business.py:36-48`) carries `trade_id` — so trade legs *can* be grouped — but
nothing equivalent for a sale or buy session. `confirm_buy_session` loops
`repo.put_transaction(txn)` per item (`routers/admin/purchases.py:328`) and
`confirm_sale_session` loops `repo.record_sale(txn)` (`routers/admin/sales.py:292`); the
resulting rows share only a `date` and a `payment_method`.

**Fix — a real, small schema addition.** `Transaction.batch_id: str | None = None`,
written by all three confirm paths with the session id that produced it (`buy_id`,
`sell_id`, `trade_id`). Then:

- `GET /admin/transactions` returns rows as today (it is an archive; nothing is
  filtered out) and the **frontend groups** by `batch_id`, rendering one summary line —
  `Purchase · 5 cards · −$200.00` — expandable to the legs.
- Rows with `batch_id = None` render as single-row groups. **Historical rows are not
  backfilled**, and a same-day/same-method heuristic is explicitly rejected: two separate
  cash sales on one show day are indistinguishable from one two-card sale under that rule,
  and a wrong grouping in a money view is worse than no grouping.

Server-side grouping was considered and rejected — see Alternatives.

#### F.3 Voiding a transaction (doc item 11)

**Confirmed gap: nothing can undo a transaction.** No `DELETE`, no void, no edit exists
on any transaction route (`grep` over `routers/admin/` returns deletes only for session
line-items, locations, cosigners and inventory items). `record_sale`
(`dynamodb.py:1174-1207`) writes the ledger row and flips the item to `sold` in **one**
`transact_write_items`, condition-guarded on the item not already being sold — so undoing
a sale is a two-part reversal, not a row delete.

**Owner decision, 2026-08-10: void with an audit trail, not a hard delete.** This
matches the precedent already in the codebase — Shows "delete" is an archive because
nothing that analytics has counted may ever dangle (CLAUDE.md, RFC 0008 Q6).

**Design.**

- `Transaction` gains `voided_at: datetime | None`, `voided_by: str | None` (the admin's
  Cognito subject, **server-stamped** — a client's claim about who voided a sale is not
  evidence) and `void_reason: str | None` (bounded, like `review_reason`).
- `POST /admin/transactions/{txn_id}/void` — body carries the reason. Reverses
  atomically: stamp the ledger row **and** restore the item's status in one
  `transact_write_items`, mirroring `record_sale`'s shape so the two halves can never
  disagree. A sale restores `sold → available`; a purchase reversal is different in kind
  and is scoped in Open Questions.
- `POST /admin/transactions/{txn_id}/restore` — un-voids. Archiving that cannot be undone
  is just a slower delete (the phrasing `unarchive_show` already uses,
  `routers/admin/analytics.py:244-245`).
- **Every aggregate excludes voided rows.** `summarize_transactions`, `sell_through_rate`,
  `starting_inventory`, `daily_analytics`, the show snapshot generator and the dashboard.
  This is the risk surface: a void that some aggregates honour and others do not is worse
  than no void at all, so the exclusion goes in **one** predicate that every reader calls,
  and the task's test list names each reader explicitly.
- **Show analytics snapshots are stored, not derived** (`put_show_analytics`,
  `dynamodb.py:1277`). A void therefore leaves any already-generated snapshot stale. The
  snapshot is marked stale and the UI offers to regenerate — silently rewriting a
  point-in-time record is the wrong move, and silently serving a wrong one is worse.
- Voiding a member of a `batch_id` group offers **"void the whole transaction"** as the
  primary action (F.2 is a prerequisite for this being coherent) with per-leg void
  available for a partial correction.
- The item's timeline event is **not** deleted; a `voided` event is appended. The
  timeline is a history, and history includes the mistake.

### G. Money inputs reject what a human types

**Two facts, both confirmed, and they point the same way.**

**G.1 — The live merge blocker.** `SlabEntryForm`'s Cost field is free text —
`<input aria-label="Cost" inputMode="decimal">`
(`frontend/components/admin/slabs/SlabEntryForm.tsx:257-263`) — and `inputMode` only hints
the mobile keyboard; it constrains nothing. Validation is `!cost.trim()`
(line 130), so `1,300` and `$40` both pass. Then `Number("1,300")` → `NaN` →
`JSON.stringify` → **`buy_price: null`** (`slabs/page.tsx:82`); `add_buy_item` only checks
`"buy_price" not in body`, so `null` returns **200**; then `confirm_buy_session` does
`Decimal(str(None))` → `InvalidOperation` → **unhandled 500** — *after* the loop has
already written `put_inventory_item` + `put_transaction` + `put_timeline_event` for every
earlier row. There is no rollback and `status` is set to `confirmed` only after the loop.

A five-slab batch with a comma in row 3 leaves rows 1–2 as **real inventory with real
purchase transactions**, the session stuck in `draft`, and the UI reporting *"Nothing was
created; the batch is intact"* — which is false. The operator's natural response is to
press Commit again, duplicating rows 1–2. `StagingTable` renders the raw string, so
`1,300` displays as a correct-looking `$1,300` with no signal before commit. This is
recorded as the RFC 0009 T-FINAL merge blocker
(`docs/plans/rfc-0009/progress.md`, Blocked table).

**G.2 — The owner's requirement rules out the obvious fix.** The recommendation on file
was `type="number" step="0.01"`. The owner's review comment — *"typing 1,300 for cost
will break the commit, but typing 1300 is accepted. Both should work"* — rules that out:
a native number input does not accept a comma at all, so `1,300` would become
un-typeable rather than correct. **The input must parse, not restrict.**

And the naive parse is a worse bug than the one it fixes. Measured 2026-08-10:

| input | `Number(v)` | `parseFloat(v)` |
|---|---|---|
| `1300` | `1300` | `1300` |
| `1,300` | `NaN` | **`1`** |
| `1,300.50` | `NaN` | **`1`** |
| `$40` | `NaN` | `NaN` |
| `1.2.3` | `NaN` | `1.2` |
| `""` | `0` | `NaN` |

`parseFloat` stops at the comma and returns **1**, and it is not `NaN`, so it survives
every `isNaN` guard in the codebase. Swapping `Number` for `parseFloat` in the slab form
would turn a loud 500 into a silent $1,299 loss.

**Slabs is the only free-text money field**, which is why this has not bitten elsewhere:
Buy (`buy/page.tsx:563, 569`), Sell (`:488, :517`), Prep Queue (`outgoing:275, :439`),
Show Prep (`show-prep:279, :423, :509`) and `InlineEditCell` (`:135`) are all
`type="number"`, and the browser refuses the comma keystroke. That consistency is what
makes fixing only Slabs the wrong shape of fix: it would be the one field that accepts
`1,300` while the rest silently swallow the keystroke.

**Fix.**

- **`parseMoney(raw): number | null`** in `frontend/lib/money.ts`. Strips `$`,
  whitespace and thousands separators; accepts `1300`, `1,300`, `$1,300.50`, ` 40 `;
  returns `null` — never a guess — for `1,30`, `1.2.3`, `abc`, `""`. **Never** uses
  `parseFloat`. Rejecting ambiguity is the point: a misplaced separator must not resolve
  to a plausible wrong number.
- **A `MoneyInput` component** wrapping a text input with `inputMode="decimal"`, which
  normalizes to canonical form on blur, exposes the parsed value, and renders an
  inline "that isn't a number I can read" state that disables the action.
- **Backend guard, independent of the client.** `add_buy_item` validates `buy_price` is
  present and finite, returning **422 at add time** — matching the precedent that graded
  field validation happens at add, not confirm, so a bad row cannot lose the staged batch
  (RFC 0009 T3 decision, 2026-08-08).
- **`confirm_buy_session` validates every row before writing any.** This is the only
  change that fixes **partial write as a class** rather than this one trigger, and the
  T-FINAL writeup names it as such. Given §F.3 is being built precisely because the
  ledger had no correction path, spending the extra work here rather than filing it is
  the right call.
- **Rollout.** Slabs first, as the merge blocker. Then `MoneyInput` replaces the
  `type="number"` money fields on Buy, Sell, Trade, Prep Queue, Show Prep, Market and
  Cosigners, so `1,300` works everywhere and the `parseFloat` call sites go away.

A latent divergence found alongside, worth fixing in the same sweep: Prep Queue and Show
Prep **parse one value and send another** — they guard on `parseFloat(stickerValue)` then
`PUT { sticker_price: stickerValue }`, the raw string (`outgoing/page.tsx:140-150`,
`show-prep/page.tsx:133-138`). Harmless while the input is `type="number"`; a live bug the
moment it is not.

### H. PSA is dropped (owner decision, 2026-08-10)

**The cert API went paid, so the last reason to keep the placeholders is gone.** Until
now the position was "403 at the account, remedied by an approval email"
(`docs/plans/rfc-0009/progress.md`, re-confirmed 2026-08-10 against PSA's Swagger with
both bearer spellings). A paid API the owner has declined changes that from *deferred* to
**withdrawn** — the same call already made about PriceCharting on 2026-08-07.

**What is removed:**

- `/admin/slabs`' two disabled buttons — **Camera scan** and **Auto-fill from cert** —
  and the `#psa-blocked` explanatory note (`slabs/page.tsx:145-171`). They were rendered
  disabled *on purpose*, so the gap read as known rather than forgotten; with the gap now
  permanent, they are clutter that implies a roadmap that does not exist.
- RFC 0009 **T2** (PSA lookup + quota) and **T5** (camera scan) move from `DEFERRED` to
  **WON'T DO**, with the reason recorded rather than the docs deleted.
- `PSA_API_KEY` disappears from `backend/.env.example` and the docs. It is read by **no
  code** — there is no `psa_api_key` field on `Settings` and `extra="ignore"` swallows it —
  so this is a documentation removal with no behavioural change, and
  `test_config.py::test_there_is_still_no_psa_setting_to_configure` already guards it.
- Every doc claiming PSA is pending approval is corrected: CLAUDE.md "Third-Party APIs",
  RFC 0009 §5.1/§7/§8/§9, its progress and follow-up files.

**What is NOT removed — read this before touching `CertInput`.** The cert number stays
**required**: without one it is not a slab, it is a normal card, and
`GradedInventoryItem.cert_number` is `str`, not `str | None`. The `CERT#` pointer row and
`GET /admin/slabs/certs/{cert}` duplicate warning stay: they never depended on PSA.

### I. Slab intake: scanner affordance hidden, price at intake (owner ask, 2026-08-10)

The owner's requested flow: **enter a cert number → match to a catalog card → manual
entry if there is no match → send to the pricing API for a market price.** Three of those
four steps already exist; the fourth is new.

**I.1 — Hide the scanner affordance, keep the scanner working.** The owner's reasoning is
exactly right: *"all the scanner does is essentially type the number when it scans so it
could just be used in the normal input box anyway."* That is why `CertInput` was built
with **no scanner detection and no timing logic** in the first place. So the **Scan cert**
button and the `armed` / "waiting for scan" state go, along with `focusToken`'s arm path.

**The behaviour that must NOT go:** `CertInput`'s `onEnter` handler (Enter *advances*
focus, never submits) and its trailing `\r\n` stripping. A wedge scanner ends its burst
with Enter; if that submitted, or if the `\r` rode into a URL path, wedge scanning would
break — and it would break invisibly, because hand-typing would still work. "Hide the
scanner UI" must not be read as "remove the Enter handling". The existing regression test
(*characters typed one at a time over a long span are exactly as valid as a burst*) stays.

**I.2 — Price a slab at intake.** Today `attach_price` runs only from the nightly
`run_daily_sync` and from `POST /admin/slabs/refresh-prices`
(`routers/admin/slabs.py:313`), so a freshly-committed slab has no value until the next
night.

The cheap and correct implementation is to **reuse the existing refresh**, not to write a
second pricing path. `refresh_graded_prices` (`services/catalog_sync.py:226`) already
walks owned slabs **never-priced-first**, so a slab committed a second ago is already at
the head of its queue. What is needed:

- `POST /admin/slabs/refresh-prices` accepts an optional `item_ids: list[str]`, and
  `refresh_graded_prices` an `only_item_ids` filter — otherwise a 3-slab batch spends the
  day's whole 50-lookup budget re-checking the shelf.
- After a **successful** commit, `/admin/slabs` fires that scoped refresh and polls
  `/refresh-prices/status` — the Market page's existing polling UI is the precedent.

**Pricing is never in the commit's critical path.** The commit finishes, the batch
clears, *then* pricing runs. §G exists because a money write blew up mid-loop; putting a
metered third-party HTTP call inside the same loop would rebuild that failure with a
worse trigger. A vendor 500, a spent quota or a 409 ("a refresh is already running")
degrades to "committed, not yet priced" — which is a state the product already models,
at `/admin/slabs?priced=false`.

**I.3 — An unmatched slab stays unpriced, and that is the owner's decision.** The
verified-join rule is unchanged: a price attaches only when the vendor's
`externalCatalogId`, read as `en:<id>`, equals the item's own `card_id`
(`services/slab/pricing.py:451-500`). So the manual-entry fallback the owner asked for
is, by construction, **unpriceable** — no `card_id`, no join, no price. Offered the three
options, the owner chose to keep the rule: the vendor's name search was measured wrong
roughly one time in three, and a wrong price looks exactly like a right one. Japanese
slabs carry no `externalCatalogId` at all and are unpriceable for the same reason. Both
surface at `/admin/slabs?priced=false`; neither is Triage-flagged (owner decision,
2026-08-09 — and consistent with §B.4's ruling on what Triage is for).

**Quota, stated plainly:** the free tier is 100 credits/UTC day and a graded lookup costs
2, so **50 lookups a day, total, shared with the nightly job.** A 30-slab intake day
consumes 60% of it. The scoped refresh is what keeps that honest; the run summary already
reports credits remaining.

### J. Prep Queue: sort and filter by location (doc item 6)

**Both halves already exist on the backend.** `GET /admin/inventory/search` accepts
`location` (`admin/inventory.py:92`) and `_sort_admin_results` supports `location_asc` /
`location_desc` (`admin/inventory.py:1031-1078`). `DataTable` supports controlled sorting
via `sortKey` / `sortDir` / `onSort` (`components/admin/shared/DataTable.tsx:18-35`).

The Prep Queue page wires **none** of it: its `location` column carries no
`sortable: true` and the page passes no `sortKey`/`onSort`
(`outgoing/page.tsx:225, 292, 461`). Frontend-only.

**Fix.** Make the location column sortable and wire the sort through to the existing
`sort` param; add a location filter dropdown from `useLocations()` — never a hardcoded
list. The owner's stated need — *"we often just price glass in certain cases"* — is served
better by the filter than by the sort, so both ship; the filter is the primary control.

### K. Grouped sidebar navigation (doc item 12)

Sixteen flat entries in `navItems` (`components/admin/AdminShell.tsx:30-47`). The owner
asked for larger tabs holding sub-tabs, offering "Show" (inventory, buy, sell, trade,
slabs) as an example, and chose the grouping below on 2026-08-10:

| Group | Tabs |
|---|---|
| *(top level)* | Dashboard |
| **At the show** | Inventory · Sell · Buy · Trade · Slabs |
| **Back office** | Prep Queue · Show Prep · Shows · Triage · Market · Vault |
| **Data** | Show Analytics · History · Cosigners · Locations |

Grouped by *when you use them*, which is why Inventory sits with the transaction tabs
rather than with Vault.

**Constraints the change must respect:**

- **Every route path is unchanged.** No redirects, no renames. `/admin/outgoing` keeps
  its misleading path (CLAUDE.md's documented gotcha) — relabelling the URL is a separate
  decision and would break bookmarks.
- The **Triage badge** keeps working, and must remain visible when its group is
  collapsed — a count nobody sees is the failure mode the badge was built to avoid. The
  group header carries the badge when collapsed.
- The **collapsed sidebar** (60px, icon-only) still has to work. Group headers become
  dividers or tooltip-only in that state.
- `isActive` is a `pathname.startsWith` test; the group containing the active route
  starts **expanded**, and expansion state persists in `localStorage` under a versioned
  key.
- The **mobile bottom nav** takes `navItems.slice(0, 5)` (line 166). Flattening a nested
  structure with `.slice(0, 5)` silently picks whatever is first — the mobile list becomes
  an explicit array of five so it cannot drift.

### L. A card is never identified by name alone (owner rule, 2026-08-10)

> *"when trying to search through the catalog in the triage page, it is very hard to not have
> the image of the card displayed with the names… it should be a clear rule going forward in all
> work on this project, that when searching for a card, name alone is not sufficient, it needs
> to have an image."*

**Confirmed, and the data is already there.** `CatalogCard.images`
(`models/catalog.py:91`) is populated, and `GET /admin/market/search` serialises it with
`c.model_dump(mode="json")` (`routers/admin/market.py:121`). A picker without art is not missing
data — it is discarding data it was handed. **No backend change.**

Audited: five surfaces search the catalog, and **two already do it right**.

| Surface | Image? |
|---|---|
| Buy — catalog autocomplete (`buy/page.tsx:418-440`) | ✅ **the reference row** |
| Trade — incoming search (`trade/page.tsx:538-562`) | ✅ |
| Triage — both repair dialogs (`triage/page.tsx:597-633`) | ❌ name + `card_id` only |
| Slabs — card picker (`SlabEntryForm.tsx:91-110`) | ❌ |
| Market — watchlist add (`market/page.tsx:269, 470`) | ❌ |

Three were built *from* Buy's pattern and dropped the image on the way. That is the diagnosis
that determines the fix: **one shared `CardPickerRow` with five callers**, not three more copies
of the same JSX.

Why it is a rule and not a preference: Pokémon names collide relentlessly across sets, printings,
finishes and languages, so a list of names is a list of things the operator cannot tell apart —
and on Triage's `missing_english_name` queue the name is in Japanese, so a name-only picker asks
someone to choose between rows they cannot read.

**The layout half of the ask is part of the requirement**, not a bonus: *"the UI has to be
thought about so that adding an image next to the name is still readable, not squished into a
page, and looks very clean from a design perspective so that users can do things as quickly as
possible."* So the row truncates the name rather than displacing the image, keeps real card
proportions, renders a placeholder (never a collapsed row) when art is missing so the list cannot
jump under the cursor mid-click, and the containing dropdown/dialog is widened to fit — Triage's
`Dialog` is `max-w-lg` today, which is too tight for art.

**This is now a standing rule in CLAUDE.md** ("A CARD IS NEVER IDENTIFIED BY NAME ALONE"), not
only a task. A task fixes five files; the rule fixes the sixth picker nobody has written yet.

### M. Pricing a card with no catalog match (owner question, 2026-08-10)

> *"what do we do when we have a card that doesn't have a matching catalog card? We still are
> selling it and we need a price for it as well as updating the sticker."*

**The capability already exists. What is missing is that nothing surfaces it.** Three confirmed
facts:

1. **A hand-typed value is safe.** `refresh_inventory_market_values` skips any item with
   `card_id is None` (`services/catalog_sync.py:395-397`), so the nightly denormalizer never
   overwrites it. This is the load-bearing fact — without it, manual valuation would be a lie.
2. **The item is still customer-visible and sellable.** `_is_customer_visible` gates on status
   and location, not `card_id`; `CardTile` falls back to `item.listed_price` when there is no
   catalog card.
3. **The sticker never depended on the catalog.** `sticker_price` is hand-typed on Prep Queue and
   Show Prep for every item.

**Four real gaps:**

- **No route from the problem to the fix.** Triage's `missing_card_id` queue offers *Assign
  English name* and *Re-point*, both of which assume a catalog card exists to point at. For a
  card genuinely absent from the catalog, neither applies and the row is undrainable by
  construction.
- **The condition multiplier is NOT applied to a hand-typed value.** For a linked item
  `apply_condition_adjustment` bakes it into `current_market_value` at sync
  (`catalog_sync.py:408-411`) and CLAUDE.md warns that adjusting it again applies it twice. For an
  unlinked item nothing runs, so whoever types the number must type the **condition-appropriate**
  number — and the UI has to help, or an NM comp typed on an MP card overprices it ~1.7×, the same
  failure as §B.4a.
- **An unlinked graded slab has nowhere to store a graded price.** Those rows are keyed
  `CARD#<card_id>` / `GRADEDPRICE#…`, which is why `PUT /admin/slabs/{id}/price/pin` already
  404s with *"not linked to a catalog card, so it has no price row to pin"*. The item's own
  `current_market_value` is the only place a value can live.
- **Coverage reporting collapses two truths into one.** `/admin/market`'s coverage panel and
  `/admin/slabs?priced=false` both answer "what needs a price?". A hand-valued card **has** one
  and should stop nagging — but it is not *market-derived* coverage either.

**Design: a derived "manually valued" concept, not a new field.** An item is manually valued when
it has a value and no `card_id` — already exactly the set the nightly job skips, so it cannot go
stale. `value_note` (already on the model, already used to record the condition multiplier)
carries the provenance. Then: a fourth Triage repair tool that takes a value through T0's
`MoneyInput` and *shows the condition multiplier*; a "not in catalog — value is hand-set" marker
on Prep Queue and in `CardDetailModal`; and a third coverage category so the numbers stay honest.

**Explicitly out of scope:** creating local catalog rows for cards TCGdex does not carry (a much
larger feature — identity, images, set membership, sync interaction), and auto-pricing an unlinked
card off a name search, which the owner has now declined twice.

### N. Every catalog card is re-priced weekly, by Friday (owner ask, 2026-08-10)

> *"the reason I want this is because it would be helpful when searching for catalog cards to see
> not only the name and image, but also the price… I want to make it so that the entire catalog
> has recorded/updated a new price by friday of each week. However the work is split up is up to
> you."*

§L and §N are **one story**: the display work is trivial because `CatalogCard.prices` is already
in the search response, but for ~31,300 of the 31,603 rows that dict is **empty** — the nightly
TCGdex depth pass is scoped to cards the business currently owns (`_held_card_ids`,
`services/catalog_sync.py:446-472`, ~300 cards). The picker can render a price the moment §L
lands; there is nothing to render until §N fills them in.

That scoping is backwards for the Buy table: the cards you need a price for are the ones somebody
is trying to sell you — cards you do **not** own yet. RFC 0008 §C already flagged the gap.

**Measured 2026-08-10, and the design follows from these numbers:**

| fact | value |
|---|---|
| TCGdex per-card latency, warm | **162 ms** (5 requests; the 598 ms first was connection setup) |
| courtesy delay between requests | 100 ms (`request_delay_seconds=0.1`) |
| **effective cost per card** | **~262 ms** |
| catalog lock TTL | **3600 s** (`_LOCK_TTL_SECONDS`, `dynamodb.py:326`) |
| whole catalog, serial | **~2 h 18 min** |
| extra DynamoDB cost | **~$2.40/month** — not a factor |

**A nightly full-catalog pass is rejected, and not because of time or money.**
`refresh_held_prices` holds the catalog lock for its whole run, so a 2 h 18 min pass **outlives
its own 1-hour TTL** — at which point the lock looks like a crashed holder and becomes stealable,
and its docstring states the consequence: *"A depth-pass write that lands after a reseed has
passed that card but before its finalize carries the superseded generation and is swept — the card
silently disappears from a live catalog."* Losing catalog rows is far worse than a stale price.

**Design: a rolling weekly cycle, ~5,500 cards/night, stalest-first.** 31,300 unheld cards ÷
5,500 = **5.7 nights**, so a cycle starting Saturday completes Thursday and **Friday is slack** —
which is what makes "by Friday" survive a bad night rather than merely being true when nothing
goes wrong. 5,500 × 0.262 s ≈ **24 min**, giving **2.5× headroom** under the lock TTL, so no lock
heartbeat is needed. One lost night is absorbed on Friday (24 min); two are (48 min); three would
exceed the TTL, which is the documented ceiling and the reason for the runtime guard below.

**Ordering needs no schema change.** `CatalogCard` already carries `last_synced_at` (required) and
`detail: Literal["brief","full"]`. The predicate is **`brief` rows first** (never priced at all),
then `full` rows by `last_synced_at` ascending. This is the same shape `refresh_graded_prices`
already uses — never-priced first, then stalest, capped at a nightly budget (RFC 0009 T7) — and
reusing it is deliberate.

⚠️ **`last_synced_at` is bumped by ANY write, including the breadth pass**, so a `brief` row
written by `sync_new_sets` yesterday looks *fresh* while having no price. That is why `detail` is
checked **first** rather than as a tiebreak.

Held cards are **excluded** (the daily pass covers them, and fetching a card twice in one night is
waste). Stalest-first means an aborted night strands nothing: those cards stay stale and tomorrow
picks them up, with **no cursor to corrupt**. Two additions keep it honest: a **hard runtime cap**
so a mis-set constant cannot blow the lock TTL, and two numbers on `/admin/market`'s coverage
panel — how many `full` rows are older than 8 days (healthy value: **0**, and this is the auditable
form of "by Friday") and how many rows are still `brief`.

**§L's display rules lead with the absent cases for this reason.** `detail: "brief"` means *we
have never fetched a price*; `full` with no band means *no provider covers this card*. The model
preserves that difference deliberately, and an absent price is **never** rendered as `$0.00` —
`FinishPrice` bands are only written when a provider published a figure. The displayed figure is
chosen **server-side** by `_market_price(card, "normal")`, whose fallback walk is inherited for
free; a fifth reimplementation of that walk in TypeScript is exactly how 174 of 213 live items
once went unpriced.

## Data Schemas

**`Transaction`** (`backend/src/merlins_collection/models/business.py:36-48`) — four new
fields, all optional, all defaulting to the current behaviour so existing rows validate
unchanged:

```python
class Transaction(BaseModel):
    ...
    trade_id: str | None = None
    # NEW (F.2) — the session that produced this row: buy_id, sell_id or trade_id.
    # Lets a five-card purchase render as ONE line. None on every row written
    # before this field existed; deliberately NOT backfilled (see §F.2).
    batch_id: str | None = None
    # NEW (F.3) — a void, never a delete. Every aggregate must exclude a voided
    # row through the ONE shared predicate; see the risk note below.
    voided_at: datetime | None = None
    voided_by: str | None = None                              # server-stamped
    void_reason: str | None = Field(default=None, max_length=500)
```

**`Consignor`** (`models/business.py:134-142`) — one new field, replacing an existing one:

```python
class Consignor(BaseModel):
    ...
    # NEW (§A) — "deleted" in the admin UI, and nothing is ever destroyed. Named to
    # match Show.archived, which is the house rule CLAUDE.md documents. REPLACES
    # `active`, which meant the same thing under a worse name and was read almost
    # nowhere; a before-validator maps a legacy `active: False` to archived=True,
    # because production already holds such a row.
    archived: bool = False
```

`active` stays *accepted* on input (mapped, then ignored) so no old payload 422s, but nothing
writes it. Two live fields meaning the same thing is how the next reader introduces a bug.

**`InventoryItem`** — no schema change. §B.4's withdrawn sticker reason is the only thing
that would have needed one.

**No new DynamoDB table, index or key layout.** `batch_id` and the void fields ride on
the existing `TXN#<YYYY-MM>` rows; grouping happens in the client over a date-bounded
read that is already being fetched.

## API Contracts

| Method | Route | Change | Notes |
|---|---|---|---|
| GET | `/admin/market/search` | **Modified** | Each item gains `display_price` (`Decimal \| None`, from `_market_price(card, "normal")`) and `display_finish`. `images`, `prices` and `detail` were already returned (§L, §N) |
| GET | `/admin/market/coverage` | **Modified** | Adds the two weekly-cycle numbers: `full` rows older than 8 days (healthy: 0) and rows still `brief` (§N) |
| GET | `/admin/inventory/search` | **Modified** | `?triage=true` rows carry `triage_reasons: string[]`; new `triage_reason=<key>` filter (422 on unknown); triage defaults to non-terminal statuses with an include-sold flag |
| POST | `/admin/inventory/bulk-clear-review` | **New** | Clears `needs_review` for machine-flagged items in a cohort, **excluding `blank_condition`**; server-stamps `reviewed_at` (§B.4a, §B.5) |
| PATCH | `/admin/cosigners/{id}` | **Modified** | 409 when the name collides with another consignor (archived ones included) |
| POST | `/admin/cosigners` | **Modified** | Same 409 guard |
| GET | `/admin/cosigners` | **Modified** | Hides archived consignors unless `?include_archived=true` (§A) |
| DELETE | `/admin/cosigners/{id}` | **Modified** | Now an **archive** — sets `archived=True`, row survives. No hard delete, no in-use guard |
| POST | `/admin/cosigners/{id}/unarchive` | **New** | Restores an archived consignor |
| POST | `/admin/purchases/{buy_id}/items` | **Modified** | 422 when `buy_price` is absent, null or non-finite (§G) |
| POST | `/admin/purchases/{buy_id}/confirm` | **Modified (internal)** | Validates every staged row **before** the first write — no partial batches (§G) |
| POST | `/admin/transactions/{txn_id}/void` | **New** | Body `{ reason }`. Atomically stamps the row and restores the item's status; marks affected show snapshots stale |
| POST | `/admin/transactions/{txn_id}/restore` | **New** | Un-voids |
| GET | `/admin/transactions` | **Modified** | Rows carry `batch_id` and the void fields; still filters nothing out (it is an archive) |
| GET | `/admin/analytics/daily` · `/analytics/dates` · `/admin/shows/{id}/analytics` | **Modified (internal)** | Every aggregate excludes voided rows through one shared predicate |
| POST | `/admin/slabs/refresh-prices` | **Modified** | Optional `item_ids: string[]` scopes the run to a just-committed batch (§I.2) |

**Removed:** nothing. PSA's `/admin/slabs/lookup/{cert}` was never built, so §H deletes
documentation and two disabled buttons, not endpoints.

MCP: no tool signature change. `mcp-server` reads inventory and prices, not the
transaction ledger, so `batch_id` and the void fields do not reach it. **If a voided
transaction could ever affect an MCP-reported total, that is a contract change** — checked
and it cannot, because no MCP tool sums transactions.

## Alternatives Considered

- **§A — reconcile forked consignors on read** (dedupe in `list_consignors`) instead of
  sweeping on write. Rejected: it hides the fork instead of fixing it, and every other
  reader (`get_consignor`, `delete_consignor`, the analytics join) would need the same
  dedupe or would disagree with the list. `put_show` set the precedent and consistency
  here is worth more than novelty.
- **§A — a hard delete for consignors**, guarded 409 when items reference them (mirroring
  `locations.py`). Was in this RFC's first draft; **withdrawn by the owner in favour of an
  archive.** Once the fork is swept there is no orphan row that needs destroying, and a
  consignment ledger that can lose its counterparty is worse than a list with a filter on it.
- **§A — keep `active` and merely relabel it "Archived".** Rejected: `Show.archived` is the
  established name for this concept and CLAUDE.md documents it. A second field meaning the same
  thing under a different name is how the next reader introduces a bug.
- **§A — drop `_gen_sk` from `put_consignor`.** Rejected: the generation scoping exists so
  load-then-swap has a prior generation to roll back to (BLOCKING-1b in `_gen_sk`'s own
  docstring). Removing it trades a visible duplicate for an unrecoverable import.
- **§B — keep computing reasons on the client** and fix the mirror when it drifts.
  Rejected: the mirror is correct *today* (verified), so there is nothing to fix and
  nothing to test — which is exactly why it will drift silently later. Emitting the
  server's own answer removes the class.
- **§B — a `triage` GSI** so the queue is a query rather than a filtered full read.
  Rejected as premature: `list_inventory` at hundreds of items is cheap, and the badge
  already pays the same cost on every admin page. Revisit at ~10k items.
- **§F.2 — group server-side** and return nested transactions. Rejected: `GET
  /admin/transactions` is deliberately a raw archive ("nothing is filtered out, trade cash
  legs included, because the point is to see what was actually written"), and nesting it
  would break that contract for every other reader to serve one view's layout.
- **§F.2 — backfill `batch_id` by (date, payment_method, type).** Rejected: two separate
  cash sales on one show day are indistinguishable from one two-card sale, so the
  heuristic fabricates transactions that never happened, in the one view where being wrong
  costs money.
- **§F.3 — hard delete a transaction.** Offered and declined by the owner. It leaves no
  trace a sale existed, and the show snapshots already generated would silently disagree
  with the ledger with no way to notice.
- **§G — `type="number" step="0.01"` on the Cost field** (the recommendation on file
  before the owner's review comment). Rejected because it makes `1,300` un-typeable
  rather than correct, which is the opposite of what was asked.
- **§G — `parseFloat` instead of `Number`.** Rejected on measurement:
  `parseFloat("1,300")` is `1`, and it is not `NaN`, so it defeats every existing guard
  and converts a loud 500 into a silent $1,299 loss.
- **§I.2 — price synchronously inside the commit loop.** Rejected: it puts a metered
  third-party HTTP call inside the exact loop §G exists to make safe. A slow or 500ing
  vendor would then fail a commit that had already written inventory.
- **§I.3 — price unmatched slabs off a name search, flagged "unverified".** Offered and
  declined by the owner; the vendor's name search was measured wrong ~1/3 of the time.
- **§K — nested routes** (`/admin/show/sell`) to match the nested nav. Rejected: it
  breaks every bookmark and every doc reference for a visual regrouping. Grouping is a
  sidebar concern only.
- **§N — price the whole catalog every night** (~2 h 18 min). Rejected: it outlives the catalog
  lock's 1-hour TTL, and the failure mode is catalog rows silently disappearing, not a stale
  price. Cost was never the objection — it is ~$2.40/month.
- **§N — raise `_LOCK_TTL_SECONDS`** so a 2 h 18 min run fits. Rejected: chunking is the actual
  fix, and a longer TTL means a genuinely crashed holder blocks tomorrow's run and any reseed for
  correspondingly longer. The TTL is sized to *"a crashed holder is stolen"*, not to the longest
  job anyone might write.
- **§N — a persisted cycle cursor** ("cards 5,500–11,000 done") instead of stalest-first.
  Rejected: it is state that can be wrong, and it strands the cards an aborted night skipped.
  Stalest-first self-heals, and `refresh_graded_prices` already proves the pattern here.
- **§N — parallel requests** to shorten the pass. Rejected: TCGdex is a free volunteer-run
  service with no observed rate limit, and the existing 100 ms delay is deliberate courtesy
  (`tcgdex.py:620`). Buying 6× throughput by removing that is the wrong trade against a weekly
  deadline that a serial walk already meets.
- **§L — compute the display price in the frontend** from the `prices` dict. Rejected on the
  strength of `_market_price`'s own docstring: *"Do not re-implement this walk in a caller: a
  second copy is how that divergence happened"* — the divergence being 174 of 213 live items
  silently unpriced. It also cannot work: a catalog result has no item, so no finish.

## Risks & Mitigations

- **§F.3 is the largest risk in this RFC.** A void honoured by some aggregates and not
  others produces two disagreeing sets of books, which is worse than having no void at
  all. Mitigation: **one** shared `is_countable(txn)` predicate; the task doc enumerates
  every reader (`summarize_transactions`, `sell_through_rate`, `starting_inventory`,
  `daily_analytics`, the show snapshot generator, the dashboard, `list_transactions`
  callers) and requires a test per reader. No reader may inline its own check.
- **§F.3 partially invalidates stored show snapshots.** They are point-in-time records
  (`put_show_analytics`), not derived views. Mitigation: mark stale and offer
  regeneration; never silently rewrite, and never silently serve a stale one.
- **§F.3 restoring a purchase is not symmetric with restoring a sale.** Voiding a sale
  returns an item to stock; voiding a purchase should arguably *remove* an item that
  should never have existed — which may already have been sold or traded. Mitigation:
  scoped in Open Questions and, if unresolved, sales-only in the first cut with purchases
  explicitly refused rather than half-handled.
- **§G's `confirm_buy_session` pre-validation touches a live money path** every buy and
  every slab batch runs through. Mitigation: the raw path's existing tests are the
  regression gate; validation is additive (a batch that commits today must still commit),
  and the new failure mode is a 422 *before* any write.
- **§B.5's bulk clear can wipe legitimate flags.** Mitigation: it only ever clears rows
  whose *only* reason is `flagged` **and** whose `review_reason` is in
  `MACHINE_REVIEW_REASONS`; a human's free-text note is never in that set, so a hand-flagged
  card cannot be caught by it. Confirmation dialog states the exact count.
- **§C changes `onUpdated`'s signature** on a component six pages mount. Mitigation: the
  parameter is optional, so a parent that ignores it keeps today's refetch behaviour and
  cannot break.
- **§E's fix is invisible in UTC.** A CI box on UTC passes either way, for both the display bug
  and the "today" bug. Mitigation: the tests pin a negative-offset `TZ` and fake the clock;
  without those the tests are theatre.
- **§E's "today" fix changes the default date on three live money forms.** Mitigation: it moves
  the default from *wrong after 5pm* to *right*, and the date remains user-editable on all
  three — but any test asserting a hardcoded UTC-derived default will need updating, which is a
  signal, not a failure.
- **§N's first cycle is the slow one.** Every unheld row is `brief`, so initial coverage takes
  ~6 nights and the picker shows "no price yet" for most cards until then. Mitigation: report the
  remaining `brief` count in the summary and on the coverage panel, so a cycle in progress cannot
  be mistaken for a stalled one.
- **§N adds ~31,300 nightly requests to a free, volunteer-run API.** Mitigation: the 100 ms
  courtesy delay stays, the work is spread over six nights rather than bursting, and the pass is
  capped. Do not parallelise it to go faster.
- **§N's runtime sits inside a lock with a hard ceiling.** Mitigation: 24 min against a 3600 s TTL
  is 2.5× headroom, plus an explicit runtime cap so a raised `CATALOG_REFRESH_CARDS_PER_NIGHT`
  cannot silently push a run past the TTL. Three consecutive lost nights is the documented point
  at which Friday's backlog would exceed it, and the coverage number is what makes that visible.
- **§L displays prices that §N has not yet written.** Mitigation: the absent-price states are
  built first and tested as first-class cases, so T15 ships correct on day one and needs no
  frontend follow-up when T17 lands.
- **§B.4a means `blank_condition` cards are currently mispriced to customers.** Mitigation: this
  RFC makes them findable and fixable; it does not fix the data. **The remediation is manual and
  the owner has to do it** — and until they do, those cards are listed above their value. Worth
  surfacing the count in the smoke checklist so the size of the job is known.
- **§I.2 spends real money.** Intake-time pricing draws on the same 50-lookup daily
  budget as the nightly job. Mitigation: the scoped `item_ids` run, the existing 409
  single-flight guard, and the run summary's credits-remaining report. An exhausted quota
  must read as "not priced yet", never as a failed intake.
- **§H removes the disabled buttons that made the PSA gap visible.** Mitigation: the
  reason moves into the docs (RFC 0009 T2/T5 marked WON'T DO with the paid-API reason and
  the date) rather than vanishing, so the next reader finds a decision instead of silence.
- **§K's mobile nav** currently derives from `navItems.slice(0, 5)`. Mitigation: an
  explicit five-entry array, so restructuring the sidebar cannot silently change what a
  phone shows.

## Open Questions

1. ~~**§A:** Purge as `DELETE ?purge=true` or a separate route?~~ **CLOSED 2026-08-10 — there
   is no purge.** Delete is an archive; see §A.
2. **§A:** Should the one-time fork reconcile run as a script the owner invokes (like
   `backfill_catalog_sets.py`) or automatically on the next `list_consignors`? Recommend
   the script — this is a data edit and it should be dry-run first.
3. ~~**§B.5:** Should the import stop setting `needs_review` for `blank_condition`?~~
   **CLOSED 2026-08-10.** The importer will never run again (§B.4b), so its flagging is
   historical — do not touch it. And `blank_condition` turns out to be a **money** defect
   (§B.4a), so the answer to "is it worth reviewing" is emphatically yes.
4. **§F.3:** Does voiding a **purchase** need to work in the first cut, and if so what
   happens to an item that has since been sold or traded? Sales-only, with purchases
   returning a clear 400, is the honest small version.
5. **§F.3:** Should `voided_by` use the Cognito `sub` or the email? `sub` is stable and
   opaque; the email is what the owner would want to read in an audit line. Storing `sub`
   and resolving for display is more work than this feature justifies.
6. **§I.2:** Fire the scoped price refresh **automatically** after every commit, or leave
   it as a "Price this batch" button? Automatic matches the owner's flow description;
   a button makes the credit spend a deliberate act. Recommend automatic with the credit
   cost shown in the result line.
7. **§K:** Should the Triage badge also roll up onto its group header when the group is
   **expanded**, or only when collapsed? Only-when-collapsed is less noisy; always-visible
   is harder to miss.
