"""Tests for the one-off language backfill (``scripts/backfill_language.py``).

The plan-building half runs over fixture dicts shaped like raw DynamoDB records;
the apply half runs against moto via the ``dynamo_repo`` fixture. ``scripts/`` is
not an importable package, so the module is loaded straight off disk.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_language.py"

TABLE = "merlins-cards-test"
REGION = "us-east-1"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_language", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_language"] = module
    spec.loader.exec_module(module)
    return module


bl = _load_script()


# --- fixture builders (records exactly as the live table holds them) -----

def raw_record(item_id, notes, **over):
    """A live ``inventory_item`` record. Note the deliberate ABSENCE of a
    ``language`` attribute — that is what the 1489 production rows look like."""
    record = {
        "PK": "INV#3", "SK": f"ITEM#{item_id}",
        "entity": "inventory_item", "kind": "raw", "item_id": item_id,
        "status": "available", "card_id": None, "finish": "normal",
        "condition": "NM", "condition_modifier": None, "factory_sealed": False,
        "cost_basis": Decimal("8"), "market_value_at_purchase": Decimal("12"),
        "current_market_value": None, "listed_price": Decimal("15"),
        "acquired_at": "2026-03-14", "notes": notes, "needs_review": True,
        "gen": "01KY8E5KQ4KEZQY4KP3156VSJH",
    }
    record.update(over)
    return record


def graded_record(item_id, notes, **over):
    record = raw_record(item_id, notes)
    for gone in ("finish", "condition", "condition_modifier", "factory_sealed"):
        record.pop(gone)
    record.update({"kind": "graded", "company": "PSA", "grade": Decimal("10"),
                   "cert_number": "12345678"})
    record.update(over)
    return record


def catalog_record(card_id, name):
    return {"PK": f"CARD#{card_id}", "SK": "META", "entity": "catalog_card",
            "card_id": card_id, "name": name, "number": "38",
            "set_id": "swsh6", "set_name": "Chilling Reign"}


def price_record(card_id):
    return {"PK": f"CARD#{card_id}", "SK": "PRICE#RAW#normal#2026-07-01",
            "entity": "price_point", "card_id": card_id, "kind": "raw",
            "finish": "normal", "market": Decimal("400")}


# --- planning ------------------------------------------------------------

def test_plan_targets_an_item_whose_stored_text_carries_a_marker():
    [plan] = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38")])
    assert plan.item_id == "I1"
    assert plan.field == "notes"
    assert plan.before_language == "EN"
    assert plan.after_language == "JP"
    assert plan.key == {"PK": "INV#3", "SK": "ITEM#I1"}
    assert plan.card_id is None
    # default run stamps only: the text is the evidence and stays put
    assert plan.before_text == "Seismitoad (jp) #38"
    assert plan.after_text == plan.before_text
    assert plan.strips_text is False


# --- BLOCKER-2: stamping and stripping are two separate operations -------

def test_stamping_is_the_default_and_leaves_the_marker_in_place(dynamo_repo):
    """The marker is the ONLY evidence that lets this script re-plan a row, and
    the deployed model cannot yet hold the `language` that replaces it (pydantic
    drops unknown attributes, and `put_inventory_item` is a whole-record put). So
    `--apply` stamps and stops; removing the marker is a separate, later run."""
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert summary["updated"] == 1
    after = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})
    assert after["language"] == "JP"
    assert after["notes"] == "Seismitoad (jp) #38"   # evidence preserved


def test_a_stamped_row_can_still_be_re_planned():
    """The reversibility property: because the marker survives, the row is still
    visible to a later run rather than being unrecoverable outside the CSVs."""
    stamped = raw_record("I1", "Seismitoad (jp) #38", language="JP")
    [plan] = bl.plan_updates([stamped], strip_markers=True)
    assert plan.after_text == "Seismitoad #38"


def test_stamping_is_idempotent_without_stripping():
    stamped = raw_record("I1", "Seismitoad (jp) #38", language="JP")
    assert bl.plan_updates([stamped]) == []


def test_stripping_is_opt_in_and_only_then_removes_the_marker(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38", language="JP"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--strip-markers", "--model-deployed"])
    assert summary["updated"] == 1
    after = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})
    assert after["language"] == "JP"
    assert after["notes"] == "Seismitoad #38"


def test_the_dry_run_prints_card_id_for_every_planned_row(dynamo_repo, capsys):
    """The 104 are shielded from the nightly sync only by `card_id is None`. The
    operator must be able to confirm that from the output, not infer it."""
    _seed(raw_record("I1", "Seismitoad (jp) #38"),
          raw_record("I2", "Mewtwo (jp) #150", card_id="base1-10", PK="INV#4"))
    bl.main(["--table", TABLE, "--region", REGION])
    out = capsys.readouterr().out
    assert "card_id=None" in out
    assert "card_id=base1-10" in out
    assert "LINKED" in out  # the dangerous one is called out, not just listed


def test_a_linked_row_is_reported_in_the_summary(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38"),
          raw_record("I2", "Mewtwo (jp) #150", card_id="base1-10", PK="INV#4"))
    summary = bl.main(["--table", TABLE, "--region", REGION])
    assert summary["linked"] == 1


# --- BLOCKER-7: the plan must be pinnable between dry run and apply ------

def test_expect_count_aborts_when_the_plan_moved(dynamo_repo):
    """`--apply` re-scans and re-plans, so 'read the dry run and confirm 104' is
    unenforceable on its own: rows the operator never saw can join the plan."""
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--expect-count", "104"])
    assert summary["updated"] == 0
    assert summary["aborted"] is True


def test_expect_count_matching_lets_the_run_proceed(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--expect-count", "1"])
    assert summary["updated"] == 1
    assert summary["aborted"] is False


def test_the_plan_digest_pins_which_rows_not_just_how_many(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    dry = bl.main(["--table", TABLE, "--region", REGION])
    assert len(dry["digest"]) == 16
    ok = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                  "--expect-digest", dry["digest"]])
    assert ok["updated"] == 1


def test_a_stale_digest_aborts_before_any_write(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--expect-digest", "0000000000000000"])
    assert summary["aborted"] is True
    assert summary["updated"] == 0
    assert "language" not in _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})


def test_the_digest_changes_when_a_different_row_joins_the_plan(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    first = bl.main(["--table", TABLE, "--region", REGION])["digest"]
    _seed(raw_record("I2", "Mewtwo (jp) #150", PK="INV#4"))
    second = bl.main(["--table", TABLE, "--region", REGION])["digest"]
    assert first != second


def test_the_process_exit_code_is_nonzero_when_the_run_is_incomplete(dynamo_repo):
    """R7's backfill always exited 0 — 104 planned / 0 updated read as success to
    any wrapper or CI step. It was the script doing 104 of the 111 writes."""
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    assert bl.cli(["--table", TABLE, "--region", REGION, "--apply",
                   "--expect-count", "99"]) == 1
    assert bl.cli(["--table", TABLE, "--region", REGION, "--apply"]) == 0
    # a dry run with work outstanding is not a success either
    _seed(raw_record("I2", "Mewtwo (jp) #150", PK="INV#4"))
    assert bl.cli(["--table", TABLE, "--region", REGION]) == 1


# --- BLOCKER-3: a mid-run failure must still report ----------------------

def test_one_failing_write_does_not_abort_the_batch_or_hide_the_summary(
        dynamo_repo, capsys, monkeypatch):
    """R7 caught only ConditionalCheckFailedException and re-raised everything
    else after N of 104 writes, with main()'s summary never printed."""
    from botocore.exceptions import ClientError

    _seed(raw_record("I1", "Seismitoad (jp) #38"),
          raw_record("I2", "Mewtwo (jp) #150", PK="INV#4"),
          raw_record("I3", "Lugia jp #249", PK="INV#5"))
    table = _table()
    real = table.update_item
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceeded",
                                         "Message": "slow down"}}, "UpdateItem")
        return real(**kwargs)

    monkeypatch.setattr(table, "update_item", flaky)
    plans = bl.plan_updates(list(bl.scan_inventory(table)))
    assert len(plans) == 3
    written, failed = bl.apply_updates(table, plans)
    assert written == 2 and len(failed) == 1
    assert "ProvisionedThroughputExceeded" in capsys.readouterr().out


def test_the_summary_prints_even_when_the_scan_itself_explodes(
        dynamo_repo, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("table went away")

    monkeypatch.setattr(bl, "scan_inventory", boom)
    assert bl.cli(["--table", TABLE, "--region", REGION, "--apply"]) == 1
    out = capsys.readouterr().out
    assert "table went away" in out
    assert "0 updated" in out


def test_plan_leaves_english_items_alone():
    assert bl.plan_updates([raw_record("I1", "Seismitoad #38"),
                            raw_record("I2", "Charizard jpeg scan #4")]) == []


def test_plan_covers_graded_slabs_too():
    """14 of the live Slabs rows are Japanese; the backfill is not raw-only."""
    [plan] = bl.plan_updates(
        [graded_record("I2", "Espeon V (Japanese) — Eevee Heroes #69")],
        strip_markers=True)
    assert plan.kind == "graded"
    assert plan.after_text == "Espeon V — Eevee Heroes #69"
    assert plan.after_language == "JP"


def test_plan_reads_the_kind_specific_text_field():
    sealed = {"PK": "INV#1", "SK": "ITEM#S1", "entity": "inventory_item",
              "kind": "sealed", "item_id": "S1",
              "product_name": "Eevee Heroes Booster Box (jp)", "notes": None}
    bulk = {"PK": "INV#2", "SK": "ITEM#B1", "entity": "inventory_item",
            "kind": "bulk", "item_id": "B1",
            "description": "JP bulk commons lot", "notes": None}
    plans = {p.item_id: p for p in bl.plan_updates([sealed, bulk],
                                                   strip_markers=True)}
    assert plans["S1"].field == "product_name"
    assert plans["S1"].after_text == "Eevee Heroes Booster Box"
    assert plans["B1"].field == "description"
    assert plans["B1"].after_text == "bulk commons lot"


def test_plan_ignores_everything_that_is_not_an_inventory_item():
    """Catalog and price records must never be considered, even when their own
    text mentions a language."""
    records = [catalog_record("swsh6-38", "Seismitoad (jp)"), price_record("swsh6-38")]
    assert bl.plan_updates(records) == []


def test_plan_is_empty_once_the_backfill_has_already_run():
    """Idempotency at the planning layer: nothing left to change."""
    done = raw_record("I1", "Seismitoad #38", language="JP")
    assert bl.plan_updates([done]) == []


def test_plan_repairs_a_half_migrated_item():
    """language set but the marker never stripped — still one edit to make."""
    [plan] = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38", language="JP")],
                             strip_markers=True)
    assert plan.before_language == "JP"
    assert plan.after_text == "Seismitoad #38"


def test_plan_never_empties_the_only_text_a_row_has():
    [plan] = bl.plan_updates([raw_record("I1", "(jp)")], strip_markers=True)
    assert plan.after_text == "(jp)"       # text preserved
    assert plan.after_language == "JP"     # language still recorded


def test_format_plan_shows_before_and_after():
    [plan] = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38")],
                             strip_markers=True)
    line = bl.format_plan(plan)
    assert "I1" in line
    assert "Seismitoad (jp) #38" in line and "Seismitoad #38" in line
    assert "EN" in line and "JP" in line


# --- the write path, against moto ---------------------------------------

def _table():
    import boto3
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def _seed(*records):
    table = _table()
    for record in records:
        table.put_item(Item=record)
    return table


def _fetch(table, key):
    return table.get_item(Key=key).get("Item")


def test_dry_run_is_the_default_and_writes_nothing(dynamo_repo, capsys):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION])
    assert summary["applied"] is False
    assert summary["planned"] == 1
    after = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})
    assert after["notes"] == "Seismitoad (jp) #38"
    assert "language" not in after
    assert "DRY RUN" in capsys.readouterr().out.upper()


def test_apply_sets_the_language(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert summary["scanned"] == 1
    assert summary["planned"] == 1
    assert summary["updated"] == 1
    assert summary["applied"] is True
    after = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})
    assert after["language"] == "JP"


def test_a_second_apply_changes_nothing(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    again = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert again["planned"] == 0
    assert again["updated"] == 0


def test_apply_leaves_money_identity_and_generation_fields_untouched(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    bl.main(["--table", TABLE, "--region", REGION, "--apply", "--strip-markers",
             "--model-deployed"])
    after = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})
    assert after["cost_basis"] == Decimal("8")
    assert after["market_value_at_purchase"] == Decimal("12")
    assert after["listed_price"] == Decimal("15")
    assert after["current_market_value"] is None
    assert after["card_id"] is None
    assert after["gen"] == "01KY8E5KQ4KEZQY4KP3156VSJH"
    assert after["needs_review"] is True


def test_apply_never_touches_a_non_matching_item_or_the_catalog(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"),
                  raw_record("I2", "Charizard #4"),
                  catalog_record("swsh6-38", "Seismitoad"),
                  price_record("swsh6-38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert summary["updated"] == 1
    english = _fetch(table, {"PK": "INV#3", "SK": "ITEM#I2"})
    assert "language" not in english
    assert english["notes"] == "Charizard #4"
    card = _fetch(table, {"PK": "CARD#swsh6-38", "SK": "META"})
    assert card["name"] == "Seismitoad" and "language" not in card


def test_apply_skips_a_record_edited_since_the_plan_was_built(dynamo_repo):
    """The conditional write refuses to overwrite text that moved under us."""
    table = _seed(raw_record("I1", "Seismitoad (jp) #38"))
    [plan] = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38")],
                             strip_markers=True)
    table.update_item(Key=plan.key, UpdateExpression="SET #n = :v",
                      ExpressionAttributeNames={"#n": "notes"},
                      ExpressionAttributeValues={":v": "Something else entirely"})
    assert bl.apply_updates(table, [plan]) == (0, [plan])
    assert _fetch(table, plan.key)["notes"] == "Something else entirely"


# --- the write surface must stay surgical --------------------------------

FORBIDDEN_APIS = [
    "put_item", "delete_item", "batch_writer", "batch_write_item",
    "transact_write_items", "create_table", "update_table", "delete_table",
]


def test_script_only_ever_calls_update_item():
    """A whole-record ``put_item`` would drop the import ``gen`` stamp and every
    attribute the script did not know about; only a surgical ``update_item`` on
    the two fields is allowed."""
    source = SCRIPT.read_text(encoding="utf-8")
    offenders = [api for api in FORBIDDEN_APIS if api in source]
    assert offenders == [], f"backfill must not reference {offenders}"


# =========================================================================
# Council R8 acceptance tests (Revision 9)
# =========================================================================

# --- BLOCKER-C: the digest pins "zero linked", and linked aborts ----------

def test_the_plan_digest_covers_card_id():
    """A row that acquires a card_id between the pinned dry run and --apply, text
    unchanged, must change the digest - otherwise --expect-digest waves through
    the very state the whole procedure exists to keep out."""
    clean = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38")])
    linked = bl.plan_updates([raw_record("I1", "Seismitoad (jp) #38",
                                         card_id="swsh6-38")])
    assert bl.plan_digest(clean) != bl.plan_digest(linked)


def test_a_linked_row_hard_aborts_under_apply(dynamo_repo):
    """R8 only WARNED on a linked row and stamped anyway. A JP item holding an
    English card_id is priced from the wrong card by the nightly sync - the one
    precondition the procedure asks the operator to confirm must be enforced."""
    table = _seed(raw_record("I1", "Seismitoad (jp) #38", card_id="swsh6-38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert summary["linked"] == 1
    assert summary["aborted"] is True
    assert summary["updated"] == 0
    assert "language" not in _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})


def test_a_dry_run_still_only_warns_about_a_linked_row(dynamo_repo, capsys):
    _seed(raw_record("I1", "Seismitoad (jp) #38", card_id="swsh6-38"))
    summary = bl.main(["--table", TABLE, "--region", REGION])
    assert summary["linked"] == 1
    assert summary["aborted"] is False        # a dry run does not abort
    assert "card_id" in capsys.readouterr().out


def test_the_exit_code_is_nonzero_when_a_linked_row_aborts_apply(dynamo_repo):
    _seed(raw_record("I1", "Seismitoad (jp) #38", card_id="swsh6-38"))
    assert bl.cli(["--table", TABLE, "--region", REGION, "--apply"]) == 1


# --- BLOCKER-B: --strip-markers needs a real deploy interlock -------------

def test_strip_markers_refuses_without_the_deploy_acknowledgement(dynamo_repo):
    """R8 guarded the irreversible half with a bare flag - the same 'trust the
    operator' control --expect-count was created to replace."""
    table = _seed(raw_record("I1", "Seismitoad (jp) #38", language="JP"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--strip-markers"])
    assert summary["aborted"] is True
    assert summary["updated"] == 0
    assert _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})["notes"] \
        == "Seismitoad (jp) #38"          # marker preserved


def test_strip_markers_proceeds_with_ack_when_the_model_round_trips(dynamo_repo):
    table = _seed(raw_record("I1", "Seismitoad (jp) #38", language="JP"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--strip-markers", "--model-deployed"])
    assert summary["aborted"] is False
    assert summary["updated"] == 1
    assert _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})["notes"] \
        == "Seismitoad #38"


def test_strip_markers_refuses_when_the_model_would_drop_language(
        dynamo_repo, monkeypatch):
    """The structural half of the interlock: even WITH the ack, a checkout whose
    model cannot round-trip `language` must not strip - stripping would leave the
    row with neither marker nor field."""
    monkeypatch.setattr(bl, "language_is_persisted", lambda: False)
    table = _seed(raw_record("I1", "Seismitoad (jp) #38", language="JP"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply",
                       "--strip-markers", "--model-deployed"])
    assert summary["aborted"] is True
    assert summary["updated"] == 0
    assert _fetch(table, {"PK": "INV#3", "SK": "ITEM#I1"})["notes"] \
        == "Seismitoad (jp) #38"


def test_language_round_trips_through_the_current_model():
    assert bl.language_is_persisted() is True


def test_a_bare_stamp_run_is_unaffected_by_the_strip_interlock(dynamo_repo):
    """--model-deployed is only required to STRIP; a plain stamp still runs."""
    _seed(raw_record("I1", "Seismitoad (jp) #38"))
    summary = bl.main(["--table", TABLE, "--region", REGION, "--apply"])
    assert summary["aborted"] is False
    assert summary["updated"] == 1
