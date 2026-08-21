# T11 — Triage: one place for everything that might be wrong

**Origin:** owner request 2026-08-05 (not in RFC 0008) · **Layer:** full-stack
**Depends on: T9** (its card-lookup tool *is* catalog search) **and T10** (the override field)

> **The largest item in the set and the only genuinely new feature.** Everything
> else in RFC 0008 is a bug fix or UX polish. If the UI shape feels underspecified
> once you're in the code, run the `design-doc` skill on it — the data model and
> workflows below are settled, the visual design is not.

## Premise (owner, 2026-08-05)

> *"Get rid of the assumption that all data in the system, as well as future data,
> is 100% accurate."*

Triage is the standing answer to that: automation produced this data, so there is
one obvious place to correct it, and **any card can be sent there from anywhere.**

## Name

**`Triage`**, route `/admin/triage`. Recommended over "Workshop": it says *"things
that need fixing"*, it's short enough for the sidebar, and it sets the expectation
that the list drains to empty.

## Yes — Triage *is* the `needs_review` queue

The owner asked whether these are the same thing. They should be, and the codebase
already agrees. `needs_review: bool = False` exists on `_ItemBase`
(`models/inventory.py:198`), is already filterable
(`GET /admin/inventory?needs_review=true`, `admin/inventory.py:93,153-154`), already
has a filter control on the admin inventory page, and is **already set by every
automated path that can get things wrong**:

| Setter | Condition |
|---|---|
| `spreadsheet_import.py:439-444` | match confidence medium/low/empty, or no `card_id`, or blank condition |
| `purchases.py:236` | manual entry, or no `card_id` |

So don't invent a second flag. **"Send to Triage" sets `needs_review = True`.**
One flag, many sources, one queue.

## Two things the existing flag is missing

### 1. A reason. `needs_review` is a bare boolean.

Today 21 items are flagged and nothing records *why* — low match confidence, manual
entry, and a blank condition are indistinguishable, and now humans will add a fourth
source. A queue of 21 cards with no stated problem is not a worklist.

Add **`review_reason: str | None`** to `_ItemBase`.

- Automated setters pass a short machine reason (`"low_match_confidence"`,
  `"manual_entry"`, `"no_catalog_link"`, `"blank_condition"`).
- The "Send to Triage" button prompts for a free-text note (optional but encouraged).
- **Do not reuse `value_note`.** It carries condition-adjustment and FX explanations
  and is deliberately **customer-visible** (`_CUSTOMER_ITEM_FIELDS`, Phase 19).
  A triage reason is internal — keep `review_reason` **out** of that allowlist.

### 2. Protection against automation re-flagging what a human already cleared.

A re-import or a re-sync will set `needs_review = True` again on an item the admin
has already inspected and passed. Without a guard, the queue never drains and the
tab becomes noise — the standard failure mode for review queues.

Add **`reviewed_at: datetime | None`**, set when an admin clears the flag.
Automated setters must **not** re-flag an item whose `reviewed_at` is newer than the
data they're reacting to. Get this right or the feature rots.

> This is the subtlest part of the task. If it turns out the import path can't
> cheaply tell "newer than the data", fall back to: automation never re-flags an
> item with a non-null `reviewed_at`, and clearing `reviewed_at` is itself an
> explicit admin action. Simple and predictable beats clever here.

## Shape: one list with reason chips, not parallel queues

Rather than separate tabs per problem type, render **one list** where each row
carries chips saying why it's there. Items commonly qualify under several reasons
at once (`purchases.py` flags `needs_review` *and* leaves `card_id` null), and
parallel queues would show the same card repeatedly.

Reasons come from two sources:

| Kind | Examples | Clearing |
|---|---|---|
| **Flagged** — stored `needs_review` | manually sent to triage; low match confidence; manual entry | Explicit — admin clears it |
| **Derived** — computed filters | no `card_id` (13 items); JP card with no English name | **Self-healing** — fix the underlying field and the row leaves on its own |

Derived reasons need no flag and no cleanup, which is why they stay computed rather
than being baked into `needs_review` at write time.

Filter the list by reason. Default to showing everything.

## Sizing — measured live, 2026-08-05

```
inventory items: 266
  needs_review flagged:                        21
  no card_id (never matched to a catalog row): 13
  JP items:                                    17   (9 with a card_id)
```

Tens, not thousands — which is exactly why hands-on beats more automation, and why
the queue can realistically reach zero.

## "Send to Triage" from every tab

The owner's requirement: **any card on any tab gets a button.**

**Cheapest correct insertion point: `CardDetailModal`.** Its own docstring says
*"Opens when clicking a card row in any admin page"* — so one button there covers
Inventory, Vault, Sell, Buy, Trade, Show Prep, Prep Queue, History, and card detail
in a single change. Do this first.

Then add a row-level quick action (no modal round-trip) on the list-heavy pages
where spotting a bad card mid-workflow is the actual use case: **Inventory, Vault,
Show Prep, Prep Queue**.

Behaviour:
- Prompts for an optional note → sets `needs_review = True` + `review_reason`.
- Toast confirms, with an **Undo**. Misclicks on a row action are inevitable.
- If already flagged, the button reads "In Triage" and offers to view or clear it —
  never silently no-ops.
- Sidebar nav shows an outstanding count badge. This is what makes the tab get used
  instead of forgotten.

## The two repair tools

### 1. Re-point a mismatched card

Change an item's `card_id` to the correct catalog row. **The dangerous write in this
feature** — `card_id` drives pricing, images, set, and rarity.

- Show a **before/after side-by-side** with images. The admin must see what they're
  changing to.
- Require explicit confirmation.
- Re-run price resolution after a re-point, or say plainly in the UI that it's
  needed — don't leave the admin looking at the old card's price.
- **Warn when the item has lineage** (`lineage_id`, `predecessor_item_id`) or
  transaction history: re-pointing rewrites what a historical record appears to
  refer to. Warn, don't block — fixing an old error is legitimate.
- **Warn loudly on a cross-language link** (an `EN` item to a `ja:` row or vice
  versa). Per `models/inventory.py:38-53` a JP item resolves to a JP catalog row by
  design, so this is nearly always a mistake.

Don't build automated mismatch detection. The owner reports some cards *are*
mismatched, but there's no trustworthy signal — name similarity produces false
positives on legitimately different prints. Make manual re-pointing excellent;
treat detection as a separate later idea.

### 2. Assign an English display name

Writes `display_name_override` (T10). Two paths:

- **Copy from an English catalog card** — search the catalog, pick the English
  equivalent, copy its `name`. The admin is choosing a *name*, not re-linking:
  **`card_id` must not change.** Make that unmistakable in the UI; designing out
  that exact confusion is the owner's stated requirement.
- **Type it manually** — for JP-exclusive prints with no English equivalent, which
  T10's research confirmed is a large and permanent share of the Japanese catalog.

Show the **effective** rendered name (resolved through T10's precedence) for every
item, so the admin sees what the customer sees and can override an English card too.

## Hard dependency on T9

Both tools are built on catalog search, which currently takes **11.2 seconds per
request**. Building Triage first yields a tool that is unusable and looks broken.
**Do T9 first.** Not a soft preference.

## Endpoints

Reuse before adding:

- Listing → existing admin inventory search. It already filters `needs_review`. Add
  filters for `card_id is None` and the JP/no-override case; don't build a parallel
  list endpoint.
- Card lookup → `/admin/market/search` (post-T9).
- Writes → `PATCH /admin/inventory/{item_id}` (`admin_update_item`). Confirm
  `card_id`, `display_name_override`, `needs_review`, `review_reason`, and
  `reviewed_at` are in its allowed-field set. **`card_id` may be excluded today
  precisely because it's dangerous** — if so, permitting it is a deliberate decision
  to record in a code comment, not an oversight to quietly patch.
- New: `GET /admin/triage/counts` for the sidebar badge. Cheap and worth it.

## UI notes

- Add to `navItems` in `AdminShell.tsx`, with the count badge.
- Reuse `CardDetailModal` (widened by T5) rather than building a second editor.
- Fixing an item removes it from the list immediately — match the Prep Queue's
  existing "Priced → removed" toast pattern (CLAUDE.md).
- Empty state should read as success ("Nothing needs review").

## RED — write these first, confirm they fail, then stop

Backend:
1. `PATCH` sets `needs_review = True` with a `review_reason`. Reason field fails today.
2. Clearing review sets `needs_review = False` **and** stamps `reviewed_at`.
3. An automated setter does **not** re-flag an item with a `reviewed_at`.
   **The test that stops the queue from rotting — don't skip it.**
4. `review_reason` is absent from `/inventory/search` output. **Leak guard** —
   internal notes must never reach a customer.
5. Item fixture with none of the three new attributes loads with sane defaults.
   Migration safety.
6. Search filters to `card_id is None`.
7. Search filters to the JP-without-override case.
8. `PATCH` accepts a `card_id` change and persists it. Likely fails today.
9. `/admin/triage/counts` returns per-reason counts.
10. Non-admin rejected on every new/changed route.

Frontend:
11. `CardDetailModal` renders a "Send to Triage" button — assert it appears for an
    item opened from **more than one** page, so the shared-modal assumption is
    actually pinned.
12. Sending to triage posts `needs_review: true` and the note.
13. An already-flagged item shows "In Triage" rather than re-flagging.
14. Row-level quick action works on the inventory list.
15. Undo reverts a send-to-triage.
16. Triage list renders reason chips, including both stored and derived reasons.
17. A card qualifying under two reasons appears **once**, with both chips.
18. Filtering by reason narrows the list.
19. Re-point shows before/after confirmation before writing.
20. Re-point warns on lineage.
21. Re-point warns on cross-language link.
22. **Copying an English name sets `display_name_override` and leaves `card_id`
    unchanged.** The single most important test here — it encodes the owner's core
    requirement.
23. Manual name entry sets the override.
24. Clearing the override reverts to the catalog name.
25. Cleared item leaves the list without a full reload.
26. Empty list renders a success-toned empty state.
27. Sidebar badge reflects the outstanding count.

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "triage or review or inventory or admin_update"
cd frontend && npx vitest run triage CardDetailModal
ruff check backend/src && npm run lint --workspace=frontend
```

Then drive it on live data: clear the 21 flagged items, link the 13 unmatched, name
the 9 linked JP cards. If the tool is good that session is quick — and it doubles as
acceptance testing.

## Done when

- All 27 green; `/admin/triage` reachable with a working count badge.
- "Send to Triage" reachable from every admin tab that shows a card.
- Copying a name never mutates `card_id`.
- A cleared item is not re-flagged by the next import.
