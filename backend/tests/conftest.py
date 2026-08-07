import os
import time
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Drop the cached rate-limiter singleton between tests.

    Counters now live in DynamoDB (not process memory), so isolation comes from
    each test's fresh moto table; this just clears the lru_cache so a test never
    reuses a limiter bound to a torn-down moto backend. Guarded so the suite
    still collects if the module can't import (TDD RED phase).
    """
    try:
        from merlins_collection.rate_limit import get_rate_limiter
    except Exception:
        yield
        return
    get_rate_limiter.cache_clear()
    yield
    get_rate_limiter.cache_clear()


@pytest.fixture(autouse=True)
def _reset_catalog_cache():
    """Drop the process-local catalog cache between tests.

    Autouse and global, not scoped to the market tests: the cache is
    module-level state that outlives a test, while each test's moto table does
    not. Without this, one test's cards answer the next test's catalog search
    against a table that never held them -- order-dependent failures of exactly
    the kind ``_reset_sync_status_dicts`` exists to prevent.
    """
    from merlins_collection.services import catalog_cache

    catalog_cache.invalidate()
    yield
    catalog_cache.invalidate()


@pytest.fixture
def client():
    from merlins_collection.main import app
    return TestClient(app)


# --- Cognito / JWT auth test helpers -------------------------------------

# Fixed values shared by the auth tests; the verifier under test is configured
# with these and `mint_token` mints tokens that satisfy them by default.
COGNITO_REGION = "us-east-1"
COGNITO_USER_POOL_ID = "us-east-1_testpool"
COGNITO_CLIENT_ID = "test-client-id"
COGNITO_ISSUER = (
    f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
)


@dataclass
class SigningKey:
    private_pem: str
    jwk: dict
    kid: str


def _generate_signing_key(kid: str = "test-key-1") -> SigningKey:
    """Generate an RSA keypair and the matching public JWK (with kid)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk as jose_jwk

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    pub_jwk = jose_jwk.construct(public_pem, "RS256").to_dict()
    pub_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return SigningKey(private_pem=private_pem, jwk=pub_jwk, kid=kid)


@pytest.fixture
def make_signing_key():
    """Factory for tests that need a SECOND, different key (see test_cognito)."""
    return _generate_signing_key


# Session-scoped: RSA-2048 keygen costs ~53ms and roughly 700 tests take a token,
# so regenerating per test spent ~37s of the suite producing identical material.
# Safe to share only because nothing writes to either value -- verified across
# the suite: no test mutates ``jwks`` or ``signing_key.jwk``
# (``test_cognito.py`` builds a *new* dict from ``signing_key.jwk``), and
# ``CognitoJwtVerifier`` rebinds ``self._cached_jwks`` rather than mutating the
# dict it was handed. Keep it that way, or these go back to function scope.
@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    return _generate_signing_key("test-key-1")


@pytest.fixture(scope="session")
def jwks(signing_key) -> dict:
    return {"keys": [signing_key.jwk]}


@pytest.fixture
def cognito_config() -> dict:
    return {
        "region": COGNITO_REGION,
        "user_pool_id": COGNITO_USER_POOL_ID,
        "client_id": COGNITO_CLIENT_ID,
    }


@pytest.fixture
def mint_token(signing_key):
    """Factory minting a signed JWT. Defaults to a valid Cognito access token.

    Override or remove claims via `claims` (a value of None drops the claim).
    Drop/replace header fields via `headers` (None drops). Sign with a different
    key via `key`, or set a specific `kid`.
    """
    from jose import jwt

    def _mint(claims=None, *, key=None, kid=None, headers=None) -> str:
        key = key or signing_key
        now = int(time.time())
        base = {
            "sub": "user-123",
            "iss": COGNITO_ISSUER,
            "exp": now + 3600,
            "iat": now,
            "token_use": "access",
            "client_id": COGNITO_CLIENT_ID,
            "username": "merlin",
        }
        base.update(claims or {})
        base = {k: v for k, v in base.items() if v is not None}
        hdr = {"kid": kid if kid is not None else key.kid}
        hdr.update(headers or {})
        hdr = {k: v for k, v in hdr.items() if v is not None}
        return jwt.encode(base, key.private_pem, algorithm="RS256", headers=hdr)

    return _mint


@pytest.fixture
def make_verifier(cognito_config, jwks):
    """Factory building a CognitoJwtVerifier wired to the test config/JWKS."""

    def _make(*, with_jwks: bool = True, **kwargs):
        from merlins_collection.services.cognito import CognitoJwtVerifier

        return CognitoJwtVerifier(
            region=cognito_config["region"],
            user_pool_id=cognito_config["user_pool_id"],
            client_id=cognito_config["client_id"],
            jwks=jwks if with_jwks else None,
            **kwargs,
        )

    return _make


# --- moto / DynamoDB ------------------------------------------------------
#
# ONE ``mock_aws()`` for the whole session, reset between tests -- do not go back
# to entering a fresh one per test.
#
# Entering ``mock_aws()`` invalidates botocore's service-model caches, so the
# very next ``boto3.resource("dynamodb")`` pays a full model reload. Measured on
# this machine 2026-08-07: building the repo + table cost **507ms** per test
# behind a fresh ``mock_aws()`` versus **15ms** inside a long-lived one (the
# resource call alone is 371ms vs 3.5ms). Roughly 850 of the suite's tests take
# ``dynamo_repo`` directly or transitively, which is why ``--durations`` used to
# be almost entirely ``setup`` rows at ~0.65s and the backend suite took 9m50s.
#
# Isolation is unchanged: resetting the moto dynamodb backend drops every table
# and all stored state, which is exactly what leaving the old per-test
# ``mock_aws()`` did.


@pytest.fixture(scope="session")
def _moto_aws():
    """Start a single moto mock for the whole session.

    Credentials are set before the mock starts so no test can reach real AWS.
    """
    from moto import mock_aws

    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    mock = mock_aws()
    mock.start()
    yield mock
    mock.stop()


@pytest.fixture(autouse=True)
def _clean_aws(_moto_aws):
    """Give every test an empty DynamoDB, standing in for a fresh ``mock_aws()``.

    Autouse **and** an explicit dependency of every fixture that builds a table
    (``dynamo_repo`` here, ``chat_client`` in ``routers/test_chat.py``). The
    autouse alone would work today only by relying on pytest instantiating
    autouse fixtures ahead of requested ones at the same scope; naming it as a
    dependency makes the ordering a fact rather than an inference. Without it a
    second test creating the same table name gets ``ResourceInUseException``,
    since nothing else clears tables now that the mock outlives the test.

    DynamoDB is the only AWS service these tests mock -- every repository here
    (``InventoryRepository``, ``DynamoRateLimiter``) is DynamoDB-backed.
    """
    import moto.backends

    for backend in moto.backends.get_backend("dynamodb").values():
        backend.reset()
    yield


@pytest.fixture
def dynamo_repo(_clean_aws):
    from merlins_collection.services.dynamodb import InventoryRepository

    # The name is load-bearing: script tests pass it as a ``--confirm-table``
    # CLI argument and assert on it (test_apply_review_decisions,
    # test_wipe_catalog, test_backfill_language, test_build_review).
    repo = InventoryRepository("merlins-cards-test", region_name="us-east-1")
    repo.create_table()
    yield repo
