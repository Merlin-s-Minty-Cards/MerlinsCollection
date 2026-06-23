"""AWS Cognito JWT validation.

Verifies Cognito **access** tokens (the AWS-recommended token for API
authorization): RS256 signature against the user pool's JWKS, issuer, expiry
(with clock-skew leeway), ``token_use == "access"`` and a strict ``client_id``
match. Roles are derived from the ``cognito:groups`` claim.

The JWKS is injectable for tests; in production it is fetched from the pool's
``/.well-known/jwks.json`` and cached, with a single rate-limited refresh on an
unknown ``kid`` so signing-key rotation self-heals without hammering the IDP.
"""

from __future__ import annotations

import time

import httpx
from jose import jwt
from jose.exceptions import JWTError

from merlins_collection.models.auth import AuthenticatedUser

_JWKS_PATH = "/.well-known/jwks.json"
_HTTP_TIMEOUT = 5.0


class InvalidTokenError(Exception):
    """The token is present but failed validation (structure, signature, claims)."""


class JwksUnavailableError(Exception):
    """The signing keys could not be fetched — a transient infrastructure fault.

    Distinct from :class:`InvalidTokenError` so callers can answer 503 (our
    problem) rather than 401 (the client's problem).
    """


class CognitoJwtVerifier:
    def __init__(
        self,
        region: str,
        user_pool_id: str,
        client_id: str,
        *,
        jwks: dict | None = None,
        http_client: httpx.Client | None = None,
        admin_group: str = "admin",
        leeway: int = 60,
        min_refresh_interval: float = 60.0,
    ):
        self._region = region
        self._user_pool_id = user_pool_id
        self._client_id = client_id
        self._admin_group = admin_group
        self._leeway = leeway
        self._min_refresh_interval = min_refresh_interval
        self._http_client = http_client
        # An injected JWKS is static (tests); otherwise keys are fetched lazily.
        self._static_jwks = jwks
        self._cached_jwks: dict | None = jwks
        self._last_fetch = 0.0

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self._region}.amazonaws.com/{self._user_pool_id}"

    # -- JWKS retrieval ---------------------------------------------------
    def _fetch_jwks(self) -> dict:
        url = f"{self.issuer}{_JWKS_PATH}"
        client = self._http_client or httpx.Client(timeout=_HTTP_TIMEOUT)
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                raise JwksUnavailableError(f"JWKS fetch returned HTTP {resp.status_code}")
            data = resp.json()
        except httpx.HTTPError as exc:
            raise JwksUnavailableError("JWKS fetch failed") from exc
        finally:
            if self._http_client is None:
                client.close()
        self._cached_jwks = data
        self._last_fetch = time.monotonic()
        return data

    def _get_jwks(self, *, force_refresh: bool = False) -> dict:
        if self._static_jwks is not None:
            return self._static_jwks
        if self._cached_jwks is None:
            return self._fetch_jwks()
        if force_refresh and (time.monotonic() - self._last_fetch) >= self._min_refresh_interval:
            return self._fetch_jwks()
        return self._cached_jwks

    @staticmethod
    def _find_key(jwks: dict, kid: str) -> dict | None:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    # -- verification -----------------------------------------------------
    def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise InvalidTokenError("malformed token header") from exc
        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("token header missing 'kid'")

        # Look up the signing key; refresh once (rate-limited) if the kid is
        # unknown, to absorb Cognito key rotation. JWKS-fetch failures raise
        # JwksUnavailableError, which deliberately propagates (not a 401).
        key = self._find_key(self._get_jwks(), kid)
        if key is None:
            key = self._find_key(self._get_jwks(force_refresh=True), kid)
        if key is None:
            raise InvalidTokenError("no signing key matches token 'kid'")
        if key.get("kty") != "RSA":
            raise InvalidTokenError("unexpected signing key type")

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],  # pin: blocks alg=none / HS256 confusion
                issuer=self.issuer,
                options={"verify_aud": False, "leeway": self._leeway},
            )
        except JWTError as exc:
            raise InvalidTokenError(str(exc) or "token validation failed") from exc

        if claims.get("token_use") != "access":
            raise InvalidTokenError("token_use is not 'access'")
        # Access tokens carry no `aud`; client_id is the only guard against a
        # token minted for another app client in the same pool. Must be present.
        if claims.get("client_id") != self._client_id:
            raise InvalidTokenError("client_id does not match")

        groups = claims.get("cognito:groups") or []
        return AuthenticatedUser(
            sub=claims.get("sub", ""),
            username=claims.get("username") or claims.get("cognito:username"),
            email=claims.get("email"),
            groups=list(groups),
            is_admin=self._admin_group in groups,
        )
