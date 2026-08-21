# T15 — Every card picker shows the card: name, image AND price

**RFC:** 0010 §L · **Layer:** frontend + a small backend addition ·
**Depends on:** — · **Blocks:** — · **Pairs with: T17** (which fills the prices in)
**Owner report, 2026-08-10:** *"when trying to search through the catalog in the triage page,
it is very hard to not have the image of the card displayed with the names… it should be a
clear rule going forward in all work on this project, that when searching for a card, name
alone is not sufficient, it needs to have an image."* Extended the same day: *"I also want
prices displayed as well."*

The rule now lives in **CLAUDE.md** ("A CARD IS NEVER IDENTIFIED BY NAME ALONE"). This task
makes the code match it, and extracts a shared component so it cannot rot back out.

**Three fields, always: name, image, price.** The image answers *"is this the card?"*; the
price answers *"what do I do about it?"* — which at a buy table is the only question that
matters.

> **T15 and T17 are independent, and the dependency runs one way only.** T15 can ship first:
> most catalog rows have **no** price today, so the picker will honestly render "no price yet"
> until T17's weekly cycle fills them in. Build the absent-price states properly and T17 needs
> no frontend follow-up. **Do not wait for T17** — the image half is the daily annoyance.

## Why the rule is a rule

Pokémon names collide relentlessly across sets, printings, finishes and languages, so a list
of names is a list of things the operator cannot tell apart. They are holding the physical
card. The image is the only field that answers *"is this the one?"* — and on the Triage
`missing_english_name` queue the name is in Japanese, so a name-only picker is asking someone
to choose between rows they literally cannot read.

## Both fields are already in the response

`CatalogCard.images` **and** `CatalogCard.prices`
(`backend/src/merlins_collection/models/catalog.py:91-92`) are both populated, and
`GET /admin/market/search` serialises the whole model with `c.model_dump(mode="json")`
(`routers/admin/market.py:121`). **No extra request, no new lookup.** The pickers below were
handed both and threw them away.

Note this is *not* `useCardImages` territory — that hook resolves art for **inventory items**
by `card_id`. A catalog search result already carries `images.small` inline. Do not add a batch
lookup for data you already have.

### The one backend addition: the backend picks the price figure

`prices` is a dict keyed by finish, so "the price of this card" needs a choice — and the
frontend is the wrong place to make it. A catalog result has **no item**, therefore no finish,
and `_market_price(card, finish)` returns `None` without one (`models/inventory.py:413-414`).

So: `GET /admin/market/search` gains two fields per item, computed with the **existing**
authority:

```python
display_price  = _market_price(card, "normal")   # Decimal | None
display_finish = <the finish that figure came from>   # str | None
```

Passing a default finish buys `_market_price`'s entire fallback walk for free — the item's
finish, then `_MARKET_FINISH_FALLBACK`, then any band carrying a figure. **Do not re-implement
that walk in TypeScript.** Its docstring is explicit: *"Do not re-implement this walk in a
caller: a second copy is how that divergence happened"* — the divergence being 174 of 213 live
items silently unpriced. This would be the fifth copy.

## The absent-price cases are the main cases, not the edges

Today most of the 31,603 catalog rows have never had a price fetched, because the nightly depth
pass is scoped to held cards. So get these right first:

| state | how to tell | render |
|---|---|---|
| priced | `display_price != null` | the figure + the finish it came from |
| never fetched | `detail === 'brief'` | **"no price yet"** — T17's cycle will fill it |
| no provider covers it | `detail === 'full'` && `display_price == null` | **"not priced"** — waiting will not help |
| stale | `last_synced_at` older than ~8 days | the figure **plus its age** |

`detail: "brief" | "full"` exists precisely to keep the middle two apart — the model's own
docstring calls it *"an honesty requirement"*. Collapsing both to `—` throws away the only
signal that says whether waiting helps.

**Never render an absent price as `$0.00` or as a blank cell.** `FinishPrice` bands are written
only when a provider actually published a figure, so absent means absent — the same discipline
the graded prices already document (*"'No coverage' is an ABSENT KEY… not one contains a `0`"*).

**A catalog price is a NEAR MINT market figure and is NOT condition-adjusted** — there is no
item, so there is no condition. Do not label it as a sale price or a sticker price.

## Current state, audited 2026-08-10

Five surfaces call `GET /admin/market/search`. Two do it right; three do not:

| Surface | File | Image? |
|---|---|---|
| Buy — catalog autocomplete | `app/(admin)/admin/buy/page.tsx:418-440` | ✅ **the reference** |
| Trade — incoming card search | `app/(admin)/admin/trade/page.tsx:538-562` | ✅ |
| **Triage — both repair dialogs** | `app/(admin)/admin/triage/page.tsx:597-633` (`CatalogPicker`) | ❌ name + `card_id` only |
| **Slabs — card picker** | `components/admin/slabs/SlabEntryForm.tsx:91-110` | ❌ |
| **Market — watchlist add** | `app/(admin)/admin/market/page.tsx:269, 470` | ❌ |

Three of the five were built from Buy's pattern and dropped the image on the way — which is
why the fix is a shared component, not three copies of the same JSX.

## Files

- **Create:** `frontend/components/admin/shared/CardPickerRow.tsx` — one candidate row
- **Create:** `frontend/components/admin/shared/__tests__/CardPickerRow.test.tsx`
- **Modify:** `app/(admin)/admin/triage/page.tsx` — `CatalogPicker` uses it
- **Modify:** `components/admin/slabs/SlabEntryForm.tsx`
- **Modify:** `app/(admin)/admin/market/page.tsx`
- **Modify:** `app/(admin)/admin/buy/page.tsx`, `app/(admin)/admin/trade/page.tsx` — replace
  their inline copies with the shared component, so there is one definition and five callers
- **Tests:** the five page/component test files

## Design

### `CardPickerRow`

Extract Buy's row verbatim, since it is already correct, and give it the one seam the callers
differ on — the action. Triage's two dialogs need *different* actions on the same row shape
("Use this name" vs. select-as-candidate), which is why `renderAction` already exists in
`CatalogPicker` and must survive.

```tsx
<CardPickerRow card={card} onSelect={…} />              // the common case
<CardPickerRow card={card} action={<button …/>} />      // Triage's name dialog
```

The row itself, non-negotiable (this is the CLAUDE.md contract in code):

- `CardImage size="sm"` from `components/admin/shared/CardImage.tsx` — **never a hand-picked
  size**, and never a bare `<img>`;
- a two-line text block: **name** on line 1, `set · #number · rarity` on line 2;
- **the price right-aligned in its own column**, not appended to the metadata line. It is the
  field the eye scans down a list of candidates, and a right-aligned mono column is scannable
  where inline text is not. Use `PriceDisplay` — never a second currency formatter;
- the finish as small secondary text under the price when it is **not** `normal`, since a
  holofoil figure against a normal card is the kind of mismatch that costs money at a buy table;
- `min-w-0 flex-1` on the text block with `truncate` on the name, so a long name shrinks
  instead of shoving the image or the price out of the row. **The price column never shrinks** —
  a truncated price is worse than no price;
- the image **never shrinks and never grows** — `flex-shrink-0` belongs here, unlike in T6's
  modal where it was the bug (a fixed 56×78 thumb is not competing for the row's width);
- **a card-less or failed image renders the placeholder**, so every row is the same height.
  Rows that change height as art loads make the list jump under the cursor mid-click — which
  on a picker means selecting the wrong card;
- `card_id` stays visible, in mono, as *tertiary* text. It is how a re-point is verified, and
  Triage's dialogs already show it.

### Readability is part of the acceptance criteria, not a bonus

Owner: *"the UI has to be thought about so that adding an image next to the name is still
readable, not squished into a page, and looks very clean from a design perspective so that
users can do things as quickly as possible."*

So:

- **Give the dropdown room.** A 56×78 thumb plus two text lines needs ~5rem of row height;
  Triage's list is capped at `max-h-56` (14rem ≈ 3 rows) and Buy's at `max-h-56` too. Raise
  both so ~5 candidates are visible without scrolling — scanning five cards at a glance is the
  whole workflow.
- **The dialog has to fit it.** Triage's `Dialog` is `max-w-lg` (`triage/page.tsx:654`). With
  art in the rows that is tight; widen to `max-w-2xl`. Check it against T6's lesson — a picker
  squeezed until the name truncates to three characters is worse than the name-only list it
  replaced.
- Keep the existing debounce (200ms in Triage, 300ms elsewhere) and never fire a request per
  row.

### Do not break what already works

Buy's autocomplete has a `searchSeqRef` **sequence guard** that stops a slow search from
overwriting a newer one's results, and it deliberately does **not** mirror the
`!api.isAuthenticated` early return (a test's mock api has no such field, so copying it makes
every catalog search return early). Both notes are recorded in RFC 0009's T4 doc. Refactoring
Buy to use the shared row must not disturb either.

## RED — write these first, show the failing output, wait for confirmation

**Backend (4):**
1. `GET /admin/market/search` returns `display_price` and `display_finish` per item;
2. a card priced only under `holofoil` still yields a figure, with `display_finish: "holofoil"` —
   this proves `_market_price`'s fallback walk is being used rather than an exact match;
3. a card with **no** bands yields `display_price: null` — **not `0`**;
4. `detail` is present on every item so the frontend can tell "never fetched" from "not covered".

**`CardPickerRow` (10):**
5. renders the card's `images.small` through `CardImage`;
6. renders name, set, number and rarity;
7. **renders the price**;
8. shows the finish when it is not `normal`, and omits it when it is;
9. **`detail: 'brief'` renders "no price yet"** — never `$0.00`, never blank;
10. **`detail: 'full'` with no price renders "not priced"** — a different string from row 9,
    asserted as different, because that distinction is the whole point of `detail`;
11. a stale `last_synced_at` renders the figure **plus its age**;
12. **a card with no `images` renders the placeholder, not a collapsed row** — assert the row is
    still present and the image slot is occupied;
13. a long name truncates rather than displacing the image or the price (assert the truncate class
    on the text block, `flex-shrink-0` on the image, and that the price column is not truncated);
14. `onSelect` fires with the card, and a custom `action` renders in place of the default.

**Per surface (5 × 2) — for Triage, Slabs, Market, Buy and Trade:**
15. a search result row renders **both the image and the price**;
16. selecting a row still does what it did before (sets `card_id` / adds to the watchlist /
    picks the candidate). This is the regression half, and it matters more than the display half —
    five pickers are being edited and each one writes something different.

**Triage specifically (2):**
17. the **name** dialog's "Use this name" button still writes `display_name_override` and
    **never** `card_id` — the one rule in that feature that must not break;
18. the **re-point** dialog still goes through its two-stage confirm with the before/after diff.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_market.py -q --tb=short
cd frontend && npx vitest run components/admin/shared/__tests__/CardPickerRow "app/(admin)/admin/triage" "app/(admin)/admin/buy" "app/(admin)/admin/trade" "app/(admin)/admin/market" components/admin/slabs --reporter=verbose
```

## GREEN — done when

The above pass, **every** pre-existing test in those five files passes (they cover three live
money paths — buy, trade and slab intake), and `npm run lint --workspace=frontend` is clean.

Run `npm run build --workspace=frontend`: five call sites adopting one new component signature
is exactly the shape of change vitest cannot typecheck.

## Manual check — with real cards in hand

Search a name that has many printings (`Charizard`, `Pikachu`) in **all five** pickers and
confirm you can tell the candidates apart at a glance. Then, on Triage's
`missing_english_name` queue, search a Japanese card and confirm the art is what lets you pick
it — that is the case that motivated the report.

Confirm the price column: a held card (which the daily depth pass has priced) shows a figure,
and an unheld one shows **"no price yet"** rather than `$0.00`. That asymmetry is expected until
T17 runs, and seeing it is how you know the absent-price states are right.

At 100% and 150% zoom, confirm no picker squeezes the name into unreadability and no price
truncates.

## Do not

- Do not add a second request. Both the art and the prices are already in the response.
- **Do not compute the display price in TypeScript.** `_market_price` is the one authority and
  this would be its fifth reimplementation.
- Do not use `useCardImages` here — that is for inventory items by `card_id`; a catalog result
  carries `images.small` inline.
- Do not hand-pick an image size. `CardImage`'s named sizes only.
- Do not render an absent price as `$0.00` or a blank cell.
- Do not collapse `detail: "brief"` and an unpriced `"full"` row into the same message.
- Do not present a catalog price as condition-adjusted or as a sticker price.
- Do not let a missing image collapse a row.
- Do not ship art at the cost of the name. If the name truncates to nothing, the row is wrong.
- Do not block on T17. The picker renders honestly with no prices at all.
- Do not disturb Buy's `searchSeqRef` guard, and do not add its `!api.isAuthenticated` check to
  anything.
- Do not let Triage's name dialog write `card_id`. Ever.

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

**T17 — Every catalog card is re-priced at least once a week, by Friday**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t17-weekly-catalog-price-cycle.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
