"""FastAPI auth dependencies built on the Cognito JWT verifier.

``get_verifier`` is a cached singleton built from settings; tests override it
via ``app.dependency_overrides``. ``get_current_user`` enforces a valid bearer
token (401 on missing/invalid, 503 when signing keys can't be fetched), and
``require_admin`` gates admin-only routes (403).
"""

from __future__ import annotations

import hmac
import sys
from functools import lru_cache
from pathlib import Path

import boto3
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from merlins_collection.config import settings
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.services.bedrock import (
    _ADMIN_SYSTEM_PROMPT,
    ADMIN_VISIBILITY,
    BedrockChatService,
    _admin_tool_schemas,
)
from merlins_collection.services.cognito import (
    CognitoJwtVerifier,
    InvalidTokenError,
    JwksUnavailableError,
)
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.mcp_client import McpToolExecutor

# auto_error=False so a missing credential yields our own 401 (with a
# WWW-Authenticate header) rather than FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)

# settings.mcp_server_path is documented as relative to the backend directory.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


@lru_cache
def get_repo() -> InventoryRepository:
    """Provide the inventory repository as a cached singleton."""
    return InventoryRepository(settings.dynamodb_table_name, region_name=settings.aws_region)


@lru_cache
def get_mcp_executor() -> McpToolExecutor:
    """Provide the MCP tool executor as a cached singleton.

    One executor per process: it owns the MCP server subprocess (spawned
    lazily on the first tool call), which every chat request shares.
    """
    path = Path(settings.mcp_server_path)
    if not path.is_absolute():
        path = (_BACKEND_DIR / path).resolve()
    return McpToolExecutor(
        ["node", str(path)],
        # pydantic-settings reads .env without exporting to os.environ, so the
        # config the MCP server needs must be handed over explicitly.
        env={
            "AWS_REGION": settings.aws_region,
            "DYNAMODB_TABLE_NAME": settings.dynamodb_table_name,
        },
    )


@lru_cache
def get_admin_mcp_executor() -> McpToolExecutor:
    """The ADMIN analyst tool executor — a second, separate subprocess.

    Deliberately NOT the same server as ``get_mcp_executor()``: the customer
    chat must not be able to name a tool that reads cost basis, and the
    cheapest way to guarantee that is for the process serving customers to have
    never loaded one (RFC 0018, owner decision 6). The isolation is which
    binary is spawned, not a runtime boolean — a wrong branch in a future
    refactor is a quiet diff, a wrong process is a loud one.

    **A Python module, not a second npm workspace** (roadmap item 4). ``mcp`` is
    already a backend dependency and ``merlins_collection`` is already installed
    in the image, so this needs no Dockerfile stage, no workspace entry and no
    CI job — and, far more importantly, the tools it serves import
    ``services.ledger`` and ``services.condition_pricing`` directly instead of
    re-implementing the ledger in a second language.
    """
    return McpToolExecutor(
        [sys.executable, "-m", "merlins_collection.mcp_admin"],
        env={
            "AWS_REGION": settings.aws_region,
            "DYNAMODB_TABLE_NAME": settings.dynamodb_table_name,
        },
    )


def shutdown_admin_mcp_executor() -> None:
    """Close the admin executor's subprocess if one was ever created.

    Called from the same app-shutdown hook as its customer sibling. Both are
    lazy — spawned on the first tool call, never at boot — so a deployment
    nobody asks an analyst question of never starts this process at all.
    """
    if get_admin_mcp_executor.cache_info().currsize:
        get_admin_mcp_executor().close()


def shutdown_mcp_executor() -> None:
    """Close the executor's subprocess if one was ever created (app shutdown)."""
    if get_mcp_executor.cache_info().currsize:
        get_mcp_executor().close()


def get_bedrock_service() -> BedrockChatService:
    """Provide a Bedrock chat service wired to the MCP tool executor.

    Not cached: the boto3 client build is cheap, and per-request construction
    keeps tests free to override this dependency; the expensive part (the MCP
    subprocess) is the cached executor singleton.
    """
    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    return BedrockChatService(
        client=client,
        model_id=settings.bedrock_model_id,
        tool_executor=get_mcp_executor(),
        repo=get_repo(),
    )


def get_admin_bedrock_service() -> BedrockChatService:
    """The admin analyst's Bedrock service — a second instance, three ways apart.

    Different **tool schemas** (built from the packaged
    `merlins_collection/admin-tool-contract.json`), a
    different **system prompt** (read-only analyst, not a card-shop assistant),
    a different **executor** (a separate subprocess that is the only one wired
    to a server implementing those tools), and a different **hydration scope**
    (`ADMIN_VISIBILITY`, so an aging-stock answer does not silently drop the
    raw-in-storage rows the question was about).

    Two layers keep cost basis off the customer wire, and neither is a runtime
    boolean: a tool the customer model was never told about cannot be called,
    and the customer executor is wired to a process that does not implement it.

    ``max_tool_turns``/``max_query_tool_calls_per_request`` are RAISED here,
    on the same per-instance seam `tools`/`system_prompt` use (RFC 0020 item
    6) — the module defaults (5/10) stay exactly what `get_bedrock_service`
    (customer) gets, since raising them for the librarian tools' benefit
    would otherwise have silently widened the customer surface too
    (adversarial review of RFC 0020's first draft). 6/14 are not a guess:
    `scripts/measure_admin_chat_latency.py`, extended with the four RFC-0020
    raw-listing tools and run live against the production table
    (2026-08-30), measured a 14-call sequence mixing all eight admin tools at
    ~15.6-16.9s of tool time across two runs (52-57% of the 30s Lambda
    budget) — over a home connection to us-east-1, so production (in-region)
    has more headroom than that, not less. `list_shows` was the single
    slowest tool (~2.4s median, an N+1 `get_show_analytics` per show) —
    still well under the 10s per-call `McpToolExecutor` timeout, which is
    left unchanged.
    """
    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    return BedrockChatService(
        client=client,
        model_id=settings.bedrock_model_id,
        tool_executor=get_admin_mcp_executor(),
        repo=get_repo(),
        tools=_admin_tool_schemas(),
        system_prompt=_ADMIN_SYSTEM_PROMPT,
        visible=ADMIN_VISIBILITY,
        max_tool_turns=6,
        max_query_tool_calls_per_request=14,
    )


@lru_cache
def get_verifier() -> CognitoJwtVerifier | None:
    """Provide the Cognito JWT verifier as a cached singleton (keeps the JWKS cache warm).

    Returns ``None`` when auth is disabled (dev bypass) so a missing Cognito
    config can't 500 requests before ``get_current_user`` short-circuits.
    """
    if settings.auth_disabled:
        return None
    return CognitoJwtVerifier(
        region=settings.aws_region,
        user_pool_id=settings.cognito_user_pool_id,
        client_id=settings.cognito_client_id,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: CognitoJwtVerifier | None = Depends(get_verifier),
) -> AuthenticatedUser:
    if settings.auth_disabled:
        # Dev-only bypass (AUTH_DISABLED=true): fake user, never admin.
        return AuthenticatedUser(sub="dev-user", username="dev", is_admin=False)
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verifier.verify(credentials.credentials)
    except JwksUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: CognitoJwtVerifier | None = Depends(get_verifier),
) -> AuthenticatedUser:
    """Gate admin routes. Accepts either:
    1. A static API key (``ADMIN_API_KEY`` setting) — for Retool/external tools.
    2. A valid Cognito JWT for a user in the admin group.

    The API key path bypasses Cognito entirely and returns a synthetic admin user.
    """
    # --- Path 1: Static API key ---
    if settings.admin_api_key and credentials and credentials.credentials:
        # compare_digest, not `==`: a plain string comparison short-circuits on
        # the first differing byte, which leaks the key one character at a time
        # to anyone who can time the response. That matters here specifically
        # because the backend sits behind a Lambda Function URL with
        # `authType: NONE` and no WAF, so this comparison is reachable from the
        # public internet at whatever rate the caller likes.
        if hmac.compare_digest(credentials.credentials, settings.admin_api_key):
            return AuthenticatedUser(
                sub="api-key-admin",
                username="retool",
                is_admin=True,
            )

    # --- Path 2: Cognito JWT (original flow) ---
    user = get_current_user(credentials, verifier)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
