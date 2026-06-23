import os
import time
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient


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
    return _generate_signing_key


@pytest.fixture
def signing_key() -> SigningKey:
    return _generate_signing_key("test-key-1")


@pytest.fixture
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


@pytest.fixture
def dynamo_repo():
    from moto import mock_aws

    with mock_aws():
        os.environ["AWS_ACCESS_KEY_ID"] = "testing"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        from merlins_collection.services.dynamodb import InventoryRepository

        repo = InventoryRepository("merlins-cards-test", region_name="us-east-1")
        repo.create_table()
        yield repo
