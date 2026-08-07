# T7 — Shows CRUD, with archive instead of delete

**RFC:** 0008 §F1 (issue #5) · **Layer:** full-stack · **Depends on:** nothing

## The gap

`routers/admin/analytics.py` exposes only `GET /admin/shows` (line 153-164) and the
analytics snapshot endpoints. There is **no create/update/delete for a `Show`**.
The only writer today is `services/spreadsheet_import.py:694` (`repo.put_show`), a
one-time import path. No `/admin/shows` frontend page exists.

The data layer is mostly ready: `put_show()` (upsert), `list_shows()`, `get_show()`
(`services/dynamodb.py:1085-1102`). There's no `delete_show()` — and per the owner
decision below, **you don't need one**.

## Owner decision (RFC Q6 — settled)

> **Archive, not delete.** Reasoning: the real use case is "I typed the wrong show
> in and want it gone" — a show with no transactions attached yet.

So:
- Add an `archived: bool = False` field to the `Show` model
  (`models/business.py:80-92`).
- "Delete" in the UI sets `archived = True`. Nothing is ever destroyed, so a
  mistakenly-archived show with real history stays recoverable and analytics
  snapshots never dangle.
- **No 409 in-use guard, no `delete_show()` repo method.** Both were rejected —
  archiving makes the referenced-transaction problem moot.

## Endpoints

Follow the `admin/locations.py` precedent (named in CLAUDE.md as the pattern for
admin-managed lists).

| Method | Route | Notes |
|---|---|---|
| `POST` | `/admin/shows` | body validates against `Show` minus `show_id`; server generates the id (`new_ulid()`); **201** + created show |
| `PUT` | `/admin/shows/{show_id}` | partial update — merge + re-validate, mirroring `admin_update_item` (`admin/inventory.py:267-319`) |
| `POST` | `/admin/shows/{show_id}/archive` | sets `archived = True`; idempotent |
| `POST` | `/admin/shows/{show_id}/unarchive` | sets `archived = False` — archiving must be reversible or it's just a slower delete |

`GET /admin/shows` gains `?include_archived=true`. **Default excludes archived** —
existing callers (the Show Analytics page's Shows tab) must not suddenly start
listing archived shows. Check that tab's call site before changing the default.

`Show` fields today: `show_id, name, date, venue, city, sales_goal, cash_at_start,
inventory_value_at_start, notes` — plus the new `archived`.

## Backend watch-fors

- Existing show rows in DynamoDB have **no** `archived` attribute. The field must
  default to `False` on read, not blow up validation. A Pydantic default handles
  this — confirm with a fixture lacking the key.
- `PUT` must not let a client overwrite `show_id`.
- Reuse the router's existing admin auth; don't invent a new dependency.

## Frontend

New page `frontend/app/(admin)/admin/shows/page.tsx`, added to `navItems` in
`AdminShell.tsx`. Same shape as the existing **Cosigners** CRUD page — read that
first and copy its structure rather than inventing a new layout.

- List + create/edit form + archive button.
- Archive needs a confirm dialog (the page has a `ConfirmDialog` pattern already).
- A "show archived" toggle that flips `include_archived`, with unarchive available
  from there.
- If T4 has already landed, note the sidebar now has one more nav item — that's the
  case T4's independent nav scrolling exists for.

## RED — write these first, confirm they fail, then stop

Backend:
1. `POST /admin/shows` creates and returns 201 with a generated `show_id`.
2. `POST` with a missing required field → 422.
3. `PUT` partial-updates one field, leaves the rest intact.
4. `PUT` cannot change `show_id`.
5. `PUT` on an unknown id → 404.
6. Archive sets `archived = True`; the show is **not** removed from storage.
7. `GET /admin/shows` excludes archived by default.
8. `GET /admin/shows?include_archived=true` includes it.
9. Unarchive restores it to the default listing.
10. A stored show row with no `archived` attribute loads with `archived == False`.
    **The migration-safety test — don't skip it.**
11. Archiving a show referenced by a transaction succeeds (no 409). Encodes the
    owner's decision.
12. All endpoints reject a non-admin caller.

Frontend:
13. Shows page lists shows from the API.
14. Create form posts and refreshes the list.
15. Archive prompts for confirmation before firing.
16. "Show archived" toggle requests `include_archived=true`.

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "show"
cd frontend && npx vitest run shows
ruff check backend/src && npm run lint --workspace=frontend
```

## Done when

- All 16 green; `/admin/shows` reachable from the sidebar; archive round-trips.
- `grep -rn "delete_show" backend/` returns nothing — archive replaced it.
