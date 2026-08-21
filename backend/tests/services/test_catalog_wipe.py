"""Phase 2 preconditions + the card-data wipe, at the repository level.

Two things are proven here:

* **2.0a — the interleaved write.** ``batch_upsert_catalog_cards`` used to be
  read-decide-write with no condition, so a depth pass landing between the
  decision and the ``put_item`` had its priced row silently overwritten by a
  ``brief`` row. The tests below construct exactly that interleaving.
* **2.2 — the wipe.** ``purge_card_data`` is the swap half of a catalog
  load-then-swap: it removes card data of every generation except the one just
  loaded, and it must not touch business master data (shows, consignors,
  config, auth/rate-limit) or a sale the live app recorded.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from merlins_collection.models.business import Consignor, Show, Transaction
from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import Condition, RawInventoryItem


def _card(card_id="en:base1-4", *, detail="brief", market=None):
    return CatalogCard(
        card_id=card_id, name="Charizard", set_id="en:base1", set_name="Base Set",
        number="4", detail=detail,
        prices=({"holofoil": {"market": Decimal(market)}} if market else {}),
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )


def _raw_item(card_id="en:base1-4"):
    return RawInventoryItem(
        card_id=card_id, listed_price=Decimal("10"), cost_basis=Decimal("4"),
        acquired_at=_date(2026, 1, 1), finish="holofoil", condition=Condition("NM"),
    )


def _point(card_id="en:base1-4"):
    return PricePoint(card_id=card_id, date=_date(2026, 6, 20), source="tcgplayer",
                      kind="raw", finish="holofoil", market=Decimal("12"))


def _txn(**over):
    kw = dict(type="sale", item_id="i-1", category="raw", date=_date(2026, 3, 10),
              amount=Decimal("40.00"), payment_method="cash")
    kw.update(over)
    return Transaction(**kw)


# ---------------------------------------------------------------------------
# 2.0a — the interleaved write
# ---------------------------------------------------------------------------


def test_a_priced_row_is_never_overwritten_by_a_brief_row(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card(detail="full", market="800")])

    preserved = dynamo_repo.batch_upsert_catalog_cards([_card()], preserve_priced=True)

    assert preserved == 1
    kept = dynamo_repo.get_catalog_card("en:base1-4")
    assert kept.detail == "full"
    assert kept.prices["holofoil"].market == Decimal("800")


def test_a_depth_write_landing_after_the_decision_is_not_clobbered(dynamo_repo):
    """The actual race, not just the sequential case.

    ``_catalog_item`` is the last thing the writer does before handing the row
    to DynamoDB, so writing a ``full`` row from inside it reproduces a depth
    pass that lands *after* any pre-read the breadth writer might have done.
    Under check-then-act the brief row wins and the prices are gone; under a
    ``ConditionExpression`` the write is refused because the condition is
    evaluated at write time, inside the same operation.
    """
    original = dynamo_repo._catalog_item
    depth_row = original(_card(detail="full", market="800"))

    def racing(card):
        item = original(card)
        dynamo_repo._table.put_item(Item=depth_row)  # the depth pass lands here
        return item

    dynamo_repo._catalog_item = racing
    preserved = dynamo_repo.batch_upsert_catalog_cards([_card()], preserve_priced=True)

    assert preserved == 1
    kept = dynamo_repo.get_catalog_card("en:base1-4")
    assert kept.detail == "full"
    assert kept.prices["holofoil"].market == Decimal("800")


def test_preserve_priced_still_writes_rows_that_are_not_priced(dynamo_repo):
    preserved = dynamo_repo.batch_upsert_catalog_cards(
        [_card("en:base1-1"), _card("en:base1-2")], preserve_priced=True
    )
    assert preserved == 0
    assert dynamo_repo.get_catalog_card("en:base1-1") is not None
    assert dynamo_repo.get_catalog_card("en:base1-2") is not None


def test_a_preserved_priced_row_is_carried_into_the_new_generation(dynamo_repo):
    """Otherwise "preserve" and "swap" cancel out into data loss.

    A row the conditional write declines to overwrite keeps its OLD generation
    stamp, so the swap that follows would delete it — leaving neither the new
    row nor the old one. The refusal has to re-stamp the survivor.
    """
    dynamo_repo.batch_upsert_catalog_cards([_card(detail="full", market="800")])

    dynamo_repo.set_catalog_generation("G2")
    preserved = dynamo_repo.batch_upsert_catalog_cards([_card()], preserve_priced=True)
    dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)
    dynamo_repo.set_catalog_generation(None)

    assert preserved == 1
    kept = dynamo_repo.get_catalog_card("en:base1-4")
    assert kept is not None and kept.detail == "full"


def test_the_default_write_path_still_overwrites(dynamo_repo):
    """The depth pass legitimately replaces a row; only breadth is conditional."""
    dynamo_repo.batch_upsert_catalog_cards([_card(detail="full", market="800")])
    dynamo_repo.batch_upsert_catalog_cards([_card(detail="full", market="900")])
    assert dynamo_repo.get_catalog_card("en:base1-4").prices["holofoil"].market == 900


# ---------------------------------------------------------------------------
# 2.2 — the wipe
# ---------------------------------------------------------------------------


def test_purge_removes_card_data_of_every_other_generation(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card("old-1")])   # no generation
    dynamo_repo.put_inventory_item(_raw_item("old-1"))

    dynamo_repo.set_catalog_generation("G2")
    dynamo_repo.batch_upsert_catalog_cards([_card("new-1")])
    dynamo_repo.set_catalog_generation(None)

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    assert dynamo_repo.get_catalog_card("new-1") is not None
    assert dynamo_repo.get_catalog_card("old-1") is None
    assert dynamo_repo.list_inventory() == []
    assert counts["catalog_card"] == 1
    assert counts["inventory_item"] == 1


def test_purge_never_deletes_card_price_history(dynamo_repo):
    """RFC 0015: a card's TCGdex id doesn't change across a reseed, so its
    accumulated price trail is still valid even when the `catalog_card` row
    itself gets swept as belonging to a superseded generation. Unlike
    `catalog_card`, TCGdex has no way to reconstruct history once it's gone —
    deleting it here would be a real, unrecoverable loss for zero benefit.
    """
    dynamo_repo.batch_upsert_catalog_cards([_card("old-1")])   # no generation
    dynamo_repo.append_price_points([_point("old-1")])

    dynamo_repo.set_catalog_generation("G2")
    dynamo_repo.batch_upsert_catalog_cards([_card("new-1")])
    dynamo_repo.set_catalog_generation(None)

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    assert dynamo_repo.get_catalog_card("old-1") is None     # catalog identity IS swept
    assert dynamo_repo.get_price_history("old-1") != []      # its price history is NOT
    assert "price_point" not in counts


def test_purge_preserves_business_master_data(dynamo_repo):
    dynamo_repo.put_show(Show(show_id="s1", name="Mint City", date=_date(2026, 3, 8)))
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Rylan"))
    dynamo_repo.batch_upsert_catalog_cards([_card("old-1")])

    dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    assert [s.show_id for s in dynamo_repo.list_shows()] == ["s1"]
    assert [c.consignor_id for c in dynamo_repo.list_consignors()] == ["c1"]


def test_purge_removes_sheet_derived_sales_but_not_app_recorded_ones(dynamo_repo):
    """D4 scopes the wipe to "sale/transaction records derived from the sheet".

    An import stamps every row it writes with its generation; a sale the live
    app recorded carries none. That stamp is the only durable evidence of which
    writer produced a transaction, so it is what the purge keys on.
    """
    dynamo_repo.set_import_generation("IMPORT1")
    dynamo_repo.put_transaction(_txn(txn_id="from-sheet"))
    dynamo_repo.set_import_generation(None)
    dynamo_repo.put_transaction(_txn(txn_id="from-app"))

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    surviving = dynamo_repo.list_transactions(_date(2026, 1, 1), _date(2026, 12, 31))
    assert [t.txn_id for t in surviving] == ["from-app"]
    assert counts["transaction"] == 1


def test_a_dry_run_reports_what_would_be_deleted_and_deletes_nothing(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([_card("old-1")])
    dynamo_repo.put_inventory_item(_raw_item("old-1"))

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=True)

    assert counts["catalog_card"] == 1
    assert counts["inventory_item"] == 1
    assert dynamo_repo.get_catalog_card("old-1") is not None
    assert len(dynamo_repo.list_inventory()) == 1


def test_purge_never_deletes_hand_entered_graded_prices(dynamo_repo):
    """Graded slab values are hand-curated and NOT reseedable.

    TCGdex cannot recreate them, and D4 never lists ``graded_price`` for
    deletion. Their only writer never stamps a catalog generation, so any
    "keep if stamped" rule deletes all of them on every run, forever.
    """
    dynamo_repo.set_graded_market_value("en:base1-4", "PSA", "10", Decimal("800"))

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    assert dynamo_repo.get_graded_market_value("en:base1-4", "PSA", "10") is not None
    assert "graded_price" not in counts


def test_purge_never_deletes_sealed_or_bulk_price_history(dynamo_repo):
    """``item_price_point`` is the only price history sealed/bulk items have.

    There is no card to re-derive it from and no reseed path that rebuilds it.
    """
    dynamo_repo.append_item_price_point("i-1", _date(2026, 6, 20), Decimal("55"))

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", dry_run=False)

    assert len(dynamo_repo.get_item_price_history("i-1")) == 1
    assert "item_price_point" not in counts


def test_purge_leaves_another_languages_catalog_alone(dynamo_repo):
    """A single-language reseed must not delete the language it did not touch."""
    dynamo_repo.batch_upsert_catalog_cards([_card("ja:sv11b-1")])
    dynamo_repo.append_price_points([_point("ja:sv11b-1")])
    dynamo_repo.batch_upsert_catalog_cards([_card("en:base1-9")])  # in scope, stale

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2", languages={"en"},
                                         dry_run=False)

    assert dynamo_repo.get_catalog_card("ja:sv11b-1") is not None
    assert dynamo_repo.get_price_history("ja:sv11b-1") != []
    assert dynamo_repo.get_catalog_card("en:base1-9") is None
    assert counts["catalog_card"] == 1


def test_purge_still_removes_legacy_rows_that_carry_no_language_prefix(dynamo_repo):
    """The dead pokemontcg.io catalog is exactly what the wipe exists to remove.

    Those ids ("xy7-54") predate the language-composite scheme, so they belong to
    no language and must not be rescued by language scoping.
    """
    dynamo_repo.batch_upsert_catalog_cards([_card("xy7-54")])

    dynamo_repo.purge_card_data(keep_catalog_gen="G2", languages={"en"},
                                dry_run=False)

    assert dynamo_repo.get_catalog_card("xy7-54") is None


def test_a_dry_run_does_not_count_rows_the_reseed_would_replace(dynamo_repo):
    """The dry run is the last safety check before an irreversible wipe.

    Nothing is stamped during a dry run, so without being told what the reseed
    would write, the count is "the entire catalog" — an alarming figure that is
    not a prediction and trains the operator to ignore it.
    """
    dynamo_repo.batch_upsert_catalog_cards([_card("en:base1-4"), _card("en:base1-9")])

    counts = dynamo_repo.purge_card_data(keep_catalog_gen="G2",
                                         keep_card_ids={"en:base1-4"}, dry_run=True)

    assert counts["catalog_card"] == 1  # only the row the reseed would NOT replace


def test_purge_refuses_to_run_without_a_generation_to_keep(dynamo_repo):
    """Without a keep-generation this is not a swap, it is "delete the catalog"."""
    import pytest

    dynamo_repo.batch_upsert_catalog_cards([_card("old-1")])
    with pytest.raises(ValueError, match="keep_catalog_gen"):
        dynamo_repo.purge_card_data(keep_catalog_gen=None, dry_run=False)
    assert dynamo_repo.get_catalog_card("old-1") is not None
