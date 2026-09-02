# RFC 0022 — Follow-ups

Out-of-scope findings. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **Inline editing on `/admin/history` and the Daily tab's transaction groups.** | A transaction edit has a `cost_basis` side effect, an audit trail, and a snapshot-staleness consequence. It needs a dialog and its own design — RFC 0024. |
| 2 | **Bulk edit** ("set these twelve to LP"). | The bulk bar already exists on several pages for other actions. A bulk field-set is a real want but is a different interaction with its own confirmation story. |
| 3 | **Editing a `location`'s `value`.** | It is the join key on every inventory item. A rename would need a migrate-every-item transaction; delete-and-recreate is the supported path and the 409 in-use guard already makes it safe. |
| 4 | **Editing consignment terms inline.** | Owner-excluded. Split, terms and consignor move together and it is a nested object, not a scalar. |
| 5 | **Editing `card_id` inline.** | Owner-excluded. Re-pointing is a confirmed action with a before/after diff and trade-lineage warnings, and that surface exists in Triage. |
| 6 | **A keyboard-driven "edit the next cell" flow** (Tab from a committed cell into the next editable one). | Genuinely faster at a table, and genuinely a separate design. |
| 7 | **`current_market_value` editing.** | Overwritten by `refresh_inventory_market_values` on the next nightly run, so an edit would silently revert. The graded price pin is the real mechanism and it has no frontend control yet (RFC 0009 follow-up). |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| | | |
