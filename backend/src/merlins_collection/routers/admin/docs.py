"""``/admin/docs`` — the admin operations knowledge base (RFC 0026).

Serves the SAME content the `search_admin_docs` MCP tool reads
(`services/admin_docs.py`) over the ordinary authenticated admin REST API —
the frontend Docs tab fetches this exactly like every other admin dropdown/
list (`useLocations`, `useCosigners`, ...), and there is no second content
pipeline for the two surfaces to drift against each other.

No new auth surface: `admin_router` already gates every route under it
behind `require_admin` (see `routers/admin/__init__.py`).
"""

from __future__ import annotations

from fastapi import APIRouter

from merlins_collection.services import admin_docs

router = APIRouter(prefix="/docs", tags=["admin-docs"])


@router.get("")
def get_admin_docs() -> dict:
    return {
        "categories": admin_docs.list_categories(),
        "articles": admin_docs.list_all(),
    }
