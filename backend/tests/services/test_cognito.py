import time

import httpx
import pytest

from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.services.cognito import (
    CognitoJwtVerifier,
    InvalidTokenError,
    JwksUnavailableError,
)


# --- happy paths ---------------------------------------------------------


def test_verify_returns_user_for_valid_access_token(make_verifier, mint_token):
    user = make_verifier().verify(mint_token())
    assert isinstance(user, AuthenticatedUser)
    assert user.sub == "user-123"
    assert user.username == "merlin"
    assert user.groups == []
    assert user.is_admin is False


def test_verify_marks_admin_from_cognito_groups(make_verifier, mint_token):
    user = make_verifier().verify(mint_token({"cognito:groups": ["admin", "staff"]}))
    assert user.is_admin is True
    assert set(user.groups) == {"admin", "staff"}


def test_verify_non_admin_group_is_not_admin(make_verifier, mint_token):
    user = make_verifier().verify(mint_token({"cognito:groups": ["customers"]}))
    assert user.is_admin is False


def test_verify_custom_admin_group_name(make_verifier, mint_token):
    user = make_verifier(admin_group="owners").verify(
        mint_token({"cognito:groups": ["owners"]})
    )
    assert user.is_admin is True


# --- claim / signature rejections (validly signed unless noted) ----------


def test_verify_rejects_expired_token(make_verifier, mint_token):
    expired = mint_token({"exp": int(time.time()) - 7200})
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(expired)


def test_verify_allows_token_within_clock_skew(make_verifier, mint_token):
    # Expired 30s ago but within the 60s leeway -> still valid.
    slightly_stale = mint_token({"exp": int(time.time()) - 30})
    user = make_verifier(leeway=60).verify(slightly_stale)
    assert user.sub == "user-123"


def test_verify_rejects_wrong_issuer(make_verifier, mint_token):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token({"iss": "https://evil.example.com/pool"}))


def test_verify_rejects_wrong_client_id(make_verifier, mint_token):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token({"client_id": "some-other-client"}))


def test_verify_rejects_missing_client_id(make_verifier, mint_token):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token({"client_id": None}))


def test_verify_rejects_id_token(make_verifier, mint_token):
    # Only access tokens authorize the API; an ID token must be refused.
    id_token = mint_token({"token_use": "id", "client_id": None, "aud": "test-client-id"})
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(id_token)


def test_verify_rejects_tampered_signature(make_verifier, mint_token, make_signing_key):
    # Signed by a different key but carrying a kid that IS in the JWKS.
    impostor = make_signing_key("test-key-1")
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token(key=impostor))


def test_verify_rejects_unknown_kid(make_verifier, mint_token):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token(kid="not-in-jwks"))


def test_verify_rejects_missing_kid_header(make_verifier, mint_token):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify(mint_token(headers={"kid": None}))


def test_verify_rejects_malformed_token(make_verifier):
    with pytest.raises(InvalidTokenError):
        make_verifier().verify("this.is.not-a-jwt")


# --- JWKS fetching / caching / rotation ----------------------------------


def test_verify_refetches_jwks_on_unknown_kid(make_verifier, mint_token, signing_key):
    # Simulates key rotation: first fetch lacks the key, the forced refetch has it.
    real_jwks = {"keys": [signing_key.jwk]}
    state = {"calls": 0}

    def handler(request):
        state["calls"] += 1
        body = real_jwks if state["calls"] >= 2 else {"keys": []}
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = make_verifier(with_jwks=False, http_client=http, min_refresh_interval=0)

    user = verifier.verify(mint_token())
    assert user.sub == "user-123"
    assert state["calls"] == 2  # initial fetch + one refresh


def test_verify_rate_limits_jwks_refresh(make_verifier, mint_token):
    # The JWKS never contains the kid; the cooldown must prevent a second fetch.
    state = {"calls": 0}

    def handler(request):
        state["calls"] += 1
        return httpx.Response(200, json={"keys": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = make_verifier(
        with_jwks=False, http_client=http, min_refresh_interval=10_000
    )

    with pytest.raises(InvalidTokenError):
        verifier.verify(mint_token())
    assert state["calls"] == 1  # lazy load only; refresh suppressed by cooldown


def test_verify_raises_jwks_unavailable_on_fetch_failure(make_verifier, mint_token):
    def handler(request):
        return httpx.Response(503, json={})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = make_verifier(with_jwks=False, http_client=http)

    with pytest.raises(JwksUnavailableError):
        verifier.verify(mint_token())


def test_issuer_is_derived_from_region_and_pool(make_verifier):
    assert (
        make_verifier().issuer
        == "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_testpool"
    )
