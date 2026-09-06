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
| 7 | T2 | ~~**The customer-visible search wire never gained a `sticker_price` field, and the frontend tile does not read one.**~~ — **RESOLVED (Round 9 closeout, 2026-09-03).** Decided without escalating: the RFC's own motivation ("Showing them the sticker is the fix") already settled what the tile should show, and the fix the row below spells out was mechanical, not a business tradeoff — no fact the owner held that this session didn't. `sticker_price` joined `_CUSTOMER_ITEM_FIELDS` (additive; nothing else on the allowlist moved), and `frontend/lib/inventory.ts::toPresentedCard` now reads `item.sticker_price` directly instead of `item.card?.market_price ?? item.listed_price`. The chat-mode path (`toPresentedCardFromChat`/`DisplayedCard.listed_price`) needed **no change** — `services/bedrock.py::_hydrate_item` already set `listed_price=item.sticker_price` under T2, so chat was already correct; only the filter-mode search tile had drifted from `_display_price`'s own authority. New coverage: `test_search_response_carries_sticker_price` (backend) plus updated `toPresentedCard` cases in `lib/__tests__/inventory.test.ts`. |
