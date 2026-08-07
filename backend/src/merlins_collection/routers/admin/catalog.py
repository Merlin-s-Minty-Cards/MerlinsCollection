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

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from merlins_collection.dependencies import get_repo
from merlins_collection.models.inventory import Language
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
