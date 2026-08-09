"""``/admin/slabs`` — slab intake support and the slab list (RFC 0009).

Five endpoints. ``GET /admin/slabs/certs/{cert}`` is the duplicate check a
barcode scan runs before staging a slab; ``GET /admin/slabs`` is the list of
graded stock joined to whatever market value each slab has; and T7 added the
pricing controls — ``POST /admin/slabs/refresh-prices`` with its
``/refresh-prices/status`` poll, and ``PUT /admin/slabs/{item_id}/price/pin``.

There is deliberately **no** ``/admin/slabs/lookup/{cert}``. RFC 0009 §7
specifies one, but PSA's public API 403s at the account level, so it would be a
mapper with nothing to map; intake is hand-entered and needs no such call.

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

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import GradingCompany, ItemStatus
from merlins_collection.services.card_text import admin_item_name
from merlins_collection.services.catalog_sync import (
    build_pricing_provider,
    refresh_graded_prices,
)
from merlins_collection.services.dynamodb import InventoryRepository

logger = logging.getLogger(__name__)

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
        # The list is where an operator decides what to protect, so it has to
        # show what is already protected.
        "price_pinned": bool(price_row.get("pinned")) if price_row else False,
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


# ---------------------------------------------------------------------------
# Refresh trigger (RFC 0009 T7)
# ---------------------------------------------------------------------------

# Run status, kept in a module-level dict rather than a datastore — the same
# single-worker assumption, and the same tradeoff, as the two dicts in
# ``routers/admin/market.py``. A SEPARATE dict from those on purpose: the raw
# price sync and the graded pass are different jobs against different vendors
# with different budgets, so one being in flight must not block or clobber the
# other's report.
_REFRESH_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "candidates": None,
    "priced": None,
    "skipped": None,
    "failures": None,
    "credits_remaining": None,
    "error": None,
}


def _run_slab_price_refresh(repo: InventoryRepository) -> None:
    """Background body: price every owned slab the day's budget reaches.

    Wrapped end to end, because a crash that left ``state`` on ``"running"``
    would 409 every future press of the button, permanently.

    A missing provider FAILS here rather than degrading quietly, which is the
    opposite of what ``run_daily_sync`` does with the same absence — and
    deliberately so. Nobody is watching the nightly job, so it degrades; a human
    pressed this, and telling them "completed" while nothing could possibly have
    been fetched is a lie they cannot see through.
    """
    try:
        provider = build_pricing_provider()
        if provider is None:
            raise RuntimeError(
                "No pricing provider is configured (POKEMONPRICETRACKER_API_KEY "
                "is unset), so no slab prices can be fetched."
            )
        summary = refresh_graded_prices(repo, provider)
        _REFRESH_STATUS.update({
            "state": "completed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "candidates": summary.get("graded_candidates", 0),
            "priced": summary.get("graded_priced", 0),
            "skipped": summary.get("graded_skipped", 0),
            "failures": summary.get("graded_failures", 0),
            "credits_remaining": summary.get("graded_credits_remaining"),
            "error": None,
        })
    except Exception as exc:  # noqa: BLE001 - report the failure, don't crash the worker
        # `str(exc)` only. Every exception this path can raise is built from our
        # own text or a class name — the pricing client is careful never to
        # construct one from the request — and this dict is served to a browser.
        _REFRESH_STATUS.update({
            "state": "failed",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
            "error": str(exc),
        })


@router.post("/refresh-prices", status_code=202)
def trigger_slab_price_refresh(
    background_tasks: BackgroundTasks,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, str]:
    """Kick off a graded price refresh; poll ``/refresh-prices/status``.

    Mirrors ``POST /admin/market/sync`` so the Market page's polling UI is the
    precedent the frontend reuses rather than a second pattern to learn.

    The 409 is not politeness here — it is money. Each run spends up to the whole
    day's credit budget, so a double-clicked button would buy the same prices
    twice and leave nothing for tonight's scheduled run.
    """
    if _REFRESH_STATUS["state"] == "running":
        raise HTTPException(status_code=409,
                            detail="A slab price refresh is already running")

    _REFRESH_STATUS.update({
        "state": "running",
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "finished_at": None,
        "candidates": None,
        "priced": None,
        "skipped": None,
        "failures": None,
        "credits_remaining": None,
        "error": None,
    })
    background_tasks.add_task(_run_slab_price_refresh, repo)
    return {"state": "started"}


@router.get("/refresh-prices/status")
def slab_price_refresh_status() -> dict[str, Any]:
    """Return the current (or most recent) refresh run's status."""
    return _REFRESH_STATUS


# ---------------------------------------------------------------------------
# Price pin (RFC 0009 T7)
# ---------------------------------------------------------------------------

class PricePinRequest(BaseModel):
    pinned: bool


@router.put("/{item_id}/price/pin")
def set_slab_price_pin(
    item_id: str = Path(..., max_length=64),
    body: PricePinRequest = ...,
    repo: InventoryRepository = Depends(get_repo),
) -> dict[str, Any]:
    """Protect this slab's graded price from the provider refresh, or release it.

    The owner's precedence decision (2026-08-09) is that a hand-typed price is
    NOT protected by default — the provider replaces it like any other. Pinning
    is the deliberate act that says otherwise, and without this endpoint that
    decision would silently collapse into "the provider always wins", which is
    the option the owner did not choose.

    Pinning does not touch the figure, its source or its ``updated_at``: it is
    not a re-pricing and must not appear on a chart as one.
    """
    item = repo.get_inventory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.kind != "graded":
        # Raw singles take their value from the catalog card and sealed products
        # from the item itself; neither has a `GRADEDPRICE#` row to pin.
        raise HTTPException(
            status_code=400,
            detail="Only graded slabs have a per-grade price to pin.",
        )
    if not item.card_id:
        raise HTTPException(
            status_code=404,
            detail="This slab is not linked to a catalog card, so it has no "
                   "price row to pin.",
        )

    if not repo.set_graded_price_pinned(item.card_id, item.company, item.grade,
                                        body.pinned):
        # Refusing to create the row is the point: a pin is a promise about a
        # specific figure, and there is no figure yet to promise anything about.
        raise HTTPException(
            status_code=404,
            detail="This slab has no stored price yet, so there is nothing to pin.",
        )

    return {
        "item_id": item.item_id,
        "card_id": item.card_id,
        "company": item.company.value,
        "grade": str(item.grade),
        "pinned": body.pinned,
    }
