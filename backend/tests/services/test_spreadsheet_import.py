from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import Consignor, Show
from merlins_collection.models.inventory import Condition, ConditionModifier, Language
from merlins_collection.services.spreadsheet_import import (
    SINGLES_ONLY_CSV_NAME,
    ExistingBusinessDataError,
    ImportContext,
    _match_card,
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
    parse_language,
    parse_money,
    run_import,
    run_singles_only_import,
    seed_payment_methods,
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


def test_import_singles_disambiguates_ambiguous_match_via_tcg_url(dynamo_repo):
    """(D) The Singles tab has no Set column, so "Dragonair #181" — printed in two
    sets — used to go to review. Its TCGplayer link names the set, so the import
    now narrows to the one card: the item links (and gets an image) instead of
    being flagged for a human."""
    card_a = _catalog_card(card_id="sv3pt5-181", name="Dragonair",
                           set_name="Scarlet & Violet 151", number="181")
    card_b = _catalog_card(card_id="base1-181", name="Dragonair",
                           set_name="Base Set", number="181")
    ctx = ImportContext(repo=dynamo_repo,
                        catalog_index=_normalized_index([card_a, card_b]))
    row = _singles_row(Name="Dragonair", **{
        "Card #": "181/165",
        "TCG Link": ("https://www.tcgplayer.com/product/517020/"
                     "pokemon-sv-scarlet-and-violet-151-dragonair-181-165?Condition=Near+Mint"),
    })
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "sv3pt5-181"
    assert item.needs_review is False


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


def test_import_singles_each_call_creates_fresh_records(dynamo_repo):
    # Row identity is a fresh ULID per unit; idempotency is a run_import concern
    # (load-then-swap generation replace), NOT importer-level dedup. Two calls =>
    # two records.
    ctx = ImportContext(repo=dynamo_repo)
    rows = [_singles_row()]
    import_singles(rows, ctx)
    import_singles(rows, ctx)
    assert len(dynamo_repo.list_inventory()) == 2


def test_import_singles_skips_malformed_row(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row(Condition="???")], ctx)
    assert summary["skipped"] == 1
    assert dynamo_repo.list_inventory() == []


# ---- Slabs / Sealed / Bulk tabs ----

def test_import_slabs_defaults_psa_and_flags_when_unmatched(dynamo_repo):
    """Company still defaults to PSA. With no catalog to match against, the card
    is unidentified, so the slab is flagged — but now because it is UNMATCHED (C),
    not merely because it is a slab."""
    ctx = ImportContext(repo=dynamo_repo)  # empty catalog -> no match
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
    assert item.card_id is None and item.needs_review is True  # unmatched -> flagged


def test_import_slabs_matched_slab_with_cert_is_not_flagged(dynamo_repo):
    """(C) A slab whose card the catalog resolves and that carries a cert number
    no longer needs a human — the blanket 'every slab is review' rule is gone."""
    card = _catalog_card(card_id="base1-4", name="Charizard",
                         set_name="Base Set", number="4")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = {"Date Recieved": "1/5/2026", "Name": "Charizard", "Set": "Base Set",
           "card#": "4", "Grade": "9.5", "Cert #": "12345678", "Amount Paid": "$250"}
    summary = import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "base1-4"
    assert item.needs_review is False
    assert summary["needs_review"] == 0


def test_import_slabs_matched_slab_without_cert_is_flagged(dynamo_repo):
    """(C) The card resolved, but a missing cert number is still worth a look."""
    card = _catalog_card(card_id="base1-4", name="Charizard",
                         set_name="Base Set", number="4")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = {"Date Recieved": "1/5/2026", "Name": "Charizard", "Set": "Base Set",
           "card#": "4", "Grade": "9.5", "Cert #": "", "Amount Paid": "$250"}
    import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "base1-4"
    assert item.cert_number == "unknown" and item.needs_review is True


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


def test_import_populates_show_venue_city_when_columns_present(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Day": "8/14/2026", "Show": "Seattle Trading Card Con",
             "Venue": "Convention Center", "City": "Seattle, WA"}]
    import_shows(rows, ctx)
    [show] = dynamo_repo.list_shows()
    assert show.venue == "Convention Center"
    assert show.city == "Seattle, WA"


def test_import_leaves_show_venue_city_none_when_absent(dynamo_repo):
    # The historical "Show Fees" ledger has no structured venue/city columns, so
    # nothing is invented — the fields stay None (no free-text parsing).
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Day": "3/8/2026", "Show": "Mint City", "Goal": "$500"}]
    import_shows(rows, ctx)
    [show] = dynamo_repo.list_shows()
    assert show.venue is None
    assert show.city is None


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
    assert item.consignment.split_percent == Decimal("0.20")  # 20% stored as a fraction
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


# ---- real-workbook header aliasing (RED) ----
# These feed the ACTUAL headers from the 2026 tracker, which differ from the
# importer's assumed names. Headers carry dates ("updated 7/16", "(2/25)") that
# change yearly, so the fix must normalize/alias rather than hard-code strings.

def test_singles_reads_dated_sticker_header(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = _singles_row()
    del row["Sticker"]
    row["Sticker updated 7/16"] = "$15.00"  # real header
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.listed_price == Decimal("15.00")


def test_slabs_reads_verbose_name_and_market_headers(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date Recieved": "1/5/2026",
           "Name (pkm + rarity + language )": "Charizard",  # real header
           "Set": "Base", "card#": "4", "Grade": "9.5", "Cert #": "12345678",
           "Market @ time of purchase": "$300",  # real header (not "@ purchase")
           "Amount Paid": "$250", "Sold": "", "Date Sold": "", "Venmo?": "",
           "Sticker": "", "Current Market": "", "Venmo Fees": ""}
    summary = import_slabs([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.market_value_at_purchase == Decimal("300")
    assert "Charizard" in (item.notes or "")


def test_sealed_reads_column1_date_header(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Column 1": "1/5/2026",  # real date header on the Sealed tab
           "Name": "Evolving Skies Booster Box",
           "Market @ time of purchase": "$400", "Amount Paid": "$350",
           "Sold": "", "Date Sold": "", "Venmo?": "", "Sticker": "",
           "Hold": "", "TCG Link": "", "Venmo Fees": ""}
    import_sealed([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.acquired_at == date(2026, 1, 5)


def test_shows_read_real_cash_and_inventory_headers(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Day": "3/8/2026", "Show": "Mint City", "Goal": "$500",
           "Cash at Beginning of Show": "$200",  # real (not "...Every Show Day")
           "Inventory Value heading into the show": "$3,000"}  # real header
    import_shows([row], ctx)
    [show] = dynamo_repo.list_shows()
    assert show.cash_at_start == Decimal("200")
    assert show.inventory_value_at_start == Decimal("3000")


def test_buying_guidelines_tolerates_leading_space_header(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {" Product Type": "Slabs", "Cash % Min": "60%", "Cash % Max": "75%",
           "Trade % Min": "70%", "Trade % Max": "85%"}  # note leading space
    import_buying_guidelines([row], ctx)
    [policy] = dynamo_repo.list_buying_policies()
    assert policy.product_type == "slabs"


def test_consignments_reads_date_sold_or_returned_header(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date recieved": "2/1/2026", "Card Name": "Umbreon VMAX",
           "Condition": "NM", "Slab": "", "Card #": "215", "Sold": "$100",
           "Date Sold or Returned": "3/7/2026",  # real header (not "Date Sold")
           "Venmo?": "No", "Persons Name": "David", "Market": "$110",
           "Minimum": "$90", "To payout": "$80", "Percentage we get": "5%",
           "Paid Out?": "No", "Sold/Returned": "Sold", "Venmo Fees": ""}
    summary = import_consignments([row], ctx)
    assert summary["sales"] == 1
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.date == date(2026, 3, 7)


# ---- consignment split as a fraction + payment-method coverage (RED) ----
# The real sheet stores "Percentage we get" as a fraction (0.05 = a 5% cut);
# the consignor is owed sold * (1 - split). Payments span more than venmo/cash.

def _consignment_row(**over):
    row = {"Date recieved": "2/1/2026", "Card Name": "Umbreon", "Condition": "NM",
           "Slab": "", "Card #": "1", "Sold": "", "Persons Name": "David",
           "Market": "$100", "Minimum": "$90", "Paid Out?": "No",
           "Sold/Returned": "", "Venmo?": "No", "Percentage we get": "0.05"}
    row.update(over)
    return row


def test_consignment_percentage_stored_as_fraction(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    import_consignments([_consignment_row(**{"Percentage we get": "5%"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.consignment.split_percent == Decimal("0.05")


def test_consignment_payout_defaults_to_sold_times_one_minus_split(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = _consignment_row(Sold="$100", **{"Date Sold or Returned": "3/7/2026",
                                           "Sold/Returned": "Sold",
                                           "Percentage we get": "0.05"})
    del row["Paid Out?"]  # keep it simple; no "To payout" provided -> compute it
    row["Paid Out?"] = "No"
    import_consignments([row], ctx)
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.consignor_payout == Decimal("95.00")


def test_seed_payment_methods_covers_all_sheet_platforms(dynamo_repo):
    seed_payment_methods(dynamo_repo)
    for method in ("venmo", "cash", "card", "bank", "trade", "cashapp",
                   "zelle", "reimbursed"):
        assert dynamo_repo.get_payment_method(method) is not None, method


def test_run_import_end_to_end(tmp_path, dynamo_repo):
    (tmp_path / "Vending Net.csv").write_text(
        "Day,Show,Goal\n3/8/2026,Mint City,$500\n", encoding="utf-8")
    (tmp_path / "Bulk.csv").write_text(
        "Name,Amount Paid,Sold,Date Sold,Venmo?,Net,Venmo Fees\n"
        "bulk lot,$50,$80,3/7/2026,No,,\n", encoding="utf-8")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["Vending Net"]["imported"] == 1
    assert summaries["Bulk"]["sales"] == 1
    # the bulk sale matched the imported show
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.show_id is not None
    # payment methods were seeded
    assert dynamo_repo.get_payment_method("venmo") is not None


# ---- expense tabs (Show Fees / Other COGS / Marketing / Supplies / Wages /
#      Employee Expenses) all land in the one Expense ledger ----

def test_import_show_fees_links_nearest_show_and_signs_amount(dynamo_repo):
    from merlins_collection.models.business import ExpenseCategory
    from merlins_collection.services.spreadsheet_import import import_expenses
    show = Show(show_id="s1", name="Cardboard Diamonds", date=date(2026, 1, 10))
    ctx = ImportContext(repo=dynamo_repo, shows=[show])
    rows = [
        {"Name": "Cardboard Diamonds Dec", "Date of Transaction": "1/10/2026",
         "Platform": "Cash", "Amount (neg numbers is money coming in)": "30.0",
         "Reason": "Show Fee"},
        {"Name": "Tenzin Show Fee", "Date of Transaction": "1/10/2026",
         "Platform": "Trade", "Amount (neg numbers is money coming in)": "-90.0",
         "Reason": "Show Fee"},  # negative = money came in
    ]
    summary = import_expenses(rows, ctx, ExpenseCategory.SHOW_FEE, link_show=True)
    assert summary["imported"] == 2
    exps = dynamo_repo.list_expenses(date(2026, 1, 1), date(2026, 1, 31))
    assert {e.amount for e in exps} == {Decimal("30.0"), Decimal("-90.0")}
    assert all(e.category.value == "show_fee" for e in exps)
    assert all(e.show_id == "s1" for e in exps)
    assert {e.payment_method for e in exps} == {"cash", "trade"}


def test_import_expenses_skips_totals_row(dynamo_repo):
    from merlins_collection.models.business import ExpenseCategory
    from merlins_collection.services.spreadsheet_import import import_expenses
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Name": "Toploaders", "Date of Transaction": "6/18/2026",
             "Platform": "Card", "Amount (neg numbers is money coming in)": "56.66"},
            {"Name": "Totals", "Amount (neg numbers is money coming in)": "56.66"}]
    summary = import_expenses(rows, ctx, ExpenseCategory.SUPPLIES)
    assert summary == {"imported": 1, "skipped": 1}
    [exp] = dynamo_repo.list_expenses(date(2026, 6, 1), date(2026, 6, 30))
    assert exp.show_id is None  # non-show overhead is not force-linked


def test_import_employee_wages_one_expense_per_nonzero_person(dynamo_repo):
    from merlins_collection.services.spreadsheet_import import import_employee_wages
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Date": "3/1/2026", "Show": "Front Row", "Person 1 Amt": "80",
             "Person 2 Amt": "0", "Person 3 Amt": "", "Total": "80",
             "Paid?": "True"}]
    summary = import_employee_wages(rows, ctx)
    assert summary["imported"] == 1  # only the non-zero person
    [exp] = dynamo_repo.list_expenses(date(2026, 3, 1), date(2026, 3, 31))
    assert exp.category.value == "employee_wage"
    assert exp.amount == Decimal("80")
    assert exp.person == "Person 1"
    assert exp.paid is True


def test_import_employee_expenses_maps_charge(dynamo_repo):
    from merlins_collection.services.spreadsheet_import import import_employee_expenses
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Event Date": "2/28/2026", "Event name": "Front Row Day 1",
             "Name of Charge": "Red Robin", "Amount": "20.98", "Reason": "Food",
             "Paid?": "True"}]
    summary = import_employee_expenses(rows, ctx)
    assert summary["imported"] == 1
    [exp] = dynamo_repo.list_expenses(date(2026, 2, 1), date(2026, 2, 28))
    assert exp.category.value == "employee_expense"
    assert exp.amount == Decimal("20.98")
    assert exp.description == "Red Robin"
    assert exp.reason == "Food"


# ---- Debts tab: two side-by-side ledgers sharing header names ----

def test_run_import_debts_dual_ledger(tmp_path, dynamo_repo):
    # Header row reuses Date/Who/Reason/Cleared on both the left (owed to us) and
    # right (we owe) ledgers, plus two empty summary columns between them.
    (tmp_path / "Debts.csv").write_text(
        "Date,Amount Owed to Company,Who,Reason,Cleared,,,"
        "Date,Amount in Debt to Others,Who,Reason,Cleared\n"
        "1/10/2026,22,Colin,Cashapp,True,,,1/10/2026,30,Jackson,Cash,True\n",
        encoding="utf-8")
    from merlins_collection.services.spreadsheet_import import run_import
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["Debts"]["imported"] == 2
    debts = dynamo_repo.list_debts()
    owed = next(d for d in debts if d.direction.value == "owed_to_us")
    owe = next(d for d in debts if d.direction.value == "we_owe")
    assert owed.counterparty == "Colin" and owed.amount == Decimal("22")
    assert owe.counterparty == "Jackson" and owe.amount == Decimal("30")


# ---- Payouts tab: dynamic per-partner columns ----

def test_import_payouts_one_per_partner_column(dynamo_repo):
    from merlins_collection.services.spreadsheet_import import import_payouts
    ctx = ImportContext(repo=dynamo_repo)
    rows = [
        {"Event": "Cards N More Day #1 (5/10)", "Casey": "40", "Colin": "60",
         "Jackson": "100", "Note": "All Cash", "Percentage": "0.05"},
        {"Event": "", "Casey": "800", "Colin": "1200", "Jackson": "2000",
         "Percentage": "1"},  # totals row -> skipped (no event)
    ]
    summary = import_payouts(rows, ctx)
    assert summary["imported"] == 3  # one per partner column with a value
    payouts = dynamo_repo.list_payouts()
    assert {p.partner for p in payouts} == {"Casey", "Colin", "Jackson"}
    assert all(p.event == "Cards N More Day #1 (5/10)" for p in payouts)
    assert all(p.percent == Decimal("0.05") for p in payouts)


# ---- Balance Sheet tab: sectioned label/amount/note, totals are computed ----

def test_import_balance_sheet_captures_leaf_lines_by_section(dynamo_repo):
    from merlins_collection.services.spreadsheet_import import import_balance_sheet
    ctx = ImportContext(repo=dynamo_repo)
    rows = [
        {"Column 1": "Assets"},
        {"Column 1": "Current Assets"},
        {"Column 1": "Inventory", "Column 2": "5228.81", "Column 3": "cost"},
        {"Column 1": "Total Current Assets", "Column 2": "5228.81"},  # computed
        {"Column 1": "Liabilities"},
        {"Column 1": "Loan", "Column 2": "1000"},
        {"Column 1": "Equity"},
        {"Column 1": "Owners Capital", "Column 2": "4000"},
    ]
    summary = import_balance_sheet(rows, ctx, label="beginning", frozen=True)
    assert summary["imported"] == 3  # totals + section headers excluded
    [snap] = dynamo_repo.list_balance_sheets()
    assert snap.label == "beginning" and snap.frozen is True
    by_label = {ln.label: ln for ln in snap.lines}
    assert by_label["Inventory"].section.value == "asset"
    assert by_label["Loan"].section.value == "liability"
    assert by_label["Owners Capital"].section.value == "equity"
    assert by_label["Owners Capital"].amount == Decimal("4000")


def test_import_singles_blank_condition_defaults_nm_needs_review(dynamo_repo):
    """A real card with no condition shouldn't be dropped: default NM + flag it."""
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles([_singles_row(Condition="")], ctx)
    assert summary == {"imported": 1, "sales": 0, "skipped": 0, "needs_review": 1}
    [item] = dynamo_repo.list_inventory()
    assert item.condition is Condition.NM
    assert item.condition_modifier is None
    assert item.needs_review is True


# ================= Council revision-1 fixes (B1-B8) acceptance =================

def test_B1_two_identical_rows_import_as_two_distinct_records(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    import_singles([_singles_row(), _singles_row()], ctx)  # two byte-identical rows
    assert len(dynamo_repo.list_inventory()) == 2


# ============ Council revision-2 fixes (C1-C3) acceptance ============

def _write_bulk_csv(tmp_path, body: str):
    (tmp_path / "Bulk.csv").write_text(
        "Name,Amount Paid,Sold,Date Sold,Venmo?,Net,Venmo Fees\n" + body, encoding="utf-8")


def test_C1_reimport_after_deleting_a_middle_row_no_orphan_no_double_revenue(
        tmp_path, dynamo_repo):
    # three bulk lots, the middle one sold
    _write_bulk_csv(tmp_path,
                    "lot A,10,,,,,\nlot B,20,25,3/7/2026,No,,\nlot C,30,,,,,\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_inventory()) == 3
    assert len(dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))) == 1
    # DELETE the middle (sold) row and re-import — replace semantics, no orphan.
    # Every re-import below passes force_replace=True: the table now holds business
    # data, and the outer re-import guard refuses an accidental second run without
    # that explicit opt-in (see the re-import guard tests at the end of this file).
    _write_bulk_csv(tmp_path, "lot A,10,,,,,\nlot C,30,,,,,\n")
    run_import(tmp_path, dynamo_repo, require_complete=False, force_replace=True)
    assert len(dynamo_repo.list_inventory()) == 2
    assert dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31)) == []


def test_C1_reimport_after_sorting_rows_is_idempotent(tmp_path, dynamo_repo):
    _write_bulk_csv(tmp_path, "lot A,10,,,,,\nlot B,20,,,,,\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_inventory()) == 2
    _write_bulk_csv(tmp_path, "lot B,20,,,,,\nlot A,10,,,,,\n")  # reordered
    run_import(tmp_path, dynamo_repo, require_complete=False, force_replace=True)
    assert len(dynamo_repo.list_inventory()) == 2  # not 4


def test_C2_total_named_vendor_and_event_are_kept(dynamo_repo):
    from merlins_collection.models.business import ExpenseCategory
    from merlins_collection.services.spreadsheet_import import (
        import_expenses, import_payouts)
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Name": "Total Wine & More", "Amount (neg numbers is money coming in)": "20"},
            {"Name": "Grand Total", "Amount (neg numbers is money coming in)": "20"},
            {"Name": "Total COGS", "Amount (neg numbers is money coming in)": "5"}]
    assert import_expenses(rows, ctx, ExpenseCategory.MARKETING) == {"imported": 1, "skipped": 2}
    [exp] = dynamo_repo.list_expenses(date(2026, 1, 1), date(2026, 12, 31))
    assert exp.description == "Total Wine & More"
    import_payouts([{"Event": "Total Sports Card Expo", "Casey": "40"}], ctx)
    assert {p.event for p in dynamo_repo.list_payouts()} == {"Total Sports Card Expo"}


def test_C3_parse_money_rejects_excessive_precision():
    assert parse_money("0." + "1" * 45) is None      # >38 significant digits
    assert parse_money("123.45") == Decimal("123.45")


def test_C3_structural_tab_failure_rolls_back_atomically(tmp_path, dynamo_repo):
    # An oversized cell in Buying Guidelines raises csv.Error at read time -> that
    # tab fails -> the whole run is atomic: it does NOT commit, and nothing
    # (not even the Bulk lot that loaded) is persisted. No half-import on the
    # live table.
    (tmp_path / "Buying Guidelines.csv").write_text(
        " Product Type,Cash % Min\n" + ("x" * 200000) + ",0.7\n", encoding="utf-8")
    _write_bulk_csv(tmp_path, "lot,10,,,,,\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert "failed" in summaries["Buying Guidelines"]
    assert summaries["_committed"] is False           # atomic: not committed
    assert dynamo_repo.list_inventory() == []         # rolled back, nothing persisted


def test_D1_run_import_refuses_incomplete_export(tmp_path, dynamo_repo):
    # Only one of the expected tab CSVs is present -> refuse before any DB write.
    _write_bulk_csv(tmp_path, "lot,10,,,,,\n")
    with pytest.raises(ImportError, match="incomplete export"):
        run_import(tmp_path, dynamo_repo)            # require_complete defaults True
    assert dynamo_repo.list_inventory() == []         # no destructive action taken


def test_D2_failed_tab_does_not_destroy_previous_generation(tmp_path, dynamo_repo):
    # First import lands cleanly.
    _write_bulk_csv(tmp_path, "lot A,10,,,,,\nlot B,20,,,,,\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_inventory()) == 2
    # A second run where a tab fails must NOT delete the prior generation.
    (tmp_path / "Buying Guidelines.csv").write_text(
        " Product Type,Cash % Min\n" + ("x" * 200000) + ",0.7\n", encoding="utf-8")
    _write_bulk_csv(tmp_path, "lot A,10,,,,,\nlot B,20,,,,,\nlot C,30,,,,,\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is False
    assert len(dynamo_repo.list_inventory()) == 2     # prior data intact, not wiped


def test_D3_infra_error_is_not_swallowed_as_a_skipped_row(dynamo_repo, monkeypatch):
    from botocore.exceptions import ClientError
    err = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
        "PutItem")

    def boom(item):
        raise err

    monkeypatch.setattr(dynamo_repo, "put_inventory_item", boom)
    ctx = ImportContext(repo=dynamo_repo)
    with pytest.raises(ClientError):          # propagates; NOT counted as skipped
        import_singles([_singles_row()], ctx)


def test_B2_import_payouts_ignores_a_total_column(dynamo_repo):
    from merlins_collection.services.spreadsheet_import import import_payouts
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Event": "Show A", "Casey": "40", "Total": "40", "Percentage": "0.05"}]
    import_payouts(rows, ctx)
    partners = {p.partner for p in dynamo_repo.list_payouts()}
    assert partners == {"Casey"}


def test_B3_find_does_not_fuzzy_match_short_ambiguous_alias():
    from merlins_collection.services.spreadsheet_import import _find
    # "Column 1" drifted/absent; the short "Date" alias must NOT grab "Date Sold".
    assert _find({"Date Sold": "3/7/2026", "Name": "x"}, "Date", "Column 1") is None


def test_B4_balance_sheet_raises_on_layout_drift_instead_of_empty_snapshot(dynamo_repo):
    # R5 strengthening: a non-empty tab that yields ZERO leaf lines must FAIL the
    # tab (raise) so the run rolls back — never return a success dict that
    # authorizes deleting the prior (non-re-derivable) snapshot.
    from merlins_collection.services.spreadsheet_import import import_balance_sheet
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Column 1": "Inventory", "Column 2": "5228.81"},  # no Assets section row
            {"Column 1": "Loan", "Column 2": "1000"}]
    with pytest.raises(ValueError):
        import_balance_sheet(rows, ctx, label="beginning", frozen=True)
    assert dynamo_repo.list_balance_sheets() == []


def test_B5_import_expenses_skips_grand_total_footer(dynamo_repo):
    from merlins_collection.models.business import ExpenseCategory
    from merlins_collection.services.spreadsheet_import import import_expenses
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Name": "Toploaders", "Amount (neg numbers is money coming in)": "10"},
            {"Name": "Grand Total", "Amount (neg numbers is money coming in)": "10"}]
    assert import_expenses(rows, ctx, ExpenseCategory.SUPPLIES) == {"imported": 1, "skipped": 1}


def test_B6_parse_fraction_bare_number_and_range():
    from merlins_collection.services.spreadsheet_import import _parse_fraction
    assert _parse_fraction("5") == Decimal("0.05")     # bare whole-number percent
    assert _parse_fraction("0.05") == Decimal("0.05")
    assert _parse_fraction("5%") == Decimal("0.05")
    assert _parse_fraction("150") is None              # out of [0,1] rejected


def test_B6_consignment_bare_percent_payout_not_negative(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = _consignment_row(Sold="$100", **{"Date Sold or Returned": "3/7/2026",
                                           "Sold/Returned": "Sold",
                                           "Percentage we get": "5"})
    import_consignments([row], ctx)
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.consignor_payout == Decimal("95.00")


def test_B7_parse_money_rejects_non_finite_and_oversized():
    assert parse_money("NaN") is None
    assert parse_money("Infinity") is None
    assert parse_money("1E200") is None
    assert parse_money("42.50") == Decimal("42.50")


def test_B7_import_expenses_skips_poison_cell_without_aborting(dynamo_repo):
    from merlins_collection.models.business import ExpenseCategory
    from merlins_collection.services.spreadsheet_import import import_expenses
    ctx = ImportContext(repo=dynamo_repo)
    rows = [{"Name": "bad", "Amount (neg numbers is money coming in)": "NaN"},
            {"Name": "good", "Amount (neg numbers is money coming in)": "10"}]
    summary = import_expenses(rows, ctx, ExpenseCategory.MARKETING)
    assert summary["imported"] == 1 and summary["skipped"] == 1
    [exp] = dynamo_repo.list_expenses(date(2026, 1, 1), date(2026, 12, 31))
    assert exp.description == "good"


def test_B8_import_sale_is_atomic_no_half_sold_item(dynamo_repo, monkeypatch):
    ctx = ImportContext(repo=dynamo_repo)

    def boom(txn):
        raise RuntimeError("ledger write failed")

    monkeypatch.setattr(dynamo_repo, "record_sale", boom)
    row = _singles_row(Sold="$40.00", **{"Date Sold": "3/7/2026"})
    with pytest.raises(RuntimeError):  # infra-style failure propagates (D3), not swallowed
        import_singles([row], ctx)
    # the item was persisted available BEFORE the sale; the failed atomic sale
    # never flipped it to sold and wrote no txn (no half-sold item).
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "available"
    assert dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31)) == []


# ================= Council revision-5 fixes (BLOCKING-1) =====================
# The R4 verdict's non-negotiable: a present-file tab that yields ZERO (or fewer)
# records than the generation it replaces must FAIL the run (rollback), never
# return a success dict that authorizes the commit-delete of the prior data.

_BS_HEADER = "Column 1,Column 2,Column 3\n"
_BS_VALID = (
    _BS_HEADER
    + "Assets,,\n"
    + "Inventory,5228.81,cost\n"
    + "Total Current Assets,5228.81,\n"
    + "Liabilities,,\n"
    + "Loan,1000,\n"
    + "Equity,,\n"
    + "Owners Capital,4000,\n"
)


def _write(tmp_path, name: str, body: str):
    (tmp_path / name).write_text(body, encoding="utf-8")


# ---- BLOCKING-1a: the frozen baseline is immutable (write-once) ----

def test_R6_partial_truncation_preserves_frozen_baseline(tmp_path, dynamo_repo):
    # Seed a full committed import; the frozen `beginning` baseline has 3 leaf lines.
    _write(tmp_path, "Balance Sheet Beginning.csv", _BS_VALID)
    _write(tmp_path, "Copy of Balance Sheet Beginning.csv", _BS_VALID)
    run_import(tmp_path, dynamo_repo, require_complete=False)
    before = next(s for s in dynamo_repo.list_balance_sheets() if s.label == "beginning")
    assert len(before.lines) == 3

    # Re-run with a PARTIALLY truncated Beginning tab: only the Assets block lands
    # (>=1 leaf line, so the zero-leaf raise never fires). The frozen baseline is
    # write-once/immutable, so it must be left UNCHANGED — not the truncated subset.
    partial = _BS_HEADER + "Assets,,\nInventory,5228.81,cost\n"
    _write(tmp_path, "Balance Sheet Beginning.csv", partial)
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is True

    after = next(s for s in dynamo_repo.list_balance_sheets() if s.label == "beginning")
    assert len(after.lines) == 3  # NOT collapsed to the 1-line subset
    assert [(ln.label, ln.amount) for ln in after.lines] == \
           [(ln.label, ln.amount) for ln in before.lines]


def test_R6_rolled_back_first_import_captures_no_frozen_baseline(
        tmp_path, dynamo_repo):
    # The baseline is write-once, so a baseline captured by a run that then FAILS
    # must not persist — otherwise a truncated first export would permanently lock
    # in a bad baseline that write-once forbids ever correcting.
    _write(tmp_path, "Balance Sheet Beginning.csv", _BS_VALID)
    _write(tmp_path, "Buying Guidelines.csv",  # oversized cell -> this tab raises
           " Product Type,Cash % Min\n" + ("x" * 200000) + ",0.7\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["_committed"] is False
    assert dynamo_repo.get_frozen_balance_sheet("beginning") is None

    # A clean re-run then captures the baseline properly.
    (tmp_path / "Buying Guidelines.csv").unlink()
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["_committed"] is True
    baseline = dynamo_repo.get_frozen_balance_sheet("beginning")
    assert baseline is not None and len(baseline.lines) == 3


# ---- BLOCKING-1b: a zero-leaf rollback must preserve every stable-key entity ----

def test_R6_zero_leaf_rollback_preserves_stable_key_entities(tmp_path, dynamo_repo):
    # Seed a committed import touching several stable-key (natural-key) entities.
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Mint City,$500\n")
    _write(tmp_path, "Cash.csv", "Type,Amount\nVenmo,$321.50\n")
    _write(tmp_path, "Buying Guidelines.csv", " Product Type,Cash % Min\nSlabs,60%\n")
    _write(tmp_path, "Balance Sheet Beginning.csv", _BS_VALID)
    _write(tmp_path, "Copy of Balance Sheet Beginning.csv", _BS_VALID)
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert dynamo_repo.list_shows() and dynamo_repo.list_cash_accounts()
    assert dynamo_repo.list_buying_policies()
    assert dynamo_repo.get_payment_method("venmo") is not None
    assert any(s.label == "current" for s in dynamo_repo.list_balance_sheets())

    # Re-run where the CURRENT balance-sheet tab drifts to zero leaf lines -> raises
    # -> whole-run rollback. Every stable-key entity re-written in place earlier in
    # the same run must SURVIVE from the prior generation (not wiped by the rollback).
    _write(tmp_path, "Copy of Balance Sheet Beginning.csv",
           "Item,Column 2,Column 3\nAssets,,\nInventory,5228.81,cost\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is False
    assert dynamo_repo.list_shows() != []
    assert dynamo_repo.list_cash_accounts() != []
    assert dynamo_repo.list_buying_policies() != []
    assert dynamo_repo.get_payment_method("venmo") is not None
    labels = {s.label for s in dynamo_repo.list_balance_sheets()}
    assert "current" in labels and "beginning" in labels


def test_R6_committed_reimport_leaves_one_copy_of_each_stable_key_entity(
        tmp_path, dynamo_repo):
    # Generation-scoping stable keys must not make re-imports ACCUMULATE copies:
    # the commit sweep still collapses each natural-key entity back to exactly one.
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Mint City,$500\n")
    _write(tmp_path, "Cash.csv", "Type,Amount\nVenmo,$321.50\n")
    _write(tmp_path, "Buying Guidelines.csv", " Product Type,Cash % Min\nSlabs,60%\n")
    _write(tmp_path, "Copy of Balance Sheet Beginning.csv", _BS_VALID)
    for run in range(3):
        summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                               force_replace=run > 0)
        assert summaries["_committed"] is True
    assert len(dynamo_repo.list_shows()) == 1
    assert len(dynamo_repo.list_cash_accounts()) == 1
    assert len(dynamo_repo.list_buying_policies()) == 1
    assert len(dynamo_repo.list_payment_methods()) == 8  # seeded set, not 24
    assert len([s for s in dynamo_repo.list_balance_sheets()
                if s.label == "current"]) == 1


# ---- BLOCKING-2: a truncated tab feeding a MULTI-tab entity must fail loud ----

def test_R6_truncated_expense_tab_preserves_prior_expenses(tmp_path, dynamo_repo):
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n1/10/2026,Cardboard,$500\n")
    _write(tmp_path, "Show Fees.csv",
           "Name,Date of Transaction,Platform,"
           "Amount (neg numbers is money coming in),Reason\n"
           "Table Fee,1/10/2026,Cash,30,Fee\n")
    _write(tmp_path, "Marketing.csv",
           "Name,Amount (neg numbers is money coming in)\nFlyers,20\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    before = len(dynamo_repo.list_expenses(date(2026, 1, 1), date(2026, 12, 31)))
    assert before == 2

    # Re-run: Show Fees truncated to header-only, Marketing still full. The `expense`
    # entity total stays > 0 (Marketing), so a mere entity-count guard misses it; the
    # per-tab check must fail loud and preserve the prior expense ledger.
    _write(tmp_path, "Show Fees.csv",
           "Name,Date of Transaction,Platform,"
           "Amount (neg numbers is money coming in),Reason\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is False
    assert len(dynamo_repo.list_expenses(date(2026, 1, 1), date(2026, 12, 31))) == before


# ---- BLOCKING-3: a legitimately-empty ledger needs an explicit operator override --

def test_R6_legit_empty_ledger_needs_override(tmp_path, dynamo_repo):
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Mint City,$500\n")
    _write(tmp_path, "Payouts.csv", "Event,Casey,Colin\nShow A,40,60\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_payouts()) == 2

    # A later period legitimately has no payouts. WITHOUT the override -> fail loud.
    _write(tmp_path, "Payouts.csv", "Event,Casey,Colin\n")
    s1 = run_import(tmp_path, dynamo_repo, require_complete=False,
                    force_replace=True)
    assert s1["_committed"] is False
    assert len(dynamo_repo.list_payouts()) == 2  # prior preserved, not wiped

    # WITH the explicit operator override -> the empty ledger imports to zero AND the
    # rest of that period's workbook (the show) still commits.
    s2 = run_import(tmp_path, dynamo_repo, require_complete=False,
                    allow_empty={"Payouts"}, force_replace=True)
    assert s2["_committed"] is True
    assert dynamo_repo.list_payouts() == []
    assert dynamo_repo.list_shows() != []


# ---- BLOCKING-4 / lock: a second run is refused while one is in flight ----

def test_R6_run_import_refused_while_lock_held(tmp_path, dynamo_repo):
    from merlins_collection.services.dynamodb import ImportInProgressError
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Mint City,$500\n")
    dynamo_repo.acquire_import_lock("other-run")  # another run holds the lock
    with pytest.raises(ImportInProgressError):
        run_import(tmp_path, dynamo_repo, require_complete=False)
    assert dynamo_repo.list_shows() == []  # refused before any write
    dynamo_repo.release_import_lock("other-run")
    # Once released, the run proceeds and releases the lock itself.
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["_committed"] is True


def _debts_body(with_rows: bool) -> str:
    header = ("Date,Amount Owed to Company,Who,Reason,Cleared,,,"
              "Date,Amount in Debt to Others,Who,Reason,Cleared\n")
    if not with_rows:
        return header
    return header + "1/10/2026,22,Colin,Cashapp,True,,,1/10/2026,30,Jackson,Cash,True\n"


def test_R5_present_but_empty_debts_tab_does_not_delete_prior_debts(
        tmp_path, dynamo_repo):
    # First import lands two debts.
    _write(tmp_path, "Debts.csv", _debts_body(with_rows=True))
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_debts()) == 2

    # Re-import with a present-but-header-only Debts.csv (truncated/partial export)
    # -> zero new debts while the prior generation was non-empty. The run must fail
    # loud and preserve the prior debts, never silently empty the ledger.
    _write(tmp_path, "Debts.csv", _debts_body(with_rows=False))
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is False
    assert len(dynamo_repo.list_debts()) == 2  # prior debts intact


def test_R5_truncated_payouts_tab_does_not_delete_unreplaced_remainder(
        tmp_path, dynamo_repo):
    # First import lands two payouts.
    _write(tmp_path, "Payouts.csv",
           "Event,Casey,Colin,Note,Percentage\nShow A,40,60,cash,0.05\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_payouts()) == 2

    # A truncated (header-only) re-export collapses the entity to zero rows. The
    # un-replaced prior remainder must NOT be silently deleted on a commit.
    _write(tmp_path, "Payouts.csv", "Event,Casey,Colin,Note,Percentage\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is False
    assert len(dynamo_repo.list_payouts()) == 2  # remainder preserved


def test_R5_import_debts_aliases_reworded_amount_header(dynamo_repo):
    # A dated/reworded header on the debts amount column must still resolve via the
    # same `_find` aliasing the other importers use (not a raw row.get).
    from merlins_collection.services.spreadsheet_import import import_debts
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date": "1/10/2026", "Amount Owed to Company (as of 7/16)": "22",
           "Who": "Colin", "Reason": "Cashapp", "Cleared": "True"}
    summary = import_debts([row], ctx)
    assert summary["imported"] == 1
    [debt] = dynamo_repo.list_debts()
    assert debt.amount == Decimal("22")
    assert debt.counterparty == "Colin"


# ============ re-import guard: the DB is the source of truth ============
# The spreadsheet was imported ONCE. From then on the database — not the sheet —
# is authoritative, and a re-import REPLACES every import-owned record with the
# sheet's contents (including the non-re-derivable frozen baseline's neighbours).
# So an import into a table that already holds business data is refused outright
# unless the operator asks for it with force_replace / --force-replace.

def _raw_table_snapshot(repo) -> list:
    """Every stored item, fully materialized and ordered, for byte-for-byte
    before/after comparison (a plain list_* read would hide gen/key changes)."""
    items, kwargs = [], {"ConsistentRead": True}
    while True:
        resp = repo._table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted((i["PK"], i["SK"], repr(sorted(i.items()))) for i in items)


def _seed_workbook(tmp_path):
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Mint City,$500\n")
    _write(tmp_path, "Cash.csv", "Type,Amount\nVenmo,$321.50\n")
    _write(tmp_path, "Copy of Balance Sheet Beginning.csv", _BS_VALID)
    _write_bulk_csv(tmp_path, "lot A,10,25,3/7/2026,No,,\n")


def test_reimport_into_populated_table_is_refused_and_mutates_nothing(
        tmp_path, dynamo_repo, monkeypatch):
    _seed_workbook(tmp_path)
    assert run_import(tmp_path, dynamo_repo, require_complete=False)["_committed"]
    before = _raw_table_snapshot(dynamo_repo)
    assert before  # the first import really did land business data

    # Nothing may run past the guard — not the lock, not the generation stamp.
    def _forbidden(*args, **kwargs):
        raise AssertionError("mutating call reached past the re-import guard")

    monkeypatch.setattr(dynamo_repo, "acquire_import_lock", _forbidden)
    monkeypatch.setattr(dynamo_repo, "set_import_generation", _forbidden)
    monkeypatch.setattr(dynamo_repo, "finalize_import", _forbidden)

    with pytest.raises(ExistingBusinessDataError, match="force-replace"):
        run_import(tmp_path, dynamo_repo, require_complete=False)

    assert _raw_table_snapshot(dynamo_repo) == before  # byte-for-byte untouched
    assert dynamo_repo._import_gen is None             # no generation was set


def test_reimport_into_populated_table_proceeds_with_force_replace(
        tmp_path, dynamo_repo):
    _seed_workbook(tmp_path)
    assert run_import(tmp_path, dynamo_repo, require_complete=False)["_committed"]
    assert len(dynamo_repo.list_inventory()) == 1

    _write_bulk_csv(tmp_path, "lot A,10,25,3/7/2026,No,,\nlot B,20,,,,,\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is True
    assert len(dynamo_repo.list_inventory()) == 2   # normal replace semantics
    assert len(dynamo_repo.list_shows()) == 1


def test_first_import_into_catalog_only_table_needs_no_flag(tmp_path, dynamo_repo):
    # The catalog (catalog_card / price_point) is seeded BEFORE the first import
    # and is not import-owned — it must not be mistaken for business data.
    from datetime import datetime

    from merlins_collection.models.catalog import CatalogCard, PricePoint
    dynamo_repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="swsh1-1", name="Celebi V", set_id="swsh1", set_name="S&S",
        number="1", images={"small": "s", "large": "l"},
        prices={"holofoil": {"market": Decimal("12.50")}},
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0))])
    dynamo_repo.append_price_points([PricePoint(
        card_id="swsh1-1", date=date(2026, 6, 20), source="tcgplayer",
        kind="raw", finish="holofoil", market=Decimal("10"))])

    _seed_workbook(tmp_path)
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["_committed"] is True
    assert len(dynamo_repo.list_inventory()) == 1
    assert dynamo_repo.get_catalog_card("swsh1-1") is not None  # catalog preserved


def test_first_import_into_empty_table_needs_no_flag(tmp_path, dynamo_repo):
    _seed_workbook(tmp_path)
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False)
    assert summaries["_committed"] is True
    assert len(dynamo_repo.list_inventory()) == 1


def test_R5_nonzero_row_edit_still_commits_as_normal_replace(tmp_path, dynamo_repo):
    # Guard-rail: the collapse guard only fires on a total collapse to ZERO. A
    # legitimate nonzero row edit (2 -> 1 payouts) is indistinguishable from an
    # intentional edit and must STILL commit as a normal replace (cf. C1).
    _write(tmp_path, "Payouts.csv",
           "Event,Casey,Colin,Note,Percentage\nShow A,40,60,cash,0.05\n")
    run_import(tmp_path, dynamo_repo, require_complete=False)
    assert len(dynamo_repo.list_payouts()) == 2
    _write(tmp_path, "Payouts.csv",
           "Event,Casey,Colin,Note,Percentage\nShow A,40,,cash,0.05\n")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           force_replace=True)
    assert summaries["_committed"] is True
    assert len(dynamo_repo.list_payouts()) == 1  # replaced, no orphan


# ---- print language (a JP card is a DIFFERENT card, not an English one) ----

@pytest.mark.parametrize("text,cleaned", [
    # every marker spelling/casing seen in the real workbook
    ("Team Rocket's Mewtwo (jp)", "Team Rocket's Mewtwo"),
    ("Articuno (Jp)", "Articuno"),
    ("Milotic (JP)", "Milotic"),
    ("Reshiram Ex (japanese)", "Reshiram Ex"),
    ("Espeon V (Japanese)", "Espeon V"),
    ("COLRESS'S EXPERIMENT - FULL ART (Japanese)", "COLRESS'S EXPERIMENT - FULL ART"),
    ("Espathra (JP)", "Espathra"),
    # bare, whitespace-delimited markers — also real rows in the sheet
    ("Lugia jp", "Lugia"),
    ("Slakoth JP", "Slakoth"),
    ("JP exxeggutor Promo", "exxeggutor Promo"),
    ("Dragonite JP ANA airlines", "Dragonite ANA airlines"),
    # a marker sitting alongside other parenthesised text must take only its own
    ("Wooper (Delta Species) Jp 1st Edition", "Wooper (Delta Species) 1st Edition"),
])
def test_parse_language_reads_every_marker_spelling(text, cleaned):
    assert parse_language(text) == (Language.JP, cleaned)


def test_parse_language_defaults_to_english_and_leaves_the_text_untouched():
    for text in ("Charizard", "Mr. Mime", "Team Rocket's Mewtwo", ""):
        assert parse_language(text) == (Language.EN, text)


def test_parse_language_ignores_a_marker_buried_in_an_ordinary_word():
    """Conservative by construction: only a WHOLE, delimited word counts. A bare
    ``jp`` substring inside a longer word is never a language marker."""
    for text in ("Charizard jpeg scan", "Mewtwo Jpop Promo", "Japanophile Deck",
                 "Snorlax 1stjp", "jpn2 lot"):
        assert parse_language(text) == (Language.EN, text)


def test_parse_language_keeps_the_text_when_stripping_would_empty_it():
    """A name that is nothing but a marker still yields JP, but we refuse to
    destroy the only text the row has."""
    assert parse_language("(jp)") == (Language.JP, "(jp)")


def test_parse_language_survives_combined_qualifiers():
    assert parse_language("Venusaur (jp) 1st holo") == (Language.JP, "Venusaur 1st holo")
    assert parse_language("Eevee (jp) 1st Ed") == (Language.JP, "Eevee 1st Ed")
    assert parse_language("Magnezone (jp) first") == (Language.JP, "Magnezone first")


# The English catalog, containing exactly the card a JP row would collide with.
# Built through the PRODUCTION index builder (RFC F.1) so no test carries an
# un-normalized catalog-keying path the real matcher never uses.
def _english_catalog_index():
    from datetime import datetime, timezone

    from merlins_collection.models.catalog import CatalogCard
    from merlins_collection.services.spreadsheet_import import build_catalog_index

    card = CatalogCard(
        card_id="swsh6-38", name="Seismitoad", set_id="swsh6", set_name="Chilling Reign",
        number="38", images={"small": "https://img/s.png", "large": "https://img/l.png"},
        prices={"normal": {"market": Decimal("400.00")}},
        last_synced_at=datetime.now(tz=timezone.utc))
    return build_catalog_index([card])


def test_english_single_still_matches_the_catalog_exactly_as_before(dynamo_repo):
    """No regression on the existing matching path: an English row still links."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    import_singles([_singles_row(Name="Seismitoad", **{"Card #": "38"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "swsh6-38"
    assert item.language is Language.EN
    assert item.needs_review is False


def test_japanese_single_is_never_matched_to_an_english_catalog_card(dynamo_repo):
    """THE central regression test. Name and number match an English catalog card
    exactly, and the match must still be refused — a Japanese Seismitoad is a
    different card, and ``card_id is None`` is its CORRECT terminal state."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    import_singles([_singles_row(Name="Seismitoad (jp)", **{"Card #": "38"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.language is Language.JP
    assert item.card_id is None
    assert item.notes == "Seismitoad #38"  # marker stripped, identity preserved


def test_japanese_single_keeps_the_sheets_own_money_figures(dynamo_repo):
    """The English card is worth $400; the sheet says $12/$8/$15. The item must
    carry the SHEET's figures and no catalog-derived market value at all."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    import_singles([_singles_row(Name="Seismitoad (jp)", **{"Card #": "38"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.cost_basis == Decimal("8.00")
    assert item.market_value_at_purchase == Decimal("12.00")
    assert item.listed_price == Decimal("15.00")
    assert item.current_market_value is None


def test_japanese_slab_is_never_matched_to_an_english_catalog_card(dynamo_repo):
    """Graded JP slabs are real (14 of them in the live Slabs tab)."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    row = {"Date Recieved": "1/5/2026", "Name": "Seismitoad (Japanese)",
           "Set": "Chilling Reign", "card#": "38", "Grade": "10",
           "Cert #": "12345678", "Market @ purchase": "$60", "Amount Paid": "$50",
           "Sold": "", "Date Sold": "", "Venmo?": "", "Sticker": "$75"}
    import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.kind == "graded"
    assert item.language is Language.JP
    assert item.card_id is None
    assert item.listed_price == Decimal("75")
    assert item.current_market_value is None
    assert item.notes.startswith("Seismitoad —")  # marker stripped from the notes


def test_japanese_slab_marked_only_in_the_set_column_is_still_gated(dynamo_repo):
    """Two live Slabs rows write the marker in Set ("Pikachu" / "jp 151") rather
    than in the name, so both columns are read before the catalog is consulted."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    row = {"Date Recieved": "1/5/2026", "Name": "Seismitoad", "Set": "jp 151",
           "card#": "38", "Grade": "10", "Cert #": "1", "Amount Paid": "$50"}
    import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.language is Language.JP
    assert item.card_id is None
    assert item.notes == "Seismitoad — 151 #38"  # marker stripped from the set text


def test_match_card_itself_refuses_a_non_english_language(dynamo_repo):
    """The gate lives INSIDE ``_match_card``, the single place a catalog lookup
    can happen, so any future caller inherits it rather than re-deriving it."""
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_english_catalog_index())
    assert _match_card(ctx, "Seismitoad", "38") == "swsh6-38"
    assert _match_card(ctx, "Seismitoad", "38", language=Language.EN) == "swsh6-38"
    assert _match_card(ctx, "Seismitoad", "38", language=Language.JP) is None


def test_daily_sync_never_writes_an_english_price_onto_a_japanese_item(dynamo_repo):
    """End-to-end money guarantee: the daily market-value sync walks every item,
    and the JP one (card_id None) must come out with its value fields untouched."""
    from merlins_collection.services.catalog_sync import refresh_inventory_market_values

    index = _english_catalog_index()
    [card] = index.by_name_number[("seismitoad", "38", Language.EN)]
    dynamo_repo.batch_upsert_catalog_cards([card])
    ctx = ImportContext(repo=dynamo_repo, catalog_index=index)
    import_singles([_singles_row(Name="Seismitoad (jp)", **{"Card #": "38", "Condition": "NM"}),
                    _singles_row(Name="Seismitoad", **{"Card #": "38", "Condition": "NM"})], ctx)

    refresh_inventory_market_values(dynamo_repo)

    by_language = {i.language: i for i in dynamo_repo.list_inventory()}
    assert by_language[Language.JP].current_market_value is None
    assert by_language[Language.EN].current_market_value == Decimal("400.00")


# ================= RFC 0001: catalog relink matcher normalization (RED) =====
# docs/rfcs/0001-inventory-catalog-relink-and-display-fallback.md, section B.
# The importer's matcher and the catalog index it reads compare RAW,
# un-normalized name/number strings, so an Excel float artifact ("181.0" vs
# catalog "181"), a slash form ("182/167"), or minor name punctuation defeats
# every lookup. These tests build the catalog index through the PRODUCTION
# index builder (`build_catalog_index`, section B.2 — not yet implemented) so
# a test can never pass by hand-normalizing a key the real matcher doesn't.

def _catalog_card(**over):
    from datetime import datetime, timezone

    from merlins_collection.models.catalog import CatalogCard

    defaults = dict(
        card_id="swsh6-38", name="Dragonair", set_id="swsh6",
        set_name="Chilling Reign", number="181",
        images={"small": "https://img/s.png", "large": "https://img/l.png"},
        prices={"normal": {"market": Decimal("5.00")}},
        last_synced_at=datetime.now(tz=timezone.utc),
    )
    defaults.update(over)
    return CatalogCard(**defaults)


def _normalized_index(cards):
    """Route through the production catalog-index builder instead of
    hand-rolling a normalized dict in the test — otherwise a test could pass
    without the real matcher ever normalizing anything (section F.1)."""
    from merlins_collection.services.spreadsheet_import import build_catalog_index
    return build_catalog_index(cards)


def test_match_card_links_number_with_float_artifact(dynamo_repo):
    """Catalog stores number "181"; the sheet's Excel export writes "181.0".
    _match_card must undo the float artifact before comparing. (fails now:
    "181.0" != "181")"""
    card = _catalog_card(card_id="swsh6-181", name="Dragonair", number="181")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Dragonair", "181.0") == "swsh6-181"


def test_match_card_links_slash_form_number(dynamo_repo):
    """The sheet writes the full collector string ("182/167"); the catalog
    stores only the number before the slash. (fails now)"""
    card = _catalog_card(card_id="swsh1-182", name="Mew", number="182")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Mew", "182/167") == "swsh1-182"


def test_match_card_normalizes_name_punctuation(dynamo_repo):
    """Name punctuation/spacing drift ("Moltres & Zapdos-GX" vs catalog's
    "Moltres & Zapdos GX") must not defeat the match. (fails now)"""
    card = _catalog_card(card_id="swsh1-84", name="Moltres & Zapdos GX", number="84")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Moltres & Zapdos-GX", "84") == "swsh1-84"


def test_match_card_ambiguous_multiset_stays_unlinked(dynamo_repo):
    """A genuinely ambiguous single (same normalized name+number in two sets,
    no Set column) must stay card_id=None — NEVER force-guessed to hits[0].
    Guards against over-linking to the wrong set's price."""
    card_a = _catalog_card(card_id="base1-4", name="Charizard",
                           set_name="Base Set", number="4")
    card_b = _catalog_card(card_id="base4-4", name="Charizard",
                           set_name="Base Set 2", number="4")
    ctx = ImportContext(repo=dynamo_repo,
                        catalog_index=_normalized_index([card_a, card_b]))
    assert _match_card(ctx, "Charizard", "4") is None


def test_match_card_slab_set_inference_links_unique(dynamo_repo):
    """A slab's Set column narrows a multi-set name+number hit to one card.
    (fails now: no set_text param / no narrowing)"""
    card_a = _catalog_card(card_id="chi6-38", name="Seismitoad",
                           set_name="Chilling Reign", number="38")
    card_b = _catalog_card(card_id="base1-38", name="Seismitoad",
                           set_name="Base Set", number="38")
    ctx = ImportContext(repo=dynamo_repo,
                        catalog_index=_normalized_index([card_a, card_b]))
    assert _match_card(ctx, "Seismitoad", "38", set_text="Chilling Reign") == "chi6-38"


def test_import_singles_links_float_artifact_row(dynamo_repo):
    """Integration: a real Singles row with the Excel float artifact links to
    its unique catalog card and is NOT flagged for review. (fails now)"""
    card = _catalog_card(card_id="swsh6-181", name="Dragonair", number="181")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = _singles_row(Name="Dragonair", **{"Card #": "181.0"})
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "swsh6-181"
    assert item.needs_review is False


def test_build_catalog_index_keys_are_normalized(dynamo_repo):
    """The index builder keys on normalize_name + number_keys, so a lookup by
    ("dragonair", "181") resolves a catalog card whose raw number was "181"
    and whose raw name was "Dragonair". (new unit — build_catalog_index does
    not exist yet)"""
    from merlins_collection.services.spreadsheet_import import build_catalog_index

    card = _catalog_card(card_id="swsh6-181", name="Dragonair", number="181")
    index = build_catalog_index([card])
    by_name_number = getattr(index, "by_name_number", None)
    if by_name_number is None and isinstance(index, dict):
        by_name_number = index.get("by_name_number", index)
    hits = by_name_number.get(("dragonair", "181", Language.EN), [])
    assert len(hits) == 1
    assert hits[0].card_id == "swsh6-181"


def test_build_catalog_index_exposes_a_card_id_lookup(dynamo_repo):
    """The enriched-path validation needs a direct card_id -> card lookup, not
    just the name/number indexes _match_card uses."""
    from merlins_collection.services.spreadsheet_import import build_catalog_index

    card = _catalog_card(card_id="en:base1-4", name="Charizard", number="4")
    index = build_catalog_index([card])
    assert index.by_card_id["en:base1-4"].card_id == "en:base1-4"
    assert index.by_card_id.get("en:nonexistent") is None


# ===== Council revision-2 MUST-FIX 2 & 3: conservative single-hit auto-link =====
# The rev-1 matcher auto-linked ANY unique hit before checking set agreement, and
# auto-linked a variant to the base card when core_name stripped a qualifier. Both
# silently hang the wrong price on a card; both must route to review instead.

def test_match_card_single_hit_rejected_when_set_text_contradicts(dynamo_repo):
    """MUST-FIX 2: a graded slab whose Set text contradicts the ONLY catalog hit
    must NOT auto-link (McDonald's Pikachu #58 is not Base Set Pikachu #58). The
    set-agreement gate applies to the unique-hit branch, not only to multi-hit."""
    card = _catalog_card(card_id="base1-58", name="Pikachu",
                         set_name="Base Set", number="58")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Pikachu", "58",
                       set_text="McDonald's Collection 2016") is None


def test_match_card_single_hit_links_when_set_text_agrees(dynamo_repo):
    """Companion to MUST-FIX 2: a unique hit whose Set text AGREES still links —
    the gate only fires on a contradiction, never on a match."""
    card = _catalog_card(card_id="base1-58", name="Pikachu",
                         set_name="Base Set", number="58")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Pikachu", "58", set_text="Base Set") == "base1-58"


def test_match_card_variant_qualifier_not_autolinked_to_base(dynamo_repo):
    """MUST-FIX 3: "Charizard V Alt Art" #154 misses the full-name tier, then
    core_name drops the 'alt'/'art' qualifiers and hits the BASE "Charizard V"
    #154. That variant is a different print at a different price — never auto-link
    a core-tier match that dropped a qualifier; route to review (None)."""
    card = _catalog_card(card_id="swsh1-154", name="Charizard V", number="154")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Charizard V Alt Art", "154") is None


def test_match_card_finish_only_normalization_still_links(dynamo_repo):
    """MUST-FIX 3 guard rail: dropping a FINISH word (holo/reverse) costs no
    confidence — the catalog never carries it — so a finish-only core-tier match
    still auto-links. Only qualifier tokens (alt/gold/1st…) route to review."""
    card = _catalog_card(card_id="base1-4", name="Dragonite", number="4")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    assert _match_card(ctx, "Dragonite Holo", "4") == "base1-4"


# ===== Council revision-3 MUST-FIX B: qualifier guard on BOTH return paths =====
# rev-2 installed the _dropped_qualifier guard on the len(hits)==1 branch only.
# The len(hits)>1 -> set-narrowed-to-1 branch returned narrowed[0].card_id with no
# guard, so a variant still auto-linked to the base card at the base price through
# the multi-hit door. The guard must run on the narrowed return path too.

def test_match_card_variant_qualifier_not_autolinked_via_narrowed_branch(dynamo_repo):
    """MUST-FIX B: "Charizard V Alt Art" #154, Set "Brilliant Stars" misses the
    full-name tier; core_name drops 'alt'/'art' -> base "Charizard V" #154 hits in
    TWO sets (core_tier); set_text narrows to exactly ONE. That narrowed hit still
    dropped a qualifier, so it must route to review (None) — the same variant->base
    defect MUST-FIX 3 forbids, routed through the len(hits)>1 branch."""
    card_a = _catalog_card(card_id="swsh9-154", name="Charizard V",
                           set_name="Brilliant Stars", number="154")
    card_b = _catalog_card(card_id="cel25-154", name="Charizard V",
                           set_name="Celebrations", number="154")
    ctx = ImportContext(repo=dynamo_repo,
                        catalog_index=_normalized_index([card_a, card_b]))
    assert _match_card(ctx, "Charizard V Alt Art", "154",
                       set_text="Brilliant Stars") is None


def test_match_card_finish_only_narrowed_branch_still_links(dynamo_repo):
    """MUST-FIX B guard rail: a dropped FINISH word (holo) on the multi-hit
    set-narrowed path costs no confidence, so it still links to the narrowed card —
    only a stripped QUALIFIER routes to review."""
    card_a = _catalog_card(card_id="swsh9-20", name="Dragonite",
                           set_name="Brilliant Stars", number="20")
    card_b = _catalog_card(card_id="cel25-20", name="Dragonite",
                           set_name="Celebrations", number="20")
    ctx = ImportContext(repo=dynamo_repo,
                        catalog_index=_normalized_index([card_a, card_b]))
    assert _match_card(ctx, "Dragonite Holo", "20",
                       set_text="Brilliant Stars") == "swsh9-20"


# ===== Council revision-3 MUST-FIX A/C: display_name materialized at import =====
# The customer-facing name is composed ONCE, at import, from the sheet's own
# structured Name + Card # columns and stored on the item row. Both read surfaces
# (backend _enrich, MCP toCard) then read that one stored field; neither re-parses
# the free-text `notes` blob, so internal Notes text can never leak into a name.

def test_import_singles_materializes_display_name_from_structured_identity(dynamo_repo):
    """A normal unmatched single stores "Dragonair #181" (from Name + Card #), so
    the customer surface shows a card name instead of a ULID — no notes parsing."""
    ctx = ImportContext(repo=dynamo_repo)
    import_singles([_singles_row(Name="Dragonair", **{"Card #": "181.0"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id is None
    assert item.display_name == "Dragonair #181"


def test_import_singles_stores_no_display_name_when_name_is_blank(dynamo_repo):
    """Council MUST-FIX A: a blank-Name row whose Notes column carries internal
    free-text ("cost 40 sold to David #12", "box #3", "PSA cert #12345678") stores
    display_name=None. The name is NEVER derived from Notes, so none of that text
    reaches the wire or MCP — even though the trailing " #<digits>" once fooled the
    read-time parser."""
    ctx = ImportContext(repo=dynamo_repo)
    leaky = ["cost 40 sold to David #12", "box #3", "PSA cert #12345678"]
    import_singles([_singles_row(Name="", Notes=n) for n in leaky], ctx)
    items = dynamo_repo.list_inventory()
    assert len(items) == 3
    for item in items:
        assert item.display_name is None
        assert item.card_id is None


def test_import_singles_matched_row_still_stores_structured_display_name(dynamo_repo):
    """Even a matched row stores its structured display_name (a robust fallback if
    the catalog META is momentarily missing); the read path prefers the catalog
    name when the card resolves."""
    card = _catalog_card(card_id="swsh6-181", name="Dragonair", number="181")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    import_singles([_singles_row(Name="Dragonair", **{"Card #": "181.0"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "swsh6-181"
    assert item.display_name == "Dragonair #181"


def test_import_slabs_materializes_display_name_from_structured_identity(dynamo_repo):
    """A slab stores its display_name from the Name + card# columns too."""
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date Recieved": "1/5/2026", "Name": "Charizard", "Set": "Base",
           "card#": "4", "Grade": "9.5", "Cert #": "12345678", "Amount Paid": "$250"}
    import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.display_name == "Charizard #4"


def test_import_consignments_materializes_display_name(dynamo_repo):
    """A consignment raw/graded item (never catalog-matched by the importer) also
    stores a structured display_name from its Card Name + Card # columns."""
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Date recieved": "2/1/2026", "Card Name": "Umbreon VMAX", "Condition": "NM",
           "Slab": "", "Card #": "215", "Persons Name": "David",
           "Percentage we get": "20%", "Sold/Returned": "", "Sold": "", "Date Sold": "",
           "Market": "$110", "Minimum": "", "To payout": "", "Paid Out?": "No"}
    import_consignments([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.display_name == "Umbreon VMAX #215"


# =============================================================================
# PHASE 3 (RFC 0003 §3 / claude-progress.txt Section 3, Phase 3.1-3.3): store
# EVERYTHING, show only unsold; multilingual matching; needs_review round trip.
# Everything above this banner pins the PRE-Phase-3 shape (English-only single
# hit matching); everything below is new coverage for the Phase 3 rewrite.
# =============================================================================

import csv as _csv
from pathlib import Path as _Path

_REAL_CSV_DIR = _Path(__file__).resolve().parents[3] / "data" / "spreadsheet" / "csv"


def _real_rows(tab: str) -> list[dict]:
    path = _REAL_CSV_DIR / f"{tab}.csv"
    if not path.exists():
        pytest.skip(f"real workbook export not present (gitignored): {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(_csv.DictReader(f))


# ---- D3: store EVERY row, sold or not, with its full money/date fields -------

def test_parse_date_reads_the_real_sheets_datetime_with_time_suffix():
    """The 7-25 workbook's own CSV export writes every date as a full
    ``YYYY-MM-DD HH:MM:SS`` timestamp ("2026-04-18 00:00:00"), not the
    "%m/%d/%Y" the fixtures elsewhere in this file use. ``parse_date`` does not
    try that format today, so a real acquired/sold date silently falls through
    to ``None`` — which, for a Sold row, means it can never be classified SOLD
    no matter what the Sold cell says (see the real-Bulk-csv test below, which
    catches this against production data: 44 rows misclassified)."""
    assert parse_date("2026-04-18 00:00:00") == date(2026, 4, 18)
    assert parse_date("2026-01-03 00:00:00") == date(2026, 1, 3)


def test_import_bulk_sold_row_using_the_real_datetime_format_is_recognized_as_sold(
        dynamo_repo):
    """A synthetic row shaped exactly like the real Bulk tab: today this silently
    fails to record a sale because ``Date Sold`` never parses."""
    ctx = ImportContext(repo=dynamo_repo)
    row = {"Name": "Bulk Sale 1", "Amount Paid": "0.0", "Sold": "8.0",
           "Date Sold": "2026-01-03 00:00:00", "Venmo?": "False", "Net": "8",
           "Venmo Fees": "0"}
    summary = import_bulk([row], ctx)
    assert summary["sales"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "sold"


def test_real_bulk_csv_recognizes_every_row_carrying_both_sold_and_date_sold(
        dynamo_repo):
    """Regression pin against the SAME datetime-format bug, run against the
    actual 2026-07-25 workbook export: 44 of the 137 Bulk rows carry a Sold
    amount AND a Date Sold (measured directly off the CSV this session) and each
    must produce a sale transaction — not the 0 today's ``parse_date`` manages."""
    rows = _real_rows("Bulk")
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_bulk(rows, ctx)
    assert summary["imported"] == len(rows)
    assert summary["sales"] == 44
    assert len(dynamo_repo.list_transactions(date(2026, 1, 1), date(2026, 12, 31))) == 44


def test_real_singles_csv_stores_every_row_and_shows_only_the_unsold(dynamo_repo):
    """Section 2's measurement this session: the owner pruned every sold Singles
    row before saving the 7-25 workbook, so 0 of its rows carry both a Sold
    amount and a Date Sold. D3 requires every row to be STORED regardless — and,
    since none of them are sold, every stored row's status must be something
    other than 'sold' (available/on_hold/lost/out_for_grading are all fine)."""
    rows = _real_rows("Singles")
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles(rows, ctx)
    assert summary["imported"] + summary["skipped"] == len(rows)
    items = dynamo_repo.list_inventory()
    assert len(items) == summary["imported"]
    assert summary["sales"] == 0
    assert all(i.status.value != "sold" for i in items)
    assert all(i.cost_basis is not None for i in items)  # nothing dropped in translation


def test_import_singles_sold_row_stores_the_full_d3_field_set(dynamo_repo):
    """D3 names six facts a sold row must keep: location, cost_basis,
    market_value_at_purchase, listed/sticker, sold price, and both dates. The
    pre-Phase-3 sold-row test only checked the transaction; this pins the ITEM
    fields too, on both sides of the sale."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _singles_row(Sold="$40.00", **{"Date Sold": "3/7/2026"})
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "sold"
    assert item.location == "glass"                            # Location
    assert item.cost_basis == Decimal("8.00")                  # Amount Paid
    assert item.market_value_at_purchase == Decimal("12.00")   # Market @ purchase
    assert item.listed_price == Decimal("15.00")               # Sticker
    assert item.acquired_at == date(2026, 1, 5)                 # Date
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.amount == Decimal("40.00")                       # Sold
    assert txn.date == date(2026, 3, 7)                         # Date Sold


def test_a_sold_amount_without_a_sold_date_is_not_classified_sold(dynamo_repo):
    """D3's rule is an AND, not an OR: a Sold cell with no Date Sold must not
    flip the item or create a phantom sale."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _singles_row(Sold="$40.00")  # Date Sold left blank
    summary = import_singles([row], ctx)
    assert summary["sales"] == 0
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "available"
    assert dynamo_repo.list_transactions(date(2026, 1, 1), date(2026, 12, 31)) == []


def test_a_sold_date_without_a_sold_amount_is_not_classified_sold(dynamo_repo):
    ctx = ImportContext(repo=dynamo_repo)
    row = _singles_row(**{"Date Sold": "3/7/2026"})  # Sold left blank
    summary = import_singles([row], ctx)
    assert summary["sales"] == 0
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "available"


# ---- Slabs deferred: schema support YES, import NO (Section 7 HANDOFF) -------

def test_run_import_defers_slabs_entirely_via_allow_empty(tmp_path, dynamo_repo):
    """The owner is holding slab import until PSA cert lookup exists (Section 7
    HANDOFF: "Defer the tab via the existing allow_empty knob"). But as
    ``allow_empty`` stands today it only forgives a tab that imports ZERO
    records — it does NOT stop the tab from running. A Slabs.csv carrying real
    rows is fully imported today even when "Slabs" is passed in ``allow_empty``,
    which is the opposite of "deferred". This pins the INTENDED behavior: no
    GradedInventoryItem may be created from the Slabs tab while it is deferred.
    (If ``allow_empty`` genuinely cannot be stretched to mean "skip this tab
    outright", that is the gap to report back — see the QA report.)"""
    (tmp_path / "Vending Net.csv").write_text(
        "Day,Show,Goal\n3/8/2026,Mint City,$500\n", encoding="utf-8")
    (tmp_path / "Slabs.csv").write_text(
        "Date Recieved,Name,Set,card#,Grade,Cert #,Amount Paid\n"
        "1/5/2026,Charizard,Base,4,9.5,12345678,250\n", encoding="utf-8")
    summaries = run_import(tmp_path, dynamo_repo, require_complete=False,
                           allow_empty={"Slabs"})
    assert summaries["_committed"] is True
    assert dynamo_repo.list_inventory() == []          # the Slabs row never landed
    assert summaries["Slabs"]["imported"] == 0


# ---- 3.2: multilingual matching — a JP row resolves to a JP catalog row ------
# RFC 0003 §3 gives card_id the composite form "{lang}:{tcgdex_id}" precisely so
# a JP printing and its EN twin are separate catalog rows with separate prices.
# The catalog index built here must therefore key on language too — today's
# ``build_catalog_index``/``_match_card`` key on (name, number) alone, so adding
# a same-name-and-number JP row to the index does not merely fail to help a JP
# lookup, it actively BREAKS the EN one (a unique EN hit becomes an ambiguous
# same-key pair the moment a JP twin is added).

def test_build_catalog_index_keys_include_language(dynamo_repo):
    en = _catalog_card(card_id="swsh6-38", name="Seismitoad", number="38",
                       language=Language.EN)
    jp = _catalog_card(card_id="ja:swsh6-38", name="Seismitoad", number="38",
                       language=Language.JP)
    index = _normalized_index([en, jp])
    en_hits = index.by_name_number.get(("seismitoad", "38", Language.EN), [])
    jp_hits = index.by_name_number.get(("seismitoad", "38", Language.JP), [])
    assert [c.card_id for c in en_hits] == ["swsh6-38"]
    assert [c.card_id for c in jp_hits] == ["ja:swsh6-38"]


def test_match_card_links_a_japanese_single_to_its_japanese_catalog_row(dynamo_repo):
    """THE Phase 3.2 acceptance test: a JP item must resolve to the JP printing,
    not be refused outright the way the pre-Phase-3 English-only gate did."""
    en = _catalog_card(card_id="swsh6-38", name="Seismitoad", number="38",
                       language=Language.EN)
    jp = _catalog_card(card_id="ja:swsh6-38", name="Seismitoad", number="38",
                       language=Language.JP)
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([en, jp]))
    assert _match_card(ctx, "Seismitoad", "38", language=Language.JP) == "ja:swsh6-38"


def test_match_card_english_lookup_is_unaffected_by_a_same_key_japanese_twin(
        dynamo_repo):
    """The flip side, and the reason language MUST be part of the key rather
    than a post-hoc filter: adding the JP twin above must not turn the EN
    lookup into an ambiguous multi-hit that routes to review by accident."""
    en = _catalog_card(card_id="swsh6-38", name="Seismitoad", number="38",
                       language=Language.EN)
    jp = _catalog_card(card_id="ja:swsh6-38", name="Seismitoad", number="38",
                       language=Language.JP)
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([en, jp]))
    assert _match_card(ctx, "Seismitoad", "38", language=Language.EN) == "swsh6-38"


def test_import_singles_links_a_japanese_row_to_its_japanese_catalog_card(dynamo_repo):
    en = _catalog_card(card_id="swsh6-38", name="Seismitoad", number="38",
                       language=Language.EN)
    jp = _catalog_card(card_id="ja:swsh6-38", name="Seismitoad", number="38",
                       language=Language.JP)
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([en, jp]))
    row = _singles_row(Name="Seismitoad (jp)", **{"Card #": "38"})
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.language is Language.JP
    assert item.card_id == "ja:swsh6-38"
    assert item.needs_review is False


def test_import_slabs_links_a_set_only_japanese_row_to_its_japanese_catalog_card(
        dynamo_repo):
    """The real Slabs.csv row 18 (Seismitoad / Set "SV11B"): no name marker
    anywhere. Once language detection covers the set-code fallback (see the
    card_text tests) AND matching is language-aware, this slab should link
    instead of going unmatched.

    IMPORTANT LATENT-BUG NOTE for the code-writer: today, with the language
    gate mis-detecting this row as EN (no set fallback yet) and the catalog
    index NOT yet scoped by language, this test's card_id assertion can
    ACCIDENTALLY already equal "ja:sv11b-109" — the item silently borrows a
    Japanese-only catalog card's identity while still labeled EN, with
    needs_review left False. That is the real Phase-3.2 hazard: fixing only
    ONE of (set-based language detection, language-scoped indexing) leaves the
    other free to mislink silently rather than merely fail to link. Both must
    land together. The ``language is Language.JP`` assertion below is what
    actually catches today's mislabeling; do not consider this test passing
    unless BOTH assertions hold for the right reason."""
    jp = _catalog_card(card_id="ja:sv11b-109", name="Seismitoad",
                       set_name="SV11B", number="109", language=Language.JP)
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([jp]))
    row = {"Date Recieved": "7/25/2026", "Name": "Seismitoad", "Set": "SV11B",
           "card#": "109.0", "Grade": "10.0", "Cert #": "150656224.0",
           "Amount Paid": "127.0"}
    import_slabs([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.language is Language.JP
    assert item.card_id == "ja:sv11b-109"
    assert item.needs_review is False


# ---- 3.3: needs_review round trip survives the Phase 3 rewrite (regression) --
# Not a NEW behavior request — Phase 3.3 asks that this mechanic be PRESERVED
# while 3.1/3.2 rewrite the matcher underneath it. Kept to English-only data on
# purpose: build_review.py / apply_review_decisions.py's OWN multilingual
# banding (NA/CONTRADICTION for any non-EN item) is explicitly Phase 6 scope
# (claude-progress.txt §3, Phase 6.1) and must not be pre-empted here.

def test_an_unmatched_singles_row_surfaces_in_build_review_and_is_relinked(
        dynamo_repo):
    import importlib.util
    import sys as _sys

    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        _sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    scripts_dir = _Path(__file__).resolve().parents[2] / "scripts"
    br = _load("br_roundtrip_phase3", scripts_dir / "build_review.py")
    ard = _load("ard_roundtrip_phase3", scripts_dir / "apply_review_decisions.py")

    card = _catalog_card(card_id="base1-4", name="Charizard", set_name="Base Set",
                         number="4")
    # ambiguous ON PURPOSE: Singles has no Set column, and a second printing
    # shares the same name+number, so the importer cannot pick one on its own
    # -> needs_review stays True, exactly as it did before the Phase 3 rewrite.
    twin = _catalog_card(card_id="base2-4", name="Charizard",
                         set_name="Base Set 2", number="4")
    dynamo_repo.batch_upsert_catalog_cards([card, twin])
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card, twin]))
    import_singles([_singles_row(Name="Charizard", **{"Card #": "4"})], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id is None and item.needs_review is True

    data = br.collect(br.scan_records("merlins-cards-test", "us-east-1"))
    rows = br.build_card_rows(data["inventory"], br.CatalogIndex.build(data["catalog"]),
                              data["prices"])
    assert item.item_id in [r["item_id"] for r in rows]

    text = ("# MERLIN-REVIEW-V1\n"
            f"CARD {item.item_id} ACCEPT card_id=base1-4; name=Charizard; "
            f"set=Base Set; number=4\n")
    report = ard.DecisionApplier(dynamo_repo, apply=True).run(ard.parse_block(text))
    assert report.exit_code == 0
    relinked = dynamo_repo.get_inventory_item(item.item_id)
    assert relinked.card_id == "base1-4"
    assert relinked.needs_review is False


# =============================================================================
# PHASE 3.1 STAGE B: import_singles consumes Singles_enriched_v3.csv columns
# deterministically. Language + card_id come from the enriched file, not from
# URL-param parsing or live _match_card. Confidence tiers drive needs_review.
# =============================================================================

_ENRICHED_CSV = "Singles_enriched_v3"


def _enriched_singles_row(**over):
    """A row shaped like Singles_enriched_v3.csv (Stage B input)."""
    row = {
        "Date": "1/5/2026", "Location": "Glass", "Name": "Pikachu",
        "Card #": "25", "Condition": "LP +",
        "Market @ purchase": "$12.00", "Amount Paid": "$8.00",
        "Sold": "", "Date Sold": "", "Venmo?": "",
        # Enrichment columns (Stage A output):
        "language": "EN",
        "matched_set_id": "base1",
        "matched_set_name": "Base Set",
        "matched_number": "25",
        "matched_card_id": "base1-25",
        "match_confidence": "high",
        "match_notes": "",
    }
    row.update(over)
    return row


def test_enriched_high_confidence_row_imports_with_resolved_card_id(dynamo_repo):
    """HIGH confidence: card_id comes from the enriched matched_card_id column
    deterministically, language from the enriched language column. No _match_card
    call, no URL-param parsing. The stored card_id is the composite
    ``{language}:{tcgdex_id}`` form the catalog actually keys on, validated
    against a real catalog_index — not the bare id straight off the CSV."""
    card = _catalog_card(card_id="en:base1-25", name="Pikachu", number="25")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = _enriched_singles_row(
        Name="Pikachu", **{"Card #": "25"},
        language="EN", matched_card_id="base1-25", match_confidence="high",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "en:base1-25"
    assert item.language is Language.EN
    assert item.needs_review is False


def test_enriched_medium_confidence_row_imports_with_card_id_and_needs_review(
        dynamo_repo):
    """MEDIUM confidence: card_id IS populated from the enriched file (as the
    composite ``{language}:{tcgdex_id}`` form, validated against the catalog),
    but the row is always flagged needs_review=True so a human can verify."""
    card = _catalog_card(card_id="en:me02-106", name="Meowth", number="106")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = _enriched_singles_row(
        Name="Meowth", **{"Card #": "106"},
        language="EN", matched_card_id="me02-106", match_confidence="medium",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    assert summary["needs_review"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "en:me02-106"
    assert item.needs_review is True


def test_enriched_low_confidence_row_imports_with_no_card_id_and_needs_review(
        dynamo_repo):
    """LOW confidence / no match: card_id is None, needs_review is True, but the
    row IS stored (not skipped). display_name uses format_display_name output."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row(
        Name="Ultra Ball", **{"Card #": "68a"},
        language="EN", matched_card_id="", match_confidence="low",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    assert summary["skipped"] == 0
    [item] = dynamo_repo.list_inventory()
    assert item.card_id is None
    assert item.needs_review is True
    # display_name from format_display_name(name, card_number):
    assert item.display_name == "Ultra Ball #68a"


def test_enriched_high_confidence_row_with_a_dangling_card_id_is_not_trusted(
        dynamo_repo):
    """A HIGH-confidence matched_card_id that does not resolve against the
    catalog (TCGdex sometimes advertises a set it holds zero card data for —
    Stage A resolved the id live, but the reseed's catalog never got the card)
    must not be trusted just because confidence says 'high'. It must import
    with card_id=None + needs_review=True, exactly like the no-match tier —
    never store a reference to a card that does not exist."""
    ctx = ImportContext(repo=dynamo_repo)  # no catalog card seeded — empty index
    row = _enriched_singles_row(
        Name="Meloetta ex", **{"Card #": "170"},
        language="JP", matched_card_id="SV11B-170", match_confidence="high",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    assert summary["needs_review"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.card_id is None
    assert item.needs_review is True


def test_enriched_high_confidence_japanese_row_gets_the_ja_composite_prefix(
        dynamo_repo):
    """The composite scheme is per-language: a JP row's matched_card_id must be
    prefixed 'ja:', never 'en:' — verified against a real JP catalog card."""
    card = _catalog_card(card_id="ja:sv11b-1", name="Pikachu", number="1")
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = _enriched_singles_row(
        Name="Pikachu", **{"Card #": "1"},
        language="JP", matched_card_id="sv11b-1", match_confidence="high",
    )
    summary = import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "ja:sv11b-1"
    assert item.language is Language.JP


def test_enriched_row_does_not_populate_listed_price(dynamo_repo):
    """The enriched CSV has no Sticker column. listed_price must be None —
    it is out of scope entirely (LISTED_PRICE DROPPED decision)."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row()
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.listed_price is None


def test_enriched_row_does_not_store_tcg_url(dynamo_repo):
    """The enriched CSV has no TCG Link column. tcg_url must be None."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row()
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.tcg_url is None


def test_enriched_japanese_row_maps_language_correctly(dynamo_repo):
    """Language comes from the enriched 'language' column, not from
    parse_language / language_from_url. Using a name WITHOUT a '(jp)' marker
    to prove the enrichment column is the source — parse_language alone would
    return EN for this name."""
    card = _catalog_card(card_id="ja:cp3-16", name="Espurr", number="16",
                         language=Language.JP)
    ctx = ImportContext(repo=dynamo_repo, catalog_index=_normalized_index([card]))
    row = _enriched_singles_row(
        Name="Espurr", **{"Card #": "16"},
        language="JP", matched_card_id="cp3-16", match_confidence="high",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.language is Language.JP
    assert item.card_id == "ja:cp3-16"


def test_enriched_sold_row_records_sale_transaction(dynamo_repo):
    """Sold/available logic is unchanged: SOLD when BOTH Sold amount AND
    Date Sold are present."""
    show = Show(show_id="s1", name="Show", date=date(2026, 3, 8))
    ctx = ImportContext(repo=dynamo_repo, shows=[show])
    row = _enriched_singles_row(
        Sold="$40.00", **{"Date Sold": "3/7/2026", "Venmo?": "Yes"},
    )
    summary = import_singles([row], ctx)
    assert summary["sales"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.status.value == "sold"
    txns = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert len(txns) == 1
    assert txns[0].amount == Decimal("40.00")


def test_enriched_row_stores_cost_basis_and_market_value(dynamo_repo):
    """cost_basis and market_value_at_purchase come from Amount Paid and
    Market @ purchase, same as before."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row()
    import_singles([row], ctx)
    [item] = dynamo_repo.list_inventory()
    assert item.cost_basis == Decimal("8.00")
    assert item.market_value_at_purchase == Decimal("12.00")


def test_enriched_blank_matched_card_id_treated_as_no_match(dynamo_repo):
    """An empty matched_card_id string means no match, even if confidence
    says 'high'. card_id=None and needs_review=True."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row(
        matched_card_id="", match_confidence="high",
    )
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.card_id is None
    assert item.needs_review is True


def test_enriched_row_blank_condition_still_defaults_nm_needs_review(dynamo_repo):
    """A high-confidence row with a blank Condition still defaults to NM
    but forces needs_review=True (blank condition overrides confidence)."""
    ctx = ImportContext(repo=dynamo_repo)
    row = _enriched_singles_row(Condition="", match_confidence="high")
    summary = import_singles([row], ctx)
    assert summary["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.condition is Condition.NM
    assert item.needs_review is True


def test_real_enriched_csv_stores_every_row(dynamo_repo):
    """Read the actual Singles_enriched_v3.csv and confirm every row is
    accounted for. None are silently dropped. listed_price and tcg_url
    are never set."""
    rows = _real_rows(_ENRICHED_CSV)
    ctx = ImportContext(repo=dynamo_repo)
    summary = import_singles(rows, ctx)
    # All 266 rows accounted for (imported + skipped = total):
    assert summary["imported"] + summary["skipped"] == 266
    # At minimum 19 need review (13 low + 6 medium):
    assert summary["needs_review"] >= 19
    # Every stored item: no listed_price, no tcg_url
    items = dynamo_repo.list_inventory()
    assert len(items) == summary["imported"]
    for item in items:
        assert item.listed_price is None, (
            f"listed_price must be None, got {item.listed_price} on {item.item_id}")
        assert item.tcg_url is None, (
            f"tcg_url must be None, got {item.tcg_url} on {item.item_id}")


# =============================================================================
# SINGLES-ONLY IMPORT (scoped guard + scoped sweep)
# The live table holds real shows/debts/payouts/consignors/config that this
# rebuild never re-imports. A Singles-only run must land Singles' inventory and
# transactions under a fresh generation and leave all of that alone — neither
# refused over by the re-import guard nor deleted by the commit sweep.
# =============================================================================

_ENRICHED_HEADER = (
    "Date,Location,Name,Card #,Condition,Market @ purchase,Amount Paid,Sold,"
    "Date Sold,Venmo?,language,matched_set_id,matched_set_name,matched_number,"
    "matched_card_id,match_confidence,match_notes\n"
)

_ENRICHED_ROW = (
    "1/5/2026,Glass,Pikachu,25,LP +,$12.00,$8.00,,,,"
    "EN,base1,Base Set,25,base1-25,high,\n"
)


def _write_enriched(tmp_path, body=_ENRICHED_ROW, header=_ENRICHED_HEADER):
    (tmp_path / SINGLES_ONLY_CSV_NAME).write_text(header + body, encoding="utf-8")


def _seed_default_enriched_catalog_card(repo):
    """Seed the catalog card that ``_ENRICHED_ROW`` references so
    ``run_singles_only_import`` can validate the composite card_id against the
    catalog index it builds from the repo."""
    from datetime import datetime, timezone

    from merlins_collection.models.catalog import CatalogCard
    repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="en:base1-25", name="Pikachu", set_id="base1",
        set_name="Base Set", number="25",
        images={"small": "s", "large": "l"},
        last_synced_at=datetime.now(tz=timezone.utc),
    )])


def _seed_untouchable_business_data(repo):
    """The live post-wipe survivors: every import-owned entity EXCEPT
    inventory_item / transaction. Written under a committed prior generation,
    exactly like the real table's rows."""
    from merlins_collection.models.business import (
        BalanceSheetLine,
        BalanceSheetSection,
        BalanceSheetSnapshot,
        BuyingPolicy,
        CashAccount,
        Debt,
        DebtDirection,
        PaymentMethod,
        Payout,
    )
    repo.set_import_generation("gen-prior")
    repo.put_show(Show(show_id="s1", name="Mint City", date=date(2026, 3, 8)))
    repo.put_debt(Debt(direction=DebtDirection.OWED_TO_US, date=date(2026, 1, 1),
                       amount=Decimal("10"), counterparty="Colin"))
    repo.put_payout(Payout(event="E1", partner="Casey", amount=Decimal("40")))
    repo.put_consignor(Consignor(consignor_id="c1", name="Rylan"))
    repo.put_cash_account(CashAccount(account="venmo", balance=Decimal("10")))
    repo.put_payment_method(PaymentMethod(method="cash"))
    repo.put_buying_policy(BuyingPolicy(product_type="raw",
                                        cash_pct_min=Decimal("60")))
    repo.put_balance_sheet(BalanceSheetSnapshot(
        snapshot_id="beginning", label="beginning", frozen=True,
        lines=[BalanceSheetLine(section=BalanceSheetSection.ASSET,
                                label="Inventory", amount=Decimal("100"))]))
    repo.set_import_generation(None)


_SINGLES_SCOPE = frozenset({"inventory_item", "transaction"})


def _out_of_scope_snapshot(repo) -> list:
    """Every stored row that is NOT inventory/transaction, fully materialized,
    so "untouched" can be proven byte-for-byte rather than by a count."""
    items, kwargs = [], {"ConsistentRead": True}
    while True:
        resp = repo._table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted((i["PK"], i["SK"], repr(sorted(i.items()))) for i in items
                  if i.get("entity") not in _SINGLES_SCOPE)


def test_singles_only_import_runs_despite_other_business_data(tmp_path, dynamo_repo):
    """The whole point: 28 shows / 104 debts / 33 payouts on the live table must
    not refuse a Singles-only run that never touches them. No --force-replace."""
    _seed_untouchable_business_data(dynamo_repo)
    _seed_default_enriched_catalog_card(dynamo_repo)
    _write_enriched(tmp_path)

    summaries = run_singles_only_import(tmp_path, dynamo_repo)

    assert summaries["_committed"] is True
    assert summaries["Singles"]["imported"] == 1
    [item] = dynamo_repo.list_inventory()
    assert item.card_id == "en:base1-25"


def test_singles_only_import_leaves_other_business_data_byte_identical(
        tmp_path, dynamo_repo):
    _seed_untouchable_business_data(dynamo_repo)
    _write_enriched(tmp_path)
    before = _out_of_scope_snapshot(dynamo_repo)
    assert before  # the fixture really did land data

    assert run_singles_only_import(tmp_path, dynamo_repo)["_committed"] is True

    assert _out_of_scope_snapshot(dynamo_repo) == before
    # And spelled out per entity, so a future reader sees WHAT survived:
    assert len(dynamo_repo.list_shows()) == 1
    assert len(dynamo_repo.list_debts()) == 1
    assert len(dynamo_repo.list_payouts()) == 1
    assert len(dynamo_repo.list_consignors()) == 1
    assert len(dynamo_repo.list_cash_accounts()) == 1
    assert len(dynamo_repo.list_payment_methods()) == 1
    assert len(dynamo_repo.list_buying_policies()) == 1
    assert len(dynamo_repo.list_balance_sheets()) == 1


def test_singles_only_import_does_not_reseed_payment_methods(tmp_path, dynamo_repo):
    """payment_method is OUT of the sweep scope, so re-seeding it would strand a
    duplicate copy under the new generation that nothing ever cleans up."""
    _seed_untouchable_business_data(dynamo_repo)
    _write_enriched(tmp_path)
    run_singles_only_import(tmp_path, dynamo_repo)
    assert [m.method for m in dynamo_repo.list_payment_methods()] == ["cash"]


def test_singles_only_import_is_refused_when_inventory_already_exists(
        tmp_path, dynamo_repo, monkeypatch):
    from merlins_collection.models.inventory import RawInventoryItem
    dynamo_repo.put_inventory_item(RawInventoryItem(
        card_id="swsh1-1", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
        finish="normal", condition=Condition.NM))
    _write_enriched(tmp_path)

    def _forbidden(*a, **k):
        raise AssertionError("mutating call reached past the scoped guard")

    monkeypatch.setattr(dynamo_repo, "acquire_import_lock", _forbidden)
    monkeypatch.setattr(dynamo_repo, "set_import_generation", _forbidden)
    monkeypatch.setattr(dynamo_repo, "finalize_import", _forbidden)
    with pytest.raises(ExistingBusinessDataError, match="force-replace"):
        run_singles_only_import(tmp_path, dynamo_repo)
    assert dynamo_repo._import_gen is None


def test_singles_only_import_force_replace_proceeds(tmp_path, dynamo_repo):
    from merlins_collection.models.inventory import RawInventoryItem
    dynamo_repo.put_inventory_item(RawInventoryItem(
        card_id="stale-1", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
        finish="normal", condition=Condition.NM))
    _seed_default_enriched_catalog_card(dynamo_repo)
    _write_enriched(tmp_path)
    summaries = run_singles_only_import(tmp_path, dynamo_repo, force_replace=True)
    assert summaries["_committed"] is True
    assert [i.card_id for i in dynamo_repo.list_inventory()] == ["en:base1-25"]


def test_singles_only_import_sweeps_prior_inventory_but_nothing_else(
        tmp_path, dynamo_repo):
    """KNOWN LIMITATION, asserted rather than merely commented: the sweep is
    scoped by ENTITY TYPE, so it removes EVERY prior-generation inventory row —
    including one a future Sealed/Bulk run would have written. Correct today
    (inventory is empty post-wipe and Singles is the only tab in scope); it is
    exactly what must change before a second tab is turned back on."""
    _seed_untouchable_business_data(dynamo_repo)
    from merlins_collection.models.inventory import BulkInventoryItem
    dynamo_repo.set_import_generation("gen-prior")
    dynamo_repo.put_inventory_item(BulkInventoryItem(
        description="lot A", cost_basis=Decimal("10"),
        acquired_at=date(2026, 1, 1)))
    dynamo_repo.set_import_generation(None)
    _write_enriched(tmp_path)

    summaries = run_singles_only_import(tmp_path, dynamo_repo, force_replace=True)

    assert summaries["_committed"] is True
    assert summaries["_removed"] == 1                       # the prior bulk lot
    assert [i.display_name for i in dynamo_repo.list_inventory()] == ["Pikachu #25"]
    assert len(dynamo_repo.list_shows()) == 1               # still untouched


def test_singles_only_import_links_sales_to_shows_already_in_the_table(
        tmp_path, dynamo_repo):
    """The Vending Net tab is not read, so the shows a sale links to come from
    the table. Without this the 28 live shows would silently lose every new
    sale's linkage."""
    _seed_untouchable_business_data(dynamo_repo)
    _write_enriched(tmp_path, body=(
        "1/5/2026,Glass,Pikachu,25,LP +,$12.00,$8.00,$20.00,3/9/2026,,"
        "EN,base1,Base Set,25,base1-25,high,\n"))

    summaries = run_singles_only_import(tmp_path, dynamo_repo)

    assert summaries["Singles"]["sales"] == 1
    [txn] = dynamo_repo.list_transactions(date(2026, 3, 1), date(2026, 3, 31))
    assert txn.show_id == "s1"


def test_singles_only_import_reads_no_other_tab(tmp_path, dynamo_repo):
    _seed_untouchable_business_data(dynamo_repo)
    _write_enriched(tmp_path)
    # Poison every other tab: if any of them is read, the assertions below break.
    _write(tmp_path, "Singles.csv",
           "Date,Location,Name,Card #,Condition\n1/1/2026,Glass,Charizard,4,NM\n")
    _write_bulk_csv(tmp_path, "lot Z,10,25,3/7/2026,No,,\n")
    _write(tmp_path, "Vending Net.csv", "Day,Show,Goal\n3/8/2026,Ghost Show,$500\n")
    _write(tmp_path, "Debts.csv", "Date,Amount,Who,Reason\n1/1/2026,99,Ghost,x\n")

    assert run_singles_only_import(tmp_path, dynamo_repo)["_committed"] is True

    names = [i.display_name for i in dynamo_repo.list_inventory()]
    assert names == ["Pikachu #25"]                       # no Charizard, no lot Z
    assert [s.name for s in dynamo_repo.list_shows()] == ["Mint City"]
    assert [d.counterparty for d in dynamo_repo.list_debts()] == ["Colin"]


def test_singles_only_import_requires_the_enriched_csv(tmp_path, dynamo_repo):
    with pytest.raises(ImportError, match=SINGLES_ONLY_CSV_NAME):
        run_singles_only_import(tmp_path, dynamo_repo)


def test_singles_only_import_rejects_a_non_enriched_csv(tmp_path, dynamo_repo):
    """The plain Singles.csv columns produce the LEGACY fuzzy-match path. Under
    that name it would import silently and wrongly, so the header is checked."""
    (tmp_path / SINGLES_ONLY_CSV_NAME).write_text(
        "Date,Location,Name,Card #,Condition\n1/1/2026,Glass,Pikachu,25,NM\n",
        encoding="utf-8")
    with pytest.raises(ImportError, match="match_confidence"):
        run_singles_only_import(tmp_path, dynamo_repo)


def test_singles_only_import_fails_closed_on_zero_rows(tmp_path, dynamo_repo):
    """A truncated export must not commit — that would sweep the prior
    inventory generation and reload nothing."""
    _seed_untouchable_business_data(dynamo_repo)
    from merlins_collection.models.inventory import RawInventoryItem
    dynamo_repo.set_import_generation("gen-prior")
    dynamo_repo.put_inventory_item(RawInventoryItem(
        card_id="survivor-1", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
        finish="normal", condition=Condition.NM))
    dynamo_repo.set_import_generation(None)
    _write_enriched(tmp_path, body="")

    summaries = run_singles_only_import(tmp_path, dynamo_repo, force_replace=True)

    assert summaries["_committed"] is False
    assert [i.card_id for i in dynamo_repo.list_inventory()] == ["survivor-1"]
    assert len(dynamo_repo.list_shows()) == 1


def test_singles_only_import_releases_the_lock(tmp_path, dynamo_repo):
    _write_enriched(tmp_path)
    run_singles_only_import(tmp_path, dynamo_repo)
    dynamo_repo.acquire_import_lock("gen-after")  # no ImportInProgressError
    dynamo_repo.release_import_lock("gen-after")


# ---- regression guards: the full-import path is scoped by NOBODY ------------

def test_full_import_still_probes_and_sweeps_every_entity(tmp_path, dynamo_repo,
                                                          monkeypatch):
    """The existing CLI path must be byte-identical in behavior: an UNSCOPED
    guard and an UNSCOPED sweep. Same spirit as the seed_catalog fix's "English
    keeps its stricter floor" test — this fails if the new scoping leaks in."""
    _seed_workbook(tmp_path)
    probe_kwargs, finalize_kwargs = [], []
    real_probe = dynamo_repo.find_import_owned_entity
    real_finalize = dynamo_repo.finalize_import

    def _probe(**kwargs):
        probe_kwargs.append(kwargs)
        return real_probe(**kwargs)

    def _finalize(gen, **kwargs):
        finalize_kwargs.append(kwargs)
        return real_finalize(gen, **kwargs)

    monkeypatch.setattr(dynamo_repo, "find_import_owned_entity", _probe)
    monkeypatch.setattr(dynamo_repo, "finalize_import", _finalize)
    assert run_import(tmp_path, dynamo_repo, require_complete=False)["_committed"]

    assert probe_kwargs == [{}]                       # no entities= narrowing
    assert finalize_kwargs == [{"committed": True}]   # no entity_scope= narrowing
