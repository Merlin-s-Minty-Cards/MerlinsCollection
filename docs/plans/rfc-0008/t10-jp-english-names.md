# T10 — English display names, admin-authored

**RFC:** 0008 §C (issue #3) · **Layer:** backend + frontend · **Depends on:** nothing
**Supersedes** the RFC's automated `dexId`/`name_en` pipeline — see "Why the RFC's plan was dropped".

> Owner redirected 2026-08-05: *"shift to a more hands on approach for the JP
> cards."* This doc implements that. The **editing UI** lives in T11 (Triage tab);
> T10 is the data model plus the display fix.

## Why the RFC's plan was dropped — measured against live data

The RFC designed a `dexId` → English-species-name sync pipeline: new catalog
fields, a sync-mapper change, a name-map reduction over 23,444 EN rows, a suffix
table, and a paced backfill script. Live table says that is wildly disproportionate:

```
inventory items: 266   →   EN 249 | JP 17
JP items with a card_id: 9
```

The whole pipeline would resolve **at most 9 names**, and at the measured ~69%
coverage, realistically ~6. Not worth a schema change and a backfill script.

**And most of those names are already in the database, in English.** The
sheet-derived `display_name` on your JP items:

| card_id | display_name |
|---|---|
| `ja:M4-084` | Chespin #84 |
| `ja:SM11b-036` | Reshiram & Zekrom GX #36 |
| `ja:M3-086` | Clefairy #86 |
| `ja:M2a-205` | Team Rocke'ts Mimikyu #205 |
| `ja:SV11B-170` | Meloetta ex #170 |

The reason a customer sees Japanese script anyway is one line —
`frontend/lib/inventory.ts:240`:

```ts
return item.card?.name ?? item.display_name ?? item.card_id ?? item.item_id
//            ^^^^^^^^^ JP catalog name wins over the English name already on the item
```

So issue #3 affects at most 9 items, 5 of which already have a usable English name
sitting unused. This is a display-precedence bug plus a small manual-entry gap —
not a translation-pipeline problem.

**Do not build:** `name_en`, `dex_number`, the dexId capture, the species-name map,
the suffix table, or the catalog backfill script. All dropped.

## Design

### Recommended: an override field, not a materialized one

Add **`display_name_override: str | None = None`** to `_ItemBase`
(`models/inventory.py:170-202`). Resolution order becomes:

```
display_name_override  ??  card.name  ??  display_name  ??  card_id  ??  item_id
```

Why an override rather than "materialize a display name onto every card":

- **English cards need no data change at all.** With no override, the rendered name
  *is* the catalog name — which already satisfies "English cards should by default
  have the same name and display name". Zero migration for 249 items.
- **The alternative regresses English tiles.** If instead `display_name` were
  promoted ahead of `card.name`, all 249 EN items would start rendering their
  messy sheet-derived strings ("Magnezone first #68" instead of "Magnezone").
  That's a visible downgrade across the whole store to fix 9 cards.
- **No clobber problem.** An override is admin-owned by construction; nothing in
  the sync or import path writes it, so no "was this edited?" flag is needed and
  no future sync can silently overwrite a typed name.
- **Editing a name still cannot break the TCGdex link** — the owner's stated
  requirement. `card_id` is a separate field and the override never touches it.
  (Re-pointing a *mismatched* `card_id` is a deliberate, separate action — T11.)

The existing `display_name` keeps its current documented meaning (sanitized
name+number fallback materialized at import for unmatched items). Don't repurpose it.

### Backend

- `display_name_override` on `_ItemBase`, defaulting to `None`. Existing rows have
  no such attribute — **it must default cleanly on read**, tested against a fixture
  that lacks the key.
- Add it to `admin_update_item`'s allowed fields
  (`routers/admin/inventory.py:267-319`) so it's writable.
- Add it to `_CUSTOMER_ITEM_FIELDS` (`routers/inventory.py:133-150`). That
  allowlist is deliberately an allowlist — a new field is hidden until named, so
  the customer-facing name will silently not appear unless you add it.
- Trim and treat empty-string as `None`, so clearing the box in the UI actually
  clears the override rather than rendering a blank tile.
- Cap the length (match the existing name-field bound) — it reaches customers.

### Frontend

- `itemTitle()` (`lib/inventory.ts:238-241`) — new precedence above. Update the
  docstring, which currently describes the old order.
- Sealed items still short-circuit on `product_name` — but an override should beat
  that too if set, since the whole point is admin correction. Handle deliberately.
- The **JP badge must still render** (`CardTile.tsx:24-31`, `isJapanese()`).
  A customer seeing "Chespin" must still be able to tell it's a Japanese print —
  that's pricing-relevant and an owner-approved disclosure.

## RED — write these first, confirm they fail, then stop

Backend:
1. `display_name_override` round-trips through `PATCH /admin/inventory/{id}`.
   Fails today.
2. An item fixture with **no** `display_name_override` attribute loads with `None`.
   Migration-safety test.
3. Empty string is stored as `None`, not `""`.
4. The override is present in `/inventory/search` output (allowlist test).
   Fails today — and would be silently missed without this test.
5. Over-length input → 422.

Frontend:
6. `itemTitle()` prefers `display_name_override` over `card.name`. Fails today.
7. With no override, a JP item renders `card.name` (native) — unchanged fallback.
8. With no override, an EN item renders `card.name`, **not** the sheet-derived
   `display_name`. Passes today; the regression guard that protects all 249 EN items.
9. JP badge still renders when an override is displayed. Not optional.
10. Unmatched item (no `card_id`, no override) still falls back to `display_name`.

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "display_name or override or search"
cd frontend && npx vitest run inventory CardTile
ruff check backend/src
```

## Done when

- All 10 green.
- Setting an override on `ja:M4-084` makes `/inventory` render "Chespin" with the
  JP badge intact.
- No `name_en`, no `dex_number`, no backfill script exists.
