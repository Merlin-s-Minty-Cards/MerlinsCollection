from datetime import date
from decimal import Decimal

from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
)
from merlins_collection.services.catalog_sync import (
    refresh_inventory_market_values,
    run_daily_sync,
    snapshot_graded_prices,
    snapshot_sealed_prices,
)
from merlins_collection.services.tcgdex import to_catalog_card

FX = Decimal("1.08")

# A TCGdex *detail* record — the only response shape that carries pricing.
RAW = {
    "id": "swsh1-1", "localId": "1", "name": "Celebi V",
    "set": {"id": "swsh1", "name": "S&S"},
    "image": "https://assets.tcgdex.net/en/swsh/swsh1/1",
    "pricing": {"tcgplayer": {
        "unit": "USD", "updated": "2026-06-22T00:00:00.000Z",
        "holofoil": {"marketPrice": 9.25},
    }},
}
CARD_ID = "en:swsh1-1"


def _raw_item(card_id=CARD_ID):
    return RawInventoryItem(
        card_id=card_id, listed_price=Decimal("10"),
        cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.NM,
    )


def _graded_item(card_id=CARD_ID):
    return GradedInventoryItem(
        card_id=card_id, listed_price=Decimal("700"),
        cost_basis=Decimal("300"), acquired_at=date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number="123",
    )


def _seed_catalog(repo):
    """Put the mapped catalog card in place; Phase 2 owns the writer that fetches
    the detail record this maps from (see BLOAT-1 in the revision-1 verdict)."""
    repo.batch_upsert_catalog_cards([to_catalog_card(RAW, Language.EN, fx_rate=FX)])


def test_refresh_sets_current_market_value_from_catalog(dynamo_repo):
    _seed_catalog(dynamo_repo)
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    updated = refresh_inventory_market_values(dynamo_repo)
    assert updated == 1
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("9.25")


def test_snapshot_graded_prices_writes_history_for_owned_slabs(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    dynamo_repo.put_inventory_item(_graded_item())
    summary = snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))
    assert summary == {"graded_points_written": 1}
    hist = dynamo_repo.get_price_history(CARD_ID, company=GradingCompany.PSA, grade=Decimal("10"))
    assert hist[0].market == Decimal("500")


def test_run_daily_sync_combines_steps(dynamo_repo):
    _seed_catalog(dynamo_repo)
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    summary = run_daily_sync(dynamo_repo, date(2026, 6, 22))
    assert summary["items_refreshed"] == 1
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("9.25")


def test_sync_skips_unlinked_items_and_snapshots_sealed(dynamo_repo):
    unlinked = RawInventoryItem(card_id=None, finish="normal", condition="NM",
                                cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1))
    sealed = SealedInventoryItem(product_name="Box", product_type="booster_box",
                                 cost_basis=Decimal("400"),
                                 current_market_value=Decimal("500"),
                                 acquired_at=date(2026, 1, 1))
    dynamo_repo.put_inventory_item(unlinked)
    dynamo_repo.put_inventory_item(sealed)
    # must not raise on card_id=None / non-card kinds:
    assert refresh_inventory_market_values(dynamo_repo) == 0
    summary = snapshot_sealed_prices(dynamo_repo, date(2026, 3, 1))
    assert summary == {"sealed_points_written": 1}
    assert len(dynamo_repo.get_item_price_history(sealed.item_id)) == 1


def test_run_daily_sync_includes_graded_snapshot_and_refresh(dynamo_repo):
    # Own a graded slab and set its manual market value.
    dynamo_repo.set_graded_market_value(
        CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    item = _graded_item()
    dynamo_repo.put_inventory_item(item)

    summary = run_daily_sync(dynamo_repo, date(2026, 6, 22))

    # merge completeness: graded snapshot key is present and counted
    assert summary["graded_points_written"] == 1
    # graded refresh write-back path: current_market_value denormalized from the manual graded value
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("500")
