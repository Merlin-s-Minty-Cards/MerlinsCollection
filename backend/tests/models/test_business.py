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


# ---- Expense (unifies the 6 expense tabs) ----

def test_expense_round_trip_and_defaults():
    from merlins_collection.models.business import Expense, ExpenseCategory
    exp = Expense(
        category=ExpenseCategory.SHOW_FEE, date=date(2026, 1, 10),
        amount=Decimal("30.00"), payment_method="cash",
        description="Cardboard Diamonds Dec", reason="Show Fee", show_id="s1",
    )
    again = Expense.model_validate(exp.model_dump())
    assert again.category is ExpenseCategory.SHOW_FEE
    assert again.amount == Decimal("30.00")
    assert again.show_id == "s1"
    assert again.paid is True          # default
    assert again.person is None
    assert len(again.expense_id) == 26  # generated ULID


def test_expense_amount_may_be_negative_money_in():
    from merlins_collection.models.business import Expense, ExpenseCategory
    exp = Expense(category=ExpenseCategory.SHOW_FEE, date=date(2026, 1, 10),
                  amount=Decimal("-90.00"))
    assert exp.amount == Decimal("-90.00")  # negative = money coming in


# ---- Debt (two-directional: owed to us vs we owe) ----

def test_debt_round_trip_and_defaults():
    from merlins_collection.models.business import Debt, DebtDirection
    d = Debt(direction=DebtDirection.OWED_TO_US, date=date(2026, 1, 10),
             amount=Decimal("22.00"), counterparty="Colin", reason="Cashapp")
    again = Debt.model_validate(d.model_dump())
    assert again.direction is DebtDirection.OWED_TO_US
    assert again.amount == Decimal("22.00")
    assert again.counterparty == "Colin"
    assert again.cleared is False
    assert len(again.debt_id) == 26


# ---- Payout (per-event partner profit split) ----

def test_payout_round_trip_and_defaults():
    from merlins_collection.models.business import Payout
    p = Payout(event="Twinoaks (7/26)", partner="Colin", amount=Decimal("60"),
               percent=Decimal("0.05"), notes="Cash")
    again = Payout.model_validate(p.model_dump())
    assert again.partner == "Colin"
    assert again.amount == Decimal("60")
    assert again.percent == Decimal("0.05")
    assert again.notes == "Cash"
    assert len(again.payout_id) == 26


# ---- BalanceSheetSnapshot (frozen baseline + live current, for comparison) ----

def test_balance_sheet_snapshot_round_trip():
    from merlins_collection.models.business import (
        BalanceSheetLine, BalanceSheetSnapshot, BalanceSheetSection)
    snap = BalanceSheetSnapshot(
        label="beginning", frozen=True,
        lines=[BalanceSheetLine(section=BalanceSheetSection.ASSET,
                                label="Inventory", amount=Decimal("5228.81"),
                                note="what we paid"),
               BalanceSheetLine(section=BalanceSheetSection.EQUITY,
                                label="Owners Capital", amount=Decimal("4000"))])
    again = BalanceSheetSnapshot.model_validate(snap.model_dump())
    assert again.frozen is True
    assert len(again.lines) == 2
    assert again.lines[0].section.value == "asset"
    assert again.lines[0].amount == Decimal("5228.81")
