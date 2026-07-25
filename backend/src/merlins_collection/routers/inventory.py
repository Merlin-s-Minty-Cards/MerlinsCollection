"""``/inventory`` router — the filter mode of the inventory search tool.

Loads the full inventory and applies the requested filters in-process (the
collection is small enough that this is simpler than per-filter queries).
Filters are applied cheapest-first: in-item fields (condition, price) before
filters that require a catalog lookup (set, name, rarity).
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from merlins_collection.dependencies import get_repo
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import (
    CardSummary,
    Condition,
    EnrichedBulkInventoryItem,
    EnrichedGradedInventoryItem,
    EnrichedInventoryItem,
    EnrichedRawInventoryItem,
    EnrichedSealedInventoryItem,
    InventoryItem,
    InventorySearchResult,
    ItemStatus,
    Language,
)
from merlins_collection.rate_limit import rate_limit_search
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Bulk lots are internal-only; everything else shows when it's available.
_CUSTOMER_KINDS = {"raw", "graded", "sealed"}


def _price(item) -> Decimal | None:
    """The price a filter compares against: sticker first, market as fallback."""
    return item.listed_price if item.listed_price is not None else item.current_market_value


# Allowlist of the ONLY fields a customer may see on a search result (mirrors the
# frontend contract + the MCP toCard discipline). Everything else — cost_basis,
# consignment terms, needs_review, location (physical whereabouts),
# market_value_at_purchase, acquired_show_id, notes, tcg_url — is internal and
# must never reach the wire. An allowlist (not a denylist) means a field added to
# the model later defaults to hidden rather than silently leaking.
_CUSTOMER_ITEM_FIELDS = {
    "item_id", "kind", "card_id", "listed_price", "current_market_value",
    "acquired_at", "finish", "condition", "condition_modifier", "factory_sealed",
    "company", "grade", "cert_number", "product_name", "product_type", "card",
    # language (EN/JP) is a deliberate, owner-approved customer-facing exposure:
    # a JP print is a different card at a different price, so buyers must be able
    # to tell an English and a Japanese copy apart.
    "language",
}


@router.get(
    "/search",
    response_model=InventorySearchResult,
    response_model_include={"total": True, "items": {"__all__": _CUSTOMER_ITEM_FIELDS}},
)
def search_inventory(
    name: str | None = Query(None, max_length=200),
    set_id: str | None = Query(None),
    rarity: str | None = Query(None),
    condition: Condition | None = Query(None),
    min_price: Decimal | None = Query(None),
    max_price: Decimal | None = Query(None),
    language: Language | None = Query(None),
    _user: AuthenticatedUser = Depends(rate_limit_search),
    repo: InventoryRepository = Depends(get_repo),
) -> InventorySearchResult:
    """Return inventory matching the given filters (all optional, AND-combined).

    ``condition`` selects raw cards only (graded items are excluded when it's
    set). An inverted price range (``min_price > max_price``) is rejected with
    422. ``cost_basis`` is stripped from the response by ``response_model_exclude``.
    """
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=422,
            detail="min_price must be <= max_price",
        )

    items = repo.list_inventory()
    # Customers only ever see available items of customer-visible kinds.
    items = [
        i for i in items
        if i.kind in _CUSTOMER_KINDS and i.status == ItemStatus.AVAILABLE
    ]
    # Catalog rows fetched along the way are kept for response enrichment.
    catalog: dict[str, CatalogCard | None] = {}

    # language: an in-item field (defaults EN for records written before the
    # field existed). Applied on its own it must still return JP items, which
    # carry card_id=None by design and so never survive the name/set/rarity
    # filters — hence it AND-combines here rather than via the catalog.
    if language is not None:
        items = [i for i in items if i.language == language]

    # condition: raw items only; graded items are excluded when this filter is set.
    # The tier alone is compared, so LP matches LP+ / LP / LP-.
    if condition is not None:
        items = [i for i in items if i.kind == "raw" and i.condition == condition]

    if min_price is not None:
        items = [i for i in items if _price(i) is not None and _price(i) >= min_price]
    if max_price is not None:
        items = [i for i in items if _price(i) is not None and _price(i) <= max_price]

    # set_id: use the catalog GSI to get valid card_ids for the set
    if set_id is not None:
        set_cards = repo.list_cards_by_set(set_id)
        catalog.update({c.card_id: c for c in set_cards})
        set_card_ids = {c.card_id for c in set_cards}
        items = [i for i in items if getattr(i, "card_id", None) in set_card_ids]

    # name / rarity: require catalog lookup per remaining unique card_id
    if name is not None or rarity is not None:
        _load_catalog(repo, items, catalog)

        if name is not None:
            name_lower = name.lower()
            items = [
                i for i in items
                if catalog.get(getattr(i, "card_id", None)) is not None
                and name_lower in catalog[i.card_id].name.lower()
            ]
        if rarity is not None:
            items = [
                i for i in items
                if catalog.get(getattr(i, "card_id", None)) is not None
                and catalog[i.card_id].rarity == rarity
            ]

    # Enrich the surviving items with the catalog summary the UI renders.
    _load_catalog(repo, items, catalog)

    enriched = [
        _enrich(item, catalog.get(getattr(item, "card_id", None))) for item in items
    ]
    return InventorySearchResult(items=enriched, total=len(enriched))


def _load_catalog(
    repo: InventoryRepository,
    items: list[InventoryItem],
    catalog: dict[str, CatalogCard | None],
) -> None:
    """Batch-fetch catalog rows for any item not already in ``catalog``.

    Missing ids are recorded as ``None`` so they are never re-fetched.
    """
    missing = {
        card_id
        for i in items
        if (card_id := getattr(i, "card_id", None)) is not None
    } - catalog.keys()
    if not missing:
        return
    found = repo.batch_get_catalog_cards(missing)
    catalog.update(found)
    catalog.update(dict.fromkeys(missing - found.keys()))


_ENRICHED = {
    "raw": EnrichedRawInventoryItem,
    "graded": EnrichedGradedInventoryItem,
    "sealed": EnrichedSealedInventoryItem,
    "bulk": EnrichedBulkInventoryItem,
}


def _enrich(item: InventoryItem, card: CatalogCard | None) -> EnrichedInventoryItem:
    summary = CardSummary.from_catalog(card) if card is not None else None
    return _ENRICHED[item.kind](**item.model_dump(), card=summary)
