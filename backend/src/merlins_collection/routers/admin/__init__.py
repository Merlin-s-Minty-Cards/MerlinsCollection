"""``/admin`` router package — admin-only endpoints for Retool integration.

All routes are gated behind ``require_admin`` (Cognito admin group check).
Retool authenticates with a Bearer JWT token.
"""

from fastapi import APIRouter, Depends

from merlins_collection.dependencies import require_admin

from .inventory import router as inventory_router
from .market import router as market_router
from .market import watchlist_router

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

admin_router.include_router(inventory_router)
admin_router.include_router(market_router)
admin_router.include_router(watchlist_router)


@admin_router.get("/health")
def admin_health() -> dict:
    """Simple health check confirming admin auth is working."""
    return {"status": "ok", "scope": "admin"}
