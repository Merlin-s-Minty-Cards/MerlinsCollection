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

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator
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
    different market value, so this field is part of the catalog lookup key: a
    JP item resolves to a JP catalog row, never to its English twin. Records
    written before the field existed simply validate as ``EN``, the default.

    ``EN`` and ``JP`` are the only members and that is deliberate — the source
    spreadsheet contains no other language, and every added member is another
    axis of matcher ambiguity for data that does not exist (RFC 0003 §4).
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


def normalize_condition(value: str) -> tuple[Condition, ConditionModifier | None]:
    """Split a display condition string (``"LP+"``) into its two stored fields.

    Storage is ALWAYS two fields — ``condition`` (the tier) plus
    ``condition_modifier`` — but every human-facing surface writes and reads one
    combined string (spec §14). This is the server-side mirror of the frontend's
    ``parseCondition`` (``frontend/lib/constants.ts``): a trailing ``+``/``-`` is
    the modifier, everything before it is the tier. Casing and surrounding
    whitespace are forgiving; anything else raises ``ValueError`` rather than
    silently degrading to a tier the admin did not pick.
    """
    if not isinstance(value, str):
        raise ValueError(f"Invalid condition: {value!r}")

    text = value.strip().upper()
    if not text:
        raise ValueError("Condition must not be empty")

    modifier: ConditionModifier | None = None
    if text[-1] in ("+", "-"):
        modifier = ConditionModifier(text[-1])
        text = text[:-1].strip()

    try:
        condition = Condition(text)
    except ValueError as exc:
        raise ValueError(f"Invalid condition: {value!r}") from exc

    return condition, modifier


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


class InventoryLocation(StrEnum):
    """Standardized physical locations where inventory can reside.

    Replaces the legacy free-text ``location`` field. All admin UIs should
    use this list via the ``/admin/locations`` endpoint or import it directly.
    """

    GLASS = "glass"
    TOPLOADER = "toploader"
    BINDER = "binder"
    STORAGE = "storage"
    SHOW_BOX_A = "show_box_a"
    SHOW_BOX_B = "show_box_b"
    DISPLAY_CASE = "display_case"
    GRADING_PILE = "grading_pile"
    SOLD_PILE = "sold_pile"


# Ordered list for API/UI consumption — human-readable labels.
INVENTORY_LOCATION_CHOICES: list[dict[str, str]] = [
    {"value": loc.value, "label": loc.value.replace("_", " ").title()}
    for loc in InventoryLocation
]


class SealedProductType(StrEnum):
    BOOSTER_BOX = "booster_box"
    ETB = "etb"
    BUNDLE = "bundle"
    BOOSTER_PACK = "booster_pack"
    COLLECTION_BOX = "collection_box"
    OTHER = "other"


# The reasons an AUTOMATED path flags an item for review. A human "Send to
# Triage" types free text instead, and that difference is what the re-flag guard
# in ``admin_update_item`` keys off: automation must not re-flag an item an admin
# has already inspected and passed, but a human always may.
#
# Kept as one column shared with human free text rather than a second
# ``review_source`` field — see docs/plans/rfc-0008/follow-ups.md (T11) for the
# seam that creates and why it was accepted.
MACHINE_REVIEW_REASONS = frozenset({
    "low_match_confidence",
    "manual_entry",
    "no_catalog_link",
    "blank_condition",
    # A slab whose PSA cert lookup failed -- no key, provider down, or the daily
    # quota spent -- and which was therefore entered by hand (RFC 0009 §9).
    "cert_lookup_failed",
})


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
    sticker_price: Decimal | None = None
    sticker_notes: str | None = None
    acquired_at: date
    acquired_show_id: str | None = None
    consignment: ConsignmentTerms | None = None
    notes: str | None = None
    tcg_url: str | None = None
    needs_review: bool = False
    # Why this item is in Triage. ``needs_review`` alone is a bare boolean, so
    # low match confidence, a manual buy entry and a human's "back looks
    # trimmed" were indistinguishable — a queue of cards with no stated problem
    # is not a worklist. Machine reasons come from MACHINE_REVIEW_REASONS above;
    # anything else is an admin's own note.
    #
    # INTERNAL. Deliberately kept OUT of ``_CUSTOMER_ITEM_FIELDS`` — unlike
    # ``value_note``, which is customer-visible by design (Phase 19). Bounded
    # because it is free text riding into a DynamoDB item with a 400 KB ceiling,
    # and blank normalizes to None so clearing the box means "no reason" rather
    # than an empty chip.
    review_reason: str | None = Field(default=None, max_length=500)
    # Stamped by the SERVER when an admin clears the flag; the client never
    # sends it. This is what stops the queue rotting: without it a later
    # automated write re-flags an item a human already inspected and passed,
    # the tab fills with cards nobody needs to look at, and it stops being used.
    # See docs/plans/rfc-0008/t11-triage-tab.md.
    reviewed_at: datetime | None = None
    value_note: str | None = None
    lineage_id: str | None = None
    predecessor_item_id: str | None = None
    # An admin-typed name that OUTRANKS the catalog name on customer surfaces —
    # the fix for a Japanese card whose catalog row is in Japanese script that a
    # customer cannot read. It is an override, not a materialized name: leaving
    # it None means the catalog name renders, so the ~249 English items need no
    # data change at all. Nothing in the sync or import path writes this field,
    # which is what makes it safe from being silently clobbered later — and it
    # is separate from ``card_id``, so renaming an item can never break its
    # catalog link. Bounded because it reaches customers.
    # See docs/plans/rfc-0008/t10-jp-english-names.md.
    display_name_override: str | None = Field(default=None, max_length=200)
    # Stored answer to a question the DERIVED ``missing_card_id`` reason cannot
    # ask: "we looked, and TCGdex does not carry this card." Without it an
    # unmatchable card sits in Triage forever, because ``is_missing_card_id`` is
    # recomputed on every read and stays true no matter how many times a human
    # confirms there is nothing to match — so the queue has a floor it can never
    # get under. See RFC 0011 §C.
    #
    # INTERNAL. Deliberately kept OUT of ``_CUSTOMER_ITEM_FIELDS``, same rule as
    # ``review_reason`` — a customer has no use for our cataloguing backlog.
    #
    # Defaults to False and NOTHING is backfilled: the owner's requirement is
    # that the queue ships empty and every card in it got there under admin
    # supervision.
    no_catalog_match: bool = False
    # Stamped by the SERVER when the flag is set; the client never sends it —
    # the same rule ``reviewed_at`` follows. Drives "parked 3 weeks ago" on the
    # queue and lets the list sort oldest-first.
    no_catalog_match_at: datetime | None = None

    @model_validator(mode="after")
    def _unmatched_implies_unlinked(self):
        """A card that is matched is not unmatched.

        Allowing both to be true creates a row that is simultaneously in
        Triage's "no catalog link" reason AND in the queue that exists to hold
        cards which have no link — two answers to one question, which is the
        state this whole feature exists to remove. The admin's route is: unlink
        first, which T6 does in the same click.

        ``getattr``, not attribute access: sealed and bulk items have no
        ``card_id`` field at all, and must never be parkable.
        """
        if self.no_catalog_match and getattr(self, "card_id", None) is not None:
            raise ValueError(
                "no_catalog_match cannot be set on an item that still has a "
                "card_id; unlink the card first"
            )
        return self

    @field_validator("display_name_override", "review_reason", mode="before")
    @classmethod
    def _blank_admin_text_is_none(cls, value: object) -> object:
        """Trim, and treat a blank string as "not set".

        Clearing the box in the admin UI submits ``""``. For
        ``display_name_override`` that would out-rank the catalog name and
        render a NAMELESS tile; for ``review_reason`` it would render an empty
        chip on the Triage row. Both have to mean "remove it" instead. Runs
        before the length bound, so a padded-but-legal value is trimmed rather
        than rejected.
        """
        if isinstance(value, str):
            return value.strip() or None
        return value


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
    """A slabbed card.

    The four cert fields below are what PSA's cert lookup fills in (RFC 0009 §6),
    and every one of them is OPTIONAL on purpose: each graded row already in the
    live table predates them, so a required field would fail validation on all of
    them the moment this deploys. ``cert_verified_at is None`` is the honest
    reading of "no provider ever confirmed this cert" — a hand-entered slab and a
    PSA-verified one must stay distinguishable.

    There is deliberately **no population field**: PSA's public API always returns
    ``null`` for ``TotalPopulation``/``PopulationHigher`` (RFC 0009 §5.1), so a
    column for it could only ever hold nothing.
    """

    kind: Literal["graded"] = "graded"
    card_id: str | None = None
    display_name: str | None = None
    company: GradingCompany
    grade: Decimal
    cert_number: str
    # PSA's own wording for the grade ("GEM MT 10"), which is not derivable from
    # the numeric ``grade`` -- the label carries qualifiers the number does not.
    grade_label: str | None = Field(default=None, max_length=50)
    # When a provider CONFIRMED this cert. None = never verified.
    cert_verified_at: datetime | None = None
    # The provider's label/card image. PROVIDER-SUPPLIED and rendered in the admin
    # UI, so the scheme is validated below rather than trusted.
    cert_image_url: str | None = Field(default=None, max_length=2000)
    # The pricing provider's own product id, resolved once and reused so later
    # refreshes skip the fuzzy name search. Named for the ROLE, not the vendor:
    # the vendor decision is revisitable (RFC 0009 §5.2) and a column called
    # after one of them would have to be renamed or lie.
    price_source_id: str | None = Field(default=None, max_length=100)

    @field_validator("cert_image_url", mode="before")
    @classmethod
    def _http_url_only(cls, value: object) -> object:
        """Accept ``http``/``https`` only; blank means "no image".

        This value comes from a third party and is rendered as a link/image in
        the admin panel, so a ``javascript:`` URI here is stored XSS waiting for
        an admin to click it. The codebase already carries one finding for
        ``tcg_url`` accepting exactly that (RFC 0008 follow-ups); this is the
        field that does not repeat it.

        ``netloc`` is required too, which is what rejects the protocol-relative
        ``//evil.example.com/x`` — its scheme is whatever the surrounding page's
        happens to be, so a scheme check alone would wave it through.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return None
        parsed = urlparse(text)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "cert_image_url must be an absolute http:// or https:// URL"
            )
        return text


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
#
# *** THIS TUPLE IS THE CANONICAL FALLBACK ORDER FOR THE WHOLE PRODUCT, in every
# language it is implemented in (claude-progress.txt, CONCURRENCY warning). The
# MCP server re-implements the same walk in TypeScript; if the two orders ever
# disagree, the website and the Bedrock chat quote different prices for the same
# card. Change it here and there together, or not at all. ***
_MARKET_FINISH_FALLBACK = (
    "normal", "holofoil", "reverseHolofoil",
    "1stEditionHolofoil", "1stEditionNormal", "unlimitedHolofoil",
)


def market_price_and_finish(card, finish: str | None) -> tuple[Decimal | None, str | None]:
    """``_market_price``'s answer plus WHICH finish it came from.

    The walk lives here and ``_market_price`` delegates to it, so there is
    still exactly ONE implementation — see that function's docstring for why
    that matters. Split out for RFC 0010 T15: a card picker shows the figure
    *and* names its finish, because a holofoil price quoted against a normal
    card is the kind of mismatch that costs money at a buy table. Getting the
    finish by looking the price up a second time would be the fifth copy.
    """
    if not finish:
        return None, None
    prices = getattr(card, "prices", None) or {}
    order: list[str] = [finish]
    order += [f for f in _MARKET_FINISH_FALLBACK if f not in order]
    for key in order:
        band = prices.get(key)
        if band is not None and band.market is not None:
            return band.market, key
    for key, band in prices.items():
        if band is not None and band.market is not None:
            return band.market, key
    return None, None


def _market_price(card, finish: str | None) -> Decimal | None:
    """The catalog market price (USD) for a card, preferring the item's finish.

    **THE ONE SHARED FINISH-AWARE PRICE LOOKUP.** All three paths that need a
    catalog price call exactly this function — the search/read path (via
    ``CardSummary.from_catalog`` below), the write path that denormalizes
    ``current_market_value`` onto the stored item
    (``services.catalog_sync.refresh_inventory_market_values``), and the
    dashboard summary (``routers.inventory.inventory_summary``). They each used
    to resolve prices for themselves, and the write path's bare exact match left
    174 of 213 live items unpriced while the read path priced them fine
    (claude-progress.txt Phase 12/Phase 10). Do not re-implement this walk in a
    caller: a second copy is how that divergence happened.

    ``card.prices`` is keyed by finish (``normal``/``holofoil``/…); the item's own
    finish is tried first, then a sensible fallback order, then any finish that
    carries a market figure. ``None`` when the card has no market price at all.
    Every band is USD regardless of which provider supplied it, so no currency
    check is needed here (see ``models.catalog.FinishPrice``).

    Requires a ``finish``: the catalog figures are UNGRADED prices, so they are
    surfaced only for raw items (which always carry a finish). A graded slab has
    no finish and commands a grade premium the catalog does not know, so it gets
    no market price here and the caller keeps the slab's own figure.
    """
    return market_price_and_finish(card, finish)[0]


class CardSummary(BaseModel):
    """The slice of catalog data the search UI needs to render a result tile."""

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    image_small: str | None = None
    # Live catalog market price in USD (per finish) — the customer-facing price for
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
    # How many otherwise-matching items a price bound excluded purely because
    # they have no resolvable price (Phase 12, owner decision 2). They stay
    # excluded — a card with no known price cannot honestly be claimed to be
    # under $500 — but the UI renders this count ("N cards hidden (no price on
    # file)") so they are not dropped invisibly. Always 0 when no bound is set.
    hidden_no_price: int = 0
