import time
from datetime import date as _date
from datetime import datetime
from decimal import Decimal

import pytest

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


def test_batch_upsert_deduplicates_repeated_ids_within_one_call(dynamo_repo):
    """boto3's ``batch_writer`` does not deduplicate: two rows with the same key
    in one request raise ``ValidationException`` and fail the whole 25-item
    batch — killing the run over rows that were redundant, not wrong."""
    dynamo_repo.batch_upsert_catalog_cards(
        [_card("dupe-1", market="1.00"), _card("dupe-1", market="2.00")]
    )
    assert dynamo_repo.get_catalog_card("dupe-1").prices["holofoil"].market == Decimal("2.00")


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


# ---------------------------------------------------------------------------
# upsert_catalog_card_preserving_prices — the depth pass's write (RFC 0003 §7)
#
# The invariant "a depth-pass write never deletes, zeroes or nulls an existing
# price" lives HERE, in the storage layer, rather than in an `if` at the caller.
# These tests are the enforcement: they exercise the repository directly, with
# no depth pass in sight, so the guarantee survives a future second caller.
# ---------------------------------------------------------------------------


def _priceless(card_id="swsh1-1", set_id="swsh1", *, rarity="Rare Holo V",
               name="Celebi V"):
    """An identity-complete card carrying no price band at all.

    This is what ``to_catalog_card`` returns for a perfectly good HTTP 200 whose
    ``pricing`` block is absent, null, or carries only a ``lowPrice`` with a null
    ``marketPrice`` — a case ``tcgdex`` documents as routine, not exceptional.
    """
    return CatalogCard(
        card_id=card_id, name=name, set_id=set_id, set_name="S&S", number="1",
        rarity=rarity, images={"small": "s", "large": "l"}, prices={},
        detail="full", last_synced_at=datetime(2026, 6, 23, 12, 0, 0),
    )


def test_preserving_upsert_keeps_a_stored_band_when_the_incoming_card_has_none(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card(market="9.25")])

    dynamo_repo.upsert_catalog_card_preserving_prices(_priceless(rarity="Reprint"))

    card = dynamo_repo.get_catalog_card("swsh1-1")
    assert card.prices["holofoil"].market == Decimal("9.25")  # never nulled
    assert card.rarity == "Reprint"      # ...and the row IS otherwise updated
    assert card.detail == "full"


def test_preserving_upsert_replaces_the_band_when_the_incoming_card_has_one(dynamo_repo):
    """Preservation must not curdle into immutability: the very next response
    that does carry a price has to land, or the price freezes forever."""
    dynamo_repo.batch_upsert_catalog_cards([_card(market="9.25")])

    dynamo_repo.upsert_catalog_card_preserving_prices(_card(market="2.00"))

    assert dynamo_repo.get_catalog_card("swsh1-1").prices["holofoil"].market == Decimal("2.00")


def test_preserving_upsert_creates_a_row_that_does_not_exist_yet(dynamo_repo):
    """It is an UPSERT: a card the catalog has never seen must still be written,
    priced or not, or a new holding would never get its identity row."""
    dynamo_repo.upsert_catalog_card_preserving_prices(_priceless("swsh1-new"))

    card = dynamo_repo.get_catalog_card("swsh1-new")
    assert card is not None
    assert card.prices == {}
    assert card.rarity == "Rare Holo V"


def test_preserving_upsert_leaves_other_cards_alone(dynamo_repo):
    """It writes one row. Also pins that the GSI key is maintained: an
    `update_item` that skipped `GSI1PK` would leave the row queryable only under
    the set it used to belong to."""
    dynamo_repo.batch_upsert_catalog_cards([_card("a-1", "setA"), _card("a-2", "setA")])

    dynamo_repo.upsert_catalog_card_preserving_prices(_priceless("a-1", "setA"))

    assert dynamo_repo.get_catalog_card("a-2").prices["holofoil"].market == Decimal("12.50")
    assert {c.card_id for c in dynamo_repo.list_cards_by_set("setA")} == {"a-1", "a-2"}


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
    return PricePoint(card_id=card_id, date=d, source="tcgplayer",
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


# ---- catalog reseed lock (RFC 0003 §8) ----
# A second, PARALLEL lock domain from the import lock above -- same
# conditional-write + TTL-expiry semantics, but keyed under its own
# "CATALOGLOCK"/"LOCK" item so a spreadsheet import and a catalog reseed can
# never block each other. Phase 9 wires only the depth-pass side
# (`refresh_held_prices`) to this lock; the reseed side (`seed_catalog.py`)
# stays unwired this session. These tests pin the LOCK's own behavior so the
# eventual `_acquire_lock(key, gen, ttl)` extraction (RFC §8) is safe.


def test_catalog_lock_is_single_flight(dynamo_repo):
    from merlins_collection.services.dynamodb import CatalogReseedInProgressError
    dynamo_repo.acquire_catalog_lock("cgen-A")
    # A second acquire while the lock is held is refused.
    try:
        dynamo_repo.acquire_catalog_lock("cgen-B")
        raised = False
    except CatalogReseedInProgressError:
        raised = True
    assert raised
    # After release, a new run can acquire.
    dynamo_repo.release_catalog_lock("cgen-A")
    dynamo_repo.acquire_catalog_lock("cgen-B")  # no raise
    dynamo_repo.release_catalog_lock("cgen-B")


def test_catalog_lock_reclaims_an_expired_lock(dynamo_repo):
    # A negative TTL stamps `expires_at` in the past at write time, so the lock
    # is already stale for any later acquire attempt -- deterministic, no real
    # sleep or wall-clock mocking required.
    dynamo_repo.acquire_catalog_lock("cgen-A", ttl_seconds=-10)
    dynamo_repo.acquire_catalog_lock("cgen-B")  # reclaims the expired lock; no raise
    dynamo_repo.release_catalog_lock("cgen-B")


def test_catalog_lock_release_is_a_noop_when_the_lock_was_stolen(dynamo_repo):
    from merlins_collection.services.dynamodb import CatalogReseedInProgressError
    dynamo_repo.acquire_catalog_lock("cgen-A", ttl_seconds=-10)
    dynamo_repo.acquire_catalog_lock("cgen-B")  # reclaims; steals the lock from A
    # Releasing under the OLD (stolen) gen must be a silent no-op, not an error,
    # and must NOT clear B's now-live lock.
    dynamo_repo.release_catalog_lock("cgen-A")
    try:
        dynamo_repo.acquire_catalog_lock("cgen-C")
        held = False
    except CatalogReseedInProgressError:
        held = True
    assert held  # B's lock is still in force
    dynamo_repo.release_catalog_lock("cgen-B")


def test_catalog_lock_is_independent_of_the_import_lock(dynamo_repo):
    # RFC 0003 §8: "a second, parallel generation domain, not an extension of
    # the first" -- holding one must never block the other.
    dynamo_repo.acquire_import_lock("igen-A")
    dynamo_repo.acquire_catalog_lock("cgen-A")  # must not raise
    dynamo_repo.release_import_lock("igen-A")
    dynamo_repo.release_catalog_lock("cgen-A")


def test_current_catalog_generation_is_none_on_a_fresh_table(dynamo_repo):
    # No `CATALOGGEN` marker has ever been written (the reseed/`finalize_catalog`
    # writer stays unwired this session), so reading it back must degrade to
    # "no generation" rather than raise.
    assert dynamo_repo.current_catalog_generation() is None


# ---- import-owned data probe (re-import guard) ----

def test_find_import_owned_entity_none_on_empty_table(dynamo_repo):
    assert dynamo_repo.find_import_owned_entity() is None


def test_find_import_owned_entity_ignores_catalog_only_table(dynamo_repo):
    # The ~53k-row catalog (catalog_card + price_point) is NOT import-owned: a
    # seeded-but-never-imported table must still read as "no business data".
    dynamo_repo.batch_upsert_catalog_cards([_card("a-1", "setA"), _card("a-2", "setA")])
    dynamo_repo.append_price_points([_raw_point("a-1", _date(2026, 6, 20), "10")])
    dynamo_repo.set_graded_market_value("a-1", GradingCompany.PSA, Decimal("10"),
                                        Decimal("500"))
    dynamo_repo.append_item_price_point("i-1", _date(2026, 6, 20), Decimal("3"))
    assert dynamo_repo.find_import_owned_entity() is None


def test_find_import_owned_entity_ignores_the_import_lock(dynamo_repo):
    dynamo_repo.acquire_import_lock("gen-A")
    assert dynamo_repo.find_import_owned_entity() is None
    dynamo_repo.release_import_lock("gen-A")


def test_find_import_owned_entity_detects_each_business_partition(dynamo_repo):
    from merlins_collection.models.business import (
        BalanceSheetLine,
        BalanceSheetSection,
        BalanceSheetSnapshot,
        Payout,
    )

    def _snapshot():
        # non-frozen: a frozen baseline is deliberately never swept by a commit,
        # so it could not be cleared between probes.
        return BalanceSheetSnapshot(
            snapshot_id="current", label="current", frozen=False,
            lines=[BalanceSheetLine(section=BalanceSheetSection.ASSET,
                                    label="Inventory", amount=Decimal("100"))])

    writes = {
        "inventory_item": lambda: dynamo_repo.put_inventory_item(_raw_item()),
        "show": lambda: dynamo_repo.put_show(
            Show(show_id="s1", name="Mint City", date=_date(2026, 3, 8))),
        "debt": lambda: dynamo_repo.put_debt(_debt("Colin")),
        "payout": lambda: dynamo_repo.put_payout(
            Payout(event="E1", partner="Casey", amount=Decimal("40"))),
        "consignor": lambda: dynamo_repo.put_consignor(
            Consignor(consignor_id="c1", name="Rylan")),
        "cash_account": lambda: dynamo_repo.put_cash_account(
            CashAccount(account="venmo", balance=Decimal("10"))),
        "balance_sheet_snapshot": lambda: dynamo_repo.put_balance_sheet(_snapshot()),
    }
    for entity, write in writes.items():
        assert dynamo_repo.find_import_owned_entity() is None, entity
        write()
        assert dynamo_repo.find_import_owned_entity() == entity
        # Clear it again so the next entity is probed in isolation.
        dynamo_repo.finalize_import("no-such-gen", committed=True)
    assert dynamo_repo.find_import_owned_entity() is None


def test_find_import_owned_entity_does_not_scan_the_table(dynamo_repo):
    # The probe must be partition-bounded: a full table scan would read the whole
    # ~53k-row catalog on every import.
    dynamo_repo.batch_upsert_catalog_cards([_card()])
    scans = []
    original_scan = dynamo_repo._table.scan

    def _spy(**kwargs):
        scans.append(kwargs)
        return original_scan(**kwargs)

    dynamo_repo._table.scan = _spy
    assert dynamo_repo.find_import_owned_entity() is None
    assert scans == []


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


# ======================= scoped guard + scoped sweep =========================
# A Singles-only import must be able to ask "does inventory/transaction data
# already exist?" and to sweep ONLY inventory/transaction on commit, without the
# shows/debts/payouts/consignors/config rows it never touches being probed,
# refused over, or deleted. Both knobs sentinel-default to today's full scope.

_SCOPED = frozenset({"inventory_item", "transaction"})


def _seed_other_business_data(repo):
    """One row of every import-owned entity a Singles-only run must NOT touch."""
    from merlins_collection.models.business import (
        BalanceSheetLine,
        BalanceSheetSection,
        BalanceSheetSnapshot,
        Payout,
    )
    repo.put_show(Show(show_id="s1", name="Mint City", date=_date(2026, 3, 8)))
    repo.put_debt(_debt("Colin"))
    repo.put_payout(Payout(event="E1", partner="Casey", amount=Decimal("40")))
    repo.put_consignor(Consignor(consignor_id="c1", name="Rylan"))
    repo.put_cash_account(CashAccount(account="venmo", balance=Decimal("10")))
    repo.put_payment_method(PaymentMethod(method="cash"))
    repo.put_buying_policy(BuyingPolicy(product_type="raw", cash_pct_min=Decimal("60")))
    repo.put_balance_sheet(BalanceSheetSnapshot(
        snapshot_id="current", label="current", frozen=False,
        lines=[BalanceSheetLine(section=BalanceSheetSection.ASSET,
                                label="Inventory", amount=Decimal("100"))]))


def test_find_import_owned_entity_scoped_ignores_out_of_scope_entities(dynamo_repo):
    _seed_other_business_data(dynamo_repo)
    # Unscoped, this table plainly holds business data...
    assert dynamo_repo.find_import_owned_entity() is not None
    # ...but a Singles-only run asks only about inventory/transactions.
    assert dynamo_repo.find_import_owned_entity(entities=_SCOPED) is None


def test_find_import_owned_entity_scoped_still_detects_in_scope_entities(dynamo_repo):
    dynamo_repo.put_inventory_item(_raw_item())
    assert dynamo_repo.find_import_owned_entity(entities=_SCOPED) == "inventory_item"


def test_find_import_owned_entity_scoped_does_not_query_other_partitions(dynamo_repo):
    # "Not swept" is not enough — the out-of-scope partitions must not even be READ.
    _seed_other_business_data(dynamo_repo)
    queried, original_query = [], dynamo_repo._table.query

    def _spy(**kwargs):
        queried.append(kwargs["KeyConditionExpression"].get_expression()["values"][1])
        return original_query(**kwargs)

    dynamo_repo._table.query = _spy
    assert dynamo_repo.find_import_owned_entity(entities=_SCOPED) is None
    assert queried  # the probe really ran
    assert set(queried) == {f"INV#{b}" for b in range(INVENTORY_SHARD_COUNT)}


def test_find_import_owned_entity_rejects_an_unknown_entity_name(dynamo_repo):
    with pytest.raises(ValueError, match="not import-owned"):
        dynamo_repo.find_import_owned_entity(entities={"catalog_card"})


def test_find_import_owned_entity_rejects_a_scope_with_no_probeable_partition(
        dynamo_repo):
    # The month-partitioned ledgers are never probed directly, so a scope naming
    # ONLY one of them would silently always answer "no data" — refuse instead.
    dynamo_repo.put_inventory_item(_raw_item())
    with pytest.raises(ValueError, match="no probeable partition"):
        dynamo_repo.find_import_owned_entity(entities={"transaction"})
    with pytest.raises(ValueError, match="no probeable partition"):
        dynamo_repo.find_import_owned_entity(entities=frozenset())


def test_entity_partition_map_matches_the_unscoped_probe(dynamo_repo):
    # The scoped map and the unscoped partition list must not drift: every
    # import-owned entity has an entry, and their union is exactly what an
    # unscoped probe reads. An entity added without an entry fails here.
    repo = type(dynamo_repo)
    assert set(repo._ENTITY_PARTITIONS) == set(repo._IMPORT_OWNED_ENTITIES)
    union = {p for ps in repo._ENTITY_PARTITIONS.values() for p in ps}
    unscoped = {f"INV#{b}" for b in range(INVENTORY_SHARD_COUNT)}
    unscoped |= set(repo._BUSINESS_PARTITIONS)
    assert union == unscoped


def test_finalize_import_entity_scope_leaves_other_entities_alone(dynamo_repo):
    # Prior generation: everything. New generation: inventory only.
    dynamo_repo.set_import_generation("gen-old")
    _seed_other_business_data(dynamo_repo)
    dynamo_repo.put_inventory_item(_raw_item(card_id="old-1"))
    dynamo_repo.finalize_import("gen-old", committed=True)

    dynamo_repo.set_import_generation("gen-new")
    dynamo_repo.put_inventory_item(_raw_item(card_id="new-1"))
    removed = dynamo_repo.finalize_import("gen-new", committed=True,
                                          entity_scope=_SCOPED)
    dynamo_repo.set_import_generation(None)

    assert removed == 1  # only the prior generation's inventory row
    assert [i.card_id for i in dynamo_repo.list_inventory()] == ["new-1"]
    # Everything outside the scope survived, gen-old tag and all.
    assert len(dynamo_repo.list_shows()) == 1
    assert len(dynamo_repo.list_debts()) == 1
    assert len(dynamo_repo.list_payouts()) == 1
    assert len(dynamo_repo.list_consignors()) == 1
    assert len(dynamo_repo.list_cash_accounts()) == 1
    assert len(dynamo_repo.list_payment_methods()) == 1
    assert len(dynamo_repo.list_buying_policies()) == 1
    assert len(dynamo_repo.list_balance_sheets()) == 1


def test_finalize_import_without_a_scope_still_sweeps_everything(dynamo_repo):
    # REGRESSION GUARD (mirrors the scoped test above exactly, minus the kwarg):
    # omitting entity_scope must keep today's all-or-nothing swap behavior.
    dynamo_repo.set_import_generation("gen-old")
    _seed_other_business_data(dynamo_repo)
    dynamo_repo.put_inventory_item(_raw_item(card_id="old-1"))
    dynamo_repo.finalize_import("gen-old", committed=True)

    dynamo_repo.set_import_generation("gen-new")
    dynamo_repo.put_inventory_item(_raw_item(card_id="new-1"))
    dynamo_repo.finalize_import("gen-new", committed=True)
    dynamo_repo.set_import_generation(None)

    assert [i.card_id for i in dynamo_repo.list_inventory()] == ["new-1"]
    assert dynamo_repo.list_shows() == []
    assert dynamo_repo.list_debts() == []
    assert dynamo_repo.list_payouts() == []
    assert dynamo_repo.list_consignors() == []
    assert dynamo_repo.list_cash_accounts() == []
    assert dynamo_repo.list_payment_methods() == []
    assert dynamo_repo.list_buying_policies() == []
    assert dynamo_repo.list_balance_sheets() == []


def test_finalize_import_entity_scope_also_scopes_a_rollback(dynamo_repo):
    # A scoped ROLLBACK must not delete this generation's out-of-scope rows
    # either — it only unwinds what the scoped run itself was allowed to write.
    dynamo_repo.set_import_generation("gen-x")
    _seed_other_business_data(dynamo_repo)
    dynamo_repo.put_inventory_item(_raw_item(card_id="doomed"))
    removed = dynamo_repo.finalize_import("gen-x", committed=False,
                                          entity_scope=_SCOPED)
    dynamo_repo.set_import_generation(None)

    assert removed == 1
    assert dynamo_repo.list_inventory() == []
    assert len(dynamo_repo.list_shows()) == 1


def test_finalize_import_rejects_a_bad_entity_scope(dynamo_repo):
    with pytest.raises(ValueError, match="not import-owned"):
        dynamo_repo.finalize_import("gen-x", committed=True,
                                    entity_scope={"catalog_card"})
    with pytest.raises(ValueError, match="empty"):
        dynamo_repo.finalize_import("gen-x", committed=True,
                                    entity_scope=frozenset())


# ---- float -> Decimal coercion -------------------------------------------
# DynamoDB has no float type and boto3 refuses one outright ("Float types are
# not supported. Use Decimal types instead."). Every value we write therefore
# has to be a Decimal by the time it reaches `put_item`. Pydantic models give
# us that for free, but the sell/buy/trade session routers store RAW REQUEST
# JSON, where a price arrives as a Python float. That path 500'd in production
# on `POST /admin/sales/{id}/items` -- these tests pin the coercion that fixes
# it. The tests above never caught it because they all send prices as STRINGS.

def test_serialize_converts_float_to_decimal():
    from merlins_collection.services.dynamodb import _serialize

    assert _serialize(45.0) == Decimal("45.0")
    assert isinstance(_serialize(45.0), Decimal)


def test_serialize_float_conversion_goes_through_str_not_binary():
    # Decimal(0.1) is 0.1000000000000000055511151231257827..., which would
    # persist a price that no longer round-trips. Decimal(str(0.1)) is "0.1".
    from merlins_collection.services.dynamodb import _serialize

    assert _serialize(0.1) == Decimal("0.1")
    assert _serialize(45.67) == Decimal("45.67")


def test_serialize_converts_floats_nested_in_dicts_and_lists():
    from merlins_collection.services.dynamodb import _serialize

    result = _serialize({"items": [{"agreed_price": 45.5, "discount_pct": 10.0}]})
    price = result["items"][0]["agreed_price"]
    assert isinstance(price, Decimal) and price == Decimal("45.5")
    assert isinstance(result["items"][0]["discount_pct"], Decimal)


def test_serialize_leaves_ints_and_bools_alone():
    # bool is a subclass of int, not of float, but DynamoDB stores it as BOOL
    # and turning it into Decimal("1") would silently change the stored type.
    from merlins_collection.services.dynamodb import _serialize

    assert _serialize(True) is True
    assert _serialize(False) is False
    assert _serialize(7) == 7 and isinstance(_serialize(7), int)


def test_serialize_rejects_nan_and_infinity():
    # Python's json module parses the bare literals NaN/Infinity, so these can
    # reach us from a request body. DynamoDB cannot store either; failing here
    # names the offending value instead of surfacing a boto3 error two frames on.
    from merlins_collection.services.dynamodb import _serialize

    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            _serialize(bad)


def test_put_sell_session_accepts_float_prices(dynamo_repo):
    # The exact production payload: the Sell page sends agreed_price as a JSON
    # number (sell/page.tsx builds it with parseFloat), so it lands as a float.
    dynamo_repo.put_sell_session({
        "sell_id": "sell-float-1",
        "status": "draft",
        "created_at": "2026-08-07T00:00:00",
        "items": [{"item_id": "card-1", "agreed_price": 45.5,
                   "original_price": 60.0, "discount_pct": 24.17}],
    })

    stored = dynamo_repo.get_sell_session("sell-float-1")
    assert stored["items"][0]["agreed_price"] == Decimal("45.5")


# --- RFC 0009 T1: the cert pointer row ------------------------------------
#
# "Do I already own this slab?" must be an O(1) point read. CLAUDE.md's Ops
# section records what a full-table scan on a request path already cost this
# project once.
#
# Staleness is handled on the READ side: the pointer is advisory, and
# ``get_item_id_by_cert`` re-reads the item and confirms it still claims that
# cert. The alternative -- sweeping the old pointer on update -- would put an
# extra ``get_item`` on EVERY inventory write, including the bulk import loop,
# and still would not cover a deleted item.


def _graded_item(cert_number="12345678", company=GradingCompany.PSA, **over):
    kw = dict(
        card_id="swsh1-1", cost_basis=Decimal("300"), acquired_at=_date(2026, 1, 1),
        company=company, grade=Decimal("10"), cert_number=cert_number,
    )
    kw.update(over)
    return GradedInventoryItem(**kw)


def test_saving_a_graded_item_writes_a_resolvable_cert_pointer(dynamo_repo):
    item = _graded_item()
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_item_id_by_cert("PSA", "12345678") == item.item_id


def test_get_item_id_by_cert_returns_none_for_unknown_cert(dynamo_repo):
    assert dynamo_repo.get_item_id_by_cert("PSA", "99999999") is None


def _cert_pointer_rows(repo):
    """Every cert_pointer row in the table. Asserted directly rather than through
    the reader, because "the lookup returns None" is also what a WRONG pointer
    looks like -- these two tests are about nothing being written at all."""
    return [i for i in repo._table.scan().get("Items", [])
            if i.get("entity") == "cert_pointer"]


def test_saving_a_raw_item_writes_no_cert_pointer(dynamo_repo):
    """A raw single has no cert. Nothing should land in the CERT# partition."""
    dynamo_repo.put_inventory_item(_raw_item())
    assert _cert_pointer_rows(dynamo_repo) == []


@pytest.mark.parametrize("blank", ["", "   "])
def test_saving_a_graded_item_with_a_blank_cert_writes_no_pointer(dynamo_repo, blank):
    """An unverified/manual slab may have no cert yet. Writing ``CERT#PSA#``
    would make every such slab a duplicate of every other."""
    dynamo_repo.put_inventory_item(_graded_item(cert_number=blank))
    assert _cert_pointer_rows(dynamo_repo) == []


def test_editing_a_cert_makes_the_old_pointer_stop_resolving(dynamo_repo):
    """The stale-pointer case. Re-pointing a slab at its real cert leaves the
    old pointer row behind; the reader must not report the item under a cert it
    no longer claims, or the owner gets a false "duplicate" on a cert they
    legitimately re-enter."""
    item = _graded_item(cert_number="11111111")
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_item_id_by_cert("PSA", "11111111") == item.item_id

    corrected = item.model_copy(update={"cert_number": "22222222"})
    dynamo_repo.put_inventory_item(corrected)

    assert dynamo_repo.get_item_id_by_cert("PSA", "11111111") is None
    assert dynamo_repo.get_item_id_by_cert("PSA", "22222222") == item.item_id


def test_deleted_item_stops_resolving_by_cert(dynamo_repo):
    """``delete_inventory_item`` does not know about the pointer. Reader-side
    verification is what keeps the orphan harmless."""
    item = _graded_item(cert_number="33333333")
    dynamo_repo.put_inventory_item(item)
    dynamo_repo.delete_inventory_item(item.item_id)
    assert dynamo_repo.get_item_id_by_cert("PSA", "33333333") is None


def test_cert_pointer_is_scoped_by_grading_company(dynamo_repo):
    """The same cert digits can exist at two graders; they are different slabs."""
    psa = _graded_item(cert_number="44444444", company=GradingCompany.PSA)
    cgc = _graded_item(cert_number="44444444", company=GradingCompany.CGC)
    dynamo_repo.put_inventory_item(psa)
    dynamo_repo.put_inventory_item(cgc)
    assert dynamo_repo.get_item_id_by_cert("PSA", "44444444") == psa.item_id
    assert dynamo_repo.get_item_id_by_cert("CGC", "44444444") == cgc.item_id


def test_cert_lookup_normalizes_company_case_and_surrounding_space(dynamo_repo):
    """The lookup is fed by a query string and a hand-typed scan bar, so the
    read side must normalize exactly as the write side did or it silently misses."""
    item = _graded_item(cert_number="55555555")
    dynamo_repo.put_inventory_item(item)
    assert dynamo_repo.get_item_id_by_cert("psa", " 55555555 ") == item.item_id


def test_rebuying_a_sold_slab_points_at_the_newest_item(dynamo_repo):
    """Two items can legitimately share a cert over time -- you sell a slab and
    buy it back. The pointer holds the MOST RECENT item id."""
    old = _graded_item(cert_number="66666666")
    dynamo_repo.put_inventory_item(old)
    new = _graded_item(cert_number="66666666")
    dynamo_repo.put_inventory_item(new)
    assert dynamo_repo.get_item_id_by_cert("PSA", "66666666") == new.item_id
