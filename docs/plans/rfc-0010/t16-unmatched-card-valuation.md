# T16 — A card with no catalog match still gets a price and a sticker

**RFC:** 0010 §M · **Layer:** backend + frontend · **Depends on: T3, T15** · **Blocks:** —
**Owner question, 2026-08-10:** *"what do we do when we have a card that doesn't have a matching
catalog card? We still are selling it and we need a price for it as well as updating the
sticker."*

## The short answer: it already works, and nothing tells you so

Researched 2026-08-10. Three facts, in the order that matters:

**1. A hand-typed value on an unlinked item is SAFE.** `refresh_inventory_market_values`
(`services/catalog_sync.py:395-397`) opens with:

```python
for item in repo.list_inventory():
    if item.kind not in ("raw", "graded") or item.card_id is None:
        continue
```

So the nightly denormalizer **skips unlinked items entirely.** A `current_market_value` typed by
hand is never overwritten. This is the load-bearing fact — without it, manual valuation would be
a lie.

**2. An unlinked item is still customer-visible and still sellable.** `_is_customer_visible`
gates on status and location, not on `card_id`. `CardTile` renders
`item.card?.market_price ?? item.listed_price` — so with no catalog card it falls back to
**`listed_price`**, which is admin-typed.

**3. The sticker never depended on the catalog.** `sticker_price` is typed by hand on Prep Queue
and Show Prep already, for every item.

So the capability exists. What is missing is that **nothing surfaces it, nothing guides it, and
two things quietly misreport it.** This task closes that gap; it does not build a new pricing
system.

## What is actually broken

**A. There is no route from "this card has no catalog match" to "here is what it's worth."**
Triage's `missing_card_id` queue offers *Assign English name* and *Re-point* — both of which
assume a catalog card exists to point at. For a card genuinely absent from the catalog (a
JP-exclusive print, a promo TCGdex never carried), neither tool applies, and the row is
undrainable by construction. That is the owner's question, exactly.

**B. The condition multiplier does NOT get applied to a hand-typed value.** For a *linked* item,
`refresh_inventory_market_values` calls `apply_condition_adjustment` before storing
`current_market_value` (`catalog_sync.py:408-411`), so the stored figure already has LP ×0.82 /
MP ×0.58 / HP ×0.33 / DMG ×0.15 baked in — and CLAUDE.md warns that **adjusting it again would
apply it twice.** For an *unlinked* item nothing runs, so whatever is typed is used verbatim.

**Whoever types the number must type the condition-appropriate number**, and the UI has to say
so. Otherwise an admin reads an NM comp off eBay, types it on an MP card, and the customer sees
a price ~1.7× too high — the same failure mode as T3's `blank_condition` finding.

**C. An unlinked GRADED slab has nowhere to store a graded price.** Graded values live in
`CARD#<card_id>` / `GRADEDPRICE#<company>#<grade>` rows, so they are **keyed by `card_id`**.
`PUT /admin/slabs/{id}/price/pin` already returns 404 *"This slab is not linked to a catalog
card, so it has no price row to pin"* (`routers/admin/slabs.py:360-395`). So for an unlinked
slab the **only** place a value can live is the item's own `current_market_value` /
`listed_price` / `sticker_price`. That is fine — but it means "priced" means something different
for a linked slab than an unlinked one, and the code should say which.

**D. Market coverage counts these as unpriced.** `/admin/market`'s coverage/confidence panel and
`/admin/slabs?priced=false` both answer "what still needs a price?". A hand-valued unlinked card
**has** a price and should not be nagging in a worklist forever — but it should also not be
counted as *market-derived* coverage, because nobody synced it. Two different truths that
currently collapse into one number.

## Design

### A named concept: **manually valued**

Not a new field. An item is manually valued when it has a `current_market_value` (or
`listed_price`) and **no** `card_id` — which is already exactly the set of items the nightly job
skips. Deriving it rather than storing a flag means it cannot go stale, and it is the same
self-healing discipline as Triage's derived reasons.

`value_note` (already on the model, already used by `apply_condition_adjustment` to record its
multiplier) is where the *provenance* goes: `"hand-valued 2026-08-11, NM comp $40 × MP 0.58"`.
That is one field doing one job — recording why a number is what it is — and it is the existing
precedent for the codebase's one currency conversion, too.

### 1. A fourth Triage repair tool: **Set a value by hand**

On a `missing_card_id` row, beside *Assign English name* and *Re-point*. A small dialog that:

- states plainly that this card is not in the catalog, so **no sync will ever price it**;
- takes a market value through **T0's `MoneyInput`** (so `1,300` works), plus an optional
  sticker price;
- **shows the item's condition and the multiplier that applies to it**, and offers to compute
  the adjusted figure from an NM comp — *"NM comp $40 × MP (0.58) = $23.20"* — so the admin does
  not have to remember the table. Reuse the multipliers from `frontend/lib/` if they are mirrored
  there, or add the mirror; **do not hardcode a second copy of the table** (the backend authority
  is `services/condition_pricing.py`);
- writes `current_market_value`, optionally `sticker_price`, and a `value_note` recording the
  basis and the date;
- **does not clear `needs_review`** by itself. Valuing a card is not the same as confirming its
  identity, and the row's `missing_card_id` reason is derived and stays until the card is
  actually linked. Say that in the dialog, or the admin will think the tool is broken.

**Do not write `card_id`.** Same rule as the name dialog — this tool sets a value, nothing else.

### 2. The same affordance where the work actually happens

Prep Queue already edits `sticker_price` inline and is the sticker workflow. Add, for a row with
no `card_id`, a visible marker (*"not in catalog — value is hand-set"*) so an admin pricing a
stack understands why there is no market figure to compare against. After T7 they can filter by
location, so this is the screen where a shelf gets priced.

`CardDetailModal` already exposes `current_market_value`, `listed_price`, `sticker_price` and
`value_note` as editable rows (RFC 0008 T5), so the *modal* needs nothing new — but it should
render the "manually valued" marker too, so the number's provenance is visible next to it.

### 3. Report it honestly

- `/admin/market` coverage: report manually-valued items as a **third** category — *market-priced
  / hand-valued / unpriced* — not folded into either. One number that means two things is how a
  worklist stops being trusted.
- `/admin/slabs?priced=false`: an unlinked slab with a hand-set `current_market_value` is
  **priced**, and the list should say *hand-set* rather than showing a provider source it never
  had. `GET /admin/slabs` already returns a `source` per row (`"manual"` / `"provider"`) from RFC
  0009 T6 — extend that vocabulary rather than inventing a parallel one.

### 4. What this task does NOT do

- **It does not add the card to the catalog.** Creating local catalog rows for cards TCGdex does
  not carry is a much larger feature (identity, images, set membership, sync interaction) and it
  is not what the owner asked for. If it ever happens, it supersedes this task rather than
  extending it — note that in `follow-ups.md`.
- **It does not price unlinked cards automatically.** The pricing vendor's name search was
  measured wrong ~1/3 of the time and the owner has twice declined to attach a price without a
  verified join (2026-08-09, and again for slabs in T12). A hand-set number is honest; a guessed
  one is not.

## RED — write these first, show the failing output, wait for confirmation

**Backend (5):**
1. `refresh_inventory_market_values` **leaves a hand-set `current_market_value` on an unlinked
   item untouched** — the invariant everything else rests on. Name the test for it;
2. it still updates a linked item (the regression gate);
3. `PUT /admin/inventory/{id}` accepts `current_market_value` + `value_note` on an unlinked item;
4. `GET /admin/slabs` reports an unlinked slab with a hand-set value as **priced**, with a
   hand-set source;
5. market coverage reports hand-valued items as their own category, and the three categories sum
   to the total.

**Frontend (7):**
6. the **Set a value by hand** tool appears on a `missing_card_id` row and **not** on a linked one;
7. it writes `current_market_value` and `value_note`, and **never `card_id`**;
8. it shows the item's condition multiplier and computes the adjusted figure from an NM comp;
9. it accepts `1,300` (T0's `MoneyInput`);
10. **it does not clear `needs_review`**, and the row stays in the queue;
11. Prep Queue marks a no-catalog row as hand-valued;
12. `CardDetailModal` renders the hand-valued marker beside the value.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short -k "catalog_sync or slab or market_coverage"
cd frontend && npx vitest run "app/(admin)/admin/triage" "app/(admin)/admin/outgoing" components/admin/shared/__tests__/CardDetailModal --reporter=verbose
```

## GREEN — done when

The above pass, pre-existing `catalog_sync` / slab / market tests pass, `ruff check backend/src`
is clean, and `npm run lint --workspace=frontend` is clean.

## Manual check

Take a real card that is not in the catalog. From Triage, hand-value it using an NM comp and the
condition helper. Confirm: it shows that price on `/inventory` as a customer, it can be sold
through `/admin/sell`, its sticker can be set from Prep Queue, and **the value is still there
after `POST /admin/market/sync`** — that last one is the whole point.

## Do not

- Do not add a `manually_valued` boolean. It is derivable, and a stored flag would go stale.
- Do not let this tool write `card_id`.
- Do not apply the condition multiplier **twice**. The stored `current_market_value` on a linked
  item already has it baked in (CLAUDE.md); this path is for items the job never touches.
- Do not hardcode a second copy of the condition multiplier table.
- Do not clear `needs_review` on valuing. The identity problem is separate from the price problem.
- Do not auto-price an unlinked card off a name search. Declined twice by the owner.
- Do not create local catalog rows. Out of scope; file it.
- Do not report a hand-set number as provider-sourced coverage.

---

## Done means: committed, recorded, and the next prompt emitted

This task is finished when **all five** of these are true. Four is not done.

1. **The narrow test selection above passes**, and you have shown the output. Not "should pass".
2. **[`progress.md`](progress.md) is updated** — this row set to `DONE` with the commit sha, a
   Notes line if a later task needs to know something, and anything surprising added to the
   Decisions table.
3. **Out-of-scope findings are appended to [`follow-ups.md`](follow-ups.md)** — not fixed as a
   side errand, and not left only in the conversation.
4. **The work is committed.** One focused commit, or a small series, in this branch's
   conventional-commit style (`feat(scope):` / `fix(scope):` / `docs(scope):`). Do not merge, do
   not push unless asked.
5. **Your final output is the ready-to-paste prompt below**, so a fresh conversation can pick up
   the next task without the owner reconstructing anything.

### Next in the chain

**T8 — Dates stop rendering a day early**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t8-local-date-formatting.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
