from __future__ import annotations

from datetime import date

from merlins_collection.models.catalog import PricePoint
from merlins_collection.services.pokemontcg import to_catalog_card


def sync_catalog(repo, client, today: date, *, batch_size: int = 500) -> dict:
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
