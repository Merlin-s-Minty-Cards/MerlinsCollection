"""``/admin/triage`` — the outstanding-work count behind the sidebar badge.

Deliberately the ONLY route here. The Triage list itself is
``GET /admin/inventory/search?triage=true``, not a parallel list endpoint, so
the page inherits sorting, the catalog join and every existing filter for free
(docs/plans/rfc-0008/t11-triage-tab.md, "Endpoints: reuse before adding").

Both this and the list read the same predicates from ``services.triage``. A
badge that counts differently from the page it links to is worse than no badge.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.services.dynamodb import InventoryRepository
from merlins_collection.services.triage import count_by_reason, needs_triage

router = APIRouter(prefix="/triage", tags=["admin-triage"])


class TriageCounts(BaseModel):
    """Outstanding triage work.

    ``total`` counts CARDS; ``reasons`` counts REASON HITS and the two do not
    reconcile, because an item can qualify under several reasons at once. That
    is intentional and load-bearing: the badge must show "4 things to fix", not
    the sum of overlapping reasons, or it sends the admin hunting for cards that
    are not in the list.
    """

    total: int
    reasons: dict[str, int]


@router.get("/counts", response_model=TriageCounts)
def triage_counts(repo: InventoryRepository = Depends(get_repo)) -> TriageCounts:
    """Per-reason counts plus the distinct-item total.

    A full inventory read per call, and ``AdminShell`` renders on every admin
    page. At the current scale (hundreds of items) that is genuinely cheap, and
    caching it would reintroduce the staleness the badge exists to prevent — a
    cleared item still showing in the count. See follow-ups.md (T11) before
    reaching for a cache.
    """
    items = repo.list_inventory()
    return TriageCounts(
        total=sum(1 for i in items if needs_triage(i)),
        reasons=count_by_reason(items),
    )
