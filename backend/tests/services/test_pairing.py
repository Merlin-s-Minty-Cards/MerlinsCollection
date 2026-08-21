"""T7 — ranked pairing suggestions: the scoring service. RED tests.

`spreadsheet_import._match_card` already normalizes names and numbers on both
sides and indexes by ``(name, number, language)``. It answers *"is there exactly
one safe answer?"* and returns ``None`` for everything ambiguous — correct for an
importer writing ``card_id`` unattended, wrong for a human picking from a list.

This module's subject is the sibling that returns **the candidates with a
score**, over the same normalizers. It never forks them.

**Two things the task doc's illustrative snippets get wrong about the model, and
these tests correct rather than copy:**

* There is **no ``card_number`` field on an inventory item.** A raw item's
  number lives inside ``display_name``, materialized at import as
  ``"Dragonair #181"`` (``card_text.format_display_name``). So ``_raw`` here
  takes ``card_number`` as a *test* convenience and folds it into the display
  name exactly the way the importer does — which also pins that the service has
  to split the number back out before normalizing the name, or
  ``normalize_name("Charizard #4")`` is ``"charizard 4"`` and misses every time.
* A parked item must have ``card_id=None``; the model validator refuses
  ``no_catalog_match`` on a still-linked row (RFC 0011 T5).
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import CardImages, CatalogCard, FinishPrice
from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    Language,
    RawInventoryItem,
)
from merlins_collection.services.pairing import build_pairing_index, candidates_for


# ---- helpers ----

def _raw(*, item_id=None, display_name="Charizard", card_number=None,
         card_id=None, language=Language.EN, condition=Condition.NM, **extra):
    """A raw item whose number rides in ``display_name``, as the importer writes it."""
    name = f"{display_name} #{card_number}" if card_number else display_name
    kw = dict(
        card_id=card_id,
        display_name=name,
        language=language,
        finish="normal",
        condition=condition,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("10.00"),
        acquired_at=date(2025, 1, 1),
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return RawInventoryItem(**kw)


class _Catalog:
    """Collects catalog cards and builds the pairing index over them."""

    def __init__(self):
        self.cards = []

    def add(self, *, card_id, name, number, set_id="base1", set_name="Base Set",
            rarity="Rare", language=Language.EN, prices=None, image="s.webp",
            detail="brief"):
        self.cards.append(CatalogCard(
            card_id=card_id,
            language=language,
            name=name,
            set_id=set_id,
            set_name=set_name,
            number=number,
            rarity=rarity,
            images=CardImages(small=image, large=""),
            prices={
                k: (v if isinstance(v, FinishPrice) else FinishPrice(**v))
                for k, v in (prices or {}).items()
            },
            last_synced_at=datetime.now(tz=timezone.utc),
            detail=detail,
        ))
        return self

    @property
    def index(self):
        return build_pairing_index(self.cards)


@pytest.fixture
def catalog():
    return _Catalog()


# ---- tests ----

class TestScoring:
    def test_exact_name_and_number_scores_highest(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    set_name="Base Set")
        item = _raw(display_name="Charizard", card_number="4")

        [best] = candidates_for(item, catalog.index)

        assert best.card_id == "en:base1-4"
        assert best.score == 1.0
        assert best.why == "name and number match"

    def test_name_match_with_a_different_number_ranks_lower(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        item = _raw(display_name="Charizard", card_number="99")

        [only] = candidates_for(item, catalog.index)

        assert only.score == 0.7
        assert only.why == "name matches, number differs"

    def test_a_close_name_with_a_matching_number_is_the_lowest_tier(self, catalog):
        """A variant word dropped to reach the catalog is the weakest evidence we
        will still show — it is exactly the promo/alt-art class the importer
        refuses to auto-link."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        item = _raw(display_name="Charizard Holo", card_number="4")

        [only] = candidates_for(item, catalog.index)

        assert only.score == 0.5
        assert only.why == "close name, number matches"

    def test_a_weak_match_is_not_offered_at_all(self, catalog):
        """A long list of bad guesses invites the exact promo-mispairing this
        feature exists to stop."""
        catalog.add(card_id="en:base1-58", name="Pikachu", number="58")
        item = _raw(display_name="Blastoise", card_number="2")

        assert candidates_for(item, catalog.index) == []

    def test_ranked_best_first(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        catalog.add(card_id="en:base2-4", name="Charizard", number="88")
        item = _raw(display_name="Charizard", card_number="4")

        result = candidates_for(item, catalog.index)

        assert [c.score for c in result] == [1.0, 0.7]
        assert [c.card_id for c in result] == ["en:base1-4", "en:base2-4"]

    def test_one_catalog_card_is_offered_once(self, catalog):
        """A card reachable by two tiers is ONE candidate at its best score —
        the same card twice in a picker reads as two different printings."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        item = _raw(display_name="Charizard", card_number="4")

        assert [c.card_id for c in candidates_for(item, catalog.index)] == ["en:base1-4"]

    def test_limit_bounds_the_list(self, catalog):
        for n in range(6):
            catalog.add(card_id=f"en:base{n}-4", name="Charizard", number="4")
        item = _raw(display_name="Charizard", card_number="4")

        assert len(candidates_for(item, catalog.index, limit=2)) == 2


class TestLanguage:
    def test_a_jp_item_never_matches_an_english_printing(self, catalog):
        """A JP card trades at a different price. Language is part of the KEY."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    language=Language.EN)
        item = _raw(display_name="Charizard", card_number="4", language=Language.JP)

        assert [c.card_id for c in candidates_for(item, catalog.index)] == []

    def test_zero_candidates_is_an_honest_answer(self, catalog):
        assert candidates_for(_raw(display_name="Nothing"), catalog.index) == []


class TestIdentity:
    def test_a_display_name_override_wins_over_the_stored_name(self, catalog):
        """One rule everywhere (CLAUDE.md): the admin's typed English name is the
        single best signal on a JP card whose stored name the matcher cannot
        normalize."""
        catalog.add(card_id="ja:base1-4", name="Charizard", number="4",
                    language=Language.JP)
        item = _raw(display_name="リザードン #4", display_name_override="Charizard #4",
                    language=Language.JP)

        assert [c.card_id for c in candidates_for(item, catalog.index)] == ["ja:base1-4"]


class TestPrices:
    def test_an_absent_price_is_none_not_zero(self, catalog):
        """FinishPrice bands are written only when a provider published a figure."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4", prices={})
        item = _raw(display_name="Charizard", card_number="4")

        assert candidates_for(item, catalog.index)[0].market_price is None

    def test_the_price_is_not_condition_adjusted(self, catalog):
        """A catalog price is a NEAR MINT market figure. There is no item condition
        in a catalog row, so scaling it would be inventing a number."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    prices={"normal": {"market": Decimal("100")}})
        item = _raw(display_name="Charizard", card_number="4",
                    condition=Condition.DMG)

        assert candidates_for(item, catalog.index)[0].market_price == Decimal("100")

    def test_brief_and_full_stay_distinguishable(self, catalog):
        """"We never fetched a price" and "no provider covers this card" are
        different facts. Collapsing them throws away the only signal that says
        whether waiting will help (CLAUDE.md)."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    prices={}, detail="full")
        item = _raw(display_name="Charizard", card_number="4")

        [only] = candidates_for(item, catalog.index)

        assert only.market_price is None
        assert only.detail == "full"
        assert only.last_synced_at is not None

    def test_an_absent_image_is_an_empty_string_not_a_missing_field(self, catalog):
        """T8 renders a placeholder off this. The field must always be present."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4", image="")
        item = _raw(display_name="Charizard", card_number="4")

        assert candidates_for(item, catalog.index)[0].image_small == ""
