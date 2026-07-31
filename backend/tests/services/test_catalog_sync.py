from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    _MARKET_FINISH_FALLBACK,
    _market_price,
    Condition,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
)
from merlins_collection.services.catalog_sync import (
    refresh_inventory_market_values,
    run_daily_sync,
    snapshot_graded_prices,
    snapshot_sealed_prices,
)
from merlins_collection.services.tcgdex import to_catalog_card

FX = Decimal("1.08")

# A TCGdex *detail* record — the only response shape that carries pricing.
RAW = {
    "id": "swsh1-1", "localId": "1", "name": "Celebi V",
    "set": {"id": "swsh1", "name": "S&S"}, "rarity": "Rare Holo V",
    "image": "https://assets.tcgdex.net/en/swsh/swsh1/1",
    "pricing": {"tcgplayer": {
        "unit": "USD", "updated": "2026-06-22T00:00:00.000Z",
        "holofoil": {"marketPrice": 9.25},
    }},
}
CARD_ID = "en:swsh1-1"


def _raw_item(card_id=CARD_ID, *, status=ItemStatus.AVAILABLE):
    return RawInventoryItem(
        card_id=card_id, listed_price=Decimal("10"),
        cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.NM, status=status,
    )


def _detail(tcgdex_id, local_id, *, market="9.25", rarity="Rare Holo V"):
    """A minimal TCGdex *detail* record for a held-card fixture, USD-priced."""
    return {
        "id": tcgdex_id, "localId": local_id, "name": f"Card {tcgdex_id}",
        "set": {"id": "swsh1", "name": "S&S"}, "rarity": rarity,
        "pricing": {"tcgplayer": {
            "unit": "USD", "updated": "2026-06-22T00:00:00.000Z",
            "holofoil": {"marketPrice": market},
        }},
    }


class FakeTcgdexClient:
    """Serves committed detail records (or raises), keyed by ``(language, id)``.

    Mirrors ``tests/scripts/test_seed_catalog.py::FakeClient`` — same shape,
    scoped to the detail endpoint (``get_card``) that the depth pass calls.
    ``calls`` records every ``(language, tcgdex_id)`` pair requested, so tests
    can assert on what was (and was not) fetched without a real network call.
    """

    def __init__(self, cards=None, *, errors=None, always_raise=None):
        self.cards = cards or {}
        self.errors = errors or {}
        self.always_raise = always_raise
        self.calls = []

    def get_card(self, language, tcgdex_id):
        self.calls.append((language, tcgdex_id))
        if self.always_raise is not None:
            raise self.always_raise
        key = (language, tcgdex_id)
        if key in self.errors:
            raise self.errors[key]
        return self.cards.get(key)


class SequencedTcgdexClient:
    """Serves a fixed pass/fail OUTCOME per call, indexed by call order.

    Used only for pinning down ``max_consecutive_failures`` behavior. The
    held-card set's internal iteration order is not part of
    ``refresh_held_prices``'s contract (the RFC spells it as a Python
    ``{...}`` set comprehension), so a test asserting on the failure/reset
    counter must not depend on WHICH card lands in which position — only on
    call ORDER. Outcomes are consumed positionally; any call past the end of
    the list fails, so an over-running test still terminates.

    Three outcomes: ``"ok"`` (returns ``raw``), ``"fail"`` (raises), and
    ``"notfound"`` (returns ``None``, the client's documented 404 contract —
    counted separately and must neither increment nor reset the consecutive-
    failure counter).
    """

    def __init__(self, outcomes, raw=RAW):
        self.outcomes = list(outcomes)
        self.raw = raw
        self.calls = []

    def get_card(self, language, tcgdex_id):
        index = len(self.calls)
        self.calls.append((language, tcgdex_id))
        outcome = self.outcomes[index] if index < len(self.outcomes) else "fail"
        if outcome == "fail":
            raise RuntimeError("simulated tcgdex failure")
        if outcome == "notfound":
            return None
        return self.raw


def _graded_item(card_id=CARD_ID):
    return GradedInventoryItem(
        card_id=card_id, listed_price=Decimal("700"),
        cost_basis=Decimal("300"), acquired_at=date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number="123",
    )


def _seed_catalog(repo):
    """Put the mapped catalog card in place; Phase 2 owns the writer that fetches
    the detail record this maps from (see BLOAT-1 in the revision-1 verdict)."""
    repo.batch_upsert_catalog_cards([to_catalog_card(RAW, Language.EN, fx_rate=FX)])


def _catalog_card(card_id, prices, *, name="Card", set_id="swsh1", set_name="S&S"):
    """A `CatalogCard` with an EXACT, hand-specified `prices` dict (Phase 12:
    the fallback-chain tests need precise control over which finishes carry a
    market figure, which the TCGdex-detail-shaped fixtures above don't give
    without going through the mapper)."""
    return CatalogCard(
        card_id=card_id, name=name, set_id=set_id, set_name=set_name, number="1",
        images=CardImages(), last_synced_at=datetime.now(tz=timezone.utc),
        prices={finish: FinishPrice(market=market) for finish, market in prices.items()},
    )


def test_refresh_sets_current_market_value_from_catalog(dynamo_repo):
    _seed_catalog(dynamo_repo)
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    updated = refresh_inventory_market_values(dynamo_repo)
    assert updated == 1
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("9.25")


def test_refresh_applies_condition_adjustment_for_lp(dynamo_repo):
    """An LP card's denormalized price is the NM market price * 0.82 (Phase 19)."""
    _seed_catalog(dynamo_repo)
    item = RawInventoryItem(
        card_id=CARD_ID, cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.LP,
    )
    dynamo_repo.put_inventory_item(item)
    refresh_inventory_market_values(dynamo_repo)
    stored = dynamo_repo.get_inventory_item(item.item_id)
    # 9.25 * 0.82 = 7.585 -> 7.59
    assert stored.current_market_value == Decimal("7.59")
    assert stored.value_note is not None
    assert "LP" in stored.value_note
    assert "0.82" in stored.value_note


def test_refresh_applies_condition_adjustment_for_lp_plus(dynamo_repo):
    """LP+ uses midpoint(0.82, 1.00) = 0.91 (Phase 19)."""
    _seed_catalog(dynamo_repo)
    from merlins_collection.models.inventory import ConditionModifier
    item = RawInventoryItem(
        card_id=CARD_ID, cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.LP,
        condition_modifier=ConditionModifier.PLUS,
    )
    dynamo_repo.put_inventory_item(item)
    refresh_inventory_market_values(dynamo_repo)
    stored = dynamo_repo.get_inventory_item(item.item_id)
    # 9.25 * 0.91 = 8.4175 -> 8.42
    assert stored.current_market_value == Decimal("8.42")
    assert "LP+" in stored.value_note


def test_refresh_nm_gets_no_condition_note(dynamo_repo):
    """NM items get no value_note since 1.00x multiplier means no adjustment."""
    _seed_catalog(dynamo_repo)
    item = _raw_item()  # NM by default
    dynamo_repo.put_inventory_item(item)
    refresh_inventory_market_values(dynamo_repo)
    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.current_market_value == Decimal("9.25")
    assert stored.value_note is None


def test_snapshot_graded_prices_writes_history_for_owned_slabs(dynamo_repo):
    dynamo_repo.set_graded_market_value(
        CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    dynamo_repo.put_inventory_item(_graded_item())
    summary = snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))
    assert summary == {"graded_points_written": 1}
    hist = dynamo_repo.get_price_history(CARD_ID, company=GradingCompany.PSA, grade=Decimal("10"))
    assert hist[0].market == Decimal("500")


def test_run_daily_sync_combines_steps(dynamo_repo):
    # No pre-seeded catalog card: per RFC 0003 §7, `run_daily_sync` now runs
    # `refresh_held_prices` FIRST, so this item's price must come from the
    # injected `client`, not from `_seed_catalog`.
    item = _raw_item()
    dynamo_repo.put_inventory_item(item)
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})
    summary = run_daily_sync(dynamo_repo, client, date(2026, 6, 22))
    assert summary["items_refreshed"] == 1
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("9.25")


def test_sync_skips_unlinked_items_and_snapshots_sealed(dynamo_repo):
    unlinked = RawInventoryItem(card_id=None, finish="normal", condition="NM",
                                cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1))
    sealed = SealedInventoryItem(product_name="Box", product_type="booster_box",
                                 cost_basis=Decimal("400"),
                                 current_market_value=Decimal("500"),
                                 acquired_at=date(2026, 1, 1))
    dynamo_repo.put_inventory_item(unlinked)
    dynamo_repo.put_inventory_item(sealed)
    # must not raise on card_id=None / non-card kinds:
    assert refresh_inventory_market_values(dynamo_repo) == 0
    summary = snapshot_sealed_prices(dynamo_repo, date(2026, 3, 1))
    assert summary == {"sealed_points_written": 1}
    assert len(dynamo_repo.get_item_price_history(sealed.item_id)) == 1


def test_run_daily_sync_includes_graded_snapshot_and_refresh(dynamo_repo):
    # Own a graded slab and set its manual market value.
    dynamo_repo.set_graded_market_value(
        CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    item = _graded_item()
    dynamo_repo.put_inventory_item(item)
    # Graded slabs are EXCLUDED from the held-set predicate entirely (owner
    # decision, deviating from RFC §7's written predicate — see
    # test_refresh_held_prices_excludes_graded_slabs_entirely below): their
    # pricing and details are Phase 4's PSA-cert/PriceCharting business, not
    # this depth pass's. The client is never called for it, so an empty fake
    # is sufficient — not a 404-degrade workaround.
    client = FakeTcgdexClient()

    summary = run_daily_sync(dynamo_repo, client, date(2026, 6, 22))
    assert client.calls == []

    # merge completeness: graded snapshot key is present and counted
    assert summary["graded_points_written"] == 1
    # graded refresh write-back path: current_market_value denormalized from the manual graded value
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("500")


# ---------------------------------------------------------------------------
# refresh_held_prices — the Tier-2 depth pass (RFC 0003 §7)
# ---------------------------------------------------------------------------

# A second held card, priced in EUR via Cardmarket, to exercise the JP/EUR path
# alongside the EN/USD path in the same run.
RAW_JA = {
    "id": "swsh1-2", "localId": "2", "name": "Celebi V (JP)",
    "set": {"id": "swsh1", "name": "S&S"},
    "pricing": {"cardmarket": {
        "unit": "EUR", "updated": "2026-06-20T00:00:00.000Z", "trend": 5.00,
    }},
    "variants": {"normal": True},
}
HELD_ID_EN = "en:swsh1-1"
HELD_ID_JA = "ja:swsh1-2"
SOLD_ID = "en:swsh1-9"

STALE_RAW = _detail("swsh1-3", "3", market=3.00)
STALE_RAW["pricing"]["tcgplayer"]["updated"] = "2020-01-01T00:00:00.000Z"
STALE_HELD_ID = "en:swsh1-3"


def test_refresh_held_prices_writes_rarity_prices_and_history_for_held_cards(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id=HELD_ID_EN))  # AVAILABLE
    dynamo_repo.put_inventory_item(
        _raw_item(card_id=HELD_ID_JA, status=ItemStatus.ON_HOLD)
    )
    # A SOLD copy must be excluded from the held set entirely — never fetched.
    dynamo_repo.put_inventory_item(_raw_item(card_id=SOLD_ID, status=ItemStatus.SOLD))

    client = FakeTcgdexClient(cards={
        (Language.EN, "swsh1-1"): RAW,
        (Language.JP, "swsh1-2"): RAW_JA,
    })

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert summary["failures"] == 0
    assert len(client.calls) == 2  # exactly the two held cards, no more
    assert all(tcgdex_id != "swsh1-9" for _, tcgdex_id in client.calls)

    en_card = dynamo_repo.get_catalog_card(HELD_ID_EN)
    assert en_card.detail == "full"
    assert en_card.rarity == "Rare Holo V"
    assert en_card.prices["holofoil"].market == Decimal("9.25")

    ja_card = dynamo_repo.get_catalog_card(HELD_ID_JA)
    assert ja_card.prices["normal"].market == Decimal("5.40")  # EUR 5.00 * FX 1.08

    hist = dynamo_repo.get_price_history(HELD_ID_EN, finish="holofoil")
    assert hist[-1].market == Decimal("9.25")


def test_refresh_held_prices_excludes_graded_slabs_entirely(dynamo_repo):
    """Owner decision (deviates from RFC §7's written predicate, which has no
    `kind` filter — doc-writer will amend the RFC to match): graded slabs get
    their price AND descriptive detail from the PSA-cert/PriceCharting
    pipeline (Phase 4), not this depth pass. A card held ONLY as a graded slab
    must never be fetched and must get no catalog write at all."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    graded_only_id = "en:swsh1-7"
    dynamo_repo.put_inventory_item(_graded_item(card_id=graded_only_id))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-7"): _detail("swsh1-7", "7")})

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert client.calls == []  # never fetched
    assert dynamo_repo.get_catalog_card(graded_only_id) is None  # no catalog write
    assert summary["failures"] == 0


def test_refresh_held_prices_never_touches_graded_pricing(dynamo_repo):
    """Slab pricing stays owned by the graded pipeline: `refresh_held_prices`
    must never write a graded item's `current_market_value` and must never
    touch its `graded_price` row, since the card is excluded from its held set."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    graded_only_id = "en:swsh1-8"
    dynamo_repo.set_graded_market_value(
        graded_only_id, GradingCompany.PSA, Decimal("10"), Decimal("500")
    )
    item = _graded_item(card_id=graded_only_id)
    dynamo_repo.put_inventory_item(item)
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-8"): _detail("swsh1-8", "8")})

    refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    assert client.calls == []
    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value is None
    assert dynamo_repo.get_graded_market_value(
        graded_only_id, GradingCompany.PSA, Decimal("10")
    ) == Decimal("500")  # unchanged


def test_refresh_held_prices_excludes_sealed_items_with_no_card_id(dynamo_repo):
    """Sealed items have no `card_id` so they were always excluded, but this is
    now load-bearing (not merely incidental) alongside the graded exclusion —
    pin it explicitly."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    sealed = SealedInventoryItem(
        product_name="Box", product_type="booster_box",
        cost_basis=Decimal("400"), current_market_value=Decimal("500"),
        acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(sealed)
    client = FakeTcgdexClient()

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert client.calls == []
    assert summary["failures"] == 0


def test_refresh_held_prices_counts_a_per_card_failure_and_continues(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _seed_catalog(dynamo_repo)  # CARD_ID already has a market price of 9.25
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))  # will fail this run
    ok_id = "en:swsh1-5"
    dynamo_repo.put_inventory_item(_raw_item(card_id=ok_id))  # will succeed

    client = FakeTcgdexClient(
        cards={(Language.EN, "swsh1-5"): _detail("swsh1-5", "5", market=2.00)},
        errors={(Language.EN, "swsh1-1"): RuntimeError("boom")},
    )

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert summary["failures"] == 1
    assert not summary.get("aborted")
    # the failing card's PRE-EXISTING price is never deleted, zeroed or nulled
    still_there = dynamo_repo.get_catalog_card(CARD_ID)
    assert still_there.prices["holofoil"].market == Decimal("9.25")
    # the run continued on to the next card in the same pass
    ok_card = dynamo_repo.get_catalog_card(ok_id)
    assert ok_card.prices["holofoil"].market == Decimal("2.00")


def test_refresh_held_prices_aborts_after_max_consecutive_failures(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    for i in range(3):
        dynamo_repo.put_inventory_item(_raw_item(card_id=f"en:swsh1-{10 + i}"))

    client = FakeTcgdexClient(always_raise=RuntimeError("dead endpoint"))

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0, max_consecutive_failures=2)

    assert summary["aborted"] is True
    # must not burn a request against the third card once the threshold trips
    assert len(client.calls) == 2


def test_refresh_held_prices_consecutive_failure_counter_resets_on_success(dynamo_repo):
    """24-failures-then-one-success-then-more-failures, scaled down to 4 calls.

    Outcomes are keyed by CALL ORDER (see ``SequencedTcgdexClient``), not by
    which of the 4 held cards is being fetched — the held set's internal
    iteration order is a Python ``{...}`` set per the RFC and is explicitly
    not part of the contract under test, so this must hold regardless of it.
    """
    from merlins_collection.services.catalog_sync import refresh_held_prices

    for i in range(4):
        dynamo_repo.put_inventory_item(_raw_item(card_id=f"en:swsh1-{20 + i}"))

    client = SequencedTcgdexClient(outcomes=["fail", "ok", "fail", "fail"])

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0, max_consecutive_failures=2)

    # WITHOUT a reset, 3 cumulative failures (calls 1, 3, 4) would already
    # exceed the threshold of 2 by call #3, aborting after only 3 calls. WITH
    # a correct reset, the leading failure + intervening success clear the
    # streak, so the abort fires only on the second of the two TRAILING
    # failures — exactly 4 calls, not 3.
    assert len(client.calls) == 4
    assert summary["aborted"] is True
    assert summary["failures"] == 3


def test_refresh_held_prices_counts_a_404_as_not_found_not_a_failure(dynamo_repo):
    """A `None` return (the client's documented 404 contract) means TCGdex
    retired the card upstream — it is not an error and must not inflate
    `failures`, which is reserved for genuine per-card errors."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id="en:swsh1-60"))
    client = FakeTcgdexClient()  # no cards registered -> get_card returns None

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert summary["failures"] == 0
    assert summary["not_found"] == 1
    assert not summary.get("aborted")


def test_refresh_held_prices_leaves_an_existing_price_untouched_on_a_404(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _seed_catalog(dynamo_repo)  # CARD_ID already has a market price of 9.25
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient()  # returns None for every id -> 404

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert summary["not_found"] == 1
    card = dynamo_repo.get_catalog_card(CARD_ID)
    assert card.prices["holofoil"].market == Decimal("9.25")  # untouched, not nulled


def test_refresh_held_prices_404_neither_increments_nor_resets_the_failure_counter(dynamo_repo):
    """The subtle case: a 404 interleaved between two genuine failures must
    leave the consecutive-failure counter exactly where the two failures put
    it — neither counting itself in (aborting one call too early) nor
    resetting the streak (aborting one call too late, or not at all).

    outcomes = [fail, notfound, fail] with max_consecutive_failures=2:
      * correct (404 untouched): consec after call1=1, call2 (404) stays 1,
        call3 -> consec=2 -> ABORTS AT CALL 3.
      * wrong — 404 counts as a failure: call2 would itself push consec to 2
        and abort AT CALL 2 (one call too early).
      * wrong — 404 resets like a success: call2 would clear consec to 0, so
        call3 alone only reaches consec=1 and the run would continue past
        call3 into a 4th held card instead of aborting (one call too late).
    A 4th held card is present so the "resets" bug is distinguishable by call
    count, not just by the `aborted` flag.
    """
    from merlins_collection.services.catalog_sync import refresh_held_prices

    for i in range(4):
        dynamo_repo.put_inventory_item(_raw_item(card_id=f"en:swsh1-{70 + i}"))

    client = SequencedTcgdexClient(outcomes=["fail", "notfound", "fail", "fail"])

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0, max_consecutive_failures=2)

    assert len(client.calls) == 3
    assert summary["aborted"] is True
    assert summary["failures"] == 2
    assert summary["not_found"] == 1


# ---------------------------------------------------------------------------
# The "priceless success": HTTP 200, complete record, no usable price band.
# ---------------------------------------------------------------------------

# `_tcgplayer_prices` stores a band only when the provider published a `market`
# figure, so a `lowPrice` with a null `marketPrice` maps to NO band at all —
# which `services.tcgdex` documents as routine for thin-liquidity singles, not
# as an error. The response is otherwise complete and carries a fresh `rarity`.
PRICELESS_RAW = {
    "id": "swsh1-1", "localId": "1", "name": "Celebi V",
    "set": {"id": "swsh1", "name": "S&S"}, "rarity": "Rare Holo V (reprint)",
    "pricing": {"tcgplayer": {
        "unit": "USD", "updated": "2026-06-22T00:00:00.000Z",
        "holofoil": {"lowPrice": 0.11, "marketPrice": None},
    }},
}


def test_a_200_carrying_no_usable_price_never_erases_the_stored_price(dynamo_repo):
    """RFC 0003 §7: the depth pass "never deletes, zeroes, or nulls an existing
    price". The promise was kept for a total outage and for a 404, and broken for
    the far commoner case of a perfectly good 200 whose pricing block yields no
    band — no exception is raised, so nothing distinguishes it from a priced
    success, and the whole-item write replaced yesterday's band with `{}`.
    """
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _seed_catalog(dynamo_repo)  # CARD_ID priced at 9.25 by yesterday's pass
    assert dynamo_repo.get_catalog_card(CARD_ID).prices["holofoil"].market == Decimal("9.25")
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): PRICELESS_RAW})

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    card = dynamo_repo.get_catalog_card(CARD_ID)
    assert card.prices["holofoil"].market == Decimal("9.25")  # untouched, not nulled
    # ...while the identity data the SAME response did carry is still written:
    # skipping the write outright would trade one data problem for a smaller one.
    assert card.rarity == "Rare Holo V (reprint)"
    assert card.detail == "full"
    # ...and the state is counted, not reported as an ordinary success.
    assert summary["no_usable_price"] == 1
    assert summary["cards_updated"] == 1
    assert summary["failures"] == 0
    assert not summary.get("aborted")


def test_a_200_with_no_usable_price_still_creates_a_row_for_an_unseen_card(dynamo_repo):
    """No stored price to protect means nothing to preserve — the identity row
    must still land, or a newly acquired holding never gets one."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): PRICELESS_RAW})

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    card = dynamo_repo.get_catalog_card(CARD_ID)
    assert card is not None
    assert card.prices == {}
    assert card.rarity == "Rare Holo V (reprint)"
    assert summary["no_usable_price"] == 1


def test_a_price_preserved_through_a_priceless_day_is_replaced_the_next_day(dynamo_repo):
    """Preservation must not curdle into immutability: yesterday's band is kept
    only until upstream publishes a real one again."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _seed_catalog(dynamo_repo)  # 9.25
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))

    refresh_held_prices(dynamo_repo, FakeTcgdexClient(
        cards={(Language.EN, "swsh1-1"): PRICELESS_RAW}),
        date(2026, 6, 22), request_delay_seconds=0)
    assert dynamo_repo.get_catalog_card(CARD_ID).prices["holofoil"].market == Decimal("9.25")

    refresh_held_prices(dynamo_repo, FakeTcgdexClient(
        cards={(Language.EN, "swsh1-1"): _detail("swsh1-1", "1", market="2.00")}),
        date(2026, 6, 23), request_delay_seconds=0)
    assert dynamo_repo.get_catalog_card(CARD_ID).prices["holofoil"].market == Decimal("2.00")


def test_a_fully_priced_run_reports_no_usable_price_zero(dynamo_repo):
    """The new counter must discriminate, not just exist."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0)

    assert summary["no_usable_price"] == 0
    assert summary["cards_updated"] == 1


def test_refresh_held_prices_counts_a_legacy_non_composite_card_id_as_unparsable(dynamo_repo):
    """266 stored rows predate the composite-id scheme (commit 6685a28) and carry
    pokemontcg.io-era ids like `xy7-54`; a language this build does not speak is
    the same class of stored-data defect. Neither is fetchable, and counting them
    as failures would let a pocket of legacy rows abort the run every morning
    against a perfectly healthy endpoint — so `max_consecutive_failures=1` here
    is the discriminator, not decoration.
    """
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id="xy7-54"))     # legacy id
    dynamo_repo.put_inventory_item(_raw_item(card_id="fr:xy7-54"))  # unspoken language
    dynamo_repo.put_inventory_item(_raw_item(card_id=HELD_ID_EN))   # a real one
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                   request_delay_seconds=0, max_consecutive_failures=1)

    assert summary["unparsable_card_ids"] == 2
    assert summary["failures"] == 0
    assert not summary.get("aborted")
    assert summary["cards_updated"] == 1
    assert client.calls == [(Language.EN, "swsh1-1")]  # neither bad id was requested


def test_refresh_held_prices_annotates_but_does_not_suppress_a_stale_price(dynamo_repo):
    from merlins_collection.config import settings
    from merlins_collection.services.catalog_sync import refresh_held_prices

    assert settings.catalog_price_stale_days == 30  # documented default (RFC §7)

    dynamo_repo.put_inventory_item(_raw_item(card_id=STALE_HELD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-3"): STALE_RAW})

    refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    card = dynamo_repo.get_catalog_card(STALE_HELD_ID)
    band = card.prices["holofoil"]
    # the figure is STILL STORED -- never suppressed, hidden or nulled
    assert band.market == Decimal("3.00")
    assert band.value_note is not None
    assert "stale" in band.value_note.lower()


def test_refresh_held_prices_leaves_a_price_at_exactly_the_stale_threshold_unannotated(
    dynamo_repo,
):
    """``_staleness_note`` compares with ``<=``, so a price exactly
    ``catalog_price_stale_days`` old is still fresh -- only STRICTLY older gets a
    note. No other test in this file asserts ``value_note is None`` on a card it
    is not specifically testing as stale, so a regression that annotated every
    price regardless of age (e.g. a stray ``<`` -> unconditional, or an off-by-
    one flip to ``<``) would pass every other test here unnoticed."""
    from merlins_collection.services.catalog_sync import refresh_held_prices
    from merlins_collection.config import settings

    assert settings.catalog_price_stale_days == 30  # documented default (RFC §7)
    today = date(2026, 6, 22)
    exactly_at_threshold = today - timedelta(days=30)
    detail = _detail("swsh1-4", "4", market="4.00")
    detail["pricing"]["tcgplayer"]["updated"] = f"{exactly_at_threshold.isoformat()}T00:00:00.000Z"
    card_id = "en:swsh1-4"
    dynamo_repo.put_inventory_item(_raw_item(card_id=card_id))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-4"): detail})

    refresh_held_prices(dynamo_repo, client, today, request_delay_seconds=0)

    band = dynamo_repo.get_catalog_card(card_id).prices["holofoil"]
    assert band.market == Decimal("4.00")
    assert band.value_note is None


def test_refresh_held_prices_annotates_a_price_one_day_past_the_stale_threshold(dynamo_repo):
    """The other side of the same boundary: one day older than the threshold
    above IS stale. Pinned as its own test so the boundary is bracketed from
    both directions rather than inferred from a single sample far past it."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    today = date(2026, 6, 22)
    one_day_past_threshold = today - timedelta(days=31)
    detail = _detail("swsh1-5", "5", market="5.00")
    detail["pricing"]["tcgplayer"]["updated"] = (
        f"{one_day_past_threshold.isoformat()}T00:00:00.000Z"
    )
    card_id = "en:swsh1-5"
    dynamo_repo.put_inventory_item(_raw_item(card_id=card_id))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-5"): detail})

    refresh_held_prices(dynamo_repo, client, today, request_delay_seconds=0)

    band = dynamo_repo.get_catalog_card(card_id).prices["holofoil"]
    assert band.market == Decimal("5.00")
    assert band.value_note is not None
    assert "stale" in band.value_note.lower()


def test_refresh_held_prices_skips_when_catalog_lock_is_held(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _seed_catalog(dynamo_repo)
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))

    dynamo_repo.acquire_catalog_lock("reseed-in-flight")
    try:
        client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})
        summary = refresh_held_prices(dynamo_repo, client, date(2026, 6, 22),
                                       request_delay_seconds=0)
        assert summary == {"skipped": "catalog reseed in flight"}
        assert client.calls == []  # no request was even attempted
        # the pre-existing catalog price is completely untouched
        card = dynamo_repo.get_catalog_card(CARD_ID)
        assert card.prices["holofoil"].market == Decimal("9.25")
    finally:
        dynamo_repo.release_catalog_lock("reseed-in-flight")


def test_refresh_held_prices_releases_the_catalog_lock_after_a_normal_run(dynamo_repo):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    # the run's own lock must be gone -> a fresh acquire succeeds immediately
    dynamo_repo.acquire_catalog_lock("post-run-probe")
    dynamo_repo.release_catalog_lock("post-run-probe")


def test_refresh_held_prices_releases_the_catalog_lock_even_if_the_run_raises(
    dynamo_repo, monkeypatch
):
    from merlins_collection.services.catalog_sync import refresh_held_prices

    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    def _boom():
        raise RuntimeError("unexpected repo failure")

    monkeypatch.setattr(dynamo_repo, "list_inventory", _boom)

    with pytest.raises(RuntimeError):
        refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    # the lock must still be released via `finally`, never leaked by the raise
    dynamo_repo.acquire_catalog_lock("post-crash-probe")
    dynamo_repo.release_catalog_lock("post-crash-probe")


def _commit_catalog_generation(repo, gen):
    """Write the ``CATALOGGEN`` marker ``current_catalog_generation()`` reads.

    Stands in for the reseed's finalize step, which does not exist yet (per
    ``current_catalog_generation``'s own docstring: "a fresh table, or today's
    not-yet-wired reseed path" both read ``None``). There is no public writer
    for this marker pre-reseed, so the raw item is written directly — mirroring
    ``dynamo_repo._table.put_item`` usage already established in
    ``test_catalog_wipe.py`` for the same reason.
    """
    repo._table.put_item(Item={**repo._CATALOG_GEN_KEY, "gen": gen})


def test_refresh_held_prices_stamps_its_writes_with_the_committed_generation(dynamo_repo):
    """A depth-pass write landing after a reseed has passed a card but before its
    finalize must carry the CURRENT committed generation, or the very next purge
    sweeps it as "not of this generation" and the card silently disappears from
    a live catalog (RFC 0003 §8). Nothing else in this file ever commits a
    generation, so without this test the stamping branch in
    ``refresh_held_prices`` (``repo.set_catalog_generation(repo.current_catalog_
    generation())``) runs on every call but is only ever exercised with `None`.
    """
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _commit_catalog_generation(dynamo_repo, "G-committed")
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    raw_item = dynamo_repo._table.get_item(
        Key={"PK": f"CARD#{CARD_ID}", "SK": "META"}
    )["Item"]
    assert raw_item["cat_gen"] == "G-committed"
    # The stamp is not cosmetic: the row must actually survive the purge that
    # follows a reseed finalized under that same generation.
    dynamo_repo.purge_card_data(keep_catalog_gen="G-committed", dry_run=False)
    assert dynamo_repo.get_catalog_card(CARD_ID) is not None


def test_refresh_held_prices_clears_the_generation_stamp_after_a_normal_run(dynamo_repo):
    """The stamp is scoped to the run via the ``finally`` alongside the lock
    release. A write made AFTER the depth pass returns must NOT inherit its
    generation, or an unrelated later write becomes invisibly tied to a reseed
    it had nothing to do with — surviving purges it should not survive."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _commit_catalog_generation(dynamo_repo, "G-committed")
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})
    refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    other = to_catalog_card({**RAW, "id": "swsh1-99"}, Language.EN, fx_rate=FX)
    dynamo_repo.batch_upsert_catalog_cards([other])

    raw_item = dynamo_repo._table.get_item(
        Key={"PK": f"CARD#{other.card_id}", "SK": "META"}
    )["Item"]
    assert "cat_gen" not in raw_item


def test_refresh_held_prices_clears_the_generation_stamp_even_if_the_run_raises(
    dynamo_repo, monkeypatch
):
    """Mirrors ``test_refresh_held_prices_releases_the_catalog_lock_even_if_the_
    run_raises`` for the OTHER piece of state the same ``finally`` resets: an
    unexpected raise must not leave the instance stamping every later write
    with a generation from a run that never finished."""
    from merlins_collection.services.catalog_sync import refresh_held_prices

    _commit_catalog_generation(dynamo_repo, "G-committed")
    dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    def _boom():
        raise RuntimeError("unexpected repo failure")

    monkeypatch.setattr(dynamo_repo, "list_inventory", _boom)

    with pytest.raises(RuntimeError):
        refresh_held_prices(dynamo_repo, client, date(2026, 6, 22), request_delay_seconds=0)

    other = to_catalog_card({**RAW, "id": "swsh1-98"}, Language.EN, fx_rate=FX)
    dynamo_repo.batch_upsert_catalog_cards([other])

    raw_item = dynamo_repo._table.get_item(
        Key={"PK": f"CARD#{other.card_id}", "SK": "META"}
    )["Item"]
    assert "cat_gen" not in raw_item


def test_refresh_held_prices_request_delay_seconds_paces_and_is_configurable_to_zero(
    dynamo_repo, monkeypatch
):
    import merlins_collection.services.catalog_sync as catalog_sync_module
    from merlins_collection.services.catalog_sync import refresh_held_prices

    sleeps = []
    monkeypatch.setattr(catalog_sync_module.time, "sleep", lambda s: sleeps.append(s))

    for i in range(3):
        dynamo_repo.put_inventory_item(_raw_item(card_id=f"en:swsh1-{30 + i}"))
    cards = {(Language.EN, f"swsh1-{30 + i}"): RAW for i in range(3)}
    refresh_held_prices(dynamo_repo, FakeTcgdexClient(cards=cards), date(2026, 6, 22),
                        request_delay_seconds=0.25)
    assert sleeps and all(s == 0.25 for s in sleeps)

    sleeps.clear()
    for i in range(3):
        dynamo_repo.put_inventory_item(_raw_item(card_id=f"en:swsh1-{50 + i}"))
    cards2 = {(Language.EN, f"swsh1-{50 + i}"): RAW for i in range(3)}
    refresh_held_prices(dynamo_repo, FakeTcgdexClient(cards=cards2), date(2026, 6, 22),
                        request_delay_seconds=0)
    assert sleeps == []  # a zero delay must never sleep


def test_run_daily_sync_runs_the_depth_pass_before_the_denormalize_step(dynamo_repo):
    """Ordering is load-bearing (RFC §7): `refresh_inventory_market_values`
    reads catalog prices, so it must run AFTER `refresh_held_prices` writes
    them. No catalog card is pre-seeded here -- only the depth pass (driven by
    `client`) can populate one, so a wrong order leaves the item's
    `current_market_value` at None."""
    from merlins_collection.services.catalog_sync import refresh_held_prices  # noqa: F401

    item = _raw_item(card_id=CARD_ID)
    dynamo_repo.put_inventory_item(item)
    client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

    summary = run_daily_sync(dynamo_repo, client, date(2026, 6, 22))

    assert dynamo_repo.get_inventory_item(item.item_id).current_market_value == Decimal("9.25")
    assert summary["items_refreshed"] == 1
    # the depth pass's own summary keys are merged in too, not overwritten
    assert "failures" in summary


# ---------------------------------------------------------------------------
# PHASE 12 — inventory price correctness (RED phase, absorbs Phase 10)
#
# claude-progress.txt Section 3, Phase 12. `refresh_inventory_market_values`
# (this module, :74-103) does a bare exact-match `card.prices.get(item.finish)`
# instead of walking the SAME `_MARKET_FINISH_FALLBACK` chain the read path
# (`models.inventory._market_price`) already uses. Measured live: 174/213
# null `current_market_value`s trace to exactly this mismatch.
# ---------------------------------------------------------------------------


def test_refresh_resolves_normal_finish_item_via_holo_only_fallback(dynamo_repo):
    """THE single highest-value Phase 12 test (pins 155+11=166 of the 174 live
    nulls): a `normal`-finish raw item against a catalog card priced ONLY
    under `holofoil` must resolve a NON-NULL `current_market_value` through
    the fallback chain. Today the bare exact match leaves it `None`."""
    card = _catalog_card("en:swsh1-1", {"holofoil": Decimal("9.25")})
    dynamo_repo.batch_upsert_catalog_cards([card])
    item = RawInventoryItem(
        card_id="en:swsh1-1", finish="normal", condition=Condition.NM,
        cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(item)

    updated = refresh_inventory_market_values(dynamo_repo)

    assert updated == 1
    result = dynamo_repo.get_inventory_item(item.item_id)
    assert result.current_market_value == Decimal("9.25")


@pytest.mark.parametrize("fallback_finish", [f for f in _MARKET_FINISH_FALLBACK if f != "normal"])
def test_refresh_walks_the_same_canonical_fallback_order_as_the_read_path(
    dynamo_repo, fallback_finish,
):
    """Parametrized over EVERY non-trivial entry in `_MARKET_FINISH_FALLBACK`
    (models/inventory.py:199-202) — `holofoil`, `reverseHolofoil`,
    `1stEditionHolofoil`, `1stEditionNormal`, `unlimitedHolofoil` — so the
    write path is proven to walk the SAME chain the read path uses, not a
    re-invented one. A `normal`-finish item against a card priced ONLY under
    each fallback finish in turn must resolve through the write path."""
    card_id = f"en:swsh1-{fallback_finish}"
    card = _catalog_card(card_id, {fallback_finish: Decimal("4.50")})
    dynamo_repo.batch_upsert_catalog_cards([card])
    item = RawInventoryItem(
        card_id=card_id, finish="normal", condition=Condition.NM,
        cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(item)

    refresh_inventory_market_values(dynamo_repo)

    result = dynamo_repo.get_inventory_item(item.item_id)
    assert result.current_market_value == Decimal("4.50")


def test_refresh_resolves_via_last_resort_for_non_canonical_finishes(dynamo_repo):
    """Measured breakdown (Phase 10/12, 7 live items): a `normal`-finish item
    against a card priced only under `1stEdition`/`unlimited` — TCGdex finish
    names that are NOT themselves members of `_MARKET_FINISH_FALLBACK` but are
    still reached by `_market_price`'s final "any priced band" fallback
    (models/inventory.py:230-232). The write path must reach the same result
    as the read path for this non-canonical-but-real case too."""
    card = _catalog_card("en:base1-4", {
        "1stEdition": Decimal("120.00"), "unlimited": Decimal("60.00"),
    })
    dynamo_repo.batch_upsert_catalog_cards([card])
    item = RawInventoryItem(
        card_id="en:base1-4", finish="normal", condition=Condition.NM,
        cost_basis=Decimal("20"), acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(item)

    refresh_inventory_market_values(dynamo_repo)

    result = dynamo_repo.get_inventory_item(item.item_id)
    # dict insertion order is deterministic; "1stEdition" was inserted first,
    # matching what `_market_price`'s last-resort loop over `prices.values()`
    # picks for this same card today.
    assert result.current_market_value == Decimal("120.00")


_AGREEMENT_MATRIX = [
    # (item_finish, {catalog finish: market price})
    ("normal", {"holofoil": Decimal("9.25")}),
    ("normal", {"holofoil": Decimal("9.25"), "reverseHolofoil": Decimal("3.00")}),
    ("holofoil", {"normal": Decimal("2.00"), "holofoil": Decimal("9.25")}),
    ("reverseHolofoil", {"normal": Decimal("2.00")}),
    ("normal", {"1stEditionHolofoil": Decimal("300.00"), "unlimitedHolofoil": Decimal("50.00")}),
    ("normal", {}),  # genuinely priceless: both paths must agree on None
]


@pytest.mark.parametrize("item_finish,card_prices", _AGREEMENT_MATRIX)
def test_write_path_agrees_with_read_path_for_every_finish_combination(
    dynamo_repo, item_finish, card_prices,
):
    """THE ANTI-DRIFT TEST (Phase 12 SCOPE): whatever
    `refresh_inventory_market_values` WRITES onto `current_market_value` must
    equal what the read path (`_market_price` / `CardSummary.from_catalog`)
    RESOLVES for the identical item + card. Asserts BEHAVIORAL equality only —
    no assumption about a shared helper's name or import path, so the
    implementer is free to choose the refactor shape (e.g. the write path
    calling `_market_price` directly, or both calling a new common helper).
    Fails today for every row whose `item_finish` has no EXACT key in
    `card_prices`, since the write path does a bare exact match."""
    card_id = f"en:swsh1-agree-{item_finish}-{len(card_prices)}"
    card = _catalog_card(card_id, card_prices)
    dynamo_repo.batch_upsert_catalog_cards([card])
    item = RawInventoryItem(
        card_id=card_id, finish=item_finish, condition=Condition.NM,
        cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
    )
    dynamo_repo.put_inventory_item(item)

    refresh_inventory_market_values(dynamo_repo)

    written = dynamo_repo.get_inventory_item(item.item_id).current_market_value
    expected = _market_price(card, item_finish)
    assert written == expected
