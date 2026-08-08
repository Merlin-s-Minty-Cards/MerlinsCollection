"""Tests for ``/admin/slabs`` — RFC 0009 T1, the duplicate-cert check.

The question this endpoint answers is "do I already own this slab?", asked once
per barcode scan during intake. It is a **warning**, not a gate: two items can
legitimately share a cert over time (you sell a slab and buy it back later), so
"owned" never blocks — it tells the admin what they are about to re-buy.

"Not owned" is the NORMAL answer and returns ``200``, not ``404``. A 404 would
make every ordinary scan look like an error to the frontend.
"""

from datetime import date
from decimal import Decimal

from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    ItemStatus,
    RawInventoryItem,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _graded(cert_number="12345678", **over):
    kw = dict(
        card_id="swsh1-1", cost_basis=Decimal("300"), acquired_at=date(2026, 1, 1),
        company=GradingCompany.PSA, grade=Decimal("10"), cert_number=cert_number,
    )
    kw.update(over)
    return GradedInventoryItem(**kw)


class TestCertLookup:
    def test_unknown_cert_is_a_200_saying_not_owned(self, admin_client):
        client, _repo, token = admin_client
        resp = client.get("/admin/slabs/certs/99999999", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == {"owned": False}

    def test_known_cert_returns_the_owning_item(self, admin_client):
        client, repo, token = admin_client
        item = _graded(display_name_override="Charizard #4")
        repo.put_inventory_item(item)

        resp = client.get("/admin/slabs/certs/12345678", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["owned"] is True
        assert body["item_id"] == item.item_id
        assert body["status"] == ItemStatus.AVAILABLE.value
        assert body["name"] == "Charizard #4"

    def test_company_defaults_to_psa_and_scopes_the_lookup(self, admin_client):
        """The same digits at two graders are two different slabs."""
        client, repo, token = admin_client
        cgc = _graded(cert_number="44444444", company=GradingCompany.CGC)
        repo.put_inventory_item(cgc)

        default = client.get("/admin/slabs/certs/44444444", headers=_auth(token))
        assert default.json() == {"owned": False}  # defaulted to PSA

        scoped = client.get("/admin/slabs/certs/44444444?company=CGC",
                            headers=_auth(token))
        assert scoped.json()["item_id"] == cgc.item_id

    def test_sold_slab_is_still_reported_as_owned_with_its_status(self, admin_client):
        """A sold slab you are buying back is exactly the case the warning is for
        — the answer is "yes, and it is SOLD", not silence."""
        client, repo, token = admin_client
        item = _graded(cert_number="55555555", status=ItemStatus.SOLD)
        repo.put_inventory_item(item)

        body = client.get("/admin/slabs/certs/55555555", headers=_auth(token)).json()
        assert body["owned"] is True
        assert body["status"] == ItemStatus.SOLD.value

    def test_falls_back_to_the_catalog_name(self, admin_client):
        """Slabs rarely carry a ``display_name``, and a duplicate warning that
        names no card is not a warning."""
        from datetime import datetime

        from merlins_collection.models.catalog import CatalogCard

        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([CatalogCard(
            card_id="swsh1-1", name="Celebi V", set_id="swsh1", set_name="S&S",
            number="1", images={"small": "s", "large": "l"}, prices={},
            last_synced_at=datetime(2026, 6, 22, 12, 0, 0),
        )])
        repo.put_inventory_item(_graded(cert_number="66666666"))

        body = client.get("/admin/slabs/certs/66666666", headers=_auth(token)).json()
        assert body["name"] == "Celebi V"

    def test_edited_cert_no_longer_reports_the_old_cert_as_owned(self, admin_client):
        """End-to-end on the stale-pointer path: a false "duplicate" on a cert
        the owner legitimately re-enters is worse than no warning at all."""
        client, repo, token = admin_client
        item = _graded(cert_number="11111111")
        repo.put_inventory_item(item)
        repo.put_inventory_item(item.model_copy(update={"cert_number": "22222222"}))

        assert client.get("/admin/slabs/certs/11111111",
                          headers=_auth(token)).json() == {"owned": False}
        assert client.get("/admin/slabs/certs/22222222",
                          headers=_auth(token)).json()["item_id"] == item.item_id

    def test_response_never_leaks_cost_basis(self, admin_client):
        """It is a duplicate check, not an item dump. ``cost_basis`` is internal
        purchase data and there is no reason for it to ride along."""
        client, repo, token = admin_client
        repo.put_inventory_item(_graded(cert_number="77777777"))
        body = client.get("/admin/slabs/certs/77777777", headers=_auth(token)).json()
        assert "cost_basis" not in body

    def test_oversized_cert_is_rejected_not_a_500(self, admin_client):
        """The cert becomes part of a DynamoDB partition key, which is capped at
        2048 bytes — unbounded, a long scan-bar paste is a ValidationException
        surfacing as a 500."""
        client, _repo, token = admin_client
        resp = client.get(f"/admin/slabs/certs/{'9' * 5000}", headers=_auth(token))
        assert resp.status_code == 422

    def test_requires_admin_auth(self, admin_client):
        client, _repo, _token = admin_client
        resp = client.get("/admin/slabs/certs/12345678")
        assert resp.status_code in (401, 403)


class TestCertLookupIgnoresNonGradedItems:
    def test_raw_inventory_never_answers_a_cert_lookup(self, admin_client):
        client, repo, token = admin_client
        repo.put_inventory_item(RawInventoryItem(
            card_id="swsh1-1", finish="holofoil", condition=Condition.NM,
            cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        ))
        resp = client.get("/admin/slabs/certs/12345678", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == {"owned": False}
