"""``/inventory`` router — the filter mode of the inventory search tool.

Loads the full inventory and applies the requested filters in-process (the
collection is small enough that this is simpler than per-filter queries).
Filters are applied cheapest-first — in-item fields (language, condition) before
filters that require a catalog lookup (set, name, rarity) — with ONE deliberate
exception: the price bound runs LAST. It is the only filter that reports what it
excluded (``hidden_no_price``), and that count is only honest when it is taken
against the cohort every other filter has already agreed on (Phase 12, owner
decision 2).
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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
    _market_price,
)
from merlins_collection.rate_limit import rate_limit_search
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Cards-only customer surface (RFC 0001 owner decision, binding): bulk lots are
# internal-only, and sealed products are hidden too — the search surfaces single
# cards, not booster packs. Only available raw/graded items reach a customer.
_CUSTOMER_KINDS = {"raw", "graded"}

# Phase 5 (D3, display scoping): only items physically stored in a
# customer-facing location (the glass display case or a toploader binder page)
# are shown. ``factory_sealed`` items (still in original plastic wrap — a
# condition premium, not a physical location) are also visible regardless of
# location. Items in storage, binders, or with no recorded location stay hidden.
_CUSTOMER_VISIBLE_LOCATIONS = frozenset({"glass", "toploader"})


def customer_visible_items(repo: InventoryRepository) -> list[InventoryItem]:
    """The ONE cohort every customer surface is allowed to show: available items
    of a customer-visible kind stored in a customer-visible location.

    This is a security boundary (leaking sold/held or bulk/sealed stock is the
    failure mode), so the predicate lives in exactly one place. Search, the authed
    dashboard summary, and the ANONYMOUS public featured endpoint all call this —
    a future exclusion (a ``needs_review`` gate, a new ``RESERVED`` status) is then
    made once here and can never drift on the public endpoint.

    The location gate (Phase 5, D3) ensures that only items in a display-ready
    location (glass case, toploader) or marked ``factory_sealed`` are surfaced.
    ``getattr`` is used because ``factory_sealed`` exists only on
    ``RawInventoryItem``; graded slabs must have a visible location.
    """
    return [
        i for i in repo.list_inventory()
        if i.kind in _CUSTOMER_KINDS
        and i.status == ItemStatus.AVAILABLE
        and (
            getattr(i, "location", None) in _CUSTOMER_VISIBLE_LOCATIONS
            or getattr(i, "factory_sealed", False)
        )
    ]


def _price(item) -> Decimal | None:
    """The price a price-range filter compares an item against, or ``None`` when
    the item has no known price at all.

    This is ``current_market_value`` outright — the denormalized projection of
    the ONE shared finish-aware helper (``models.inventory._market_price``),
    rewritten nightly by ``services.catalog_sync.refresh_inventory_market_values``.
    It used to prefer ``listed_price``, which is null on EVERY item by owner
    decision (Section 1/D3 — the sheet has no sticker prices and never will), so
    the preference was pure dead weight in front of the only field that carries a
    figure (claude-progress.txt Phase 12, Problem 2).

    ``None`` is NOT treated as zero and never matches a bound: a card whose price
    nobody knows cannot honestly be claimed to be under $500. The search counts
    those exclusions instead and reports them as ``hidden_no_price`` so they are
    surfaced rather than dropped invisibly (Phase 12, owner decision 2).
    """
    return item.current_market_value


def _apply_price_bounds(
    items: list[InventoryItem],
    min_price: Decimal | None,
    max_price: Decimal | None,
) -> tuple[list[InventoryItem], int]:
    """Filter ``items`` to those priced within the bounds; also return how many
    were dropped purely for having no resolvable price.

    With no bound set nothing is excluded and the count is 0 — a priceless item
    is perfectly displayable, it just cannot answer a question about its price.
    """
    if min_price is None and max_price is None:
        return items, 0
    kept: list[InventoryItem] = []
    hidden_no_price = 0
    for item in items:
        price = _price(item)
        if price is None:
            hidden_no_price += 1
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        kept.append(item)
    return kept, hidden_no_price


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
    # display_name is a sanitized name+number fallback for unmatched items (no
    # catalog card). It is MATERIALIZED at import time from the item's structured
    # Name + Card # columns (services.card_text.format_display_name), stored on the
    # row, and read verbatim here — never re-parsed from the free-text notes — so
    # it carries only name+number and no cost/location/free-text (see _enrich).
    "display_name",
    # value_note carries condition-adjustment and FX-conversion explanations
    # visible to the customer (Phase 19 visibility requirement).
    "value_note",
}


@router.get(
    "/search",
    response_model=InventorySearchResult,
    response_model_include={
        "total": True,
        "hidden_no_price": True,
        "items": {"__all__": _CUSTOMER_ITEM_FIELDS},
    },
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
    422. ``cost_basis`` (and every other internal field) is stripped from the
    response by the ``_CUSTOMER_ITEM_FIELDS`` allowlist via ``response_model_include``.

    A price bound excludes items with no known price and reports how many under
    ``hidden_no_price`` (Phase 12, owner decision 2), so the UI can say "N cards
    hidden (no price on file)" instead of an unexplained empty grid.
    """
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=422,
            detail="min_price must be <= max_price",
        )

    # Customers only ever see available items of customer-visible kinds.
    items = customer_visible_items(repo)
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

    # Price LAST, so `hidden_no_price` counts only what the bound itself hid —
    # not items some other filter had already ruled out (see the module docstring).
    items, hidden_no_price = _apply_price_bounds(items, min_price, max_price)

    # Enrich the surviving items with the catalog summary the UI renders.
    _load_catalog(repo, items, catalog)

    enriched = [
        _enrich(item, catalog.get(getattr(item, "card_id", None))) for item in items
    ]
    return InventorySearchResult(
        items=enriched, total=len(enriched), hidden_no_price=hidden_no_price,
    )


class InventorySummary(BaseModel):
    """Dashboard header stats over the customer-visible cohort. ``est_value`` is a
    ``Decimal`` serialized on the wire as a string (existing contract)."""

    cards_in_vault: int
    est_value: Decimal
    sets_tracked: int


@router.get("/summary", response_model=InventorySummary)
def inventory_summary(
    _user: AuthenticatedUser = Depends(rate_limit_search),
    repo: InventoryRepository = Depends(get_repo),
) -> InventorySummary:
    """Header stats for the authenticated dashboard, over the SAME cohort as
    ``/inventory/search`` (available raw/graded items).

    ``est_value`` resolves each item's price LIVE, through the same shared
    finish-aware helper the search results are rendered with
    (``models.inventory._market_price``), against the catalog batch this endpoint
    already fetches for ``sets_tracked``. Two reasons, both from the owner's bug
    report (Phase 12, Problem 3 / owner decision 1): the dashboard stays correct
    even when the nightly denormalizer has not run yet, and the header total can
    never disagree with the per-card prices rendered beneath it.

    The STORED ``current_market_value ?? listed_price`` is the fallback, used
    whenever the helper yields nothing — an item with no catalog card at all, and
    equally a graded slab, which by design gets NO catalog price (it has no finish
    and carries a grade premium the catalog does not know) and must keep its own
    manually-maintained figure. Items with no price from either source are
    skipped rather than counted as zero.

    ``sets_tracked`` counts the distinct catalog ``set_id`` among items whose
    ``card_id`` resolves in the catalog (NULL-``card_id`` items contribute none).

    This read is exactly as heavy as ``/inventory/search`` (a full sharded
    ``list_inventory`` fan-out + a catalog batch-get), so it reuses the SAME
    ``rate_limit_search`` cap — an ``InventoryStats`` remount storm can't drive
    unbounded scans. ``rate_limit_search`` still requires a valid token first
    (unauth → 401) and fails OPEN if the limiter itself is unreachable.
    """
    items = customer_visible_items(repo)

    card_ids = {i.card_id for i in items if getattr(i, "card_id", None)}
    catalog = repo.batch_get_catalog_cards(card_ids) if card_ids else {}
    sets_tracked = len({card.set_id for card in catalog.values()})

    est_value = Decimal(0)
    for i in items:
        card = catalog.get(getattr(i, "card_id", None))
        value = _market_price(card, getattr(i, "finish", None)) if card is not None else None
        if value is None:
            value = (i.current_market_value if i.current_market_value is not None
                     else i.listed_price)
        if value is not None:
            est_value += value

    return InventorySummary(
        cards_in_vault=len(items),
        est_value=est_value,
        sets_tracked=sets_tracked,
    )


# ---- /inventory/facets ----

class FacetSet(BaseModel):
    """A set option for the filter dropdown: id + human label."""
    id: str
    name: str


class InventoryFacets(BaseModel):
    """Distinct filterable values present among customer-visible inventory.

    Every dropdown in the filter panel sources its options from this endpoint
    rather than hardcoded constants (Phase 13). Values that appear in the DB
    but shouldn't be selectable (e.g. the literal string "None" as a rarity)
    are excluded at this layer.
    """
    sets: list[FacetSet]
    rarities: list[str]
    conditions: list[str]
    languages: list[str]


@router.get("/facets", response_model=InventoryFacets)
def inventory_facets(
    _user: AuthenticatedUser = Depends(rate_limit_search),
    repo: InventoryRepository = Depends(get_repo),
) -> InventoryFacets:
    """Distinct sets/rarities/conditions/languages among customer-visible items.

    Computed live from the inventory + catalog (same scan weight as /summary).
    The set dropdown needs both the id (for filtering) and a human label (the
    set name from the catalog), sorted alphabetically by name.
    """
    items = customer_visible_items(repo)

    # Collect distinct facet values from the items themselves.
    conditions: set[str] = set()
    languages: set[str] = set()
    card_ids: set[str] = set()
    for item in items:
        if hasattr(item, "condition"):
            conditions.add(item.condition.value)
        languages.add(item.language.value)
        cid = getattr(item, "card_id", None)
        if cid is not None:
            card_ids.add(cid)

    # Fetch catalog rows to get set names and rarities.
    catalog = repo.batch_get_catalog_cards(card_ids) if card_ids else {}
    sets_map: dict[str, str] = {}  # set_id -> set_name
    rarities: set[str] = set()
    for card in catalog.values():
        sets_map[card.set_id] = card.set_name
        if card.rarity and card.rarity != "None":
            rarities.add(card.rarity)

    # Sort sets alphabetically by name.
    sorted_sets = sorted(
        [FacetSet(id=sid, name=sname) for sid, sname in sets_map.items()],
        key=lambda s: s.name.lower(),
    )

    return InventoryFacets(
        sets=sorted_sets,
        rarities=sorted(rarities),
        conditions=sorted(conditions),
        languages=sorted(languages),
    )


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
    summary = (
        CardSummary.from_catalog(card, finish=getattr(item, "finish", None))
        if card is not None else None
    )
    data = item.model_dump()
    # The catalog name is authoritative when the item is matched; otherwise expose
    # the sanitized display_name that was materialized on the row at import time
    # (services.card_text.format_display_name). Reading the stored field rather than
    # re-parsing notes keeps the customer wire and the LLM context free of internal
    # free-text (Council MUST-FIX A). Sealed/bulk rows carry no display_name field,
    # so ``.get`` yields None for them.
    data["display_name"] = data.get("display_name") if card is None else None
    return _ENRICHED[item.kind](**data, card=summary)
