"""``/admin`` router package — admin-only endpoints for Retool integration.

All routes are gated behind ``require_admin`` (Cognito admin group check).
Retool authenticates with a Bearer JWT token.
"""

from fastapi import APIRouter, Depends

from merlins_collection.dependencies import require_admin
from merlins_collection.models.inventory import INVENTORY_LOCATION_CHOICES

from .inventory import router as inventory_router
from .market import router as market_router
from .market import watchlist_router
from .purchases import router as purchases_router
from .sales import router as sales_router
from .show_prep import router as show_prep_router
from .trades import router as trades_router
from .vault import router as vault_router
from .cosigners import router as cosigners_router

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

admin_router.include_router(inventory_router)
admin_router.include_router(market_router)
admin_router.include_router(watchlist_router)
admin_router.include_router(sales_router)
admin_router.include_router(purchases_router)
admin_router.include_router(trades_router)
admin_router.include_router(show_prep_router)
admin_router.include_router(vault_router)
admin_router.include_router(cosigners_router)


@admin_router.get("/health")
def admin_health() -> dict:
    """Simple health check confirming admin auth is working."""
    return {"status": "ok", "scope": "admin"}


@admin_router.get("/locations")
def list_locations() -> list[dict[str, str]]:
    """Return the canonical list of inventory location choices for dropdowns."""
    return INVENTORY_LOCATION_CHOICES
