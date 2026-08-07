# T3 — MCP chat total must match the dashboard

**RFC:** 0008 §D (issue #4) · **Layer:** mcp-server only · **Depends on:** nothing
**File:** `mcp-server/src/dynamodb-repository.ts`, `marketPrice()` (~line 195-233)

## The bug

The owner's hypothesis was that the dashboard total is static. **It is not** —
`InventoryStats.tsx:27-44` refetches on every mount, and the backend computes
`est_value` live. That part is working correctly; don't "fix" it.

The real defect is that the MCP tools resolve a card's price in the **opposite
order** from the backend:

| | tries first | falls back to |
|---|---|---|
| `/inventory/summary` (`routers/inventory.py:300-307`) | **live** `_market_price(card, finish)` | stored `current_market_value ?? listed_price` |
| MCP `marketPrice()` | **stored** `current_market_value` | live finish-aware lookup |

So whenever the nightly denormalizer lags the live catalog — the same staleness
that causes the §A Rayquaza bug — `get_inventory_summary` and
`calculate_inventory_value` sum stale figures while the dashboard sums live ones,
and the two disagree.

## The fix

Invert the priority in `marketPrice()`: try the live finish-aware catalog lookup
first, fall back to `current_market_value`, then `listed_price`.

Mirror `/inventory/summary` **exactly**, including these two already-settled points:

- **No condition adjustment.** Resolved during planning by reading the code:
  `routers/inventory.py:302` calls `_market_price(card, finish)` with no
  adjustment step. `apply_condition_adjustment` is used only by `catalog_sync` and
  the admin `refresh-prices` path. RFC Open Question 5 is answered — **do not add
  it**, that would make chat disagree with the dashboard in the other direction.
- **Graded slabs get no catalog price.** A graded item has no finish and carries a
  grade premium the catalog doesn't know, so it must keep its own stored figure.
  Confirm the TS side honours this the same way the Python side does.
- **Items with no price from either source are skipped, not counted as zero.**

Read `models/inventory.py:272-311` before editing — its docstring explicitly warns
against re-implementing this walk, and this task is repairing the drift that warning
predicted. Leave a comment in the TS naming the Python function it mirrors, so the
next person finds both.

## Scope

- Do **not** change `shared/tool-contract.json`. No tool signature changes; this is
  a bugfix inside an existing implementation.
- Do **not** touch the backend. `/inventory/summary` is already correct.

## RED — write these first, confirm they fail, then stop

In `mcp-server/`'s existing repository tests:

1. Card with `current_market_value = 400` (stale) and a live catalog price of
   `517` → `marketPrice()` returns **517**. Fails today (returns 400).
2. Card with no live catalog price and `current_market_value = 250` → returns 250.
   Passes today; regression guard for the fallback.
3. Card with neither → returns null/undefined and is **excluded** from a total,
   not summed as 0.
4. Graded item → does **not** take the catalog price; uses its stored value.
5. Finish-awareness survives: a reverse-holo item resolves the reverseHolofoil
   band, not the normal one.
6. End-to-end: `get_inventory_summary` over a fixture where stale and live differ
   produces the same total as the backend's `/inventory/summary` over the same
   fixture. **This is the test that expresses the actual bug** — the two totals
   must agree.

## Verify (narrow)

```bash
npm test --workspace=mcp-server
```

(~60s — small enough to run whole; still don't run the root `npm test`.)

## Done when

- All six green.
- A release note line exists for T-FINAL: chat-reported inventory totals will
  change, because they were previously stale. This is a number customers see.
