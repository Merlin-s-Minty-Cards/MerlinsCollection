"""``/admin`` router package — admin-only endpoints for Retool integration.

All routes are gated behind ``require_admin`` (Cognito admin group check).
Retool authenticates with a Bearer JWT token.
"""

from fastapi import APIRouter, Depends

from merlins_collection.dependencies import require_admin

from .analytics import router as analytics_router
from .catalog import router as catalog_router
from .chat import router as chat_router
from .cosigners import router as cosigners_router
from .docs import router as docs_router
from .inventory import router as inventory_router
from .locations import router as locations_router
from .market import router as market_router
from .market import watchlist_router
from .purchases import router as purchases_router
from .sales import router as sales_router
from .show_prep import router as show_prep_router
from .slabs import router as slabs_router
from .trades import router as trades_router
from .triage import router as triage_router
from .unmatched import router as unmatched_router
from .vault import router as vault_router

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

admin_router.include_router(inventory_router)
admin_router.include_router(catalog_router)
admin_router.include_router(chat_router)
admin_router.include_router(locations_router)
admin_router.include_router(market_router)
admin_router.include_router(watchlist_router)
admin_router.include_router(sales_router)
admin_router.include_router(purchases_router)
admin_router.include_router(trades_router)
admin_router.include_router(show_prep_router)
admin_router.include_router(vault_router)
admin_router.include_router(cosigners_router)
admin_router.include_router(analytics_router)
admin_router.include_router(triage_router)
admin_router.include_router(unmatched_router)
admin_router.include_router(slabs_router)
admin_router.include_router(docs_router)


@admin_router.get("/health")
def admin_health() -> dict:
    """Simple health check confirming admin auth is working."""
    return {"status": "ok", "scope": "admin"}
