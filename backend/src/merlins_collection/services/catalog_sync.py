"""Daily batch job: price snapshots and inventory market-value denormalization.

``run_daily_sync`` is the entry point, driven by ``scripts/daily_sync.py``; the
individual steps are exposed for testing:

- ``snapshot_graded_prices`` — append a daily history point for each owned
  graded slab that has a manual market value.
- ``snapshot_sealed_prices`` — the same for sealed products, whose history hangs
  off the item rather than a catalog card.
- ``refresh_inventory_market_values`` — denormalize the latest market value onto
  each inventory item so list/search reads don't need a second lookup.

Each function takes ``repo`` (an ``InventoryRepository``) and returns a small
summary dict so the job can log what it did.

**No catalog fetching happens here.** The Tier 1 breadth seed is
``scripts/seed_catalog.py``; the Tier 2 depth pass that fetches prices for held
cards is ``refresh_held_prices``, which RFC 0003 §7 specifies with per-card
failure counting, a ``max_consecutive_failures`` abort and a lock-held
``{"skipped": ...}`` return — none of which the old ``sync_catalog`` had. It is
written from scratch in Phase 2 rather than adapted from a seam kept warm for it.
"""

from __future__ import annotations

from datetime import date

from merlins_collection.models.catalog import PricePoint


def snapshot_graded_prices(repo, today: date) -> dict:
    """Append a daily history point for each owned graded slab with a market value.

    Deduplicates by ``(card_id, company, grade)`` so multiples of the same slab
    write only one point per day.
    """
    seen = set()
    written = 0
    for item in repo.list_inventory():
        if item.kind != "graded" or item.card_id is None:
            continue
        key = (item.card_id, item.company, item.grade)
        if key in seen:
            continue
        seen.add(key)
        value = repo.get_graded_market_value(item.card_id, item.company, item.grade)
        if value is None:
            continue
        repo.append_price_points(
            [
                PricePoint(
                    card_id=item.card_id, date=today, source="manual",
                    kind="graded", company=item.company, grade=item.grade, market=value,
                )
            ]
        )
        written += 1
    return {"graded_points_written": written}


def refresh_inventory_market_values(repo) -> int:
    """Write the latest market value onto each inventory item; return the count.

    Raw items take their value from the catalog card's finish price; graded items
    from the manual graded value. Per-card lookups are cached, and an item is
    only rewritten when its value actually changed. Returns how many were updated.
    """
    updated = 0
    catalog_cache: dict = {}
    graded_cache: dict = {}
    for item in repo.list_inventory():
        if item.kind not in ("raw", "graded") or item.card_id is None:
            continue
        if item.kind == "raw":
            if item.card_id not in catalog_cache:
                catalog_cache[item.card_id] = repo.get_catalog_card(item.card_id)
            card = catalog_cache[item.card_id]
            finish_price = card.prices.get(item.finish) if card else None
            value = finish_price.market if finish_price else None
        else:
            ckey = (item.card_id, item.company, item.grade)
            if ckey not in graded_cache:
                graded_cache[ckey] = repo.get_graded_market_value(
                    item.card_id, item.company, item.grade
                )
            value = graded_cache[ckey]
        if value is not None and value != item.current_market_value:
            repo.put_inventory_item(item.model_copy(update={"current_market_value": value}))
            updated += 1
    return updated


def snapshot_sealed_prices(repo, today: date) -> dict:
    """Append a daily history point for each sealed item with a market value.

    Sealed products have no catalog card, so their history hangs off the item
    itself (``ITEM#<item_id>`` price points).
    """
    written = 0
    for item in repo.list_inventory():
        if item.kind != "sealed" or item.current_market_value is None:
            continue
        repo.append_item_price_point(item.item_id, today, item.current_market_value)
        written += 1
    return {"sealed_points_written": written}


def run_daily_sync(repo, today: date) -> dict:
    """Run all sync steps in order and return their merged summary."""
    summary = dict(snapshot_graded_prices(repo, today))
    summary.update(snapshot_sealed_prices(repo, today))
    summary["items_refreshed"] = refresh_inventory_market_values(repo)
    return summary
