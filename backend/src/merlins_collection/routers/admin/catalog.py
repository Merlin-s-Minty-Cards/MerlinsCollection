"""``/admin/catalog`` — the catalog's own shape, as opposed to what we own.

One route: every set in the catalog, with how many cards of it we hold. It backs
the admin inventory page's set combobox (RFC 0008 §F4 / T8).

**Why this is not ``/inventory/facets``.** The owner's ask decides it: *"so we
can double check if there is a set in the catalog we have no cards of."* A facet
is by construction the distinct values PRESENT in a result set, so a set we own
nothing from can never appear in one. Deriving the list from admin inventory has
the same hole. The list has to come from the catalog side.

**Why this is not a scan.** There is no set entity on the card rows' side of the
table — sets exist only as denormalized ``set_id``/``set_name`` fields on 31,603
catalog cards, and GSI1's ``SET#`` partition answers "cards in this set", never
"what sets exist". Reading the set list off the cards is therefore a full-table
scan: the 11.2-second operation T9 diagnosed as the cause of the dead catalog
search, on a control the admin opens constantly. So the sets come from the
``catalog_set`` registry (``services/catalog_sync``), one query, and the owned
counts come from point-reads of the items' own catalog cards. Nothing here
scans, and ``test_does_not_scan_the_catalog`` fails the build if that changes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import Language, _market_price
from merlins_collection.services import catalog_cache
from merlins_collection.services.dynamodb import InventoryRepository

router = APIRouter(prefix="/catalog", tags=["admin-catalog"])


class CatalogSetSummary(BaseModel):
    """One set, as the combobox needs it.

    ``language`` is carried per set rather than inferred from the name because
    names are NOT unique across languages — "Base Set" exists in both — while
    ``set_id`` is the language composite (``en:base1`` / ``ja:base1``) and is.
    Two identically-named sets are two entries; the language is what lets an
    admin tell them apart.

    ``card_count`` is how many of the set's cards our catalog holds, and
    ``owned_count`` how many physical items we have from it. They answer
    different questions and a zero in either is meaningful: no catalog rows
    means the sync has not reached that set, no owned items means it is a
    buying gap.
    """

    set_id: str
    set_name: str
    language: str
    card_count: int
    owned_count: int


@router.get("/sets", response_model=list[CatalogSetSummary])
def list_catalog_sets(
    repo: InventoryRepository = Depends(get_repo),
) -> list[CatalogSetSummary]:
    """Every set in the catalog, alphabetically, with owned counts.

    An empty list means the registry has never been written — a table whose
    catalog sync has not run, or one seeded before T8 and not yet backfilled by
    ``scripts/backfill_catalog_sets.py``. Answering honestly beats falling back
    to a scan of the card rows, which is what this endpoint exists to avoid.
    """
    registry = repo.list_catalog_sets()
    if not registry:
        # Short-circuited before touching inventory: with no sets to attribute
        # them to, the owned counts have nowhere to go.
        return []

    owned = _owned_counts_by_set(repo)
    summaries = [
        CatalogSetSummary(
            set_id=row["set_id"],
            # A set the seed could not name (``list_sets`` was unavailable for
            # that run) would otherwise render as a blank, unselectable row.
            set_name=row.get("set_name") or row["set_id"],
            language=row.get("language") or Language.EN.value,
            card_count=int(row.get("card_count") or 0),
            owned_count=owned.get(row["set_id"], 0),
        )
        for row in registry
        if row.get("set_id")
    ]
    # Language and id break name ties, so the ~400 rows come back in a stable
    # order rather than DynamoDB's — a list that reshuffles between requests
    # moves the option under the admin's cursor.
    return sorted(summaries, key=lambda s: (s.set_name.lower(), s.language, s.set_id))


class CatalogLanguageSummary(BaseModel):
    """One language actually present in the catalog, for the search filter.

    ``code`` is the ``Language`` enum VALUE ("EN", "JP", ...), matching
    ``CatalogSetSummary.language`` above — not the TCGdex API code ("en",
    "ja"), which is a URL-path detail this response has no reason to leak.
    """

    code: str
    label: str
    sets: int


@router.get("/languages", response_model=list[CatalogLanguageSummary])
def list_catalog_languages(
    repo: InventoryRepository = Depends(get_repo),
) -> list[CatalogLanguageSummary]:
    """Every language that ACTUALLY has catalog rows, with how many sets.

    RFC 0023 grew ``Language`` to 19 members (18 real TCGdex codes + ``OTHER``)
    while the catalog itself stays seeded per language, on demand (see
    ``SEEDED_LANGUAGES``, ``models/inventory.py``) — most members have zero
    rows. Offering all 19 in a search filter would let an admin pick a
    language that can only ever return nothing, so this endpoint derives the
    list from the SAME ``catalog_set`` registry ``/sets`` above already
    reads (one query, no scan), grouped and counted, rather than from the
    enum. An empty catalog answers ``[]`` honestly, same as ``/sets``.
    """
    registry = repo.list_catalog_sets()
    counts: dict[str, int] = {}
    for row in registry:
        code = row.get("language")
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1

    def _label(code: str) -> str:
        try:
            return Language(code).label
        except ValueError:
            # A registry row from a language build this process no longer
            # recognizes (should not happen — nothing removes enum members —
            # but answering with the raw code beats a 500 on a filter list).
            return code

    summaries = [
        CatalogLanguageSummary(code=code, label=_label(code), sets=count)
        for code, count in counts.items()
    ]
    return sorted(summaries, key=lambda s: s.label)


class NewCard(BaseModel):
    """One newly-catalogued card, as the dashboard widget renders it.

    Name, image AND price — the owner's absolute rule, and the widget is a place
    a card APPEARS, which the rule covers just as much as a picker does.

    ``market_price`` is a **NEAR MINT** catalog figure and is **not**
    condition-adjusted: there is no item involved, so there is no condition to
    adjust by. ``None`` means no provider published a figure — never ``0``.
    """

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    images: dict[str, Any] = {}
    market_price: Decimal | None = None
    first_seen_at: datetime | None = None


class NewCardsResponse(BaseModel):
    """``count`` is the whole window; ``cards`` is the sample the widget shows.

    They are deliberately different numbers. ``limit`` bounds what is rendered,
    never the answer to "how many new cards are there" — capping the count too
    would under-report the work waiting.
    """

    count: int
    #: The window's start, so the UI does not recompute it — and so it cannot
    #: recompute it in UTC and land a day off (CLAUDE.md, dates).
    since: date
    cards: list[NewCard] = []


@router.get("/new-cards", response_model=NewCardsResponse)
def new_catalog_cards(
    since_days: int = Query(30, ge=1, le=365),
    limit: int = Query(6, ge=1, le=25),
    repo: InventoryRepository = Depends(get_repo),
) -> NewCardsResponse:
    """Catalog cards first seen inside the window, newest first.

    **Counts only rows carrying a ``first_seen_at``.** A null means "predates the
    field", not "new" — every one of the 31,603 rows seeded before RFC 0011 has
    one, so counting nulls would report the entire catalog as new on the very
    first load. Same honesty ``detail: brief|full`` already keeps.

    Served from ``catalog_cache`` (~93 MB resident, RFC 0008 T9), so this is an
    in-memory filter and not the 11.2-second full-table scan that reading the
    catalog per request used to cost.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    fresh = [
        card
        for card in catalog_cache.get_catalog_cards(repo.list_all_catalog_cards)
        if (stamped := getattr(card, "first_seen_at", None)) is not None
        and _as_utc(stamped) >= cutoff
    ]
    # `card_id` breaks the tie so a page of cards stamped in the same second
    # comes back in a stable order rather than the scan's.
    fresh.sort(key=lambda c: (_as_utc(c.first_seen_at), c.card_id), reverse=True)
    return NewCardsResponse(
        count=len(fresh),
        since=(datetime.now(timezone.utc) - timedelta(days=since_days)).date(),
        cards=[_new_card(card) for card in fresh[:limit]],
    )


def _as_utc(moment: datetime) -> datetime:
    """A stored timestamp as an aware UTC datetime.

    A row written before anything stamped a zone back can be naive, and
    comparing a naive datetime to an aware one raises ``TypeError`` — a 500 on a
    dashboard, caused by one old row.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _new_card(card) -> NewCard:
    """Project a catalog card for the widget.

    The price comes from ``_market_price(card, "normal")`` — the ONE shared
    finish-aware lookup. There is no item here and therefore no finish, so
    ``"normal"`` is passed to buy the whole fallback walk; re-implementing that
    selection is how 174 of 213 live items once went unpriced.
    """
    return NewCard(
        card_id=card.card_id,
        name=card.name,
        set_id=card.set_id,
        set_name=card.set_name,
        number=card.number,
        rarity=card.rarity,
        images=card.images.model_dump(),
        market_price=_market_price(card, "normal"),
        first_seen_at=card.first_seen_at,
    )


def _owned_counts_by_set(repo: InventoryRepository) -> dict[str, int]:
    """How many inventory items each set accounts for, by point-read.

    Counts EVERY inventory row, not just ``available`` stock, because clicking a
    set in the combobox filters the admin table — which shows all statuses by
    default. A count that disagreed with the list it filters is the failure mode
    the triage badge documents at length.

    ``getattr`` rather than ``item.card_id``: sealed and bulk items have no such
    FIELD, not a null one, so the direct attribute access raises
    ``AttributeError`` on the first box in the inventory.
    """
    card_ids = [
        card_id
        for item in repo.list_inventory()
        if (card_id := getattr(item, "card_id", None))
    ]
    if not card_ids:
        return {}

    # Chunked BatchGetItem, not a scan. Ids repeat across items (three copies of
    # one card is three rows), and `batch_get_catalog_cards` de-duplicates them,
    # so the walk below counts ITEMS while the read costs one entry per card.
    cards = repo.batch_get_catalog_cards(card_ids)
    counts: dict[str, int] = {}
    for card_id in card_ids:
        card = cards.get(card_id)
        if card is None:
            # An item pointing at a card the catalog does not have belongs to no
            # set. Counting it anywhere would inflate a set it may not be in.
            continue
        counts[card.set_id] = counts.get(card.set_id, 0) + 1
    return counts
