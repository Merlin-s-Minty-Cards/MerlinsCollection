# T3 — Triage: the server says why, one filter narrows, the queue can reach zero

**RFC:** 0010 §B · **Layer:** full-stack · **Depends on:** — · **Blocks:** T4
**Owner report:** plan doc item 2

## The report

> *"The triage seems to be pulling a lot more than just the cards marked to be in the triage
> menu, i assume these are cards without stickers, and as of now the filter doesn't filter by
> reasons it still lists all these non flagged cards when you filter by each reason, fix so
> that these cards aren't pulled unless they have a why reason, create an additional why
> reason (sticker needs to be updated) and make filter actually filter by these tags"*

Screenshot: **266** rows, "All reasons" selected, WHY column reading empty.

## Read this before you start: the query is NOT broken

The predicates were probed directly against the model on 2026-08-10
(`services/triage.py` + `InventoryItemAdapter`):

| item | `needs_triage` | reasons |
|---|---|---|
| EN raw, linked | `False` | — |
| EN raw, no `card_id` | `True` | `missing_card_id` |
| JP raw, no override | `True` | `missing_english_name` |
| JP raw, **with** override | `False` | — |
| EN raw, `needs_review=True` | `True` | `flagged` |
| sold EN raw, linked | `False` | — |
| sealed / bulk | `False` | — |

**There is no "pulls everything" bug.** The owner's guess ("cards without stickers") is not
what is happening — no predicate reads `sticker_price`.

**The 266 rows are the spreadsheet import's own flags.** `import_singles` sets
`needs_review = True` for every row whose matcher confidence was anything but `high`, and
separately for every row with a blank condition
(`services/spreadsheet_import.py:475-484, 498-502`), stamping `review_reason` from
`MACHINE_REVIEW_REASONS` — `low_match_confidence`, `no_catalog_link`, `blank_condition`. On a
bulk import of a hand-kept spreadsheet, that is most of the sheet.

So Triage is behaving as designed, and the **design is wrong for how it is used**: a queue
whose stated goal is to reach zero was seeded with hundreds of machine flags a human cannot
drain. The owner's phrasing is the right fix.

> ### ⚠️ `blank_condition` is a MONEY bug, not queue noise. Do not treat it as clutter.
>
> The importer's own comment says *"A card with no condition: default NM but flag it rather
> than drop"* — `condition, modifier, blank_condition = Condition.NM, None, True`
> (`services/spreadsheet_import.py:437-443`).
>
> **`Condition.NM` is the most expensive tier**, and every customer-facing price is
> condition-adjusted from it (`services/condition_pricing.py` — LP ×0.82, MP ×0.58, HP ×0.33,
> DMG ×0.15). So a card whose real condition is LP is being shown to a buyer at **1.22× what
> it is worth**, and an MP card at **1.72×** — wrong in the *business's* favour, which is the
> exact failure the condition-pricing work was built to fix (CLAUDE.md: a DMG card was once
> shown at ~6.7× its value).
>
> **Consequence for this task:** `blank_condition` is the highest-value queue in Triage, and
> it is *fixable* — someone has the card in hand. It must be easy to filter to and easy to
> resolve in place. See "a third repair tool" below. **It must NOT be bulk-cleared.**

**The importer will not run again — owner, 2026-08-10:** *"We will most likely never run the
importer again. That was a one time thing, but we are actively reviewing and adding cards to
match the sheet until we will eventually drop the sheet altogether."*

Two consequences, both simplifying:

1. **Nothing refills the queue.** A cleared flag stays cleared, so draining Triage is a
   one-way job rather than a treadmill. The open question about changing the importer's
   flagging behaviour is **closed — do not touch the importer.**
2. **Triage is now the primary reconciliation workflow**, not a janitorial afterthought. The
   owner is working through these rows against the sheet by hand. That raises the bar on
   ergonomics: filtering, searching (T4) and fixing in place are the features that matter,
   and a blunt "clear everything" button is the *least* useful thing here.

**First action of this task: run the diagnostic** and record the numbers in `progress.md`,
because they decide how much of §B.5 matters:

```bash
# with the app running and an admin token
curl -s -H "Authorization: Bearer $TOKEN" "$API/admin/triage/counts" | python -m json.tool
```

That returns `total` plus a **per-reason breakdown**. If `flagged` accounts for ~all 266, the
bulk clear is the load-bearing part of this task. If `missing_card_id` does, the re-point tool
is, and the bulk clear is a nicety.

## ⚠️ The requested sticker reason is NOT built — owner decision, 2026-08-10

Asked to choose between a stored and a derived form, the owner reframed the question:

> *"Triage is not for stickers that need updating, it is for cards with correctness issues
> that need manual fixing from an admin."*

**Do not add the reason.** The clarification overrides the written plan document. Derived, it
would have added ~224 rows to a list the owner wants to shrink and duplicated Prep Queue;
stored, it would have made Triage a second sticker worklist. The need it described is served
by **Prep Queue**, which *is* the unstickered-inventory list, and which **T7** makes
filterable by location.

Triage's reason set stays at the three correctness reasons.

## Files

- **Modify:** `backend/src/merlins_collection/services/triage.py` — a `reasons_for(item)`
  function beside `needs_triage`
- **Modify:** `backend/src/merlins_collection/routers/admin/inventory.py` — emit
  `triage_reasons`, add the `triage_reason` filter, scope statuses, add the bulk-clear route
- **Modify:** `frontend/lib/triage.ts` — labels for machine reasons; demote `reasonsFor`
- **Modify:** `frontend/app/(admin)/admin/triage/page.tsx` — render server reasons, one filter,
  status toggle, bulk clear
- **Tests:** `backend/tests/routers/admin/test_triage.py` (corrected as executed —
  `backend/tests/test_admin_inventory.py` does not exist),
  `frontend/app/(admin)/admin/triage/__tests__/page.test.tsx`,
  `frontend/lib/__tests__/triage.test.ts`

## Design

### B.1 — The server emits the reasons it used

Today membership is decided in Python (`services/triage.py:66-75`) and the chips are
recomputed in TypeScript (`frontend/lib/triage.ts:60-68`) from a hand-mirrored copy of the
same three rules. The mirror is faithful **today** — that was verified, not assumed — which is
exactly why a later drift would be silent, and a row with no chip is the owner's own report.

Add to `services/triage.py`:

```python
def reasons_for(item: InventoryItem) -> list[str]:
    """Every reason this item is in the queue, in TRIAGE_REASONS order.

    `needs_triage(item)` is exactly `bool(reasons_for(item))`. Keep them that way:
    a row in the list with no reason is the defect this function exists to make
    impossible.
    """
    return [name for name, matches in TRIAGE_REASONS.items() if matches(item)]
```

and express `needs_triage` in terms of it, so they cannot diverge.

`admin_search_inventory` sets `row["triage_reasons"]` on every serialized row when
`triage=true`, alongside the `card` join it already attaches (`admin/inventory.py:255-256`).
Scoped to `triage` for the same reason the join is: the ordinary admin search keeps its payload
and its cost.

The page renders **that array**. `reasonsFor()` survives only for optimistic local updates
(the page predicts the next state before a refetch — `triage/page.tsx:101, 264, 281`), with a
comment saying it is a *prediction*, not the authority.

### B.2 — One filter parameter

The page currently maps its dropdown onto three separate params — `needs_review`,
`missing_card_id`, `missing_english_name` (`triage/page.tsx:67-69`), each a distinct backend
filter (`admin/inventory.py:101-107, 164-182`). Two problems: `flagged` narrows by the
**stored boolean** rather than by the predicate that produced the chip, and a new reason has
no param at all.

Add `triage_reason: str | None`, validated against `TRIAGE_REASONS` keys (**422** on an
unknown key — not a silent no-op, which is how a broken filter looks like a broken list), and
applied with the same predicate that built the union. Adding a reason later then means adding
one row to `TRIAGE_REASONS` and nothing else.

Keep the three existing params for backward compatibility; the Triage page stops using them.

### B.3 — Human labels for machine reasons

`flagged` renders `item.review_reason` raw (`triage/page.tsx:153-155`), so an imported row
reads `low_match_confidence`. Add a label map over `MACHINE_REVIEW_REASONS`:

| stored | shown |
|---|---|
| `low_match_confidence` | The matcher wasn't sure this is the right card |
| `no_catalog_link` | Imported with no catalog match |
| `blank_condition` | No condition on the imported row |
| `manual_entry` | Entered by hand |
| `cert_lookup_failed` | Cert lookup failed *(legacy — see note)* |

An admin's **free-text** note is not in that set and passes through verbatim. That
set-membership test is what separates the two, and T3's bulk clear depends on it being exact.

*Note:* `cert_lookup_failed` describes a PSA flow that RFC 0010 §H drops. Leave the label —
old rows may carry it — but do not add new writers.

### B.5 — Making the queue drainable

**Status scope.** `triage=true` applies no status filter, so a `sold` card's data quality sits
in a worklist forever. Default to non-terminal statuses; add an "include sold" checkbox that
sends the existing `status` param or a new `include_sold` flag. Whichever you choose, the
**count endpoint must agree** — `GET /admin/triage/counts` and the list must never scope
differently, which is the invariant `services/triage.py`'s docstring exists to protect.

**A third repair tool: set the condition.** The row already carries *Assign English name* and
*Re-point* (`triage/page.tsx:170-185`). A `blank_condition` row's fix is neither of those — it
is a condition, and the admin is holding the card. Add an inline **Condition** control using
`CONDITION_OPTIONS` (`frontend/lib/constants.ts` — `NM, LP+, LP, LP-, MP, HP, DMG`) and
`parseCondition`, writing `condition` + `condition_modifier` through the existing
`PUT /admin/inventory/{id}` (`_split_combined_condition` already handles the combined form).

**Never send a combined `"LP+"` as the `condition` value** — storage is always the two
separate fields, and sending the combined form is the Round 1 enum-validation bug (CLAUDE.md,
"Condition vocabulary").

Setting a condition does **not** clear `needs_review` by itself — the flag and the data are
separate facts — so the row keeps its chip until an admin clears it. If that proves annoying in
use, clearing the flag on a condition write is a one-line change; do not guess now.

**Bulk clear of machine flags — narrow it, and exclude `blank_condition`.**
`POST /admin/inventory/bulk-clear-review`, taking the same filter arguments as the search so
"clear what I am looking at" is expressible. It clears `needs_review` **only** for items whose
*only* reason is `flagged` **and** whose `review_reason` is in `MACHINE_REVIEW_REASONS`.

**`blank_condition` is excluded from bulk clear** — see the money-bug box above. Clearing it
in bulk would silently accept an NM price on every card whose condition nobody ever checked.
Make that an explicit exclusion in the code with the reason in a comment, not an omission
somebody later "fixes".

Consequences of the narrowing, all deliberate:

- a hand-flagged card (free-text note) can never be caught by it;
- an item that is *also* unlinked or unnamed keeps its other reasons and stays in the list —
  clearing the flag does not clear the problem;
- `reviewed_at` is server-stamped, and `_apply_review_transition`
  (`admin/inventory.py:1103-1147`) already prevents automation re-flagging a reviewed item, so
  the bulk path inherits the anti-rot guarantee for free.

Response returns the count cleared. The UI confirms with the **exact count** before firing —
"Clear 231 machine flags?" — never a bare "Clear all", and it names which reasons are included.

**Do not change the importer.** The owner will not run it again (see above), so its flagging
behaviour is now historical. Editing it would be dead code with a live blast radius.

## RED — write these first, show the failing output, wait for confirmation

**`reasons_for` (backend, 4):** returns `[]` for an ordinary EN linked raw item; returns both
reasons for an unlinked JP item with no override; is in `TRIAGE_REASONS` order;
**`needs_triage(i) == bool(reasons_for(i))` for every probe case** — that equivalence is the
invariant, assert it directly.

**Search response (backend, 3):** `?triage=true` rows each carry a **non-empty**
`triage_reasons`; a non-triage search does **not** carry the key (payload cost); the array
matches `reasons_for` for a crafted item.

**`triage_reason` filter (backend, 4):** `triage_reason=flagged` returns only flagged items;
`=missing_card_id` returns only unlinked ones; an item qualifying under two reasons appears
under **both** filters; an unknown key → **422**.

**Status scope (backend, 2):** a sold item with a triage reason is absent by default and
present with the include flag; **`/admin/triage/counts` and the list agree** under the same
scope.

**Bulk clear (backend, 6):** clears a machine-flagged item; **does NOT clear a human-noted
one**; **does NOT clear a `blank_condition` item** (the money-bug exclusion — name the test for
it); leaves an item that is also unlinked in the list with its remaining reason; stamps
`reviewed_at`; returns the count.

**Condition repair tool (frontend, 3):** picking `LP+` sends `condition: "LP"` **and**
`condition_modifier: "+"` — *not* a combined `"LP+"`; the control lists every
`CONDITION_OPTIONS` value; the row's condition updates in place without a full refetch.

**Frontend (5):** a row renders the chips from `triage_reasons` and **not** from a local
recompute (assert by returning a `triage_reasons` the local rules would not produce); a
machine key renders its human label; selecting a reason sends `triage_reason=<key>` and
nothing else; the bulk-clear confirm shows the exact count; the empty state still reads as
success.

Run:

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_triage.py -q --tb=short
npm test --workspace=frontend -- --run "app/(admin)/admin/triage" "lib/__tests__/triage"
```

*(Both commands corrected as executed. The `npx vitest` form fails with "Vitest
failed to find the runner" — progress.md has recorded that since T0, and this is
the fifth task doc to repeat it.)*

## GREEN — done when

The above pass, pre-existing triage tests are still green, `ruff check backend/src` is clean,
`npm run lint --workspace=frontend` is clean, and the diagnostic numbers are recorded in
`progress.md`.

## Manual check

Open Triage. Every visible row must have at least one chip — that is the owner's requirement,
stated as an invariant. Filter by each reason and confirm the count changes.

Filter to **`blank_condition`** and set a real condition on a card you have in hand. Confirm it
stores as the tier plus the modifier, and confirm the **customer-facing** price on `/inventory`
moves accordingly — that is the money this queue is protecting.

Then bulk clear and confirm the `blank_condition` rows **survive** it.

## Do not

- **Do not add a sticker reason.** Owner decision, above.
- **Do not bulk-clear `blank_condition`.** Those cards are priced to customers as NM until
  someone checks them.
- Do not "fix" `needs_triage` — it is correct. The defect is that its answer was recomputed
  elsewhere and that its input data is full of machine flags.
- Do not let the filter silently ignore an unknown key. 422.
- Do not let the list and `/triage/counts` scope differently.
- Do not clear a human's flag in bulk. The `MACHINE_REVIEW_REASONS` membership test is the
  whole safety property.
- **Do not touch the importer.** It will not run again; changing it is dead code with a live
  blast radius.
- Do not send a combined `"LP+"` as `condition`.
- Do not cache `/triage/counts`. A badge that still counts a fixed card is the failure it
  exists to prevent (and if a cache ever lands, it must be invalidated by the bulk clear).

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

**T4 — A search bar on the Triage page**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t4-triage-search.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
