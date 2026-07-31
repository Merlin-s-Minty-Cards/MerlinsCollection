"""Tests for the review-decision applier (``scripts/apply_review_decisions.py``).

Parsing is tested over plain strings; everything that touches DynamoDB runs
against the moto-backed ``dynamo_repo`` fixture. ``scripts/`` is not an
importable package, so the module is loaded straight off disk.

The safety properties this file pins are the whole point of the script: a bare
run must write NOTHING, REJECT/NOCHANGE must write NOTHING even with ``--apply``,
a card_id whose name/set/number disagree with the catalog must be refused, and
applying the same batch twice must be a no-op.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from merlins_collection.models.business import Transaction
from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import GradedInventoryItem, RawInventoryItem

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "apply_review_decisions.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("apply_review_decisions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply_review_decisions"] = module
    spec.loader.exec_module(module)
    return module


ard = _load_script()


# --- write spy -----------------------------------------------------------

class WriteSpy:
    """Wraps a boto3 Table and records every mutating call made through it."""

    MUTATORS = ("put_item", "update_item", "delete_item", "batch_writer",
                "transact_write_items")

    def __init__(self, table):
        self._table = table
        self.writes: list[tuple[str, dict]] = []

    def __getattr__(self, name):
        attr = getattr(self._table, name)
        if name not in self.MUTATORS:
            return attr

        def recorder(*args, **kwargs):
            self.writes.append((name, kwargs))
            return attr(*args, **kwargs)

        return recorder


@pytest.fixture
def spy(dynamo_repo):
    """Replace the repo's table with a recording proxy and hand it back."""
    watcher = WriteSpy(dynamo_repo._table)
    dynamo_repo._table = watcher
    return watcher


# --- fixture builders ----------------------------------------------------

def make_card(card_id="swshp-SWSH068", name="Snorlax",
              set_name="SWSH Black Star Promos", number="SWSH068", set_id="swshp"):
    return CatalogCard(
        card_id=card_id, name=name, set_id=set_id, set_name=set_name, number=number,
        rarity="Promo", types=["Colorless"],
        images=CardImages(small=f"https://img/{card_id}.png",
                          large=f"https://img/{card_id}_hires.png"),
        prices={}, last_synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def make_raw_item(item_id="01ITEM0000000000000000RAW1", **over):
    kw = dict(item_id=item_id, finish="normal", condition="NM",
              cost_basis=Decimal("5"), acquired_at=date(2026, 3, 14),
              needs_review=True, notes="Snorlax #SWSH068")
    kw.update(over)
    return RawInventoryItem(**kw)


def make_graded_item(item_id="01ITEM000000000000000GRAD1", **over):
    kw = dict(item_id=item_id, company="PSA", grade=Decimal("9"),
              cert_number="1400665984", cost_basis=Decimal("50"),
              acquired_at=date(2026, 3, 14), needs_review=True,
              notes="Tyranitar - HS-Unleashed #88")
    kw.update(over)
    return GradedInventoryItem(**kw)


def make_txn(txn_id="01TXN00000000000000000001", **over):
    kw = dict(txn_id=txn_id, type="sale", item_id="01ITEM0000000000000000RAW1",
              category="raw", date=date(2026, 4, 18), amount=Decimal("70"),
              payment_method="cash", show_id="show-1", notes="a sale")
    kw.update(over)
    return Transaction(**kw)


def run(repo, text, *, apply=False):
    """Parse ``text`` and run it, returning the report."""
    parsed = ard.parse_block(text)
    return ard.DecisionApplier(repo, apply=apply).run(parsed)


def actions(report):
    return {(r.decision.kind, r.decision.record_id): r.action for r in report.results}


HEADER = "# MERLIN-REVIEW-V1\n"


# --- parsing -------------------------------------------------------------

def test_parses_every_verb_and_field_shape():
    text = HEADER + "\n".join([
        "CARD i-reject REJECT",
        "CARD i-accept ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
        "set=SWSH Black Star Promos; number=SWSH068; value=229.56",
        "CARD i-set SET card_id=me2pt5-289; name=Steven's Metagross ex; "
        "set=Ascended Heroes; number=289",
        "CARD i-note SET note=(jp) is used to denote the japanese printing of a card",
        "TXN t-nochange NOCHANGE",
        "TXN t-date SET date=2026-04-18",
        "# end: 4 cards, 2 transactions",
    ])
    parsed = ard.parse_block(text)

    assert parsed.errors == []
    by_id = {d.record_id: d for d in parsed.decisions}
    assert len(by_id) == 6
    assert by_id["i-reject"].kind == "CARD"
    assert by_id["i-reject"].verb == "REJECT"
    assert by_id["i-reject"].fields == {}
    assert by_id["i-accept"].fields == {
        "card_id": "swshp-SWSH068", "name": "Snorlax",
        "set": "SWSH Black Star Promos", "number": "SWSH068", "value": "229.56"}
    assert by_id["i-set"].fields["name"] == "Steven's Metagross ex"
    assert by_id["i-note"].fields == {
        "note": "(jp) is used to denote the japanese printing of a card"}
    assert by_id["t-nochange"].kind == "TXN"
    assert by_id["t-date"].fields == {"date": "2026-04-18"}


def test_malformed_lines_are_reported_not_dropped():
    text = HEADER + "\n".join([
        "CARD i-good REJECT",
        "CARD i-missing-verb",
        "WIDGET i-bad-kind ACCEPT",
        "CARD i-bad-verb MAYBE",
        "CARD i-bad-field SET card_id",
    ])
    parsed = ard.parse_block(text)

    assert [d.record_id for d in parsed.decisions] == ["i-good"]
    assert len(parsed.errors) == 4
    joined = " ".join(parsed.errors)
    for token in ("i-missing-verb", "i-bad-kind", "i-bad-verb", "i-bad-field"):
        assert token in joined


def test_block_without_the_version_marker_is_refused():
    parsed = ard.parse_block("CARD i-1 REJECT\n")
    assert parsed.decisions == []
    assert any("MERLIN-REVIEW-V1" in error for error in parsed.errors)


def test_two_decisions_for_the_same_record_are_refused():
    text = HEADER + "CARD i-1 REJECT\nCARD i-1 ACCEPT card_id=x\n"
    parsed = ard.parse_block(text)
    assert parsed.decisions == []
    assert any("i-1" in error and "twice" in error.lower() for error in parsed.errors)


# --- no-write verbs ------------------------------------------------------

def test_reject_and_nochange_write_nothing_even_with_apply(dynamo_repo, spy):
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)
    txn = make_txn()
    dynamo_repo.put_transaction(txn)
    spy.writes.clear()

    text = HEADER + f"CARD {item.item_id} REJECT\nTXN {txn.txn_id} NOCHANGE\n"
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert set(actions(report).values()) == {ard.SKIP_NO_WRITE}
    after = dynamo_repo.get_inventory_item(item.item_id)
    assert after.needs_review is True
    assert after.card_id is None


def test_reject_for_an_item_that_does_not_exist_is_refused(dynamo_repo, spy):
    """A typo'd item_id must not be quietly counted as 'left flagged'."""
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + "CARD 01NOSUCHITEM00000000000000 REJECT\n",
                 apply=True)

    assert spy.writes == []
    assert actions(report) == {("CARD", "01NOSUCHITEM00000000000000"): ard.REFUSED}
    assert report.exit_code != 0


def test_note_only_set_is_reported_and_writes_nothing(dynamo_repo, spy):
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()

    text = HEADER + f"CARD {item.item_id} SET note=(jp) means the japanese printing\n"
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert actions(report) == {("CARD", item.item_id): ard.SKIP_NOTE_ONLY}
    assert report.notes == [(item.item_id, "(jp) means the japanese printing")]
    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.needs_review is True


# --- card validation -----------------------------------------------------

def test_card_accept_with_mismatched_name_is_refused(dynamo_repo, spy):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()

    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=swshp-SWSH068; name=Charizard; "
            f"set=SWSH Black Star Promos; number=SWSH068; value=229.56\n")
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert actions(report) == {("CARD", item.item_id): ard.REFUSED}
    assert "name" in report.results[0].detail
    assert report.exit_code != 0
    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.card_id is None
    assert stored.needs_review is True


def test_card_accept_with_unknown_card_id_or_missing_item_is_refused(dynamo_repo, spy):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()

    text = HEADER + "\n".join([
        f"CARD {item.item_id} ACCEPT card_id=nope-1; name=Snorlax; "
        f"set=SWSH Black Star Promos; number=SWSH068",
        "CARD 01NOSUCHITEM00000000000000 ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
        "set=SWSH Black Star Promos; number=SWSH068",
        "TXN 01NOSUCHTXN000000000000000 SET date=2026-04-18",  # date move: refused
    ])
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert set(actions(report).values()) == {ard.REFUSED}
    assert report.exit_code != 0


def test_card_accept_applies_fields_and_clears_needs_review(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)

    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
            f"set=SWSH Black Star Promos; number=SWSH068; value=229.56\n")
    report = run(dynamo_repo, text, apply=True)

    assert actions(report) == {("CARD", item.item_id): ard.UPDATE}
    assert report.exit_code == 0
    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.card_id == "swshp-SWSH068"
    # BLOCKER-6: the daily sync owns current_market_value, so the applier
    # reports the reviewed figure but does not write it.
    assert stored.current_market_value is None
    assert stored.needs_review is False
    # untouched fields survive
    assert stored.cost_basis == Decimal("5")
    assert stored.notes == "Snorlax #SWSH068"
    # the card link is queryable through GSI1, like a normal repo write
    assert [i.item_id for i in dynamo_repo.list_inventory_for_card("swshp-SWSH068")] \
        == [item.item_id]


def test_card_accept_materializes_display_name_from_the_decision(dynamo_repo):
    """Council MUST-FIX A/C, relink path: when the applier sets identity it also
    writes a structured display_name (from the decision's confirmed name + number),
    so a relinked/backfilled row carries a name too — a robust fallback if the
    catalog META is momentarily missing. Derived from the structured decision
    fields, never from the item's free-text notes."""
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item(display_name=None)
    dynamo_repo.put_inventory_item(item)

    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
            f"set=SWSH Black Star Promos; number=SWSH068\n")
    report = run(dynamo_repo, text, apply=True)

    assert actions(report) == {("CARD", item.item_id): ard.UPDATE}
    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.card_id == "swshp-SWSH068"
    assert stored.display_name == "Snorlax #swsh068"


def test_card_set_without_value_leaves_market_value_alone(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        make_card(card_id="me2pt5-289", name="Steven's Metagross ex",
                  set_name="Ascended Heroes", number="289", set_id="me2pt5")])
    item = make_raw_item(current_market_value=Decimal("12"),
                         notes="Steven's Metagross ex #289")
    dynamo_repo.put_inventory_item(item)

    text = (HEADER + f"CARD {item.item_id} SET card_id=me2pt5-289; "
            f"name=Steven's Metagross ex; set=Ascended Heroes; number=289\n")
    run(dynamo_repo, text, apply=True)

    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.card_id == "me2pt5-289"
    assert stored.current_market_value == Decimal("12")
    assert stored.needs_review is False


def test_name_and_set_comparison_ignores_punctuation_and_dashes(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        make_card(card_id="hgss2-88", name="Tyranitar", set_name="HS-Unleashed",
                  number="88", set_id="hgss2")])
    item = make_graded_item()
    dynamo_repo.put_inventory_item(item)

    # the review page emits an em dash where the catalog stores a hyphen
    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=hgss2-88; name=Tyranitar; "
            f"set=HS—Unleashed; number=88; value=214.33\n")
    report = run(dynamo_repo, text, apply=True)

    assert actions(report) == {("CARD", item.item_id): ard.UPDATE}
    assert dynamo_repo.get_inventory_item(item.item_id).card_id == "hgss2-88"


def test_a_card_id_with_no_confirming_text_is_flagged_as_unconfirmed(dynamo_repo):
    """The review page lets you type a bare card_id. It still has to exist, but
    nothing cross-checks it, and the report has to say so out loud."""
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)

    text = HEADER + f"CARD {item.item_id} SET card_id=swshp-SWSH068\n"
    report = run(dynamo_repo, text, apply=True)

    assert actions(report) == {("CARD", item.item_id): ard.UPDATE}
    assert "UNCONFIRMED" in report.results[0].detail
    assert "Snorlax" in report.results[0].detail
    assert "UNCONFIRMED" in ard.format_report(report)
    assert dynamo_repo.get_inventory_item(item.item_id).card_id == "swshp-SWSH068"


def test_card_id_on_a_kind_that_has_none_is_refused(dynamo_repo, spy):
    from merlins_collection.models.inventory import SealedInventoryItem

    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = SealedInventoryItem(item_id="01ITEM000000000000000SEAL1",
                               product_name="Phantasmal Flames Bundle",
                               product_type="bundle", cost_basis=Decimal("30"),
                               acquired_at=date(2025, 12, 20), needs_review=True)
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()

    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
            f"set=SWSH Black Star Promos; number=SWSH068\n")
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert actions(report) == {("CARD", item.item_id): ard.REFUSED}


def test_unparseable_value_is_refused(dynamo_repo, spy):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    item = make_raw_item()
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()

    text = (HEADER + f"CARD {item.item_id} ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
            f"set=SWSH Black Star Promos; number=SWSH068; value=lots\n")
    report = run(dynamo_repo, text, apply=True)

    assert spy.writes == []
    assert actions(report) == {("CARD", item.item_id): ard.REFUSED}


# --- transactions: no-ops kept, date-move CUT (owner decision) ------------
# The delete-and-reput date-move path was removed entirely after four Council
# rounds failed in it; the 3 batch-01 date typos are fixed by a separate manual
# operation. A TXN SET date= is now REFUSED with a specific message; NOCHANGE and
# REJECT stay no-ops and no longer read the ledger at all.

def test_txn_set_date_is_refused_and_points_to_the_manual_process(dynamo_repo, spy):
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + "TXN 01TXN00000000000000000001 SET "
                 "date=2026-04-18\n", apply=True)
    assert spy.writes == []
    r = report.results[0]
    assert r.action == ard.REFUSED
    detail = r.detail.lower()
    assert "manual" in detail
    assert "no longer" in detail and "move" in detail
    assert report.exit_code == 1


def test_txn_set_date_is_refused_even_with_a_from_pin(dynamo_repo, spy):
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + "TXN 01TXN00000000000000000001 SET "
                 "date=2026-05-01; from=2026-04-18\n", apply=True)
    assert spy.writes == []
    assert report.results[0].action == ard.REFUSED


def test_txn_nochange_and_reject_are_no_ops_without_reading_the_ledger(
        dynamo_repo, spy):
    """The two verbs never wrote; they now also never scan. batch-01's 17
    NOCHANGE + 1 REJECT must parse, count, and write nothing — even for a txn_id
    that is not in the table (no existence probe remains)."""
    spy.writes.clear()
    report = run(dynamo_repo, HEADER
                 + "TXN 01TXN00000000000000000001 NOCHANGE\n"
                 + "TXN 01TXN00000000000000000002 REJECT\n", apply=True)
    assert spy.writes == []
    assert set(actions(report).values()) == {ard.SKIP_NO_WRITE}
    assert report.exit_code == 0


def test_txn_set_without_a_date_is_refused_as_unsupported(dynamo_repo, spy):
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + "TXN 01TXN00000000000000000001 SET "
                 "amount=99\n", apply=True)
    assert spy.writes == []
    assert report.results[0].action == ard.REFUSED


# --- dry run + idempotency ----------------------------------------------

BATCH = """# MERLIN-REVIEW-V1
CARD {raw} ACCEPT card_id=swshp-SWSH068; name=Snorlax; set=SWSH Black Star Promos; \
number=SWSH068; value=229.56
CARD {graded} SET card_id=hgss2-88; name=Tyranitar; set=HS-Unleashed; number=88
CARD {raw2} REJECT
CARD {raw3} SET note=(jp) denotes the japanese printing
TXN {txn2} NOCHANGE
# end: 4 cards, 1 transaction
"""


@pytest.fixture
def seeded(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([
        make_card(),
        make_card(card_id="hgss2-88", name="Tyranitar", set_name="HS-Unleashed",
                  number="88", set_id="hgss2"),
    ])
    items = {
        "raw": make_raw_item("01ITEM0000000000000000RAW1"),
        "raw2": make_raw_item("01ITEM0000000000000000RAW2"),
        "raw3": make_raw_item("01ITEM0000000000000000RAW3"),
        "graded": make_graded_item("01ITEM000000000000000GRAD1"),
    }
    for item in items.values():
        dynamo_repo.put_inventory_item(item)
    txns = {"txn2": make_txn("01TXN00000000000000000002", date=date(2026, 5, 2))}
    text = BATCH.format(**{k: v.item_id for k, v in items.items()},
                        **{k: v.txn_id for k, v in txns.items()})
    return {"text": text, "items": items, "txns": txns}


def _snapshot(repo):
    table = repo._table
    items, kwargs = [], {}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return sorted((i["PK"], i["SK"], repr(sorted(i.items(), key=str))) for i in items)


def test_dry_run_is_the_default_and_writes_nothing(dynamo_repo, spy, seeded):
    spy.writes.clear()
    before = _snapshot(dynamo_repo)

    report = run(dynamo_repo, seeded["text"])  # no apply= -> dry run

    assert spy.writes == []
    assert _snapshot(dynamo_repo) == before
    assert report.dry_run is True
    # it still reports exactly what it *would* do
    planned = actions(report)
    assert planned[("CARD", seeded["items"]["raw"].item_id)] == ard.UPDATE
    assert planned[("TXN", seeded["txns"]["txn2"].txn_id)] == ard.SKIP_NO_WRITE


def test_applying_the_same_batch_twice_writes_nothing_the_second_time(
        dynamo_repo, spy, seeded):
    first = run(dynamo_repo, seeded["text"], apply=True)
    assert first.exit_code == 0
    assert sorted(first.counts.items()) == sorted({
        ard.UPDATE: 2, ard.SKIP_NO_WRITE: 2, ard.SKIP_NOTE_ONLY: 1}.items())
    settled = _snapshot(dynamo_repo)

    spy.writes.clear()
    second = run(dynamo_repo, seeded["text"], apply=True)

    assert spy.writes == []
    assert _snapshot(dynamo_repo) == settled
    assert second.exit_code == 0
    assert second.counts[ard.SKIP_APPLIED] == 2


def test_summary_counts_and_report_text(dynamo_repo, seeded):
    report = run(dynamo_repo, seeded["text"])
    text = ard.format_report(report)

    assert "DRY RUN" in text
    assert seeded["items"]["raw"].item_id in text
    assert "(jp) denotes the japanese printing" in text
    for action in (ard.UPDATE, ard.SKIP_NO_WRITE, ard.SKIP_NOTE_ONLY):
        assert action in text
    assert sum(report.counts.values()) == len(report.results) == 5


def test_catalog_and_unnamed_entities_are_never_touched(dynamo_repo, seeded):
    catalog_before = _snapshot_of_entities(dynamo_repo, {"catalog_card", "price_point"})
    other = make_raw_item("01ITEM00000000000000UNNAMED")
    dynamo_repo.put_inventory_item(other)
    other_before = dynamo_repo.get_inventory_item(other.item_id)

    run(dynamo_repo, seeded["text"], apply=True)

    assert _snapshot_of_entities(dynamo_repo, {"catalog_card", "price_point"}) \
        == catalog_before
    assert dynamo_repo.get_inventory_item(other.item_id) == other_before


def _snapshot_of_entities(repo, entities):
    return sorted(repr(sorted(i.items(), key=str))
                  for i in _scan_all(repo) if i.get("entity") in entities)


def _scan_all(repo):
    items, kwargs = [], {}
    while True:
        response = repo._table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


# --- CLI -----------------------------------------------------------------

def test_cli_without_apply_is_a_dry_run(dynamo_repo, spy, seeded, tmp_path, capsys):
    block = tmp_path / "batch.txt"
    block.write_text(seeded["text"], encoding="utf-8")
    spy.writes.clear()
    before = _snapshot(dynamo_repo)

    code = ard.main([str(block), "--table", "merlins-cards-test", "--region", "us-east-1"])

    assert code == 0
    assert spy.writes == []
    assert _snapshot(dynamo_repo) == before
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed
    assert "--apply" in printed


def test_cli_exit_code_is_nonzero_when_a_row_is_refused(dynamo_repo, tmp_path, capsys):
    block = tmp_path / "batch.txt"
    block.write_text(HEADER + "TXN 01NOSUCHTXN000000000000000 SET date=2026-04-18\n",
                     encoding="utf-8")

    code = ard.main([str(block), "--table", "merlins-cards-test", "--region", "us-east-1"])

    assert code == 1
    assert ard.REFUSED in capsys.readouterr().out


# =========================================================================
# Council R7 acceptance tests
# =========================================================================

# --- BLOCKER-1(b): an English card_id must never land on a non-EN item ---

def test_a_japanese_item_refuses_an_english_card_id(dynamo_repo, spy):
    """The other end of the mislink chain. The review page no longer recommends
    an English card for a Japanese item, but a stale page, a hand-typed id or a
    re-used block can still carry one, and this is the last gate before it
    reaches live money."""
    dynamo_repo.batch_upsert_catalog_cards([make_card("sv3pt5-173", "Pikachu",
                                                      "151", "173")])
    dynamo_repo.put_inventory_item(make_graded_item(
        "01KY8EC7JYF175WA1NKFYESKZV", notes="Pikachu — jp 151 #173.0"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01KY8EC7JYF175WA1NKFYESKZV ACCEPT card_id=sv3pt5-173; name=Pikachu; "
        "set=151; number=173; value=93.50\n"), apply=True)

    assert actions(report) == {("CARD", "01KY8EC7JYF175WA1NKFYESKZV"): ard.REFUSED}
    assert spy.writes == []
    assert report.exit_code == 1
    assert "japanese" in report.results[0].detail.lower()
    item = dynamo_repo.get_inventory_item("01KY8EC7JYF175WA1NKFYESKZV")
    assert item.card_id is None
    assert item.needs_review is True   # NOT cleared - it must stay on the page


def test_the_refusal_works_before_the_backfill_has_stamped_anything(dynamo_repo, spy):
    """Production items carry no ``language`` attribute at all, so the check
    cannot rely on the stored field - it reads the item's own text, exactly like
    the review page does."""
    dynamo_repo.batch_upsert_catalog_cards([make_card("me1-184",
                                                      "Lilies Determination",
                                                      "Mega Evolution", "184")])
    item = make_graded_item("01KY8EC1PRGMR1HW32Z7QSD7J5",
                            notes="Lilies Determination — Mega 1 jp #184.0")
    assert item.language.value == "EN"          # the model default, unstamped
    dynamo_repo.put_inventory_item(item)
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01KY8EC1PRGMR1HW32Z7QSD7J5 ACCEPT card_id=me1-184; "
        "name=Lilies Determination; set=Mega Evolution; number=184\n"), apply=True)
    assert report.results[0].action == ard.REFUSED
    assert spy.writes == []


def test_a_stamped_japanese_item_is_refused_too(dynamo_repo, spy):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item(language="JP"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n"), apply=True)
    assert report.results[0].action == ard.REFUSED
    assert spy.writes == []


def make_jp_card(card_id="sv4a-123", name="Pikachu", set_name="Shiny Treasure EX",
                 number="123", set_id="sv4a"):
    """A JP catalog card — TCGdex now seeds these alongside the EN ones."""
    return CatalogCard(
        card_id=card_id, name=name, set_id=set_id, set_name=set_name, number=number,
        rarity="Rare", types=["Electric"], language=ard.Language.JP,
        images=CardImages(small=f"https://img/{card_id}.png",
                          large=f"https://img/{card_id}_hires.png"),
        prices={}, last_synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_a_japanese_item_accepts_a_matching_japanese_catalog_card(dynamo_repo, spy):
    """Phase 6.1: the catalog is no longer English-only (TCGdex adds JP cards),
    so a JP item linking to a JP catalog card is the CORRECT match and must be
    applied, not refused outright by the old English-only gate."""
    dynamo_repo.batch_upsert_catalog_cards([make_jp_card()])
    dynamo_repo.put_inventory_item(
        make_raw_item(language="JP", notes="Pikachu #123"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=sv4a-123; "
        "name=Pikachu; set=Shiny Treasure EX; number=123\n"), apply=True)

    assert report.results[0].action == ard.UPDATE
    assert dynamo_repo.get_inventory_item(
        "01ITEM0000000000000000RAW1").card_id == "sv4a-123"


def test_a_japanese_item_still_refuses_an_english_catalog_card(dynamo_repo, spy):
    """Regression guard: a cross-language mismatch (JP item, EN card) must
    still be refused — only a matching JP card_id is now accepted."""
    dynamo_repo.batch_upsert_catalog_cards([make_card()])  # default language EN
    dynamo_repo.put_inventory_item(
        make_raw_item(language="JP", notes="Snorlax #SWSH068"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n"), apply=True)

    assert report.results[0].action == ard.REFUSED
    assert spy.writes == []


def test_an_english_item_is_unaffected_by_the_language_gate(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item())
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n"), apply=True)
    assert report.results[0].action == ard.UPDATE
    assert dynamo_repo.get_inventory_item(
        "01ITEM0000000000000000RAW1").card_id == "swshp-SWSH068"


# --- BLOCKER-4: the block must agree with the item's OWN stored text ------

def test_a_block_that_disagrees_with_the_items_own_number_is_refused(dynamo_repo, spy):
    """Live in batch-01: item 01KY8E8EPFV4MMQZ1VG1HZ4P1N stores
    notes='Dark Chairzard #35.0 - 30.0' while the block asserts number=21. R7
    validated only against the catalog, so a transposed item_id that happens to
    exist validated perfectly."""
    dynamo_repo.batch_upsert_catalog_cards([make_card("base5-21", "Dark Charizard",
                                                      "Team Rocket", "21")])
    dynamo_repo.put_inventory_item(make_raw_item(
        "01KY8E8EPFV4MMQZ1VG1HZ4P1N", notes="Dark Chairzard #35.0 — 30.0"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01KY8E8EPFV4MMQZ1VG1HZ4P1N ACCEPT card_id=base5-21; "
        "name=Dark Charizard; set=Team Rocket; number=21\n"), apply=True)
    assert report.results[0].action == ard.REFUSED
    assert "35" in report.results[0].detail   # quotes the item's own number
    assert spy.writes == []


def test_the_operator_can_acknowledge_a_genuine_sheet_correction(dynamo_repo):
    """That row may well be a legitimate fix to a misspelled, mis-numbered sheet
    entry - so the escape hatch is explicit acknowledgement, not silence."""
    dynamo_repo.batch_upsert_catalog_cards([make_card("base5-21", "Dark Charizard",
                                                      "Team Rocket", "21")])
    dynamo_repo.put_inventory_item(make_raw_item(
        "01KY8E8EPFV4MMQZ1VG1HZ4P1N", notes="Dark Chairzard #35.0 — 30.0"))
    report = run(dynamo_repo, HEADER + (
        "CARD 01KY8E8EPFV4MMQZ1VG1HZ4P1N ACCEPT card_id=base5-21; "
        "name=Dark Charizard; set=Team Rocket; number=21; "
        "override=stored-text-mismatch\n"), apply=True)
    assert report.results[0].action == ard.UPDATE
    assert "override" in report.results[0].detail.lower()


def test_a_block_agreeing_with_the_stored_text_needs_no_override(dynamo_repo):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item(notes="Snorlax #SWSH068"))
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n"), apply=True)
    assert report.results[0].action == ard.UPDATE


# --- BLOCKER-9: one normalizer, so an em-dash cannot split the round trip -

def test_the_em_dash_set_name_in_batch_01_compares_equal(dynamo_repo):
    """batch-01 line 8 carries `set=HS-Unleashed` with an EM DASH while the
    catalog stores a hyphen. R7 had two normalizers that disagreed on exactly
    this input."""
    dynamo_repo.batch_upsert_catalog_cards([make_card("hgss2-88", "Tyranitar",
                                                      "HS-Unleashed", "88")])
    dynamo_repo.put_inventory_item(make_graded_item(
        "01KY8E8BH6TK05BTG0RYWD7TDF", notes="Tyranitar — HS-Unleashed #88"))
    report = run(dynamo_repo, HEADER + (
        "CARD 01KY8E8BH6TK05BTG0RYWD7TDF ACCEPT card_id=hgss2-88; name=Tyranitar; "
        "set=HS—Unleashed; number=88\n"), apply=True)
    assert report.results[0].action == ard.UPDATE


def test_both_ends_of_the_round_trip_use_the_same_function():
    from merlins_collection.services import card_text

    assert ard.normalize_name is card_text.normalize_name
    assert ard.normalize_number is card_text.normalize_number


# --- BLOCKER-6: one owner for current_market_value -----------------------

def test_the_applier_does_not_write_the_market_value(dynamo_repo):
    """`refresh_inventory_market_values` overwrites this attribute nightly, so a
    value written here is transient - and on a re-run the applier would write the
    stale review-page figure back over the fresher synced one, oscillating live
    money. The sync owns it; the block's `value` is reported, not stored."""
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item(
        current_market_value=Decimal("300")))
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068; value=229.56\n"),
        apply=True)
    assert report.results[0].action == ard.UPDATE
    item = dynamo_repo.get_inventory_item("01ITEM0000000000000000RAW1")
    assert item.card_id == "swshp-SWSH068"
    assert item.current_market_value == Decimal("300")   # untouched
    assert "229.56" in report.results[0].detail          # but reported


def test_re_running_after_a_sync_is_still_a_no_op(dynamo_repo, spy):
    """R7's idempotency check compared current_market_value, which the sync
    changes - so the second run missed SKIP-already-applied and wrote again."""
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item())
    block = HEADER + ("CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
                      "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068; "
                      "value=229.56\n")
    run(dynamo_repo, block, apply=True)
    # the nightly sync moves the market value
    item = dynamo_repo.get_inventory_item("01ITEM0000000000000000RAW1")
    dynamo_repo.put_inventory_item(item.model_copy(
        update={"current_market_value": Decimal("241.00")}))
    spy.writes.clear()
    report = run(dynamo_repo, block, apply=True)
    assert report.results[0].action == ard.SKIP_APPLIED
    assert spy.writes == []
    assert dynamo_repo.get_inventory_item(
        "01ITEM0000000000000000RAW1").current_market_value == Decimal("241.00")


# --- BLOCKER-3: no unguarded write; the report always prints -------------

def test_one_raising_row_becomes_a_refusal_and_the_batch_continues(
        dynamo_repo, monkeypatch):
    """R7 ran the rows in a bare list comprehension, so a throttle on write 4 of
    7 left three writes on live money data with nothing printed at all."""
    from botocore.exceptions import ClientError

    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    for n in (1, 2):
        dynamo_repo.put_inventory_item(make_raw_item(f"01ITEM000000000000000RAW{n}"))
    calls = {"n": 0}
    real = ard.DecisionApplier._write_card

    def flaky(self, item_id, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceeded",
                                         "Message": "slow down"}}, "UpdateItem")
        return real(self, item_id, *a, **kw)

    monkeypatch.setattr(ard.DecisionApplier, "_write_card", flaky)
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
        "set=SWSH Black Star Promos; number=SWSH068\n"
        "CARD 01ITEM000000000000000RAW2 ACCEPT card_id=swshp-SWSH068; name=Snorlax; "
        "set=SWSH Black Star Promos; number=SWSH068\n"), apply=True)

    assert [r.action for r in report.results] == [ard.REFUSED, ard.UPDATE]
    assert "ProvisionedThroughputExceeded" in report.results[0].detail
    assert report.exit_code == 1
    # the row that could be written, was
    assert dynamo_repo.get_inventory_item(
        "01ITEM000000000000000RAW2").card_id == "swshp-SWSH068"


def test_the_cli_prints_a_report_even_when_the_run_explodes(
        dynamo_repo, tmp_path, capsys, monkeypatch):
    """main() wraps the run in try/finally so a failure outside a single row
    (credentials, the table itself) still prints a report and exits non-zero,
    never leaving the operator with only a traceback."""
    def boom(self, parsed):
        raise RuntimeError("run died")

    monkeypatch.setattr(ard.DecisionApplier, "run", boom)
    path = tmp_path / "b.txt"
    path.write_text(HEADER + "CARD 01ITEM0000000000000000RAW1 REJECT\n",
                    encoding="utf-8")
    code = ard.main([str(path), "--table", "merlins-cards-test",
                     "--region", "us-east-1", "--apply"])
    out = capsys.readouterr().out
    assert code == 1
    assert "run died" in out
    assert "MERLIN-REVIEW-V1" in out       # the report still printed


def test_each_write_is_announced_as_it_lands(dynamo_repo, capsys):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item())
    ard.DecisionApplier(dynamo_repo, apply=True).run(ard.parse_block(
        HEADER + "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
                 "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n"))
    out = capsys.readouterr().out
    assert "01ITEM0000000000000000RAW1" in out
    assert "WROTE" in out


# --- appendix items worth closing while we are here ----------------------

def test_a_utf8_bom_does_not_look_like_a_missing_marker(tmp_path):
    """The block is copied from a browser and hand-saved on Windows."""
    path = tmp_path / "bom.txt"
    path.write_text(HEADER + "CARD 01ITEM0000000000000000RAW1 REJECT\n",
                    encoding="utf-8-sig")
    parsed = ard.parse_block(ard.read_block(path))
    assert parsed.errors == []
    assert len(parsed.decisions) == 1


def test_a_non_numeric_value_cannot_crash_the_batch(dynamo_repo, spy):
    dynamo_repo.batch_upsert_catalog_cards([make_card()])
    dynamo_repo.put_inventory_item(make_raw_item())
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068; value=nan\n"),
        apply=True)
    assert report.results[0].action == ard.REFUSED
    assert spy.writes == []


def test_an_accept_carrying_only_a_note_is_not_silently_downgraded(dynamo_repo):
    dynamo_repo.put_inventory_item(make_raw_item())
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT note=looks right to me\n"))
    assert report.results[0].action == ard.REFUSED


def test_an_identity_check_that_could_pass_vacuously_is_refused(dynamo_repo, spy):
    """S3: two fully non-ASCII names both normalize to '' and compared equal."""
    dynamo_repo.batch_upsert_catalog_cards(
        [make_card("jp-1", "ピカチュウ", "151", "173")])
    dynamo_repo.put_inventory_item(
        make_raw_item(notes="リザードン #173"))
    spy.writes.clear()
    report = run(dynamo_repo, HEADER + (
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=jp-1; "
        "name=リザードン; set=151; number=173\n"), apply=True)
    assert report.results[0].action == ard.REFUSED
    assert spy.writes == []


# --- BLOCKER-4 tuning: the check must not refuse legitimate rows ---------

BATCH_01 = [
    # (item_id, stored notes, block name, block number, expected to pass)
    ("01KY8E6RSRXZXM5GCC81DSEGVH", "Snorlax Prerelease #SWSH068",
     "Snorlax", "SWSH068", True),
    ("01KY8E77MHB14ZYN7F346VJT8A", "Stevens Metagross Ex #289.0",
     "Steven's Metagross ex", "289", True),
    ("01KY8E8BH6TK05BTG0RYWD7TDF", "Tyranitar Prime #88.0 — 90.0",
     "Tyranitar", "88", True),
    ("01KY8E8EPFV4MMQZ1VG1HZ4P1N", "Dark Chairzard #35.0 — 30.0",
     "Dark Charizard", "21", False),
]


@pytest.mark.parametrize("item_id,notes,name,number,agrees", BATCH_01)
def test_the_stored_text_check_against_every_row_of_batch_01(
        item_id, notes, name, number, agrees):
    """Exactly one of tonight's four CARD writes should be stopped by this check.

    The sheet routinely carries qualifiers the catalog name does not, so a strict
    comparison would refuse all four and teach the operator to override blindly.
    """
    values = {"name": name, "number": number}
    item = make_raw_item(item_id, notes=notes)
    mismatch = ard.DecisionApplier._stored_text_mismatch(values, item)
    assert (mismatch == "") is agrees, mismatch


def test_a_qualifier_the_catalog_does_not_carry_is_not_a_disagreement():
    for given, stored in (("Snorlax", "Snorlax Prerelease"),
                          ("Tyranitar", "Tyranitar Prime"),
                          ("Steven's Metagross ex", "Stevens Metagross Ex"),
                          ("Moltres & Zapdos-GX", "Moltres and Zapdos GX")):
        assert ard._texts_agree(given, stored), (given, stored)


def test_a_substituted_word_is_a_disagreement():
    assert not ard._texts_agree("Dark Charizard", "Dark Chairzard")
    assert not ard._texts_agree("Pikachu", "Raichu")


def test_slash_and_padded_numbers_are_the_same_number():
    assert ard._numbers_agree("182", "182/167")
    assert ard._numbers_agree("073/066", "73")
    assert not ard._numbers_agree("21", "35")


# --- BLOCKER-D: a block is bound to the table it was generated against -----

def test_a_block_generated_for_another_table_is_refused(
        dynamo_repo, tmp_path, capsys):
    path = tmp_path / "b.txt"
    path.write_text("# MERLIN-REVIEW-V1\n# table: some-other-table\n"
                    "CARD 01ITEM0000000000000000RAW1 REJECT\n", encoding="utf-8")
    code = ard.main([str(path), "--table", "merlins-cards-test",
                     "--region", "us-east-1", "--apply"])
    out = capsys.readouterr().out
    assert code == 1
    assert "some-other-table" in out
    assert "merlins-cards-test" in out


def test_a_block_bound_to_the_matching_table_proceeds(dynamo_repo):
    dynamo_repo.put_inventory_item(make_raw_item())
    parsed = ard.parse_block(
        "# MERLIN-REVIEW-V1\n# table: merlins-cards-test\n"
        "CARD 01ITEM0000000000000000RAW1 REJECT\n")
    assert parsed.table == "merlins-cards-test"
    report = ard.DecisionApplier(dynamo_repo, apply=True).run(parsed)
    assert report.results[0].action == ard.SKIP_NO_WRITE
    assert report.exit_code == 0


def test_a_block_bound_to_a_different_table_writes_nothing(dynamo_repo, spy):
    dynamo_repo.put_inventory_item(make_raw_item())
    spy.writes.clear()
    parsed = ard.parse_block(
        "# MERLIN-REVIEW-V1\n# table: prod-table\n"
        "CARD 01ITEM0000000000000000RAW1 ACCEPT card_id=swshp-SWSH068; "
        "name=Snorlax; set=SWSH Black Star Promos; number=SWSH068\n")
    report = ard.DecisionApplier(dynamo_repo, apply=True).run(parsed)
    assert spy.writes == []
    assert report.exit_code == 1
    assert any("prod-table" in e for e in report.errors)


def test_a_block_without_a_table_line_still_parses_and_runs(dynamo_repo):
    """Back-compat: a block that predates the binding is not refused outright."""
    dynamo_repo.put_inventory_item(make_raw_item())
    parsed = ard.parse_block(HEADER + "CARD 01ITEM0000000000000000RAW1 REJECT\n")
    assert parsed.table is None
    report = ard.DecisionApplier(dynamo_repo, apply=True).run(parsed)
    assert report.results[0].action == ard.SKIP_NO_WRITE


def test_the_snapshot_timestamp_is_captured_when_present():
    parsed = ard.parse_block(
        "# MERLIN-REVIEW-V1\n# table: t\n# snapshot: 2026-07-23T16:22:48\n"
        "CARD x REJECT\n")
    assert parsed.snapshot == "2026-07-23T16:22:48"

