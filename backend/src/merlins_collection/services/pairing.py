"""Ranked catalog candidates for a parked (``no_catalog_match``) item — RFC 0011 §E.

**The sibling of ``spreadsheet_import._match_card``, not a fork of it.** That
matcher answers *"is there exactly one safe answer?"* and returns ``None`` for
everything ambiguous — correct for an importer writing ``card_id`` unattended,
wrong for a human picking off a list. This module relaxes only the **verdict**:
it returns the candidates it found, each with a score and a stated reason, over
the very same normalizers (``normalize_name`` / ``core_name`` /
``normalize_number`` / ``number_keys`` from ``services.card_text``). Do not
re-implement any of them here; a second normalizer is how the two sides stop
agreeing about what ``"182/167"`` means.

**Language is part of the KEY, never a post-filter** — the same rule and the same
reason as ``build_catalog_index``: a Japanese Seismitoad #38 must resolve to the
Japanese printing, which trades at a different price. A JP item can therefore
legitimately have **zero** candidates (TCGdex's Japanese coverage is thin), and
zero is an honest answer — it is usually *why* the card is parked.

**Never call the pricing provider from here.** A suggestion is a catalog lookup.
The graded price provider is metered at fifty lookups a day (CLAUDE.md,
Third-Party APIs), and a page load that quietly spends quota is how a budget
disappears without anyone deciding to spend it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from merlins_collection.models.inventory import _market_price
from merlins_collection.services.card_text import (
    admin_item_name,
    coerce_language,
    core_name,
    normalize_name,
    normalize_number,
    number_keys,
)

#: Never suggest below this. A weak candidate presented beside a strong one reads
#: as an option, and the promo-priced mispairing this feature exists to prevent is
#: exactly what happens when a human picks the plausible-looking wrong card off a
#: ranked list. The owner described the failure in those words: "cards that are
#: close to the right card but are actually a promo so the price is completely
#: wrong."
MIN_SCORE = 0.5

#: Trailing ``#181`` on a materialized display name (``card_text.format_display_name``
#: composes ``"<name> #<number>"``). An inventory item has no ``card_number`` field,
#: so this is where a raw item's collector number actually lives.
_TRAILING_NUMBER_RE = re.compile(r"\s*#\s*([A-Za-z0-9]+(?:/[A-Za-z0-9]+)?)\s*$")


class Candidate(BaseModel):
    """One catalog card offered as a pairing, with why it is being offered.

    ``image_small`` is ``""`` and ``market_price`` is ``None`` when the catalog
    has neither — **an absent image and an absent price are facts, not errors**.
    Both fields are always present so the picker can render its placeholder
    rather than collapse the row (owner rule: a card picker shows name, image AND
    price).

    ``market_price`` is a **NEAR MINT** catalog figure and is deliberately **not**
    condition-adjusted: there is no item condition in a catalog row, so scaling it
    would be inventing a number. The consumer must not present it as a sale price.

    ``detail`` and ``last_synced_at`` are carried because the picker cannot be
    honest without them, and both are free — the catalog row is already in hand:

    * ``detail`` preserves a real distinction the UI must keep (CLAUDE.md).
      ``brief`` = *we have never fetched a price for this card*; ``full`` with no
      price = *no provider covers this card*. Collapsing both to one "no price"
      throws away the only signal that says whether waiting will help.
    * ``last_synced_at`` is what lets a stale figure be shown WITH its age. A
      price from six days ago is fine; a three-month-old one is a different claim
      and must not look identical.
    """

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None = None
    image_small: str = ""
    market_price: Decimal | None = None
    detail: str | None = None
    last_synced_at: datetime | None = None
    score: float
    why: str


class ItemSuggestions(BaseModel):
    """Every candidate for one parked item; ``candidates`` may legitimately be empty."""

    item_id: str
    candidates: list[Candidate] = []


class SuggestionsResponse(BaseModel):
    """``items_with_candidates`` counts ROWS you can act on, not suggestions.

    The dashboard widget (T10) quotes it and the queue page (T8) lists the same
    rows, so it is computed in the same pass as ``items`` — the two can never
    disagree about how much work is waiting.
    """

    items: list[ItemSuggestions] = []
    items_with_candidates: int = 0


@dataclass(frozen=True)
class PairingIndex:
    """Normalized lookup structures over catalog cards, keyed like the importer's.

    ``by_name_number`` and ``by_core_number`` are keyed exactly as
    ``card_text.build_catalog_index`` keys them. ``by_name`` is the one addition,
    and it is what the importer deliberately does not have: a **number-blind**
    name lookup, which only makes sense when a human is going to look at the
    result. Building it here rather than widening ``CatalogIndex`` keeps the
    importer unable to auto-link off it.
    """

    by_name: dict = field(default_factory=dict)
    by_name_number: dict = field(default_factory=dict)
    by_core_number: dict = field(default_factory=dict)


def build_pairing_index(cards) -> PairingIndex:
    """Build the index ONCE, over the whole catalog, and reuse it across items.

    Building it per parked item would walk 31,603 rows per row of the queue,
    which is the one way to turn an in-memory join into a timeout.
    """
    by_name: dict = defaultdict(list)
    by_name_number: dict = defaultdict(list)
    by_core_number: dict = defaultdict(list)
    for card in cards:
        name = normalize_name(card.name)
        core = core_name(card.name)
        language = coerce_language(getattr(card, "language", None))
        by_name[(name, language)].append(card)
        for key in number_keys(normalize_number(card.number)):
            by_name_number[(name, key, language)].append(card)
            by_core_number[(core, key, language)].append(card)
    return PairingIndex(dict(by_name), dict(by_name_number), dict(by_core_number))


def identity_of(item) -> tuple[str, str]:
    """``(name, number)`` to search on, from the item's OWN fields.

    ``admin_item_name`` first — ``display_name_override`` is an admin's typed
    English name and is the single best signal we have on a JP card whose stored
    name is in script the matcher cannot normalize. One rule everywhere
    (CLAUDE.md, name resolution).

    The number is then **split back off** the name. An inventory item has no
    ``card_number`` field: the importer materializes ``"Dragonair #181"`` into
    ``display_name``, so leaving the suffix on would normalize to
    ``"dragonair 181"`` and miss the catalog's ``"dragonair"`` every single time.
    """
    name = admin_item_name(item) or ""
    number = ""
    match = _TRAILING_NUMBER_RE.search(name)
    if match:
        number = match.group(1)
        name = name[: match.start()]
    return name.strip(), number


def candidates_for(item, index: PairingIndex, *, limit: int = 3) -> list[Candidate]:
    """Ranked catalog candidates for one parked item, best first, ``limit`` at most.

    Three tiers, and the ``why`` string exists so the admin can see which tier
    they are looking at rather than trusting a bare number:

    ==========  =========================================  ============================
    score       condition                                  ``why``
    ==========  =========================================  ============================
    ``1.0``     name **and** number match                   name and number match
    ``0.7``     name matches, number differs                name matches, number differs
    ``0.5``     core name matches (a variant word was       close name, number matches
                dropped), number matches
    ==========  =========================================  ============================

    A card reachable by more than one tier is offered **once**, at its best score
    — the same card twice in a picker reads as two different printings.

    Nothing below ``MIN_SCORE`` is returned, and there is no fourth, looser tier.
    Lowering that floor "to give the admin more to look at" re-introduces the
    promo mispairing this whole feature exists to stop.
    """
    name, number = identity_of(item)
    full = normalize_name(name)
    if not full:  # a fully non-ASCII name is "no evidence", never a match
        return []
    language = coerce_language(getattr(item, "language", None))
    keys = number_keys(normalize_number(number))

    # card_id -> (score, why). Best score wins; a tie keeps the earlier (stronger)
    # tier's wording, which is why the strongest tier is scored first.
    scored: dict[str, tuple[float, str]] = {}
    by_id: dict = {}

    def _offer(cards, score: float, why: str) -> None:
        for card in cards:
            by_id.setdefault(card.card_id, card)
            if scored.get(card.card_id, (0.0, ""))[0] < score:
                scored[card.card_id] = (score, why)

    for key in keys:
        _offer(index.by_name_number.get((full, key, language), []),
               1.0, "name and number match")
    # Number-blind, so it also covers an item carrying no number at all — the
    # honest reading there is still "we matched the name and could not compare
    # numbers", which is exactly what this tier means.
    _offer(index.by_name.get((full, language), []),
           0.7, "name matches, number differs")
    for key in keys:
        _offer(index.by_core_number.get((core_name(name), key, language), []),
               0.5, "close name, number matches")

    ranked = sorted(
        (
            (score, why, by_id[card_id])
            for card_id, (score, why) in scored.items()
            if score >= MIN_SCORE
        ),
        # ``card_id`` breaks a tie so the order is stable across requests; a list
        # that reshuffles between renders is a list nobody can point at.
        key=lambda row: (-row[0], row[2].card_id),
    )
    return [_candidate(card, score, why) for score, why, card in ranked[:limit]]


def _candidate(card, score: float, why: str) -> Candidate:
    """Project a catalog card into a Candidate.

    The price comes from ``_market_price(card, "normal")`` — the ONE shared
    finish-aware lookup (``models/inventory.py``). Do not re-implement price
    selection: CLAUDE.md records that a second copy of that fallback walk is how
    174 of 213 live items once went unpriced. A parked item has no verified
    finish to pass (it has no catalog link at all), so ``"normal"`` is supplied to
    buy the whole fallback walk.
    """
    return Candidate(
        card_id=card.card_id,
        name=card.name,
        set_id=card.set_id,
        set_name=card.set_name,
        number=card.number,
        rarity=card.rarity,
        image_small=getattr(card.images, "small", "") or "",
        market_price=_market_price(card, "normal"),
        detail=getattr(card, "detail", None),
        last_synced_at=getattr(card, "last_synced_at", None),
        score=score,
        why=why,
    )


def suggestions_for(items, index: PairingIndex, *, limit: int = 3) -> SuggestionsResponse:
    """Suggestions for every parked item, plus the count the dashboard quotes.

    An item with **no** candidates is still listed. A parked card with nothing to
    suggest is the queue's most common row, and dropping it would hide work from
    the page that exists to show it — it is only excluded from
    ``items_with_candidates``, which means "cards you can act on".
    """
    rows = [
        ItemSuggestions(item_id=item.item_id,
                        candidates=candidates_for(item, index, limit=limit))
        for item in items
    ]
    return SuggestionsResponse(
        items=rows,
        items_with_candidates=sum(1 for row in rows if row.candidates),
    )
