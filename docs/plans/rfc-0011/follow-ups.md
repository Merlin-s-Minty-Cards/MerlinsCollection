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
