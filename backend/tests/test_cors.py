"""CORS: the browser frontend (a different origin) must be able to call the API."""

import pytest
from fastapi.testclient import TestClient

FRONTEND_ORIGIN = "http://localhost:3000"


@pytest.fixture
def cors_client(cognito_config, jwks):
    """TestClient with a working verifier so non-preflight requests 401 cleanly."""
    from merlins_collection.dependencies import get_verifier
    from merlins_collection.main import app
    from merlins_collection.services.cognito import CognitoJwtVerifier

    verifier = CognitoJwtVerifier(
        region=cognito_config["region"],
        user_pool_id=cognito_config["user_pool_id"],
        client_id=cognito_config["client_id"],
        jwks=jwks,
    )
    app.dependency_overrides[get_verifier] = lambda: verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_preflight_allows_frontend_origin_with_auth_header(cors_client):
    resp = cors_client.options(
        "/inventory/search",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers


def test_actual_response_carries_cors_header_even_when_unauthorized(cors_client):
    """The 401 must still be CORS-readable or the browser masks it as a network error."""
    resp = cors_client.get("/inventory/search", headers={"Origin": FRONTEND_ORIGIN})
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN


def test_unknown_origin_gets_no_cors_header(cors_client):
    resp = cors_client.get(
        "/inventory/search", headers={"Origin": "https://evil.example.com"}
    )
    assert resp.headers.get("access-control-allow-origin") is None


def test_chat_preflight_allows_post(cors_client):
    resp = cors_client.options(
        "/chat/",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200
    assert "POST" in resp.headers.get("access-control-allow-methods", "")
