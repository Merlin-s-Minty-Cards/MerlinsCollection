"""Tests for ``/admin/slabs`` — RFC 0009 T1's duplicate-cert check and T6's list.

The question T1's endpoint answers is "do I already own this slab?", asked once
per barcode scan during intake. It is a **warning**, not a gate: two items can
legitimately share a cert over time (you sell a slab and buy it back later), so
"owned" never blocks — it tells the admin what they are about to re-buy.

"Not owned" is the NORMAL answer and returns ``200``, not ``404``. A 404 would
make every ordinary scan look like an error to the frontend.

T6 adds ``GET /admin/slabs`` — the slab list, joined to whatever graded price
row each slab has. An UNPRICED slab is a first-class row there, not an omission:
after the verified-join rule, every Japanese slab is unpriced by construction
(spike §3.2), and a list that hid them would hide most of the JP shelf.
"""

from datetime import date, datetime
from decimal import Decimal

from merlins_collection.models.catalog import CatalogCard
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


# ---------------------------------------------------------------------------
# T6 — GET /admin/slabs, the slab list
# ---------------------------------------------------------------------------

def _catalog(card_id="swsh1-1", name="Celebi V"):
    return CatalogCard(
        card_id=card_id, name=name, set_id="swsh1", set_name="S&S", number="1",
        images={"small": "s", "large": "l"}, prices={},
        last_synced_at=datetime(2026, 8, 8, 12, 0, 0),
    )


class TestSlabList:
    def test_returns_only_graded_items(self, admin_client):
        """RED 12. Raw singles are the overwhelming majority of the table; a
        slab list that included them would be the inventory page again."""
        client, repo, token = admin_client
        slab = _graded(cert_number="10000001")
        repo.put_inventory_item(slab)
        repo.put_inventory_item(RawInventoryItem(
            card_id="swsh1-1", finish="holofoil", condition=Condition.NM,
            cost_basis=Decimal("4"), acquired_at=date(2026, 1, 1),
        ))

        body = client.get("/admin/slabs", headers=_auth(token)).json()
        assert [i["item_id"] for i in body["items"]] == [slab.item_id]

    def test_a_slab_with_no_card_id_still_appears_with_a_null_value(self, admin_client):
        """RED 15. It is real inventory that was really paid for. After the
        verified-join rule this is the ordinary state of a Japanese slab, so
        dropping it would drop most of the JP shelf."""
        client, repo, token = admin_client
        repo.put_inventory_item(_graded(cert_number="10000002", card_id=None))

        rows = client.get("/admin/slabs", headers=_auth(token)).json()["items"]
        assert len(rows) == 1
        assert rows[0]["market_value"] is None
        assert rows[0]["price_source"] is None

    def test_a_priced_slab_carries_its_value_source_and_age(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        repo.put_inventory_item(_graded(cert_number="10000003"))
        repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"),
                                     Decimal("2479.5"))

        row = client.get("/admin/slabs", headers=_auth(token)).json()["items"][0]
        assert Decimal(row["market_value"]) == Decimal("2479.5")
        assert row["price_source"] == "manual"
        assert row["value_as_of"]

    def test_priced_false_returns_only_slabs_with_no_value(self, admin_client):
        """RED 13. This is the worklist — after the owner's 2026-08-08 decision
        it is the ONLY worklist, since an unpriced slab is not Triage-flagged."""
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        priced = _graded(cert_number="10000004")
        unpriced = _graded(cert_number="10000005", card_id=None)
        repo.put_inventory_item(priced)
        repo.put_inventory_item(unpriced)
        repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"),
                                     Decimal("100"))

        rows = client.get("/admin/slabs?priced=false", headers=_auth(token)).json()["items"]
        assert [r["item_id"] for r in rows] == [unpriced.item_id]

        rows = client.get("/admin/slabs?priced=true", headers=_auth(token)).json()["items"]
        assert [r["item_id"] for r in rows] == [priced.item_id]

    def test_company_and_grade_filter_together(self, admin_client):
        """RED 14."""
        client, repo, token = admin_client
        want = _graded(cert_number="10000006", company=GradingCompany.PSA,
                       grade=Decimal("10"))
        wrong_grade = _graded(cert_number="10000007", company=GradingCompany.PSA,
                              grade=Decimal("9"))
        wrong_company = _graded(cert_number="10000008", company=GradingCompany.CGC,
                                grade=Decimal("10"))
        for item in (want, wrong_grade, wrong_company):
            repo.put_inventory_item(item)

        rows = client.get("/admin/slabs?company=PSA&grade=10",
                          headers=_auth(token)).json()["items"]
        assert [r["item_id"] for r in rows] == [want.item_id]

    def test_a_half_grade_filters_exactly(self, admin_client):
        """`9.5` and `9` are different slabs and different price rows."""
        client, repo, token = admin_client
        half = _graded(cert_number="10000009", grade=Decimal("9.5"))
        whole = _graded(cert_number="10000010", grade=Decimal("9"))
        repo.put_inventory_item(half)
        repo.put_inventory_item(whole)

        rows = client.get("/admin/slabs?grade=9.5", headers=_auth(token)).json()["items"]
        assert [r["item_id"] for r in rows] == [half.item_id]

    def test_status_narrows_the_list_and_nothing_is_hidden_by_default(self, admin_client):
        """No default status filter. A sold slab is still a slab you owned and
        priced, and silently omitting it would make the list disagree with the
        vault for reasons the operator cannot see."""
        client, repo, token = admin_client
        available = _graded(cert_number="10000011")
        sold = _graded(cert_number="10000012", status=ItemStatus.SOLD)
        repo.put_inventory_item(available)
        repo.put_inventory_item(sold)

        everything = client.get("/admin/slabs", headers=_auth(token)).json()
        assert everything["total"] == 2

        rows = client.get("/admin/slabs?status=sold", headers=_auth(token)).json()["items"]
        assert [r["item_id"] for r in rows] == [sold.item_id]

    def test_limit_bounds_the_response(self, admin_client):
        client, repo, token = admin_client
        for n in range(5):
            repo.put_inventory_item(_graded(cert_number=f"1100000{n}"))

        body = client.get("/admin/slabs?limit=2", headers=_auth(token)).json()
        assert len(body["items"]) == 2
        assert body["total"] == 5, "total counts the matches, not the page"

    def test_rows_carry_what_the_list_renders(self, admin_client):
        """Card art needs `card_id`; the columns need cert, company, grade,
        cost and a name."""
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        repo.put_inventory_item(_graded(cert_number="10000013"))

        row = client.get("/admin/slabs", headers=_auth(token)).json()["items"][0]
        for field in ("item_id", "card_id", "name", "cert_number", "company",
                      "grade", "cost_basis", "status", "market_value",
                      "value_as_of", "price_source"):
            assert field in row, f"{field} missing from a slab row"
        assert row["name"] == "Celebi V"

    def test_requires_admin_auth(self, admin_client):
        client, _repo, _token = admin_client
        assert client.get("/admin/slabs").status_code in (401, 403)


# ===========================================================================
# RFC 0009 T7 — the refresh trigger and the price pin
# ===========================================================================
#
# `POST /admin/slabs/refresh-prices` mirrors `POST /admin/market/sync`: a 202,
# a background run, and a status endpoint to poll. The shape is copied
# deliberately rather than invented, because the Market page's polling UI is
# the precedent the frontend will reuse.
#
# The pin exists because of the owner's 2026-08-09 precedence decision: a
# hand-typed price is NOT protected from the provider unless it is explicitly
# pinned. Without a way to pin, that decision would mean "the provider always
# wins", which is the option the owner did not pick.

import pytest

from merlins_collection.config import settings
from merlins_collection.services.slab.pricing import GradedPrices


@pytest.fixture(autouse=True)
def _reset_refresh_status():
    """The refresh status is a module-level dict, exactly like the two in
    `routers/admin/market.py`. A test that leaves it `"running"` would 409 every
    later test that presses the button — the order-dependence `test_market.py`'s
    own reset fixture exists to prevent."""
    yield
    from merlins_collection.routers.admin import slabs

    slabs._REFRESH_STATUS.update({
        "state": "idle", "started_at": None, "finished_at": None,
        "candidates": None, "priced": None, "skipped": None, "failures": None,
        "credits_remaining": None, "error": None,
    })


class _FakeProvider:
    """Answers one vendor id; records every call. No socket, no credits."""

    def __init__(self, prices=None):
        self._prices = prices
        self.calls: list[str] = []

    def resolve(self, *, name, set_name, number, language=None):
        return None

    def prices(self, price_source_id):
        self.calls.append(price_source_id)
        return self._prices


def _priced(**by_grade) -> GradedPrices:
    return GradedPrices(
        price_source_id="253266",
        prices={k: Decimal(v) for k, v in by_grade.items()},
        confidences={k: "high" for k in by_grade},
        currency="USD", currency_assumed=True, as_of=None,
    )


class TestRefreshPricesTrigger:
    def test_it_returns_immediately_and_reports_status(self, admin_client,
                                                       monkeypatch):
        """RED 12. Same contract as `POST /admin/market/sync`: 202 + a status
        endpoint, because a run that walks the shelf cannot finish inside a
        request."""
        from merlins_collection.routers.admin import slabs

        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        repo.put_inventory_item(_graded(cert_number="10000101",
                                        price_source_id="253266"))
        provider = _FakeProvider(_priced(psa10="2479.5"))
        monkeypatch.setattr(slabs, "build_pricing_provider", lambda: provider)

        resp = client.post("/admin/slabs/refresh-prices", headers=_auth(token))
        assert resp.status_code == 202
        assert resp.json()["state"] == "started"

        status = client.get("/admin/slabs/refresh-prices/status",
                            headers=_auth(token)).json()
        assert status["state"] == "completed"
        assert status["priced"] == 1
        assert status["error"] is None
        assert repo.get_graded_market_value(
            "swsh1-1", GradingCompany.PSA, Decimal("10")) == Decimal("2479.5")

    def test_a_second_trigger_while_one_runs_is_a_409(self, admin_client):
        """Each run spends real credits — 2 per slab against a 100-credit day.
        A double-click must not buy the same prices twice."""
        from merlins_collection.routers.admin import slabs

        client, _repo, token = admin_client
        slabs._REFRESH_STATUS["state"] = "running"

        resp = client.post("/admin/slabs/refresh-prices", headers=_auth(token))
        assert resp.status_code == 409

    def test_an_unconfigured_key_reports_a_failure_not_a_silent_success(
            self, admin_client, monkeypatch):
        """Unlike the nightly job, which degrades quietly so the other steps
        still run, a human pressed this button — telling them "completed" when
        no provider exists would be a lie they cannot see through."""
        client, _repo, token = admin_client
        # Forced empty, not assumed: `env_file=".env"` resolves against the CWD,
        # so a run started from `backend/` would load the REAL key and this test
        # would spend real credits.
        monkeypatch.setattr(settings, "pokemonpricetracker_api_key", "")

        client.post("/admin/slabs/refresh-prices", headers=_auth(token))

        status = client.get("/admin/slabs/refresh-prices/status",
                            headers=_auth(token)).json()
        assert status["state"] == "failed"
        assert status["error"]

    def test_the_status_never_leaks_the_api_key(self, admin_client, monkeypatch):
        """Both keys have already been pasted into a chat transcript once
        (progress.md). The status dict is served to a browser."""
        from merlins_collection.routers.admin import slabs

        client, _repo, token = admin_client
        monkeypatch.setattr(settings, "pokemonpricetracker_api_key", "sekrit-key-xyz")

        def explode():
            raise RuntimeError("vendor said no")

        monkeypatch.setattr(slabs, "build_pricing_provider", explode)
        client.post("/admin/slabs/refresh-prices", headers=_auth(token))

        body = client.get("/admin/slabs/refresh-prices/status",
                          headers=_auth(token)).text
        assert "sekrit-key-xyz" not in body

    def test_it_requires_admin_auth(self, admin_client):
        client, _repo, _token = admin_client
        assert client.post("/admin/slabs/refresh-prices").status_code in (401, 403)


class TestPricePin:
    """The owner's 2026-08-09 decision needs a way to actually pin a price."""

    def test_pinning_protects_a_price_from_the_provider(self, admin_client):
        client, repo, token = admin_client
        item = _graded(cert_number="10000102")
        repo.put_inventory_item(item)
        repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"),
                                     Decimal("5000"), source="manual")

        resp = client.put("/admin/slabs/%s/price/pin" % item.item_id,
                          json={"pinned": True}, headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["pinned"] is True
        row = repo.get_graded_price_row("swsh1-1", GradingCompany.PSA, Decimal("10"))
        assert row["pinned"] is True
        assert row["market_value"] == Decimal("5000"), "pinning must not touch the figure"

    def test_unpinning_releases_it_back_to_automatic(self, admin_client):
        client, repo, token = admin_client
        item = _graded(cert_number="10000103")
        repo.put_inventory_item(item)
        repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"),
                                     Decimal("5000"), source="manual", pinned=True)

        resp = client.put("/admin/slabs/%s/price/pin" % item.item_id,
                          json={"pinned": False}, headers=_auth(token))

        assert resp.status_code == 200
        row = repo.get_graded_price_row("swsh1-1", GradingCompany.PSA, Decimal("10"))
        assert row["pinned"] is False

    def test_pinning_a_slab_with_no_price_row_is_a_404(self, admin_client):
        """There is nothing to protect yet. A 200 here would report a pin that
        the next provider write would silently ignore."""
        client, repo, token = admin_client
        item = _graded(cert_number="10000104")
        repo.put_inventory_item(item)

        resp = client.put("/admin/slabs/%s/price/pin" % item.item_id,
                          json={"pinned": True}, headers=_auth(token))
        assert resp.status_code == 404

    def test_pinning_an_unknown_item_is_a_404(self, admin_client):
        client, _repo, token = admin_client
        resp = client.put("/admin/slabs/01JQNOTAREALITEMID/price/pin",
                          json={"pinned": True}, headers=_auth(token))
        assert resp.status_code == 404

    def test_pinning_a_raw_item_is_refused(self, admin_client):
        """Raw singles are priced off the catalog card, not off a
        `GRADEDPRICE#` row — there is no pin to set."""
        client, repo, token = admin_client
        raw = RawInventoryItem(card_id="swsh1-1", finish="normal",
                               condition=Condition.NM, cost_basis=Decimal("1"),
                               acquired_at=date(2026, 1, 1))
        repo.put_inventory_item(raw)

        resp = client.put("/admin/slabs/%s/price/pin" % raw.item_id,
                          json={"pinned": True}, headers=_auth(token))
        assert resp.status_code in (400, 404)

    def test_the_slab_list_reports_whether_a_price_is_pinned(self, admin_client):
        """The list is where the operator decides what to protect, so it has to
        show what is already protected."""
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog()])
        repo.put_inventory_item(_graded(cert_number="10000105"))
        repo.set_graded_market_value("swsh1-1", GradingCompany.PSA, Decimal("10"),
                                     Decimal("5000"), source="manual", pinned=True)

        row = client.get("/admin/slabs", headers=_auth(token)).json()["items"][0]
        assert row["price_pinned"] is True

    def test_requires_admin_auth(self, admin_client):
        client, _repo, _token = admin_client
        assert client.put("/admin/slabs/anything/price/pin",
                          json={"pinned": True}).status_code in (401, 403)
