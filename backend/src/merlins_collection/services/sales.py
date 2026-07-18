"""Sale construction: fee + consignor-payout math for the transaction ledger."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from merlins_collection.models.business import (
    ItemCategory,
    PaymentMethod,
    Transaction,
    TransactionType,
)
from merlins_collection.models.inventory import InventoryItem


def build_sale_transaction(
    item: InventoryItem,
    *,
    amount: Decimal,
    method: PaymentMethod,
    sale_date: date,
    show_id: str | None = None,
    trade_id: str | None = None,
) -> Transaction:
    """Build (not persist) the ledger record for selling ``item``.

    Consigned items are categorized ``consignment`` and carry the payout the
    consignor is owed: the gross minus our ``split_percent`` cut.
    """
    if item.consignment is not None:
        category = ItemCategory.CONSIGNMENT
        our_cut = (amount * item.consignment.split_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        payout = amount - our_cut
    else:
        category = ItemCategory(item.kind)
        payout = None
    return Transaction(
        type=TransactionType.SALE,
        item_id=item.item_id,
        category=category,
        date=sale_date,
        amount=amount,
        payment_method=method.method,
        fee=method.fee_for(amount),
        show_id=show_id,
        trade_id=trade_id,
        consignor_payout=payout,
    )
