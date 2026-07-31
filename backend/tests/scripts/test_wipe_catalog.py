"""Tests for the Phase-2 wipe entrypoint (``scripts/wipe_catalog.py``).

This is the only script in the tree that deletes customer-facing data, so most
of what is proven here is refusal: it does nothing without ``--execute``, it
does nothing unless the operator names the target table back, it does not swap
if the load failed, and it does not swap onto an empty catalog.

``scripts/`` is not an importable package, so the module is loaded off disk;
the run goes against moto and a fake TCGdex client, so nothing touches the
network or real AWS.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from merlins_collection.models.business import Consignor, Show
from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import Condition, RawInventoryItem
from merlins_collection.services.tcgdex import LANGUAGE_API_CODE

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wipe_catalog.py"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tcgdex"


def _load_script():
    spec = importlib.util.spec_from_file_location("wipe_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["wipe_catalog"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wipe():
    return _load_script()


class FakeClient:
    """Serves the committed brief fixtures through the client's interface.

    ``rows`` may be a plain list (served for every language) or a dict keyed by
    API language code. The per-language form matters: this fake previously
    ignored its ``language`` argument entirely, which is what hid the fact that a
    single-language run was purging the OTHER language's catalog — every test
    looked language-scoped while none of them actually were.
    """

    def __init__(self, rows=None, sets=None, rows_error=None):
        default = json.loads(
            (FIXTURES / "cards_en_brief.json").read_text(encoding="utf-8")
        )
        self.rows = default if rows is None else rows
        self.sets = sets if sets is not None else [
            {"id": "base1", "name": "Base Set", "cardCount": {"total": 4}}
        ]
        self.rows_error = rows_error
        self.languages_seen = []

    def _rows_for(self, language):
        if isinstance(self.rows, dict):
            return self.rows.get(LANGUAGE_API_CODE[language], [])
        return self.rows

    def list_sets(self, language):
        if isinstance(self.sets, dict):
            return self.sets.get(LANGUAGE_API_CODE[language], [])
        return self.sets

    def iter_brief_cards(self, language):
        self.languages_seen.append(LANGUAGE_API_CODE[language])
        yield from self._rows_for(language)
        if self.rows_error:
            raise self.rows_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wired(wipe, dynamo_repo, monkeypatch):
    """Point the script at moto + a fake client, and seed one language only."""
    monkeypatch.setattr(wipe, "_repository", lambda: dynamo_repo)
    monkeypatch.setattr(wipe, "_client", lambda: FakeClient())
    monkeypatch.setattr(wipe.settings, "dynamodb_table_name", "merlins-cards-test")
    return wipe


def _stale_table(repo):
    """A table holding the OLD world: dead catalog, holdings, and master data."""
    repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="xy7-54", name="Gengar EX", set_id="xy7", set_name="Ancient Origins",
        number="54", last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )])
    repo.put_inventory_item(RawInventoryItem(
        card_id="xy7-54", listed_price=Decimal("10"), cost_basis=Decimal("4"),
        acquired_at=_date(2026, 1, 1), finish="holofoil", condition=Condition("NM"),
    ))
    repo.put_show(Show(show_id="s1", name="Mint City", date=_date(2026, 3, 8)))
    repo.put_consignor(Consignor(consignor_id="c1", name="Rylan"))


ARGS = ["--language", "en", "--execute", "--confirm-table", "merlins-cards-test"]


# ---------------------------------------------------------------------------
# 2.0b — the confirmation rail
# ---------------------------------------------------------------------------


def test_the_wipe_is_a_dry_run_by_default(wired, dynamo_repo, capsys):
    _stale_table(dynamo_repo)

    assert wired.main(["--language", "en"]) == 0

    assert dynamo_repo.get_catalog_card("xy7-54") is not None
    assert len(dynamo_repo.list_inventory()) == 1
    assert dynamo_repo.get_catalog_card("en:base1-4") is None  # nothing loaded either
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "catalog_card" in out  # it reports what WOULD go


def test_the_wipe_refuses_to_execute_without_the_table_named_back(wired, dynamo_repo):
    _stale_table(dynamo_repo)

    assert wired.main(["--language", "en", "--execute",
                       "--confirm-table", "merlins-cards"]) == 2

    assert dynamo_repo.get_catalog_card("xy7-54") is not None
    assert len(dynamo_repo.list_inventory()) == 1


def test_the_wipe_refuses_to_execute_with_no_confirmation_at_all(wired, dynamo_repo):
    _stale_table(dynamo_repo)
    assert wired.main(["--language", "en", "--execute"]) == 2
    assert dynamo_repo.get_catalog_card("xy7-54") is not None


# ---------------------------------------------------------------------------
# 2.2 — load, then swap
# ---------------------------------------------------------------------------


def test_the_wipe_loads_the_new_catalog_before_deleting_the_old(wired, dynamo_repo):
    _stale_table(dynamo_repo)

    assert wired.main(ARGS) == 0

    assert dynamo_repo.get_catalog_card("en:base1-4") is not None  # new catalog
    assert dynamo_repo.get_catalog_card("xy7-54") is None          # old catalog
    assert dynamo_repo.list_inventory() == []                      # old holdings
    assert [s.show_id for s in dynamo_repo.list_shows()] == ["s1"]
    assert [c.consignor_id for c in dynamo_repo.list_consignors()] == ["c1"]


def test_a_failed_load_never_reaches_the_swap(wired, dynamo_repo, monkeypatch):
    """Deleting the old catalog because the new one failed to arrive is the one
    outcome this script must never produce."""
    _stale_table(dynamo_repo)
    monkeypatch.setattr(
        wired, "_client", lambda: FakeClient(rows_error=RuntimeError("upstream died")))

    with pytest.raises(RuntimeError):
        wired.main(ARGS)

    assert dynamo_repo.get_catalog_card("xy7-54") is not None
    assert len(dynamo_repo.list_inventory()) == 1


def test_an_aborted_seed_never_reaches_the_swap(wired, dynamo_repo, monkeypatch):
    """The seed's own magnitude rail firing is a failed load, not a green light."""
    _stale_table(dynamo_repo)
    monkeypatch.setattr(wired, "_client", lambda: FakeClient(
        sets=[{"id": "base1", "name": "Base Set", "cardCount": {"total": 4000}}]))

    assert wired.main(ARGS) == 1

    assert dynamo_repo.get_catalog_card("xy7-54") is not None
    assert len(dynamo_repo.list_inventory()) == 1


def test_the_wipe_refuses_to_swap_onto_an_empty_catalog(wired, dynamo_repo, monkeypatch):
    """A source that returns nothing must not be allowed to empty the table."""
    _stale_table(dynamo_repo)
    monkeypatch.setattr(wired, "_client",
                        lambda: FakeClient(rows=[], sets=[{"id": "base1", "name": "B"}]))

    assert wired.main(ARGS + ["--allow-unverified"]) == 1

    assert dynamo_repo.get_catalog_card("xy7-54") is not None
    assert len(dynamo_repo.list_inventory()) == 1


def test_a_single_language_run_does_not_delete_the_other_language(wired, dynamo_repo):
    """`--language en` after a Japanese abort must not wipe the Japanese catalog.

    This is the natural retry move, and it used to exit 0 having silently
    deleted every JP card and its price history.
    """
    _stale_table(dynamo_repo)
    dynamo_repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="ja:sv11b-1", name="ピカチュウ", set_id="ja:sv11b",
        set_name="Shiny Treasure EX", number="1",
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )])

    assert wired.main(ARGS) == 0

    assert dynamo_repo.get_catalog_card("ja:sv11b-1") is not None  # untouched
    assert dynamo_repo.get_catalog_card("en:base1-4") is not None  # reseeded
    assert dynamo_repo.get_catalog_card("xy7-54") is None          # legacy, gone


def test_a_dry_run_predicts_what_would_go_rather_than_the_whole_catalog(
        wired, dynamo_repo, capsys):
    """A dry run writes nothing, so nothing carries the new generation.

    Without being told what the reseed would write, the count is the size of the
    entire catalog — an alarming figure that is not a prediction.
    """
    _stale_table(dynamo_repo)
    # A row the reseed WOULD replace, so it is not lost and must not be counted.
    dynamo_repo.batch_upsert_catalog_cards([CatalogCard(
        card_id="en:base1-4", name="Charizard", set_id="en:base1",
        set_name="Base Set", number="4",
        last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
    )])

    assert wired.main(["--language", "en"]) == 0

    out = capsys.readouterr().out
    # Only the legacy xy7-54 row is genuinely going; en:base1-4 gets replaced.
    assert "catalog_card: 1" in out


# ---------------------------------------------------------------------------
# single-flight
# ---------------------------------------------------------------------------


def test_the_wipe_refuses_to_run_while_an_import_holds_the_lock(wired, dynamo_repo):
    _stale_table(dynamo_repo)
    dynamo_repo.acquire_import_lock("someone-else")

    assert wired.main(ARGS) == 1

    assert dynamo_repo.get_catalog_card("xy7-54") is not None


def test_the_wipe_releases_the_lock_when_it_finishes(wired, dynamo_repo):
    assert wired.main(ARGS) == 0
    dynamo_repo.acquire_import_lock("next-run")  # would raise if still held


def test_the_wipe_releases_the_lock_when_the_load_explodes(wired, dynamo_repo,
                                                           monkeypatch):
    monkeypatch.setattr(
        wired, "_client", lambda: FakeClient(rows_error=RuntimeError("upstream died")))
    with pytest.raises(RuntimeError):
        wired.main(ARGS)
    dynamo_repo.acquire_import_lock("next-run")


def test_the_wipe_stops_stamping_writes_once_it_is_done(wired, dynamo_repo):
    """A leaked catalog generation would silently tag every later write."""
    assert wired.main(ARGS) == 0
    assert dynamo_repo._catalog_gen is None
