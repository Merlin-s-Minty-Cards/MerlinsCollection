"""``/admin/slabs`` — slab intake support (RFC 0009).

One endpoint so far: the duplicate check a barcode scan runs before staging a
slab. It answers "do I already own this cert?" off the cert pointer row
(``services.dynamodb.get_item_id_by_cert``), which is a point read — this is
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

from fastapi import APIRouter, Depends, Path, Query

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import GradingCompany
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
