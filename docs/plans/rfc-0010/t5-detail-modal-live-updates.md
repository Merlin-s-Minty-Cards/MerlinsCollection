# T5 — An edit in the detail modal shows up immediately, and the list stops jumping

**RFC:** 0010 §C · **Layer:** frontend · **Depends on:** — · **Blocks:** T6 (same file)
**Owner report:** plan doc item 3

## The report

> *"when you click on a card and it pulls up the image with editables, once you click and edit
> a label on a card, it doesn't update immediately instead, you have to reload or click out
> which often resets you to the top of the menu"*

Both halves of that sentence are one bug and one consequence.

## Confirmed root cause

`CardDetailModal.saveEdit` (`frontend/components/admin/shared/CardDetailModal.tsx:202-205`):

```ts
await api.put(`/inventory/${item.item_id}`, payload)   // ← return value DISCARDED
setEditingField(null)
setEditValue('')
onUpdated?.()
```

`PUT /admin/inventory/{item_id}` returns the **full updated item** — `admin_update_item` ends
in `_serialize_item(...)` (`backend/.../routers/admin/inventory.py:312-...`). The modal throws
it away.

It then renders `item`, which is a **prop**, and every parent passes an object out of its own
*list* state:

| page | line |
|---|---|
| triage | `triage/page.tsx:51, 286-290` |
| inventory | `inventory/page.tsx` (`detailItem` state) |
| outgoing (Prep Queue) | `outgoing/page.tsx` |
| sell | `sell/page.tsx` |
| show-prep | `show-prep/page.tsx` |
| vault | `vault/page.tsx` |

`onUpdated` triggers a whole-list refetch, which replaces the array but **not** the
`detailItem` object the modal is rendering. So the edited field keeps its old value until the
modal is closed and reopened — and the refetch re-mounts the table, which is the "resets you to
the top" half.

The `useEffect` at line 149-157 keys on `[item?.item_id, item?.needs_review]`, so it does not
re-sync on any other field change either.

## Files

- **Modify:** `frontend/components/admin/shared/CardDetailModal.tsx`
- **Modify:** the six pages above
- **Tests:** `frontend/components/admin/shared/__tests__/CardDetailModal.test.tsx`, plus the
  page tests that already exercise the modal (`outgoing`, `inventory`)

## Design — two changes, and the second one fixes the scroll reset for free

### 1. The modal owns the item it displays

```ts
const [current, setCurrent] = useState(item)
useEffect(() => { setCurrent(item) }, [item?.item_id])   // re-seed only on a NEW item
```

Render `current` everywhere the component currently reads `item`. On a successful save,
replace it with **the server's own answer**:

```ts
const updated = await api.put<Record<string, unknown>>(`/inventory/${item.item_id}`, payload)
setCurrent(updated)
onUpdated?.(updated)
```

Taking the response rather than optimistically merging `payload` matters: the server
normalises (`_split_combined_condition`, the blank-to-`None` validators, the server-stamped
`reviewed_at`), so a local merge would display a value the database does not hold. It also
means the modal can never claim a save that did not land.

Apply the same treatment to `writeTriage` (line 213-232), which has the identical shape.

Keep `flagged` derived from `current.needs_review` rather than kept as separate state, or the
two drift.

### 2. `onUpdated` hands the updated item to the parent

```ts
onUpdated?: (updated?: Record<string, unknown>) => void
```

**Optional parameter, deliberately** — a parent that ignores it keeps today's refetch
behaviour and cannot break. Then each of the six pages patches the one row:

```ts
onUpdated={(updated) => {
  if (!updated) { fetchItems(); return }              // fall back to the old behaviour
  setItems((rows) => rows.map((r) =>
    r.item_id === updated.item_id ? { ...r, ...updated } : r))
}}
```

No refetch, so the table does not re-mount and scroll position and list order survive. That is
the "resets you to the top" fix, and it costs a request per edit less than today.

**Page-specific rules, do not flatten them:**

- **Triage** must still *remove* a row once its problem is fixed — the page's `dropRow` /
  `reasonsFor` logic (`triage/page.tsx:86-106`) exists for that. After T3 the row carries
  server-computed `triage_reasons`, so the correct test is on the **updated item's**
  `triage_reasons` being empty. Patch, then drop if empty.
- **Prep Queue** removes a row when a sticker price is set — its documented
  "Priced → removed" behaviour. Same shape: patch, then drop if `sticker_price` is non-null.
- **Sell / Show Prep** may hold the item in a staged selection as well as a list; patch both
  or the staged copy goes stale, which would be this same bug one level down.

## RED — write these first, show the failing output, wait for confirmation

**`CardDetailModal` (5):**
1. **after saving a field, the modal renders the value from the PUT response** — the owner's
   bug. Have the mock return a value *different* from what was typed, and assert the response's
   value is shown, which proves it is not an optimistic echo;
2. `onUpdated` is called **with** the updated item;
3. a failed PUT leaves the displayed value unchanged and shows the error;
4. re-opening on a different item re-seeds from the new prop;
5. the triage write path (`Send to Triage`) also updates the displayed state from its response.

**Pages (4, one per behaviour that must not regress):**
6. **an edit does NOT trigger a list refetch** — assert the search endpoint is called once, on
   mount, and not again after the save. This is the scroll-reset fix expressed as a test, since
   scroll position itself is not observable in jsdom;
7. the patched row shows the new value in the list;
8. **Triage:** a row whose `triage_reasons` comes back empty is removed;
9. **Prep Queue:** a row that gains a `sticker_price` is removed.

```bash
cd frontend && npx vitest run components/admin/shared/__tests__/CardDetailModal "app/(admin)/admin/triage" "app/(admin)/admin/outgoing" "app/(admin)/admin/inventory" --reporter=verbose
```

## GREEN — done when

The above pass, every pre-existing test in those files still passes, and
`npm run lint --workspace=frontend` is clean.

**`next build` matters here.** `onUpdated`'s signature changes across six call sites and vitest
does not typecheck — that is exactly the class of error that reached production in RFC 0009.
Run `npm run build --workspace=frontend` before calling this done, even though T-FINAL will run
it again.

## Manual check

On Inventory, scroll well down the list, open a card, edit its location, and confirm: the new
value appears at once, and closing the modal leaves you where you were rather than at the top.

## Do not

- Do not optimistically merge the payload instead of using the response. The server normalises.
- Do not make `onUpdated`'s parameter required.
- Do not remove the refetch fallback — a parent that passes no handler must still work.
- Do not flatten Triage's and Prep Queue's row-removal rules into a generic "always patch".
- Do not re-seed `current` on every prop change; keying on `item_id` is what stops a stale
  parent prop from overwriting the fresh server value.

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

**T6 — The detail modal stays usable when you zoom**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t6-detail-modal-layout.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
