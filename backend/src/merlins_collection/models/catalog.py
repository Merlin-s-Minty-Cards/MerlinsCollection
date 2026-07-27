"""Catalog + price-history models, derived from TCGdex data.

``CatalogCard`` is the reference data for a card (name, set, images, current
prices per finish). ``PricePoint`` is one dated observation kept for history —
raw (per finish) or graded (per company/grade).

A card's IDENTITY includes its print language: ``card_id`` is the composite
``"{api_lang}:{tcgdex_id}"`` (``en:base1-4``, ``ja:M5-001``), so a Japanese card
and its English twin are distinct rows rather than one row overwriting the other
(RFC 0003 §3). ``services.tcgdex`` owns that format; this module only stores it.

**Every ``Decimal`` in ``FinishPrice`` and every ``PricePoint.market`` is USD.**
TCGdex ships TCGplayer figures in USD and Cardmarket figures in EUR; the mapper
converts at the boundary so downstream code never has to ask. Where a figure was
converted, ``source_currency`` and ``value_note`` record it (RFC 0003 §5).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from merlins_collection.models.inventory import Language


class CardImages(BaseModel):
    """Hosted image URLs for a card.

    Both default to ``""`` because TCGdex omits ``image`` entirely on many cards
    (Japanese printings especially). An absent image is a fact to render around,
    not an error — ``CardSummary.image_small`` is already optional downstream.
    """

    small: str = ""
    large: str = ""


class FinishPrice(BaseModel):
    """Price band for one finish. **All money fields are USD.**

    ``source`` is the provider the figure came from (``tcgplayer``/``cardmarket``)
    and ``source_currency`` the currency it was quoted in. When those differ —
    the Cardmarket EUR path — ``value_note`` states the original amount, the
    field used, and the FX rate applied, so any converted figure is auditable and
    re-derivable. Bands are only written when the provider actually published a
    figure; a card with no market data has no band at all.
    """

    market: Decimal | None = None
    low: Decimal | None = None
    mid: Decimal | None = None
    high: Decimal | None = None
    currency: Literal["USD"] = "USD"
    source: str | None = None
    source_currency: str | None = None
    source_updated_at: datetime | None = None
    value_note: str | None = None


class CatalogCard(BaseModel):
    """Reference data for a single card; ``prices`` is keyed by finish name.

    ``prices`` keys are the INTERNAL finish vocabulary (``normal``/``holofoil``/
    ``reverseHolofoil``/…), normalized from TCGdex's own names by
    ``services.tcgdex.map_finish``.

    ``language`` is stored rather than parsed back out of ``card_id`` because the
    matcher indexes on it and a model should not have to parse its own key; the
    two always agree. It defaults to ``EN`` so rows written before the field
    existed still validate.

    ``detail`` says which pass wrote the row: ``brief`` rows come from the cheap
    list endpoint (identity only, no prices), ``full`` rows from a per-card
    request. Keeping them distinguishable is an honesty requirement — "we never
    fetched a price for this card" and "no provider covers this card" are
    different facts and must not be conflated.
    """

    card_id: str
    language: Language = Language.EN
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    types: list[str] = []
    images: CardImages = CardImages()
    prices: dict[str, FinishPrice] = {}
    detail: Literal["brief", "full"] = "brief"
    last_synced_at: datetime


class PricePoint(BaseModel):
    """One dated price observation, in USD. ``kind`` decides which fields apply.

    Raw points carry ``finish``; graded points carry ``company`` + ``grade``.
    ``source`` records where the figure came from (``tcgplayer``/``cardmarket``
    for catalog prices, ``manual`` for graded values). ``source_currency`` and
    ``value_note`` carry the same conversion provenance as ``FinishPrice``, so a
    history row remains auditable long after the catalog row is overwritten.
    """

    card_id: str
    date: date
    source: str
    kind: Literal["raw", "graded"]
    finish: str | None = None
    company: str | None = None
    grade: Decimal | None = None
    market: Decimal | None = None
    low: Decimal | None = None
    mid: Decimal | None = None
    high: Decimal | None = None
    currency: str = "USD"
    source_currency: str | None = None
    source_updated_at: datetime | None = None
    value_note: str | None = None
