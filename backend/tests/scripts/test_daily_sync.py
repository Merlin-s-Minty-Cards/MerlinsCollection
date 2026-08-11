"""The daily job must be reachable from an executable entry point.

Revision 1 rewrote ``seed_catalog.py`` and left ``catalog_sync.run_daily_sync``
with zero production callers, which silently took the graded-slab snapshot, the
sealed snapshot, and the inventory market-value refresh offline — with a green
test suite (verdict BLOAT-1 / Architect S1). This module is the rail that makes
that regression visible: it drives the script the same way cron would.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from merlins_collection.models.inventory import (
    GradedInventoryItem,
    GradingCompany,
    SealedInventoryItem,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "daily_sync.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("daily_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_sync"] = module
    spec.loader.exec_module(module)
    return module


def test_the_daily_job_runs_its_three_steps_from_the_script(dynamo_repo, monkeypatch,
                                                            capsys):
    script = _load_script()
    monkeypatch.setattr(script, "_repository", lambda: dynamo_repo)

    dynamo_repo.set_graded_market_value(
        "en:swsh1-1", GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    slab = GradedInventoryItem(
        card_id="en:swsh1-1", listed_price=Decimal("700"), cost_basis=Decimal("300"),
        acquired_at=date(2026, 1, 1), company=GradingCompany.PSA,
        grade=Decimal("10"), cert_number="123",
    )
    sealed = SealedInventoryItem(
        product_name="Box", product_type="booster_box", cost_basis=Decimal("400"),
        current_market_value=Decimal("500"), acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(slab)
    dynamo_repo.put_inventory_item(sealed)

    assert script.main() == 0

    summary = capsys.readouterr().out
    assert "graded_points_written" in summary
    assert "sealed_points_written" in summary
    assert "items_refreshed" in summary
    assert dynamo_repo.get_inventory_item(slab.item_id).current_market_value == Decimal("500")


# ---------------------------------------------------------------------------
# Exit-code hygiene.
#
# This job runs unattended. Before the depth pass existed, every failure mode of
# `run_daily_sync` was an exception, so it exited non-zero and any cron MAILTO /
# ECS Scheduled Task / K8s `backoffLimit` / healthchecks.io ping saw it. The
# depth pass added the first two ways to finish NORMALLY while doing nothing —
# an aborted run and a lock-skipped run — and a `return 0` on those is the exact
# silent-no-op this module's docstring says the script exists to prevent.
# ---------------------------------------------------------------------------


class _NullClient:
    """Stands in for `TcgdexClient` so no exit-code test can open a socket."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _script_returning(monkeypatch, summary):
    script = _load_script()
    monkeypatch.setattr(script, "_repository", lambda: object())
    monkeypatch.setattr(script, "TcgdexClient", _NullClient)
    monkeypatch.setattr(script, "run_daily_sync", lambda repo, client, today: summary)
    return script


def test_an_aborted_depth_pass_exits_non_zero(monkeypatch, capsys):
    script = _script_returning(monkeypatch, {
        "cards_updated": 0, "failures": 25, "not_found": 0,
        "unparsable_card_ids": 0, "no_usable_price": 0, "aborted": True,
        "graded_points_written": 1, "sealed_points_written": 1, "items_refreshed": 0,
    })

    code = script.main()

    assert code == 1
    out = capsys.readouterr().out
    assert "ABORTED" in out.upper()   # actionable, not just a dict key in a wall of text
    assert "failures: 25" in out      # the summary is still printed in full


def test_a_lock_skipped_depth_pass_exits_with_a_distinct_non_zero_code(monkeypatch, capsys):
    """Non-zero: with the reseed side unwired, the only thing that can hold this
    lock is a dead depth pass, so a skip is always an anomaly — and a week of
    silent no-ops behind a wedged lock must not look like a week of clean runs.
    DISTINCT from an abort: the two need different operator responses (chase
    TCGdex vs. clear a stale lock), and the exit code is the only signal a
    process-level monitor gets."""
    script = _script_returning(monkeypatch, {
        "skipped": "catalog reseed in flight",
        "graded_points_written": 1, "sealed_points_written": 1, "items_refreshed": 0,
    })

    code = script.main()

    assert code != 0
    assert code == 2
    out = capsys.readouterr().out
    assert "SKIPPED" in out.upper()
    assert "catalog reseed in flight" in out


def test_a_clean_run_still_exits_zero(monkeypatch, capsys):
    script = _script_returning(monkeypatch, {
        "cards_updated": 3, "failures": 0, "not_found": 0,
        "unparsable_card_ids": 0, "no_usable_price": 0, "aborted": False,
        "graded_points_written": 1, "sealed_points_written": 1, "items_refreshed": 2,
        "catalog_cards_updated": 5500, "catalog_failures": 0,
        "catalog_aborted": False, "catalog_skipped": None,
    })

    assert script.main() == 0
    assert "cards_updated: 3" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# RFC 0010 T17 — the weekly catalog cycle is a fifth failure surface.
#
# It walks ~5,500 cards a night on a six-night rotation with Friday as slack, so
# a night it silently drops is a night of the week's coverage promise gone. The
# depth pass's exit codes exist for exactly this reason; the catalog pass gets
# the same treatment rather than a quiet zero.
# ---------------------------------------------------------------------------


def test_an_aborted_catalog_pass_exits_non_zero(monkeypatch, capsys):
    """The depth pass completed, so the old checks all pass — and without this
    the run reports OK while the week's catalog coverage silently stalled."""
    script = _script_returning(monkeypatch, {
        "cards_updated": 3, "failures": 0, "not_found": 0,
        "unparsable_card_ids": 0, "no_usable_price": 0, "aborted": False,
        "graded_points_written": 1, "sealed_points_written": 1, "items_refreshed": 2,
        "catalog_candidates": 5500, "catalog_cards_updated": 12,
        "catalog_failures": 25, "catalog_aborted": True, "catalog_skipped": None,
    })

    code = script.main()

    assert code != 0
    out = capsys.readouterr().out
    assert "ABORTED" in out.upper()
    assert "catalog" in out.lower()      # says WHICH pass, not just that one died
    assert "catalog_failures: 25" in out  # the summary is still printed in full


def test_a_lock_skipped_catalog_pass_exits_non_zero(monkeypatch, capsys):
    """A week of half-runs must not look like a week of clean ones."""
    script = _script_returning(monkeypatch, {
        "cards_updated": 3, "failures": 0, "not_found": 0,
        "unparsable_card_ids": 0, "no_usable_price": 0, "aborted": False,
        "graded_points_written": 1, "sealed_points_written": 1, "items_refreshed": 2,
        "catalog_candidates": 0, "catalog_cards_updated": 0, "catalog_failures": 0,
        "catalog_aborted": False, "catalog_skipped": "catalog reseed in flight",
    })

    code = script.main()

    assert code != 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out.upper()
    assert "catalog reseed in flight" in out
