from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import Show
from merlins_collection.models.inventory import Condition, ConditionModifier
from merlins_collection.services.spreadsheet_import import (
    ImportContext,
    deterministic_id,
    import_bulk,
    import_buying_guidelines,
    import_cash,
    import_consignments,
    import_sealed,
    import_shows,
    import_singles,
    import_slabs,
    map_location,
    nearest_show_id,
    parse_bool,
    parse_condition,
    parse_date,
    parse_money,
    run_import,
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


# ---- Slabs / Sealed / Bulk tabs ----

def test_import_slabs_defaults_psa_needs_review(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date Recieved": "1/5/2026", "Name": "Charizard", "Set": "Base",
           "card#": "4", "Grade": "9.5", "Cert #": "12345678",
           "Market @ purchase": "$300", "Amount Paid": "$250", "Percentage": "",
           "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "", "Sticker": "",
           "Current Market": "", "# Of Show Days had": "", "Venmo Fees": ""}
    summary = import_slabs([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "graded"
    assert item.company.value == "PSA"
    assert item.grade == Decimal("9.5")
    assert item.cert_number == "12345678"
    assert item.needs_review is True


def test_import_sealed_maps_product_type_and_hold(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date": "1/5/2026", "Name": "Evolving Skies Booster Box",
           "Market @ time of purchase": "$400", "Amount Paid": "$350",
           "Percentage": "", "Sold": "", "Date Sold": "", "Venmo?": "", "Net": "",
           "Sticker": "", "Current Market (2/25)": "", "Hold": "TRUE",
           "TCG Link": "", "of days had": "", "Venmo Fees": ""}
    import_sealed([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "sealed"
    assert item.product_type.value == "booster_box"
    assert item.status.value == "on_hold"


def test_import_bulk_sold_lot(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Name": "5k bulk lot", "Amount Paid": "$50", "Sold": "$80",
           "Date Sold": "3/7/2026", "Venmo?": "No", "Net": "", "Venmo Fees": ""}
    summary = import_bulk([row], ctx)
    assert summary == {"imported": 1, "sales": 1, "skipped": 0, "needs_review": 0}
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.category.value == "bulk"
    assert txn.payment_method == "cash"


# ---- Shows / Consignments / Cash / Buying Guidelines / run_import ----

def test_import_shows_builds_context(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Day": "3/8/2026", "Show": "Mint City", "Goal": "$500",
             "Cash at Beginning of Every Show Day": "$200",
             "Assets At start of every show day": "",
             "Inventory Value at Beginning of show": "$3,000"},
            {"Day": "", "Show": "junk row"}]
    summary = import_shows(rows, ctx)
    assert summary == {"imported": 1, "skipped": 1}
    [show] = dynamo_repo.list_shows()
    assert show.name == "Mint City"
    assert show.sales_goal == Decimal("500")
    assert show.inventory_value_at_start == Decimal("3000")
    assert ctx.shows == [show]


def test_import_consignments_creates_consignor_terms_and_payout(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date recieved": "2/1/2026", "Card Name": "Umbreon VMAX", "Condition": "NM",
           "Slab": "", "Card #": "215", "Amount we get": "", "Sold": "$100",
           "Date Sold": "3/7/2026", "Venmo?": "No", "Net": "", "Persons Name": "David",
           "Market": "$110", "Minimum": "$90", "To payout": "$80",
           "Percentage we get": "20%", "# of Show Days": "", "Paid Out?": "No",
           "Sold/Returned": "Sold", "Venmo Fees": ""}
    summary = import_consignments([row], ctx)
    assert summary["imported"] == 1 and summary["sales"] == 1
    [consignor] = dynamo_repo.list_consignors()
    assert consignor.name == "David"
    [item] = dynamo_repo.list_inventory()
    assert item.consignment.consignor_id == consignor.consignor_id
    assert item.consignment.split_percent == Decimal("20")
    assert item.consignment.minimum_price == Decimal("90")
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.category.value == "consignment"
    assert txn.consignor_payout == Decimal("80")


def test_import_cash_and_buying_guidelines(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    import_cash([{"Type": "Venmo", "Amount": "$321.50"},
                 {"Type": "Total", "Amount": "$999"}], ctx)
    accounts = dynamo_repo.list_cash_accounts()
    assert [a.account for a in accounts] == ["venmo"]
    import_buying_guidelines([{"Product Type": "Slabs", "Cash % Min": "60%",
                               "Cash % Max": "75%", "Trade % Min": "70%",
                               "Trade % Max": "85%"}], ctx)
    [policy] = dynamo_repo.list_buying_policies()
    assert policy.product_type == "slabs"
    assert policy.cash_pct_max == Decimal("75")


def test_run_import_end_to_end(tmp_path, dynamo_repo):
    (tmp_path / "Vending Net.csv").write_text(
        "Day,Show,Goal\n3/8/2026,Mint City,$500\n", encoding="utf-8")
    (tmp_path / "Bulk.csv").write_text(
        "Name,Amount Paid,Sold,Date Sold,Venmo?,Net,Venmo Fees\n"
        "bulk lot,$50,$80,3/7/2026,No,,\n", encoding="utf-8")
    summaries = run_import(tmp_path, dynamo_repo)
    assert summaries["Vending Net"]["imported"] == 1
    assert summaries["Bulk"]["sales"] == 1
    # the bulk sale matched the imported show
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.show_id is not None
    # payment methods were seeded
    assert dynamo_repo.get_payment_method("venmo") is not None
