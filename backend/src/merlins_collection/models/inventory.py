"""Inventory domain models.

An inventory item is either **raw** (ungraded, has a finish + condition) or
**graded** (slabbed by a grading company, has a company/grade/cert). They share
``_ItemBase`` and are combined into a single ``InventoryItem`` discriminated
union on the ``kind`` field, so a stored item round-trips to the right subtype.
``InventoryItemAdapter`` validates raw dicts (e.g. straight from DynamoDB) into
that union.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class Condition(StrEnum):
    """Raw-card condition grades, best (``NM``) to worst (``DMG``)."""

    NM = "NM"
    LP = "LP"
    MP = "MP"
    HP = "HP"
    DMG = "DMG"


class GradingCompany(StrEnum):
    """Third-party grading companies we track for slabbed cards."""

    PSA = "PSA"
    BGS = "BGS"
    CGC = "CGC"
    SGC = "SGC"


class _ItemBase(BaseModel):
    """Fields common to every inventory item.

    ``cost_basis`` is our internal purchase price and must never be exposed to
    customers (the search endpoint strips it). ``current_market_value`` is
    denormalized by the daily sync and may be ``None`` until it first runs.
    """

    card_id: str
    quantity: int
    listed_price: Decimal
    cost_basis: Decimal
    current_market_value: Decimal | None = None
    acquired_at: date


class RawInventoryItem(_ItemBase):
    """An ungraded card, identified by its finish and condition."""

    kind: Literal["raw"] = "raw"
    finish: str
    condition: Condition


class GradedInventoryItem(_ItemBase):
    """A slabbed card, identified by grading company, grade, and cert number."""

    kind: Literal["graded"] = "graded"
    company: GradingCompany
    grade: Decimal
    cert_number: str


# Discriminated union: pydantic selects the subtype from the ``kind`` value.
InventoryItem = Annotated[
    Union[RawInventoryItem, GradedInventoryItem],
    Field(discriminator="kind"),
]

InventoryItemAdapter: TypeAdapter[InventoryItem] = TypeAdapter(InventoryItem)


class CardSummary(BaseModel):
    """The slice of catalog data the search UI needs to render a result tile."""

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    image_small: str | None = None

    @classmethod
    def from_catalog(cls, card) -> CardSummary:
        """Build from a ``CatalogCard`` (typed loosely to avoid a module cycle)."""
        return cls(
            card_id=card.card_id,
            name=card.name,
            set_id=card.set_id,
            set_name=card.set_name,
            number=card.number,
            rarity=card.rarity,
            image_small=card.images.small,
        )


class EnrichedRawInventoryItem(RawInventoryItem):
    """A raw item joined with its catalog summary (``None`` if not yet synced)."""

    card: CardSummary | None = None


class EnrichedGradedInventoryItem(GradedInventoryItem):
    """A graded item joined with its catalog summary (``None`` if not yet synced)."""

    card: CardSummary | None = None


EnrichedInventoryItem = Annotated[
    Union[EnrichedRawInventoryItem, EnrichedGradedInventoryItem],
    Field(discriminator="kind"),
]


class InventorySearchResult(BaseModel):
    """Search response: the matching (catalog-enriched) items plus their count."""

    items: list[EnrichedInventoryItem]
    total: int
