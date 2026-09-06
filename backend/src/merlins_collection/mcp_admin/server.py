"""Tool registration for the admin analyst MCP server.

Thin by design: every tool here is a few lines that parse arguments and hand
off to `services/admin_analytics.py`. The arithmetic lives there so it is
testable without an MCP transport, and so it can import the same helpers the
admin pages use.

Tool names and argument shapes are pinned to
`merlins_collection/admin-tool-contract.json` by
`backend/tests/test_admin_tool_contract.py`, the same way the customer side is
pinned to `shared/tool-contract.json`. Change the contract file first.

The admin contract lives INSIDE the package while the customer one lives in
`shared/`, and that asymmetry is deliberate: `shared/` is for values crossing
the Python/TypeScript boundary, and `mcp-server/` (TypeScript) reads the
customer contract. Nothing outside the backend has ever read this one, and a
file resolved relative to the repo root does not survive the container image —
see `backend/tests/test_admin_contract_ships.py`.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from merlins_collection.services import admin_analytics, admin_docs
from merlins_collection.services.dynamodb import InventoryRepository

#: Every tool on this server is read-only (owner decision 1). This is asserted
#: by a test, not merely intended: the server must have no write path to
#: mis-fire, because routing writes through a language model would put a
#: probabilistic layer in front of the most carefully-built guarantees in the
#: repo.
READ_ONLY = ToolAnnotations(readOnlyHint=True)


def _json(payload: Any) -> str:
    """Serialize a tool result, rendering Decimal as a STRING, never a float.

    A money figure that round-trips through IEEE-754 to reach the model is the
    class of bug CLAUDE.md bans `parseFloat` over. The model reads these as
    text either way, so there is nothing to gain from a float and a cent to
    lose.
    """
    def default(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date):
            return value.isoformat()
        raise TypeError(f"not JSON-serializable: {type(value).__name__}")

    return json.dumps(payload, default=default)


def build_server(repo: InventoryRepository) -> FastMCP:
    server = FastMCP("merlins-collection-admin")

    @server.tool(
        name="get_profit_summary",
        description=(
            "Gross sales, purchases, net and margin for a date range, "
            "optionally scoped to one show. start and end are both OPTIONAL: "
            "omit both for a wide default window through today (see the "
            "response's period for the exact dates actually used — it is not "
            "guaranteed to be literally every transaction ever recorded); "
            "omit just one to leave that side unbounded. Dates are ISO "
            "(YYYY-MM-DD) and both bounds are inclusive."
        ),
        annotations=READ_ONLY,
    )
    def get_profit_summary(
        start: str | None = None, end: str | None = None, show_id: str | None = None
    ) -> str:
        return _json(
            admin_analytics.profit_summary(
                repo,
                start=date.fromisoformat(start) if start else None,
                end=date.fromisoformat(end) if end else None,
                show_id=show_id,
            )
        )

    @server.tool(
        name="find_aging_stock",
        description=(
            "Held inventory that has been sitting unsold the longest, oldest "
            "first. Sold, lost and returned-to-consignor items are excluded — "
            "they are not sitting on a shelf. Optionally filter by location or "
            "by minimum value."
        ),
        annotations=READ_ONLY,
    )
    def find_aging_stock(
        min_days: int = 90,
        location: str | None = None,
        min_value: float | None = None,
    ) -> str:
        return _json(
            admin_analytics.aging_stock(
                repo,
                min_days=min_days,
                location=location,
                # str() first: float -> Decimal directly carries the binary
                # rounding error through into a money comparison.
                min_value=Decimal(str(min_value)) if min_value is not None else None,
            )
        )

    @server.tool(
        name="get_consignor_position",
        description=(
            "Value of stock held on each consignor's behalf, with our cut and "
            "their projected share. Archived consignors are included — "
            "archiving is not settlement. Omit consignor_id for all of them."
        ),
        annotations=READ_ONLY,
    )
    def get_consignor_position(consignor_id: str | None = None) -> str:
        return _json(admin_analytics.consignor_position(repo, consignor_id=consignor_id))

    @server.tool(
        name="find_pricing_outliers",
        description=(
            "Held stock whose asking price disagrees with the market figure. "
            "direction is 'over' (asking above market), 'under' (below), or "
            "'unpriced' (no asking price). threshold_pct is a magnitude — "
            "direction alone decides the sign."
        ),
        annotations=READ_ONLY,
    )
    def find_pricing_outliers(direction: str, threshold_pct: float = 20.0) -> str:
        return _json(
            admin_analytics.pricing_outliers(
                repo, direction=direction, threshold_pct=threshold_pct
            )
        )

    @server.tool(
        name="list_shows",
        description=(
            "Every show with its date/venue and, when available, its analytics "
            "snapshot (gross sales, purchases, net, item counts), newest first. "
            "A show that has never been archived or manually analyzed has "
            "has_analytics=false and null money fields — that is not the same "
            "as a show with zero sales; say so rather than treating it as "
            "unprofitable. If limit truncates the result, you are seeing the "
            "most RECENT shows, not a representative sample of all of them."
        ),
        annotations=READ_ONLY,
    )
    def list_shows(
        start: str | None = None,
        end: str | None = None,
        include_archived: bool = True,
        limit: int = 200,
    ) -> str:
        return _json(
            admin_analytics.shows_with_analytics(
                repo,
                start=date.fromisoformat(start) if start else None,
                end=date.fromisoformat(end) if end else None,
                include_archived=include_archived,
                limit=limit,
            )
        )

    @server.tool(
        name="list_transactions",
        description=(
            "Raw ledger rows in a date range. NEVER sum amount across these "
            "rows to state a profit/revenue/gross figure — call "
            "get_profit_summary instead (trade cash legs double-count and "
            "voided rows must be excluded; both are flagged per-row here so "
            "you can filter, but the aggregate tools already do it "
            "correctly). Use this to browse, filter, or answer questions the "
            "aggregate tools do not cover."
        ),
        annotations=READ_ONLY,
    )
    def list_transactions(
        start: str | None = None,
        end: str | None = None,
        show_id: str | None = None,
        type: str | None = None,
        include_voided: bool = False,
        sort: str | None = None,
        limit: int = 100,
    ) -> str:
        return _json(
            admin_analytics.raw_transactions(
                repo,
                start=date.fromisoformat(start) if start else None,
                end=date.fromisoformat(end) if end else None,
                show_id=show_id,
                type=type,
                include_voided=include_voided,
                sort=sort,
                limit=limit,
            )
        )

    @server.tool(
        name="list_inventory",
        description=(
            "Raw inventory rows with admin-only fields (cost basis, "
            "consignment terms, review flags) the customer-facing inventory "
            "tools never expose. Prices here are RAW figures, not "
            "customer-facing condition-adjusted prices. A row's consignment "
            "field is non-null when the item is held for someone else — "
            "exclude those rows before summing cost_basis as the business's "
            "own capital, the same way get_consignor_position already does "
            "for consignment value. Narrow with filters — the table is the "
            "largest in the system and results are capped."
        ),
        annotations=READ_ONLY,
    )
    def list_inventory(
        filters: list[str] | None = None,
        sort: str | None = None,
        limit: int = 100,
    ) -> str:
        return _json(
            admin_analytics.raw_inventory(
                repo, filters=filters, sort=sort, limit=limit
            )
        )

    @server.tool(
        name="list_consignors",
        description=(
            "Every consignor's identity and default payout_percent (THEIR "
            "share as a percent, e.g. 50 = 50% — the OPPOSITE convention "
            "from an item's ConsignmentTerms.split_percent, which is OUR "
            "cut as a 0-1 fraction). Do not use this to compute anyone's "
            "payout — call get_consignor_position for a correct, item-level "
            "projected split. Use this for identity/contact/archived-status "
            "questions."
        ),
        annotations=READ_ONLY,
    )
    def list_consignors(
        include_archived: bool = True,
        limit: int = 200,
    ) -> str:
        return _json(
            admin_analytics.raw_consignors(
                repo, include_archived=include_archived, limit=limit
            )
        )

    @server.tool(
        name="search_admin_docs",
        description=(
            "Search the admin operations knowledge base -- how admin-panel "
            "pages and buttons work, what they cost or how often to run "
            "them, and how displayed figures (e.g. the trade page's "
            "acquisition-ratio percent) are calculated. This is "
            "DOCUMENTATION, not live business data -- for actual numbers use "
            "the other tools. Pass query to search titles/keywords/body and "
            "get full article text back (capped at limit). Omit query (or "
            "pass an empty string) to get a lightweight browse index (id, "
            "category, title, summary -- no body) of every article; narrow "
            "with category, or call again with a query once you know what "
            "you're looking for."
        ),
        annotations=READ_ONLY,
    )
    def search_admin_docs(
        query: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> str:
        return _json(admin_docs.search(query=query, category=category, limit=limit))

    return server
