# RFC 0011 — Follow-ups

Out-of-scope findings from RFC 0011 tasks. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **Bulk park** — "move these six cards to unmatched" in one action | The owner's rule is admin supervision per card, and a bulk action over a destructive write that clears prices is not the first version of this feature. |
| 2 | **Notifying on a new candidate** (push, rather than the dashboard widget) | The widget answers the question. A push channel is a separate decision. |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| 3 | T4 | **An unparseable filter bound is dropped silently.** `buildFilterParams` skips a `range` value `parseMoney` cannot read (`"1,"`, `"abc"`) rather than sending it, because the value changes on every keystroke and a 422 mid-type blanks the list. The trade is that a bound left permanently unreadable filters nothing and says nothing. The fix is a per-control validation state showing `MONEY_PARSE_MESSAGE`, which is a `ColumnFilter` change, not a `buildFilterParams` one. |
| 4 | T4 | **`useShows()` fetches on every inventory page load**, even though the Acquired Show column is off by default. Same shape as `useCatalogSets`, so it is consistent rather than novel — but with T4 the page now makes three unconditional support requests (`/locations`, `/catalog/sets`, `/shows`) to populate dropdowns most visits never open. A shared lazy `optionSource` resolver would fix all three at once. |
| 5 | T4 | **The `_actions` column has no filter and is excluded by name** in `admin-inventory-columns.test.ts`'s `NO_FILTER` set, alongside `_image`. A future pinned/synthetic column has to be added to that set by hand or the totality test fails for the wrong reason. A `filterable: false` flag on `InventoryColumnDef` would say it once, in the registry. |
| 6 | T8 | **`/admin/unmatched` carries a LOCAL copy of Triage's `CatalogPicker`** (name-only search, `CardPickerRow` results) because T11's shared `CardSearchPanel` has not landed. When T11 lands, swap `CatalogSearchDialog` in `app/(admin)/admin/unmatched/page.tsx` for it, with `onManualEntry` omitted — a parked card is being *paired* with a row that already exists, so there is nothing to create. T11's own "Done means" checks for this row. |
| 7 | T8 | **`PriceDisplay` parses money with `parseFloat`** (`components/admin/shared/PriceDisplay.tsx:15`). It is a display-only path so nothing is written wrong today, but `parseFloat("1,300.00")` renders **`$1.00`** — and `CardPickerRow` feeds it a server-formatted string. Nothing currently sends a grouped string, which is why this is a follow-up and not a fix; `formatMoney`/`parseMoney` is the correct pair. |
| 8 | T8 | **The queue has no search or filter box.** Triage has both. At the queue's designed scale (tens of rows) scanning is fine, and adding a search that hits `/inventory/search` per keystroke for a list that short is cost without benefit — but if the parked cohort ever reaches the low hundreds this becomes the first thing to add. |
