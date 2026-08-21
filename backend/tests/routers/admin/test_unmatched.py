"""T7 — ``GET /admin/unmatched/suggestions``: the endpoint. RED tests.

**Located here, not at the task doc's ``tests/routers/test_admin_unmatched.py``.**
Every admin router test lives in this package because ``admin_client`` is defined
in its ``conftest.py``; a file one level up would have to restate the fixture,
which is the duplication that conftest was created to delete.

The list this feeds is ``GET /admin/inventory/search?no_catalog_match=true``
(T5). This endpoint adds only the ranked candidates and the one number the
dashboard widget quotes (T10) — no second list endpoint.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.catalog import CardImages, CatalogCard
from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    Language,
    RawInventoryItem,
)


# ---- helpers ----

def _raw(*, item_id=None, display_name="Charizard", card_number=None,
         card_id=None, no_catalog_match=False, **extra):
    """A raw item whose number rides in ``display_name``, as the importer writes it.

    There is no ``card_number`` field on the model — see the note in
    ``tests/services/test_pairing.py``.
    """
    name = f"{display_name} #{card_number}" if card_number else display_name
    kw = dict(
        card_id=card_id,
        display_name=name,
        language=Language.EN,
        finish="normal",
        condition=Condition.NM,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("10.00"),
        acquired_at=date(2025, 1, 1),
        no_catalog_match=no_catalog_match,
    )
    if item_id:
        kw["item_id"] = item_id
    kw.update(extra)
    return RawInventoryItem(**kw)


def _card(card_id, name="Charizard", number="4"):
    return CatalogCard(
        card_id=card_id,
        language=Language.EN,
        name=name,
        set_id="base1",
        set_name="Base Set",
        number=number,
        rarity="Rare",
        images=CardImages(small="https://example.com/s.webp", large=""),
        last_synced_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def get(admin_client):
    client, repo, token = admin_client

    def _get(**params):
        return client.get("/admin/unmatched/suggestions", params=params,
                          headers={"Authorization": f"Bearer {token}"})

    return _get


# ---- tests ----

def test_only_parked_items_are_considered(admin_client, get):
    """The endpoint answers for the queue, not for every unlinked row in inventory."""
    _, repo, _ = admin_client
    repo.put_inventory_item(_raw(item_id="parked", no_catalog_match=True))
    repo.put_inventory_item(_raw(item_id="merely_unlinked"))

    body = get().json()

    assert [i["item_id"] for i in body["items"]] == ["parked"]


def test_items_with_candidates_counts_rows_not_candidates(admin_client, get):
    """The dashboard quotes this number. It must mean "cards you can act on",
    not "suggestions in total"."""
    _, repo, _ = admin_client
    repo.batch_upsert_catalog_cards([
        _card("en:base1-4", number="4"),
        _card("en:base2-4", number="88"),
    ])
    repo.put_inventory_item(_raw(item_id="x", display_name="Charizard",
                                 card_number="4", no_catalog_match=True))

    body = get().json()

    assert len(body["items"][0]["candidates"]) == 2
    assert body["items_with_candidates"] == 1


def test_an_item_with_no_candidates_is_still_listed_but_not_counted(admin_client, get):
    """A parked card with nothing to suggest is the queue's most common row —
    dropping it would hide work from the page that exists to show it."""
    _, repo, _ = admin_client
    repo.put_inventory_item(_raw(item_id="x", display_name="Nothing At All",
                                 no_catalog_match=True))

    body = get().json()

    assert [i["item_id"] for i in body["items"]] == ["x"]
    assert body["items"][0]["candidates"] == []
    assert body["items_with_candidates"] == 0


def test_limit_bounds_the_candidates_per_item(admin_client, get):
    _, repo, _ = admin_client
    repo.batch_upsert_catalog_cards(
        [_card(f"en:base{n}-4", number="4") for n in range(6)]
    )
    repo.put_inventory_item(_raw(item_id="x", display_name="Charizard",
                                 card_number="4", no_catalog_match=True))

    body = get(limit=2).json()

    assert len(body["items"][0]["candidates"]) == 2


@pytest.mark.parametrize("limit", [0, 11])
def test_an_out_of_range_limit_is_a_422(get, limit):
    """An unbounded limit turns one request into a full cross-product."""
    assert get(limit=limit).status_code == 422


def test_every_candidate_carries_an_image_field_and_a_price_field(admin_client, get):
    """Owner rule, absolute: a card picker shows name, image AND price. The fields
    must be present even when empty, or T8 cannot render the placeholder."""
    _, repo, _ = admin_client
    repo.batch_upsert_catalog_cards([_card("en:base1-4")])
    repo.put_inventory_item(_raw(item_id="x", display_name="Charizard",
                                 card_number="4", no_catalog_match=True))

    candidate = get().json()["items"][0]["candidates"][0]

    assert "image_small" in candidate
    assert "market_price" in candidate
    assert candidate["name"] == "Charizard"
    assert candidate["set_name"] == "Base Set"
    assert candidate["number"] == "4"
    assert candidate["why"] == "name and number match"


def test_the_oldest_parked_card_comes_first(admin_client, get):
    """Same order as the queue page sorts by, so the two never disagree about
    which card has been waiting longest."""
    _, repo, _ = admin_client
    repo.put_inventory_item(_raw(
        item_id="newer", no_catalog_match=True,
        no_catalog_match_at=datetime(2026, 8, 1, tzinfo=timezone.utc)))
    repo.put_inventory_item(_raw(
        item_id="older", no_catalog_match=True,
        no_catalog_match_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))

    assert [i["item_id"] for i in get().json()["items"]] == ["older", "newer"]


def test_the_pricing_provider_is_never_called(admin_client, get, monkeypatch):
    """A suggestion is a catalog lookup. The graded price provider is metered at
    fifty lookups a day; a page load must not spend them."""
    from merlins_collection.services import catalog_sync

    def _boom(*a, **k):
        raise AssertionError("the pricing provider must not be called here")

    monkeypatch.setattr(catalog_sync, "build_pricing_provider", _boom, raising=False)

    _, repo, _ = admin_client
    repo.batch_upsert_catalog_cards([_card("en:base1-4")])
    repo.put_inventory_item(_raw(item_id="x", display_name="Charizard",
                                 card_number="4", no_catalog_match=True))

    assert get().status_code == 200
