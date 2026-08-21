# T1 — Price filter must compare the price the customer actually sees

**RFC:** 0008 §A (issue #2) · **Layer:** backend · **Depends on:** nothing
**File:** `backend/src/merlins_collection/routers/inventory.py`

## The bug

Three code paths read three different figures for "the price of a card", and only
two agree:

| Path | Reads | Freshness |
|---|---|---|
| `min_price`/`max_price` filter (`_price`, line ~96) | `item.current_market_value` | **stale** — nightly |
| `sort=price_*` (`_display_price`, line ~408) | `item.card.market_price` | live |
| `CardTile.tsx:18-19` render | `item.card?.market_price ?? item.listed_price` | live |

Owner-observed symptom: a Rayquaza **displaying $517** still passes
`max_price=500`, because its stale `current_market_value` was ≤ 500 at last sync.

## The fix

Make the price bound filter on the same value the tile renders — i.e. route
`_apply_price_bounds` through `_display_price()` instead of `_price()`.

### The ordering trap — read this before editing

`_display_price()` reads `item.card.market_price`. **`item.card` is only populated
by `_enrich()`**, which today runs *after* `_apply_price_bounds`. If you just swap
the helper without reordering, `item.card` is `None` for every item, every card
falls back to `listed_price` (which is `NULL` on every item by owner decision —
see the `_price` docstring), and **the filter will silently hide the entire
inventory** into `hidden_no_price`. That failure looks like "the filter works, there's
just no stock", so it will not be obvious.

So the change is two parts, and both are required:

1. In `search_inventory`, move catalog enrichment **before** the price-bound call.
2. Point the bound at `_display_price`.

### Steps

1. Read `search_inventory` end to end and write down the current order of
   operations (filter → bound → enrich → sort). Confirm exactly where `_enrich()`
   runs and what else depends on that position (the sort already needs enrichment,
   so enrichment is already before sorting — you are moving it earlier still).
2. Move enrichment above `_apply_price_bounds`.
3. Change `_apply_price_bounds` to call `_display_price(item)`.
4. Delete `_price()` if nothing else calls it (grep first). If it survives, update
   its docstring — the current one describes behaviour that will no longer exist.
5. Rewrite the `_display_price` docstring to state it is now the single authority
   for filter, sort, **and** tile, and that the three must never diverge again.

### Leave alone

- `hidden_no_price` semantics are unchanged — still "excluded because the price is
  unknown", just measured against the right field now. Do not change the count's
  meaning or its wire name.
- Graded slabs: `_display_price` deliberately skips the catalog price for
  non-`raw` kinds (a graded slab's catalog price is ungraded and inapplicable).
  Preserve that — do not "fix" it.
- The admin-side `_effective_price` (`routers/admin/inventory.py:879`) is a
  **different** bug (§K, blended market-or-cost-basis semantics). **Out of scope
  for T1.** Do not touch it.

## RED — write these first, confirm they fail, then stop

In `backend/tests/` alongside the existing `/inventory/search` tests:

1. **The reported bug.** Item whose stale `current_market_value` = 400 but whose
   live catalog `market_price` = 517. `max_price=500` must **exclude** it.
   Fails today (it's included).
2. **The mirror case.** Stale `current_market_value` = 600, live = 450.
   `max_price=500` must **include** it. Fails today (it's excluded).
3. **Regression guard for the ordering trap.** A normal item with a live catalog
   price inside the bound is returned, and `hidden_no_price == 0`. This is the test
   that catches "enrichment ran too late" — it passes today and must keep passing.
4. **`hidden_no_price` still counts.** An item with no catalog card and no
   `listed_price` is excluded and counted, with a bound set.
5. **Filter/sort agreement.** With a bound applied and `sort=price_desc`, every
   returned item's displayed price is within the bound and ordering is by the same
   figure. This is the invariant the whole task exists to establish.

Also re-run the **existing** `_apply_price_bounds` / `hidden_no_price` tests. The
RFC flags that some will need updating for the new call order — expect that, and
when one fails, check whether it encoded the *old* stale-field behaviour as
correct before you change it.

## Verify (narrow — do not run the full suite)

```bash
python -m pytest backend/tests -q --tb=short -k "price or facet or search"
ruff check backend/src
```

## Done when

- All five new tests green; pre-existing price tests green or knowingly updated.
- `grep -n "current_market_value" backend/src/merlins_collection/routers/inventory.py`
  shows it only in `/summary`'s documented fallback, not in the search filter path.
