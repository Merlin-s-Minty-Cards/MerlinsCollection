"""T8 — ``GET /admin/catalog/sets``: every set in the catalog, with owned counts.

RED tests for the admin set combobox's data source
(docs/plans/rfc-0008/t8-admin-set-combobox.md).

The owner's ask decides the whole design, so it is stated once here: the list is
**the whole catalog, not inventory facets** — *"so we can double check if there is
a set in the catalog we have no cards of."* A set we own zero cards from must
appear, which rules out deriving the list from inventory at all.

What these tests pin:

* the endpoint reads a ``catalog_set`` REGISTRY (one row per set, written by the
  sync), never a full catalog scan. ``_table.scan`` is booby-trapped in
  ``test_does_not_scan_the_catalog`` because "list every set" via the card rows
  is exactly the 11.2-second full-table read T9 diagnosed as the cause of the
  dead catalog search. Regressing into it would be invisible in a 3-row test
  table and fatal against 31,603 live rows.
* ``owned_count`` is resolved through point-reads of the items' own catalog
  cards, so a set with zero owned cards still reports ``0`` rather than being
  absent.
* ``language`` is carried per set. EN and JA sets share names ("Base Set" exists
  in both), and ``set_id`` is the language-composite (``en:base1`` / ``ja:base1``),
  so a collision must yield two distinct entries rather than one.
* admin gating, which is inherited from ``admin_router`` and therefore exactly
  the kind of thing that silently disappears if the router is mounted wrong.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest


from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
    SealedProductType,
)


# ---- helpers ----

def _card(card_id, *, set_id, set_name, name="Pikachu", language=Language.EN):
    return CatalogCard(
        card_id=card_id,
        language=language,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number="1",
        detail="brief",
        last_synced_at=datetime.now(tz=timezone.utc),
    )


def _raw(item_id, card_id, *, language=Language.EN):
    return RawInventoryItem(
        item_id=item_id,
        card_id=card_id,
        language=language,
        finish="normal",
        condition=Condition.NM,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("10.00"),
        acquired_at=date(2025, 1, 1),
    )


def _sealed(item_id):
    """A kind with NO ``card_id`` attribute at all.

    Present on purpose: a naive ``item.card_id`` walk raises ``AttributeError``
    on sealed and bulk items and turns the whole endpoint into a 500. Same trap
    the triage filters had to dodge.
    """
    return SealedInventoryItem(
        item_id=item_id,
        product_name="Obsidian Flames ETB",
        product_type=SealedProductType.ETB,
        location="glass",
        status=ItemStatus.AVAILABLE,
        cost_basis=Decimal("40.00"),
        acquired_at=date(2025, 1, 1),
    )


def _register(repo, *rows):
    """Write registry rows in the shape the catalog sync produces."""
    repo.put_catalog_sets(list(rows))


def _set_row(set_id, set_name, language, card_count):
    return {
        "set_id": set_id,
        "set_name": set_name,
        "language": language,
        "card_count": card_count,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListCatalogSets:
    def test_returns_sets_we_own_nothing_from(self, admin_client, dynamo_repo):
        """THE owner's ask: a set with zero owned cards is listed, with a 0 count.

        Two sets in the registry, stock in only one of them. The empty one is the
        whole reason this endpoint is not built on ``/inventory/facets``.
        """
        client, _repo, token = admin_client
        _register(
            dynamo_repo,
            _set_row("en:base1", "Base Set", "EN", 102),
            _set_row("en:sv1", "Scarlet & Violet", "EN", 258),
        )
        dynamo_repo.batch_upsert_catalog_cards([
            _card("en:base1-4", set_id="en:base1", set_name="Base Set", name="Charizard"),
        ])
        dynamo_repo.put_inventory_item(_raw("item-1", "en:base1-4"))
        dynamo_repo.put_inventory_item(_raw("item-2", "en:base1-4"))

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        assert resp.status_code == 200
        by_id = {s["set_id"]: s for s in resp.json()}
        assert set(by_id) == {"en:base1", "en:sv1"}
        assert by_id["en:base1"]["owned_count"] == 2
        assert by_id["en:sv1"]["owned_count"] == 0
        assert by_id["en:sv1"]["set_name"] == "Scarlet & Violet"
        assert by_id["en:sv1"]["card_count"] == 258

    def test_sorted_alphabetically_by_name(self, admin_client, dynamo_repo):
        client, _repo, token = admin_client
        _register(
            dynamo_repo,
            _set_row("en:sv1", "Scarlet & Violet", "EN", 258),
            _set_row("en:base1", "Base Set", "EN", 102),
            _set_row("en:base2", "Jungle", "EN", 64),
        )

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        assert [s["set_name"] for s in resp.json()] == [
            "Base Set", "Jungle", "Scarlet & Violet",
        ]

    def test_does_not_scan_the_catalog(self, admin_client, dynamo_repo, monkeypatch):
        """The T9 regression guard, and the reason the registry exists at all.

        "List every set" has no index today: sets live only as denormalized
        fields on 31,603 card rows, so the obvious implementation is a full-table
        scan — the same 11.2-second read that killed catalog search. Any scan on
        this request path raises here.
        """
        client, _repo, token = admin_client
        _register(dynamo_repo, _set_row("en:base1", "Base Set", "EN", 102))
        dynamo_repo.put_inventory_item(_raw("item-1", "en:base1-4"))

        def _forbidden(*args, **kwargs):
            raise AssertionError(
                "GET /admin/catalog/sets scanned the table. Sets must come from "
                "the catalog_set registry (one query), never from walking the "
                "catalog card rows."
            )

        monkeypatch.setattr(dynamo_repo._table, "scan", _forbidden)
        monkeypatch.setattr(dynamo_repo, "iter_catalog_cards", _forbidden)
        monkeypatch.setattr(dynamo_repo, "list_all_catalog_cards", _forbidden)

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        assert resp.status_code == 200

    def test_en_and_ja_sets_with_the_same_name_stay_distinct(
        self, admin_client, dynamo_repo
    ):
        """Names are not unique across languages; ``set_id`` is. Both are listed,
        each carrying its own ``language`` so the admin can tell them apart."""
        client, _repo, token = admin_client
        _register(
            dynamo_repo,
            _set_row("en:base1", "Base Set", "EN", 102),
            _set_row("ja:base1", "Base Set", "JP", 102),
        )
        dynamo_repo.batch_upsert_catalog_cards([
            _card("ja:base1-4", set_id="ja:base1", set_name="Base Set",
                  name="リザードン", language=Language.JP),
        ])
        dynamo_repo.put_inventory_item(
            _raw("item-jp", "ja:base1-4", language=Language.JP)
        )

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        entries = [s for s in resp.json() if s["set_name"] == "Base Set"]
        assert len(entries) == 2
        assert {e["language"] for e in entries} == {"EN", "JP"}
        by_id = {e["set_id"]: e for e in entries}
        assert by_id["ja:base1"]["owned_count"] == 1
        assert by_id["en:base1"]["owned_count"] == 0

    def test_sealed_items_do_not_break_the_owned_count(self, admin_client, dynamo_repo):
        """Sealed and bulk items have no ``card_id`` FIELD, not a null one."""
        client, _repo, token = admin_client
        _register(dynamo_repo, _set_row("en:base1", "Base Set", "EN", 102))
        dynamo_repo.put_inventory_item(_sealed("item-sealed"))

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()[0]["owned_count"] == 0

    def test_empty_registry_returns_an_empty_list(self, admin_client):
        """A table whose sync has never run answers honestly, not with a 500."""
        client, _repo, token = admin_client
        assert client.get("/admin/catalog/sets", headers=_auth(token)).json() == []

    def test_rejects_a_non_admin_caller(self, admin_client, mint_token):
        client, _repo, _ = admin_client
        member_token = mint_token(claims={"cognito:groups": ["members"]})

        resp = client.get("/admin/catalog/sets", headers=_auth(member_token))

        assert resp.status_code == 403


# ===========================================================================
# RFC 0011 T9 — GET /admin/catalog/new-cards
# ===========================================================================
#
# The dashboard widget's data source (T10). The owner's ask: *"if there could be
# some kind of widget on the dashboard to show any new cards from TCGdex, that
# would be great, and then we can look at the new tab to see which card can now
# be paired."*


def _new_cards_row(repo, card_id, *, name="Celebi V", set_id="en:swsh1",
                   first_seen_at=None, prices=None, image="https://img/1.png"):
    """A catalog row written straight to the table.

    Direct, because the point of most of these tests is a row whose
    ``first_seen_at`` is a SPECIFIC value — including absent, which is what all
    31,603 rows seeded before RFC 0011 look like and which no writer can produce
    once the writer stamps.
    """
    item = {
        "PK": f"CARD#{card_id}", "SK": "META",
        "GSI1PK": f"SET#{set_id}", "GSI1SK": f"CARD#{card_id}",
        "entity": "catalog_card",
        "card_id": card_id, "language": "EN", "name": name,
        "set_id": set_id, "set_name": "Sword & Shield", "number": "1",
        "rarity": "Rare",
        "images": {"small": image, "large": ""},
        "prices": prices or {},
        "detail": "brief",
        "last_synced_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if first_seen_at is not None:
        item["first_seen_at"] = first_seen_at.isoformat()
    repo._table.put_item(Item=item)


def _days_ago(days):
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


def _get_new_cards(admin_client, **params):
    client, _repo, token = admin_client
    return client.get("/admin/catalog/new-cards", params=params,
                      headers={"Authorization": f"Bearer {token}"})


def test_new_cards_counts_only_stamped_rows(admin_client):
    """A null ``first_seen_at`` means "predates the field", not "new". Counting
    nulls would report all 31,603 rows as new on the very first load — the
    same honesty ``detail: brief|full`` already keeps."""
    _, repo, _ = admin_client
    _new_cards_row(repo, "en:old-1")                                # unstamped
    _new_cards_row(repo, "en:new-1", first_seen_at=_days_ago(1))

    body = _get_new_cards(admin_client).json()

    assert body["count"] == 1
    assert [c["card_id"] for c in body["cards"]] == ["en:new-1"]


def test_new_cards_respects_the_window(admin_client):
    _, repo, _ = admin_client
    _new_cards_row(repo, "en:ancient-1", first_seen_at=_days_ago(200))
    _new_cards_row(repo, "en:new-1", first_seen_at=_days_ago(1))

    body = _get_new_cards(admin_client, since_days=30).json()

    assert [c["card_id"] for c in body["cards"]] == ["en:new-1"]
    assert body["count"] == 1


def test_new_cards_returns_newest_first(admin_client):
    _, repo, _ = admin_client
    _new_cards_row(repo, "en:older-1", first_seen_at=_days_ago(10))
    _new_cards_row(repo, "en:newer-1", first_seen_at=_days_ago(1))

    body = _get_new_cards(admin_client).json()

    assert [c["card_id"] for c in body["cards"]] == ["en:newer-1", "en:older-1"]


def test_the_count_is_the_whole_window_even_when_the_sample_is_capped(admin_client):
    """``limit`` bounds what is RENDERED; ``count`` is the answer to "how many
    new cards are there". Capping the count too would under-report the work."""
    _, repo, _ = admin_client
    for n in range(5):
        _new_cards_row(repo, f"en:new-{n}", first_seen_at=_days_ago(1))

    body = _get_new_cards(admin_client, limit=2).json()

    assert body["count"] == 5
    assert len(body["cards"]) == 2


def test_each_returned_card_carries_an_image_and_a_price_field(admin_client):
    """Owner rule, absolute: a card is never identified by name alone. The
    fields must be present even when empty, or the widget cannot render its
    placeholder."""
    _, repo, _ = admin_client
    _new_cards_row(repo, "en:new-1", first_seen_at=_days_ago(1))

    card = _get_new_cards(admin_client).json()["cards"][0]

    assert "images" in card
    assert "market_price" in card
    assert card["name"] == "Celebi V"
    assert card["set_name"] == "Sword & Shield"


def test_an_absent_price_is_none_never_zero(admin_client):
    """``FinishPrice`` bands are written only when a provider published a
    figure, so absent means absent."""
    _, repo, _ = admin_client
    _new_cards_row(repo, "en:new-1", first_seen_at=_days_ago(1), prices={})

    assert _get_new_cards(admin_client).json()["cards"][0]["market_price"] is None


def test_the_window_start_is_returned_so_the_ui_need_not_recompute_it(admin_client):
    """And it is the UTC date, because that is the boundary actually applied.

    first_seen_at is stored in UTC and the cutoff is computed in UTC, so a
    since derived from the SERVER's local date would name a day the filter
    did not use — off by one for the eight hours a day Pacific and UTC disagree.
    Returning it at all exists to stop the UI recomputing it wrong; returning a
    locally-derived one would just move the bug to the server.
    """
    body = _get_new_cards(admin_client, since_days=30).json()

    expected = (datetime.now(tz=timezone.utc) - timedelta(days=30)).date()
    assert body["since"] == expected.isoformat()


@pytest.mark.parametrize(
    "params",
    [{"since_days": 0}, {"since_days": 366}, {"limit": 0}, {"limit": 26}],
)
def test_out_of_range_bounds_are_a_422(admin_client, params):
    assert _get_new_cards(admin_client, **params).status_code == 422


def test_an_empty_catalog_is_an_honest_zero(admin_client):
    body = _get_new_cards(admin_client).json()

    assert body["count"] == 0
    assert body["cards"] == []
