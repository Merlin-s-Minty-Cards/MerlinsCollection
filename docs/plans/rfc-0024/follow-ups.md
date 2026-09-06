# RFC 0024 — Follow-ups

Out-of-scope findings. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **A correction path for TRADES.** | `_compute_basis_pool` allocates incoming basis across all legs at confirm; correcting one leg means re-running the allocation over items that may since have been sold, re-priced or consigned. It needs its own design, and it is the second recorded gap of this shape (a mistaken buy still has no void either). |
| 2 | **Re-pointing a transaction's `item_id`.** | Owner-scoped out. One edit would rewrite two items' histories with no diff surface. Void plus a fresh entry is the honest expression of "wrong card". |
| 3 | **Editing `type` or `category`.** | A purchase that should have been a sale is not a typo; it is a different transaction. |
| 4 | **Auto-regenerating a stale `ShowAnalyticsSnapshot` after an edit.** | The edit marks it `stale` and `/admin/analytics` renders that flag; regenerating on every edit would run a full show aggregation on a keystroke-scale action. The manual Generate button is the recovery path, as it is for a void. |
| 5 | **An "edited" filter or badge on the transaction archive.** | The archive's point is to show what was written; `edit_history` is on the row for anyone who wants it. |
| 6 | **Bulk transaction edit** (correcting a whole batch's date). | Real — a show entered on the wrong date is a plausible mistake — and it is a batch write with its own 50-leg ceiling reasoning, exactly like batch void. Separate design. |
| 7 | **Per-attribute or per-condition adjustment on the acquisition ratio.** | The ratio compares two stored figures. Adjusting either would make it a different, invented number. |
| 8 | **Showing the ratio on the customer inventory page.** | It is a margin figure. It never leaves the admin surface. |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| | | |
