import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from merlins_collection.models.auth import AuthenticatedUser


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


# --- require_admin dependency (unit-level; no admin routes exist yet) -----


def test_require_admin_allows_admin_user():
    from merlins_collection.dependencies import require_admin

    admin = AuthenticatedUser(sub="u", is_admin=True)
    assert require_admin(user=admin) is admin


def test_require_admin_blocks_non_admin_user():
    from merlins_collection.dependencies import require_admin

    customer = AuthenticatedUser(sub="u", is_admin=False)
    with pytest.raises(HTTPException) as exc:
        require_admin(user=customer)
    assert exc.value.status_code == 403
