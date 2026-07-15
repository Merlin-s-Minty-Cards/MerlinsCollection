"""``/inventory`` router — the filter mode of the inventory search tool.

Loads the full inventory and applies the requested filters in-process (the
collection is small enough that this is simpler than per-filter queries).
Filters are applied cheapest-first: in-item fields (condition, price) before
filters that require a catalog lookup (set, name, rarity).
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from merlins_collection.dependencies import get_current_user, get_repo
from merlins_collection.models.auth import AuthenticatedUser
from merlins_collection.models.catalog import CatalogCard
from merlins_collection.models.inventory import (
    CardSummary,
    Condition,
    EnrichedGradedInventoryItem,
    EnrichedInventoryItem,
    EnrichedRawInventoryItem,
    InventoryItem,
    InventorySearchResult,
)
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get(
    "/search",
    response_model=InventorySearchResult,
    # cost_basis is internal purchase data — never expose it to customers
    response_model_exclude={"items": {"__all__": {"cost_basis"}}},
)
def search_inventory(
    name: str | None = Query(None, max_length=200),
    set_id: str | None = Query(None),
    rarity: str | None = Query(None),
    condition: Condition | None = Query(None),
    min_price: Decimal | None = Query(None),
    max_price: Decimal | None = Query(None),
    _user: AuthenticatedUser = Depends(get_current_user),
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
    # Catalog rows fetched along the way are kept for response enrichment.
    catalog: dict[str, CatalogCard | None] = {}

    # condition: raw items only; graded items are excluded when this filter is set
    if condition is not None:
        items = [i for i in items if i.kind == "raw" and i.condition == condition]

    if min_price is not None:
        items = [i for i in items if i.listed_price >= min_price]
    if max_price is not None:
        items = [i for i in items if i.listed_price <= max_price]

    # set_id: use the catalog GSI to get valid card_ids for the set
    if set_id is not None:
        set_cards = repo.list_cards_by_set(set_id)
        catalog.update({c.card_id: c for c in set_cards})
        set_card_ids = {c.card_id for c in set_cards}
        items = [i for i in items if i.card_id in set_card_ids]

    # name / rarity: require catalog lookup per remaining unique card_id
    if name is not None or rarity is not None:
        _load_catalog(repo, items, catalog)

        if name is not None:
            name_lower = name.lower()
            items = [
                i for i in items
                if catalog.get(i.card_id) is not None
                and name_lower in catalog[i.card_id].name.lower()
            ]
        if rarity is not None:
            items = [
                i for i in items
                if catalog.get(i.card_id) is not None
                and catalog[i.card_id].rarity == rarity
            ]

    # Enrich the surviving items with the catalog summary the UI renders.
    _load_catalog(repo, items, catalog)

    enriched = [_enrich(item, catalog.get(item.card_id)) for item in items]
    return InventorySearchResult(items=enriched, total=len(enriched))


def _load_catalog(
    repo: InventoryRepository,
    items: list[InventoryItem],
    catalog: dict[str, CatalogCard | None],
) -> None:
    """Batch-fetch catalog rows for any item not already in ``catalog``.

    Missing ids are recorded as ``None`` so they are never re-fetched.
    """
    missing = {i.card_id for i in items} - catalog.keys()
    if not missing:
        return
    found = repo.batch_get_catalog_cards(missing)
    catalog.update(found)
    catalog.update(dict.fromkeys(missing - found.keys()))


def _enrich(item: InventoryItem, card: CatalogCard | None) -> EnrichedInventoryItem:
    summary = CardSummary.from_catalog(card) if card is not None else None
    data = item.model_dump()
    if item.kind == "raw":
        return EnrichedRawInventoryItem(**data, card=summary)
    return EnrichedGradedInventoryItem(**data, card=summary)
