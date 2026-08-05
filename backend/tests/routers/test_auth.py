import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def authed(cognito_config, jwks):
    """TestClient with get_verifier overridden; `holder` lets a test swap it."""
    from merlins_collection.dependencies import get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    holder = {
        "verifier": CognitoJwtVerifier(
            region=cognito_config["region"],
            user_pool_id=cognito_config["user_pool_id"],
            client_id=cognito_config["client_id"],
            jwks=jwks,
        )
    }
    app.dependency_overrides[get_verifier] = lambda: holder["verifier"]
    yield TestClient(app), holder
    app.dependency_overrides.clear()


def test_me_returns_current_user_with_valid_token(authed, mint_token):
    client, _ = authed
    resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {mint_token({'cognito:groups': ['admin']})}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == "user-123"
    assert body["username"] == "merlin"
    assert body["is_admin"] is True


def test_me_requires_authentication(authed):
    client, _ = authed
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_me_rejects_invalid_token(authed):
    client, _ = authed
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_me_rejects_non_bearer_scheme(authed):
    client, _ = authed
    resp = client.get("/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_me_returns_503_when_jwks_unavailable(authed, mint_token, cognito_config):
    from merlins_collection.services.cognito import CognitoJwtVerifier

    client, holder = authed

    def handler(request):
        return httpx.Response(503, json={})

    holder["verifier"] = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {mint_token()}"})
    assert resp.status_code == 503


# --- require_admin: static ADMIN_API_KEY bypass path -----------------------
# The Cognito-JWT path of require_admin is already covered end-to-end by every
# admin router's TestAdminAuthGate-style tests (e.g. test_inventory.py). Only
# the API-key bypass (for Retool/external tools) had zero coverage anywhere.


def test_require_admin_accepts_configured_api_key(monkeypatch, cognito_config, jwks):
    from merlins_collection import dependencies
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    monkeypatch.setattr(dependencies.settings, "admin_api_key", "test-retool-key")
    # require_admin's `verifier` sub-dependency is resolved by FastAPI before
    # the handler body runs, even on the API-key success path — so it must be
    # overridden the same way admin_client is, or get_verifier() 500s on the
    # test env's empty Cognito config.
    app.dependency_overrides[dependencies.get_verifier] = lambda: CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    client = TestClient(app)
    try:
        resp = client.get(
            "/admin/health",
            headers={"Authorization": "Bearer test-retool-key"},
        )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_require_admin_rejects_wrong_api_key(monkeypatch, cognito_config, jwks):
    from merlins_collection import dependencies
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    monkeypatch.setattr(dependencies.settings, "admin_api_key", "test-retool-key")
    app.dependency_overrides[dependencies.get_verifier] = lambda: CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    client = TestClient(app)
    try:
        resp = client.get(
            "/admin/health",
            headers={"Authorization": "Bearer not-the-right-key"},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()
