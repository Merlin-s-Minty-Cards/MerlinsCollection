"""Application entry point: builds the FastAPI ``app`` and mounts the routers.

Run with ``uvicorn merlins_collection.main:app``. Each router owns its own URL
prefix (``/auth``, ``/inventory``, ``/chat``); dependencies and services are
wired in ``dependencies.py``. CORS is restricted to the configured frontend
origins, and the MCP tool-executor subprocess (spawned lazily by the first
chat request) is torn down on shutdown.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from merlins_collection.config import settings
from merlins_collection.rate_limit import validate_rate_limit_settings
from merlins_collection.routers import auth, chat, health, inventory, public
from merlins_collection.routers.admin import admin_router

logger = logging.getLogger(__name__)

# Validate every rate-limit setting at import (app-construction) time. A malformed
# or empty limit value crashes startup LOUDLY here rather than silently disabling
# the cost cap at request time — the R14 fail-open trap. Deploys fail fast.
validate_rate_limit_settings(settings)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if settings.auth_disabled:
        logger.warning(
            "AUTH_DISABLED is set — Cognito auth is BYPASSED. Dev only; "
            "never run production with this flag."
        )
    yield
    # Kill the MCP server subprocess (if one was started) — child processes
    # don't die with the parent on Windows.
    from merlins_collection.dependencies import shutdown_mcp_executor

    shutdown_mcp_executor()


app = FastAPI(title="Merlin's Collection API", version="0.1.0", lifespan=_lifespan)

# App-side rate limiting is DynamoDB-backed and distributed (correct across
# restarts, redeploys, and multiple instances) — see rate_limit.py. Each limited
# route enforces it via a per-route dependency (rate_limit_chat / _search / _auth)
# that runs before the endpoint body, so an over-limit /chat request 429s without
# ever reaching Bedrock.

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # Expose Retry-After so the cross-origin browser frontend can actually read
    # the back-off hint on a 429 (it is not a CORS-safelisted response header).
    expose_headers=["Retry-After"],
)
app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(chat.router)
app.include_router(health.router)
app.include_router(public.router)  # prefix="/public" — unauthenticated read surface
app.include_router(admin_router)  # prefix="/admin" — Retool admin panel
