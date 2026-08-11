# T7 — Prep Queue sorts and filters by location

**RFC:** 0010 §J · **Layer:** frontend · **Depends on:** — · **Blocks:** —
**Owner report:** plan doc item 6 — *"Prep queue is great but have an option to sort by location
as we often just price glass in certain cases"*

Also the home for the need T3 declined: the owner clarified that Triage is for correctness
issues, not stickers. **Prep Queue is the unstickered-inventory worklist**, so "price everything
in the glass case" belongs here.

## Everything needed already exists on the backend

| capability | where |
|---|---|
| `location` filter | `routers/admin/inventory.py:92` |
| `location_asc` / `location_desc` sort | `_sort_admin_results`, `admin/inventory.py:1031-1078` |
| controlled sorting | `DataTable`'s `sortKey` / `sortDir` / `onSort`, `components/admin/shared/DataTable.tsx:18-35, 64-70` |
| the location list | `useLocations()` — already imported on this page (`outgoing/page.tsx:7, 44`) |

The Prep Queue page wires **none** of it: its `location` column carries no `sortable: true`
(`outgoing/page.tsx:292`) and the page passes no `sortKey`/`onSort` to `DataTable`
(`outgoing/page.tsx:461`). **There is no backend change in this task.**

## The filter is the primary control, not the sort

The owner's stated need — *"we often just price glass in certain cases"* — is a **filter**
("show me only the glass case"), not a sort ("group the glass case together somewhere in a
224-row list"). Ship both, but the filter is what the report is asking for and it should be the
prominent control. Sorting is the cheap extra.

## Files

- **Modify:** `frontend/app/(admin)/admin/outgoing/page.tsx`
- **Tests:** `frontend/app/(admin)/admin/outgoing/__tests__/page.test.tsx`

## Design

**Location filter.** A `<select>` beside the existing controls, options from
`useLocations()` — which returns **`options`**, not `locations`, and yields `{ value, label }`
pairs. Never hardcode a location list (CLAUDE.md). An "All locations" default omits the param.

Use `vault-field` on the select. An admin control without it renders light-green-on-white,
because the admin theme is dark and an unstyled `<select>` inherits the theme's text colour over
the browser's default background (CLAUDE.md, "Never ship an admin control without
`vault-field`").

**Sortable columns.** Add `sortable: true` to the `location` column and hold `sortKey`/`sortDir`
in page state, passing them plus `onSort` to `DataTable`. Send the existing `sort` param as
`${key}_${dir}`. While you are wiring it, make `cost` and `market` sortable too — the backend
supports `cost_basis` and `current_market_value` and a table with exactly one sortable column
reads as broken.

**Both narrow within the queue's existing criterion.** The page fetches
`status=available, missing_sticker=true`; location and sort are additional params on the same
request, not a replacement for it. The header counts (`In queue`, `Est. value`) should reflect
the **filtered** set, and the label should make that obvious — "In queue (Glass)" or similar —
or the owner will read a filtered count as the whole queue.

**Interaction with "Priced → removed".** Pricing an item inline drops it from the queue
immediately (the page's documented behaviour). With a filter active that still holds; do not
refetch on price, which would reset the list — and after T5 the correct move is to patch and
drop the row.

## RED — write these first, show the failing output, wait for confirmation

1. selecting a location sends `location=<value>` on the search request;
2. "All locations" omits the param;
3. the location options come from `useLocations()`, **not** a hardcoded array (assert against a
   mocked hook returning an unusual value like `Vault B`);
4. clicking the Location header sends `sort=location_asc`, and clicking again sends
   `location_desc`;
5. the sort indicator reflects the active column;
6. the `In queue` count and `Est. value` reflect the filtered set;
7. the location `<select>` carries `vault-field`;
8. pricing an item with a filter active still removes just that row and does not refetch.

```bash
cd frontend && npx vitest run "app/(admin)/admin/outgoing" --reporter=verbose
```

## GREEN — done when

The above pass, every pre-existing Prep Queue test passes, and
`npm run lint --workspace=frontend` is clean.

## Manual check

Filter to the glass case and price two cards without leaving the filter. Confirm the count drops
by two, the list does not jump, and the remaining rows are still only glass-case items.

## Do not

- Do not add a backend parameter or sort field. They exist.
- Do not hardcode a location list.
- Do not ship a `<select>` without `vault-field`.
- Do not drop the queue's `status=available, missing_sticker=true` criterion.
- Do not refetch the list when an item is priced.

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

**T16 — A card with no catalog match still gets a price and a sticker**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t16-unmatched-card-valuation.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
