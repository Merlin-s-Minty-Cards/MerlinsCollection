# RFC 0012: Admin Page Width Consistency, Graded Manual Entry, and Consignment Tracking UI

Status: Draft
Author: Claude (session with owner, Ethan Harter)
Date: 2026-08-14

This RFC documents a design the owner approved directly in conversation on
2026-08-14, given explicit urgency ("ASAP") — it records the approved shape
for implementation rather than seeking a fresh written-spec review round.

## Summary

Three independent fixes bundled into one branch:

- **A.** Every admin page wraps its content in a differently-capped
  `max-w-{3xl,5xl,6xl,7xl}` wrapper; unify them to no cap at all, matching
  `/admin/slabs`, which already has none.
- **B.** A graded card can only be manually entered (no catalog match) on the
  Slabs intake page — `/admin/trade` forces any manual entry to `raw`, and
  additionally blocks *all* graded entry (catalog-matched or not) in Buy mode.
  Lift both restrictions. The card lands unpriced and self-routes to Triage
  through machinery that already exists — no new routing code.
- **C.** Consignment is already tracked per-item on the backend
  (`InventoryItem.consignment`), but nothing in the UI lets an admin see it
  per-cosigner from Inventory, or assign a cosigner to a card outside the
  Cosigners page. Add an inventory filter by cosigner and a `CosignorPicker`
  reachable from `CardDetailModal` and from `IncomingCardForm`.

## Motivation

The owner flagged three real gaps while looking at the live admin panel:
inconsistent page widths waste screen space on wide monitors, the "manual
entry can only ever be raw" rule (RFC 0011 §K, restated in CLAUDE.md) turned
out to have no correctness reason behind it once traced to source — it is a
Trade-specific guard, not a Slabs-page or inventory-model constraint — and
consignment tracking, while real in the data model, is invisible anywhere an
admin would actually look for it day to day.

## Detailed Design

### A. Layout width

Remove the `max-w-*` class from the outer `<div className="p-6 lg:p-8
max-w-Nxl">` wrapper on every top-level admin page. `p-6 lg:p-8` stays —
only the cap goes. Files (grep-confirmed):

| File | Current cap(s) |
|---|---|
| `app/(admin)/admin/page.tsx` | `max-w-6xl` |
| `app/(admin)/admin/locations/page.tsx` | `max-w-3xl` |
| `app/(admin)/admin/analytics/page.tsx` | `max-w-5xl` (loading state), `max-w-6xl` (loaded) |
| `app/(admin)/admin/market/page.tsx` | `max-w-5xl` |
| `app/(admin)/admin/history/page.tsx` | `max-w-5xl` |
| `app/(admin)/admin/cosigners/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/inventory/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/shows/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/card/[id]/page.tsx` | `max-w-5xl` (×3 states: loading/error/loaded) |
| `app/(admin)/admin/outgoing/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/show-prep/page.tsx` | `max-w-6xl` |
| `app/(admin)/admin/vault/page.tsx` | `max-w-6xl` |
| `app/(admin)/admin/unmatched/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/triage/page.tsx` | `max-w-7xl` |
| `app/(admin)/admin/trade/page.tsx` | `max-w-3xl` (mode-selector view), `max-w-7xl` (main view) |

`app/(admin)/admin/slabs/page.tsx` already has no cap — the reference.

**Do not touch** any `max-w-md` / `max-w-lg` / `max-w-2xl` on modal/dialog
panels (e.g. `cosigners/page.tsx:600`, `inventory/page.tsx:597`,
`triage/page.tsx:1298`, `history/page.tsx:360/414/452`) — those bound a
centered dialog, not the page, and are correct as-is.

No test currently asserts a specific `max-w-*` value on these wrappers
(confirmed by scope of the change); if one is found during implementation
it gets updated in the same commit, not treated as a separate task.

### B. Graded manual entry

**What's actually gating this today**, traced to source:

1. `backend/src/merlins_collection/routers/admin/trades.py:430-437`
   ("Decision 14") — 422s a graded incoming leg when `card_id` is falsy:
   ```python
   if not body.get("card_id"):
       raise HTTPException(422, "A graded incoming leg must be linked to a catalog card.")
   ```
2. `frontend/components/admin/deal/IncomingCardForm.tsx:129`:
   `gradedSelectable = !manual && gradedAllowed` — disables the Graded radio
   (line 236) and forces `kind: 'raw'` at submit (line 154) whenever the leg
   is a manual entry (`card === null`), regardless of mode.
3. `frontend/app/(admin)/admin/trade/page.tsx:380`:
   `gradedAllowed={mode !== 'buy'}` — blocks graded entirely in Buy mode,
   catalog-matched or not, "pending a cert-ownership UI" per the comment at
   `IncomingCardForm.tsx:53-64`.

Neither `backend/src/merlins_collection/models/inventory.py`'s
`GradedInventoryItem.card_id: str | None = None` nor
`purchases.py`'s `_GRADED_REQUIRED_FIELDS = ("company", "grade",
"cert_number")` (no `card_id`) require a catalog link for a graded item to
exist. The restriction is Trade-specific policy, not a model or pricing
constraint.

**The "cert-ownership UI" already exists** — `IncomingCardForm.tsx:101-123`
already runs a debounced `GET /slabs/certs/{cert}` lookup and renders a
non-blocking amber warning (`owned?.owned`, lines 338-346: "You already own
cert ... You can still add it.") whenever `kind === 'graded'`, independent of
`manual` or the mode gate. It is simply unreachable today because the gates
above never let `kind` reach `'graded'` in the states this RFC unblocks. No
new cert-collision code is needed — removing the gates makes existing code
reachable.

**Changes:**

- `trades.py`: delete the `if not body.get("card_id")` 422 block
  (lines 430-437). Keep the adjacent, unrelated check that 422s a raw leg
  carrying graded fields (`condition`/`grade` stay mutually exclusive,
  RFC 0011 §H) — that rule is untouched.
- `IncomingCardForm.tsx`: `gradedSelectable` becomes just `gradedAllowed`
  (drop the `!manual &&`). Delete the manual-only explanatory span (lines
  243-249, "Graded needs a catalog card…") since it's no longer true. Delete
  the `!gradedAllowed` explanatory span (lines 250-254, "Graded intake isn't
  available from Buy yet…") since the mode gate goes away too.
- `trade/page.tsx:380`: change `gradedAllowed={mode !== 'buy'}` to
  `gradedAllowed={true}`, or drop the prop and its default entirely if no
  caller still needs `false`. Grep for other `IncomingCardForm` consumers
  before removing the prop outright — at time of writing `trade/page.tsx` is
  the only one.
- Update `IncomingCardForm.tsx`'s own doc comment (lines 13-25, 48-64) — it
  currently states the manual-only-raw and Buy-mode-blocked rules as settled
  fact; both are reversed by this RFC.
- `IncomingCardForm.test.tsx:191` ("disables Graded and says why when
  gradedAllowed is false (Buy mode, Critical 1 regression)") tests the exact
  behavior being removed. Replace it with a test asserting graded IS
  selectable for a manual entry and in Buy mode, and that the cert-owned
  warning fires for a manual graded entry (previously untestable since the
  radio was disabled).

**Triage routing — no new code.**
`backend/src/merlins_collection/services/triage.py:38-61`,
`is_missing_card_id()`, already returns `True` for any item (raw or graded —
`getattr` covers both kinds) with `card_id is None` and `no_catalog_match`
unset. A graded manual entry with `card_id=None` is indistinguishable, to
this predicate, from any other unmatched item, and surfaces in
`GET /admin/inventory/search?triage=true` and the Triage sidebar badge
automatically the moment it can be created. Add one backend test: create a
graded incoming leg via `POST /trades/{id}/incoming` with no `card_id`,
confirm the trade, and assert the resulting item appears in the triage query
with `missing_card_id` among its `triage_reasons`.

**Pricing consequence, stated explicitly (not a new behavior, an existing
one applying to a new source):** a graded item with no `card_id` is
unpriceable by construction — same as a JP slab today (`services/slab/
pricing.py:16-37`, verified join requires `card_id`). It sits at
`/admin/slabs?priced=false` until an admin attaches a `card_id` (via
Triage's re-point flow, which already exists), at which point the nightly
`refresh_graded_prices` job picks it up stalest-first on its own.

### C. Consignment UI

**New shared component**: `frontend/components/admin/shared/CosignorPicker.tsx`.

- Fetches the cosigner list once via `GET /admin/cosigners` (mirrors
  `frontend/lib/use-locations.ts`'s `useLocations()` shape: hook returns
  `{ options, loading }`, no refetch-per-keystroke).
- Renders a text input that client-side substring-filters the fetched list
  as the admin types (the list is bounded — dozens, not thousands — so no
  server-side search endpoint is needed; this matches `useLocations()`'s
  complexity level, not `CardSearchPanel`'s debounced remote search).
- Emits the selected `consignor_id` plus display name; a "no cosigner /
  clear" option is always present.

**1. Inventory filter by cosigner.**
`consignment` itself is `FieldKind.PRESENCE` in `FILTERABLE_FIELDS`
(`backend/src/merlins_collection/services/inventory_filters.py:107`) —
that already answers "has a cosigner or not," but the generic `FieldFilter`
mechanism does one-level `getattr` (`inventory_filters.py:253`) and cannot
reach the nested `item.consignment.consignor_id`. Add a hand-written filter
following the module's existing pattern for `name`/`condition`/`min_price`
(docstring, lines 17-26):

```python
def _item_matches_consignor(item: InventoryItem, consignor_id: str) -> bool:
    return item.consignment is not None and item.consignment.consignor_id == consignor_id
```

Wire a `consignor_id` query param into the admin inventory search router
(wherever `name`/`condition` are already special-cased as named params
alongside the generic `filter=` mechanism) the same way. An unknown
`consignor_id` value (a real string that matches no cosigner) is not a 422 —
same as any other filter value that legitimately matches zero rows; only an
*unknown filter field* is a 422, and `consignor_id` is a known, declared
field once this ships.

Frontend: add a `consignor_id` entry to `INVENTORY_FILTERS`
(`frontend/lib/admin-inventory-columns.tsx`), rendered by
`frontend/components/admin/shared/ColumnFilter.tsx` using `CosignorPicker`
as its control, consumed by `app/(admin)/admin/inventory/page.tsx`. Filter
only — no sort-by-cosigner (explicit owner non-goal).

**2. Assign during card edit.**
Add a "Consignor" row to `frontend/components/admin/shared/CardDetailModal.tsx`,
alongside its other editable fields. Rather than hand-rolling a `consignment`
payload against `PUT /admin/inventory/{item_id}` (which *would* accept it per
that endpoint's "exposes ALL fields" docstring, but would require the
frontend to duplicate the default-split-percent logic that already lives
server-side), reuse the existing, tested cosigner endpoints directly:

- Assign: `POST /admin/cosigners/{consignor_id}/link` with
  `{ "item_ids": [item.item_id] }`. The endpoint already defaults
  `split_percent` from the consignor's stored `payout_percent`
  (`cosigners.py:221`) when not supplied, and accepts an optional
  `minimum_price` override — surface both as optional, collapsed
  "advanced" inputs (`minimum_price` through `MoneyInput`, per the repo's
  money-input rule: never `parseFloat`, never `type="number"`) rather than
  requiring them up front.
- Unassign: `DELETE /admin/cosigners/{consignor_id}/assets/{item_id}`
  (existing endpoint, `cosigners.py:246-262`).
- No backend changes needed for this piece — both endpoints already exist
  and already do exactly this.

**3. Assign during Buy/Trade.**
`IncomingCardForm` gets an optional, collapsed-by-default "Consignor"
section (`CosignorPicker` + optional split/min-price override, same shape as
above). Neither `purchases.py`'s item-add endpoint nor `trades.py`'s
incoming-leg endpoint accepts `consignment` at creation time, and that is
not changing — inventing a second way to set consignment at create-time
would duplicate the default-split logic `cosigners.py:221` already owns.
Instead:

- The staged leg carries an optional `consignor_id` (+ overrides) client-side
  only (`lib/trade-incoming-form.ts`'s `IncomingLeg` type gains an optional
  field; `deal-session.ts` does not send it to `addIncoming`).
- After `confirm()` returns (`ConfirmResult.item_ids`, already present on the
  type per T13's graded-price verification use — `deal-session.ts:39-43`),
  the page fires `POST /admin/cosigners/{consignor_id}/link` once per
  item_id that had a consignor staged, un-awaited on its own status line —
  the same "commit succeeds and is reported first; a secondary metadata call
  happens after, outside the write loop" shape already used for slab price
  refresh (CLAUDE.md, "A slab is priced AFTER the commit, never inside its
  loop"). A link failure must not read back as "the deal failed" — the deal
  already committed.
- Verify `POST /purchases/{id}/confirm`'s response also includes `item_ids`
  (Trade's confirm is confirmed to; Buy's needs a one-line check against
  `purchases.py` during implementation — if it doesn't, add it there, since
  nothing else in this RFC needs a new backend field).

## Data Schemas

No schema changes. `ConsignmentTerms` (`inventory.py:181-187`) and
`InventoryItem.consignment` (`inventory.py:215`) are unchanged — this RFC is
UI and one relaxed validation rule, not new data shape.

## API Contracts

| Endpoint | Change |
|---|---|
| `POST /admin/trades/{trade_id}/incoming` | Removes the `card_id`-required-for-graded 422 (Decision 14 partially reversed). Raw-carrying-graded-fields 422 unchanged. |
| `GET /admin/inventory/search` | New optional `consignor_id` query param, hand-written filter, same 422-on-unknown-field semantics as existing named filters. |
| `POST /admin/cosigners/{consignor_id}/link` | No contract change — new frontend callers only (CardDetailModal, post-deal-commit from Buy/Trade). |
| `DELETE /admin/cosigners/{consignor_id}/assets/{item_id}` | No contract change — new frontend caller only (CardDetailModal). |
| `POST /admin/purchases/{buy_id}/confirm` | No change — already returns `item_ids` (`purchases.py:438`). |
| `POST /admin/trades/{trade_id}/confirm` | **Correction from the original draft**: this endpoint did NOT already return `item_ids` (the assumption below, that it mirrored `purchases.py`, was wrong — confirmed by grep, not by inference, during implementation planning). Add `item_ids`, index-aligned with the incoming legs submitted, needed for post-commit consignor linking in both Buy and Trade modes. |

## Alternatives Considered

- **B: keep a backend gate but relax the frontend only.** Rejected — the
  frontend would just get a 422 back on submit, which is a worse experience
  than removing the (now-agreed-unnecessary) backend rule.
- **C: set `consignment` directly via `PUT /admin/inventory/{item_id}`
  instead of reusing `POST /cosigners/{id}/link`.** Rejected — it works, but
  would force the frontend to duplicate `cosigners.py:221`'s default-split
  calculation, creating two places that decide what an unspecified split
  means. Reusing the existing endpoint is fewer moving parts.
- **C: server-side search-as-you-type for `CosignorPicker`, matching
  `CardSearchPanel`.** Rejected as over-built for a cosigner list, which is
  small (owner-managed, dozens at most) — client-side filtering of one fetch
  is simpler and matches `useLocations()`'s existing precedent for
  small, admin-managed lists.

## Risks & Mitigations

- **Removing Buy-mode's graded gate reintroduces a duplicate-cert risk if
  the cert-owned warning isn't actually wired for that path.** Mitigated —
  traced to source: the warning check (`IncomingCardForm.tsx:101-123`) is
  gated on `kind === 'graded'` only, not on mode or `manual`, so it already
  fires correctly once the outer gates are lifted. No new code needed, but
  the replacement test (see B) must assert this explicitly so a future
  refactor can't silently re-narrow the check's condition without a test
  failing.
- **A graded manual entry that never gets a `card_id` sits in Triage
  forever.** Accepted, matching the existing JP-slab precedent — this is a
  worklist, not a bug, and Triage already has a re-point flow for exactly
  this.
- **Post-commit consignor link is un-awaited, so a failure is silent to the
  operator unless surfaced.** Mirrors the accepted slab-pricing precedent
  (CLAUDE.md: "a pricing failure must never reach the commit's catch") — an
  admin can always assign the cosigner after the fact via CardDetailModal,
  so failure here is recoverable, not data loss.

## Open Questions

- Whether `IncomingCardForm`'s `gradedAllowed` prop should be deleted
  entirely (no remaining caller passes `false`) or kept with its `true`
  default for forward compatibility — implementation should check for other
  callers first and prefer deletion if none exist (YAGNI).
- Resolved during plan-writing (see `docs/plans/rfc-0012/c4-buy-trade-assign.md`):
  `purchases.py` already returns `item_ids`; `trades.py` did not and needed
  a small addition (a `created_item_ids` list appended to inside the
  existing incoming-legs loop, returned alongside the other confirm fields).
