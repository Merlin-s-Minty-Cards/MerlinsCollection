# RFC 0025: Customer Inventory — Sticker Pricing & Estimated-Value Removal

**Status:** Draft — written 2026-09-02, adversarially reviewed the same day
(see "Adversarial review findings"). No code written yet.
**Author:** Claude (planning session), owner-directed
**Round:** 9 — see [`docs/plans/round9/README.md`](../plans/round9/README.md)
**Owner tasks covered:** "Our front facing inventory page should use sticker
prices instead of market since sticker price is essentially the price we sell the
cards at"; "Remove estimated value widget on the inventory page."

## Summary

**The customer-facing price becomes `sticker_price`, and a card without one is
not shown at all.** The estimated-value figure comes off the `/inventory`
dashboard, and the server-side computation behind it — a full catalog join over
every visible item — is deleted with it.

This is the smallest RFC in Round 9 and the one with the largest blast radius on
what customers see. It is scheduled last for that reason.

## Motivation

`_display_price` (`routers/inventory.py`) is the single authority for the
customer price — the filter bound, the sort, and the figure the tile renders — and
today it reads:

```python
market = item.card.market_price if item.kind == "raw" and item.card else None
return market if market is not None else item.listed_price
```

A live catalog market figure, condition-adjusted at enrichment, falling back to
`listed_price`. That is **an estimate of what the card is worth**, not what the
business sells it for.

`sticker_price` is what the business sells it for. It is what is physically
written on the card in the case. An admin set it by hand, with the card and its
condition in front of them. The owner's framing is exact: *"sticker price is
essentially the price we sell the cards at."*

Showing a customer a market estimate and then charging a different number at the
table is the problem. Showing them the sticker is the fix.

The estimated-value widget is the same category of number pointed at the customer:
`InventoryStats`' middle tile ("Est. value") sums a condition-adjusted market
figure across every visible item. It is not a price, it is not a sale total, and
it is not something a customer needs.

## Owner decisions (recorded 2026-09-02)

**A card with no sticker price is hidden entirely.** Rejected explicitly:
falling back to condition-adjusted market (the recommended option), and showing
the card with no price.

The consequence is real and stated up front: **the storefront shrinks to exactly
the stock that has been priced.** The whole reason `/admin/outgoing` (Prep Queue)
exists is to find unstickered available inventory, which means unstickered stock
is a normal, expected state and not an edge case. §4 makes measuring this a gate.

## Detailed Design

### 1. The rule lives in `is_customer_visible`, not in a router

`services/customer_visibility.py::is_customer_visible` is described by its own
module docstring as a **security boundary**: leaking sold, held, bulk or sealed
stock is the failure mode, so the predicate lives in exactly one place and every
reader calls it rather than re-deriving an equivalent condition.

The sticker requirement goes **there**:

```python
return (
    item.status == ItemStatus.AVAILABLE
    and item.kind in CUSTOMER_KINDS
    and (
        getattr(item, "location", None) in CUSTOMER_VISIBLE_LOCATIONS
        or getattr(item, "factory_sealed", False)
    )
    # RFC 0025: a card with no sticker price has no price we are willing to
    # quote. It is not hidden because it is unimportant — it is hidden because
    # the alternative is quoting a market estimate as a sale price.
    and item.sticker_price is not None
)
```

That one edit reaches **every** customer surface at once, which is the entire
reason the predicate exists:

| Caller | Surface |
|---|---|
| `routers/inventory.py::customer_visible_items` | filter-mode search, the authed dashboard summary |
| `routers/public.py` | the anonymous public featured endpoint |
| `services/bedrock.py` (twice, `visible=is_customer_visible`) | chat display hydration |

`sticker_price` is on `_ItemBase`, so both customer kinds (`raw`, `graded`) carry
it and `getattr` is unnecessary.

**There is a fourth copy, in TypeScript, and it must move in the same commit.**
`mcp-server/src/dynamodb-repository.ts` has its own mirror of this predicate
(`PUBLIC_LOCATIONS`, `row.status === "available"`, …) because the MCP server
queries DynamoDB directly. A sticker rule applied on three surfaces and not the
fourth means the chat offers a customer a card the search will not show and no
price is quoted for. Update it, and add the parity assertion — CLAUDE.md's
standing warning about this file is that it has claimed cross-language pinning
that no test actually checked.

### 2. `_display_price` becomes the sticker

```python
def _display_price(item) -> Decimal | None:
    """THE price of an item, and the only one any customer-facing code may use.

    RFC 0025: this is ``sticker_price`` — the price the business actually sells
    the card at, set by hand with the card and its condition in front of the
    person setting it.

    There is no fallback. ``is_customer_visible`` already guarantees a visible
    item has one, so ``None`` here means a caller is asking about an item it
    should never have been holding.
    """
    return item.sticker_price
```

`_apply_price_bounds`, the price sort and the tile all inherit this, which is what
keeps RFC 0008's single-authority invariant intact: they must never diverge again,
and the way to change the price is to change this function, not a caller.

**`hidden_no_price` becomes structurally zero** — a visible item always has a
price now. Keep the field in the response (removing it is a contract change for no
gain) and keep the counting code; it simply never fires. Add a test asserting it
is zero, so the day it is not, something upstream has broken.

### 3. Condition adjustment does not apply to a sticker price

This is the subtle part, and it deliberately narrows a rule CLAUDE.md states
emphatically.

The condition-adjustment rule exists because **the catalog relays one market
figure per finish and that figure is a Near Mint price** — so quoting it for a DMG
card overstates its value by ~6.7×. That measurement (−18.5% across 73 of 228 live
items) is real and the rule that came out of it is right.

**It does not apply to a sticker price, because a sticker price is not a Near Mint
catalog figure.** A human wrote it on the card while holding the card. Multiplying
it by 0.15 because the card is DMG would apply the adjustment a second time, to a
number that already reflects the condition — the identical error CLAUDE.md already
warns about for the stored `current_market_value` ("the nightly denormalizer
already baked the multiplier in — adjusting that would apply it twice").

So:

- **`_condition_adjust` is removed from the customer price path.** The customer
  price is the sticker, unadjusted, on the tile, in the filter bound, in the sort,
  in chat, and in MCP.
- **`apply_condition_adjustment` stays exactly where it is otherwise** — in
  `catalog_sync.refresh_inventory_market_values` (which bakes it into the stored
  `current_market_value`), on the admin surfaces in `routers/admin/inventory.py`,
  and in `mcp-server/src/condition-pricing.ts`'s admin-facing use. **Do not delete
  the module.** Its authority over *market* figures is unchanged; it simply no
  longer decides what a customer is charged.

**Update CLAUDE.md's condition-pricing section in the same change.** It currently
says the adjustment is applied "in exactly ONE place per surface" and names
`_condition_adjust` as the customer one. Leaving that standing after this RFC
would be a doc that actively misleads the next reader, which is the failure mode
the stale-gate-comment lesson is about.

### 3b. This turns two RFC 0022 cells into customer-visibility switches

RFC 0022 makes `sticker_price` and `status` click-to-edit on six admin tables.
After this RFC, **clearing a sticker inline removes the card from the storefront**,
and so does moving `status` off `available` — with nothing on the admin table
saying so.

Whichever of the two RFCs lands second owns the fix, and it is small: RFC 0022's
undo toast already fires on both fields, so it only needs the right words. For a
**cleared** sticker and for a status leaving `available`, the toast reads
**"Removed from the customer site · Undo"** rather than the generic field name.

Note this also changes an existing, deliberate Prep Queue behaviour: clearing a
sticker there says *"Sticker price cleared"* and **keeps the row**, because a
cleared row still meets that queue's `missing_sticker=true` criterion. That stays
correct — the row belongs in the queue — but the same action now also delists the
card, and the message must say both things.

### 4. Measure the impact before merging — this is a gate, not a suggestion

**Before this ships, count how many currently-visible items have a
`sticker_price`, and report the number to the owner.**

The Prep Queue exists because unstickered available inventory is routine. If the
number is 40 of 228, the storefront loses 82% of its stock the moment this
deploys, and that is a business decision the owner should make with the number in
front of them rather than discover afterwards.

Read-only, one `repo.list_inventory()` walk, reported as:

```
customer-visible today:            N
   of which have a sticker price:  M   (M/N %)
   of which do not:                N-M
```

The owner's decision stands unless they change it on seeing the number. This
task's job is to make sure they see it.

### 5. Remove the estimated-value widget

**Frontend** — `frontend/components/inventory/InventoryStats.tsx`: drop the
**"Est. value"** tile. `LABELS` becomes `['Cards in vault', 'Sets tracked']` and
the auto-fit grid reflows on its own (it was already changed from a fixed
`grid-cols-3` to auto-fit for exactly this kind of reason).

**Only the middle tile goes.** "Cards in vault" and "Sets tracked" are counts, not
valuations; they are cheap, harmless and informative. Removing the whole component
would be a larger change than the owner asked for, and it is trivially reversible
if they meant the whole bar.

**Backend** — `GET /inventory/summary`: delete `est_value` from
`InventorySummary` **and the loop that computes it.** That loop is the expensive
part of the endpoint: per item, a catalog lookup plus a `_market_price` finish walk
plus a condition adjustment. Removing it makes the endpoint two counts over one
inventory walk.

Removing a response field is a contract change, so: the frontend stops reading it
in the same change, and a test asserts the key is gone (a field nothing reads is a
field that will be quietly re-derived by someone later).

## API Contracts

```
GET /inventory/search      — unchanged shape; `hidden_no_price` is now
                             structurally always 0
GET /inventory/summary     — `est_value` REMOVED
                             -> { cards_in_vault, sets_tracked }
GET /public/featured       — unchanged shape; the cohort narrows
```

No new endpoints. No model fields added or removed.

## Alternatives Considered

**Fall back to condition-adjusted market when no sticker exists.** The
recommended option, declined by the owner. It keeps the storefront full at the
cost of the exact ambiguity this RFC exists to remove — the customer cannot tell
which prices are real.

**Show the card with no price.** Keeps it browsable and makes it invisible to the
price filter and unsortable by price, so a customer filtering "under $50" gets a
list that silently excludes cards that might qualify. Declined by the owner.

**Filter in the router instead of the predicate.** Fewer lines and it would have
to be repeated in four places, with the chat and the public endpoint the two most
likely to be missed. The predicate is a security boundary and this is exactly the
kind of rule it exists to hold.

**Keep `est_value` on the endpoint and just hide the tile.** A field nothing
renders is a silent serve — the same reasoning that put
`ShowAnalyticsSnapshot.stale` on a page rather than leaving it unrendered.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **The storefront empties out.** | §4 makes measuring and reporting the number a gate before merge. The owner's decision stands, but with the number in front of them. |
| **A surface is missed and quotes a market price.** | The rule goes in `is_customer_visible` and `_display_price`, both of which are documented single authorities with every reader enumerated. The **fourth** copy — `mcp-server/src/dynamodb-repository.ts` — is called out explicitly because it is a separate language and a separate process. |
| **Condition adjustment gets applied to a sticker.** | It is removed from the customer path and CLAUDE.md is updated in the same change so the doc does not keep asserting the old rule. |
| **`apply_condition_adjustment` gets deleted as "unused".** | It is not unused: `catalog_sync`, the admin routers, and the MCP admin path all still call it. The RFC says so and the tests still cover it. |
| **Removing `est_value` breaks a caller nobody remembered.** | `grep` for it across all three workspaces before deleting; a test asserts the key is absent afterwards. |
| **A price the customer sees goes stale because nobody re-stickers.** | A real operational risk and out of scope for this RFC. Prep Queue is the existing tool for finding unstickered stock; "stickered but stale" would need a new signal — see follow-ups. |

## Adversarial review findings (2026-09-02)

1. **Chaos — `mcp-server/src/dynamodb-repository.ts` is a fourth, TypeScript copy
   of the visibility predicate** that queries DynamoDB directly. Missing it means
   the chat offers a card the search hides and quotes no price for it. Added as a
   same-commit requirement with a parity assertion, because this file has a
   recorded history of claiming parity nothing checked.
2. **Correctness — condition adjustment must NOT be applied to a sticker price.**
   The first draft left `_condition_adjust` in place, which would have scaled a
   human-set price by a multiplier meant for a Near Mint catalog figure — the same
   double-application CLAUDE.md already warns about for `current_market_value`.
   Removed from the customer path only; the module stays.
3. **Documentation — CLAUDE.md's condition-pricing section becomes wrong** the
   moment this lands, and it is one of the most emphatic sections in the file.
   Updating it is part of the change, not a follow-up.
4. **Business risk — "hide the card entirely" was accepted without anyone knowing
   the number.** The Prep Queue's existence proves unstickered stock is routine.
   §4 turns measuring it into a gate.
5. **Bloat — the first draft removed the whole `InventoryStats` component.** The
   owner asked for the estimated-value widget. Two counts are not a valuation;
   they stay.
6. **Correctness — `hidden_no_price` becomes structurally unreachable.** Left in
   place (removing it is a contract change for no gain) with a test asserting it
   is zero, so it becomes a tripwire rather than dead code.

## Open Questions

One, and it resolves itself during execution: **§4's measurement.** If the
stickered fraction is small enough that the storefront becomes unusable, report
the number and let the owner reconsider before merging. That is not an escalation
on uncertainty — it is a fact only the live table holds, and the owner is the only
person who can decide what an acceptable storefront size is.
