"""Catalog-search caching for ``GET /admin/market/search`` (RFC 0008 T9).

The endpoint used to re-scan the whole catalog table on every request --
measured at 11.2s against the live 31,603-row table, on every keystroke-batch
from the Buy page's autocomplete. These tests pin the in-process cache that
replaces that scan.

Most of the value here is NOT the "it caches" test. It is the invalidation and
freshness tests, which exist to stop the cache from trading a performance bug
for a correctness bug -- serving a catalog that no longer matches the table,
with no way to tell from the UI.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from merlins_collection.models.catalog import CardImages, CatalogCard


# ---- helpers ----

def _catalog_card(card_id="en:sv1-1", name="Pikachu", set_id="en:sv1",
                  set_name="Scarlet & Violet", number="001", rarity="Common"):
    return CatalogCard(
        card_id=card_id,
        name=name,
        set_id=set_id,
        set_name=set_name,
        number=number,
        rarity=rarity,
        images=CardImages(
            small="https://example.com/small.webp",
            large="https://example.com/large.webp",
        ),
        last_synced_at=datetime.now(tz=timezone.utc),
        prices={},
    )


class _StubTcgdexClient:
    """A TCGdex client that reports no sets at all.

    Enough for ``sync_new_sets`` to complete a full run without writing
    anything, which is exactly the case these tests need: the sync ran, so the
    cache must be dropped regardless of whether that particular run happened to
    find new cards.
    """

    def list_sets(self, language):
        return []

    def iter_brief_cards(self, language):
        return iter(())


def _count_scans(repo) -> list[int]:
    """Wrap ``list_all_catalog_cards`` so tests can count full-table scans.

    Patched on the repo INSTANCE, so it sees the call however the endpoint
    reaches it -- directly today, through a cache layer once one exists.
    """
    calls: list[int] = []
    original = repo.list_all_catalog_cards

    def counting():
        calls.append(1)
        return original()

    repo.list_all_catalog_cards = counting
    return calls


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


def _names(resp) -> list[str]:
    return [item["name"] for item in resp.json()["items"]]


# ===========================================================================


class TestCatalogSearchCaching:
    """The cache itself: a repeat search must not re-scan the table."""

    def test_repeat_name_search_scans_the_table_once(self, admin_client):
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-1", name="Pikachu"),
            _catalog_card(card_id="en:sv1-2", name="Charizard", number="002"),
        ])
        scans = _count_scans(repo)

        first = client.get("/admin/market/search?name=pika", headers=_auth(token))
        second = client.get("/admin/market/search?name=chari", headers=_auth(token))

        assert first.status_code == 200
        assert second.status_code == 200
        assert _names(first) == ["Pikachu"]
        assert _names(second) == ["Charizard"]
        assert len(scans) == 1, (
            f"expected one full-table scan across both searches, got {len(scans)}"
        )

    def test_set_scoped_search_never_scans_the_whole_catalog(self, admin_client):
        """A ``set_id`` search has a GSI; it must not touch the full-scan path.

        Neither consulting the cache nor populating it: a set query returns one
        set's cards, and seeding the full-catalog cache from that partial result
        would make every later name search silently miss everything else.
        """
        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv1-1", name="Pikachu", set_id="en:sv1"),
            _catalog_card(card_id="en:sv2-1", name="Charizard", set_id="en:sv2"),
        ])
        scans = _count_scans(repo)

        scoped = client.get("/admin/market/search?set_id=en:sv1", headers=_auth(token))
        assert scoped.status_code == 200
        assert _names(scoped) == ["Pikachu"]
        assert scans == [], "set-scoped search must not run a full-table scan"

        # And it must not have poisoned the cache: a name search for a card in
        # the OTHER set still finds it.
        later = client.get("/admin/market/search?name=chari", headers=_auth(token))
        assert _names(later) == ["Charizard"]


class TestCatalogCacheFreshness:
    """The tests that stop the cache from becoming a correctness bug."""

    def test_a_card_added_by_a_catalog_sync_is_findable_without_a_restart(
        self, admin_client
    ):
        from merlins_collection.services.catalog_sync import sync_new_sets

        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(name="Pikachu")])

        # Populate whatever cache exists.
        client.get("/admin/market/search?name=pika", headers=_auth(token))

        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv9-1", name="Mimikyu", set_id="en:sv9",
                          number="042"),
        ])
        sync_new_sets(repo, _StubTcgdexClient())

        resp = client.get("/admin/market/search?name=mimikyu", headers=_auth(token))
        assert _names(resp) == ["Mimikyu"], (
            "a catalog sync must drop the cache; a newly synced card was not "
            "findable without restarting the API process"
        )

    def test_a_price_sync_drops_the_cache(self, admin_client):
        """Prices ride along on the cached rows, so the depth pass invalidates too.

        The Buy page reads ``card.prices`` off a search result to pre-fill market
        value. A cache that survives a price sync hands the owner yesterday's
        number while the table holds today's.
        """
        from merlins_collection.services.catalog_sync import refresh_held_prices

        client, repo, token = admin_client
        repo.batch_upsert_catalog_cards([_catalog_card(name="Pikachu")])
        client.get("/admin/market/search?name=pika", headers=_auth(token))

        repo.batch_upsert_catalog_cards([
            _catalog_card(card_id="en:sv9-1", name="Mimikyu", set_id="en:sv9",
                          number="042"),
        ])
        refresh_held_prices(repo, _StubTcgdexClient(), datetime.now(tz=timezone.utc).date())

        resp = client.get("/admin/market/search?name=mimikyu", headers=_auth(token))
        assert _names(resp) == ["Mimikyu"], (
            "a price sync must drop the cache"
        )

    def test_an_empty_catalog_is_never_cached(self, admin_client):
        """The failure mode this whole RFC came from, guarded.

        ``scripts/seed_catalog.py`` runs in a SEPARATE process, so it cannot
        invalidate the API's cache. If an empty scan were cached, the owner
        would seed 31k cards and still watch Buy find nothing until the TTL
        expired -- indistinguishable from the bug they just fixed.
        """
        client, repo, token = admin_client
        scans = _count_scans(repo)

        empty = client.get("/admin/market/search?name=pika", headers=_auth(token))
        assert empty.json()["total"] == 0

        repo.batch_upsert_catalog_cards([_catalog_card(name="Pikachu")])

        after_seed = client.get("/admin/market/search?name=pika", headers=_auth(token))
        assert _names(after_seed) == ["Pikachu"], (
            "an empty scan must not be cached; a catalog seeded out-of-process "
            "was invisible to the running API"
        )
        assert len(scans) == 2


class TestCatalogCacheModule:
    """Unit-level contract of the cache primitive itself."""

    def test_an_invalidation_during_a_scan_discards_that_scan(self):
        """The race that would strand a stale catalog for a full TTL.

        A search that begins its scan at T-5s and finishes at T+1s must not
        overwrite an invalidation that landed at T. Without a generation check
        the late writer wins and stamps pre-sync data with a fresh timestamp --
        the sync's whole point, silently undone, for the length of the TTL.
        """
        from merlins_collection.services import catalog_cache

        catalog_cache.invalidate()
        card = _catalog_card()

        def loader_that_is_invalidated_mid_scan():
            # Stands in for the 11s window the real scan is open for.
            catalog_cache.invalidate()
            return [card]

        first = catalog_cache.get_catalog_cards(loader_that_is_invalidated_mid_scan)
        assert first == [card], "the in-flight scan still serves its own caller"

        calls: list[int] = []

        def counting_loader():
            calls.append(1)
            return [card]

        catalog_cache.get_catalog_cards(counting_loader)
        assert calls == [1], (
            "the scan that straddled an invalidation must not have been stored"
        )

    def test_a_ttl_refill_stores_its_result(self, monkeypatch):
        """Guards the interaction between freeing the expired copy and storing.

        A refill drops the ~93 MB expired list before scanning, so it does not
        hold two of them at once. If that release ever bumped the generation it
        would make the fill discard its own result and re-scan on every single
        request -- the original 11-second bug restored, now with the memory
        cost on top.
        """
        from merlins_collection.services import catalog_cache

        catalog_cache.invalidate()
        card = _catalog_card()
        calls: list[int] = []

        def counting_loader():
            calls.append(1)
            return [card]

        catalog_cache.get_catalog_cards(counting_loader)
        assert calls == [1]

        monkeypatch.setattr(catalog_cache, "TTL_SECONDS", -1)
        catalog_cache.get_catalog_cards(counting_loader)
        assert calls == [1, 1], "an expired cache must be re-read"

        monkeypatch.setattr(catalog_cache, "TTL_SECONDS", 900)
        catalog_cache.get_catalog_cards(counting_loader)
        assert calls == [1, 1], "the refill did not store its result"
