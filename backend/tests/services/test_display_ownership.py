"""RED availability/ownership boundary tests for shared customer inventory."""

from datetime import date
from decimal import Decimal

from merlins_collection.models.inventory import Condition, ItemStatus, RawInventoryItem
from merlins_collection.services import bedrock


def _hydrate(repo, item_id: str):
    assert hasattr(bedrock, "_hydrate_item"), "RFC 0016 _hydrate_item is not implemented"
    return bedrock._hydrate_item(repo, item_id)


def _item(
    item_id: str,
    status: ItemStatus = ItemStatus.AVAILABLE,
    *,
    location: str | None = None,
):
    """A raw item. `location` defaults to None (WITHHELD) so visibility is always
    stated explicitly in this file — it is the file that tests the gate."""
    return RawInventoryItem(
        item_id=item_id,
        card_id=None,
        status=status,
        listed_price=Decimal("10.00"),
        # RFC 0025 T2: the visibility predicate now requires a sticker price.
        sticker_price=Decimal("10.00"),
        cost_basis=Decimal("5.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location=location,
    )


def test_unknown_item_id_cannot_be_hydrated(dynamo_repo):
    assert _hydrate(dynamo_repo, "not-owned-or-missing") is None


def test_unavailable_item_cannot_be_hydrated(dynamo_repo):
    item = _item("sold-item", ItemStatus.SOLD)
    dynamo_repo.put_inventory_item(item)
    assert _hydrate(dynamo_repo, item.item_id) is None


def test_shared_inventory_has_no_per_user_owner_gate(dynamo_repo):
    """Phase 1 inventory is shared; there is deliberately no per-user owner field.

    This replaces `test_any_available_shared_inventory_item_can_be_hydrated`, which
    encoded the Council item 2 bug: it asserted an AVAILABLE item with no location
    hydrates, pinning the status-only gate as correct. The "no per-user owner"
    property it was really protecting is preserved here — a customer-visible item
    hydrates for any caller, with no owner check — while the visibility gate itself
    is enforced. Withheld-stock cases live in the item 2 section below.
    """
    item = _item("shared-item", location="glass")
    dynamo_repo.put_inventory_item(item)
    assert _hydrate(dynamo_repo, item.item_id).item_id == "shared-item"


# ---- Council item 2: visibility predicate must match customer_visible_items ----


def test_hydrate_withheld_item_in_storage_location_must_fail(dynamo_repo):
    """RED for Council item 2: _hydrate_item must use the SAME per-item visibility
    predicate as customer_visible_items in routers/inventory.py.
    
    Currently FAILS because _hydrate_item checks status==AVAILABLE only, omitting
    the kind ∈ {raw, graded} and location ∈ {glass, toploader} gates that both
    existing customer-visibility boundaries enforce.
    
    An AVAILABLE raw card in storage=storage is invisible to customer_visible_items
    but hydratable via client-supplied panel_item_ids, which is a security defect
    (Security FATAL-1).
    """
    from merlins_collection.models.inventory import RawInventoryItem
    
    withheld = RawInventoryItem(
        item_id="storage-card",
        card_id="en:base1-4",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("20.00"),
        cost_basis=Decimal("10.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location="storage",  # NOT in {glass, toploader}
        factory_sealed=False,
    )
    dynamo_repo.put_inventory_item(withheld)
    
    # This must return None (not hydratable), matching customer_visible_items behavior
    result = _hydrate(dynamo_repo, withheld.item_id)
    assert result is None, (
        f"Item in storage location must not hydrate, but got {result}. "
        "Fix: extract visibility predicate from customer_visible_items and use in _hydrate_item."
    )


def test_hydrate_bulk_item_kind_must_fail(dynamo_repo):
    """Bulk items are excluded from customer_visible_items (only raw/graded allowed)."""
    from merlins_collection.models.inventory import BulkInventoryItem
    
    bulk = BulkInventoryItem(
        item_id="bulk-lot",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("50.00"),
        cost_basis=Decimal("25.00"),
        acquired_at=date.today(),
        quantity=100,
        description="Bulk common cards",
    )
    dynamo_repo.put_inventory_item(bulk)
    
    result = _hydrate(dynamo_repo, bulk.item_id)
    assert result is None, "Bulk items must not hydrate (kind not in {raw, graded})"


def test_hydrate_factory_sealed_without_location_succeeds(dynamo_repo):
    """Factory sealed items are visible regardless of location (or even if location is None)."""
    from merlins_collection.models.inventory import RawInventoryItem
    
    sealed = RawInventoryItem(
        item_id="sealed-box",
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("150.00"),
        sticker_price=Decimal("150.00"),
        cost_basis=Decimal("100.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location=None,  # No location recorded
        factory_sealed=True,
    )
    dynamo_repo.put_inventory_item(sealed)
    
    result = _hydrate(dynamo_repo, sealed.item_id)
    assert result is not None, "Factory sealed items must hydrate regardless of location"
    assert result.item_id == "sealed-box"


def test_hydrate_graded_in_glass_location_succeeds(dynamo_repo):
    """Graded slabs in glass/toploader are customer-visible."""
    from merlins_collection.models.inventory import GradedInventoryItem, GradingCompany

    graded = GradedInventoryItem(
        item_id="graded-slab",
        card_id="en:base1-4",
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("500.00"),
        sticker_price=Decimal("500.00"),
        cost_basis=Decimal("300.00"),
        acquired_at=date.today(),
        cert_number="12345678",
        company=GradingCompany.PSA,
        grade=Decimal("10"),
        location="glass",
    )
    dynamo_repo.put_inventory_item(graded)
    
    result = _hydrate(dynamo_repo, graded.item_id)
    assert result is not None
    assert result.item_id == "graded-slab"
