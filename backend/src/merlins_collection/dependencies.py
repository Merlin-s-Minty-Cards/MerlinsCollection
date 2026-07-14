"""FastAPI auth dependencies built on the Cognito JWT verifier.

``get_verifier`` is a cached singleton built from settings; tests override it
via ``app.dependency_overrides``. ``get_current_user`` enforces a valid bearer
token (401 on missing/invalid, 503 when signing keys can't be fetched), and
``require_admin`` gates admin-only routes (403).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import boto3
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from merlins_collection.config import settings
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.services.bedrock import BedrockChatService
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
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
