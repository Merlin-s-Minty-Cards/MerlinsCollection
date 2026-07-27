"""Tests for the Tier 1 breadth seed (``scripts/seed_catalog.py``).

``scripts/`` is not an importable package, so the module is loaded straight off
disk. The seed runs against moto via the ``dynamo_repo`` fixture and a fake
client, so nothing here touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from merlins_collection.models.catalog import CatalogCard, FinishPrice
from merlins_collection.models.inventory import Language

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_catalog.py"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tcgdex"


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_catalog"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seed():
    return _load_script()


def _briefs(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeClient:
    """Serves the committed brief fixtures through the client's interface."""

    def __init__(self, rows, sets=None, sets_error=None, rows_error=None):
        self.rows = rows
        self.sets = sets or []
        self.sets_error = sets_error
        self.rows_error = rows_error

    def list_sets(self, language):
        if self.sets_error:
            raise self.sets_error
        return self.sets

    def iter_brief_cards(self, language):
        yield from self.rows
        if self.rows_error:
            raise self.rows_error


def test_seed_writes_language_qualified_identity_rows_with_no_prices(seed, dynamo_repo):
    client = FakeClient(_briefs("cards_en_brief"),
                        sets=[{"id": "base1", "name": "Base Set"}])

    summary = seed.seed_language(dynamo_repo, client, Language.EN, execute=True,
                                 allow_unverified=True)

    assert summary["cards_seeded"] == 4
    assert summary["cards_written"] == 4
    assert summary["failures"] == 0
    card = dynamo_repo.get_catalog_card("en:base1-4")
    assert card.language is Language.EN
    assert card.set_id == "en:base1"
    assert card.set_name == "Base Set"
    assert card.detail == "brief"
    # breadth carries identity only — pricing lives on the detail endpoint
    assert card.prices == {}


# --------------------------------------------------------------------------
# FRAIL-2 — a production writer needs rails
# --------------------------------------------------------------------------


def test_the_seed_is_a_dry_run_unless_execute_is_requested(seed, dynamo_repo):
    """A bare ``python scripts/seed_catalog.py`` writes ~23,444 rows into the
    live table that serves ``/inventory``. It must not do that by default."""
    summary = seed.seed_language(dynamo_repo, FakeClient(_briefs("cards_en_brief")),
                                 Language.EN, allow_unverified=True)
    assert summary["cards_seeded"] == 4
    assert summary["cards_written"] == 0
    assert dynamo_repo.get_catalog_card("en:base1-4") is None


def test_the_seed_refuses_to_overwrite_a_priced_row(seed, dynamo_repo):
    """Once the Phase-2 depth pass has run, a routine re-run of the weekly
    breadth seed would otherwise ``put_item`` every price away and revert
    ``detail`` to ``brief``. Recovery is a full depth re-run."""
    priced = CatalogCard(
        card_id="en:base1-4", language=Language.EN, name="Charizard",
        set_id="en:base1", set_name="Base Set", number="4", detail="full",
        prices={"holofoil": FinishPrice(market=800)},
        last_synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    dynamo_repo.batch_upsert_catalog_cards([priced])

    summary = seed.seed_language(dynamo_repo, FakeClient(_briefs("cards_en_brief")),
                                 Language.EN, execute=True, allow_unverified=True)

    assert summary["cards_preserved"] == 1
    assert summary["cards_written"] == 3
    kept = dynamo_repo.get_catalog_card("en:base1-4")
    assert kept.detail == "full"
    assert kept.prices["holofoil"].market == 800


def test_the_seed_decides_at_write_time_not_by_pre_reading(seed, dynamo_repo):
    """Phase 2.0a: flush must not read-then-decide-then-write.

    A pre-read is a window. Once a depth pass exists, anything landing between
    the ``batch_get`` and the ``batch_upsert`` gets overwritten by a ``brief``
    row and its prices are gone. The refusal has to be a ``ConditionExpression``
    evaluated inside the write itself, which means the pre-read is not merely
    redundant — it must be absent.
    """
    reads = []
    dynamo_repo.batch_get_catalog_cards = lambda ids: reads.append(list(ids)) or {}

    seed.seed_language(dynamo_repo, FakeClient(_briefs("cards_en_brief")),
                       Language.EN, execute=True, allow_unverified=True)

    assert reads == []
    assert dynamo_repo.get_catalog_card("en:base1-4") is not None


def test_an_aborted_run_still_flushes_and_reports_what_it_managed(seed, dynamo_repo):
    """FRAIL-3: an exception from the generator in the ``for`` header used to
    discard up to 499 mapped cards and print no summary, so the operator could
    not tell how far the run got."""
    rows = _briefs("cards_en_brief")
    client = FakeClient(rows, rows_error=RuntimeError("upstream died"))

    with pytest.raises(RuntimeError):
        seed.seed_language(dynamo_repo, client, Language.EN, execute=True,
                           batch_size=1000)

    assert dynamo_repo.get_catalog_card("en:base1-4") is not None


def test_a_wholesale_mapping_failure_aborts_instead_of_reporting_success(seed, dynamo_repo):
    """FRAIL-4: ``{"cards_seeded": 0, "failures": 23444}`` with exit code 0 is
    how a sync stays dead for a week without anyone noticing."""
    rows = [{"localId": str(n), "name": "no id"} for n in range(20)]
    with pytest.raises(seed.SeedAborted, match="failure"):
        seed.seed_language(dynamo_repo, FakeClient(rows), Language.EN, execute=True)


def test_a_truncated_seed_is_caught_by_the_set_card_count_cross_check(seed, dynamo_repo):
    """The magnitude rail: ``list_sets`` already reports how many cards each set
    holds and the seed used to discard it. 4 of 4,000 is not a successful run."""
    client = FakeClient(_briefs("cards_en_brief"),
                        sets=[{"id": "base1", "name": "Base Set",
                               "cardCount": {"total": 4000}}])
    with pytest.raises(seed.SeedAborted, match="short"):
        seed.seed_language(dynamo_repo, client, Language.EN, execute=True)


def test_a_run_that_cannot_confirm_its_size_refuses_to_report_success(seed, dynamo_repo):
    """LOGIC-1: when ``list_sets`` fails the magnitude rail is not merely leaky,
    it is fully disarmed — ``expected is None`` makes the comparison a no-op. A
    struggling free API degrades both endpoints together, so a truncated
    ``/cards`` walk plus a failed ``/sets`` used to produce a short catalog with
    exit code 0. Unverifiable must fail loud, not pass quietly."""
    client = FakeClient(_briefs("cards_en_brief"), sets_error=RuntimeError("503"))
    with pytest.raises(seed.SeedAborted, match="could not be verified"):
        seed.seed_language(dynamo_repo, client, Language.EN, execute=True)


def test_an_unverified_run_still_needs_an_explicit_override(seed, dynamo_repo):
    """The escape hatch exists, but the operator has to ask for it by name."""
    client = FakeClient(_briefs("cards_en_brief"), sets_error=RuntimeError("503"))
    summary = seed.seed_language(dynamo_repo, client, Language.EN, execute=True,
                                 allow_unverified=True)
    assert summary["cards_seeded"] == 4
    assert summary["cards_expected"] is None


def test_the_cross_check_passes_when_the_counts_agree(seed, dynamo_repo):
    client = FakeClient(_briefs("cards_en_brief"),
                        sets=[{"id": "base1", "name": "Base Set",
                               "cardCount": {"total": 4}}])
    summary = seed.seed_language(dynamo_repo, client, Language.EN, execute=True)
    assert summary["cards_expected"] == 4


# --------------------------------------------------------------------------
# behaviour preserved from revision 1
# --------------------------------------------------------------------------


def test_seed_stores_a_japanese_card_separately_from_its_english_twin(seed, dynamo_repo):
    seed.seed_language(dynamo_repo, FakeClient(_briefs("cards_ja_brief")),
                       Language.JP, execute=True, allow_unverified=True)
    seed.seed_language(
        dynamo_repo,
        FakeClient([{"id": "M5-001", "localId": "001", "name": "Tropius"}]),
        Language.EN, execute=True, allow_unverified=True,
    )
    assert dynamo_repo.get_catalog_card("ja:M5-001").name == "トロピウス"
    assert dynamo_repo.get_catalog_card("en:M5-001").name == "Tropius"


def test_seed_survives_an_unavailable_set_list(seed, dynamo_repo):
    client = FakeClient(_briefs("cards_en_brief"), sets_error=RuntimeError("503"))
    summary = seed.seed_language(dynamo_repo, client, Language.EN, execute=True,
                                 allow_unverified=True)
    assert summary["cards_seeded"] == 4
    assert summary["cards_expected"] is None  # no cross-check without the set list
    assert dynamo_repo.get_catalog_card("en:base1-4").set_name == ""


def test_seed_counts_a_malformed_row_instead_of_aborting(seed, dynamo_repo):
    rows = [{"localId": "1", "name": "no id"}] + _briefs("cards_ja_brief")
    summary = seed.seed_language(dynamo_repo, FakeClient(rows), Language.JP,
                                 execute=True, max_failure_ratio=0.5,
                                 allow_unverified=True)
    assert summary["failures"] == 1
    assert summary["cards_seeded"] == 3


def test_seed_flushes_in_batches(seed, dynamo_repo):
    rows = _briefs("cards_en_brief")
    summary = seed.seed_language(dynamo_repo, FakeClient(rows), Language.EN,
                                 batch_size=2, execute=True,
                                 allow_unverified=True)
    assert summary["cards_seeded"] == 4
    assert dynamo_repo.get_catalog_card("en:sv09-045") is not None
