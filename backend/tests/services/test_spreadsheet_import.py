from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import Show
from merlins_collection.models.inventory import Condition, ConditionModifier
from merlins_collection.services.spreadsheet_import import (
    ImportContext,
    deterministic_id,
    import_singles,
    map_location,
    nearest_show_id,
    parse_bool,
    parse_condition,
    parse_date,
    parse_money,
)


def test_parse_money():
    assert parse_money("$1,234.56") == Decimal("1234.56")
    assert parse_money("40") == Decimal("40")
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("-") is None


def test_parse_date():
    assert parse_date("3/7/2026") == date(2026, 3, 7)
    assert parse_date("2026-03-07") == date(2026, 3, 7)
    assert parse_date("") is None


def test_parse_bool():
    assert parse_bool("Yes") and parse_bool("y") and parse_bool("TRUE") and parse_bool("x")
    assert not parse_bool("No") and not parse_bool("") and not parse_bool(None)


def test_parse_condition():
    assert parse_condition("LP +") == (Condition.LP, ConditionModifier.PLUS)
    assert parse_condition("LP-") == (Condition.LP, ConditionModifier.MINUS)
    assert parse_condition("NM") == (Condition.NM, None)
    assert parse_condition("D") == (Condition.DMG, None)
    with pytest.raises(ValueError):
        parse_condition("Mint-ish")


def test_map_location():
    assert map_location("Glass")["location"] == "glass"
    assert map_location("Sealed")["factory_sealed"] is True
    assert map_location("Hold")["status"] == "on_hold"
    assert map_location("Lost")["status"] == "lost"
    assert map_location("Grading")["status"] == "out_for_grading"
    fd = map_location("For David")
    assert fd["status"] == "on_hold" and fd["notes_extra"] == "For David"


def test_deterministic_id_stable_and_distinct():
    row = {"Name": "Pikachu", "Sold": "40"}
    assert deterministic_id("Singles", row) == deterministic_id("Singles", row)
    assert deterministic_id("Singles", row) != deterministic_id("Slabs", row)
    assert len(deterministic_id("Singles", row)) == 26


def test_nearest_show_id():
    shows = [Show(show_id="a", name="A", date=date(2026, 3, 1)),
             Show(show_id="b", name="B", date=date(2026, 3, 20))]
    assert nearest_show_id(date(2026, 3, 5), shows) == "a"
    assert nearest_show_id(date(2026, 3, 18), shows) == "b"
    assert nearest_show_id(date(2026, 3, 5), []) is None


# ---- Singles tab ----

def _singles_row(**over):
    row = {"Date": "1/5/2026", "Location": "Glass", "Name": "Pikachu", "Card #": "25",
           "Condition": "LP +", "Market @ purchase": "$12.00", "Amount Paid": "$8.00",
           "Percent": "", "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "",
           "Sticker": "$15.00", "Notes": "", "TCG Link": "http://example.com/25",
           "# of Show days had": "", "Venmo Fees": ""}
    row.update(over)
    return row


def test_import_singles_unsold_row(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row()], ctx)
    assert summary == {"imported": 1, "sales": 0, "skipped": 0, "needs_review": 1}
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "raw"
    assert item.condition is Condition.LP
    assert item.condition_modifier is ConditionModifier.PLUS
    assert item.location == "glass"
    assert item.cost_basis == Decimal("8.00")
    assert item.market_value_at_purchase == Decimal("12.00")
    assert item.listed_price == Decimal("15.00")
    assert item.tcg_url == "http://example.com/25"
    assert item.card_id is None and item.needs_review is True  # no catalog match
    assert item.notes == "Pikachu #25"  # sheet identity preserved for review


def test_import_singles_sold_row_writes_sale_txn(dynamo_repo):
    show = Show(show_id="s1", name="Show", date=date(2026, 3, 8))
    ctx = ImportContext(repo=dynamo_repo, shows=[show])
    row = _singles_row(Sold="$40.00", **{"Date Sold": "3/7/2026", "Venmo?": "Yes",
                                         "Venmo Fees": "$0.86"})
    summary = import_singles([row], ctx)
    assert summary["sales"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "sold"
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.amount == Decimal("40.00")
    assert txn.payment_method == "venmo"
    assert txn.fee == Decimal("0.86")
    assert txn.show_id == "s1"          # nearest show
    assert txn.item_id == item.item_id


def test_import_singles_is_idempotent(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    rows = [_singles_row()]
    import_singles(rows, ctx)
    import_singles(rows, ctx)
    assert len(dynamo_repo.list_inventory()) == 1


def test_import_singles_skips_malformed_row(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row(Condition="???")], ctx)
    assert summary["skipped"] == 1
    assert dynamo_repo.list_inventory() == []
