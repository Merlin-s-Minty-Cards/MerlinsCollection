# T4 — A search bar on the Triage page

**RFC:** 0010 §B.6 · **Layer:** frontend · **Depends on: T3** (same file) · **Blocks:** —
**Owner report:** plan doc item 4 — *"add a search bar to just search by card name in triage
menu"*

## Why this is small

The backend already does all of it. `GET /admin/inventory/search` takes `name`
(`backend/src/merlins_collection/routers/admin/inventory.py:93`) and `_matches_name`
(`admin/inventory.py:1010-1028`) already searches display name, product name, description
**and** notes — so a JP card whose only readable text is in `notes` is findable, which matters
on precisely this page.

There is **no new endpoint and no backend change**. If you find yourself writing Python, stop
and re-read this paragraph.

## Depends on T3 only for file peace

T4 edits the same `params` record T3 restructures (`triage/page.tsx:63-70`). Running it after
T3 avoids a conflict; there is no logical dependency.

## Files

- **Modify:** `frontend/app/(admin)/admin/triage/page.tsx`
- **Tests:** `frontend/app/(admin)/admin/triage/__tests__/page.test.tsx`

## Design

Use the **shared** `SearchInput` (`frontend/components/admin/shared/SearchInput.tsx`) that
every other admin list uses — Cosigners mounts it at `cosigners/page.tsx:416`. Do not
hand-roll an input; the placeholder styling, the clear affordance and the vault theming are
already solved there.

- Sits beside the existing reason `<select>`, in the same control row.
- **Debounced 300ms**, matching the catalog autocomplete convention already in this file
  (`useCatalogSearch`, `triage/page.tsx:312`) — every keystroke is a full `list_inventory`
  read on the backend, so an undebounced input is a real cost.
- Feeds the existing `params` record as `name`, so it **AND-combines** with the reason filter
  for free. Searching within a reason is the useful combination and it needs no extra work.
- Empty/whitespace-only omits the key entirely rather than sending `name=""`.
- The header count (`triage/page.tsx:209`) already reads `items.length`, so it follows the
  filtered result with no change. Make sure the empty state distinguishes "nothing needs
  review" (the success state, `Check` icon) from **"no match for that search"** — rendering
  the success panel for a failed search would tell the admin their queue is clean when it is
  not. This is the one real design decision in the task.

## RED — write these first, show the failing output, wait for confirmation

1. typing a name sends `name=<term>` on the search request;
2. the request is **debounced** — three quick keystrokes produce one call, not three;
3. search **and** a reason filter are sent together;
4. a whitespace-only term omits `name` entirely;
5. **a search with no matches renders "no match", not the "Nothing needs review" success
   panel**;
6. clearing the search restores the unfiltered queue.

```bash
cd frontend && npx vitest run "app/(admin)/admin/triage" --reporter=verbose
```

## GREEN — done when

The above pass, the pre-existing Triage page tests are still green, and
`npm run lint --workspace=frontend` is clean.

## Manual check

Search a card you know is in the queue. Then search one that is not, and confirm the message
does not congratulate you.

## Do not

- Do not add a backend endpoint or parameter.
- Do not skip the debounce.
- Do not render the success state for an empty search result.
- Do not hand-roll the input when `SearchInput` exists.

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

**T5 — An edit in the detail modal shows up immediately, and the list stops jumping**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t5-detail-modal-live-updates.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
