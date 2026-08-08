# T3 — The buy session learns to create graded items

> # ⚠️ SUPERSEDED 2026-08-08 — two instructions here are now WRONG
>
> **Build this instead:**
> [`docs/superpowers/plans/2026-08-08-slab-manual-entry.md`](../../superpowers/plans/2026-08-08-slab-manual-entry.md)
> — Tasks 1–2, which carry the corrected versions with full test code.
>
> The two errors, both of which will cost you a cycle:
>
> 1. **"Add a discriminator plus the slab fields to `BuySessionItem`" — that
>    validates nothing.** `BuySessionItem` (`purchases.py:56`) is **dead code**,
>    referenced nowhere; `add_buy_item` takes `body: dict[str, Any]` and hand-builds
>    the item. Validation belongs in `add_buy_item`.
> 2. **"`cert_verified_at is None` → `cert_lookup_failed`" is REVERSED.** With
>    manual entry now the primary path, that rule would flag *every* slab and turn
>    Triage into noise. Flag only on a missing `card_id`, which
>    `_review_reason_for_buy` already does as `no_catalog_link`. **Do not add the
>    rule.**
>
> Everything else below — the `confirm_buy_session` gap, the float landmine, the
> raw-regression requirement — is still accurate and still binding.

**RFC:** 0009 §4 · **Layer:** backend · **Depends on:** T1 · **Blocks:** T4

## The gap — the single real blocker in this RFC

`confirm_buy_session` (`routers/admin/purchases.py:213-294`) builds every item as:

```python
item_data = {
    "kind": "raw",          # line 243 — hardcoded
    ...
}
...
txn = Transaction(
    category=ItemCategory.RAW,   # line 270 — hardcoded
    ...
)
```

**No code path in this application can currently create a graded inventory item.**

We extend this rather than writing a parallel slab-intake router, because this
function is also where purchase `Transaction`s, timeline events, show attribution
and cost basis are produced. A parallel router would duplicate all of it and drift.

## Files

- **Modify:** `backend/src/merlins_collection/routers/admin/purchases.py` —
  `BuySessionItem` (line 56-68), `confirm_buy_session` (line 213-294)
- **Test:** `backend/tests/routers/admin/test_purchases.py` (extend)

## `BuySessionItem` changes

Add a discriminator plus the slab fields. All new fields optional so **every
existing caller keeps working unchanged** — the Buy page posts today's shape and
must not break.

```python
kind: Literal["raw", "graded"] = "raw"
company: str | None = None
grade: Decimal | None = None
cert_number: str | None = None
grade_label: str | None = None
cert_verified_at: datetime | None = None
cert_image_url: str | None = None
price_source_id: str | None = None
```

`condition` / `condition_modifier` / `finish` stay as they are — they are meaningless
for a slab and simply go unused. **Do not** make them optional; that would change the
raw contract for no benefit.

**Validation:** when `kind == "graded"`, `company`, `grade` and `cert_number` are
required. Enforce this at **add-item time** (`POST /{buy_id}/items`), not only at
confirm — a session that accepts a bad item and explodes on commit loses the whole
staged batch, which is exactly the failure the batch design exists to avoid.

## `confirm_buy_session` changes

Branch the item construction. Everything else in the loop — `buy_price`, the
`Transaction`, the timeline event, `show_id`, `txn_date` — stays identical.

```python
if buy_item.get("kind") == "graded":
    item_data = {
        "kind": "graded",
        "item_id": new_item_id,
        "card_id": buy_item.get("card_id"),
        "status": "available",
        "company": buy_item["company"],
        "grade": str(buy_item["grade"]),
        "cert_number": buy_item["cert_number"],
        "grade_label": buy_item.get("grade_label"),
        "cert_verified_at": buy_item.get("cert_verified_at"),
        "cert_image_url": buy_item.get("cert_image_url"),
        "price_source_id": buy_item.get("price_source_id"),
        "language": buy_item.get("language", "EN"),
        "location": buy_item.get("location", "toploader"),
        "cost_basis": str(buy_price),
        "market_value_at_purchase": buy_item.get("market_value"),
        "current_market_value": buy_item.get("market_value"),
        "acquired_at": txn_date.isoformat(),
        "acquired_show_id": show_id,
        "display_name": buy_item.get("name"),
        "needs_review": ...,
        "review_reason": ...,
    }
    category = ItemCategory.GRADED
else:
    ...existing raw path, unchanged...
    category = ItemCategory.RAW
```

`ItemCategory.GRADED` already exists (`models/business.py:30`).

**Review flagging for slabs.** `_review_reason_for_buy` (line 28) encodes the raw
rules. A slab has its own:

- PSA never verified it (`cert_verified_at is None`) → `cert_lookup_failed`
  (added to `MACHINE_REVIEW_REASONS` in T1)
- No `card_id` → `no_catalog_link`, as today. It will then also surface in Triage's
  derived `missing_card_id` chip — that is correct, not a bug; items routinely
  qualify under several reasons at once.

## The float landmine — read this before writing tests

CLAUDE.md Ops, verbatim in spirit: **never write a bare `float` to DynamoDB.** The
buy session persists **raw request JSON**, so `buy_price` arrives as a float when the
frontend sends a JSON number. `POST /admin/sales/{id}/items` 500'd in production for
exactly this. It went unnoticed for months because **every existing test sends prices
as strings.**

So: at least one test in this task must post `"buy_price": 12.50` as a **JSON
number**, and at least one must post `"grade": 9.5` as a number too. If they pass
without touching `_serialize`, good — but prove it rather than assume it.

## RED — write these first, confirm they fail, then STOP

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/routers/admin/test_purchases.py -q --tb=short
```

**Regression — raw must not change**

1. An existing raw-only session confirms exactly as before: same item, same
   `ItemCategory.RAW` transaction, same timeline event.
2. A session item posted **without** a `kind` key defaults to raw.

**Graded**

3. A graded session item confirms into a `GradedInventoryItem` with `company`,
   `grade`, `cert_number` correct and `cost_basis` equal to `buy_price`.
4. Its transaction carries `ItemCategory.GRADED`.
5. A timeline event is written, same shape as raw.
6. `acquired_show_id` is set from the session's `show_id`.
7. `cert_verified_at=None` → `needs_review` true with reason `cert_lookup_failed`.
8. `card_id=None` → `needs_review` true; reason names the missing catalog link.
9. A verified, catalog-matched slab is **not** flagged.
10. T1's cert pointer row exists after confirm — the slab is immediately
    duplicate-detectable.

**Mixed and invalid**

11. One raw + one graded item in the same session both confirm correctly, and
    `total_cost` sums both.
12. `kind="graded"` missing `cert_number` → rejected at `POST /{buy_id}/items` with
    a 4xx, and the session still holds its previously-added items.

**Money types**

13. `buy_price` as a JSON **number** (`12.50`) survives add + confirm, and
    `cost_basis` reads back as an exact `Decimal("12.50")` — not `12.499999...`.
14. `grade` as a JSON number (`9.5`) round-trips.

## GREEN

Only after the owner confirms failure. Keep the raw branch byte-identical where you
can — the smaller the diff on the existing path, the easier it is to believe the
regression tests.

## Commit

```bash
git add backend/src/merlins_collection/routers/admin/purchases.py backend/tests/
git commit -m "feat(buy): confirm graded items, unbreaking slab acquisition"
```

Update [`progress.md`](progress.md). Note in the Notes cell whether the float test
(#13) needed any `_serialize` change — T4 posts real money from the browser and the
answer matters.
