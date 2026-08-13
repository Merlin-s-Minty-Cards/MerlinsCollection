"""``/admin/unmatched`` — ranked pairing suggestions for the parked cohort.

Deliberately the ONLY route here, on the same reasoning as ``admin/triage.py``:
the unmatched **list** is ``GET /admin/inventory/search?no_catalog_match=true``
(RFC 0011 T5), so the queue page inherits sorting, filtering and the catalog join
for free. This endpoint adds only what that list cannot compute — the ranked
candidates, and the one number the dashboard widget quotes.

**Suggestions never replace full-catalog search** (owner, 2026-08-13: *"you must
also have the option for the user to search the whole catalog if none of those
candidates match"*). That half is the queue page's; this endpoint must not become
the only door.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from merlins_collection.dependencies import get_repo
from merlins_collection.services import catalog_cache
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.pairing import (
    PairingIndex,
    SuggestionsResponse,
    build_pairing_index,
    suggestions_for,
)

router = APIRouter(prefix="/unmatched", tags=["admin-unmatched"])


def _parked_first_waiting_longest(item):
    """Oldest park first; a row with no stamp sorts last rather than crashing.

    Same order the queue page sorts by, so the two never disagree about which
    card has been waiting longest. ``no_catalog_match_at`` is server-stamped, but
    a row written before T5 existed can still be parked with no stamp.
    """
    stamped = getattr(item, "no_catalog_match_at", None)
    return (stamped is None, stamped)


@router.get("/suggestions", response_model=SuggestionsResponse)
def unmatched_suggestions(
    limit: int = Query(3, ge=1, le=10),
    repo: InventoryRepository = Depends(get_repo),
) -> SuggestionsResponse:
    """Ranked catalog candidates for every parked item.

    Scoped to the parked cohort (``no_catalog_match=True``), which is tens of
    rows. The catalog comes from ``catalog_cache`` (~93 MB resident, RFC 0008 T9),
    so this is an in-memory join rather than 31,603 reads per item — and the index
    is built **once per request**, never once per item.

    The catalog is not read at all when nothing is parked: on the overwhelmingly
    common empty-queue case there is nothing to join against, and a cold cache
    would otherwise pay for an 11-second full-table scan to answer "no work".

    ``ge=1, le=10`` on ``limit``: unbounded, one request becomes a full
    cross-product of the queue against the catalog.

    **The pricing provider is never called here** — it is metered at fifty lookups
    a day and a page load must not spend them. Every price on a candidate is a
    catalog figure already on the row.
    """
    parked = sorted(
        (i for i in repo.list_inventory() if getattr(i, "no_catalog_match", False)),
        key=_parked_first_waiting_longest,
    )
    index = (
        build_pairing_index(catalog_cache.get_catalog_cards(repo.list_all_catalog_cards))
        if parked
        else PairingIndex()
    )
    return suggestions_for(parked, index, limit=limit)
