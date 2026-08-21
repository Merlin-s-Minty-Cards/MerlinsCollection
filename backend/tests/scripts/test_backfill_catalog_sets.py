"""Tests for ``scripts/backfill_catalog_sets.py`` (RFC 0008 T8).

This script exists for a catalog that is ALREADY seeded: ~31,600 card rows
written before the ``catalog_set`` registry existed, which the incremental sync
will never revisit because it deliberately skips any set that already has cards.
It therefore runs exactly once, against live data, with no second chance — which
is the entire reason it is tested rather than eyeballed.

The aggregation is what is pinned here. ``main`` itself is argument parsing plus
printing over the same function.
"""

import io
import sys
from datetime import datetime, timezone

from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import Language

from scripts.backfill_catalog_sets import build_registry_rows, main


def _card(card_id, *, set_id, set_name, language=Language.EN, name="Pikachu"):
    return CatalogCard(
        card_id=card_id,
        language=language,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number="1",
        detail="brief",
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def test_aggregates_one_row_per_set_with_a_real_card_count(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:base1-1", set_id="en:base1", set_name="Base Set"),
        _card("en:base1-2", set_id="en:base1", set_name="Base Set"),
        _card("en:base2-1", set_id="en:base2", set_name="Jungle"),
    ])

    rows = {r["set_id"]: r for r in build_registry_rows(dynamo_repo)}

    assert set(rows) == {"en:base1", "en:base2"}
    assert rows["en:base1"]["card_count"] == 2
    assert rows["en:base1"]["set_name"] == "Base Set"
    assert rows["en:base2"]["card_count"] == 1


def test_keeps_english_and_japanese_sets_apart(dynamo_repo):
    """The two carry the same ``set_name`` and differ only by the language
    prefix on ``set_id`` — which is exactly why the registry stores language."""
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:base1-1", set_id="en:base1", set_name="Base Set"),
        _card("ja:base1-1", set_id="ja:base1", set_name="Base Set",
              language=Language.JP, name="リザードン"),
    ])

    rows = {r["set_id"]: r for r in build_registry_rows(dynamo_repo)}

    assert rows["en:base1"]["language"] == "EN"
    assert rows["ja:base1"]["language"] == "JP"
    assert rows["en:base1"]["card_count"] == 1
    assert rows["ja:base1"]["card_count"] == 1


def test_a_named_row_fills_in_a_set_first_seen_unnamed(dynamo_repo):
    """A brief row seeded while ``list_sets`` was unavailable carries an empty
    ``set_name``. Whichever row the scan happens to reach first must not decide
    the set is nameless forever — the dropdown would show a blank entry."""
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:base1-1", set_id="en:base1", set_name=""),
        _card("en:base1-2", set_id="en:base1", set_name="Base Set"),
    ])

    rows = {r["set_id"]: r for r in build_registry_rows(dynamo_repo)}

    assert rows["en:base1"]["set_name"] == "Base Set"
    assert rows["en:base1"]["card_count"] == 2


def test_an_empty_catalog_produces_no_rows(dynamo_repo):
    """Writing nothing beats writing a registry that claims the catalog is empty."""
    assert build_registry_rows(dynamo_repo) == []


def test_rows_round_trip_through_the_registry_writer(dynamo_repo):
    """The script's output has to be exactly what ``put_catalog_sets`` accepts —
    a shape mismatch here would only surface on the one live run it ever gets."""
    dynamo_repo.batch_upsert_catalog_cards([
        _card("en:base1-1", set_id="en:base1", set_name="Base Set"),
    ])

    rows = build_registry_rows(dynamo_repo)
    assert dynamo_repo.put_catalog_sets(rows) == 1

    stored = dynamo_repo.list_catalog_sets()
    assert [s["set_id"] for s in stored] == ["en:base1"]
    assert stored[0]["set_name"] == "Base Set"
    assert stored[0]["card_count"] == 1
    assert stored[0]["language"] == "EN"


def test_main_writes_even_when_the_console_cannot_encode_a_japanese_set_name(
    dynamo_repo, monkeypatch,
):
    """The listing is printed BEFORE the write, so a console that cannot encode a
    set name kills the run without writing anything.

    Found by running the real script: a Windows console defaults to cp1252, and
    the first Japanese set name raised ``UnicodeEncodeError`` after ~400 English
    sets had scrolled past. The backfill runs exactly once against live data, so
    a crash here is the difference between the Set dropdown working and shipping
    empty.

    This file's own docstring called ``main`` "argument parsing plus printing
    over the same function" and left it untested — printing was the bug.
    """
    dynamo_repo.batch_upsert_catalog_cards([
        _card("ja:sv11b-1", set_id="ja:sv11b", set_name="ブラックボルト",
              language=Language.JP, name="リザードン"),
    ])
    monkeypatch.setattr(
        "scripts.backfill_catalog_sets.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )
    # A console that can encode Latin-1 and nothing else — what MINGW/cmd give
    # you on a default Windows install.
    monkeypatch.setattr(
        sys, "stdout",
        io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict"),
    )

    summary = main(["--execute"])

    assert summary["sets_written"] == 1
    assert [s["set_id"] for s in dynamo_repo.list_catalog_sets()] == ["ja:sv11b"]
