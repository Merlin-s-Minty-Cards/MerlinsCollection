"""RED availability/ownership boundary tests for shared customer inventory."""

from datetime import date
from decimal import Decimal

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _hydrate(repo, item_id: str):
    assert hasattr(bedrock, "_hydrate_item"), "RFC 0016 _hydrate_item is not implemented"
    return bedrock._hydrate_item(repo, item_id)


def _item(item_id: str, status: ItemStatus = ItemStatus.AVAILABLE):
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=status,
        listed_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
    )


def test_unknown_item_id_cannot_be_hydrated(dynamo_repo):
    assert _hydrate(dynamo_repo, "not-owned-or-missing") is None


def test_unavailable_item_cannot_be_hydrated(dynamo_repo):
    item = _item("sold-item", ItemStatus.SOLD)
    dynamo_repo.put_inventory_item(item)
    assert _hydrate(dynamo_repo, item.item_id) is None


def test_any_available_shared_inventory_item_can_be_hydrated(dynamo_repo):
    """Phase 1 inventory is shared; there is deliberately no per-user owner field."""
    item = _item("shared-item")
    dynamo_repo.put_inventory_item(item)
    assert _hydrate(dynamo_repo, item.item_id).item_id == "shared-item"
