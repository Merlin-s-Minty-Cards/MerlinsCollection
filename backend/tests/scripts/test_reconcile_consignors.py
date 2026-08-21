"""Tests for ``scripts/reconcile_consignors.py`` (RFC 0010 T2).

``put_consignor``'s sweep fixes the CAUSE of the fork. It does not merge the two
Harrys already sitting in the live table — nothing rewrites a consignor until
somebody edits it, and the whole complaint is that editing is what hurts. This
script is the one-time cleanup, and like every other script here it runs once,
against live data, with no second chance.

**Which row wins is the load-bearing decision, and it is NOT "the highest
generation".** An admin edit runs with no generation set, so it writes the
*unsuffixed* SK — the shorter key, which sorts FIRST in the partition and is by
construction the most recently written of the pair. It is also the one carrying
the values the admin typed (the owner's 85% Harry). Keeping the highest ``#gen``
suffix instead would silently discard exactly the edit that created the fork.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from merlins_collection.models.business import Consignor
from scripts.reconcile_consignors import main


@pytest.fixture
def _repo_patch(dynamo_repo, monkeypatch):
    """Point the script's repository factory at the moto-backed test repo."""
    import scripts.reconcile_consignors as script

    monkeypatch.setattr(script, "_repository", lambda table, region: dynamo_repo)
    return dynamo_repo


def _fork(repo, consignor_id="harry-1", *, gen="gen-1",
          imported_percent="70", edited_percent="85"):
    """Reproduce the production fork: an import-generation row plus the
    unsuffixed row an admin edit wrote beside it."""
    repo.set_import_generation(gen)
    repo.put_consignor(Consignor(consignor_id=consignor_id, name="Harry",
                                 payout_percent=Decimal(imported_percent)))
    repo.set_import_generation(None)
    # Written raw: ``put_consignor`` sweeps once T2 lands, which is the point.
    repo._table.put_item(Item={
        "PK": "CONSIGNORLIST",
        "SK": f"CONSIGNOR#{consignor_id}",
        "entity": "consignor",
        "consignor_id": consignor_id,
        "name": "Harry",
        "payout_percent": edited_percent,
    })


def _rows(repo, consignor_id):
    return [c for c in repo.list_consignors() if c.consignor_id == consignor_id]


def test_a_dry_run_reports_the_fork_and_writes_nothing(_repo_patch, capsys):
    repo = _repo_patch
    _fork(repo)

    summary = main(["--table", "t", "--region", "us-west-2"])

    assert summary["forked"] == 1
    assert summary["rows_removed"] == 0
    assert summary["executed"] is False
    assert len(_rows(repo, "harry-1")) == 2, "a dry run must not write"
    assert "harry-1" in capsys.readouterr().out


def test_execute_collapses_the_fork_keeping_the_admin_edit(_repo_patch):
    repo = _repo_patch
    _fork(repo)

    summary = main(["--table", "t", "--region", "us-west-2",
                    "--execute", "--confirm-table", "t"])

    rows = _rows(repo, "harry-1")
    assert len(rows) == 1, f"reconcile left {len(rows)} rows"
    assert rows[0].payout_percent == Decimal("85"), \
        "the admin's edit is the surviving value, not the imported one"
    assert summary["rows_removed"] == 1


def test_with_only_generation_rows_the_highest_generation_wins(_repo_patch):
    """No admin edit ever happened, so there is no unsuffixed row to prefer.
    Falling back to the highest generation keeps the newest import."""
    repo = _repo_patch
    repo.set_import_generation("gen-1")
    repo.put_consignor(Consignor(consignor_id="c-1", name="Old",
                                 payout_percent=Decimal("50")))
    repo.set_import_generation("gen-2")
    repo.put_consignor(Consignor(consignor_id="c-1", name="New",
                                 payout_percent=Decimal("60")))
    repo.set_import_generation(None)

    main(["--table", "t", "--region", "us-west-2", "--execute", "--confirm-table", "t"])

    rows = _rows(repo, "c-1")
    assert len(rows) == 1
    assert rows[0].name == "New"


def test_an_unforked_cosigner_is_left_alone(_repo_patch):
    repo = _repo_patch
    repo.put_consignor(Consignor(consignor_id="solo-1", name="Alice"))

    summary = main(["--table", "t", "--region", "us-west-2",
                    "--execute", "--confirm-table", "t"])

    assert summary["forked"] == 0
    assert summary["rows_removed"] == 0
    assert len(_rows(repo, "solo-1")) == 1


def test_it_refuses_to_write_without_the_table_named_back(_repo_patch):
    repo = _repo_patch
    _fork(repo)

    summary = main(["--table", "t", "--region", "us-west-2", "--execute"])

    assert summary["refused"] is True
    assert summary["rows_removed"] == 0
    assert len(_rows(repo, "harry-1")) == 2, "a refused run must write nothing"
