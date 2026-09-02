# RFC 0025 — Customer Sticker Pricing: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0025-customer-sticker-pricing.md`](../../rfcs/0025-customer-sticker-pricing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Measure the stickered fraction | NOT STARTED — **owner gate** |
| T2 Sticker rule in the predicate + `_display_price` | NOT STARTED |
| T3 MCP TypeScript mirror | NOT STARTED |
| T4 Remove condition adjustment from the customer path | NOT STARTED |
| T5 Remove Est. value + `est_value` | NOT STARTED |
| T6 Docs + verification | NOT STARTED |

## Next: T1

T5 is independent of T1–T4 and can be done any time.

**This RFC is scheduled LAST in Round 9** — it changes what customers see, so it
should land on a branch that is otherwise already green.

## Facts established during planning (do not re-derive these)

- **`sticker_price` is on `_ItemBase`** (`models/inventory.py:211`), so both
  customer kinds (`raw`, `graded`) carry it. No `getattr` needed.
- **`is_customer_visible` has FOUR readers**, three Python and one TypeScript:
  - `routers/inventory.py::customer_visible_items` — filter search + the authed
    dashboard summary (`/inventory/summary`)
  - `routers/public.py:276` — the anonymous public featured endpoint
  - `services/bedrock.py:525` and `:654` — chat display hydration, twice, via
    `visible=is_customer_visible`
  - **`mcp-server/src/dynamodb-repository.ts:46,62`** — a separate TypeScript
    mirror (`PUBLIC_LOCATIONS`, `row.status === "available"`) that queries
    DynamoDB directly, in a separate process. **This one is the easy miss.**
- **`_display_price` is the documented single authority** for the customer price
  filter, sort and tile. Its docstring records that those three once read three
  different figures and only two agreed, producing a $517 card that passed
  `max_price=500`. "They must never diverge again: change this function, not a
  caller."
- **`apply_condition_adjustment` has many callers and most are unaffected:**
  `catalog_sync.py:424` (bakes the multiplier into stored
  `current_market_value`), `routers/admin/inventory.py:899`,
  `routers/inventory.py:373` (the `est_value` loop being deleted in T5) and `:582`,
  `services/bedrock.py:437`. **Do not delete the module.**
- **`InventoryStats`' grid is already `auto-fit`, not `grid-cols-3`** — changed
  after a live 390px measurement where `$10,517.69` overflowed its card. Removing
  a tile needs no layout work.

## Decisions made autonomously (with the rejected alternative)

- **The sticker rule goes in `is_customer_visible`, not in a router.** Rejected a
  router filter: it would need repeating in four places and the two most likely to
  be missed (public featured, chat hydration) are the two least visible.
- **Condition adjustment is removed from the customer price path but the module
  stays.** A sticker is not a Near Mint catalog figure; scaling it applies the
  adjustment twice. Rejected leaving `_condition_adjust` in place (double
  application) and deleting the module (still used by four other callers).
- **Only the Est. value tile is removed, not the whole `InventoryStats`
  component.** Rejected removing the bar: two counts are not a valuation and the
  owner asked for the estimated-value widget.
- **`hidden_no_price` stays in the response with a test asserting it is zero.**
  Rejected removing it (a contract change for no gain) and leaving it untested
  (dead code rather than a tripwire).
- **CLAUDE.md's condition-pricing section is edited in T4, not deferred to T6.**
  It becomes actively wrong the moment T4 lands, and this repo has recorded the
  stale-justification failure twice already.

## Measurements to record here during execution

- **T1:** customer-visible count, stickered count, and the percentage — with the
  date. **Report to the owner before T2 merges.**

## Owner gates on this RFC

1. **T1 → T2.** The owner sees the stickered fraction before the storefront
   narrows. Their decision stands unless they change it on seeing the number.
