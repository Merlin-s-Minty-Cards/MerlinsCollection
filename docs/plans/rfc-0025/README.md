# RFC 0025 — Task Index

**RFC:** [`docs/rfcs/0025-customer-sticker-pricing.md`](../../rfcs/0025-customer-sticker-pricing.md)
**Round guide:** [`docs/plans/round9/README.md`](../round9/README.md) — read it first.
**Progress:** [`progress.md`](progress.md) · **Follow-ups:** [`follow-ups.md`](follow-ups.md)

The smallest RFC in Round 9 and the one with the largest blast radius on what
customers see. **Scheduled last**, so it lands on a branch that is otherwise
already green.

| Task | Title | Depends on | Suite |
|---|---|---|---|
| T1 | Measure the stickered fraction + report | — | none (read-only, live) |
| T2 | Sticker rule in `is_customer_visible` + `_display_price` | T1 | backend |
| T3 | MCP TypeScript mirror | T2 | mcp |
| T4 | Remove condition adjustment from the customer price path | T2 | backend, mcp |
| T5 | Remove the Est. value widget + `est_value` | — | backend, frontend |
| T6 | Docs + full-suite verification | all | all |

---

## T1 — Measure the stickered fraction

**No code changes. Read-only against live. This is a gate, not a formality.**

One `repo.list_inventory()` walk. Report:

```
customer-visible today:            N
   of which have a sticker price:  M   (M/N %)
   of which do not:                N-M
```

**Then report it to the owner before T2 merges.** The Prep Queue
(`/admin/outgoing`) exists specifically to find unstickered available inventory,
which means unstickered stock is a routine state — if the stickered fraction is
small, this RFC removes most of the storefront. The owner's decision ("hide the
card entirely") stands unless they change it, but they should see the number
first. That is not escalating on uncertainty: it is a fact only the live table
holds, and only the owner can decide what an acceptable storefront size is.

---

## T2 — Sticker rule in `is_customer_visible` + `_display_price`

**Files:** `backend/src/merlins_collection/services/customer_visibility.py`,
`backend/src/merlins_collection/routers/inventory.py`, tests for both.

Add `and item.sticker_price is not None` to `is_customer_visible`, with the
comment from the RFC's §1 explaining *why* (not what).

`sticker_price` is on `_ItemBase`, so both customer kinds carry it — no `getattr`
needed.

**Why the predicate and not a router filter:** that module's own docstring calls
it a security boundary and enumerates its readers. One edit reaches the
filter-mode search, the authed dashboard summary, the anonymous public featured
endpoint, and chat's display hydration (`services/bedrock.py`, twice, via
`visible=is_customer_visible`). A router filter would need repeating in four
places and the two most likely to be missed are the two least visible.

`_display_price` becomes `return item.sticker_price` — no fallback. Update its
docstring; it currently explains at length why market beat `current_market_value`,
and that history is worth keeping as context but must not read as current
behaviour.

`hidden_no_price` becomes structurally zero. **Keep the field and the counting
code** (removing it is a contract change for no gain) and add a test asserting it
is zero — that turns dead code into a tripwire.

**RED first.** Tests: an available, glass-located, stickerless item is **not**
visible; the same item with a sticker **is**; `_display_price` returns the
sticker and never the market; the price filter bounds against the sticker; the
price sort orders by sticker; `hidden_no_price` is 0; the public featured
endpoint and the chat hydrator both narrow.

---

## T3 — MCP TypeScript mirror

**File:** `mcp-server/src/dynamodb-repository.ts` and its tests.

**This is a fourth copy of the visibility predicate, in another language, in
another process** — it queries DynamoDB directly (`PUBLIC_LOCATIONS`,
`row.status === "available"`, …). Apply the same sticker rule and make the
customer price the sticker.

**Land it in the same commit as T2.** A rule applied on three surfaces and not the
fourth means the chat offers a customer a card the search will not show and quotes
no price for.

Add the parity assertion. CLAUDE.md's standing warning about this file is that it
has claimed cross-language pinning nothing ever checked — a comment saying "mirrors
the Python" is not a test.

---

## T4 — Remove condition adjustment from the customer price path

**Files:** `backend/src/merlins_collection/routers/inventory.py`
(`_condition_adjust` and its enrichment call), `services/bedrock.py:437`,
`mcp-server/src/dynamodb-repository.ts`.

**The reasoning, and it must go in the code comment:** the condition adjustment
exists because the catalog relays one market figure per finish and that figure is
a **Near Mint** price. A sticker price is not a catalog figure — a human wrote it
while holding the card, condition included. Scaling it by 0.15 for a DMG card
applies the adjustment twice, the identical error CLAUDE.md already warns about
for the nightly-denormalized `current_market_value`.

**Do NOT delete `services/condition_pricing.py` or
`mcp-server/src/condition-pricing.ts`.** They are still called by
`catalog_sync.refresh_inventory_market_values` (which bakes the multiplier into
stored `current_market_value`), by `routers/admin/inventory.py`, and on the MCP
admin path. Their authority over *market* figures is unchanged; they simply no
longer decide what a customer is charged.

**Update CLAUDE.md's condition-pricing section in this same task**, not in T6. It
currently names `_condition_adjust` as the customer-side application point, and
leaving that standing is exactly the stale-justification failure this repo has
already recorded twice.

---

## T5 — Remove the Est. value widget + `est_value`

**Files:** `frontend/components/inventory/InventoryStats.tsx` and its test,
`frontend/app/(auth)/inventory/__tests__/page.test.tsx`,
`backend/src/merlins_collection/routers/inventory.py` (the `/inventory/summary`
handler and `InventorySummary`), `frontend/lib/inventory.ts`.

Frontend: drop the **"Est. value"** tile only. `LABELS` becomes
`['Cards in vault', 'Sets tracked']`. The grid is already `auto-fit` (changed from
a fixed `grid-cols-3` after a real 390px overflow measurement) so it reflows on its
own.

**Only the middle tile.** Two counts are not a valuation and the owner asked for
the estimated-value widget.

Backend: delete `est_value` from `InventorySummary` **and the loop that computes
it** — per item, a catalog lookup plus a `_market_price` finish walk plus a
condition adjustment. That loop is the expensive part of the endpoint.

`grep` for `est_value` across **all three workspaces** before deleting, and add a
test asserting the key is absent afterwards.

---

## T6 — Docs + full-suite verification

- `CLAUDE.md`: the customer price is the sticker; a stickerless card is hidden;
  where condition adjustment still applies and where it no longer does; the
  `/inventory/summary` shape change. (The condition-pricing edit itself belongs to
  T4 — do not defer it here.)
- Every suite in the round guide, plus `npm test --workspace=mcp-server`, which
  this RFC is one of the few to actually touch.
