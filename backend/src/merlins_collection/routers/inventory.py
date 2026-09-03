"""``/inventory`` router — the filter mode of the inventory search tool.

Loads the full inventory and applies the requested filters in-process (the
collection is small enough that this is simpler than per-filter queries).
Filters are applied cheapest-first — in-item fields (language, condition) before
filters that require a catalog lookup (set, name, rarity) — with ONE deliberate
exception: the price bound runs LAST, after catalog enrichment. Two reasons:

- It is the only filter that reports what it excluded (``hidden_no_price``), and
  that count is only honest when it is taken against the cohort every other
  filter has already agreed on (Phase 12, owner decision 2).
- It compares against ``_display_price`` — the price the customer actually sees
  on the tile — which is only resolvable once ``_enrich`` has attached the live
  catalog row. Filtering before enrichment would leave every ``item.card`` unset
  (RFC 0008 §A; see ``_display_price``).
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
    ConditionModifier,
    EnrichedBulkInventoryItem,
    EnrichedGradedInventoryItem,
    EnrichedInventoryItem,
    EnrichedRawInventoryItem,
    EnrichedSealedInventoryItem,
    InventoryItem,
    InventorySearchResult,
    Language,
    normalize_condition,
)
from merlins_collection.rate_limit import rate_limit_search
from merlins_collection.services.condition_pricing import apply_condition_adjustment
from merlins_collection.services.customer_visibility import is_customer_visible
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/inventory", tags=["inventory"])


def customer_visible_items(repo: InventoryRepository) -> list[InventoryItem]:
    """The ONE cohort every customer surface is allowed to show: available items
    of a customer-visible kind stored in a customer-visible location.

    This is a security boundary (leaking sold/held or bulk/sealed stock is the
    failure mode), so the per-item predicate lives in exactly one place —
    ``services/customer_visibility.py::is_customer_visible`` — which
    ``services/bedrock.py``'s chat display hydration also calls (RFC 0016
    Council r1 checklist item 2). Search, the authed dashboard summary, the
    ANONYMOUS public featured endpoint, and chat all call through here or
    directly through that predicate — a future exclusion (a ``needs_review``
    gate, a new ``RESERVED`` status) is then made once and can never drift on
    any one of them.
    """
    return [i for i in repo.list_inventory() if is_customer_visible(i)]


def _display_price(item: EnrichedInventoryItem) -> Decimal | None:
    """THE price of an item, and the only one any customer-facing code may use.

    This is the single authority for the price **filter** and the price
    **sort**. It used to also be described as "the figure the tile renders";
    that changed under RFC 0025 T2 (`GET /inventory/search`'s wire shape is
    otherwise unchanged — the frontend's own price rendering is a separate
    concern this RFC does not touch).

    **RFC 0025: this is ``sticker_price`` — the price the business actually
    sells the card at**, set by hand with the card and its condition in front
    of the person setting it. Before this it read a live catalog market
    figure (condition-adjusted at enrichment), falling back to the
    permanently-dead ``listed_price``; that was an ESTIMATE of what the card
    is worth, not what it sells for, and the owner's framing was exact:
    "sticker price is essentially the price we sell the cards at." History
    kept below the line for why the OLD contract existed, in case a future
    reader wonders — not because any of it still applies to this field.

    Old history: the bound used to read ``current_market_value``
    (denormalized nightly, therefore stale between runs) while the sort and
    the tile both read the live ``card.market_price`` — the owner reported
    the consequence, a Rayquaza displaying $517 that still passed
    ``max_price=500`` because its stale value had been ≤ 500 at the last sync
    (RFC 0008 §A). **They must never diverge again**: change this function,
    not a caller.

    Requires an ENRICHED item for signature compatibility with existing
    callers (``item.card`` is populated by ``_enrich``), though it is no
    longer read here.

    **There is no fallback.** ``is_customer_visible`` already guarantees a
    visible item has a sticker price, so ``None`` here means a caller is
    asking about an item it should never have been holding — not a
    resolvable-elsewhere gap. ``hidden_no_price`` (see ``_apply_price_bounds``)
    is therefore now structurally always ``0``; it stays in the response and
    the counting code stays live as a tripwire rather than being deleted for
    a false economy.
    """
    return item.sticker_price


def _apply_price_bounds(
    items: list[EnrichedInventoryItem],
    min_price: Decimal | None,
    max_price: Decimal | None,
) -> tuple[list[EnrichedInventoryItem], int]:
    """Filter ENRICHED ``items`` to those priced within the bounds; also return
    how many were dropped purely for having no resolvable price.

    With no bound set nothing is excluded and the count is 0 — a priceless item
    is perfectly displayable, it just cannot answer a question about its price.
    """
    if min_price is None and max_price is None:
        return items, 0
    kept: list[EnrichedInventoryItem] = []
    hidden_no_price = 0
    for item in items:
        price = _display_price(item)
        if price is None:
            hidden_no_price += 1
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        kept.append(item)
    return kept, hidden_no_price


# Condition display vocabulary, best-to-worst. Mirrors the frontend's
# ``CONDITION_OPTIONS`` (``frontend/lib/constants.ts``) — the order a collector
# expects in a dropdown, which alphabetical sorting mangles into LP, LP+, LP-.
_CONDITION_ORDER = ("NM", "LP+", "LP", "LP-", "MP", "HP", "DMG")
_CONDITION_RANK = {value: rank for rank, value in enumerate(_CONDITION_ORDER)}


def _condition_display(item: InventoryItem) -> str:
    """Combine an item's two stored condition fields into the one string every
    human-facing surface speaks (``LP`` + ``+`` -> ``LP+``).

    The inverse of ``models.inventory.normalize_condition``, and the server-side
    mirror of the frontend's ``formatCondition``. Storage stays two fields —
    there is deliberately no combined ``"LP+"`` member on the ``Condition`` enum
    (that was the Round 1 bug; see CLAUDE.md).
    """
    modifier = getattr(item, "condition_modifier", None)
    return f"{item.condition.value}{modifier.value if modifier else ''}"


def _parse_condition_query(value: str) -> tuple[Condition, ConditionModifier | None]:
    """Parse a ``condition`` query value, 422-ing instead of 500-ing on garbage.

    The param used to be typed ``Condition``, which made ``LP+``/``LP-`` — the
    very values ``/inventory/facets`` now offers in its dropdown — a validation
    error the customer could not recover from (RFC 0008 §B).

    Deliberately delegates to the same ``normalize_condition`` as the admin
    router's identically-named helper, so the two surfaces can never drift into
    accepting different dialects.
    """
    try:
        return normalize_condition(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid condition '{value}'. Expected one of {', '.join(_CONDITION_ORDER)}.",
        ) from exc


# Allowlist of the ONLY fields a customer may see on a search result (mirrors the
# frontend contract + the MCP toCard discipline). Everything else — cost_basis,
# consignment terms, needs_review, location (physical whereabouts),
# market_value_at_purchase, acquired_show_id, notes, tcg_url — is internal and
# must never reach the wire. An allowlist (not a denylist) means a field added to
# the model later defaults to hidden rather than silently leaking.
_CUSTOMER_ITEM_FIELDS = {
    "item_id", "kind", "card_id", "listed_price", "current_market_value",
    "acquired_at", "finish", "condition", "condition_modifier", "factory_sealed",
    # Descriptive tags — "1st Edition", "Full Art" — that are genuinely not
    # mutually exclusive with `finish` (RFC 0023 §2.2). CUSTOMER-FACING by
    # design: this describes the physical card, the opposite call from
    # `language_note`/`review_reason`, which describe our own handling of
    # the record and stay internal.
    "finish_attributes",
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
    # display_name_override is the ONE customer-facing name field that is FREE
    # TEXT typed by an admin — the "never derived from notes" guarantee above
    # covers display_name and does NOT extend to this. It exists so a Japanese
    # card whose catalog row is in Japanese script can be shown under a name the
    # customer can read, which means a human decides its contents and a human is
    # therefore responsible for not typing a consignor name or a cost into it.
    # Bounded at the model (200 chars) because it reaches customers, and blank
    # is normalized to None so an empty edit falls back to the catalog name.
    # See docs/plans/rfc-0008/t10-jp-english-names.md.
    "display_name_override",
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
    # Typed ``str``, not ``Condition``: the accepted vocabulary is the COMBINED
    # display form (``NM``/``LP+``/``LP``/…), which the bare-tier enum rejects.
    # Length-capped because the value is echoed back in the 422 detail.
    condition: str | None = Query(None, max_length=8),
    min_price: Decimal | None = Query(None),
    max_price: Decimal | None = Query(None),
    language: Language | None = Query(None),
    sort: str | None = Query(None),
    _user: AuthenticatedUser = Depends(rate_limit_search),
    repo: InventoryRepository = Depends(get_repo),
) -> InventorySearchResult:
    """Return inventory matching the given filters (all optional, AND-combined).

    ``condition`` selects raw cards only (graded items are excluded when it's
    set) and takes the combined display form: a bare tier (``LP``) means the
    WHOLE tier including ``LP+``/``LP-``, while naming a modifier (``LP+``)
    narrows to exactly that grade. Anything else is a 422 rather than a silent
    empty result. An inverted price range (``min_price > max_price``) is rejected
    with 422. ``cost_basis`` (and every other internal field) is stripped from the
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
    if condition is not None:
        tier, modifier = _parse_condition_query(condition)
        items = [
            i for i in items
            if i.kind == "raw"
            and i.condition == tier
            # A bare tier ("LP") is the whole tier including LP+/LP-; a query
            # that names a modifier ("LP+") narrows to exactly that grade.
            and (modifier is None or i.condition_modifier == modifier)
        ]

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

    # Enrich with the catalog summary the UI renders. This runs BEFORE the price
    # bound, not after: the bound compares against `_display_price`, which reads
    # the live `item.card.market_price` that only `_enrich` attaches. Filter the
    # unenriched list and every card falls back to the permanently-null
    # `listed_price`, silently burying the whole vault in `hidden_no_price`.
    _load_catalog(repo, items, catalog)
    enriched = [
        _enrich(item, catalog.get(getattr(item, "card_id", None))) for item in items
    ]

    # Price LAST, so `hidden_no_price` counts only what the bound itself hid —
    # not items some other filter had already ruled out (see the module docstring).
    enriched, hidden_no_price = _apply_price_bounds(enriched, min_price, max_price)

    # Sort (Phase 14). Priceless items always sort last regardless of direction.
    enriched = _sort_results(enriched, sort)

    return InventorySearchResult(
        items=enriched, total=len(enriched), hidden_no_price=hidden_no_price,
    )


class InventorySummary(BaseModel):
    """Dashboard header stats over the customer-visible cohort.

    RFC 0025 T5 removed ``est_value`` (the owner asked for the estimated-value
    widget to be removed from the dashboard, not merely relabeled) — this also
    deleted the expensive part of this endpoint: a live, per-item catalog price
    resolution plus a condition-adjustment pass. ``cards_in_vault`` and
    ``sets_tracked`` are unaffected; both were always cheap counts over the
    same ``customer_visible_items`` walk and the same catalog batch-get.
    """

    cards_in_vault: int
    sets_tracked: int


@router.get("/summary", response_model=InventorySummary)
def inventory_summary(
    _user: AuthenticatedUser = Depends(rate_limit_search),
    repo: InventoryRepository = Depends(get_repo),
) -> InventorySummary:
    """Header stats for the authenticated dashboard, over the SAME cohort as
    ``/inventory/search`` (available raw/graded items).

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

    return InventorySummary(
        cards_in_vault=len(items),
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
            # The COMBINED grade (`LP+`), not the bare tier: LP+, LP and LP- are
            # three different grades at three different prices, and emitting only
            # the tier made the dropdown structurally incapable of offering the
            # other two no matter what was in stock (RFC 0008 §B).
            conditions.add(_condition_display(item))
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
        # Best-to-worst, NOT alphabetical — `sorted()` yields LP, LP+, LP-, which
        # is nonsense to a collector. An unranked value (shouldn't happen) sorts
        # last rather than crashing the dropdown.
        conditions=sorted(
            conditions,
            key=lambda c: (_CONDITION_RANK.get(c, len(_CONDITION_ORDER)), c),
        ),
        languages=sorted(languages),
    )


# ---- Sorting (Phase 14) ----

# Allowed sort values. An unrecognized value falls back to the default (newest).
_ALLOWED_SORTS = frozenset({
    "newest", "oldest", "price_desc", "price_asc", "name_asc", "name_desc",
})

_PRICE_SENTINEL_HIGH = Decimal("999999999")  # priceless items sort LAST in both directions


def _sort_results(items: list, sort: str | None) -> list:
    """Sort enriched items in place. Priceless items always sort last.

    ``sort=None`` or an unrecognized value defaults to ``newest`` (most recently
    acquired first), which is the natural order for a collector browsing new stock.

    Price sorts use the DISPLAY price — the same derivation the frontend tile
    renders — so the visual order matches the numbers on screen. Previously this
    used ``current_market_value`` (a nightly-denormalized field) which diverges
    from the live ``card.market_price`` computed at response time, causing items
    to appear out of order.
    """
    if sort is None or sort not in _ALLOWED_SORTS:
        sort = "newest"

    if sort == "newest":
        items.sort(key=lambda i: i.acquired_at, reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda i: i.acquired_at)
    elif sort == "price_desc":
        items.sort(key=lambda i: (
            0 if _display_price(i) is not None else 1,
            -(_display_price(i) or Decimal(0)),
        ))
    elif sort == "price_asc":
        items.sort(key=lambda i: (
            0 if _display_price(i) is not None else 1,
            _display_price(i) or _PRICE_SENTINEL_HIGH,
        ))
    elif sort == "name_asc":
        items.sort(key=lambda i: (i.card.name if i.card else i.display_name or "").lower())
    elif sort == "name_desc":
        items.sort(
            key=lambda i: (i.card.name if i.card else i.display_name or "").lower(),
            reverse=True,
        )

    return items


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


def _condition_adjust(
    summary: CardSummary | None, item: InventoryItem,
) -> tuple[CardSummary | None, str | None]:
    """Scale a raw card's catalog price by its condition multiplier.

    The catalog relays ONE market figure per finish and that figure is a Near
    Mint price. Applying the multiplier here — at enrichment, on the summary the
    customer receives — is what makes the tile, the sort and the price bound all
    show a DMG card at 0.15x instead of the NM figure. Before this, a DMG card
    was displayed to a buyer at ~6.7x what the business itself valued it at, and
    the error ran in the business's favour (RFC 0008 follow-up, T1 row 1; owner
    decision 2026-08-06).

    **Applied in exactly one place, deliberately.** T1's whole point was that the
    filter, the sort and the tile must resolve the SAME number; adjusting in
    ``_display_price`` alone would have left the frontend rendering the raw
    figure and reintroduced that divergence. Because the adjustment lands on
    ``summary.market_price``, every downstream reader inherits it for free.

    Only RAW cards qualify. A graded slab carries a grade, not a condition tier,
    and its catalog price is an ungraded figure ``_display_price`` already skips
    — adjusting one would be a category error. Sealed and bulk have no condition.

    Returns the (possibly rebuilt) summary and a customer-visible ``value_note``
    explaining the adjustment, or ``None`` when nothing was adjusted. The note is
    computed live rather than read off the row so it can never disagree with the
    price shown beside it.
    """
    if summary is None or summary.market_price is None or item.kind != "raw":
        return summary, None
    condition = getattr(item, "condition", None)
    if condition is None:
        return summary, None

    adjusted, note = apply_condition_adjustment(
        summary.market_price, condition, getattr(item, "condition_modifier", None),
    )
    if note is None:  # NM anchor — 1.00x, nothing changed.
        return summary, None
    return summary.model_copy(update={"market_price": adjusted}), note


def _enrich(item: InventoryItem, card: CatalogCard | None) -> EnrichedInventoryItem:
    summary = (
        CardSummary.from_catalog(card, finish=getattr(item, "finish", None))
        if card is not None else None
    )
    summary, condition_note = _condition_adjust(summary, item)
    data = item.model_dump()
    # A live note beats the one the nightly denormalizer stored: it is derived
    # from the same figure being rendered, so the two cannot drift apart between
    # syncs. Only overwritten when an adjustment actually happened, so an FX or
    # sync-authored note on an unadjusted item survives.
    if condition_note is not None:
        data["value_note"] = condition_note
    # The catalog name is authoritative when the item is matched; otherwise expose
    # the sanitized display_name that was materialized on the row at import time
    # (services.card_text.format_display_name). Reading the stored field rather than
    # re-parsing notes keeps the customer wire and the LLM context free of internal
    # free-text (Council MUST-FIX A). Sealed/bulk rows carry no display_name field,
    # so ``.get`` yields None for them.
    data["display_name"] = data.get("display_name") if card is None else None
    return _ENRICHED[item.kind](**data, card=summary)
