"""Tests for ``scripts/backfill_price_history_ttl.py`` (RFC 0015).

Additive-only backfill: stamps a `ttl` attribute onto every existing
price-history row that doesn't already carry one, so DynamoDB's native TTL
can expire it after the configured retention window. Unlike
``seed_catalog.py``/``wipe_catalog.py`` this never deletes anything, so it
takes the lighter ``backfill_catalog_sets.py`` rail: dry-run by default,
``--execute`` to write.

**Progress reporting is load-bearing, not cosmetic.** The first version
called ``InventoryRepository.backfill_price_history_ttl`` once and printed
only a final summary. Run against the live table, the scan+write took ~90
minutes with ZERO output in between — indistinguishable from a hang, and
reported as exactly that. The fix (mirroring ``reprice_catalog.py``'s
chunk-loop-in-the-script shape) is to select candidates once, then apply them
in bounded chunks with a progress line printed after each one — the repo
layer (``list_price_history_ttl_candidates`` / ``apply_price_history_ttl``,
tested in ``test_dynamodb.py``) stays a pure read/write; this script owns the
chunking and all the printing, same split as every other script here.
"""

from decimal import Decimal

from scripts.backfill_price_history_ttl import main


def _legacy_row(pk, sk, *, card_id, date="2026-01-01"):
    return {
        "PK": pk, "SK": sk, "entity": "price_point", "card_id": card_id,
        "date": date, "source": "tcgplayer", "kind": "raw",
        "finish": "holofoil", "market": Decimal("9.99"),
    }


def test_main_dry_run_reports_candidates_and_writes_nothing(dynamo_repo, monkeypatch):
    dynamo_repo._table.put_item(Item=_legacy_row(
        "CARD#legacy-1", "PRICE#RAW#holofoil#2026-01-01", card_id="legacy-1",
    ))
    monkeypatch.setattr(
        "scripts.backfill_price_history_ttl.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    result = main([])

    assert result["candidates"] == 1
    assert result["executed"] is False
    raw = dynamo_repo._table.get_item(
        Key={"PK": "CARD#legacy-1", "SK": "PRICE#RAW#holofoil#2026-01-01"}
    )["Item"]
    assert "ttl" not in raw


def test_main_execute_writes_ttl(dynamo_repo, monkeypatch):
    dynamo_repo._table.put_item(Item=_legacy_row(
        "CARD#legacy-2", "PRICE#RAW#holofoil#2026-01-01", card_id="legacy-2",
    ))
    monkeypatch.setattr(
        "scripts.backfill_price_history_ttl.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    result = main(["--execute"])

    assert result["candidates"] == 1
    assert result["written"] == 1
    assert result["executed"] is True
    raw = dynamo_repo._table.get_item(
        Key={"PK": "CARD#legacy-2", "SK": "PRICE#RAW#holofoil#2026-01-01"}
    )["Item"]
    assert "ttl" in raw
    assert raw["market"] == Decimal("9.99")  # untouched by the targeted update


def test_execute_prints_progress_between_chunks(dynamo_repo, monkeypatch, capsys):
    """The regression test for the actual reported bug: a human watching the
    terminal must see SOMETHING before the whole run finishes, not just a
    final summary. Five rows over a chunk size of 2 forces three chunks."""
    for i in range(5):
        dynamo_repo._table.put_item(Item=_legacy_row(
            f"CARD#legacy-{i}", "PRICE#RAW#holofoil#2026-01-01", card_id=f"legacy-{i}",
        ))
    monkeypatch.setattr(
        "scripts.backfill_price_history_ttl.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    result = main(["--execute", "--chunk-size", "2"])

    assert result["written"] == 5
    out = capsys.readouterr().out
    chunk_lines = [line for line in out.splitlines() if "chunk" in line.lower()]
    assert len(chunk_lines) == 3  # ceil(5 / 2)
    assert "3/3" in chunk_lines[-1] or "3 of 3" in chunk_lines[-1]


def test_no_candidates_is_reported_not_treated_as_an_error(dynamo_repo, monkeypatch, capsys):
    monkeypatch.setattr(
        "scripts.backfill_price_history_ttl.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )

    result = main(["--execute"])

    assert result["candidates"] == 0
    assert "no candidates" in capsys.readouterr().out.lower()


def test_ctrl_c_stops_cleanly_and_reports_how_far_it_got(dynamo_repo, monkeypatch, capsys):
    """The one that matters mid-run: interrupting must not crash or corrupt
    anything, and it must tell the operator it's safe to just re-run — already
    stamped rows are skipped, so nothing already written is redone."""
    for i in range(4):
        dynamo_repo._table.put_item(Item=_legacy_row(
            f"CARD#legacy-{i}", "PRICE#RAW#holofoil#2026-01-01", card_id=f"legacy-{i}",
        ))
    monkeypatch.setattr(
        "scripts.backfill_price_history_ttl.InventoryRepository",
        lambda *a, **k: dynamo_repo,
    )
    real_apply = dynamo_repo.apply_price_history_ttl
    calls = {"n": 0}

    def interrupting_apply(candidates):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return real_apply(candidates)

    monkeypatch.setattr(dynamo_repo, "apply_price_history_ttl", interrupting_apply)

    result = main(["--execute", "--chunk-size", "1"])

    assert result["interrupted"] is True
    assert result["written"] == 1  # the one chunk that completed before the interrupt
    out = capsys.readouterr().out
    assert "interrupt" in out.lower()
    assert "re-run" in out.lower()
