"""Tests for the spreadsheet-import CLI wrapper (``scripts/import_spreadsheet.py``).

Only the DISPATCH is proven here — which run function the flags select, and that
the default invocation is unchanged. The import behavior itself is covered in
``tests/services/test_spreadsheet_import.py``; both run functions are stubbed so
nothing touches AWS.

``scripts/`` is not an importable package, so the module is loaded off disk.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_spreadsheet.py"


@pytest.fixture
def cli(monkeypatch):
    """The loaded CLI module with both run paths and the repo stubbed out."""
    spec = importlib.util.spec_from_file_location("_import_spreadsheet_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    calls: dict = {}

    def _full(csv_dir, repo, **kwargs):
        calls["full"] = (csv_dir, kwargs)
        return {"_committed": True}

    def _singles(csv_dir, repo, **kwargs):
        calls["singles"] = (csv_dir, kwargs)
        return {"_committed": True}

    monkeypatch.setattr(module, "run_import", _full)
    monkeypatch.setattr(module, "run_singles_only_import", _singles)
    monkeypatch.setattr(module, "InventoryRepository", lambda table: f"repo:{table}")
    module._calls = calls
    try:
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _run(cli, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["import_spreadsheet.py", *argv])
    cli.main()
    return cli._calls


def test_default_invocation_still_runs_the_full_import(cli, monkeypatch):
    # REGRESSION GUARD: a bare run must keep taking the full 18-tab path with the
    # same arguments it always did — the Singles-only path is opt-in only.
    calls = _run(cli, monkeypatch, "some/dir", "--table", "merlins-cards")
    assert "singles" not in calls
    csv_dir, kwargs = calls["full"]
    assert csv_dir == "some/dir"
    assert kwargs == {"allow_empty": frozenset(), "force_replace": False}


def test_singles_only_flag_selects_the_scoped_run(cli, monkeypatch):
    calls = _run(cli, monkeypatch, "some/dir", "--singles-only")
    assert "full" not in calls
    csv_dir, kwargs = calls["singles"]
    assert csv_dir == "some/dir"
    assert kwargs == {"force_replace": False}


def test_singles_only_forwards_force_replace(cli, monkeypatch):
    calls = _run(cli, monkeypatch, "some/dir", "--singles-only", "--force-replace")
    assert calls["singles"][1] == {"force_replace": True}


def test_singles_only_rejects_allow_empty(cli, monkeypatch):
    # --allow-empty names TABS; a Singles-only run has one and never tolerates it
    # empty. Accepting the flag silently would imply an acknowledgement was taken.
    monkeypatch.setattr(
        sys, "argv",
        ["import_spreadsheet.py", "d", "--singles-only", "--allow-empty", "Debts"])
    with pytest.raises(SystemExit):
        cli.main()
    assert cli._calls == {}
