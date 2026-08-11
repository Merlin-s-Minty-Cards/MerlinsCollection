# T2 — Editing a consignor stops forking the row

**RFC:** 0010 §A · **Layer:** backend + frontend · **Depends on:** — · **Blocks:** —
**Owner report:** plan doc item 1

## The report, and the one bug behind all of it

> *"editing one of the consignors in this case harry creates a duplicate harry with whatever
> you edited as different … Also I cant delete the extra name from this menu and when i tried
> to it set the new 85% one to 'Sold'"*

Three symptoms, one root cause plus one mislabelled badge.

## Confirmed root cause — a known pattern this function missed

`put_consignor` (`backend/src/merlins_collection/services/dynamodb.py:1363-1370`):

```python
self._table.put_item(Item={
    "PK": "CONSIGNORLIST",
    "SK": self._gen_sk(f"CONSIGNOR#{consignor.consignor_id}"),
    "entity": "consignor", **self._gen(), **body,
})
```

`_gen_sk` (`dynamodb.py:398-410`) suffixes the SK with the import generation. So a consignor
written by `import_consignments` lives at `CONSIGNOR#<id>#<gen>`, while an admin edit runs
with **no generation** and writes `CONSIGNOR#<id>` — a *different sort key in the same
partition*. The row does not update; a second one appears.

**`put_show` documents this exact bug and was fixed for it in RFC 0008 T7**
(`dynamodb.py:1232-1263`): *"every show the spreadsheet import wrote keeps its `#<gen>` suffix
after `finalize_import` commits, while an admin edit runs with no generation set. Without the
sweep below either edit forks the show into two rows, so the list shows it twice and archiving
flips only one of them."* Same partition shape, same admin edit path, no sweep.

**The consignor id is NOT the fork axis.** `import_consignments` assigns
`deterministic_id("Consignor", {"name": person})` (`services/spreadsheet_import.py:756`), so
re-importing Harry re-uses Harry's id. Only the generation moves.

**The frontend is not at fault.** It calls `PATCH` correctly
(`frontend/app/(admin)/admin/cosigners/page.tsx:180`). "It POSTs instead of PATCHing" is the
obvious wrong guess — check the sort keys, not the verb.

### Why delete appears to do nothing

`DELETE /admin/cosigners/{id}` is a **soft** delete (`routers/admin/cosigners.py:94-108`): it
sets `active=False` and writes the row back through `put_consignor`, which lands on the
*current-generation* key. The import-generation row is never touched and stays in the list.
`repo.delete_consignor` (`dynamodb.py:1384-1391`) does a real delete but **no route calls it**.

### Why the 85% one said "Sold"

Two causes stacked. The soft delete hit the row the admin's own edit had created — the
current-gen one, i.e. the 85% copy — and
`StatusBadge status={item.active ? 'available' : 'sold'}` (`cosigners/page.tsx:317`, again at
`:459`) renders a deactivated **person** using the inventory-status vocabulary.

### And which Harry the API answers about is arbitrary

`get_consignor` and `delete_consignor` both linear-scan `CONSIGNORLIST` and act on the
**first** match in partition order (`dynamodb.py:1376-1391`).

## Files

- **Modify:** `backend/src/merlins_collection/services/dynamodb.py` — `put_consignor` sweep
- **Modify:** `backend/src/merlins_collection/models/business.py` — `Consignor.archived`
- **Modify:** `backend/src/merlins_collection/routers/admin/cosigners.py` — name guard,
  archive/unarchive, `include_archived` on the list
- **Create:** `backend/scripts/reconcile_consignors.py` — one-time fork reconcile
- **Modify:** `frontend/app/(admin)/admin/cosigners/page.tsx` — badge vocabulary,
  "View archived" toggle, unarchive action, 409 messaging
- **Tests:** `backend/tests/test_dynamodb.py`, `backend/tests/test_cosigners.py`,
  `frontend/app/(admin)/admin/cosigners/__tests__/page.test.tsx`

## Design

### 1. `put_consignor` sweeps superseded rows

Mirror `put_show` exactly, including both of its load-bearing rules:

- **Write FIRST, then delete.** A crash in between leaves a visible duplicate the next write
  cleans up, rather than deleting the only copy of the consignor.
- **Skip the sweep mid-import** (`if self._import_gen: return`). Coexisting generations are
  load-then-swap's whole point — `finalize_import` needs the prior generation to survive until
  commit/rollback is decided (`_gen_sk`'s docstring, BLOCKING-1b).

Do **not** remove `_gen_sk` from `put_consignor` to "simplify" this. That trades a visible
duplicate for an unrecoverable import.

### 2. Duplicate-name guard — 409

On `POST` and `PATCH`, reject a name that case-insensitively (and whitespace-insensitively)
matches **another** consignor. Scoped to *another* so renaming Harry to "Harry", or a PATCH
that does not touch the name, is not an error. Detail text names the colliding consignor so
the admin can go find it. The owner asked for this explicitly.

### 3. Delete is an ARCHIVE, and archived consignors are hidden by default

**Owner decision, 2026-08-10, refining the RFC:** *"If a cosignor is deleted, then it is
okay to archive them, but those cosignors should be hidden by default, and their value
should be displayed as archived instead of sold. Maybe add a view archived button."*

**There is no hard delete, and the earlier plan's `purge` route is dropped.** Once the
sweep in change 1 lands there is no orphan row to purge — the fork was the only thing that
made a destructive delete look necessary.

> ### `/admin/shows` is the reference implementation. Copy it; do not reinvent it.
>
> Owner rule, 2026-08-10: *"if there are other things that get archived, they should be the
> same… Archived entities are hidden by default but can be viewed in case they need to be
> pulled back or referenced."* The six-part contract is now in **CLAUDE.md** ("ARCHIVING IS ONE
> PATTERN"). Shows already has every part of it:
>
> | part | where |
> |---|---|
> | `include_archived` on the list call | `shows/page.tsx:70` |
> | "Show archived" checkbox | `shows/page.tsx:264-274` |
> | `Archived` badge on the row | `shows/page.tsx:183` |
> | Archive **or** Unarchive per row | `shows/page.tsx:225` |
> | confirm copy that says what is preserved | `shows/page.tsx:416` |
> | a boolean `archived` on the model | `models/business.py` (`Show.archived`) |
>
> Read that page before writing this one. Divergence here costs a bug per entity.

| Action | Route | Semantics |
|---|---|---|
| Archive | `DELETE /admin/cosigners/{id}` | sets `archived=True`; history preserved; **hidden from the list by default** |
| Unarchive | `POST /admin/cosigners/{id}/unarchive` | restores it |
| list | `GET /admin/cosigners?include_archived=true` | archived rows only appear when asked for |

`repo.delete_consignor` (`dynamodb.py:1384-1391`) stays **uncalled**, as it is today.
Archiving that cannot be undone is just a slower delete — the phrasing `unarchive_show`
already uses (`routers/admin/analytics.py:244-245`).

**No 409 in-use guard**, and that is deliberate for the same reason shows have none: a
consignor with real consignment history archives like any other, and nothing dangles because
nothing is destroyed.

### 4. `Consignor.archived`, migrated on read from `active`

`Consignor.active` (`models/business.py:141`) already means this, but it is read **almost
nowhere** — only written at create (`cosigners.py:41`) and by the soft delete, and rendered
by the two `StatusBadge` calls. No filter, no business logic depends on it.

So: **add `archived: bool = False` and stop writing `active`**, with a
`model_validator(mode="before")` that reads a legacy `active: False` as `archived: True`.

Why not just keep `active` and relabel it? Because `Show.archived` is the established name
for exactly this concept and CLAUDE.md documents it; a second field meaning the same thing
under a different name is how the next reader introduces a bug. Why not drop `active`
outright with no mapping? **Because the owner has already soft-deleted a Harry** — there is
at least one production row carrying `active: False` that must render as archived, so the
mapping is not hypothetical.

Keep `active` accepted on input (ignored, or mapped) so nothing 422s on an old payload.

### 5. Status vocabulary and the archived view

`Active` / **`Archived`**, never `AVAILABLE` / `SOLD`. Either a small dedicated badge or
`StatusBadge` with explicit label props — do not keep mapping a person onto card statuses.

Frontend:

- the list shows only unarchived consignors by default;
- a **"View archived"** toggle (button or checkbox) sends `include_archived=true`; while it
  is on, archived rows are visibly distinguished (dimmed + the `Archived` badge) rather than
  mixed in silently;
- an archived consignor offers **Unarchive**, not Archive;
- the trash icon's `ConfirmDialog` says *archive*, not delete, and says the history is kept.
  The current copy already says "Their linked items will remain in inventory"
  (`cosigners/page.tsx:725`) — make the title match.

### 5. One-time reconcile script

The sweep fixes the cause; it does not merge the two Harrys that exist in production today.

`backend/scripts/reconcile_consignors.py`, following `backfill_catalog_sets.py`'s shape:
**dry-run by default**, `--execute` to write, requires `--confirm-table`. Groups
`CONSIGNORLIST` rows by `consignor_id`, keeps the **highest-generation** row (the most
recently written), deletes the rest, and prints every action. Report the count in
`progress.md` when the owner runs it.

Remember: **every script here needs the venv interpreter spelled out** — these files have no
shebang (CLAUDE.md Ops).

## RED — write these first, show the failing output, wait for confirmation

**`put_consignor` (backend, 4):**
1. **a consignor written mid-import and then edited by an admin yields exactly ONE row** —
   the owner's bug;
2. the surviving row carries the edited values;
3. mid-import, two generations of the same consignor **coexist** (the sweep is skipped);
4. `list_consignors` returns one entry per `consignor_id` after an edit.

**Name guard (backend, 4):** `POST` with an existing name → 409; `POST` with a
different-case existing name → 409; `PATCH` renaming onto another consignor → 409; `PATCH`
that does not change the name → 200. *(An archived consignor still counts as a collision —
otherwise two live rows appear the moment it is unarchived. Assert that.)*

**Archive (backend, 6):**
1. `DELETE` sets `archived=True` and the row **survives** — nothing is destroyed;
2. `GET /admin/cosigners` **omits** it by default;
3. `GET /admin/cosigners?include_archived=true` includes it;
4. `POST /{id}/unarchive` restores it and it reappears in the default list;
5. **a stored row with legacy `active: False` and no `archived` validates as `archived=True`**
   — the production-data gate, since the owner has already soft-deleted one;
6. archiving a consignor with linked inventory **succeeds** (no in-use guard, by design).

**Frontend (4):** an archived consignor renders **"Archived"**, not "Sold"; archived rows are
hidden until "View archived" is on; an archived row offers **Unarchive**; a 409 on save
surfaces the duplicate-name message rather than the generic `alert`.

Run:

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/test_dynamodb.py backend/tests/test_cosigners.py -q --tb=short
cd frontend && npx vitest run "app/(admin)/admin/cosigners" --reporter=verbose
```

Note: anything creating a table must depend on `_clean_aws` **explicitly** — nothing else
drops a table now that the moto mock outlives the test (CLAUDE.md).

## GREEN — done when

The above pass, the pre-existing `test_cosigners.py` and `test_dynamodb.py` suites are still
green, `ruff check backend/src` is clean and `npm run lint --workspace=frontend` is clean.

## Manual check

Edit a consignor the import created — confirm **one** row, with the edited values. Try to
create a second "Harry" and confirm the 409 message reads usefully. Archive one and confirm it
vanishes from the list; turn on **View archived** and confirm it appears marked **Archived**;
unarchive it and confirm it returns.

Then check the Harry the owner already soft-deleted: it must render as **Archived**, not as
"Sold" and not as active.

## Do not

- Do not remove `_gen_sk` from `put_consignor`.
- Do not sweep mid-import.
- Do not delete before writing.
- **Do not add a hard delete.** Archive is the semantics the owner chose, matching Shows.
- Do not add a 409 in-use guard on archive. Shows deliberately have none, for the same reason.
- Do not leave `active` and `archived` both live as writable fields.
- Do not show archived consignors by default.
- Do not dedupe on read in `list_consignors` instead of sweeping on write. Every other reader
  (`get_consignor`, `delete_consignor`, the analytics join) would need the same dedupe or
  would disagree with the list.
- Do not fix `put_payout` / `put_debt`, which share the shape. Filed in
  [`follow-ups.md`](follow-ups.md) — no UI can trigger them yet.

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

**T3 — Triage: the server says why, one filter narrows, the queue can reach zero**

End your reply with exactly this, in a copyable block:

```
Read docs/plans/rfc-0010/progress.md and docs/plans/rfc-0010/t3-triage-reasons-and-filter.md.

Execute that task only, following the RED gate in the doc: write the failing
tests first, show me the failing output, and wait for my confirmation before
implementing. Do not start any other task.

When it is done: update progress.md and follow-ups.md, commit the work, and end
your reply with a ready-to-paste prompt for the next task in the chain.
```
