from datetime import date
from decimal import Decimal

from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    RawInventoryItem,
)
from merlins_collection.services.catalog_sync import (
    refresh_inventory_market_values,
    run_daily_sync,
    snapshot_graded_prices,
    sync_catalog,
)

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


def _raw_item(card_id="swsh1-1"):
    return RawInventoryItem(
        card_id=card_id, quantity=2, listed_price=Decimal("10"),
        cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.NM,
    )


def _graded_item(card_id="swsh1-1"):
    return GradedInventoryItem(
        card_id=card_id, quantity=1, listed_price=Decimal("700"),
        cost_basis=Decimal("300"), acquired_at=date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number="123",
    )


def test_refresh_sets_current_market_value_from_catalog(dynamo_repo):
    sync_catalog(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))
    dynamo_repo.put_inventory_item(_raw_item())
    updated = refresh_inventory_market_values(dynamo_repo)
    assert updated == 1
    assert dynamo_repo.get_inventory_item(_raw_item()).current_market_value == Decimal("9.25")


def test_snapshot_graded_prices_writes_history_for_owned_slabs(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        "swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    dynamo_repo.put_inventory_item(_graded_item())
    summary = snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))
    assert summary == {"graded_points_written": 1}
    hist = dynamo_repo.get_price_history("swsh1-1", company=GradingCompany.PSA, grade=Decimal("10"))
    assert hist[0].market == Decimal("500")


def test_run_daily_sync_combines_steps(dynamo_repo):
    dynamo_repo.put_inventory_item(_raw_item())
    summary = run_daily_sync(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))
    assert summary["cards_synced"] == 1
    assert summary["items_refreshed"] == 1
    assert dynamo_repo.get_inventory_item(_raw_item()).current_market_value == Decimal("9.25")


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


def test_run_daily_sync_includes_graded_snapshot_and_refresh(dynamo_repo):
    # Own a graded slab and set its manual market value.
    dynamo_repo.set_graded_market_value(
        "swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    dynamo_repo.put_inventory_item(_graded_item())

    summary = run_daily_sync(dynamo_repo, FakeClient([RAW]), date(2026, 6, 22))

    # merge completeness: graded snapshot key is present and counted
    assert summary["graded_points_written"] == 1
    # graded refresh write-back path: current_market_value denormalized from the manual graded value
    assert dynamo_repo.get_inventory_item(_graded_item()).current_market_value == Decimal("500")
