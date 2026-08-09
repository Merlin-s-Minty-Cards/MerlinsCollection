"""``/admin/slabs`` — slab intake support and the slab list (RFC 0009).

Two endpoints. ``GET /admin/slabs/certs/{cert}`` is the duplicate check a
barcode scan runs before staging a slab; ``GET /admin/slabs`` is the list of
graded stock joined to whatever market value each slab has.

The duplicate check answers "do I already own this cert?" off the cert pointer
row (``services.dynamodb.get_item_id_by_cert``), which is a point read — this is
deliberately not a search over inventory.

**"Not owned" is a 200, not a 404.** It is the normal answer to an ordinary
scan; a 404 would make every clean intake look like an error to the frontend and
would be indistinguishable from a mistyped route.

The answer is a WARNING, never a gate (RFC 0009 §9): a slab you sold and bought
back is a legitimate re-entry, so the caller is told what it is about to
re-acquire and decides for itself.

No auth dependency is declared here on purpose — ``admin_router`` already carries
``Depends(require_admin)``, so declaring it again would run the check twice.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import GradingCompany, ItemStatus
from merlins_collection.services.card_text import admin_item_name
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/slabs", tags=["admin-slabs"])

# The cert becomes part of a DynamoDB partition key, which is capped at 2048
# bytes. Bounded here so a long paste into the always-focused scan bar is a 422
# rather than a ValidationException surfacing as a 500. Real PSA certs are 8-9
# digits, so this is generous.
_MAX_CERT_LENGTH = 64


@router.get("/certs/{cert_number}")
def check_cert_owned(
    cert_number: str = Path(..., max_length=_MAX_CERT_LENGTH),
    company: GradingCompany = Query(GradingCompany.PSA),
    repo: InventoryRepository = Depends(get_repo),
) -> dict:
    """Report whether a cert is already on the shelf, and as what.

    Returns only what a duplicate warning needs — id, status and a name. The item
    is deliberately not dumped wholesale: ``cost_basis`` and the rest of the
    purchase data have no business riding along on a scan-time check.
    """
    item_id = repo.get_item_id_by_cert(company, cert_number)
    if item_id is None:
        return {"owned": False}

    item = repo.get_inventory_item(item_id)
    if item is None:  # deleted between the pointer read and here
        return {"owned": False}

    # Slabs rarely carry a display name, so fall back to the catalog. A duplicate
    # warning that names no card is not much of a warning.
    name = admin_item_name(item)
    card_id = getattr(item, "card_id", None)  # sealed/bulk kinds have none
    if not name and card_id:
        card = repo.get_catalog_card(card_id)
        if card:
            name = card.name

    return {
        "owned": True,
        "item_id": item.item_id,
        "status": item.status.value,
        "name": name,
    }


# ---------------------------------------------------------------------------
# The slab list
# ---------------------------------------------------------------------------

class SlabListResponse(BaseModel):
    """``items`` is the requested page; ``total`` counts every match.

    The two differ whenever ``limit`` bites, and they are reported separately on
    purpose — "showing 50 of 214" is a different statement from "you own 50".
    """

    items: list[dict[str, Any]]
    total: int


# Generous, but bounded: the list renders card art per row and an unbounded page
# is an unbounded image fan-out.
_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000


@router.get("", response_model=SlabListResponse)
def list_slabs(
    company: GradingCompany | None = Query(None),
    grade: str | None = Query(None, max_length=8),
    status: ItemStatus | None = Query(None),
    # `true` = only slabs that HAVE a value, `false` = only those that do not,
    # omitted = both. The `false` case is the worklist: after the verified-join
    # rule an unpriced slab is not flagged into Triage (owner's decision,
    # 2026-08-08), so this list is the only place it surfaces.
    priced: bool | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    repo: InventoryRepository = Depends(get_repo),
) -> SlabListResponse:
    """Every graded item, joined to its per-grade market value.

    Reuses ``list_inventory`` — the same shard fan-out the admin inventory
    search runs, which is a bounded set of Queries and NOT a table scan
    (CLAUDE.md Ops). A third search implementation was the alternative and would
    have been a third place for the filters to drift.
    """
    wanted_grade = _parse_grade(grade)

    items = [i for i in repo.list_inventory() if i.kind == "graded"]

    if company is not None:
        items = [i for i in items if i.company == company]
    if wanted_grade is not None:
        # Compared as Decimals, not strings: `9.5`, `9.50` and `09.5` are one
        # grade, and the storage key normalizes them together too.
        items = [i for i in items if i.grade == wanted_grade]
    if status is not None:
        items = [i for i in items if i.status == status]

    # Newest first — intake is the reason this page exists, so what was just
    # entered should be at the top. Item ids are ULIDs, so they sort by time.
    items.sort(key=lambda i: i.item_id, reverse=True)

    price_cache: dict[tuple[str, str, str], dict | None] = {}
    name_cache: dict[str, str | None] = {}
    rows = [_slab_row(item, repo, price_cache, name_cache) for item in items]

    if priced is not None:
        rows = [r for r in rows if (r["market_value"] is not None) is priced]

    return SlabListResponse(items=rows[:limit], total=len(rows))


def _parse_grade(raw: str | None) -> Decimal | None:
    """``"9.5"`` -> ``Decimal("9.5")``; a non-number is a 422, never a 500."""
    if raw is None or raw == "":
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        raise HTTPException(
            status_code=422, detail=f"Invalid grade '{raw}'. Expected a number."
        ) from None
    # `Decimal("nan")` and `Decimal("inf")` both PARSE. Left alone they compare
    # unequal to every real grade and the caller gets a silently empty list,
    # which reads as "you own no PSA 10s" rather than "that is not a grade".
    if not parsed.is_finite():
        raise HTTPException(
            status_code=422, detail=f"Invalid grade '{raw}'. Expected a number."
        )
    return parsed


def _slab_row(item, repo: InventoryRepository, price_cache: dict,
              name_cache: dict) -> dict[str, Any]:
    """One list row: the item's own fields plus where its value came from.

    A slab with no ``card_id`` is a first-class row with a null value, not an
    omission. It is real inventory that was really paid for, and after the
    verified-join rule it is the ORDINARY state of a Japanese slab (every JP
    card in T0's sample lacked the ``externalCatalogId`` the join needs), so
    dropping these would drop most of the JP shelf from the one page that exists
    to show it.
    """
    price_row = None
    if item.card_id:
        key = (item.card_id, str(item.company), str(item.grade))
        if key not in price_cache:
            price_cache[key] = repo.get_graded_price_row(
                item.card_id, item.company, item.grade
            )
        price_row = price_cache[key]

    market_value = price_row.get("market_value") if price_row else None

    return {
        "item_id": item.item_id,
        "card_id": item.card_id,
        "name": _slab_name(item, repo, name_cache),
        "cert_number": item.cert_number,
        "company": item.company.value,
        "grade": str(item.grade),
        "grade_label": item.grade_label,
        "cost_basis": str(item.cost_basis),
        "status": item.status.value,
        "location": item.location,
        "language": item.language.value,
        # Serialized as strings so a Decimal survives JSON without being turned
        # into a float on the way out — the same reason every other money field
        # on the admin surface is a string.
        "market_value": str(market_value) if market_value is not None else None,
        "value_as_of": price_row.get("updated_at") if price_row else None,
        "price_source": price_row.get("source") if price_row else None,
        "value_confidence": price_row.get("confidence") if price_row else None,
        "price_source_id": item.price_source_id,
    }


def _slab_name(item, repo: InventoryRepository, cache: dict) -> str | None:
    """The effective name, through the one helper (CLAUDE.md).

    ``admin_item_name`` already implements ``display_name_override`` outranking
    everything; the catalog fallback below is the same one the cert check uses,
    and it matters more here — slabs rarely carry a ``display_name``, so without
    it most of this list would be nameless rows.
    """
    name = admin_item_name(item)
    if name or not item.card_id:
        return name or None
    if item.card_id not in cache:
        card = repo.get_catalog_card(item.card_id)
        cache[item.card_id] = card.name if card else None
    return cache[item.card_id]
