"""Tests for show CRUD (RFC 0008 §F1 / T7).

    POST   /admin/shows
    PUT    /admin/shows/{show_id}
    POST   /admin/shows/{show_id}/archive
    POST   /admin/shows/{show_id}/unarchive
    GET    /admin/shows?include_archived=

The owner decision this file encodes: **archive, not delete**. Nothing is ever
destroyed, so there is no repo-level delete for a show and no 409 "show is in
use" guard — a show with real transactions behind it archives just like an
empty one, and the analytics snapshots that reference it never dangle.

Two tests here go beyond the endpoint contract and pin the STORAGE shape
(``TestShowStorageIsUpsert``). ``put_show`` writes ``SK=SHOW#{date}#{show_id}``,
optionally suffixed with the import generation — so "write the show again" is
only an upsert when neither the date nor the generation has moved. The one-time
import path never hit that, because it only ever created. ``PUT`` does, on the
two most ordinary edits there are.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.business import (
    ItemCategory,
    Show,
    Transaction,
    TransactionType,
)


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
    yield client, dynamo_repo, admin_token
    app.dependency_overrides.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create(client, token, **overrides) -> dict:
    """POST a show and return the created body (asserting it worked)."""
    body = {"name": "Portland Card Show", "date": "2025-06-01"}
    body.update(overrides)
    resp = client.post("/admin/shows", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _listing(client, token, *, include_archived=None) -> list[dict]:
    params = {} if include_archived is None else {"include_archived": include_archived}
    resp = client.get("/admin/shows", params=params, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ===========================================================================
# Create
# ===========================================================================

class TestCreateShow:
    def test_creates_show_with_generated_id(self, admin_client):
        client, repo, token = admin_client

        resp = client.post(
            "/admin/shows",
            json={
                "name": "Portland Card Show",
                "date": "2025-06-01",
                "venue": "Lloyd Center",
                "city": "Portland, OR",
                "sales_goal": "2500.00",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["show_id"], "server must generate a show_id"
        assert created["name"] == "Portland Card Show"
        assert created["date"] == "2025-06-01"
        assert created["venue"] == "Lloyd Center"
        assert created["archived"] is False

        stored = repo.get_show(created["show_id"])
        assert stored is not None
        assert stored.name == "Portland Card Show"

    def test_client_supplied_show_id_is_ignored(self, admin_client):
        """The id is the server's to mint — a client cannot pick or overwrite one."""
        client, _repo, token = admin_client
        created = _create(client, token, show_id="attacker-chosen")
        assert created["show_id"] != "attacker-chosen"

    def test_missing_required_field_422(self, admin_client):
        client, _repo, token = admin_client
        resp = client.post(
            "/admin/shows", json={"name": "No Date Show"}, headers=_auth(token)
        )
        assert resp.status_code == 422

    def test_unparseable_date_422(self, admin_client):
        client, _repo, token = admin_client
        resp = client.post(
            "/admin/shows",
            json={"name": "Bad Date", "date": "not-a-date"},
            headers=_auth(token),
        )
        assert resp.status_code == 422


# ===========================================================================
# Update
# ===========================================================================

class TestUpdateShow:
    def test_partial_update_leaves_other_fields_intact(self, admin_client):
        client, _repo, token = admin_client
        created = _create(
            client, token, venue="Lloyd Center", city="Portland, OR",
            cash_at_start="300.00", notes="bring the good binder",
        )

        resp = client.put(
            f"/admin/shows/{created['show_id']}",
            json={"name": "Portland Card Show (Spring)"},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        updated = resp.json()
        assert updated["name"] == "Portland Card Show (Spring)"
        assert updated["venue"] == "Lloyd Center"
        assert updated["city"] == "Portland, OR"
        assert updated["cash_at_start"] == "300.00"
        assert updated["notes"] == "bring the good binder"
        assert updated["date"] == created["date"]

    def test_cannot_change_show_id(self, admin_client):
        client, repo, token = admin_client
        created = _create(client, token)

        resp = client.put(
            f"/admin/shows/{created['show_id']}",
            json={"show_id": "hijacked", "name": "Renamed"},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["show_id"] == created["show_id"]
        assert repo.get_show("hijacked") is None
        assert repo.get_show(created["show_id"]).name == "Renamed"

    def test_unknown_id_404(self, admin_client):
        client, _repo, token = admin_client
        resp = client.put(
            "/admin/shows/does-not-exist",
            json={"name": "Ghost"},
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_invalid_field_value_422(self, admin_client):
        client, _repo, token = admin_client
        created = _create(client, token)
        resp = client.put(
            f"/admin/shows/{created['show_id']}",
            json={"date": "the third of never"},
            headers=_auth(token),
        )
        assert resp.status_code == 422


# ===========================================================================
# Storage shape — PUT must not fork a show into two rows
# ===========================================================================

class TestShowStorageIsUpsert:
    """``put_show``'s SK embeds the date and the import generation.

    Both of those move underneath an ordinary admin edit, and when they do a
    naive re-put writes a SECOND row rather than replacing the first: the show
    list shows the same show twice, and archiving flips only one of them.
    """

    def test_changing_the_date_does_not_duplicate_the_show(self, admin_client):
        client, repo, token = admin_client
        created = _create(client, token, date="2025-06-01")

        resp = client.put(
            f"/admin/shows/{created['show_id']}",
            json={"date": "2025-06-08"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text

        rows = [s for s in repo.list_shows() if s.show_id == created["show_id"]]
        assert len(rows) == 1, f"date change forked the show into {len(rows)} rows"
        assert rows[0].date == date(2025, 6, 8)

    def test_editing_an_imported_show_does_not_duplicate_it(self, admin_client):
        """A show written by the spreadsheet import carries its generation in
        the SK, which survives ``finalize_import``. An admin edit runs with no
        generation set, so it writes an unsuffixed SK — a different key for the
        same show unless ``put_show`` cleans up after itself."""
        client, repo, token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_show(Show(show_id="imported-1", name="Imported Show",
                           date=date(2025, 5, 1)))
        repo.set_import_generation(None)

        resp = client.put(
            "/admin/shows/imported-1",
            json={"name": "Imported Show (renamed)"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text

        rows = [s for s in repo.list_shows() if s.show_id == "imported-1"]
        assert len(rows) == 1, f"editing an imported show left {len(rows)} rows"
        assert rows[0].name == "Imported Show (renamed)"

    def test_import_generations_still_coexist(self, admin_client):
        """The cleanup must NOT reach across generations: a load-then-swap
        import relies on the prior generation's copy surviving until
        ``finalize_import`` decides commit or rollback (dynamodb.py BLOCKING-1b).
        """
        _client, repo, _token = admin_client

        repo.set_import_generation("gen-1")
        repo.put_show(Show(show_id="dual-1", name="Gen One", date=date(2025, 5, 1)))
        repo.set_import_generation("gen-2")
        repo.put_show(Show(show_id="dual-1", name="Gen Two", date=date(2025, 5, 1)))
        repo.set_import_generation(None)

        rows = [s for s in repo.list_shows() if s.show_id == "dual-1"]
        assert len(rows) == 2, "the prior generation's copy must survive the load phase"


# ===========================================================================
# Archive / unarchive
# ===========================================================================

class TestArchiveShow:
    def test_archive_sets_flag_without_destroying_the_row(self, admin_client):
        client, repo, token = admin_client
        created = _create(client, token)

        resp = client.post(
            f"/admin/shows/{created['show_id']}/archive", headers=_auth(token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["archived"] is True
        stored = repo.get_show(created["show_id"])
        assert stored is not None, "archive must never delete the show"
        assert stored.archived is True
        assert stored.name == created["name"]

    def test_archive_is_idempotent(self, admin_client):
        client, repo, token = admin_client
        created = _create(client, token)

        first = client.post(
            f"/admin/shows/{created['show_id']}/archive", headers=_auth(token)
        )
        second = client.post(
            f"/admin/shows/{created['show_id']}/archive", headers=_auth(token)
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["archived"] is True
        assert len([s for s in repo.list_shows() if s.show_id == created["show_id"]]) == 1

    def test_archive_unknown_id_404(self, admin_client):
        client, _repo, token = admin_client
        resp = client.post("/admin/shows/nope/archive", headers=_auth(token))
        assert resp.status_code == 404

    def test_archive_succeeds_for_a_show_with_transactions(self, admin_client):
        """Encodes the owner decision: no 409 in-use guard. Archiving is
        non-destructive, so a show with real history archives like any other."""
        client, repo, token = admin_client
        created = _create(client, token)
        repo.put_transaction(Transaction(
            type=TransactionType.SALE,
            item_id="item-1",
            category=ItemCategory.RAW,
            date=date(2025, 6, 1),
            amount=Decimal("40.00"),
            payment_method="cash",
            show_id=created["show_id"],
        ))

        resp = client.post(
            f"/admin/shows/{created['show_id']}/archive", headers=_auth(token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["archived"] is True
        assert len(repo.list_transactions_for_show(created["show_id"])) == 1

    def test_unarchive_restores_the_show(self, admin_client):
        client, repo, token = admin_client
        created = _create(client, token)
        client.post(f"/admin/shows/{created['show_id']}/archive", headers=_auth(token))

        resp = client.post(
            f"/admin/shows/{created['show_id']}/unarchive", headers=_auth(token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["archived"] is False
        assert repo.get_show(created["show_id"]).archived is False

    def test_unarchive_unknown_id_404(self, admin_client):
        client, _repo, token = admin_client
        resp = client.post("/admin/shows/nope/unarchive", headers=_auth(token))
        assert resp.status_code == 404


# ===========================================================================
# Listing
# ===========================================================================

class TestListShows:
    def test_excludes_archived_by_default(self, admin_client):
        """The existing caller (Show Analytics' Shows tab) sends no param and
        must not start seeing archived shows."""
        client, _repo, token = admin_client
        kept = _create(client, token, name="Kept Show", date="2025-06-01")
        gone = _create(client, token, name="Typo Show", date="2025-06-02")
        client.post(f"/admin/shows/{gone['show_id']}/archive", headers=_auth(token))

        ids = [s["show_id"] for s in _listing(client, token)]
        assert kept["show_id"] in ids
        assert gone["show_id"] not in ids

    def test_include_archived_true_includes_it(self, admin_client):
        client, _repo, token = admin_client
        gone = _create(client, token, name="Typo Show")
        client.post(f"/admin/shows/{gone['show_id']}/archive", headers=_auth(token))

        listing = _listing(client, token, include_archived="true")
        entry = next(s for s in listing if s["show_id"] == gone["show_id"])
        assert entry["archived"] is True

    def test_unarchived_show_returns_to_the_default_listing(self, admin_client):
        client, _repo, token = admin_client
        show = _create(client, token)
        client.post(f"/admin/shows/{show['show_id']}/archive", headers=_auth(token))
        client.post(f"/admin/shows/{show['show_id']}/unarchive", headers=_auth(token))

        ids = [s["show_id"] for s in _listing(client, token)]
        assert show["show_id"] in ids

    def test_legacy_row_without_archived_attribute_loads_as_not_archived(
        self, admin_client
    ):
        """MIGRATION SAFETY. Every show row already in DynamoDB predates the
        ``archived`` field. Reading one must default to False, not 500."""
        client, repo, token = admin_client
        repo._table.put_item(Item={
            "PK": "SHOWLIST",
            "SK": "SHOW#2025-03-01#legacy-1",
            "entity": "show",
            "show_id": "legacy-1",
            "name": "Legacy Show",
            "date": "2025-03-01",
        })

        listing = _listing(client, token)
        entry = next(s for s in listing if s["show_id"] == "legacy-1")
        assert entry["archived"] is False
        assert repo.get_show("legacy-1").archived is False


# ===========================================================================
# Auth
# ===========================================================================

_ROUTES = [
    ("get", "/admin/shows"),
    ("post", "/admin/shows"),
    ("put", "/admin/shows/some-id"),
    ("post", "/admin/shows/some-id/archive"),
    ("post", "/admin/shows/some-id/unarchive"),
]


def _call(client, method, path, headers=None):
    kwargs = {} if method == "get" else {"json": {}}
    if headers:
        kwargs["headers"] = headers
    return getattr(client, method)(path, **kwargs)


class TestShowsRequireAdmin:
    @pytest.mark.parametrize("method,path", _ROUTES)
    def test_rejects_unauthenticated_caller(self, admin_client, method, path):
        client, _repo, _token = admin_client
        assert _call(client, method, path).status_code in (401, 403)

    @pytest.mark.parametrize("method,path", _ROUTES)
    def test_rejects_non_admin_caller(self, admin_client, mint_token, method, path):
        client, _repo, _token = admin_client
        user_token = mint_token(claims={"cognito:groups": ["users"]})
        resp = _call(client, method, path, headers=_auth(user_token))
        assert resp.status_code == 403
