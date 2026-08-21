# T1 — Slab fields, the cert pointer row, and duplicate detection

**RFC:** 0009 §6 · **Layer:** backend · **Depends on:** nothing ·
**Blocks:** T2, T3

## The gap

`GradedInventoryItem` (`models/inventory.py:283-291`) has `company`, `grade` and
`cert_number` but nothing recording that PSA actually *verified* the cert, and no
way to answer "do I already own this slab?" without scanning the table.

## Files

- **Modify:** `backend/src/merlins_collection/models/inventory.py` — add four fields
  to `GradedInventoryItem` (~line 283), add `cert_lookup_failed` to
  `MACHINE_REVIEW_REASONS` (line 169-174)
- **Modify:** `backend/src/merlins_collection/services/dynamodb.py` — cert pointer
  write/read, near the existing item writer
- **Create:** `backend/src/merlins_collection/routers/admin/slabs.py`
- **Modify:** `backend/src/merlins_collection/routers/admin/__init__.py` — register
  the router
- **Test:** `backend/tests/models/test_inventory.py` (extend),
  `backend/tests/services/test_dynamodb.py` (extend),
  `backend/tests/routers/admin/test_slabs.py` (create)

## Model changes

Four **optional** fields on `GradedInventoryItem`. Optional is not a style choice —
every existing graded row in the live table lacks them and must keep validating.

| Field | Type | Notes |
|---|---|---|
| `grade_label` | `str \| None = None` | PSA's own wording, e.g. `"GEM MT 10"`. Bounded 50 chars |
| `cert_verified_at` | `datetime \| None = None` | `None` means never verified by PSA |
| `cert_image_url` | `str \| None = None` | **Must validate the scheme** — see below |
| `price_source_id` | `str \| None = None` | Pricing provider's product id. Bounded 100 chars |

**No `population` field.** PSA's public API always returns `null` for it (RFC §5.1).
If you feel the urge to add one, re-read that section.

**`cert_image_url` scheme validation is required, not optional.** It is
provider-supplied and rendered in the admin UI. Accept `http`/`https` only. The
codebase already carries a finding that `tcg_url` accepts a `javascript:` URI; do
not add a second instance of the same hole. Fix the new field only — `tcg_url` is
out of scope and already in the follow-up ledger.

## The cert pointer row

**Never scan.** CLAUDE.md's Ops section records what a full-table scan on a request
path already cost this project once.

Follow the existing single-table conventions in `services/dynamodb.py` (read the
entity table in its module docstring, ~line 13, before writing):

- `PK = f"CERT#{company}#{cert_number}"`, `SK = "POINTER"`, `entity = "cert_pointer"`
- Attributes: `item_id`, `company`, `cert_number`
- Written by `put_inventory_item` whenever `kind == "graded"` **and** `cert_number`
  is non-empty
- New repo method: `get_item_id_by_cert(company: str, cert_number: str) -> str | None`

**Watch-fors:**

- A graded item whose cert is **edited** leaves the old pointer behind, pointing at
  an item that no longer claims that cert. Either sweep the old pointer on update
  (mirror the `put_show` superseded-row sweep at
  `services/dynamodb.py`) or have the reader verify the item still has that cert
  before trusting the pointer. **Pick one and write a test for it** — a stale
  pointer produces a false "duplicate" on a cert the owner legitimately re-enters.
- Two items can legitimately share a cert over time: you sell a slab and buy it back
  later. The pointer holds the **most recent** item id; duplicate detection warns,
  it does not block.

## Endpoint

New router with prefix `/slabs`, registered on `admin_router` in
`routers/admin/__init__.py` alongside the others (line 31-43).

**Do not add an auth dependency to your router.** `admin_router` already carries
`dependencies=[Depends(require_admin)]` at line 25-29, so every included router
inherits admin gating. Declare it on `/slabs` and you get it applied twice. Follow
`admin/locations.py`, which declares only `APIRouter(prefix="/locations", tags=[...])`.

| Method | Route | Behavior |
|---|---|---|
| `GET` | `/admin/slabs/certs/{cert_number}?company=PSA` | `200` with `{"owned": false}`, or `{"owned": true, "item_id": ..., "status": ..., "name": ...}` |

`company` defaults to `PSA`. Return `200` in both cases — "not owned" is a normal
answer, not a 404.

## RED — write these first, confirm they fail, then STOP and show the owner

Narrow selection to run while working:

```bash
./.venv/Scripts/python.exe -m pytest \
  backend/tests/routers/admin/test_slabs.py \
  backend/tests/models/test_inventory.py \
  backend/tests/services/test_dynamodb.py -q --tb=short
```

Tests to write:

**Model**

1. A `GradedInventoryItem` built from a dict with **none** of the four new fields
   validates, and all four are `None`. (This is the live-data compatibility test —
   without it a deploy breaks every existing slab.)
2. All four round-trip when supplied.
3. `cert_image_url = "javascript:alert(1)"` raises a validation error.
4. `cert_image_url = "https://images.psacard.com/x.jpg"` is accepted.
5. `grade_label` over 50 chars is rejected; `price_source_id` over 100 is rejected.
6. `"cert_lookup_failed" in MACHINE_REVIEW_REASONS`.

**Repo**

7. Saving a graded item with a cert writes a pointer row; `get_item_id_by_cert`
   returns that `item_id`.
8. `get_item_id_by_cert` returns `None` for an unknown cert.
9. Saving a **raw** item writes no pointer row.
10. Saving a graded item with `cert_number=""` writes no pointer row.
11. Whichever stale-pointer strategy you chose: change an item's cert, then assert
    the old cert no longer resolves to it.

**Endpoint**

12. Unknown cert → `200`, `{"owned": false}`.
13. Known cert → `200`, `owned` true, correct `item_id`.
14. Unauthenticated → whatever the sibling admin routers return (match, don't invent).

Any test that creates a table must depend on `_clean_aws` **explicitly** — the moto
mock now outlives the test, so a second `create_table` with the same name raises
`ResourceInUseException` (CLAUDE.md).

## GREEN

Only after the owner confirms the tests fail. Minimal implementation, then re-run
the same selection.

## Commit

```bash
git add backend/src/merlins_collection/models/inventory.py \
        backend/src/merlins_collection/services/dynamodb.py \
        backend/src/merlins_collection/routers/admin/slabs.py \
        backend/src/merlins_collection/routers/admin/__init__.py \
        backend/tests/
git commit -m "feat(slabs): cert verification fields and O(1) duplicate detection"
```

Update [`progress.md`](progress.md): T1 → `DONE` + sha. Note in its Notes cell which
stale-pointer strategy you chose — T4 surfaces the duplicate warning and needs to
know how much to trust it.

## Definition of done — all four, every time

This task is not finished until **all four** are true. The fourth is what keeps the
chain moving: a task that stops at "tests pass" strands the next conversation.

1. **The narrow test selection named above passes.** Not the full suite — that runs
   once, at T-FINAL.
2. **The work is committed**, using the commit command above.
3. **[`progress.md`](progress.md) is updated** — status, commit sha, and anything a
   later task needs in the Notes cell. Out-of-scope findings go to
   [`follow-ups.md`](follow-ups.md), not here.
4. **Your final message ends with a copy-pasteable prompt for a FRESH conversation
   to execute the NEXT task.** It must be self-contained, and it must contain:
   - which files to read first (always `progress.md`, plus that task's doc);
   - the task id, and "execute that task only";
   - the RED gate — write the failing tests, show the owner the failing output,
     **wait for confirmation**, and only then implement (CLAUDE.md, binding);
   - the constraints that actually bite for that task (`./.venv/Scripts/python.exe`
     never bare `python`; do not run the full suite; any landmine this task
     uncovered);
   - **this same four-part definition of done**, with the task numbers advanced.

The next task order is in [`README.md`](README.md) and [`progress.md`](progress.md).

**Nothing carries between conversations except what you commit and what that prompt
says.** Write it for someone with no memory of this one.
