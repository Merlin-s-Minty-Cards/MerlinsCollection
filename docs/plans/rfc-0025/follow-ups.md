# RFC 0025 — Follow-ups

Out-of-scope findings. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **A "stale sticker" signal.** | Prep Queue finds *unstickered* stock. Once the sticker is the customer price, a sticker set six months ago against a market that has doubled is a new, different problem — it needs a comparison signal (sticker vs current market, with a threshold) and its own queue or badge. Genuinely worth building; not this RFC. |
| 2 | **Auto-suggesting a sticker price from market.** | The obvious next step from #1, and it is a pricing decision the business makes, not one a multiplier makes. Would need the owner's rules. |
| 3 | **A bulk "sticker everything at market ×N" action.** | Same category as #2, plus a bulk money write. |
| 4 | **Surfacing how much stock is hidden for want of a sticker, on the admin dashboard.** | T1 measures it once. A permanent widget would make the gap visible continuously and is a small, obviously useful addition — but it is a dashboard change, not a customer-pricing change. |
| 5 | **Removing `hidden_no_price` from the search response.** | Structurally unreachable after this RFC, but removing it is a contract change for no gain. It stays as a tripwire with a test asserting it is zero. |
| 6 | **Making `sticker_price` required on an available raw/graded item.** | Would enforce the invariant at the model rather than filtering for it — and would make an item unenterable at a buy table until it is priced, which is exactly backwards for how intake works. |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| 7 | T2 | **The customer-visible search wire never gained a `sticker_price` field, and the frontend tile does not read one.** `_CUSTOMER_ITEM_FIELDS` (`routers/inventory.py`) still allowlists only `listed_price`/`current_market_value`, and `frontend/lib/inventory.ts:399` still computes the tile's displayed price as `marketPrice ?? item.listed_price ?? 'Price N/A'` — the OLD catalog-derived figure. `_display_price` (filter/sort/visibility) is correctly the sticker now, but the PRICE TEXT a customer actually reads on a card tile is unaffected by this RFC and still shows the pre-RFC number. This is a real gap against the RFC's own stated motivation ("Showing them the sticker is the fix") — it happened because the RFC's own "API Contracts" section pins `GET /inventory/search` as "unchanged shape" and no task in T2-T6's file lists touches `_CUSTOMER_ITEM_FIELDS` or any frontend price-rendering file, so implementing exactly what was scoped left this uncorrected. Flagged to the owner directly rather than fixed as a side errand, per this file's own header rule — it needs a scoping decision (add `sticker_price` to the wire allowlist + point the tile at it), not a quick patch. |
