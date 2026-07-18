from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import PaymentMethod
from merlins_collection.models.inventory import (
    ConsignmentTerms,
    ItemStatus,
    RawInventoryItem,
)
from merlins_collection.services.dynamodb import ItemAlreadySoldError
from merlins_collection.services.sales import build_sale_transaction

VENMO = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"), fee_fixed=Decimal("0.10"))
CASH = PaymentMethod(method="cash")


def _item(**over):
    kw = dict(card_id="xy1-1", finish="normal", condition="NM",
              cost_basis=Decimal("10.00"), acquired_at=date(2026, 1, 5))
    kw.update(over)
    return RawInventoryItem(**kw)


def test_build_sale_computes_fee_and_category():
    item = _item()
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=VENMO,
                                 sale_date=date(2026, 3, 10), show_id="show-1")
    assert txn.type == "sale"
    assert txn.item_id == item.item_id
    assert txn.category == "raw"
    assert txn.fee == Decimal("0.86")
    assert txn.show_id == "show-1"
    assert txn.consignor_payout is None


def test_build_sale_for_consigned_item_computes_payout():
    terms = ConsignmentTerms(consignor_id="c-1", split_percent=Decimal("20"))
    item = _item(consignment=terms)
    txn = build_sale_transaction(item, amount=Decimal("100.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    assert txn.category == "consignment"
    assert txn.consignor_payout == Decimal("80.00")  # consignor gets 100 - our 20%


def test_record_sale_is_atomic_and_flips_status(dynamo_repo):
    item = _item()
    dynamo_repo.put_inventory_item(item)
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    dynamo_repo.record_sale(txn)
    assert dynamo_repo.get_inventory_item(item.item_id).status is ItemStatus.SOLD
    assert dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31)) == [txn]


def test_record_sale_rejects_double_sell(dynamo_repo):
    item = _item()
    dynamo_repo.put_inventory_item(item)
    txn = build_sale_transaction(item, amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    dynamo_repo.record_sale(txn)
    with pytest.raises(ItemAlreadySoldError):
        dynamo_repo.record_sale(build_sale_transaction(
            item, amount=Decimal("45.00"), method=CASH, sale_date=date(2026, 3, 11)))


def test_record_sale_rejects_missing_item(dynamo_repo):
    txn = build_sale_transaction(_item(), amount=Decimal("40.00"), method=CASH,
                                 sale_date=date(2026, 3, 10))
    with pytest.raises(ItemAlreadySoldError):
        dynamo_repo.record_sale(txn)
