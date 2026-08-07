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

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def admin_client(cognito_config, jwks, dynamo_repo, mint_token):
    from merlins_collection.dependencies import get_repo, get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_repo] = lambda: dynamo_repo

    admin_token = mint_token(claims={"cognito:groups": ["admin"]})
    client = TestClient(app)
    yield client, admin_token
    app.dependency_overrides.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListCatalogSets:
    def test_returns_sets_we_own_nothing_from(self, admin_client, dynamo_repo):
        """THE owner's ask: a set with zero owned cards is listed, with a 0 count.

        Two sets in the registry, stock in only one of them. The empty one is the
        whole reason this endpoint is not built on ``/inventory/facets``.
        """
        client, token = admin_client
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
        client, token = admin_client
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
        client, token = admin_client
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
        client, token = admin_client
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
        client, token = admin_client
        _register(dynamo_repo, _set_row("en:base1", "Base Set", "EN", 102))
        dynamo_repo.put_inventory_item(_sealed("item-sealed"))

        resp = client.get("/admin/catalog/sets", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()[0]["owned_count"] == 0

    def test_empty_registry_returns_an_empty_list(self, admin_client):
        """A table whose sync has never run answers honestly, not with a 500."""
        client, token = admin_client
        assert client.get("/admin/catalog/sets", headers=_auth(token)).json() == []

    def test_rejects_a_non_admin_caller(self, admin_client, mint_token):
        client, _ = admin_client
        member_token = mint_token(claims={"cognito:groups": ["members"]})

        resp = client.get("/admin/catalog/sets", headers=_auth(member_token))

        assert resp.status_code == 403
