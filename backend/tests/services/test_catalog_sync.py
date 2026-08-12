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
from merlins_collection.models.catalog import FinishPrice
from merlins_collection.services.catalog_sync import (
    refresh_inventory_market_values,
    run_daily_sync,
    snapshot_graded_prices,
    snapshot_sealed_prices,
    sync_new_sets,
)
from merlins_collection.services.tcgdex import build_card_id, to_catalog_card

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


# ---------------------------------------------------------------------------
# RFC 0010 T16 — hand-valued items: the invariant the whole feature rests on
# ---------------------------------------------------------------------------
#
# The owner's question was "what do we do when we have a card that doesn't have a
# matching catalog card? We still are selling it and we need a price for it."
# The answer is that a hand-typed value is SAFE, because this job skips an
# unlinked item entirely. That is load-bearing: if the nightly pass ever started
# writing over an unlinked item, hand valuation would silently be a lie and every
# UI T16 adds would be pointing at a number that disappears overnight.


def test_hand_set_value_on_an_unlinked_item_is_never_overwritten(dynamo_repo):
    """The invariant. An item with no ``card_id`` keeps whatever a human typed."""
    _seed_catalog(dynamo_repo)
    item = RawInventoryItem(
        card_id=None, cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.MP,
        current_market_value=Decimal("23.20"),
        value_note="Hand-valued 2026-08-11 - NM comp $40.00 x MP (0.58)",
    )
    dynamo_repo.put_inventory_item(item)

    refresh_inventory_market_values(dynamo_repo)

    stored = dynamo_repo.get_inventory_item(item.item_id)
    assert stored.current_market_value == Decimal("23.20")
    assert stored.value_note == "Hand-valued 2026-08-11 - NM comp $40.00 x MP (0.58)"


def test_a_linked_item_beside_it_is_still_refreshed(dynamo_repo):
    """The regression gate: skipping the unlinked one must not skip the rest."""
    _seed_catalog(dynamo_repo)
    unlinked = RawInventoryItem(
        card_id=None, cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        finish="holofoil", condition=Condition.NM,
        current_market_value=Decimal("99.99"),
    )
    linked = _raw_item()
    dynamo_repo.put_inventory_item(unlinked)
    dynamo_repo.put_inventory_item(linked)

    updated = refresh_inventory_market_values(dynamo_repo)

    assert updated == 1
    assert dynamo_repo.get_inventory_item(linked.item_id).current_market_value == Decimal("9.25")
    assert dynamo_repo.get_inventory_item(unlinked.item_id).current_market_value == Decimal("99.99")


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


# ---------------------------------------------------------------------------
# Task 2.8 — sync_new_sets: incremental catalog sync for newly released sets
# ---------------------------------------------------------------------------


class FakeSetsClient:
    """Serves ``list_sets``/``iter_brief_cards`` per language, mirroring
    ``FakeClient`` in ``tests/scripts/test_seed_catalog.py`` — the same shape,
    scoped to the two breadth-pass calls ``sync_new_sets`` reuses."""

    def __init__(self, sets_by_language=None, cards_by_language=None):
        self.sets_by_language = sets_by_language or {}
        self.cards_by_language = cards_by_language or {}
        self.set_calls = []
        self.card_calls = []

    def list_sets(self, language):
        self.set_calls.append(language)
        return self.sets_by_language.get(language, [])

    def iter_brief_cards(self, language):
        self.card_calls.append(language)
        yield from self.cards_by_language.get(language, [])


SWSH1_SET = {"id": "swsh1", "name": "Sword & Shield"}
SWSH2_SET = {"id": "swsh2", "name": "Rebel Clash"}

SWSH1_CARD_ROW = {"id": "swsh1-1", "localId": "1", "name": "Celebi V"}
SWSH2_CARD_ROWS = [
    {"id": "swsh2-1", "localId": "1", "name": "Grookey"},
    {"id": "swsh2-2", "localId": "2", "name": "Thwackey"},
]


def test_sync_new_sets_adds_only_missing_sets(dynamo_repo):
    """Two sets from the client, one already populated in the repo -> only the
    other's cards are written, and ``new_sets`` names exactly that one."""
    dynamo_repo.batch_upsert_catalog_cards([
        to_catalog_card_brief_for_test("swsh1", "1", "Celebi V"),
    ])
    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH1_SET, SWSH2_SET]},
        cards_by_language={Language.EN: [SWSH1_CARD_ROW, *SWSH2_CARD_ROWS]},
    )

    summary = sync_new_sets(dynamo_repo, client)

    assert summary["new_sets"] == ["en:swsh2"]
    assert summary["cards_added"] == 2
    assert summary["sets_checked"] == 2
    assert dynamo_repo.get_catalog_card("en:swsh2-1") is not None
    assert dynamo_repo.get_catalog_card("en:swsh2-2") is not None
    # the already-populated set is untouched: still exactly the one seeded card
    assert len(dynamo_repo.list_cards_by_set("en:swsh1")) == 1


def test_sync_new_sets_never_overwrites_existing_card(dynamo_repo):
    """The most important test: a card that already carries prices must survive
    a sync run untouched, even though the client's list response for the same
    set repeats its identity (with no pricing, as the list endpoint always is)."""
    priced = to_catalog_card_brief_for_test("swsh1", "1", "Celebi V")
    priced = priced.model_copy(update={
        "detail": "full",
        "prices": {"holofoil": FinishPrice(market=Decimal("9.25"))},
    })
    dynamo_repo.batch_upsert_catalog_cards([priced])
    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH1_SET]},
        cards_by_language={Language.EN: [SWSH1_CARD_ROW]},
    )

    summary = sync_new_sets(dynamo_repo, client)

    assert summary["new_sets"] == []
    assert summary["cards_added"] == 0
    stored = dynamo_repo.get_catalog_card("en:swsh1-1")
    assert stored.detail == "full"
    assert stored.prices["holofoil"].market == Decimal("9.25")


def test_sync_new_sets_writer_preserves_a_priced_card_even_when_misclassified_as_new(
    dynamo_repo, monkeypatch
):
    """Fix round 1 finding: the structural per-set skip above
    (``test_sync_new_sets_never_overwrites_existing_card``) proves the FIRST
    layer of the no-overwrite guarantee -- a set with any existing card is
    never walked, so the writer is never even called for it. That test alone
    would still pass if ``preserve_priced=True`` were deleted from the
    ``batch_upsert_catalog_cards`` call, or if its ``ConditionExpression``
    branch were entirely broken, because the writer path is never exercised.

    This test forces the SECOND, independent layer -- the conditional write
    itself -- to be the only thing standing between a priced row and data
    loss, by simulating the realistic failure mode that layer exists for: a
    ``list_cards_by_set``/``build_card_id`` mismatch, or a race with another
    writer, that makes a set with cards LOOK empty to the "is this set new"
    check. ``repo.list_cards_by_set`` is stubbed to always report empty even
    though ``en:swsh1-1`` demonstrably already exists (and is priced), which
    forces ``sync_new_sets`` to treat ``swsh1`` as new, walk its cards, and
    hand the pre-existing card's id to ``batch_upsert_catalog_cards(...,
    preserve_priced=True)`` for real. If that flag or its DynamoDB
    ``ConditionExpression`` regressed, this test fails.
    """
    priced = to_catalog_card_brief_for_test("swsh1", "1", "Celebi V")
    priced = priced.model_copy(update={
        "detail": "full",
        "prices": {"holofoil": FinishPrice(market=Decimal("9.25"))},
    })
    dynamo_repo.batch_upsert_catalog_cards([priced])
    assert dynamo_repo.get_catalog_card("en:swsh1-1") is not None  # sanity: it's really there

    monkeypatch.setattr(dynamo_repo, "list_cards_by_set", lambda set_id: [])

    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH1_SET]},
        cards_by_language={Language.EN: [SWSH1_CARD_ROW]},
    )

    summary = sync_new_sets(dynamo_repo, client)

    # misclassified as new by the stubbed (broken) membership check -- the
    # writer was actually reached, which is the point of this test
    assert summary["new_sets"] == ["en:swsh1"]
    assert summary["cards_added"] == 1

    stored = dynamo_repo.get_catalog_card("en:swsh1-1")
    assert stored.detail == "full"
    assert stored.prices["holofoil"].market == Decimal("9.25")  # untouched, not overwritten


def test_sync_new_sets_dry_run_writes_nothing(dynamo_repo):
    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH2_SET]},
        cards_by_language={Language.EN: SWSH2_CARD_ROWS},
    )

    summary = sync_new_sets(dynamo_repo, client, dry_run=True)

    assert summary["new_sets"] == ["en:swsh2"]
    assert dynamo_repo.list_cards_by_set("en:swsh2") == []
    assert dynamo_repo.get_catalog_card("en:swsh2-1") is None


# ---------------------------------------------------------------------------
# T8 — the catalog_set registry
#
# "List every set in the catalog" has no index: sets exist only as denormalized
# `set_id`/`set_name` fields on card rows, so answering it today means a full
# catalog scan -- the 11.2-second read T9 diagnosed as the cause of the dead
# catalog search. The registry is one small row per set (~400 total), written
# from the set-list response this sync ALREADY fetches, so it costs no extra
# upstream request.
# ---------------------------------------------------------------------------


def test_sync_new_sets_registers_every_set_not_just_the_new_ones(dynamo_repo):
    """The registry describes the whole catalog, so it must cover sets the sync
    skipped as already-populated.

    This is the easy thing to get wrong: the writer sits after ``sync_new_sets``'
    ``if not missing_set_ids: continue``, so a run where nothing is new
    registers nothing -- and the steady state of this job IS "nothing is new".
    """
    dynamo_repo.batch_upsert_catalog_cards([
        to_catalog_card_brief_for_test("swsh1", "1", "Celebi V"),
    ])
    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH1_SET, SWSH2_SET]},
        cards_by_language={Language.EN: [SWSH1_CARD_ROW, *SWSH2_CARD_ROWS]},
    )

    summary = sync_new_sets(dynamo_repo, client)

    # Reported, not just written: `scripts/scheduled_sync.py` prints this
    # summary as the monthly job's JSON output, and "how many sets got
    # registered" is the first thing to look at when the admin's set dropdown
    # comes back empty.
    assert summary["sets_registered"] == 2

    registry = {s["set_id"]: s for s in dynamo_repo.list_catalog_sets()}
    assert set(registry) == {"en:swsh1", "en:swsh2"}
    assert registry["en:swsh1"]["set_name"] == "Sword & Shield"
    assert registry["en:swsh1"]["language"] == "EN"
    # `card_count` is the rows WE hold for the set, in both writers -- not the
    # total TCGdex advertises. Half of TCGdex's Japanese sets advertise a card
    # count while carrying zero card rows, so the advertised figure would report
    # a set as covered when the catalog has nothing in it.
    assert registry["en:swsh1"]["card_count"] == 1
    assert registry["en:swsh2"]["card_count"] == 2  # counted AFTER its cards land


def test_sync_new_sets_dry_run_writes_no_registry_rows(dynamo_repo):
    """A dry run predicts; it does not mutate. The registry is no exception."""
    client = FakeSetsClient(
        sets_by_language={Language.EN: [SWSH2_SET]},
        cards_by_language={Language.EN: SWSH2_CARD_ROWS},
    )

    sync_new_sets(dynamo_repo, client, dry_run=True)

    assert dynamo_repo.list_catalog_sets() == []


def test_sync_new_sets_keeps_registry_rows_when_a_set_list_call_fails(dynamo_repo):
    """One language's outage must not erase that language's registry.

    ``_sync_new_sets`` already degrades a failed ``list_sets`` to "no new sets
    for this language". If the registry were rebuilt by replacing the whole
    list, the same outage would silently delete every JA set from the dropdown.
    """
    dynamo_repo.put_catalog_sets([{
        "set_id": "ja:sv1", "set_name": "スカーレット", "language": "JP",
        "card_count": 78, "updated_at": "2026-01-01T00:00:00+00:00",
    }])

    class FlakyClient(FakeSetsClient):
        def list_sets(self, language):
            if language is Language.JP:
                raise RuntimeError("upstream 503")
            return super().list_sets(language)

    client = FlakyClient(
        sets_by_language={Language.EN: [SWSH1_SET]},
        cards_by_language={Language.EN: [SWSH1_CARD_ROW]},
    )

    sync_new_sets(dynamo_repo, client)

    registry = {s["set_id"] for s in dynamo_repo.list_catalog_sets()}
    assert registry == {"ja:sv1", "en:swsh1"}


def to_catalog_card_brief_for_test(raw_set_id, local_id, name):
    """Builds a stored-shape brief `CatalogCard` for `en:{raw_set_id}-{local_id}`
    without going through the client, for pre-seeding the repo in a test."""
    from merlins_collection.models.catalog import CardImages, CatalogCard

    return CatalogCard(
        card_id=build_card_id(Language.EN, f"{raw_set_id}-{local_id}"),
        language=Language.EN,
        name=name,
        set_id=build_card_id(Language.EN, raw_set_id),
        set_name="",
        number=local_id,
        images=CardImages(),
        detail="brief",
        last_synced_at=datetime.now(tz=timezone.utc),
    )


# ===========================================================================
# RFC 0009 T7 — the nightly graded-pricing pass
# ===========================================================================
#
# T6 shipped the provider, the per-grade storage and the slab list, but nothing
# called `attach_price`. This is the job that walks the shelf.
#
# TWO OWNER DECISIONS (2026-08-09) drive what these tests assert, and both
# DEVIATE from the T7 doc as written:
#
# 1. **The job DOES do first contact.** The doc's RED item 5 says a slab with no
#    `price_source_id` is skipped, but that line predates T6: nothing anywhere
#    sets that id, so a job that skipped them would price nothing, ever, and
#    `attach_price`'s resolve branch would be dead code. The owner chose "run the
#    first name search; T6's verified join catches the bad matches".
# 2. **A hand-typed price is NOT protected unless it is explicitly PINNED.**
#    The owner rejected both "manual always wins" and "provider always wins".
#
# The other standing correction: the budget is **50 slabs, not 100**. A lookup
# costs 2 credits against a 100-credit free tier and is billed even on zero hits
# (spike-findings 2.1, measured). The doc's "refresh the 100 stalest" is the
# pre-measurement figure; follow-ups.md T0 row 1 assigns that doc fix to T8.

from merlins_collection.services.slab.pricing import (  # noqa: E402
    GradedPrices,
    PricingProviderError,
    PricingQuotaExceeded,
    ResolvedCard,
)
from merlins_collection.services.slab.quota import DailyQuota, QuotaExceeded  # noqa: E402

_CREDITS = 2  # 1 for the card + 1 for `includeEbay`; `costPerCard: 2`, measured


def _slab(card_id=CARD_ID, *, grade="10", cert="123", price_source_id=None,
          status=ItemStatus.AVAILABLE, company=GradingCompany.PSA, **over):
    """A graded item with the knobs this section needs.

    Deliberately not `_graded_item` above, which takes only a `card_id` — these
    tests turn on grade, status and `price_source_id`.
    """
    return GradedInventoryItem(
        card_id=card_id, listed_price=Decimal("700"), cost_basis=Decimal("300"),
        acquired_at=date(2026, 1, 1), company=company, grade=Decimal(grade),
        cert_number=cert, price_source_id=price_source_id, status=status, **over,
    )


def _prices(price_source_id="253266", **by_grade) -> GradedPrices:
    """Per-grade figures keyed the VENDOR's way (`psa10`), as T6 stores them.

    A grade absent from `by_grade` is absent from the result — never `0`.
    Confirmed against all 19 recorded fixtures: "no coverage" is a MISSING KEY
    (spike 2.2), and a slab silently valued at $0 drags every total while
    looking authoritative.
    """
    return GradedPrices(
        price_source_id=price_source_id,
        prices={k: Decimal(v) for k, v in by_grade.items()},
        confidences={k: "high" for k in by_grade},
        currency="USD", currency_assumed=True, as_of=None,
    )


def _resolved(price_source_id="253266", external_catalog_id="swsh1-1",
              **by_grade) -> ResolvedCard:
    """What the vendor's name search returns, prices riding along.

    `en:<external_catalog_id>` IS our `card_id` (spike 3.1) — that identity is
    the whole verified-join rule, so the default here joins onto `CARD_ID`.
    """
    return ResolvedCard(
        price_source_id=price_source_id, external_catalog_id=external_catalog_id,
        name="Celebi V", set_name="S&S", number="1",
        prices=_prices(price_source_id, **by_grade),
    )


class FakePricingProvider:
    """A `GradedPricing` implementation with a call log and no socket.

    It mirrors the real client's BILLING, which is the part these tests turn on:
    every call debits 2 credits, and the budget check happens BEFORE the answer,
    because you are billed on `limit` even when the search matches nothing
    (spike 2.1, measured — a zero-hit `limit=2` probe still cost 4 credits). A
    fake that answered for free would make every quota assertion vacuous.

    A `fail` entry bills and THEN raises, matching the 500 case: the real client
    debits as soon as the vendor answers, whatever it answered
    (`pricing.py::_get_cards`). A connection error, which never reaches the
    vendor, is the one shape that costs nothing — and is not what these test.
    """

    def __init__(self, *, by_id=None, by_name=None, quota=None, fail=()):
        self._by_id = dict(by_id or {})
        self._by_name = dict(by_name or {})
        self.quota = quota or DailyQuota(limit=100, key="test:pricing")
        self.resolve_calls: list[str] = []
        self.price_calls: list[str] = []
        self._fail = set(fail)

    @property
    def calls(self) -> list[str]:
        return self.resolve_calls + self.price_calls

    def _bill(self) -> None:
        try:
            self.quota.check(_CREDITS)
        except QuotaExceeded as exc:
            raise PricingQuotaExceeded(str(exc)) from exc
        self.quota.record(_CREDITS)

    def resolve(self, *, name, set_name, number, language=Language.EN):
        self._bill()
        self.resolve_calls.append(name)
        if name in self._fail:
            raise PricingProviderError("simulated vendor failure")
        return self._by_name.get(name)

    def prices(self, price_source_id):
        self._bill()
        self.price_calls.append(price_source_id)
        if price_source_id in self._fail:
            raise PricingProviderError("simulated vendor failure")
        return self._by_id.get(price_source_id)


def _write_priced_at(repo, card_id, when, *, grade="10", source="provider"):
    """Force a graded-price row's `updated_at`, which the writer stamps itself."""
    repo.set_graded_market_value(card_id, GradingCompany.PSA, Decimal(grade),
                                 Decimal("100"), source=source)
    row = repo.get_graded_price_row(card_id, GradingCompany.PSA, Decimal(grade))
    row["updated_at"] = when
    repo._table.put_item(Item=row)


class TestRefreshGradedPrices:
    """RED 1-11. The loop that spends real money, unattended."""

    def test_a_run_prices_owned_slabs_and_writes_graded_price_rows(self, dynamo_repo):
        """RED 1."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_priced"] == 1
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10")) == Decimal("2479.5")

    def test_a_slab_with_no_cached_id_is_resolved_once_and_the_id_is_kept(
            self, dynamo_repo):
        """The owner's first-contact decision. The fuzzy search runs ONCE; the
        vendor id it yields is cached on the item so every later night is the
        exact `prices(id)` call, which is both cheaper and more correct — the
        search is where T0 measured the wrong answers coming from."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        item = _slab()
        dynamo_repo.put_inventory_item(item)
        provider = FakePricingProvider(by_name={"Celebi V": _resolved(psa10="2479.5")})

        refresh_graded_prices(dynamo_repo, provider)

        assert provider.resolve_calls == ["Celebi V"]
        assert dynamo_repo.get_inventory_item(item.item_id).price_source_id == "253266"
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10")) == Decimal("2479.5")

    def test_a_second_run_never_searches_again(self, dynamo_repo):
        """The point of caching the id: `resolve()` runs at most once per card,
        ever. A second night is an exact lookup and no fuzzy call at all."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(_slab())
        first = FakePricingProvider(by_name={"Celebi V": _resolved(psa10="2479.5")})
        refresh_graded_prices(dynamo_repo, first)

        second = FakePricingProvider(by_id={"253266": _prices(psa10="2500")},
                                     by_name={"Celebi V": _resolved(psa10="2479.5")})
        refresh_graded_prices(dynamo_repo, second)

        assert second.resolve_calls == []
        assert second.price_calls == ["253266"]

    def test_two_slabs_of_the_same_card_and_grade_cost_one_lookup(self, dynamo_repo):
        """RED 3. Deduped by `(card_id, company, grade)` — and the reason is now
        money, not tidiness."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(_slab(cert="1", price_source_id="253266"))
        dynamo_repo.put_inventory_item(_slab(cert="2", price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        refresh_graded_prices(dynamo_repo, provider)

        assert len(provider.calls) == 1
        assert provider.quota.spent == _CREDITS

    def test_two_grades_of_the_same_card_also_cost_one_lookup(self, dynamo_repo):
        """One response carries EVERY grade (~23 buckets, spike 2.2), so a PSA 9
        and a PSA 10 of one card are one call, not two. Without this the fuzzy
        search would also run twice for a single card — 4 credits, and twice the
        exposure to the wrong-card answer the join exists to catch."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(_slab(cert="1", grade="10"))
        dynamo_repo.put_inventory_item(_slab(cert="2", grade="9"))
        provider = FakePricingProvider(
            by_name={"Celebi V": _resolved(psa10="2479.5", psa9="929.67")},
            by_id={"253266": _prices(psa10="2479.5", psa9="929.67")},
        )

        refresh_graded_prices(dynamo_repo, provider)

        assert len(provider.calls) == 1, "one card is one lookup, whatever we hold of it"
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10")) == Decimal("2479.5")
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("9")) == Decimal("929.67")

    def test_a_slab_with_no_card_id_is_skipped_and_spends_nothing(self, dynamo_repo):
        """RED 4. Unlinked is a NORMAL state that Triage already surfaces — not
        an error, and never a billed call. `attach_price` would refuse it anyway,
        but only after paying 2 credits for the answer."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.put_inventory_item(_slab(card_id=None, display_name="Celebi V"))
        provider = FakePricingProvider(by_name={"Celebi V": _resolved(psa10="1")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert provider.calls == []
        assert provider.quota.spent == 0
        assert summary["graded_skipped"] == 1
        assert summary["graded_priced"] == 0

    def test_a_sold_slab_is_not_a_candidate(self, dynamo_repo):
        """Mirrors `_held_card_ids`: a live market figure for something we no
        longer own has no consumer (RFC 0003 section 7), and here it would cost 2
        of the day's 50 lookups to produce one."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(
            _slab(price_source_id="253266", status=ItemStatus.SOLD))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert provider.calls == []
        assert summary["graded_candidates"] == 0

    def test_the_run_is_capped_at_fifty_lookups_on_a_hundred_credit_budget(
            self, dynamo_repo):
        """RED 6, with the measured budget. The doc says "150 candidates, quota
        100 -> 100 refreshed"; that assumed 1 credit per slab. It is **2**
        (`costPerCard: 2`, confirmed live), so a 100-credit free tier is FIFTY
        slabs a night. Correcting the doc and the RFC is T8's job (follow-ups.md
        T0 row 1) — the behaviour is corrected here."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        by_id = {}
        for n in range(150):
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%d" % n, cert=str(n), price_source_id=str(n)))
            by_id[str(n)] = _prices(str(n), psa10="100")
        quota = DailyQuota(limit=100, key="test:pricing")
        provider = FakePricingProvider(by_id=by_id, quota=quota)

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_candidates"] == 150
        assert len(provider.calls) == 50
        assert summary["graded_priced"] == 50
        assert quota.spent == 100

    def test_never_priced_slabs_are_refreshed_before_stale_ones(self, dynamo_repo):
        """RED 7. A slab with no value at all is more urgent than one priced
        yesterday, and with the budget smaller than the shelf, "urgent" is the
        only thing that decides who gets tonight's credits."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        for n in (1, 2):
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%d" % n, cert=str(n), price_source_id=str(n)))
            _write_priced_at(dynamo_repo, "en:swsh1-%d" % n, "2026-08-08T00:00:00+00:00")
        # Never priced: no graded_price row at all.
        dynamo_repo.put_inventory_item(
            _slab(card_id="en:swsh1-3", cert="3", price_source_id="3"))

        quota = DailyQuota(limit=_CREDITS, key="test:pricing")  # exactly one lookup
        provider = FakePricingProvider(
            by_id={str(n): _prices(str(n), psa10="200") for n in (1, 2, 3)},
            quota=quota,
        )

        refresh_graded_prices(dynamo_repo, provider)

        assert provider.calls == ["3"], "the never-priced slab must go first"

    def test_the_stalest_priced_slab_goes_before_a_fresher_one(self, dynamo_repo):
        """The second half of RED 7: among slabs that DO have a value, oldest
        first, so nothing can starve behind a slab priced last night."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        for n in (1, 2):
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%d" % n, cert=str(n), price_source_id=str(n)))
        _write_priced_at(dynamo_repo, "en:swsh1-1", "2026-08-08T00:00:00+00:00")
        _write_priced_at(dynamo_repo, "en:swsh1-2", "2026-01-01T00:00:00+00:00")

        quota = DailyQuota(limit=_CREDITS, key="test:pricing")
        provider = FakePricingProvider(
            by_id={str(n): _prices(str(n), psa10="200") for n in (1, 2)}, quota=quota)

        refresh_graded_prices(dynamo_repo, provider)

        assert provider.calls == ["2"], "January is staler than August"

    def test_one_provider_failure_does_not_abort_the_run(self, dynamo_repo):
        """RED 8. A hiccup on slab 3 of 80 must not cost the other 77."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        by_id = {}
        for n in (1, 2, 3):
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%d" % n, cert=str(n), price_source_id=str(n)))
            by_id[str(n)] = _prices(str(n), psa10="100")
        provider = FakePricingProvider(by_id=by_id, fail={"2"})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_failures"] == 1
        assert summary["graded_priced"] == 2
        assert dynamo_repo.get_graded_market_value(
            "en:swsh1-3", GradingCompany.PSA, Decimal("10")) == Decimal("100")

    def test_a_dead_vendor_stops_the_run_instead_of_burning_the_budget(
            self, dynamo_repo):
        """Every failed call is still BILLED — the real client debits as soon as
        the vendor answers, whatever it answered. So a vendor returning 500 to
        everything would spend the whole day's budget producing nothing. Mirrors
        `refresh_held_prices`' consecutive-failure abort, with a much tighter cap
        because here the unit of waste is money rather than a free request."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        ids = [str(n) for n in range(20)]
        for n in ids:
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%s" % n, cert=n, price_source_id=n))
        provider = FakePricingProvider(by_id={}, fail=set(ids))

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_aborted"] is True
        assert len(provider.calls) <= 5

    def test_a_provider_error_is_never_recorded_as_no_coverage(self, dynamo_repo):
        """The distinction T6's docstring exists to protect: `PricingProviderError`
        means the vendor is down, `None` means there is no price. Conflating them
        is how a nightly job overwrites good prices with silence."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("999"))
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        provider = FakePricingProvider(fail={"253266"})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_failures"] == 1
        assert summary["graded_unpriced"] == 0, "a failure is not 'no coverage'"
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10")) == Decimal("999")

    def test_an_uncovered_grade_writes_no_row_and_is_counted_separately(
            self, dynamo_repo):
        """"No coverage" is an ABSENT KEY, never `0` — confirmed against all 19
        recorded fixtures. T6 refuses to write a row at all in that case, and NO
        ROW beats a row saying $0: an unpriced slab is visibly unpriced, a $0 one
        quietly drags every total."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.put_inventory_item(_slab(grade="3", price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_unpriced"] == 1
        assert summary["graded_priced"] == 0
        assert dynamo_repo.get_graded_price_row(
            CARD_ID, GradingCompany.PSA, Decimal("3")) is None

    def test_quota_exhausted_mid_run_stops_cleanly_and_reports_it(self, dynamo_repo):
        """RED 10. `PricingQuotaExceeded` SUBCLASSES `PricingProviderError`, so a
        loop that caught the parent first would book the budget running out as a
        per-item failure and spin through every remaining candidate collecting
        429s — the exact thing the doc says not to do."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        by_id = {}
        for n in range(5):
            dynamo_repo.put_inventory_item(
                _slab(card_id="en:swsh1-%d" % n, cert=str(n), price_source_id=str(n)))
            by_id[str(n)] = _prices(str(n), psa10="100")
        quota = DailyQuota(limit=100, key="test:pricing")
        quota.record(96)  # room for exactly two more lookups
        provider = FakePricingProvider(by_id=by_id, quota=quota)

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_quota_exhausted"] is True
        assert summary["graded_priced"] == 2
        assert summary["graded_failures"] == 0, "running out of budget is not a failure"
        assert len(provider.calls) == 2, "no spinning through the remainder"

    def test_the_run_opens_no_socket_of_its_own(self, dynamo_repo, monkeypatch):
        """RED 9 — **zero PSA calls**. A cert's identity is immutable and
        population is `null` on the public API (RFC section 5.1), so there is
        nothing about a slab to refresh from PSA.

        There is no PSA client to hand a spy to (T2 is deferred whole), so the
        assertion is the stronger available one: every outbound HTTP call is
        blocked for the duration of the run. The injected provider is the ONLY
        collaborator; anything constructing its own client — a PSA lookup, a
        second pricing client, an image fetch — fails loudly here."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        def no_network(*args, **kwargs):
            raise AssertionError("the nightly graded pass opened its own socket")

        monkeypatch.setattr("httpx.Client.send", no_network)
        monkeypatch.setattr("httpx.Client.request", no_network)

        _seed_catalog(dynamo_repo)
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert summary["graded_priced"] == 1
        assert provider.price_calls == ["253266"]

    def test_the_summary_reports_what_an_unattended_run_did(self, dynamo_repo):
        """The only visibility into a job that runs while nobody is watching."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        summary = refresh_graded_prices(
            dynamo_repo, FakePricingProvider(by_id={"253266": _prices(psa10="1")}))

        for key in ("graded_candidates", "graded_priced", "graded_skipped",
                    "graded_unpriced", "graded_failures", "graded_pinned",
                    "graded_quota_exhausted", "graded_aborted",
                    "graded_credits_remaining"):
            assert key in summary, "%s missing from the run summary" % key


class TestPinnedPrices:
    """RED 11 — the owner's precedence decision, 2026-08-09.

    A hand-typed price is **not** protected by default; pinning is a separate,
    deliberate action. The alternative ("manual always wins") was rejected: it
    would freeze every slab the owner had ever touched out of automatic pricing
    forever, and `/admin/slabs?priced=false` would not surface them either,
    because they DO have a value.
    """

    def test_a_pinned_price_is_never_overwritten_and_costs_no_credit(self, dynamo_repo):
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("5000"),
            source="manual", pinned=True)
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = refresh_graded_prices(dynamo_repo, provider)

        assert provider.calls == [], "a pinned slab must not even be looked up"
        assert summary["graded_pinned"] == 1
        assert dynamo_repo.get_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10")) == Decimal("5000")

    def test_an_unpinned_manual_price_is_refreshed_by_the_provider(self, dynamo_repo):
        """The other half of the decision, and the one that makes it a choice
        rather than a default: an ordinary hand-typed value is a bootstrap, and
        the provider's per-grade comps replace it."""
        from merlins_collection.services.catalog_sync import refresh_graded_prices

        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("5000"),
            source="manual")
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        refresh_graded_prices(dynamo_repo, provider)

        row = dynamo_repo.get_graded_price_row(CARD_ID, GradingCompany.PSA, Decimal("10"))
        assert row["market_value"] == Decimal("2479.5")
        assert row["source"] == "provider"

    def test_rewriting_a_price_by_hand_does_not_silently_clear_its_pin(
            self, dynamo_repo):
        """`set_graded_market_value` is a whole-row `put_item`, so a later write
        that says nothing about the pin would drop it — and the owner would find
        out only when the provider quietly replaced the figure they protected."""
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("5000"),
            source="manual", pinned=True)
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("5500"),
            source="manual")

        row = dynamo_repo.get_graded_price_row(CARD_ID, GradingCompany.PSA, Decimal("10"))
        assert row["market_value"] == Decimal("5500")
        assert row["pinned"] is True


class TestSnapshotSource:
    """RED 2. A chart has to be able to tell a hand-typed point from a fetched
    one; before T7 every graded point was stamped `source="manual"` regardless."""

    def test_a_provider_sourced_point_carries_the_provider_as_its_source(
            self, dynamo_repo):
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("2479.5"),
            source="provider", confidence="high")
        dynamo_repo.put_inventory_item(_slab())

        snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))

        point = dynamo_repo.get_price_history(
            CARD_ID, company=GradingCompany.PSA, grade=Decimal("10"))[0]
        assert point.source == "provider"
        assert point.market == Decimal("2479.5")

    def test_a_hand_typed_point_still_says_manual(self, dynamo_repo):
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500"))
        dynamo_repo.put_inventory_item(_slab())

        snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))

        point = dynamo_repo.get_price_history(
            CARD_ID, company=GradingCompany.PSA, grade=Decimal("10"))[0]
        assert point.source == "manual"

    def test_still_one_point_per_card_company_grade_per_day(self, dynamo_repo):
        """Unchanged by T7, and pinned here because the fetch step now runs
        immediately before it."""
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500"))
        dynamo_repo.put_inventory_item(_slab(cert="1"))
        dynamo_repo.put_inventory_item(_slab(cert="2"))

        summary = snapshot_graded_prices(dynamo_repo, date(2026, 6, 22))

        assert summary == {"graded_points_written": 1}


class TestDailySyncWiring:
    """The nightly job as cron actually runs it."""

    def test_the_daily_sync_prices_slabs_before_it_snapshots_them(self, dynamo_repo):
        """Order is load-bearing, exactly as it is for the depth pass: fetch,
        then snapshot, then denormalize. The other order publishes yesterday's
        figure for a day and makes every new slab wait two runs for its first
        price point."""
        from merlins_collection.services.catalog_sync import run_daily_sync

        _seed_catalog(dynamo_repo)
        item = _slab(price_source_id="253266")
        dynamo_repo.put_inventory_item(item)
        provider = FakePricingProvider(by_id={"253266": _prices(psa10="2479.5")})

        summary = run_daily_sync(dynamo_repo, FakeTcgdexClient(), date(2026, 6, 22),
                                 pricing_provider=provider)

        assert summary["graded_priced"] == 1
        point = dynamo_repo.get_price_history(
            CARD_ID, company=GradingCompany.PSA, grade=Decimal("10"))[0]
        assert point.market == Decimal("2479.5")
        assert point.source == "provider"
        assert dynamo_repo.get_inventory_item(
            item.item_id).current_market_value == Decimal("2479.5")

    def test_the_daily_sync_survives_an_unconfigured_pricing_key(self, dynamo_repo,
                                                                 monkeypatch):
        """The whole nightly job must not die because one provider is not set up.
        `PokemonPriceTrackerClient.__init__` RAISES on an empty key, and T8's
        checklist includes rotating both keys — so "no key today" is a state this
        job will really meet, and the depth pass, both snapshots and the
        denormalization all have to survive it."""
        from merlins_collection.config import settings
        from merlins_collection.services.catalog_sync import run_daily_sync

        # Forced empty rather than assumed empty. `env_file=".env"` is resolved
        # against the CWD, so a run started from `backend/` would load the REAL
        # key — and this test would then make a live, BILLED vendor call.
        monkeypatch.setattr(settings, "pokemonpricetracker_api_key", "")

        _seed_catalog(dynamo_repo)
        dynamo_repo.set_graded_market_value(
            CARD_ID, GradingCompany.PSA, Decimal("10"), Decimal("500"))
        dynamo_repo.put_inventory_item(_slab(price_source_id="253266"))

        summary = run_daily_sync(dynamo_repo, FakeTcgdexClient(), date(2026, 6, 22))

        assert summary["graded_priced"] == 0
        assert summary["graded_points_written"] == 1, "the snapshot still ran"
        assert summary["items_refreshed"] == 1, "the denormalization still ran"


# ===========================================================================
# RFC 0010 T17 — the weekly catalog price cycle
#
# `refresh_held_prices` prices only the ~300 cards the business OWNS. Every
# other row in the 31,603-row catalog has no price at all, which is backwards
# for the Buy table: the card someone is trying to sell you is by definition one
# you do not own yet. T17 adds a second pass that walks the REST of the catalog,
# ~5,500 cards a night, stalest-first, so every row is re-priced at least once a
# week.
#
# A single full-catalog pass per night is not viable and the reason is the LOCK,
# not the clock: 31,603 x 0.262s = 2h18m, which outlives the catalog lock's
# 3600s TTL, at which point the lock looks like a crashed holder and becomes
# stealable — and a write landing across a reseed's swap carries the superseded
# generation and is swept, so the card silently disappears from a live catalog.
# ===========================================================================

CATALOG_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _cat_card(card_id, *, detail="full", synced=None, prices=None, name="Card"):
    """A stored catalog row with an EXACT `detail` and `last_synced_at`.

    Those two fields are the entire ordering predicate for the weekly cycle, so
    every test here sets them precisely rather than inheriting "now".
    """
    return CatalogCard(
        card_id=card_id, name=name, set_id="en:swsh1", set_name="S&S", number="1",
        images=CardImages(), detail=detail,
        last_synced_at=synced or CATALOG_EPOCH,
        prices={f: FinishPrice(market=m) for f, m in (prices or {}).items()},
    )


def _seed_cards(repo, cards):
    repo.batch_upsert_catalog_cards(cards)


class _FakeClock:
    """A deterministic stand-in for the `time` module inside `catalog_sync`.

    Patched over the module's `time` REFERENCE rather than over `time.monotonic`
    itself, so a test that fast-forwards this job's clock cannot perturb
    botocore's or moto's.
    """

    def __init__(self, *, step=0.0):
        self.now = 0.0
        self.step = step
        self.sleeps = []

    def monotonic(self):
        value = self.now
        self.now += self.step
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)


class TestCatalogRefreshCandidates:
    """Which cards tonight's cycle picks, and in what order."""

    def test_a_never_priced_card_outranks_a_stale_priced_one_even_when_newer(
        self, dynamo_repo,
    ):
        """THE trap: `last_synced_at` is bumped by ANY write, including the
        breadth pass — so a `brief` row `sync_new_sets` wrote yesterday looks
        FRESHER than a priced row from last week while having no price at all.
        Ordering on the timestamp alone pushes brand-new, never-priced cards to
        the back of the queue, which is exactly the population this cycle exists
        to reach. `detail` is therefore checked FIRST, not as a tiebreak.
        """
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-100", detail="full",
                      synced=datetime(2020, 1, 1, tzinfo=timezone.utc)),
            _cat_card("en:swsh1-101", detail="brief",
                      synced=datetime(2026, 8, 10, tzinfo=timezone.utc)),
        ])

        assert select_catalog_refresh_candidates(dynamo_repo, limit=1) == [
            "en:swsh1-101"
        ]

    def test_priced_rows_are_ordered_oldest_first(self, dynamo_repo):
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-110", synced=datetime(2026, 8, 1, tzinfo=timezone.utc)),
            _cat_card("en:swsh1-111", synced=datetime(2026, 6, 1, tzinfo=timezone.utc)),
            _cat_card("en:swsh1-112", synced=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        ])

        assert select_catalog_refresh_candidates(dynamo_repo, limit=3) == [
            "en:swsh1-111", "en:swsh1-112", "en:swsh1-110",
        ]

    def test_the_selection_is_capped_at_the_nightly_budget(self, dynamo_repo):
        """The cap is the whole design: 5,500 x 0.262s is ~24 min against a
        3600s lock TTL, where the full catalog is 2h18m and blows it."""
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        _seed_cards(dynamo_repo, [
            _cat_card(f"en:swsh1-{120 + i}", synced=CATALOG_EPOCH + timedelta(days=i))
            for i in range(5)
        ])

        assert len(select_catalog_refresh_candidates(dynamo_repo, limit=2)) == 2

    def test_held_cards_are_excluded_because_the_daily_pass_covers_them(
        self, dynamo_repo,
    ):
        """Fetching a card twice in one night is pure waste, and disjoint
        candidate sets keep the two passes' summaries readable."""
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-130"),
            _cat_card("en:swsh1-131"),
        ])
        dynamo_repo.put_inventory_item(_raw_item(card_id="en:swsh1-130"))

        assert select_catalog_refresh_candidates(dynamo_repo, limit=10) == [
            "en:swsh1-131"
        ]

    def test_a_sold_copy_does_not_exclude_a_card_from_the_catalog_cycle(
        self, dynamo_repo,
    ):
        """`_held_card_ids` counts only AVAILABLE/ON_HOLD, so a card we used to
        own gets no daily refresh — it must fall through to the weekly cycle
        rather than into the gap between the two passes."""
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        _seed_cards(dynamo_repo, [_cat_card("en:swsh1-135")])
        dynamo_repo.put_inventory_item(
            _raw_item(card_id="en:swsh1-135", status=ItemStatus.SOLD)
        )

        assert select_catalog_refresh_candidates(dynamo_repo, limit=10) == [
            "en:swsh1-135"
        ]

    def test_a_night_where_every_card_is_fresh_still_selects_the_stalest(
        self, dynamo_repo,
    ):
        """The cycle keeps turning. Selecting nothing once everything is fresh
        would make the first full week the only week that ever runs."""
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        now = datetime.now(tz=timezone.utc)
        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-140", synced=now - timedelta(minutes=1)),
            _cat_card("en:swsh1-141", synced=now - timedelta(minutes=5)),
        ])

        assert select_catalog_refresh_candidates(dynamo_repo, limit=1) == [
            "en:swsh1-141"
        ]

    def test_graded_and_sealed_inventory_contribute_no_candidates(self, dynamo_repo):
        """Candidates come from the CATALOG, never from inventory. A sealed box
        has no `card_id` field at all (not merely a null one) and a slab's price
        comes from the graded pipeline, so neither may invent a row to fetch."""
        from merlins_collection.services.catalog_sync import (
            select_catalog_refresh_candidates,
        )

        dynamo_repo.put_inventory_item(_graded_item(card_id="en:swsh1-150"))
        dynamo_repo.put_inventory_item(SealedInventoryItem(
            product_name="Box", product_type="booster_box",
            cost_basis=Decimal("400"), acquired_at=date(2026, 1, 1),
        ))

        assert select_catalog_refresh_candidates(dynamo_repo, limit=10) == []


class TestRefreshCatalogPrices:
    """The pass itself — the shared per-card body, the budget and the lock."""

    def test_a_priceless_success_never_deletes_the_stored_bands(self, dynamo_repo):
        """The extraction's regression gate. `_refresh_held_prices`' per-card
        body is a specification, not a loop: an HTTP 200 whose pricing block
        yields no band must still be written (it can carry a corrected rarity)
        but through `upsert_catalog_card_preserving_prices`, so yesterday's
        bands survive. Sharing the body is the only way both passes keep it."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card(CARD_ID, prices={"holofoil": Decimal("9.25")}),
        ])
        client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): PRICELESS_RAW})

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         cards_per_night=10,
                                         request_delay_seconds=0)

        card = dynamo_repo.get_catalog_card(CARD_ID)
        assert card.prices["holofoil"].market == Decimal("9.25")  # not nulled
        assert card.rarity == "Rare Holo V (reprint)"
        assert summary["catalog_no_usable_price"] == 1
        assert summary["catalog_cards_updated"] == 1
        assert summary["catalog_failures"] == 0

    def test_a_404_is_not_found_and_neither_increments_nor_resets_the_counter(
        self, dynamo_repo,
    ):
        """Same discriminator as the depth pass's own 404 test: with
        `max_consecutive_failures=2` and outcomes [fail, notfound, fail], a 404
        that counted would abort one call early and one that reset would abort
        one call late."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card(f"en:swsh1-{160 + i}",
                      synced=CATALOG_EPOCH + timedelta(days=i))
            for i in range(4)
        ])
        client = SequencedTcgdexClient(outcomes=["fail", "notfound", "fail", "fail"])

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         cards_per_night=10,
                                         request_delay_seconds=0,
                                         max_consecutive_failures=2)

        assert len(client.calls) == 3
        assert summary["catalog_aborted"] is True
        assert summary["catalog_failures"] == 2
        assert summary["catalog_not_found"] == 1

    def test_a_per_card_error_is_counted_and_the_run_continues(self, dynamo_repo):
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-1", prices={"holofoil": Decimal("9.25")},
                      synced=CATALOG_EPOCH),
            _cat_card("en:swsh1-5", synced=CATALOG_EPOCH + timedelta(days=1)),
        ])
        client = FakeTcgdexClient(
            cards={(Language.EN, "swsh1-5"): _detail("swsh1-5", "5", market="2.00")},
            errors={(Language.EN, "swsh1-1"): RuntimeError("boom")},
        )

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         cards_per_night=10,
                                         request_delay_seconds=0)

        assert summary["catalog_failures"] == 1
        assert summary["catalog_aborted"] is False
        # the failing card keeps the price it already had...
        assert dynamo_repo.get_catalog_card(
            "en:swsh1-1").prices["holofoil"].market == Decimal("9.25")
        # ...and the run went on to the next card in the same pass
        assert dynamo_repo.get_catalog_card(
            "en:swsh1-5").prices["holofoil"].market == Decimal("2.00")

    def test_the_run_aborts_after_max_consecutive_failures_and_reports_it(
        self, dynamo_repo,
    ):
        """A week of half-runs must not look like a week of clean ones, so the
        abort is a reported fact and not merely a shorter loop."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card(f"en:swsh1-{170 + i}",
                      synced=CATALOG_EPOCH + timedelta(days=i))
            for i in range(5)
        ])
        client = FakeTcgdexClient(always_raise=RuntimeError("dead endpoint"))

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         cards_per_night=10,
                                         request_delay_seconds=0,
                                         max_consecutive_failures=2)

        assert summary["catalog_aborted"] is True
        assert len(client.calls) == 2

    def test_the_runtime_cap_stops_the_loop_cleanly_and_reports_it(
        self, dynamo_repo, monkeypatch,
    ):
        """A mis-set `cards_per_night` must not be able to outlive the catalog
        lock's 3600s TTL. That failure mode loses catalog ROWS, not prices: an
        expired lock is stealable, and a write landing across a reseed's swap
        carries the superseded generation and is swept."""
        import merlins_collection.services.catalog_sync as catalog_sync_module
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card(f"en:swsh1-{180 + i}",
                      synced=CATALOG_EPOCH + timedelta(days=i))
            for i in range(4)
        ])
        client = FakeTcgdexClient(cards={
            (Language.EN, f"swsh1-{180 + i}"): _detail(f"swsh1-{180 + i}", str(i))
            for i in range(4)
        })
        monkeypatch.setattr(catalog_sync_module, "time", _FakeClock(step=10.0))

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         cards_per_night=10,
                                         request_delay_seconds=0,
                                         max_runtime_seconds=25)

        assert summary["catalog_runtime_exceeded"] is True
        assert summary["catalog_aborted"] is False  # a clean stop, not a failure
        assert 0 < len(client.calls) < 4

    def test_the_catalog_lock_is_released_even_when_the_run_raises(
        self, dynamo_repo, monkeypatch,
    ):
        """An unexpected raise must not leave the lock held for its full
        hour-long TTL, blocking tomorrow's run and any reseed."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [_cat_card(CARD_ID)])
        client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})

        def _boom(*args, **kwargs):
            raise RuntimeError("unexpected repo failure")

        monkeypatch.setattr(dynamo_repo, "iter_catalog_cards", _boom)

        with pytest.raises(RuntimeError):
            refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                   cards_per_night=10, request_delay_seconds=0)

        dynamo_repo.acquire_catalog_lock("post-crash-probe")
        dynamo_repo.release_catalog_lock("post-crash-probe")

    def test_a_lock_held_by_someone_else_skips_the_pass_without_failing(
        self, dynamo_repo,
    ):
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card(CARD_ID, prices={"holofoil": Decimal("9.25")}),
        ])
        dynamo_repo.acquire_catalog_lock("reseed-in-flight")
        try:
            client = FakeTcgdexClient(cards={(Language.EN, "swsh1-1"): RAW})
            summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                             cards_per_night=10,
                                             request_delay_seconds=0)

            assert summary["catalog_skipped"] == "catalog reseed in flight"
            assert summary["catalog_cards_updated"] == 0
            assert client.calls == []  # not one request was attempted
        finally:
            dynamo_repo.release_catalog_lock("reseed-in-flight")

    def test_an_aborted_night_is_picked_up_by_the_next_run_with_no_cursor(
        self, dynamo_repo,
    ):
        """The reason there is no cycle cursor: a cursor is state that can be
        wrong, and it strands whatever an aborted night skipped. With
        stalest-first, last night's untouched cards are simply the stalest
        remaining and tomorrow takes them automatically."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        ids = [f"en:swsh1-{190 + i}" for i in range(4)]
        _seed_cards(dynamo_repo, [
            _cat_card(cid, synced=CATALOG_EPOCH + timedelta(days=i))
            for i, cid in enumerate(ids)
        ])
        cards = {
            (Language.EN, f"swsh1-{190 + i}"): _detail(f"swsh1-{190 + i}", str(i))
            for i in range(4)
        }

        first = FakeTcgdexClient(cards=cards)
        refresh_catalog_prices(dynamo_repo, first, date(2026, 6, 22),
                               cards_per_night=2, request_delay_seconds=0)
        assert [c[1] for c in first.calls] == ["swsh1-190", "swsh1-191"]

        second = FakeTcgdexClient(cards=cards)
        refresh_catalog_prices(dynamo_repo, second, date(2026, 6, 23),
                               cards_per_night=2, request_delay_seconds=0)
        assert [c[1] for c in second.calls] == ["swsh1-192", "swsh1-193"]

    def test_an_explicit_card_id_list_bypasses_selection(self, dynamo_repo):
        """The one-time reprice script selects ONCE for the whole run and feeds
        the pass its chunks, so a card that 404s (and therefore stays stale) is
        not re-fetched by every later chunk of the same run."""
        from merlins_collection.services.catalog_sync import refresh_catalog_prices

        _seed_cards(dynamo_repo, [
            _cat_card("en:swsh1-200", synced=CATALOG_EPOCH),
            _cat_card("en:swsh1-201", synced=CATALOG_EPOCH + timedelta(days=1)),
        ])
        client = FakeTcgdexClient(cards={
            (Language.EN, "swsh1-201"): _detail("swsh1-201", "201"),
        })

        summary = refresh_catalog_prices(dynamo_repo, client, date(2026, 6, 22),
                                         card_ids=["en:swsh1-201"],
                                         request_delay_seconds=0)

        assert [c[1] for c in client.calls] == ["swsh1-201"]
        assert summary["catalog_candidates"] == 1


class TestCatalogPassWiring:
    """How the nightly job carries the new step."""

    def test_run_daily_sync_runs_the_catalog_pass_after_the_denormalization(
        self, dynamo_repo, monkeypatch,
    ):
        """It prices cards we do NOT own, so it feeds no denormalizer and goes
        last — a 24-minute catalog walk must never delay publishing today's
        figures for the stock actually on the table."""
        import merlins_collection.services.catalog_sync as catalog_sync_module
        from merlins_collection.services.catalog_sync import run_daily_sync

        order = []

        def _fake_denorm(repo):
            order.append("denormalize")
            return 0

        def _fake_catalog(repo, client, today, **kwargs):
            order.append("catalog")
            return {"catalog_cards_updated": 0}

        monkeypatch.setattr(catalog_sync_module,
                            "refresh_inventory_market_values", _fake_denorm)
        monkeypatch.setattr(catalog_sync_module,
                            "refresh_catalog_prices", _fake_catalog)

        run_daily_sync(dynamo_repo, FakeTcgdexClient(), date(2026, 6, 22),
                       pricing_provider=None)

        assert order == ["denormalize", "catalog"]

    def test_the_catalog_pass_counts_are_their_own_keys_not_the_held_passs(
        self, dynamo_repo,
    ):
        """Merging them would make a 5,500-card catalog walk indistinguishable
        from a 300-card depth pass in the one report anybody reads."""
        from merlins_collection.services.catalog_sync import run_daily_sync

        held_id = "en:swsh1-1"
        catalog_id = "en:swsh1-210"
        dynamo_repo.put_inventory_item(_raw_item(card_id=held_id))
        _seed_cards(dynamo_repo, [_cat_card(catalog_id)])
        client = FakeTcgdexClient(cards={
            (Language.EN, "swsh1-1"): RAW,
            (Language.EN, "swsh1-210"): _detail("swsh1-210", "210"),
        })

        summary = run_daily_sync(dynamo_repo, client, date(2026, 6, 22))

        assert summary["cards_updated"] == 1          # the held pass
        assert summary["catalog_cards_updated"] == 1  # the catalog pass
        assert summary["catalog_candidates"] == 1

    def test_a_catalog_pass_failure_does_not_abort_the_rest_of_the_job(
        self, dynamo_repo,
    ):
        """Degrade alone, exactly as the graded pricing step does."""
        from merlins_collection.services.catalog_sync import run_daily_sync

        dynamo_repo.put_inventory_item(_raw_item(card_id=CARD_ID))
        _seed_cards(dynamo_repo, [
            _cat_card(f"en:swsh1-{220 + i}",
                      synced=CATALOG_EPOCH + timedelta(days=i))
            for i in range(3)
        ])

        class _HeldOkCatalogDead:
            """TCGdex answers for the held card and dies for everything else."""

            def __init__(self):
                self.calls = []

            def get_card(self, language, tcgdex_id):
                self.calls.append((language, tcgdex_id))
                if tcgdex_id == "swsh1-1":
                    return RAW
                raise RuntimeError("dead endpoint")

        summary = run_daily_sync(dynamo_repo, _HeldOkCatalogDead(),
                                 date(2026, 6, 22))

        assert summary["cards_updated"] == 1        # the depth pass still landed
        assert summary["items_refreshed"] == 1      # and the denormalization ran
        assert summary["catalog_failures"] > 0
