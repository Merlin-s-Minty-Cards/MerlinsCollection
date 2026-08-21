"""Scheduled sync dispatcher must be reachable and route correctly.

The ``scheduled_sync.py`` script is the single entry point for all
EventBridge-triggered sync jobs. It dispatches ``--job prices`` to
``run_daily_sync`` and ``--job catalog`` to ``sync_new_sets``, providing the
CloudWatch-readable JSON summary and process-level exit codes ECS needs.

Tests mirror the style of ``test_daily_sync.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scheduled_sync.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("scheduled_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scheduled_sync"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helpers — patch out real AWS / TCGdex so tests never open a socket.
# ---------------------------------------------------------------------------

class _NullClient:
    """Stands in for ``TcgdexClient`` so no test can open a socket."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patched_script(monkeypatch, *, job_args, dispatch_return):
    """Load the script and wire it to return *dispatch_return* from the target."""
    script = _load_script()
    monkeypatch.setattr(script, "_repository", lambda: object())
    monkeypatch.setattr(script, "_tcgdex_client", _NullClient)

    if "prices" in job_args:
        monkeypatch.setattr(
            script, "run_daily_sync",
            lambda repo, client, today: dispatch_return,
        )
    elif "catalog" in job_args:
        monkeypatch.setattr(
            script, "sync_new_sets",
            lambda repo, client, dry_run=False: dispatch_return,
        )
    return script


# ---------------------------------------------------------------------------
# Core dispatch tests
# ---------------------------------------------------------------------------

def test_prices_job_calls_run_daily_sync(monkeypatch, capsys):
    """``--job prices`` dispatches to ``run_daily_sync`` and exits 0."""
    summary = {"cards_updated": 5, "failures": 0, "aborted": False}
    script = _patched_script(monkeypatch, job_args=["prices"],
                             dispatch_return=summary)

    code = script.main(["--job", "prices"])

    assert code == 0
    out = capsys.readouterr().out
    # Must contain a structured JSON summary line
    json_line = _extract_json_line(out)
    assert json_line is not None, f"No JSON summary line found in output: {out!r}"
    parsed = json.loads(json_line)
    assert parsed["job"] == "prices"
    assert parsed["status"] == "ok"


def test_catalog_job_calls_sync_new_sets(monkeypatch, capsys):
    """``--job catalog`` dispatches to ``sync_new_sets`` and exits 0."""
    summary = {"sets_added": 2, "cards_added": 150}
    script = _patched_script(monkeypatch, job_args=["catalog"],
                             dispatch_return=summary)

    code = script.main(["--job", "catalog"])

    assert code == 0
    out = capsys.readouterr().out
    json_line = _extract_json_line(out)
    assert json_line is not None, f"No JSON summary line found in output: {out!r}"
    parsed = json.loads(json_line)
    assert parsed["job"] == "catalog"
    assert parsed["status"] == "ok"


def test_unknown_job_exits_nonzero(monkeypatch, capsys):
    """An unrecognised ``--job`` value must exit non-zero."""
    script = _load_script()
    monkeypatch.setattr(script, "_repository", lambda: object())
    monkeypatch.setattr(script, "_tcgdex_client", _NullClient)

    code = script.main(["--job", "bogus"])

    assert code != 0


def test_job_failure_exits_nonzero(monkeypatch, capsys):
    """If the underlying function raises, exit code must be non-zero and the
    error must appear in the JSON summary."""
    script = _load_script()
    monkeypatch.setattr(script, "_repository", lambda: object())
    monkeypatch.setattr(script, "_tcgdex_client", _NullClient)
    monkeypatch.setattr(
        script, "run_daily_sync",
        lambda repo, client, today: (_ for _ in ()).throw(
            RuntimeError("TCGdex is down")),
    )

    code = script.main(["--job", "prices"])

    assert code != 0
    out = capsys.readouterr().out
    json_line = _extract_json_line(out)
    assert json_line is not None, f"No JSON summary line found in output: {out!r}"
    parsed = json.loads(json_line)
    assert parsed["status"] == "error"
    assert "TCGdex is down" in parsed["error"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json_line(output: str) -> str | None:
    """Return the first line in *output* that parses as JSON, or ``None``."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                json.loads(line)
                return line
            except json.JSONDecodeError:
                continue
    return None
