# Task C2: Inventory Filter by Cosigner

**Files:**
- Modify: `backend/src/merlins_collection/routers/admin/inventory.py`
- Test: `backend/tests/routers/admin/test_inventory.py` (or wherever
  `admin_search_inventory` filter tests live — grep for `def test_name_filter`
  or similar to find the right file/class)
- Modify: `frontend/lib/admin-inventory-columns.tsx`
- Modify: `frontend/app/(admin)/admin/inventory/page.tsx`
- Test: `frontend/lib/__tests__/admin-inventory-columns.test.ts` (registry
  totality test — confirm this filter doesn't break it)
- Test: `frontend/app/(admin)/admin/inventory/__tests__/page.test.tsx`

**Interfaces:**
- Consumes: `useCosigners()` from `frontend/lib/use-cosigners.ts` (Task C1)
  — this task cannot start until C1's hook exists (the component task,
  `CosignorPicker`, is not needed here — this is a plain `select`-kind
  filter using `optionSource`, same mechanism `location`/`shows` already
  use, not the combobox component).
- Produces: nothing consumed by later tasks.

## Context

`item.consignment.consignor_id` is a nested field the generic `FieldFilter`
mechanism (`inventory_filters.py`, single-level `getattr`) cannot reach —
per RFC 0012 this needs a hand-written filter, following the existing
`name`/`condition` pattern (module docstring lines 17-26). `consignment`
itself is already `FieldKind.PRESENCE` in `FILTERABLE_FIELDS`
(`inventory_filters.py:107`) via the existing `ownership` filter (has/lacks
a cosigner) — this task adds a second, narrower filter: *which* cosigner.
Filter only, no sort, no new inventory column (explicit RFC non-goal) — it
follows the same `columnKey: null` pattern already used for the catalog
filters (`set_id`/`card_number`/`artist`), which are filter-only and live
behind "show all filters".

- [ ] **Step 1: Write the failing backend test**

Find the test file/class covering `GET /admin/inventory/search`'s named
filters (grep `-rn "def test.*name.*filter\|_item_matches_name" backend/tests`
to locate it — likely `backend/tests/routers/admin/test_inventory.py`). Add:

```python
    def test_consignor_id_filter(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="owned-1"))
        consigned = _raw(item_id="consigned-1", card_id="sv1-9")
        consigned = consigned.model_copy(update={
            "consignment": ConsignmentTerms(
                consignor_id="cos-1", split_percent=Decimal("0.5"),
            ),
        })
        repo.put_inventory_item(consigned)

        resp = client.get("/admin/inventory/search", params={"consignor_id": "cos-1"},
                          headers=_auth(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["item_id"] == "consigned-1"

    def test_consignor_id_filter_matches_nothing_for_unknown_id_not_a_422(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="owned-1"))

        resp = client.get("/admin/inventory/search", params={"consignor_id": "no-such-cosigner"},
                          headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["items"] == []
```

Check the file's existing imports for `ConsignmentTerms`, `Decimal`, and its
`_raw`/`_auth` helper names — reuse whatever it already imports rather than
re-importing; the exact helper signatures may differ slightly from
`test_trades.py`'s (each router test file has its own local `_raw`).

- [ ] **Step 2: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary"
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_inventory.py -k consignor_id -v
```
Expected: FAIL — `consignor_id` isn't a query param yet, so FastAPI either
ignores it (both tests return all items, first test fails on count) or the
param doesn't exist at all depending on how the test asserts; either way the
first test's `len(items) == 1` assertion fails because filtering never
happened.

- [ ] **Step 3: Add the query param and hand-written filter**

In `backend/src/merlins_collection/routers/admin/inventory.py`, add a new
parameter to `admin_search_inventory`'s signature, alongside the other named
filters (near `location`/`condition`, around line 110-111):

```python
    consignor_id: str | None = Query(None, max_length=64),
```

Then, in the function body, alongside the other named-filter blocks (after
the `if name is not None:` block around line 191-196, following the exact
same shape):

```python
    if consignor_id is not None:
        items = [
            i for i in items
            if i.consignment is not None and i.consignment.consignor_id == consignor_id
        ]
```

No helper function needed — this is a one-line predicate, shorter than
`_item_matches_name`, so it's inlined at the call site rather than
factored into a private `_item_matches_consignor` the way the RFC sketched;
follow whichever the surrounding code's own style favors once you're
looking at the live file (if every other named filter here is a private
`_item_matches_*` function rather than an inline comprehension, match that
instead — check `_item_matches_name`'s definition site for the convention
before choosing).

Note this does NOT touch `FILTERABLE_FIELDS` or the generic `FieldFilter`
mechanism at all — it's a fifth hand-written named parameter, same
category as `name`/`condition`/`min_price`/the catalog filters (CLAUDE.md:
"Four of them stay hand-written because they do more than a field
comparison" — this becomes the fifth, for the same nested-field reason).

- [ ] **Step 4: Run it to verify it passes**

Run:
```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_inventory.py -k consignor_id -v
```
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`
Expected: PASS.

- [ ] **Step 6: Commit the backend half**

```bash
git add backend/src/merlins_collection/routers/admin/inventory.py backend/tests/routers/admin/test_inventory.py
git commit -m "feat(rfc-0012): add consignor_id filter to admin inventory search"
```

- [ ] **Step 7: Write the failing frontend registry test**

`frontend/lib/__tests__/admin-inventory-columns.test.ts` already asserts the
`INVENTORY_FILTERS` registry is TOTAL (every column has an entry) and that
every filter's `kind`/`op` matches the backend's `FILTERABLE_FIELDS`/`OPS_BY_KIND`
tables. A `columnKey: null` filter (like this one) is filter-only and does
NOT need a matching column, so the totality test should already pass once
this entry exists — but add one explicit test proving the new entry is
present and correctly shaped:

```typescript
  it('has a consignor filter that sends consignor_id and sources cosigners', () => {
    const consignorFilter = INVENTORY_FILTERS.find((f) => f.id === 'consignor')
    expect(consignorFilter).toBeDefined()
    expect(consignorFilter?.legacyParam).toBe('consignor_id')
    expect(consignorFilter?.optionSource).toBe('cosigners')
    expect(consignorFilter?.columnKey).toBeNull()
  })
```

- [ ] **Step 8: Run it to verify it fails**

Run:
```bash
cd "c:/Users/ethar/.cursor/projects/MerlinsCollection-Secondary/frontend"
npx vitest run lib/__tests__/admin-inventory-columns.test.ts --reporter=verbose
```
Expected: FAIL — no filter with `id: 'consignor'` exists yet.

- [ ] **Step 9: Add the filter definition and extend `FilterOptionSource`**

In `frontend/lib/admin-inventory-columns.tsx`, change:

```typescript
export type FilterOptionSource = 'locations' | 'shows' | 'sets'
```

to:

```typescript
export type FilterOptionSource = 'locations' | 'shows' | 'sets' | 'cosigners'
```

Add a new entry to `INVENTORY_FILTERS`, in the catalog-filters section
(`columnKey: null`, filter-only, behind "show all filters" — find where
`set_id`/`card_number`/`artist` are defined, around the area the docstring
at lines 519-525 describes, and add alongside them):

```typescript
  {
    id: 'consignor', label: 'Consignor', columnKey: null, kind: 'select',
    legacyParam: 'consignor_id', optionSource: 'cosigners',
  },
```

- [ ] **Step 10: Wire the option source in the inventory page**

In `frontend/app/(admin)/admin/inventory/page.tsx`, find the existing
mapping (around line 254-255):

```typescript
    if (def.optionSource === 'locations') return locationOptions
    if (def.optionSource === 'shows') return showOptions
```

Add a third line:

```typescript
    if (def.optionSource === 'cosigners') return cosignorOptions
```

And add the hook call alongside the existing ones (near line 86-89):

```typescript
  const { options: cosignorOptions } = useCosigners()
```

with the import added at the top of the file alongside the other
`use-*` imports (near line 8-9):

```typescript
import { useCosigners } from '@/lib/use-cosigners'
```

- [ ] **Step 11: Run it to verify it passes**

Run:
```bash
npx vitest run lib/__tests__/admin-inventory-columns.test.ts "app/(admin)/admin/inventory/__tests__/page.test.tsx" --reporter=verbose
```
Expected: PASS.

- [ ] **Step 12: Run the full frontend suite**

Run: `npm test --workspace=frontend`
Expected: PASS.

- [ ] **Step 13: Commit the frontend half**

```bash
git add frontend/lib/admin-inventory-columns.tsx "frontend/app/(admin)/admin/inventory/page.tsx" frontend/lib/__tests__/admin-inventory-columns.test.ts
git commit -m "feat(rfc-0012): add Consignor filter to the inventory filter bar"
```
