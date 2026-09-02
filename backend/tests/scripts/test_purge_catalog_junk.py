"""Tests for ``scripts/purge_catalog_junk.py`` (RFC 0021 T3).

Removes two junk cohorts from the catalog -- TCG Pocket (digital-only) rows
and legacy pokemontcg.io-era rows -- while reporting (never deleting) a third
bucket: a composite id whose language prefix this build does not speak. All
against moto; nothing here touches the network or a real table.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from merlins_collection.models.business import Consignor, Show
from merlins_collection.models.catalog import CatalogCard, PricePoint
from merlins_collection.models.inventory import Condition, Language, RawInventoryItem

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "purge_catalog_junk.py"

TCGP_SERIES = {"id": "tcgp", "name": "Pokémon TCG Pocket",
               "sets": [{"id": "A1"}, {"id": "A2"}]}


def _load_script():
    spec = importlib.util.spec_from_file_location("purge_catalog_junk", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["purge_catalog_junk"] = module
    spec.loader.exec_module(module)
    return module


class StubClient:
    """Serves ``get_series`` only -- everything ``excluded_set_ids`` needs.

    Supports the context-manager protocol because the script does
    ``with TcgdexClient() as client:``, mirroring ``_FakeClient`` in
    ``tests/scripts/test_reprice_catalog.py``.
    """

    def __init__(self, series=None, series_error=None):
        self.series = series or {}
        self.series_error = series_error

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_series(self, language, series_id):
        if self.series_error:
            raise self.series_error
        return self.series.get(language, {}).get(series_id)


def _client(**series_by_language):
    series = {Language.EN: {"tcgp": TCGP_SERIES}}
    series.update(series_by_language)
    return StubClient(series=series)


def _card(card_id, *, set_id=None, set_name="", name="Card", number="1"):
    return CatalogCard(card_id=card_id, name=name, set_id=set_id or card_id,
                       set_name=set_name, number=number,
                       last_synced_at=datetime(2026, 6, 22, tzinfo=timezone.utc))


def _wire(script, monkeypatch, repo, client):
    monkeypatch.setattr(script, "_repository", lambda table, region: repo)
    monkeypatch.setattr(script, "TcgdexClient", lambda *a, **k: client)


def _table_snapshot(repo):
    items = []
    kwargs = {}
    while True:
        resp = repo._table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted(items, key=lambda i: (i["PK"], i["SK"]))


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


def test_a_tcg_pocket_card_is_a_digital_candidate_a_physical_card_is_not(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:A1-1", set_id="en:A1", set_name="Genetic Apex", name="Pikachu (Pocket)"),
        _card("en:base1-4", set_id="en:base1", set_name="Base Set", name="Charizard"),
    ])

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=False)

    assert [c.card_id for c in result["_digital_cards"]] == ["en:A1-1"]
    assert result["digital_candidates"] == 1
    assert result["legacy_candidates"] == 0


def test_a_legacy_row_is_a_candidate_a_composite_row_is_not(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("xy7-54", set_id="xy7", set_name="XY7", name="Old Card"),
        _card("en:base1-4", set_id="en:base1", set_name="Base Set", name="Charizard"),
    ])

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=False)

    assert [c.card_id for c in result["_legacy_cards"]] == ["xy7-54"]
    assert result["legacy_candidates"] == 1
    assert result["digital_candidates"] == 0


def test_an_unknown_language_row_is_reported_not_deleted_even_when_executing(dynamo_repo):
    """RISK: a ':' with an unrecognized prefix must never be purged -- RFC 0023
    taught the build 16 more language codes, and this could still just as
    easily be a hand-seeded row in a language TCGdex itself does not speak.
    This asserts it survives even WITH --execute."""
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        # RFC 0023 landed and taught the build all 18 TCGdex codes, so this
        # must be a language even TCGdex itself does not speak -- "vi" is not
        # one of the 18 codes TCGdex's own 404 validation body enumerates.
        _card("vi:xy7-54", set_id="vi:xy7", set_name="XY7", name="Vietnamese Card"),
    ])

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=True)

    assert result["unknown_language_reported"] == 1
    assert result["digital_candidates"] == 0
    assert result["legacy_candidates"] == 0
    assert result["cards_deleted"] == 0
    assert dynamo_repo.get_catalog_card("vi:xy7-54") is not None


# --------------------------------------------------------------------------
# in-use guard
# --------------------------------------------------------------------------


def test_a_candidate_referenced_by_inventory_is_skipped_and_reported(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("xy7-54", set_id="xy7", set_name="XY7", name="Old Card"),
    ])
    item = RawInventoryItem(
        card_id="xy7-54", listed_price=Decimal("10"), cost_basis=Decimal("4"),
        acquired_at=date(2026, 1, 1), finish="holofoil", condition=Condition.NM,
    )
    dynamo_repo.put_inventory_item(item)

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=True)

    assert result["legacy_candidates"] == 0
    assert result["in_use_skipped"] == 1
    assert result["_in_use"]["xy7-54"] == [item.item_id]
    assert result["cards_deleted"] == 0
    assert dynamo_repo.get_catalog_card("xy7-54") is not None


# --------------------------------------------------------------------------
# dry run / execute rails
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing_at_all(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("xy7-54", set_id="xy7", set_name="XY7", name="Old Card"),
        _card("en:A1-1", set_id="en:A1", set_name="Genetic Apex", name="Pikachu (Pocket)"),
    ])
    before = _table_snapshot(dynamo_repo)

    script.purge_catalog_junk(dynamo_repo, _client(), execute=False)

    assert _table_snapshot(dynamo_repo) == before


def test_execute_without_confirm_table_refuses(dynamo_repo, monkeypatch, capsys):
    script = _load_script()
    _wire(script, monkeypatch, dynamo_repo, _client())

    code = script.main(["--table", "merlins-cards-test", "--execute"])

    assert code == 2
    assert "refusing" in capsys.readouterr().err


def test_execute_with_a_mismatched_confirm_table_refuses(dynamo_repo, monkeypatch, capsys):
    script = _load_script()
    _wire(script, monkeypatch, dynamo_repo, _client())

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "some-other-table"])

    assert code == 2
    assert "refusing" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the whole partition, price children included
# --------------------------------------------------------------------------


def test_execute_deletes_the_whole_partition_price_children_included(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("xy7-54", set_id="xy7", set_name="XY7", name="Old Card"),
    ])
    dynamo_repo.append_price_points([PricePoint(
        card_id="xy7-54", date=date(2026, 1, 1), source="tcgplayer",
        kind="raw", finish="holofoil", market=Decimal("5"),
    )])
    dynamo_repo.set_graded_market_value("xy7-54", "PSA", "10", Decimal("50"))

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=True)

    assert result["cards_deleted"] == 1
    assert result["child_rows_deleted"] == 2  # one PRICE#RAW# row + one GRADEDPRICE# row
    assert dynamo_repo.get_catalog_card("xy7-54") is None
    assert dynamo_repo.get_price_history("xy7-54") == []
    assert dynamo_repo.get_graded_market_value("xy7-54", "PSA", "10") is None


# --------------------------------------------------------------------------
# catalog_set deregistration
# --------------------------------------------------------------------------


def test_a_set_with_an_in_use_survivor_is_kept_a_fully_purged_set_is_deregistered(dynamo_repo):
    script = _load_script()
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:A1-1", set_id="en:A1", set_name="Genetic Apex", name="Pikachu (Pocket)"),
        _card("en:A1-2", set_id="en:A1", set_name="Genetic Apex", name="Bulbasaur (Pocket)"),
        _card("en:A2-1", set_id="en:A2", set_name="Space-Time Smackdown",
             name="Charmander (Pocket)"),
    ])
    dynamo_repo.put_catalog_sets([
        {"set_id": "en:A1", "set_name": "Genetic Apex", "language": "EN",
         "card_count": 2, "updated_at": "2026-01-01T00:00:00+00:00"},
        {"set_id": "en:A2", "set_name": "Space-Time Smackdown", "language": "EN",
         "card_count": 1, "updated_at": "2026-01-01T00:00:00+00:00"},
    ])
    # en:A1-1 is held -- en:A1 must survive with a card and NOT be deregistered.
    dynamo_repo.put_inventory_item(RawInventoryItem(
        card_id="en:A1-1", listed_price=Decimal("10"), cost_basis=Decimal("4"),
        acquired_at=date(2026, 1, 1), finish="normal", condition=Condition.NM,
    ))

    result = script.purge_catalog_junk(dynamo_repo, _client(), execute=True)

    assert result["sets_kept_partial"] == ["en:A1"]
    assert result["sets_deregistered"] == 1
    registry = {s["set_id"] for s in dynamo_repo.list_catalog_sets()}
    assert registry == {"en:A1"}
    assert dynamo_repo.get_catalog_card("en:A1-1") is not None   # in-use survivor
    assert dynamo_repo.get_catalog_card("en:A1-2") is None       # deleted
    assert dynamo_repo.get_catalog_card("en:A2-1") is None       # deleted, set gone


# --------------------------------------------------------------------------
# business master data is untouched
# --------------------------------------------------------------------------


def test_purge_leaves_business_master_data_untouched(dynamo_repo):
    script = _load_script()
    dynamo_repo.put_show(Show(show_id="s1", name="Mint City", date=date(2026, 3, 8)))
    dynamo_repo.put_consignor(Consignor(consignor_id="c1", name="Rylan"))
    dynamo_repo.batch_upsert_catalog_cards([_card("xy7-54", set_id="xy7", set_name="XY7")])

    script.purge_catalog_junk(dynamo_repo, _client(), execute=True)

    assert [s.show_id for s in dynamo_repo.list_shows()] == ["s1"]
    assert [c.consignor_id for c in dynamo_repo.list_consignors()] == ["c1"]
