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
