"""Inventory domain models.

Every physical thing the business holds is one inventory item with its own
``item_id`` (one record = one physical unit). The ``kind`` discriminator picks
the shape: **raw** (ungraded single), **graded** (slab), **sealed** (booster
box / ETB / ...), or **bulk** (a lot sold as one unit). ``card_id`` is an
optional link to the catalog, present only for kinds that correspond to a
catalog card. ``InventoryItemAdapter`` validates raw dicts (e.g. straight from
DynamoDB) into the union.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter
from ulid import ULID


def new_ulid() -> str:
    """Sortable 26-char unique id for items/transactions."""
    return str(ULID())


class Condition(StrEnum):
    """Raw-card condition tiers, best (``NM``) to worst (``DMG``)."""

    NM = "NM"
    LP = "LP"
    MP = "MP"
    HP = "HP"
    DMG = "DMG"


class Language(StrEnum):
    """The print language of a physical item — part of its IDENTITY, not a label.

    A Japanese Seismitoad is a DIFFERENT card from the English one and carries a
    different market value, so this field decides whether the (English-only)
    catalog may be consulted for an item at all. Adding a member needs no data
    migration: records written before the field existed simply validate as
    ``EN``, the default.
    """

    EN = "EN"
    JP = "JP"

    @property
    def label(self) -> str:
        """Display name for the review tooling ("JP" -> "Japanese")."""
        return LANGUAGE_LABELS.get(self, self.value)


LANGUAGE_LABELS = {Language.EN: "English", Language.JP: "Japanese"}

# The attribute holding the sheet's card-name text, per item kind. One fact, one
# place: the review page, the applier and the language backfill all read it from
# here rather than each re-encoding the kind -> field mapping.
ITEM_TEXT_FIELD = {"raw": "notes", "graded": "notes",
                   "sealed": "product_name", "bulk": "description"}


class ConditionModifier(StrEnum):
    """Finer nuance on a condition tier (an ``LP+`` is an LP, but nicer)."""

    PLUS = "+"
    MINUS = "-"


class GradingCompany(StrEnum):
    """Third-party grading companies we track for slabbed cards."""

    PSA = "PSA"
    BGS = "BGS"
    CGC = "CGC"
    SGC = "SGC"


class ItemStatus(StrEnum):
    """Lifecycle state of an item; only ``AVAILABLE`` items are customer-visible."""

    AVAILABLE = "available"
    ON_HOLD = "on_hold"
    SOLD = "sold"
    OUT_FOR_GRADING = "out_for_grading"
    LOST = "lost"
    RETURNED_TO_CONSIGNOR = "returned_to_consignor"


class SealedProductType(StrEnum):
    BOOSTER_BOX = "booster_box"
    ETB = "etb"
    BUNDLE = "bundle"
    BOOSTER_PACK = "booster_pack"
    COLLECTION_BOX = "collection_box"
    OTHER = "other"


class ConsignmentTerms(BaseModel):
    """Terms for an item we sell on someone else's behalf (we don't own it)."""

    consignor_id: str
    split_percent: Decimal  # our cut as a 0-1 fraction (0.05 = a 5% cut)
    minimum_price: Decimal | None = None
    paid_out: bool = False


class _ItemBase(BaseModel):
    """Fields shared by every inventory item. One record = one physical unit.

    ``cost_basis`` is internal purchase data and must never reach customers.
    ``current_market_value`` is denormalized by the daily sync (card-linked raw
    items) or maintained manually (graded/sealed).

    ``language`` lives here rather than on ``RawInventoryItem`` because every
    kind can be a non-English printing — Japanese slabs and Japanese sealed
    product are both ordinary stock — and because it gates catalog matching,
    which the raw and graded kinds share.
    """

    item_id: str = Field(default_factory=new_ulid)
    status: ItemStatus = ItemStatus.AVAILABLE
    language: Language = Language.EN
    location: str | None = None
    cost_basis: Decimal
    market_value_at_purchase: Decimal | None = None
    current_market_value: Decimal | None = None
    listed_price: Decimal | None = None
    acquired_at: date
    acquired_show_id: str | None = None
    consignment: ConsignmentTerms | None = None
    notes: str | None = None
    tcg_url: str | None = None
    needs_review: bool = False


# A sanitized, customer-safe fallback name (e.g. "Dragonair #181") materialized at
# IMPORT time from the sheet's structured ``Name`` + ``Card #`` columns — never
# from the free-text ``notes`` — and stored on the row so both customer surfaces
# read one field instead of re-parsing notes (see
# ``services.card_text.format_display_name`` / Council MUST-FIX A/C). ``None`` when
# the row carried no structured identity; the catalog name wins once ``card_id``
# resolves, so this is only a fallback for unmatched (or momentarily un-joined) rows.
class RawInventoryItem(_ItemBase):
    """An ungraded single. ``factory_sealed`` = still in plastic wrap (promo premium)."""

    kind: Literal["raw"] = "raw"
    card_id: str | None = None
    display_name: str | None = None
    finish: str
    condition: Condition
    condition_modifier: ConditionModifier | None = None
    factory_sealed: bool = False


class GradedInventoryItem(_ItemBase):
    """A slabbed card."""

    kind: Literal["graded"] = "graded"
    card_id: str | None = None
    display_name: str | None = None
    company: GradingCompany
    grade: Decimal
    cert_number: str


class SealedInventoryItem(_ItemBase):
    """A sealed product (booster box, ETB, ...). No catalog link; manual value."""

    kind: Literal["sealed"] = "sealed"
    product_name: str
    product_type: SealedProductType


class BulkInventoryItem(_ItemBase):
    """A bulk lot sold as one unit; no per-card identity."""

    kind: Literal["bulk"] = "bulk"
    description: str


# Discriminated union: pydantic selects the subtype from the ``kind`` value.
InventoryItem = Annotated[
    Union[RawInventoryItem, GradedInventoryItem, SealedInventoryItem, BulkInventoryItem],
    Field(discriminator="kind"),
]

InventoryItemAdapter: TypeAdapter[InventoryItem] = TypeAdapter(InventoryItem)


# Catalog finishes to fall back through when the item's own finish carries no
# market price. Most singles are "normal"; holo-only cards price under a holo key.
_MARKET_FINISH_FALLBACK = (
    "normal", "holofoil", "reverseHolofoil",
    "1stEditionHolofoil", "1stEditionNormal", "unlimitedHolofoil",
)


def _market_price(card, finish: str | None) -> Decimal | None:
    """The pokemontcg.io market price for a card, preferring the item's finish.

    ``card.prices`` is keyed by finish (``normal``/``holofoil``/…); the item's own
    finish is tried first, then a sensible fallback order, then any finish that
    carries a market figure. ``None`` when the card has no market price at all.

    Requires a ``finish``: the TCGplayer figures are UNGRADED prices, so they are
    surfaced only for raw items (which always carry a finish). A graded slab has
    no finish and commands a grade premium the catalog does not know, so it gets
    no market price here and the caller keeps the slab's own figure.
    """
    if not finish:
        return None
    prices = getattr(card, "prices", None) or {}
    order: list[str] = []
    if finish not in order:
        order.append(finish)
    order += [f for f in _MARKET_FINISH_FALLBACK if f not in order]
    for key in order:
        band = prices.get(key)
        if band is not None and band.market is not None:
            return band.market
    for band in prices.values():
        if band is not None and band.market is not None:
            return band.market
    return None


class CardSummary(BaseModel):
    """The slice of catalog data the search UI needs to render a result tile."""

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    image_small: str | None = None
    # Live pokemontcg.io market price (per finish) — the customer-facing price for
    # a matched card. ``None`` when the catalog has no market figure; the caller
    # then falls back to the sheet's listed price.
    market_price: Decimal | None = None

    @classmethod
    def from_catalog(cls, card, *, finish: str | None = None) -> CardSummary:
        """Build from a ``CatalogCard`` (typed loosely to avoid a module cycle)."""
        return cls(
            card_id=card.card_id,
            name=card.name,
            set_id=card.set_id,
            set_name=card.set_name,
            number=card.number,
            rarity=card.rarity,
            image_small=card.images.small,
            market_price=_market_price(card, finish),
        )


# The customer-facing ``display_name`` on a search result: the fallback name
# materialized on the item at import time (see the raw/graded model note above and
# ``services.card_text.format_display_name``), carrying only name+number. ``_enrich``
# sets it to ``None`` whenever a catalog card is present, since the catalog name is
# authoritative there. Sealed/bulk have no stored display_name; their enriched
# variants declare it only so the union projection is uniform.
class EnrichedRawInventoryItem(RawInventoryItem):
    """A raw item joined with its catalog summary (``None`` if not linked/synced)."""

    card: CardSummary | None = None
    display_name: str | None = None


class EnrichedGradedInventoryItem(GradedInventoryItem):
    """A graded item joined with its catalog summary (``None`` if not linked/synced)."""

    card: CardSummary | None = None
    display_name: str | None = None


class EnrichedSealedInventoryItem(SealedInventoryItem):
    """A sealed product in a search result (never has a catalog card)."""

    card: CardSummary | None = None
    display_name: str | None = None


class EnrichedBulkInventoryItem(BulkInventoryItem):
    """A bulk lot in a search result (never has a catalog card)."""

    card: CardSummary | None = None
    display_name: str | None = None


EnrichedInventoryItem = Annotated[
    Union[
        EnrichedRawInventoryItem,
        EnrichedGradedInventoryItem,
        EnrichedSealedInventoryItem,
        EnrichedBulkInventoryItem,
    ],
    Field(discriminator="kind"),
]


class InventorySearchResult(BaseModel):
    """Search response: the matching (catalog-enriched) items plus their count."""

    items: list[EnrichedInventoryItem]
    total: int
