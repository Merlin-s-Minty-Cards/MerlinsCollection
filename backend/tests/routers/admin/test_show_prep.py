"""Tests for admin show-prep router."""

from datetime import date
from decimal import Decimal


from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    Language,
    RawInventoryItem,
)


def _raw(item_id="item-1", *, card_id="sv1-1", location="glass",
         cost_basis="20.00", current_market_value="50.00",
         status=ItemStatus.AVAILABLE, **extra):
    return RawInventoryItem(
        item_id=item_id, card_id=card_id, finish="holofoil",
        condition=Condition.NM, location=location, status=status,
        cost_basis=Decimal(cost_basis),
        current_market_value=Decimal(current_market_value),
        acquired_at=date(2025, 1, 1),
        **extra,
    )


# ``admin_client`` now comes from ``conftest.py`` in this package; the identical
# copy that used to sit here was one of sixteen.


def _auth(token): return {"Authorization": f"Bearer {token}"}


class TestMispriced:
    def test_finds_mispriced_cards(self, admin_client):
        client, repo, token = admin_client
        # 150% margin -> flagged at threshold=10
        repo.put_inventory_item(_raw(item_id="high", cost_basis="20.00",
                                     current_market_value="50.00"))
        # 5% margin -> not flagged at threshold=10
        repo.put_inventory_item(_raw(item_id="low", card_id="sv1-2",
                                     cost_basis="20.00",
                                     current_market_value="21.00"))

        resp = client.get("/admin/show-prep/mispriced?threshold=10",
                          headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_flagged"] == 1
        assert data["items"][0]["item_id"] == "high"

    def test_filter_by_location(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="g1", location="glass"))
        repo.put_inventory_item(_raw(item_id="b1", card_id="sv1-2",
                                     location="binder"))

        resp = client.get("/admin/show-prep/mispriced?threshold=10&location=glass",
                          headers=_auth(token))
        assert resp.status_code == 200
        assert all(i["location"] == "glass" for i in resp.json()["items"])

    def test_mispriced_includes_tcg_url_and_sticker_notes(self, admin_client):
        """GET /show-prep/mispriced must round-trip the stored tcg_url and sticker_notes."""
        client, repo, admin_token = admin_client
        repo.put_inventory_item(_raw(
            item_id="item-1", cost_basis="10.00", current_market_value="50.00",
        ))
        # Persist tcg_url/sticker_notes exactly the way the admin PUT endpoint would.
        repo.put_inventory_item(_raw(
            item_id="item-1", cost_basis="10.00", current_market_value="50.00",
            tcg_url="https://www.tcgplayer.com/product/12345",
            sticker_notes="verify grade before pricing",
        ))

        resp = client.get("/admin/show-prep/mispriced", headers=_auth(admin_token))
        assert resp.status_code == 200
        flagged = resp.json()["items"]
        assert len(flagged) == 1
        assert flagged[0]["tcg_url"] == "https://www.tcgplayer.com/product/12345"
        assert flagged[0]["sticker_notes"] == "verify grade before pricing"

    def test_mispriced_includes_language(self, admin_client):
        """RFC 0023 T7: the frontend needs each item's language to pick the
        right TCGplayer category link (or say none exists) — this endpoint
        never returned it before, so every mispriced row silently defaulted
        to an English-category search link regardless of the card's actual
        language.
        """
        client, repo, admin_token = admin_client
        repo.put_inventory_item(_raw(
            item_id="jp-item", cost_basis="10.00", current_market_value="50.00",
            language=Language.JP,
        ))

        resp = client.get("/admin/show-prep/mispriced", headers=_auth(admin_token))
        assert resp.status_code == 200
        flagged = resp.json()["items"]
        assert len(flagged) == 1
        assert flagged[0]["language"] == "JP"

    def test_mispriced_includes_language_in_dollar_threshold_mode(self, admin_client):
        """The endpoint hand-builds two near-identical dicts (percent/dollar
        threshold modes) — both must carry `language`, not just one."""
        client, repo, admin_token = admin_client
        repo.put_inventory_item(_raw(
            item_id="jp-item", cost_basis="10.00", current_market_value="50.00",
            language=Language.JP,
        ))

        resp = client.get(
            "/admin/show-prep/mispriced?threshold=5&threshold_mode=dollar",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        flagged = resp.json()["items"]
        assert len(flagged) == 1
        assert flagged[0]["language"] == "JP"


class TestBulkMove:
    def test_move_items(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="a", location="toploader"))
        repo.put_inventory_item(_raw(item_id="b", card_id="sv1-2",
                                     location="toploader"))

        resp = client.post("/admin/show-prep/bulk-move", json={
            "item_ids": ["a", "b"],
            "new_location": "glass",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["moved"] == 2

        assert repo.get_inventory_item("a").location == "glass"
        assert repo.get_inventory_item("b").location == "glass"

    def test_move_nonexistent_reports_error(self, admin_client):
        client, repo, token = admin_client
        resp = client.post("/admin/show-prep/bulk-move", json={
            "item_ids": ["fake-id"],
            "new_location": "glass",
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["moved"] == 0
        assert len(resp.json()["errors"]) == 1


class TestLocationSummary:
    def test_counts_by_location(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(_raw(item_id="g1", location="glass"))
        repo.put_inventory_item(_raw(item_id="g2", card_id="sv1-2",
                                     location="glass"))
        repo.put_inventory_item(_raw(item_id="t1", card_id="sv1-3",
                                     location="toploader"))

        resp = client.get("/admin/show-prep/location-summary",
                          headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["locations"]["glass"] == 2
        assert data["locations"]["toploader"] == 1
        assert data["total"] == 3
