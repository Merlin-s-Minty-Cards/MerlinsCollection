import time
from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from merlins_collection.models.business import (
    BuyingPolicy,
    CashAccount,
    Consignor,
    PaymentMethod,
    Show,
    Transaction,
)
from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    GradedInventoryItem,
    GradingCompany,
    RawInventoryItem,
    SealedInventoryItem,
)
from merlins_collection.services.dynamodb import INVENTORY_SHARD_COUNT, _bucket, _grade_key


def _raw_item(card_id="swsh1-1", finish="holofoil", condition="NM"):
    return RawInventoryItem(
        card_id=card_id, listed_price=Decimal("10"),
        cost_basis=Decimal("4"), acquired_at=_date(2026, 1, 1),
        finish=finish, condition=Condition(condition),
    )


def _card(card_id="swsh1-1", set_id="swsh1", market="12.50"):
    return CatalogCard(
        card_id=card_id, name="Celebi V", set_id=set_id, set_name="S&S",
        number="1", images={"small": "s", "large": "l"},
        prices={"holofoil": {"market": Decimal(market)}},
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )


def test_upsert_then_get_catalog_card(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card()])
    got = dynamo_repo.get_catalog_card("swsh1-1")
    assert got is not None
    assert got.name == "Celebi V"
    assert got.prices["holofoil"].market == Decimal("12.50")


def test_get_missing_card_returns_none(dynamo_repo):
    assert dynamo_repo.get_catalog_card("nope") is None


def test_list_cards_by_set(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards(
        [_card("a-1", "setA"), _card("a-2", "setA"), _card("b-1", "setB")]
    )
    cards = dynamo_repo.list_cards_by_set("setA")
    assert {c.card_id for c in cards} == {"a-1", "a-2"}


def test_batch_upsert_handles_more_than_25(dynamo_repo):
    cards = [_card(f"big-{i}", "setBig") for i in range(30)]
    dynamo_repo.batch_upsert_catalog_cards(cards)
    assert len(dynamo_repo.list_cards_by_set("setBig")) == 30


def test_batch_get_catalog_cards_returns_found_and_skips_missing(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card("a-1"), _card("a-2")])

    got = dynamo_repo.batch_get_catalog_cards({"a-1", "a-2", "a-missing"})

    assert set(got) == {"a-1", "a-2"}
    assert got["a-1"].name == "Celebi V"


def test_batch_get_catalog_cards_handles_more_than_100_keys(dynamo_repo):
    """DynamoDB caps BatchGetItem at 100 keys — the repo must chunk."""
    dynamo_repo.batch_upsert_catalog_cards([_card(f"bulk-{i}", "setBulk") for i in range(120)])

    got = dynamo_repo.batch_get_catalog_cards([f"bulk-{i}" for i in range(120)])

    assert len(got) == 120


def test_batch_get_catalog_cards_empty_input_returns_empty(dynamo_repo):
    assert dynamo_repo.batch_get_catalog_cards([]) == {}


def test_batch_get_catalog_cards_bounds_unprocessed_retries(dynamo_repo, monkeypatch):
    """A perpetually-throttled BatchGetItem returns its keys in UnprocessedKeys
    on a *successful* response (no exception), so boto3's own retries never fire.
    The repo must bound its own retries instead of looping forever and hanging
    the request; missing ids are simply absent, per the method contract.
    """
    key = {"PK": "CARD#a-1", "SK": "META"}
    calls = []

    def always_unprocessed(**kwargs):
        calls.append(kwargs)
        return {
            "Responses": {},
            "UnprocessedKeys": {dynamo_repo._table_name: {"Keys": [key]}},
        }

    monkeypatch.setattr(dynamo_repo._resource, "batch_get_item", always_unprocessed)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    got = dynamo_repo.batch_get_catalog_cards(["a-1"])

    assert got == {}  # gave up gracefully — id absent rather than raising
    assert 1 < len(calls) <= 8  # retried, but bounded; did not loop forever


def test_graded_price_set_and_get(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        "swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    assert (
        dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"))
        == Decimal("500")
    )


def test_graded_price_grade_key_is_normalized(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        "swsh1-1", GradingCompany.BGS, Decimal("9.5"), Decimal("100")
    )
    # A differently-spelled-but-equal grade must resolve to the same key.
    assert (
        dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.BGS, Decimal("9.50"))
        == Decimal("100")
    )


def test_catalog_upsert_does_not_clobber_graded_price(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        "swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    dynamo_repo.batch_upsert_catalog_cards([_card()])  # re-sync the same card
    assert (
        dynamo_repo.get_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"))
        == Decimal("500")
    )


def _raw_point(card_id, d, market):
    return PricePoint(card_id=card_id, date=d, source="pokemontcg.io",
                      kind="raw", finish="holofoil", market=Decimal(market))


def test_price_history_range_for_finish(dynamo_repo):
    dynamo_repo.append_price_points([
        _raw_point("c1", _date(2026, 6, 20), "10"),
        _raw_point("c1", _date(2026, 6, 21), "11"),
        _raw_point("c1", _date(2026, 6, 22), "12"),
    ])
    got = dynamo_repo.get_price_history(
        "c1", finish="holofoil", start=_date(2026, 6, 21), end=_date(2026, 6, 22)
    )
    assert [p.date for p in got] == [_date(2026, 6, 21), _date(2026, 6, 22)]
    assert got[-1].market == Decimal("12")


def test_price_history_all_raw(dynamo_repo):
    dynamo_repo.append_price_points([_raw_point("c2", _date(2026, 6, 20), "5")])
    assert len(dynamo_repo.get_price_history("c2", finish="holofoil")) == 1


def test_query_pagination_follows_last_evaluated_key(dynamo_repo, monkeypatch):
    # Drive the LastEvaluatedKey loop deterministically (no need for >1MB of data).
    item1 = {"card_id": "c9", "date": "2026-06-20", "source": "x",
             "kind": "raw", "finish": "holofoil", "market": Decimal("1")}
    item2 = {"card_id": "c9", "date": "2026-06-21", "source": "x",
             "kind": "raw", "finish": "holofoil", "market": Decimal("2")}
    calls = []

    def fake_query(**kwargs):
        calls.append(kwargs)
        if "ExclusiveStartKey" not in kwargs:
            return {"Items": [item1], "LastEvaluatedKey": {"PK": "CARD#c9", "SK": "p"}}
        return {"Items": [item2]}

    monkeypatch.setattr(dynamo_repo._table, "query", fake_query)
    got = dynamo_repo.get_price_history("c9", finish="holofoil")
    assert len(got) == 2
    assert len(calls) == 2
    assert "ExclusiveStartKey" in calls[1]


def test_bucket_is_stable_and_in_range():
    assert _bucket("swsh1-1") == _bucket("swsh1-1")
    assert 0 <= _bucket("swsh1-1") < INVENTORY_SHARD_COUNT


def test_inventory_item_round_trip_by_item_id(dynamo_repo):
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item.item_id) == item
    dynamo_repo.delete_inventory_item(item.item_id)
    assert dynamo_repo.get_inventory_item(item.item_id) is None


def test_sealed_and_bulk_items_store_without_card_id(dynamo_repo):
    sealed = SealedInventoryItem(product_name="ES Booster Box", product_type="booster_box",
                                 cost_basis=Decimal("400"), acquired_at=_date(2026, 1, 5))
    bulk = BulkInventoryItem(description="bulk lot", cost_basis=Decimal("20"),
                             acquired_at=_date(2026, 1, 5))
    dynamo_repo.put_inventory_item(sealed)
    dynamo_repo.put_inventory_item(bulk)
    kinds = {i.kind for i in dynamo_repo.list_inventory()}
    assert kinds == {"sealed", "bulk"}


def test_two_identical_cards_are_distinct_items(dynamo_repo):
    a, b = _raw_item(), _raw_item()  # same card/finish/condition, different item_id
    dynamo_repo.put_inventory_item(a)
    dynamo_repo.put_inventory_item(b)
    assert len(dynamo_repo.list_inventory()) == 2


def test_list_inventory_gathers_across_shards(dynamo_repo):
    items = [_raw_item(card_id=f"card-{i}") for i in range(25)]
    for it in items:
        dynamo_repo.put_inventory_item(it)
    listed = dynamo_repo.list_inventory()
    assert len(listed) == 25
    assert {i.card_id for i in listed} == {f"card-{i}" for i in range(25)}


def test_list_inventory_for_card_only_returns_card_linked_items(dynamo_repo):
    dynamo_repo.put_inventory_item(_raw_item(condition="NM"))
    dynamo_repo.put_inventory_item(_raw_item(condition="LP"))
    dynamo_repo.put_inventory_item(_raw_item(card_id="other"))
    dynamo_repo.put_inventory_item(_raw_item(card_id=None))
    rows = dynamo_repo.list_inventory_for_card("swsh1-1")
    assert len(rows) == 2
    assert {r.condition for r in rows} == {Condition.NM, Condition.LP}


def test_put_then_get_graded_inventory_item(dynamo_repo):
    item = GradedInventoryItem(
        card_id="swsh1-1", listed_price=Decimal("600"),
        cost_basis=Decimal("300"), acquired_at=_date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number="12345678",
    )
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_inventory_item(item.item_id) == item


def test_price_history_start_only(dynamo_repo):
    dynamo_repo.append_price_points([
        _raw_point("c3", _date(2026, 6, 20), "10"),
        _raw_point("c3", _date(2026, 6, 22), "12"),
    ])
    got = dynamo_repo.get_price_history("c3", finish="holofoil", start=_date(2026, 6, 21))
    assert [p.date for p in got] == [_date(2026, 6, 22)]


def test_price_history_end_only(dynamo_repo):
    dynamo_repo.append_price_points([
        _raw_point("c4", _date(2026, 6, 20), "10"),
        _raw_point("c4", _date(2026, 6, 22), "12"),
    ])
    got = dynamo_repo.get_price_history("c4", finish="holofoil", end=_date(2026, 6, 21))
    assert [p.date for p in got] == [_date(2026, 6, 20)]


def test_shows_round_trip_chronological(dynamo_repo):
    later = Show(name="B Show", date=_date(2026, 5, 2))
    earlier = Show(name="A Show", date=_date(2026, 4, 4))
    dynamo_repo.put_show(later)
    dynamo_repo.put_show(earlier)
    names = [s.name for s in dynamo_repo.list_shows()]
    assert names == ["A Show", "B Show"]  # SK sorts by date
    assert dynamo_repo.get_show(later.show_id) == later
    assert dynamo_repo.get_show("nope") is None


def test_consignors_round_trip(dynamo_repo):
    c = Consignor(name="David", contact="555-1234")
    dynamo_repo.put_consignor(c)
    assert dynamo_repo.list_consignors() == [c]


def test_config_entities_round_trip(dynamo_repo):
    dynamo_repo.put_cash_account(CashAccount(account="venmo", balance=Decimal("100")))
    dynamo_repo.put_buying_policy(BuyingPolicy(product_type="slabs",
                                               cash_pct_min=Decimal("60")))
    venmo = PaymentMethod(method="venmo", fee_percent=Decimal("1.9"),
                          fee_fixed=Decimal("0.10"))
    dynamo_repo.put_payment_method(venmo)
    assert dynamo_repo.list_cash_accounts()[0].balance == Decimal("100")
    assert dynamo_repo.list_buying_policies()[0].product_type == "slabs"
    assert dynamo_repo.get_payment_method("venmo") == venmo
    assert dynamo_repo.get_payment_method("zelle") is None
    assert [m.method for m in dynamo_repo.list_payment_methods()] == ["venmo"]


def _txn(**over):
    kw = dict(type="sale", item_id="i-1", category="raw", date=_date(2026, 3, 10),
              amount=Decimal("40.00"), payment_method="cash")
    kw.update(over)
    return Transaction(**kw)


def test_transactions_query_by_date_range_across_months(dynamo_repo):
    feb = _txn(date=_date(2026, 2, 27))
    mar = _txn(date=_date(2026, 3, 5))
    apr = _txn(date=_date(2026, 4, 1))
    for t in (feb, mar, apr):
        dynamo_repo.put_transaction(t)
    found = dynamo_repo.list_transactions(_date(2026, 2, 1), _date(2026, 3, 31))
    assert sorted(t.txn_id for t in found) == sorted([feb.txn_id, mar.txn_id])
    # sub-month range bounds within the partition
    found = dynamo_repo.list_transactions(_date(2026, 3, 1), _date(2026, 3, 4))
    assert found == []


def test_transactions_query_by_show(dynamo_repo):
    at_show = _txn(show_id="show-1")
    off_show = _txn()
    dynamo_repo.put_transaction(at_show)
    dynamo_repo.put_transaction(off_show)
    found = dynamo_repo.list_transactions_for_show("show-1")
    assert [t.txn_id for t in found] == [at_show.txn_id]


def test_item_price_points_round_trip_sorted(dynamo_repo):
    dynamo_repo.append_item_price_point("item-1", _date(2026, 3, 2), Decimal("410"))
    dynamo_repo.append_item_price_point("item-1", _date(2026, 3, 1), Decimal("400"))
    history = dynamo_repo.get_item_price_history("item-1")
    assert [h["market_value"] for h in history] == [Decimal("400"), Decimal("410")]


def test_grade_key_canonicalizes():
    assert _grade_key(Decimal("9.50")) == "9.5"
    assert _grade_key(Decimal("10")) == "10"
    assert _grade_key(Decimal("10.0")) == "10"


# ---- expense ledger (EXP# month partitions; per-show derived by filter) ----

def test_put_and_list_expenses_by_month_range(dynamo_repo):
    from merlins_collection.models.business import Expense, ExpenseCategory
    jan = Expense(category=ExpenseCategory.MARKETING, date=_date(2026, 1, 15),
                  amount=Decimal("23.99"))
    mar = Expense(category=ExpenseCategory.SUPPLIES, date=_date(2026, 3, 2),
                  amount=Decimal("56.66"))
    dynamo_repo.put_expense(jan)
    dynamo_repo.put_expense(mar)

    jan_only = dynamo_repo.list_expenses(_date(2026, 1, 1), _date(2026, 1, 31))
    assert [e.expense_id for e in jan_only] == [jan.expense_id]

    both = dynamo_repo.list_expenses(_date(2026, 1, 1), _date(2026, 3, 31))
    assert {e.expense_id for e in both} == {jan.expense_id, mar.expense_id}


def test_expenses_do_not_pollute_the_show_transaction_index(dynamo_repo):
    """An expense linked to a show must not corrupt the GSI2 Transaction reader."""
    from merlins_collection.models.business import Expense, ExpenseCategory
    dynamo_repo.put_expense(Expense(
        category=ExpenseCategory.SHOW_FEE, date=_date(2026, 1, 10),
        amount=Decimal("30.00"), show_id="show-1"))
    # GSI2 is read back as Transactions; expenses stay out of it, so this is empty.
    assert dynamo_repo.list_transactions_for_show("show-1") == []


# ---- debts (single DEBTLIST partition) ----

def test_put_and_list_debts(dynamo_repo):
    from merlins_collection.models.business import Debt, DebtDirection
    dynamo_repo.put_debt(Debt(direction=DebtDirection.OWED_TO_US,
                              date=_date(2026, 1, 10), amount=Decimal("22"),
                              counterparty="Colin"))
    dynamo_repo.put_debt(Debt(direction=DebtDirection.WE_OWE,
                              date=_date(2026, 1, 10), amount=Decimal("30"),
                              counterparty="Jackson", cleared=True))
    debts = dynamo_repo.list_debts()
    assert {(d.direction.value, d.counterparty) for d in debts} == {
        ("owed_to_us", "Colin"), ("we_owe", "Jackson")}


# ---- payouts (single PAYOUTLIST partition) ----

def test_put_and_list_payouts(dynamo_repo):
    from merlins_collection.models.business import Payout
    dynamo_repo.put_payout(Payout(event="E1", partner="Casey", amount=Decimal("40")))
    dynamo_repo.put_payout(Payout(event="E1", partner="Colin", amount=Decimal("60")))
    payouts = dynamo_repo.list_payouts()
    assert {(p.partner, p.amount) for p in payouts} == {
        ("Casey", Decimal("40")), ("Colin", Decimal("60"))}


# ---- balance sheet snapshots (BALANCESHEET partition) ----

def test_put_and_list_balance_sheets(dynamo_repo):
    from merlins_collection.models.business import (
        BalanceSheetLine, BalanceSheetSnapshot, BalanceSheetSection)
    for label, frozen in (("beginning", True), ("current", False)):
        dynamo_repo.put_balance_sheet(BalanceSheetSnapshot(
            snapshot_id=label, label=label, frozen=frozen,
            lines=[BalanceSheetLine(section=BalanceSheetSection.ASSET,
                                    label="Inventory", amount=Decimal("100"))]))
    snaps = {s.label: s for s in dynamo_repo.list_balance_sheets()}
    assert snaps["beginning"].frozen is True
    assert snaps["current"].frozen is False
    assert snaps["beginning"].lines[0].label == "Inventory"


# ================= Council revision-6 fixes (BLOCKING-4 / lock) ================
# R5's monotonic `record_gen < gen` ordering rested on cross-machine ULID
# wall-clock agreement (BLOCKING-4). R6 replaces it with a single-flight import
# LOCK (so no two runs are ever concurrent) plus commit-order-wins deletion
# (`gen != mine`), which is wall-clock-independent: the run that commits LAST wins
# regardless of its gen value.

def _debt(who):
    from merlins_collection.models.business import Debt, DebtDirection
    return Debt(direction=DebtDirection.OWED_TO_US, date=_date(2026, 1, 1),
                amount=Decimal("10"), counterparty=who)


def test_R6_later_committed_run_wins_regardless_of_gen_value(dynamo_repo):
    # A run with a LEXICALLY-LARGER gen commits FIRST (older content, e.g. a
    # clock-skewed laptop). A later run with a SMALLER gen commits SECOND (the
    # genuinely newest content). Commit order — not ULID value — must decide the
    # winner, so the second run's data survives and the first's is swept.
    dynamo_repo.set_import_generation("gen-ZZZZ")  # lexically large
    dynamo_repo.put_debt(_debt("Stale"))
    dynamo_repo.finalize_import("gen-ZZZZ", committed=True)
    dynamo_repo.set_import_generation(None)

    dynamo_repo.set_import_generation("gen-AAAA")  # lexically small, commits later
    dynamo_repo.put_debt(_debt("Fresh"))
    dynamo_repo.finalize_import("gen-AAAA", committed=True)
    dynamo_repo.set_import_generation(None)

    who = {d.counterparty for d in dynamo_repo.list_debts()}
    assert who == {"Fresh"}  # newest COMMITTED wins; stale larger-gen row swept


def test_R6_import_lock_is_single_flight(dynamo_repo):
    from merlins_collection.services.dynamodb import ImportInProgressError
    dynamo_repo.acquire_import_lock("gen-A")
    # A second acquire while the lock is held is refused.
    try:
        dynamo_repo.acquire_import_lock("gen-B")
        raised = False
    except ImportInProgressError:
        raised = True
    assert raised
    # After release, a new run can acquire.
    dynamo_repo.release_import_lock("gen-A")
    dynamo_repo.acquire_import_lock("gen-B")  # no raise
    dynamo_repo.release_import_lock("gen-B")


def test_R6_import_lock_is_not_import_owned(dynamo_repo):
    # The lock item must never be swept by finalize (it is not import-owned data).
    dynamo_repo.acquire_import_lock("gen-A")
    dynamo_repo.set_import_generation("gen-A")
    dynamo_repo.put_debt(_debt("X"))
    dynamo_repo.finalize_import("gen-A", committed=True)
    dynamo_repo.set_import_generation(None)
    # Lock survived the commit sweep -> a stale second acquire is still refused.
    from merlins_collection.services.dynamodb import ImportInProgressError
    try:
        dynamo_repo.acquire_import_lock("gen-B")
        held = False
    except ImportInProgressError:
        held = True
    assert held
    dynamo_repo.release_import_lock("gen-A")


def test_R5_finalize_scan_reads_strongly_consistent(dynamo_repo):
    from merlins_collection.models.business import Debt, DebtDirection
    scan_consistency = []
    original_scan = dynamo_repo._table.scan

    def _spy(**kwargs):
        scan_consistency.append(kwargs.get("ConsistentRead"))
        return original_scan(**kwargs)

    dynamo_repo._table.scan = _spy
    dynamo_repo.set_import_generation("gen-x")
    dynamo_repo.put_debt(Debt(direction=DebtDirection.OWED_TO_US, date=_date(2026, 1, 1),
                              amount=Decimal("1"), counterparty="X"))
    dynamo_repo.finalize_import("gen-x", committed=True)
    dynamo_repo.set_import_generation(None)
    assert scan_consistency  # the finalize scan ran
    assert all(c is True for c in scan_consistency)  # every page read strongly-consistent
