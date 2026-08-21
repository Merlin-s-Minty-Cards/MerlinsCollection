"""Tests for ``scripts/backfill_show_analytics.py`` (RFC 0013).

Archiving a show now generates its snapshot automatically (see
``routers/admin/analytics.py::archive_show``), but that only covers shows
archived AFTER that change shipped. This script fills the gap for shows
archived before it — every one of them has no stored snapshot and reads 0 on
the Shows tab until this runs once.
"""

from datetime import date
from decimal import Decimal

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)

from scripts.backfill_show_analytics import find_shows_needing_backfill, main


def _archived_show(repo, show_id: str, *, name="Portland Card Show") -> Show:
    show = Show(show_id=show_id, name=name, date=date(2025, 6, 1), archived=True)
    repo.put_show(show)
    return show


def test_finds_only_archived_shows_with_no_snapshot(dynamo_repo):
    needs_it = _archived_show(dynamo_repo, "needs-backfill")
    _archived_show(dynamo_repo, "already-has-one")
    unarchived = Show(show_id="not-archived", name="Future Show",
                       date=date(2025, 7, 1), archived=False)
    dynamo_repo.put_show(unarchived)

    from merlins_collection.routers.admin.analytics import generate_show_analytics
    generate_show_analytics("already-has-one", repo=dynamo_repo)

    assert find_shows_needing_backfill(dynamo_repo) == [needs_it.show_id]


def test_dry_run_writes_nothing(dynamo_repo, monkeypatch):
    _archived_show(dynamo_repo, "needs-backfill")
    monkeypatch.setattr(
        "scripts.backfill_show_analytics.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    summary = main([])

    assert summary == {
        "shows_needing_backfill": 1, "shows_generated": 0, "executed": False,
    }
    assert dynamo_repo.get_show_analytics("needs-backfill") is None


def test_execute_generates_a_real_snapshot(dynamo_repo, monkeypatch):
    _archived_show(dynamo_repo, "needs-backfill")
    dynamo_repo.put_transaction(Transaction(
        type=TransactionType.SALE,
        item_id="item-1",
        category=ItemCategory.RAW,
        date=date(2025, 6, 1),
        amount=Decimal("40.00"),
        payment_method="cash",
        show_id="needs-backfill",
    ))
    monkeypatch.setattr(
        "scripts.backfill_show_analytics.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    summary = main(["--execute"])

    assert summary == {
        "shows_needing_backfill": 1, "shows_generated": 1, "executed": True,
    }
    snapshot = dynamo_repo.get_show_analytics("needs-backfill")
    assert snapshot is not None
    assert snapshot.total_sold == Decimal("40.00")


def test_execute_does_not_touch_a_show_that_already_has_a_snapshot(dynamo_repo, monkeypatch):
    """A snapshot already on file might be a human's deliberate re-generation
    after a correction — this script fills gaps, it does not resync."""
    _archived_show(dynamo_repo, "already-has-one")
    from merlins_collection.routers.admin.analytics import generate_show_analytics
    generate_show_analytics("already-has-one", repo=dynamo_repo)
    original = dynamo_repo.get_show_analytics("already-has-one")

    monkeypatch.setattr(
        "scripts.backfill_show_analytics.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )
    summary = main(["--execute"])

    assert summary["shows_generated"] == 0
    assert dynamo_repo.get_show_analytics("already-has-one") == original
