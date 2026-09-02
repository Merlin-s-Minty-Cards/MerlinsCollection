"""RED for RFC 0018 item 6a — `get_profit_summary`'s arithmetic.

Tested here, in Python, at the service layer — which is the whole reason the
admin MCP server is a Python process (roadmap item 4). Every money figure comes
from `services/ledger.countable` and the existing `summarize_transactions`, by
IMPORT, so there is no second definition of countability to drift.

The tests that matter are the ones about what must NOT be counted.
"""

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import (
    ItemCategory,
    Transaction,
    TransactionType,
)
from merlins_collection.services import admin_analytics


def _txn(
    txn_id: str,
    type_: TransactionType,
    amount: str,
    *,
    day: date = date(2026, 7, 15),
    item_id: str = "item-1",
    voided: bool = False,
    trade_id: str | None = None,
    show_id: str | None = None,
) -> Transaction:
    return Transaction(
        txn_id=txn_id,
        type=type_,
        item_id=item_id,
        category=ItemCategory.RAW,
        date=day,
        amount=Decimal(amount),
        payment_method="cash",
        trade_id=trade_id,
        show_id=show_id,
        voided_at="2026-08-01T00:00:00+00:00" if voided else None,
    )


@pytest.fixture
def seeded(dynamo_repo):
    """Two sales and one purchase in July; one voided sale that counts for nothing."""
    for txn in [
        _txn("t1", TransactionType.SALE, "300"),
        _txn("t2", TransactionType.SALE, "200", item_id="item-2"),
        _txn("t3", TransactionType.PURCHASE, "180", item_id="item-3"),
        _txn("t4", TransactionType.SALE, "999", item_id="item-4", voided=True),
    ]:
        dynamo_repo.put_transaction(txn)
    return dynamo_repo


def test_a_voided_sale_counts_toward_nothing(seeded):
    """THE test. A void is a record that something was written and withdrawn.

    $999 of voided sales must not appear in gross, net or the sold count. If
    this ever passes while the figure includes it, the analyst chat and the
    Analytics tab are two sets of books disagreeing by exactly one sale.
    """
    summary = admin_analytics.profit_summary(
        seeded, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )

    assert summary["gross_sales"] == Decimal("500")   # 300 + 200, NOT 1499
    assert summary["items_sold"] == 2
    assert summary["total_purchases"] == Decimal("180")
    assert summary["net"] == Decimal("320")


def test_it_uses_the_one_countability_predicate_rather_than_its_own(seeded):
    """Guard against a future inlined `voided_at is None`.

    CLAUDE.md: "Never let an aggregate inline its own `txn.voided_at is None`
    check." Monkeypatching the shared predicate must change this function's
    answer — if it does not, this module grew a second definition.
    """
    import merlins_collection.services.ledger as ledger

    original = ledger.is_countable
    try:
        ledger.is_countable = lambda txn: True  # count EVERYTHING, voids included
        summary = admin_analytics.profit_summary(
            seeded, start=date(2026, 7, 1), end=date(2026, 7, 31)
        )
    finally:
        ledger.is_countable = original

    assert summary["gross_sales"] == Decimal("1499"), (
        "profit_summary does not route through services.ledger — it has its own "
        "countability check, which is the two-sets-of-books bug"
    )


def test_a_trade_cash_leg_is_not_double_counted(dynamo_repo):
    """Card legs count at agreed value; the cash leg would double the trade."""
    dynamo_repo.put_transaction(
        _txn("tr1", TransactionType.SALE, "100", trade_id="trade-1")
    )
    # The CASH leg of a trade: trades.py writes it with item_id == trade_id,
    # because there is no inventory item behind a pile of cash. Counting it
    # alongside the card legs double-counts the trade.
    dynamo_repo.put_transaction(
        _txn("tr2", TransactionType.SALE, "40", trade_id="trade-1",
             item_id="trade-1")
    )
    summary = admin_analytics.profit_summary(
        dynamo_repo, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    assert summary["trades"] == 1
    assert summary["gross_sales"] == Decimal("100"), (
        "the trade's cash leg was counted alongside its card leg"
    )


def test_an_empty_period_is_zero_not_an_error(dynamo_repo):
    """An honest empty answer, never a crash and never a fabricated number."""
    summary = admin_analytics.profit_summary(
        dynamo_repo, start=date(2020, 1, 1), end=date(2020, 1, 31)
    )
    assert summary["gross_sales"] == Decimal("0")
    assert summary["items_sold"] == 0
    assert summary["margin_pct"] is None, (
        "margin on zero sales is undefined — it must not be reported as 0%"
    )


def test_margin_is_a_percentage_of_gross_not_of_cost(seeded):
    summary = admin_analytics.profit_summary(
        seeded, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    # net 320 / gross 500 = 64%
    assert summary["margin_pct"] == pytest.approx(64.0)


def test_the_period_bounds_are_inclusive(dynamo_repo):
    dynamo_repo.put_transaction(_txn("edge", TransactionType.SALE, "50",
                                     day=date(2026, 7, 31)))
    summary = admin_analytics.profit_summary(
        dynamo_repo, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    assert summary["gross_sales"] == Decimal("50")


# ---- "all time" (owner report 2026-08-28): start/end must be OPTIONAL ----
#
# Asked "what's our most profitable show? / All time", the analyst chat kept
# demanding literal start/end dates. `start`/`end` were required parameters
# with no default, so there was no way to ask for "everything" without the
# model inventing an arbitrary date. These tests pin the fix at the service
# layer; `test_admin_tool_schemas.py` pins it at the layer the model sees.

def test_profit_summary_omits_both_bounds_for_all_time(seeded):
    """Omitting both dates must be a valid call, not a caller error."""
    summary = admin_analytics.profit_summary(seeded, as_of=date(2026, 8, 27))
    assert summary["gross_sales"] == Decimal("500")


def test_all_time_defaults_to_a_generous_but_bounded_lookback(dynamo_repo):
    """"All time" is bounded, deliberately — never an unbounded table walk.

    `list_transactions` queries one DynamoDB partition PER MONTH in the range,
    so an unbounded "start of the universe" default would turn one chat
    message into hundreds of sequential Queries against a 30s Lambda budget.
    Measured against the live table 2026-08-28: the earliest real transaction
    is 2026-01-01 (188 rows total), so a 3-year lookback is a wide safety
    margin today — 36 month-partition queries, comfortably inside the 10s
    per-tool-call timeout even at high per-query latency — while remaining
    cheap. Revisit `_ALL_TIME_LOOKBACK_YEARS` once the ledger is actually
    older than that.
    """
    dynamo_repo.put_transaction(
        _txn("within-window", TransactionType.SALE, "40", day=date(2025, 1, 1))
    )
    dynamo_repo.put_transaction(
        _txn("beyond-window", TransactionType.SALE, "999", day=date(2015, 1, 1))
    )
    summary = admin_analytics.profit_summary(dynamo_repo, as_of=date(2026, 8, 27))
    assert summary["gross_sales"] == Decimal("40")


def test_all_time_still_ends_at_today_when_only_start_is_given(seeded):
    """Omitting just one side must not also blow away the other."""
    summary = admin_analytics.profit_summary(
        seeded, start=date(2026, 7, 1), as_of=date(2026, 8, 27)
    )
    assert summary["gross_sales"] == Decimal("500")


def test_the_defaulted_start_is_reported_back_not_hidden(dynamo_repo):
    """A bounded "all time" must be honest about WHERE it starts.

    Adversarial review on this fix (2026-08-28) flagged that a tool
    description promising "the full all-time summary" becomes a confidently
    wrong answer once the ledger outgrows `_ALL_TIME_LOOKBACK_YEARS` — unless
    the actual computed start date is visible to whoever reads the response.
    It already was (`period["start"]`), this pins that it stays that way: the
    model can always see and surface the real window it used, even when it
    picked the window itself.
    """
    summary = admin_analytics.profit_summary(dynamo_repo, as_of=date(2026, 8, 27))
    assert summary["period"]["start"] == "2023-08-28"  # 3 years back, not "the beginning"
    assert summary["period"]["end"] == "2026-08-27"


# ---- RFC 0018 item 6b: find_aging_stock ----

from merlins_collection.models.inventory import (  # noqa: E402
    Condition,
    ItemStatus,
    RawInventoryItem,
)


def _item(item_id: str, *, days_held: int, value: str = "100",
          status: ItemStatus = ItemStatus.AVAILABLE, location: str | None = "glass"):
    from datetime import timedelta
    return RawInventoryItem(
        item_id=item_id,
        card_id="en:base1-4",
        status=status,
        listed_price=Decimal(value),
        cost_basis=Decimal("10.00"),
        acquired_at=date(2026, 8, 27) - timedelta(days=days_held),
        finish="normal",
        condition=Condition.NM,
        location=location,
        current_market_value=Decimal(value),
    )


@pytest.fixture
def aging_stock(dynamo_repo):
    for item in [
        _item("old-1", days_held=400, value="500"),
        _item("old-2", days_held=200, value="50"),
        _item("fresh", days_held=5, value="900"),
        _item("sold-but-ancient", days_held=999, value="800",
              status=ItemStatus.SOLD),
    ]:
        dynamo_repo.put_inventory_item(item)
    return dynamo_repo


def test_sold_stock_is_never_aging_stock(aging_stock):
    """A sold card is not 'sitting unsold' — it is the opposite of the question.

    The 999-day-old row is the oldest thing in the table, so if the filter is
    missing it lands at the top of every answer and the operator is told to
    discount a card they no longer own.
    """
    rows = admin_analytics.aging_stock(aging_stock, min_days=30, as_of=date(2026, 8, 27))
    assert "sold-but-ancient" not in {r["item_id"] for r in rows}


def test_it_returns_the_oldest_first(aging_stock):
    rows = admin_analytics.aging_stock(aging_stock, min_days=30, as_of=date(2026, 8, 27))
    assert [r["item_id"] for r in rows] == ["old-1", "old-2"]
    assert rows[0]["days_held"] == 400


def test_min_days_excludes_fresh_stock(aging_stock):
    rows = admin_analytics.aging_stock(aging_stock, min_days=300, as_of=date(2026, 8, 27))
    assert [r["item_id"] for r in rows] == ["old-1"]


def test_min_value_filters_by_what_the_card_is_worth(aging_stock):
    rows = admin_analytics.aging_stock(
        aging_stock, min_days=30, min_value=Decimal("100"), as_of=date(2026, 8, 27)
    )
    assert [r["item_id"] for r in rows] == ["old-1"]


def test_every_row_carries_item_id_so_the_panel_can_render_a_real_card(aging_stock):
    """CLAUDE.md's absolute rule reaches the analyst chat through this field.

    A name alone never identifies a card; the panel hydrates from `item_id` to
    show image, name and price. A tool that answered with names would leave the
    operator unable to tell twelve Charizards apart.
    """
    rows = admin_analytics.aging_stock(aging_stock, min_days=30, as_of=date(2026, 8, 27))
    assert rows
    for row in rows:
        assert row["item_id"]


def test_every_held_item_has_an_acquisition_date():
    """`aging_stock` relies on this, so it is pinned rather than assumed.

    The first draft of `aging_stock` carried a `if acquired is None: continue`
    guard. It was DEAD CODE — `acquired_at` is a required, non-optional `date`
    on every inventory model, so a validated item always has one. A guard that
    cannot fire is decoration pretending to be caution (CLAUDE.md says the same
    thing about fields kept "for defense in depth" that nothing reads).

    The guard is gone; this test is what makes removing it safe. If the model
    ever relaxes the field, this goes red and `aging_stock` gets a real
    decision about what an undated item means — rather than silently computing
    `today - None`.
    """
    from merlins_collection.models.inventory import (
        BulkInventoryItem,
        GradedInventoryItem,
        RawInventoryItem,
        SealedInventoryItem,
    )

    for model in (RawInventoryItem, GradedInventoryItem,
                  SealedInventoryItem, BulkInventoryItem):
        field = model.model_fields["acquired_at"]
        assert field.is_required(), f"{model.__name__}.acquired_at became optional"
        assert field.annotation is date, (
            f"{model.__name__}.acquired_at is no longer a plain date"
        )


# ---- RFC 0018 item 6c: get_consignor_position ----

from merlins_collection.models.business import Consignor  # noqa: E402
from merlins_collection.models.inventory import ConsignmentTerms  # noqa: E402


def _consigned(item_id: str, consignor_id: str, *, value: str,
               split: str = "0.20", status: ItemStatus = ItemStatus.AVAILABLE,
               paid_out: bool = False):
    item = _item(item_id, days_held=10, value=value, status=status)
    item.consignment = ConsignmentTerms(
        consignor_id=consignor_id,
        split_percent=Decimal(split),
        paid_out=paid_out,
    )
    return item


@pytest.fixture
def consigned_stock(dynamo_repo):
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Alice"))
    dynamo_repo.put_consignor(Consignor(consignor_id="c2", name="Bob", archived=True))
    for item in [
        _consigned("a1", "c1", value="1000"),
        _consigned("a2", "c1", value="500"),
        _consigned("b1", "c2", value="300"),
        # ours outright — must never appear in anyone's position
        _item("mine", days_held=10, value="9999"),
    ]:
        dynamo_repo.put_inventory_item(item)
    return dynamo_repo


def test_the_consignor_share_is_the_complement_of_OUR_cut(consigned_stock):
    """THE money test. `split_percent` is OUR cut, as a 0-1 fraction.

    `ConsignmentTerms.split_percent` is documented as "our cut as a 0-1
    fraction (0.05 = a 5% cut)". Reading it as the CONSIGNOR's share inverts
    every payout — on a 20% split it would tell Alice she is owed $300 on a
    $1,500 position instead of $1,200, and the error is invisible because both
    numbers look plausible.
    """
    rows = admin_analytics.consignor_position(consigned_stock)
    alice = next(r for r in rows if r["consignor_id"] == "c1")

    assert alice["value_held"] == Decimal("1500")
    assert alice["our_projected_cut"] == Decimal("300")        # 20% of 1500
    assert alice["consignor_projected_share"] == Decimal("1200")  # the other 80%


def test_stock_we_own_outright_never_appears_in_a_consignor_position(consigned_stock):
    rows = admin_analytics.consignor_position(consigned_stock)
    assert all(r["consignor_id"] in {"c1", "c2"} for r in rows)
    assert sum(r["items_held"] for r in rows) == 3


def test_an_archived_consignor_with_stock_is_still_reported(consigned_stock):
    """Archiving is not settlement. Money owed survives a hidden row.

    `/admin/cosigners` hides archived consignors by design, which is exactly
    why the analyst chat must not inherit that filter — "whose stock am I
    holding" is a question about obligations, not about UI tidiness.
    """
    rows = admin_analytics.consignor_position(consigned_stock)
    bob = next((r for r in rows if r["consignor_id"] == "c2"), None)
    assert bob is not None, "an archived consignor's held stock disappeared"
    assert bob["archived"] is True, "the caller is not told the row is archived"


def test_the_consignor_name_is_resolved_not_left_as_an_id(consigned_stock):
    """A ULID is not an answer. CardDetailModal shipped this exact bug once."""
    rows = admin_analytics.consignor_position(consigned_stock)
    assert {r["name"] for r in rows} == {"Alice", "Bob"}


def test_scoping_to_one_consignor_returns_only_that_position(consigned_stock):
    rows = admin_analytics.consignor_position(consigned_stock, consignor_id="c1")
    assert [r["consignor_id"] for r in rows] == ["c1"]


def test_sold_consigned_stock_is_not_counted_as_held(dynamo_repo):
    """Held means held. A sold card is a payout question, not a position."""
    dynamo_repo.put_consignor(Consignor(consignor_id="c9", name="Carol"))
    dynamo_repo.put_inventory_item(_consigned("s1", "c9", value="400"))
    dynamo_repo.put_inventory_item(
        _consigned("s2", "c9", value="600", status=ItemStatus.SOLD)
    )

    rows = admin_analytics.consignor_position(dynamo_repo)
    carol = next(r for r in rows if r["consignor_id"] == "c9")
    assert carol["value_held"] == Decimal("400")
    assert carol["items_held"] == 1


def test_an_unpriced_consigned_item_is_counted_but_never_valued_at_zero(dynamo_repo):
    """An absent price is absent — never $0.00, never a guess.

    Counting it as zero understates what the business is holding for someone
    else, which is the direction that causes an argument.
    """
    dynamo_repo.put_consignor(Consignor(consignor_id="c8", name="Dan"))
    unpriced = _consigned("u1", "c8", value="100")
    unpriced.current_market_value = None
    unpriced.listed_price = None
    dynamo_repo.put_inventory_item(unpriced)

    rows = admin_analytics.consignor_position(dynamo_repo)
    dan = next(r for r in rows if r["consignor_id"] == "c8")
    assert dan["items_held"] == 1
    assert dan["items_unpriced"] == 1
    assert dan["value_held"] == Decimal("0")


# ---- RFC 0018 item 6d: find_pricing_outliers ----

def _priced(item_id: str, *, sticker: str | None, market: str | None,
            status: ItemStatus = ItemStatus.AVAILABLE):
    item = _item(item_id, days_held=10, status=status)
    item.sticker_price = Decimal(sticker) if sticker is not None else None
    item.listed_price = None
    item.current_market_value = Decimal(market) if market is not None else None
    return item


@pytest.fixture
def priced_stock(dynamo_repo):
    for item in [
        _priced("over", sticker="150", market="100"),    # +50%
        _priced("under", sticker="60", market="100"),    # -40%
        _priced("fair", sticker="102", market="100"),    # +2%
        _priced("unpriced", sticker=None, market="100"),
        _priced("no-market", sticker="80", market=None),
        _priced("sold", sticker="900", market="100", status=ItemStatus.SOLD),
    ]:
        dynamo_repo.put_inventory_item(item)
    return dynamo_repo


def test_over_finds_stock_priced_above_market(priced_stock):
    rows = admin_analytics.pricing_outliers(
        priced_stock, direction="over", threshold_pct=20
    )
    assert [r["item_id"] for r in rows] == ["over"]
    assert rows[0]["delta_pct"] == pytest.approx(50.0)


def test_under_finds_stock_priced_below_market(priced_stock):
    rows = admin_analytics.pricing_outliers(
        priced_stock, direction="under", threshold_pct=20
    )
    assert [r["item_id"] for r in rows] == ["under"]
    assert rows[0]["delta_pct"] == pytest.approx(-40.0)


def test_the_threshold_is_a_magnitude_so_direction_alone_decides_the_sign(priced_stock):
    """A -40% item must never satisfy `direction="over"`, whatever the threshold."""
    rows = admin_analytics.pricing_outliers(
        priced_stock, direction="over", threshold_pct=1
    )
    assert "under" not in {r["item_id"] for r in rows}


def test_fairly_priced_stock_is_not_an_outlier(priced_stock):
    rows = admin_analytics.pricing_outliers(
        priced_stock, direction="over", threshold_pct=20
    )
    assert "fair" not in {r["item_id"] for r in rows}


def test_unpriced_is_its_own_direction_not_an_infinite_deviation(priced_stock):
    """An item with no price is a different question from a mispriced one.

    Folding it into "under" by treating an absent price as 0 would report every
    unpriced card as -100% off market and bury the genuinely mispriced ones.
    """
    rows = admin_analytics.pricing_outliers(priced_stock, direction="unpriced")
    assert [r["item_id"] for r in rows] == ["unpriced"]
    assert rows[0]["delta_pct"] is None


def test_an_item_with_no_market_value_cannot_be_an_outlier(priced_stock):
    """No market figure means no comparison — never a division, never a guess."""
    for direction in ("over", "under"):
        rows = admin_analytics.pricing_outliers(
            priced_stock, direction=direction, threshold_pct=1
        )
        assert "no-market" not in {r["item_id"] for r in rows}


def test_sold_stock_is_never_a_pricing_outlier(priced_stock):
    """Repricing a card you no longer own is not an action anyone can take."""
    rows = admin_analytics.pricing_outliers(
        priced_stock, direction="over", threshold_pct=1
    )
    assert "sold" not in {r["item_id"] for r in rows}


def test_an_unknown_direction_is_rejected_rather_than_silently_returning_nothing(
    priced_stock,
):
    """Same rule as `triage_reason` and an unknown sort field: a 422, not a no-op.

    An empty list reads as "no outliers" — a reassuring answer to a question
    that was never actually asked.
    """
    with pytest.raises(ValueError, match="direction"):
        admin_analytics.pricing_outliers(priced_stock, direction="sideways")


def test_a_zero_market_value_does_not_divide_by_zero(dynamo_repo):
    dynamo_repo.put_inventory_item(_priced("zero", sticker="50", market="0"))
    rows = admin_analytics.pricing_outliers(
        dynamo_repo, direction="over", threshold_pct=1
    )
    assert "zero" not in {r["item_id"] for r in rows}


# ---- RFC 0020 item 2: shows_with_analytics ("librarian" tool set, list_shows) ----

from merlins_collection.models.business import (  # noqa: E402
    Show,
    ShowAnalyticsSnapshot,
)


def _show(show_id: str, *, name: str = "Test Show", day: date = date(2026, 3, 14),
          venue: str | None = "Lloyd Center", city: str | None = "Portland, OR",
          archived: bool = False) -> Show:
    return Show(show_id=show_id, name=name, date=day, venue=venue, city=city,
                archived=archived)


def _snapshot(show_id: str, *, day: date = date(2026, 3, 14), total_sold: str = "1830.00",
              total_bought: str = "600.00", net_sales: str = "1230.00",
              items_sold: int = 12, items_bought: int = 4, trades: int = 1,
              stale: bool = False) -> ShowAnalyticsSnapshot:
    return ShowAnalyticsSnapshot(
        show_id=show_id, date=day,
        total_sold=Decimal(total_sold), total_bought=Decimal(total_bought),
        net_sales=Decimal(net_sales),
        items_sold_count=items_sold, items_bought_count=items_bought,
        trades_count=trades, stale=stale,
    )


def test_a_show_with_a_snapshot_reports_renamed_profit_fields(dynamo_repo):
    """Field names must match get_profit_summary's, not ShowAnalyticsSnapshot's own.

    Deliberate renaming at the service-function boundary (RFC 0020): the
    model must see ONE spelling of "gross sales" everywhere in this surface,
    not `total_sold` from one tool and `gross_sales` from another for the
    identical figure.
    """
    dynamo_repo.put_show(_show("s1"))
    dynamo_repo.put_show_analytics(_snapshot("s1"))

    [row] = admin_analytics.shows_with_analytics(dynamo_repo)

    assert row["show_id"] == "s1"
    assert row["has_analytics"] is True
    assert row["gross_sales"] == Decimal("1830.00")
    assert row["total_purchases"] == Decimal("600.00")
    assert row["net_sales"] == Decimal("1230.00")
    assert row["items_sold_count"] == 12
    assert row["items_bought_count"] == 4
    assert row["trades_count"] == 1
    assert row["stale"] is False
    # Field names ShowAnalyticsSnapshot itself uses must NOT leak through —
    # that would be a second, differently-spelled path to the same figure.
    assert "total_sold" not in row
    assert "total_bought" not in row


def test_a_show_with_no_snapshot_is_explicit_about_it_not_silently_zero(dynamo_repo):
    """Absence must never read as "zero profit" — same rule as an absent price."""
    dynamo_repo.put_show(_show("s2"))

    [row] = admin_analytics.shows_with_analytics(dynamo_repo)

    assert row["has_analytics"] is False
    assert row["gross_sales"] is None
    assert row["total_purchases"] is None
    assert row["net_sales"] is None
    assert row["stale"] is False


def test_a_stale_snapshot_is_still_returned_and_flagged(dynamo_repo):
    """A stale figure is more useful than none — same rule as /admin/analytics."""
    dynamo_repo.put_show(_show("s3"))
    dynamo_repo.put_show_analytics(_snapshot("s3", stale=True))

    [row] = admin_analytics.shows_with_analytics(dynamo_repo)

    assert row["has_analytics"] is True
    assert row["stale"] is True
    assert row["gross_sales"] == Decimal("1830.00")


def test_archived_shows_are_included_by_default(dynamo_repo):
    """Unlike GET /admin/shows: most real shows are archived, and this is a
    research tool, not a picker — hiding them by default would hide the
    answer to almost every "which show" question."""
    dynamo_repo.put_show(_show("s4", archived=True))

    rows = admin_analytics.shows_with_analytics(dynamo_repo)

    assert [r["show_id"] for r in rows] == ["s4"]
    assert rows[0]["archived"] is True


def test_include_archived_false_excludes_archived_shows(dynamo_repo):
    dynamo_repo.put_show(_show("s5", archived=True))
    dynamo_repo.put_show(_show("s6", archived=False))

    rows = admin_analytics.shows_with_analytics(dynamo_repo, include_archived=False)

    assert [r["show_id"] for r in rows] == ["s6"]


def test_date_range_filters_shows_inclusively(dynamo_repo):
    dynamo_repo.put_show(_show("early", day=date(2026, 1, 1)))
    dynamo_repo.put_show(_show("in-range", day=date(2026, 3, 14)))
    dynamo_repo.put_show(_show("late", day=date(2026, 6, 1)))

    rows = admin_analytics.shows_with_analytics(
        dynamo_repo, start=date(2026, 2, 1), end=date(2026, 3, 14)
    )

    assert [r["show_id"] for r in rows] == ["in-range"]


def test_limit_keeps_the_most_recent_shows_not_an_arbitrary_slice(dynamo_repo):
    """`repo.list_shows()` is oldest-first; a naive `[:limit]` would silently
    return the OLDEST matching shows for a caller who expects "recent" —
    adversarial review flagged this as undocumented and untested. Sorted
    newest-first before capping, so `limit` means what a "list shows" caller
    would assume it means.
    """
    for i in range(5):
        dynamo_repo.put_show(_show(f"s{i}", day=date(2026, 1, i + 1)))

    rows = admin_analytics.shows_with_analytics(dynamo_repo, limit=2)

    assert [r["show_id"] for r in rows] == ["s4", "s3"]


def test_every_row_carries_identity_fields_for_the_model_to_report(dynamo_repo):
    dynamo_repo.put_show(_show("s7", name="Spring Show", venue="Lloyd Center",
                                city="Portland, OR"))

    [row] = admin_analytics.shows_with_analytics(dynamo_repo)

    assert row["name"] == "Spring Show"
    assert row["date"] == "2026-03-14"
    assert row["venue"] == "Lloyd Center"
    assert row["city"] == "Portland, OR"
    assert row["archived"] is False


# ---- RFC 0020 item 3: raw_transactions (list_transactions) ----
#
# Raw ledger rows for the "librarian" tool set. Every row self-describes
# whether it is safe to sum (`is_countable`, `is_trade_cash_leg`) rather than
# silently including or excluding it, because a raw-listing tool cannot
# assume the model will reconstruct either convention on its own — see
# CLAUDE.md's math-trust-boundary rule and RFC 0020's Detailed Design.


def test_all_time_default_window_matches_profit_summarys(dynamo_repo):
    """"All time" must behave identically across every tool on this surface —
    this reuses the SAME `_ALL_TIME_LOOKBACK_YEARS` window `profit_summary`
    already uses, not a shorter REST-archive-style default.
    """
    dynamo_repo.put_transaction(
        _txn("within-window", TransactionType.SALE, "40", day=date(2025, 1, 1))
    )
    dynamo_repo.put_transaction(
        _txn(
            "beyond-window",
            TransactionType.SALE,
            "999",
            item_id="item-2",
            day=date(2015, 1, 1),
        )
    )

    result = admin_analytics.raw_transactions(dynamo_repo, as_of=date(2026, 8, 27))

    assert {t["txn_id"] for t in result["items"]} == {"within-window"}


def test_show_id_filters_to_one_show(dynamo_repo):
    dynamo_repo.put_transaction(
        _txn("a", TransactionType.SALE, "10", show_id="show-1")
    )
    dynamo_repo.put_transaction(
        _txn("b", TransactionType.SALE, "20", item_id="item-2", show_id="show-2")
    )

    result = admin_analytics.raw_transactions(dynamo_repo, show_id="show-1")

    assert [t["txn_id"] for t in result["items"]] == ["a"]
    assert result["total_matched"] == 1


def test_type_filters_to_one_transaction_type(dynamo_repo):
    dynamo_repo.put_transaction(_txn("sale1", TransactionType.SALE, "10"))
    dynamo_repo.put_transaction(
        _txn("purchase1", TransactionType.PURCHASE, "10", item_id="item-2")
    )

    result = admin_analytics.raw_transactions(dynamo_repo, type="purchase")

    assert [t["txn_id"] for t in result["items"]] == ["purchase1"]


def test_an_unknown_type_is_rejected_rather_than_silently_returning_nothing(
    dynamo_repo,
):
    """Same rule as an unknown `direction` or sort field (adversarial review,
    RFC 0020 item 3): a typo'd `type` must not silently read as "zero
    matching transactions", which is a confidently wrong answer wearing an
    empty list's clothes.
    """
    dynamo_repo.put_transaction(_txn("a", TransactionType.SALE, "10"))

    with pytest.raises(ValueError, match="type"):
        admin_analytics.raw_transactions(dynamo_repo, type="refund")


def test_a_voided_transaction_is_excluded_by_default(dynamo_repo):
    dynamo_repo.put_transaction(_txn("live", TransactionType.SALE, "10"))
    dynamo_repo.put_transaction(
        _txn("void", TransactionType.SALE, "999", item_id="item-2", voided=True)
    )

    result = admin_analytics.raw_transactions(dynamo_repo)

    assert [t["txn_id"] for t in result["items"]] == ["live"]


def test_include_voided_true_returns_it_still_marked_uncountable(dynamo_repo):
    dynamo_repo.put_transaction(
        _txn("void", TransactionType.SALE, "999", voided=True)
    )

    result = admin_analytics.raw_transactions(dynamo_repo, include_voided=True)

    [row] = result["items"]
    assert row["txn_id"] == "void"
    assert row["voided_at"] is not None
    assert row["is_countable"] is False


def test_a_trade_cash_leg_is_flagged_but_its_card_leg_is_not(dynamo_repo):
    dynamo_repo.put_transaction(
        _txn(
            "card-out",
            TransactionType.SALE,
            "25",
            item_id="card-out",
            trade_id="tr-1",
        )
    )
    dynamo_repo.put_transaction(
        _txn("cash", TransactionType.SALE, "5", item_id="tr-1", trade_id="tr-1")
    )

    result = admin_analytics.raw_transactions(dynamo_repo)

    by_id = {t["txn_id"]: t for t in result["items"]}
    assert by_id["card-out"]["is_trade_cash_leg"] is False
    assert by_id["cash"]["is_trade_cash_leg"] is True


def test_total_matched_and_truncated_reflect_a_filtered_set_larger_than_limit(
    dynamo_repo,
):
    for i in range(5):
        dynamo_repo.put_transaction(
            _txn(f"t{i}", TransactionType.SALE, "10", item_id=f"item-{i}")
        )

    result = admin_analytics.raw_transactions(dynamo_repo, limit=2)

    assert result["total_matched"] == 5
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert len(result["items"]) == 2


def test_not_truncated_when_everything_fits(dynamo_repo):
    dynamo_repo.put_transaction(_txn("only", TransactionType.SALE, "10"))

    result = admin_analytics.raw_transactions(dynamo_repo)

    assert result["total_matched"] == 1
    assert result["returned"] == 1
    assert result["truncated"] is False


def test_limit_is_capped_at_100_regardless_of_what_is_requested(dynamo_repo):
    """Never trust a caller-supplied limit past 100 — this feeds a Bedrock
    context window, not a scrollable table (RFC 0020: NOT the REST archive's
    500-row cap)."""
    for i in range(105):
        dynamo_repo.put_transaction(
            _txn(f"t{i}", TransactionType.SALE, "10", item_id=f"item-{i}")
        )

    result = admin_analytics.raw_transactions(dynamo_repo, limit=500)

    assert result["total_matched"] == 105
    assert result["returned"] == 100
    assert len(result["items"]) == 100
    assert result["truncated"] is True


def test_a_negative_limit_is_rejected_rather_than_slicing_off_the_last_row(
    dynamo_repo,
):
    """Adversarial review (RFC 0020 item 3, post-implementation): Python
    slicing treats a negative stop as "all but the last N" —
    `txns[:-1]` on 5 matching rows silently returned 4 with
    `truncated: True`, a plausible-looking but wrong answer instead of a
    caller error. A negative `limit` must be rejected outright.
    """
    dynamo_repo.put_transaction(_txn("a", TransactionType.SALE, "10"))

    with pytest.raises(ValueError, match="limit"):
        admin_analytics.raw_transactions(dynamo_repo, limit=-1)


def test_an_unknown_sort_is_rejected_rather_than_silently_ignored(dynamo_repo):
    """`services.transactions_sort.sort_transactions` itself silently returns
    rows UNTOUCHED on a bad sort string — same as `GET /admin/transactions`,
    where the ROUTER is what turns that into a 422, not the sort helper
    itself (adversarial review, RFC 0020 item 3: the first draft of this plan
    assumed `sort_transactions` raises on its own, which it does not). This
    tool must do that validation itself.
    """
    dynamo_repo.put_transaction(_txn("a", TransactionType.SALE, "10"))

    with pytest.raises(ValueError, match="sort"):
        admin_analytics.raw_transactions(dynamo_repo, sort="not_a_real_field_desc")


def test_default_sort_is_date_then_txn_id_descending(dynamo_repo):
    dynamo_repo.put_transaction(
        _txn("early", TransactionType.SALE, "10", day=date(2026, 1, 1))
    )
    dynamo_repo.put_transaction(
        _txn("late", TransactionType.SALE, "10", item_id="item-2", day=date(2026, 6, 1))
    )

    result = admin_analytics.raw_transactions(dynamo_repo)

    assert [t["txn_id"] for t in result["items"]] == ["late", "early"]


def test_an_explicit_sort_reorders_the_rows(dynamo_repo):
    dynamo_repo.put_transaction(_txn("small", TransactionType.SALE, "5"))
    dynamo_repo.put_transaction(
        _txn("big", TransactionType.SALE, "50", item_id="item-2")
    )

    result = admin_analytics.raw_transactions(dynamo_repo, sort="amount_asc")

    assert [t["txn_id"] for t in result["items"]] == ["small", "big"]


def test_amounts_serialize_as_strings_never_floats(dynamo_repo):
    """Same discipline as the MCP `_json` serializer and CLAUDE.md's money
    rules — a Decimal that leaks through as a float is how a cent goes
    missing."""
    dynamo_repo.put_transaction(_txn("a", TransactionType.SALE, "45.50"))

    [row] = admin_analytics.raw_transactions(dynamo_repo)["items"]

    assert row["amount"] == "45.50"
    assert isinstance(row["amount"], str)


# ---- RFC 0020 item 4: raw_inventory (list_inventory) ----
#
# Raw admin-visible inventory rows for the "librarian" tool set, reusing the
# SAME registries `GET /admin/inventory/search` already validates against
# (`services.inventory_filters`, `services.inventory_sort`) rather than a
# second definition of what a filter or a sort field means.


def test_returns_the_matched_returned_truncated_shape(dynamo_repo):
    dynamo_repo.put_inventory_item(_item("a", days_held=1))
    dynamo_repo.put_inventory_item(_item("b", days_held=1))

    result = admin_analytics.raw_inventory(dynamo_repo)

    assert result["total_matched"] == 2
    assert result["returned"] == 2
    assert result["truncated"] is False
    assert {row["item_id"] for row in result["items"]} == {"a", "b"}


def test_a_filter_narrows_the_result(dynamo_repo):
    dynamo_repo.put_inventory_item(_item("available", days_held=1))
    dynamo_repo.put_inventory_item(
        _item("gone", days_held=1, status=ItemStatus.SOLD)
    )

    result = admin_analytics.raw_inventory(
        dynamo_repo, filters=["status:eq:available"]
    )

    assert [row["item_id"] for row in result["items"]] == ["available"]
    assert result["total_matched"] == 1


def test_an_unknown_filter_field_is_rejected_rather_than_silently_matching_nothing(
    dynamo_repo,
):
    """Same rule as an unknown `type`/`sort`/`direction` elsewhere on this
    surface: a typo'd filter field must not read as "zero matching items"."""
    dynamo_repo.put_inventory_item(_item("a", days_held=1))

    with pytest.raises(ValueError, match="filter"):
        admin_analytics.raw_inventory(dynamo_repo, filters=["not_a_real_field:eq:x"])


def test_a_malformed_filter_triple_is_rejected(dynamo_repo):
    dynamo_repo.put_inventory_item(_item("a", days_held=1))

    with pytest.raises(ValueError, match="filter"):
        admin_analytics.raw_inventory(dynamo_repo, filters=["status:available"])


def test_an_explicit_sort_reorders_inventory_rows(dynamo_repo):
    cheap = _item("cheap", days_held=1, value="10")
    cheap.cost_basis = Decimal("10.00")
    pricey = _item("pricey", days_held=1, value="10")
    pricey.cost_basis = Decimal("500.00")
    dynamo_repo.put_inventory_item(cheap)
    dynamo_repo.put_inventory_item(pricey)

    result = admin_analytics.raw_inventory(dynamo_repo, sort="cost_basis_desc")

    assert [row["item_id"] for row in result["items"]] == ["pricey", "cheap"]


def test_an_unknown_inventory_sort_is_rejected_rather_than_silently_ignored(
    dynamo_repo,
):
    dynamo_repo.put_inventory_item(_item("a", days_held=1))

    with pytest.raises(ValueError, match="sort"):
        admin_analytics.raw_inventory(dynamo_repo, sort="not_a_real_field_desc")


def test_consignor_name_sort_is_rejected_for_this_tool(dynamo_repo):
    """`services.inventory_sort.parse_sort` resolves `consignor_name` as a
    real, REST-supported field via a special case that needs a
    `repo.list_consignors()` id->name map (CLAUDE.md's "A `consignor_id`
    filter joined this registry" section) — but `sort_items` given that field
    with no map degrades to "every row treated as missing" (stable, unchanged
    order), which would look like a successful sort that silently did
    nothing. This tool has no signature slot for that map, and the raw
    `consignment.consignor_id` on every row is exactly what a librarian-style
    tool expects the model to cross-reference itself against a separate
    `list_consignors` call — so this field is rejected outright here rather
    than silently degrading.
    """
    dynamo_repo.put_inventory_item(_item("a", days_held=1))

    with pytest.raises(ValueError, match="sort"):
        admin_analytics.raw_inventory(dynamo_repo, sort="consignor_name_desc")


def test_inventory_total_matched_and_truncated_reflect_a_filtered_set_larger_than_limit(
    dynamo_repo,
):
    for i in range(5):
        dynamo_repo.put_inventory_item(_item(f"i{i}", days_held=1))

    result = admin_analytics.raw_inventory(dynamo_repo, limit=2)

    assert result["total_matched"] == 5
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert len(result["items"]) == 2


def test_inventory_limit_is_capped_at_100_regardless_of_what_is_requested(dynamo_repo):
    """Never trust a caller-supplied limit past 100 — this feeds a Bedrock
    context window, and inventory is the LARGEST table in the system."""
    for i in range(105):
        dynamo_repo.put_inventory_item(_item(f"i{i}", days_held=1))

    result = admin_analytics.raw_inventory(dynamo_repo, limit=500)

    assert result["total_matched"] == 105
    assert result["returned"] == 100
    assert len(result["items"]) == 100
    assert result["truncated"] is True


def test_a_negative_inventory_limit_is_rejected(dynamo_repo):
    dynamo_repo.put_inventory_item(_item("a", days_held=1))

    with pytest.raises(ValueError, match="limit"):
        admin_analytics.raw_inventory(dynamo_repo, limit=-1)


def test_money_fields_serialize_as_strings_never_floats(dynamo_repo):
    """Same discipline as `raw_transactions`' identical test — a Decimal that
    leaks through as a float is how a cent goes missing."""
    item = _item("a", days_held=1)
    item.cost_basis = Decimal("120.55")
    dynamo_repo.put_inventory_item(item)

    [row] = admin_analytics.raw_inventory(dynamo_repo)["items"]

    assert row["cost_basis"] == "120.55"
    assert isinstance(row["cost_basis"], str)


def test_name_is_resolved_via_the_one_shared_authority(dynamo_repo):
    """`display_name_override` outranks every other name field (CLAUDE.md,
    "Name resolution: `display_name_override` wins EVERYWHERE") — this tool
    must not inline its own `display_name or product_name` guess."""
    item = _item("a", days_held=1)
    item.display_name = "Base Set Charizard"
    item.display_name_override = "Charizard (English name assigned)"
    dynamo_repo.put_inventory_item(item)

    [row] = admin_analytics.raw_inventory(dynamo_repo)["items"]

    assert row["name"] == "Charizard (English name assigned)"


def test_a_consigned_items_row_carries_the_consignment_field(dynamo_repo):
    """The tool description warns the model to exclude a non-null
    `consignment` row before summing `cost_basis` as the business's own
    capital — that rule only works if the field is actually there to check.
    """
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Alice"))
    consigned = _consigned("a", "c1", value="1000")

    dynamo_repo.put_inventory_item(consigned)
    owned = _item("mine", days_held=1)
    dynamo_repo.put_inventory_item(owned)

    result = admin_analytics.raw_inventory(dynamo_repo)

    by_id = {row["item_id"]: row for row in result["items"]}
    assert by_id["a"]["consignment"]["consignor_id"] == "c1"
    assert by_id["a"]["consignment"]["split_percent"] == "0.20"
    assert by_id["mine"]["consignment"] is None


# ---- RFC 0020 item 5: raw_consignors (list_consignors) ----
#
# Every consignor's identity and default payout_percent, complementing
# get_consignor_position's item-level aggregate. RFC 0020: payout_percent is
# THEIR share as a percent (50 = 50%) — the OPPOSITE convention from
# ConsignmentTerms.split_percent (OUR cut, a 0-1 fraction).


def test_a_row_carries_identity_and_payout_percent(dynamo_repo):
    dynamo_repo.put_consignor(
        Consignor(consignor_id="c1", name="Alice", email="a@example.com",
                  payout_percent=Decimal("60"))
    )

    [row] = admin_analytics.raw_consignors(dynamo_repo)

    assert row["consignor_id"] == "c1"
    assert row["name"] == "Alice"
    assert row["email"] == "a@example.com"
    assert row["payout_percent"] == "60"
    assert isinstance(row["payout_percent"], str)
    assert row["archived"] is False


def test_include_archived_defaults_to_true(dynamo_repo):
    """Archiving is not settlement (CLAUDE.md) — an archived consignor may
    still be owed money, so hiding them by default would hide that."""
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Alice", archived=True))

    rows = admin_analytics.raw_consignors(dynamo_repo)

    assert [r["consignor_id"] for r in rows] == ["c1"]
    assert rows[0]["archived"] is True


def test_include_archived_false_excludes_archived_consignors(dynamo_repo):
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Alice", archived=True))
    dynamo_repo.put_consignor(Consignor(consignor_id="c2", name="Bob"))

    rows = admin_analytics.raw_consignors(dynamo_repo, include_archived=False)

    assert [r["consignor_id"] for r in rows] == ["c2"]


def test_limit_caps_the_number_of_rows_returned(dynamo_repo):
    for i in range(5):
        dynamo_repo.put_consignor(Consignor(consignor_id=f"c{i}", name=f"Person {i}"))

    rows = admin_analytics.raw_consignors(dynamo_repo, limit=2)

    assert len(rows) == 2
