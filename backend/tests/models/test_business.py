from datetime import date
from decimal import Decimal

from merlins_collection.models.business import (
    BuyingPolicy,
    CashAccount,
    Consignor,
    ItemCategory,
    PaymentMethod,
    Show,
    Transaction,
    TransactionType,
)


def test_transaction_defaults():
    txn = Transaction(type="sale", item_id="i-1", category="raw",
                      date=date(2026, 3, 1), amount=Decimal("40.00"),
                      payment_method="venmo")
    assert txn.type is TransactionType.SALE
    assert txn.category is ItemCategory.RAW
    assert txn.fee == Decimal("0")
    assert txn.show_id is None and txn.trade_id is None
    assert txn.consignor_payout is None
    assert len(txn.txn_id) == 26


def test_payment_method_fee_percent_plus_fixed_quantized_to_cents():
    venmo = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                          fee_fixed=Decimal("0.10"))
    # 1.9% of 40.00 = 0.76, + 0.10 = 0.86
    assert venmo.fee_for(Decimal("40.00")) == Decimal("0.86")
    # 1.9% of 33.33 = 0.633... -> rounds half-up to 0.63, + 0.10
    assert venmo.fee_for(Decimal("33.33")) == Decimal("0.73")
    cash = PaymentMethod(method="cash")
    assert cash.fee_for(Decimal("100")) == Decimal("0.00")


def test_show_consignor_config_models_construct():
    show = Show(name="Mint City Show", date=date(2026, 4, 12),
                sales_goal=Decimal("500"), cash_at_start=Decimal("200"))
    assert len(show.show_id) == 26
    consignor = Consignor(name="David")
    assert len(consignor.consignor_id) == 26
    cash = CashAccount(account="venmo", balance=Decimal("321.50"))
    assert cash.updated_at is not None
    policy = BuyingPolicy(product_type="slabs", cash_pct_min=Decimal("60"),
                          cash_pct_max=Decimal("75"), trade_pct_min=Decimal("70"),
                          trade_pct_max=Decimal("85"))
    assert policy.trade_pct_max == Decimal("85")
