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
from merlins_collection.routers import auth, chat, inventory

logger = logging.getLogger(__name__)


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(chat.router)
