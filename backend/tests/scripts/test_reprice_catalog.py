"""Tests for ``scripts/reprice_catalog.py`` (RFC 0010 T17, deliverable 2).

The owner's ask: *"I want to be able to run a script once so that the entire
catalog has it's price updated. This is something I can just leave going
overnight."* That is a 2 h 18 min run against a volunteer-run free API, started
by hand, unattended, on a live customer-facing table — so it is driven here the
way the owner will drive it rather than eyeballed.

Two properties carry the whole design and both are pinned below:

* **it never holds the catalog lock for the whole run.** The TTL is 3600 s, so a
  two-hour holder looks like a crashed one and its lock becomes stealable — at
  which point a write landing across a reseed's swap makes the card silently
  disappear from a live catalog. It works in bounded chunks instead, taking and
  releasing the lock per chunk, which also lets a waiting reseed in between
  chunks rather than starving it for two hours.
* **it is a driver, not a second implementation.** The pricing is
  ``services.catalog_sync.refresh_catalog_prices``, the same function the nightly
  cycle calls. Two implementations of "price a card" is the divergence this repo
  has already paid for twice.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reprice_catalog.py"

EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _load_script():
    spec = importlib.util.spec_from_file_location("reprice_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["reprice_catalog"] = module
    spec.loader.exec_module(module)
    return module


def _cat_card(card_id, *, detail="brief", synced=None, prices=None):
    return CatalogCard(
        card_id=card_id, name="Card", set_id="en:swsh1", set_name="S&S", number="1",
        images=CardImages(), detail=detail, last_synced_at=synced or EPOCH,
        prices={f: FinishPrice(market=m) for f, m in (prices or {}).items()},
    )


def _detail(tcgdex_id, *, market="9.25"):
    return {
        "id": tcgdex_id, "localId": "1", "name": f"Card {tcgdex_id}",
        "set": {"id": "swsh1", "name": "S&S"}, "rarity": "Rare Holo V",
        "pricing": {"tcgplayer": {
            "unit": "USD", "updated": "2026-06-22T00:00:00.000Z",
            "holofoil": {"marketPrice": market},
        }},
    }


class _FakeClient:
    """Serves detail records for any id, recording every fetch.

    ``interrupt_after`` raises ``KeyboardInterrupt`` mid-run, which is the one
    failure mode that matters at 2 a.m.: it is a ``BaseException``, so the
    per-card ``except Exception`` never sees it and it must unwind through the
    lock's ``finally``.
    """

    def __init__(self, *, interrupt_after=None, always_raise=None):
        self.calls = []
        self.interrupt_after = interrupt_after
        self.always_raise = always_raise

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_card(self, language, tcgdex_id):
        self.calls.append((language, tcgdex_id))
        if self.interrupt_after is not None and len(self.calls) > self.interrupt_after:
            raise KeyboardInterrupt
        if self.always_raise is not None:
            raise self.always_raise
        return _detail(tcgdex_id)

    @property
    def fetched_ids(self):
        return [tcgdex_id for _language, tcgdex_id in self.calls]


def _wire(script, monkeypatch, repo, client):
    """Point the script at the moto repo and a fake TCGdex, never real ones."""
    monkeypatch.setattr(script, "_repository", lambda table, region: repo)
    monkeypatch.setattr(script, "TcgdexClient", lambda *a, **k: client)


def _seed(repo, count, *, start=300):
    """``count`` never-priced catalog rows, each staler than the last."""
    ids = [f"en:swsh1-{start + i}" for i in range(count)]
    repo.batch_upsert_catalog_cards([
        _cat_card(cid, synced=EPOCH + timedelta(days=i))
        for i, cid in enumerate(ids)
    ])
    return ids


def _lock_events(monkeypatch, repo):
    """Record every catalog-lock acquire/release the run performs, in order."""
    events = []
    acquire, release = repo.acquire_catalog_lock, repo.release_catalog_lock

    def _acquire(gen, **kwargs):
        events.append("acquire")
        return acquire(gen, **kwargs)

    def _release(gen):
        events.append("release")
        return release(gen)

    monkeypatch.setattr(repo, "acquire_catalog_lock", _acquire)
    monkeypatch.setattr(repo, "release_catalog_lock", _release)
    return events


# ---------------------------------------------------------------------------
# The rails
# ---------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_reports_the_plan(dynamo_repo, monkeypatch,
                                                      capsys):
    """Dry run by default, matching every other production writer in this repo —
    and it has to print the ETA, because "leave it going overnight" is a decision
    the owner can only make if they are told what overnight means."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    ids = _seed(dynamo_repo, 4)

    code = script.main(["--table", "merlins-cards-test", "--chunk-size", "2"])

    assert code == 0
    assert client.calls == []  # not one upstream request
    for card_id in ids:
        stored = dynamo_repo.get_catalog_card(card_id)
        assert stored.detail == "brief"
        assert stored.prices == {}

    out = capsys.readouterr().out
    assert "DRY RUN" in out.upper()
    assert "4" in out                     # the candidate count
    assert "chunk" in out.lower()         # the chunk plan
    assert "estimated" in out.lower()     # the runtime estimate


def test_execute_without_confirm_table_refuses_and_writes_nothing(
    dynamo_repo, monkeypatch, capsys,
):
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    ids = _seed(dynamo_repo, 2)

    code = script.main(["--table", "merlins-cards-test", "--execute"])

    assert code == 2
    assert client.calls == []
    assert dynamo_repo.get_catalog_card(ids[0]).detail == "brief"
    assert "confirm-table" in capsys.readouterr().err


def test_a_mismatched_confirm_table_refuses(dynamo_repo, monkeypatch):
    """The rail is naming the table BACK, not merely passing a flag."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 2)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "some-other-table"])

    assert code == 2
    assert client.calls == []


# ---------------------------------------------------------------------------
# Chunking, which is the answer to the lock TTL
# ---------------------------------------------------------------------------


def test_it_takes_and_releases_the_lock_once_per_chunk(dynamo_repo, monkeypatch):
    """Not one long hold. A 2 h 18 min holder outlives the 3600 s TTL and its
    lock becomes stealable — the failure mode that loses catalog ROWS rather
    than prices. Two chunks must produce two acquire/release PAIRS, interleaved,
    so a reseed waiting on the lock gets in between them."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 4)
    events = _lock_events(monkeypatch, dynamo_repo)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test",
                        "--chunk-size", "2"])

    assert code == 0
    assert events == ["acquire", "release", "acquire", "release"]
    assert len(client.calls) == 4


def test_a_chunk_that_cannot_take_the_lock_stops_with_a_distinct_exit_code(
    dynamo_repo, monkeypatch, capsys,
):
    """It must STOP, not skip ahead: the cards it could not price are exactly
    the ones the next run needs to see as stalest, and a run that quietly
    continued past a reseed would report success having priced nothing."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 4)

    dynamo_repo.acquire_catalog_lock("reseed-in-flight")
    try:
        code = script.main(["--table", "merlins-cards-test", "--execute",
                            "--confirm-table", "merlins-cards-test",
                            "--chunk-size", "2"])
    finally:
        dynamo_repo.release_catalog_lock("reseed-in-flight")

    assert code == 3
    assert code not in (0, 1, 2)
    assert client.calls == []
    assert "lock" in capsys.readouterr().out.lower()


def test_limit_bounds_the_run(dynamo_repo, monkeypatch):
    """So the owner can prove it on a slice before committing an evening."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 4)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test",
                        "--limit", "2"])

    assert code == 0
    assert len(client.calls) == 2


def test_re_running_after_an_interrupted_run_continues_rather_than_restarting(
    dynamo_repo, monkeypatch,
):
    """The resumability claim, asserted rather than assumed. There is no
    checkpoint file and no --resume flag: stalest-first ordering means a card
    priced by the first run is now the freshest thing in the catalog, so the
    second run reaches for what is left. That is the same property that makes
    the nightly cycle self-heal after a lost night."""
    script = _load_script()
    ids = _seed(dynamo_repo, 4)

    first = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, first)
    script.main(["--table", "merlins-cards-test", "--execute",
                 "--confirm-table", "merlins-cards-test", "--limit", "2"])
    assert first.fetched_ids == ["swsh1-300", "swsh1-301"]

    second = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, second)
    script.main(["--table", "merlins-cards-test", "--execute",
                 "--confirm-table", "merlins-cards-test", "--limit", "2"])

    assert second.fetched_ids == ["swsh1-302", "swsh1-303"]
    for card_id in ids:
        assert dynamo_repo.get_catalog_card(card_id).prices["holofoil"].market == (
            Decimal("9.25")
        )


def test_ctrl_c_releases_the_lock_and_exits_cleanly(dynamo_repo, monkeypatch):
    """The one that matters at 2 a.m.: a KeyboardInterrupt that leaves the lock
    held blocks the next morning's nightly run for a full hour, and the operator
    who pressed Ctrl-C has gone to bed."""
    script = _load_script()
    client = _FakeClient(interrupt_after=1)
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 4)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test",
                        "--chunk-size", "2"])

    assert code == 4
    # The lock must be free: a fresh acquire succeeds immediately rather than
    # waiting out the 3600s TTL.
    dynamo_repo.acquire_catalog_lock("post-interrupt-probe")
    dynamo_repo.release_catalog_lock("post-interrupt-probe")
    # ...and the card that DID land keeps its price. An interrupt is a stop, not
    # a rollback.
    assert dynamo_repo.get_catalog_card(
        "en:swsh1-300").prices["holofoil"].market == Decimal("9.25")


def test_an_aborted_chunk_exits_non_zero(dynamo_repo, monkeypatch, capsys):
    """Same posture as the nightly pass: consecutive failures mean upstream is
    down, and an overnight run that priced nothing must not exit 0."""
    script = _load_script()
    client = _FakeClient(always_raise=RuntimeError("dead endpoint"))
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 4)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test",
                        "--chunk-size", "2", "--max-consecutive-failures", "2"])

    assert code == 1
    assert "abort" in capsys.readouterr().out.lower()


def test_an_empty_catalog_is_reported_not_treated_as_success(dynamo_repo,
                                                            monkeypatch, capsys):
    """A catalog with nothing to price means the seed has not run, which is a
    different problem — and "0 cards repriced" read as OK is how that goes
    unnoticed for a week."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test"])

    assert code == 0
    assert client.calls == []
    assert "no candidates" in capsys.readouterr().out.lower()


def test_the_script_never_prices_held_cards(dynamo_repo, monkeypatch):
    """The nightly depth pass owns those, daily. Re-fetching them here would
    spend requests on the one population that is already covered."""
    from datetime import date

    from merlins_collection.models.inventory import Condition, RawInventoryItem

    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 2)
    dynamo_repo.put_inventory_item(RawInventoryItem(
        card_id="en:swsh1-300", cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.NM,
    ))

    script.main(["--table", "merlins-cards-test", "--execute",
                 "--confirm-table", "merlins-cards-test"])

    assert client.fetched_ids == ["swsh1-301"]


def test_the_chunk_size_cannot_exceed_what_the_lock_ttl_allows(dynamo_repo,
                                                              monkeypatch):
    """A mis-typed --chunk-size must not be able to reproduce the very hold this
    script exists to avoid. 3600s / 0.262s is ~13,700 cards; anything near that
    is refused rather than clamped silently."""
    script = _load_script()
    client = _FakeClient()
    _wire(script, monkeypatch, dynamo_repo, client)
    _seed(dynamo_repo, 2)

    code = script.main(["--table", "merlins-cards-test", "--execute",
                        "--confirm-table", "merlins-cards-test",
                        "--chunk-size", "50000"])

    assert code == 2
    assert client.calls == []
