"""Daily batch sync of catalog data, prices, and inventory market values.

Orchestrates the scheduled job that keeps DynamoDB current. ``run_daily_sync``
is the entry point; the individual steps are exposed for testing and re-use:

- ``sync_catalog`` — pull every card from pokemontcg.io, upsert catalog rows,
  and record one raw price-history point per finish for ``today``.
- ``snapshot_graded_prices`` — append a daily history point for each owned
  graded slab that has a manual market value.
- ``refresh_inventory_market_values`` — denormalize the latest market value onto
  each inventory item so list/search reads don't need a second lookup.

Each function takes ``repo`` (an ``InventoryRepository``) and returns a small
summary dict so the job can log what it did.
"""

from __future__ import annotations

from datetime import date

from merlins_collection.models.catalog import PricePoint
from merlins_collection.services.pokemontcg import to_catalog_card


def sync_catalog(repo, client, today: date, *, batch_size: int = 500) -> dict:
    """Upsert catalog cards + raw price points, flushing in ``batch_size`` chunks.

    Cards that fail to map are skipped and counted under ``failures`` so one bad
    record never aborts the whole run.
    """
    cards: list = []
    points: list = []
    cards_synced = 0
    points_written = 0
    failures = 0

    def flush_cards():
        nonlocal cards
        if cards:
            repo.batch_upsert_catalog_cards(cards)
            cards = []

    def flush_points():
        nonlocal points, points_written
        if points:
            repo.append_price_points(points)
            points_written += len(points)
            points = []

    for raw in client.iter_all_cards():
        try:
            card = to_catalog_card(raw)
        except Exception:
            failures += 1
            continue
        cards.append(card)
        cards_synced += 1
        for finish, fp in card.prices.items():
            points.append(
                PricePoint(
                    card_id=card.card_id, date=today, source="pokemontcg.io",
                    kind="raw", finish=finish,
                    market=fp.market, low=fp.low, mid=fp.mid, high=fp.high,
                )
            )
        if len(cards) >= batch_size:
            flush_cards()
        if len(points) >= batch_size:
            flush_points()

    flush_cards()
    flush_points()
    return {
        "cards_synced": cards_synced,
        "price_points_written": points_written,
        "failures": failures,
    }


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


def run_daily_sync(repo, client, today: date) -> dict:
    """Run all sync steps in order and return their merged summary."""
    summary = sync_catalog(repo, client, today)
    summary.update(snapshot_graded_prices(repo, today))
    summary.update(snapshot_sealed_prices(repo, today))
    summary["items_refreshed"] = refresh_inventory_market_values(repo)
    return summary
