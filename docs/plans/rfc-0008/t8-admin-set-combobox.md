# T8 — Admin set filter: type-to-narrow combobox over the whole catalog

**RFC:** 0008 §F4 (issue #9) · **Layer:** full-stack · **Depends on: T10**

> Depends on T10 because both touch the catalog sync mapper. Do T10 first to avoid
> two conversations editing `services/tcgdex.py` and `services/catalog_sync.py`
> against each other.

## The gap

The public `FilterPanel.tsx` already has exactly what the owner asked for:
`SetCombobox` (line 242-339) — a type-to-narrow text input over `facets.sets`. The
admin inventory page instead has a plain `set_name` substring `<input>` against
`_filter_by_catalog` (`admin/inventory.py:885-943`). Not a dropdown at all.

## Owner decision (RFC Q8 — settled, and it changes the design)

> **The whole catalog, not inventory facets** — *"so we can double check if there is
> a set in the catalog we have no cards of."*

This is important: the owner wants to see sets they own **zero** cards from. So
this is **not** a facet over inventory, and reusing `/inventory/facets` (which is
scoped to customer-visible stock) is wrong. So is deriving it from admin inventory.

### The blocker this exposes

**There is no set entity in DynamoDB.** Verified: sets exist only as denormalized
`set_id`/`set_name` fields on catalog card rows, plus the GSI1 `SET#` partition.
Grep confirms no `put_set` / `list_sets` / `catalog_set` anywhere.

So "list every set in the catalog" today means a **full catalog scan** — the exact
11.2-second operation T9 diagnosed as the cause of the dead catalog search. Do not
build this on a scan.

## Build

### 1. A `catalog_set` registry entity

Write one row per set during catalog sync.

- `entity = "catalog_set"`, keyed so all sets sit in one partition and list via a
  single cheap query — **not** a scan. Follow the existing single-table conventions
  in `services/dynamodb.py` (read how `location_config` and the watchlist's
  `GSI1PK = "WATCHLIST#ALL"` do it).
- Fields: `set_id`, `set_name`, `language`, `card_count`, `updated_at`.
- ~400 rows total (177 JA + 218 EN sets). Trivial.
- Written from the set-list response the sync already fetches — **no extra API
  requests**.
- Needs a one-time backfill for the already-seeded catalog. It can be derived from
  existing catalog card rows in a single pass (one scan, run **once**, offline —
  acceptable as a script, unacceptable as a request path).

### 2. `GET /admin/catalog/sets`

Returns every set in the catalog, from the registry. Admin-gated.

Include an owned-card count per set so the owner can immediately spot the zero
ones — that's the stated purpose, and computing it client-side would mean shipping
the whole inventory to the browser. Sort alphabetically by name; include `language`
so EN and JA sets are distinguishable (there are near-duplicate names across the
two).

### 3. Extract `SetCombobox` to a shared component

Currently private to the public `FilterPanel.tsx`. Move it to
`frontend/components/shared/SetCombobox.tsx` and have both consumers import it.

- **The public filter panel must be unchanged in behaviour.** Extracting a working
  component is where you accidentally break the working one; test both call sites.
- The two sources differ in shape (public: `facets.sets` = `{id, name}`; admin:
  registry entries with counts and language). Keep the component's prop contract
  generic over `{id, name}` with optional annotation, rather than forking it.

### 4. Use it on the admin inventory page

Replace the plain `set_name` substring input. The admin filter currently matches on
`set_name` substring via `_filter_by_catalog`; a combobox selects a `set_id`.
Decide deliberately whether the backend filter now takes `set_id` (cleaner) or the
combobox emits the exact `set_name` (smaller change) — **prefer `set_id`**, since
set names are not unique across languages and a substring match on
"Sun & Moon" catches several sets.

## RED — write these first, confirm they fail, then stop

Backend:
1. Catalog sync writes a `catalog_set` row per set. Fails today.
2. `GET /admin/catalog/sets` returns all sets including ones with **zero** owned
   cards, each with an owned count. Fails today. **This is the owner's actual ask.**
3. The endpoint does **not** perform a full catalog scan. Assert on the repo call,
   e.g. a fake repo whose scan method raises if touched. Prevents regressing into
   the T9 bug.
4. Sets are returned with `language`, and an EN/JA name collision yields two
   distinct entries.
5. Non-admin caller rejected.

Frontend:
6. Admin inventory renders a type-to-narrow combobox, not a plain text input.
   Fails today.
7. Typing narrows the list; selecting filters by `set_id`.
8. The **public** `FilterPanel` still renders and filters identically after the
   extraction. Passes today — the regression guard that matters most here.

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "set or catalog"
cd frontend && npx vitest run SetCombobox FilterPanel inventory
ruff check backend/src && npm run lint --workspace=frontend
```

## Done when

- All 8 green; admin set filter is a combobox listing every catalog set with owned
  counts; public filter panel behaviourally unchanged; no scan on the request path.
