from datetime import date
from decimal import Decimal

from merlins_collection.services.catalog_sync import sync_catalog

RAW = {
    "id": "swsh1-1", "name": "Celebi V", "number": "1",
    "set": {"id": "swsh1", "name": "S&S"},
    "images": {"small": "s", "large": "l"},
    "tcgplayer": {"prices": {"holofoil": {"market": 9.25}}},
}


class FakeClient:
    def __init__(self, cards):
        self._cards = cards

    def iter_all_cards(self):
        yield from self._cards


def test_sync_catalog_upserts_card_and_price_point(dynamo_repo):
    summary = sync_catalog(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))
    assert summary == {"cards_synced": 1, "price_points_written": 1, "failures": 0}
    assert dynamo_repo.get_catalog_card("swsh1-1").prices["holofoil"].market == Decimal("9.25")
    history = dynamo_repo.get_price_history("swsh1-1", finish="holofoil")
    assert [p.date for p in history] == [date(2026, 6, 22)]


def test_sync_catalog_is_idempotent_for_same_day(dynamo_repo):
    sync_catalog(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))
    sync_catalog(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))
    assert len(dynamo_repo.get_price_history("swsh1-1", finish="holofoil")) == 1


def test_sync_catalog_skips_bad_cards(dynamo_repo):
    summary = sync_catalog(dynamo_repo, FakeClient([{"bad": "no id"}, RAW]), date(2026, 6, 22))
    assert summary["failures"] == 1
    assert summary["cards_synced"] == 1
