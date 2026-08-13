"""Sort keys for the admin inventory table — one registry, one extractor.

``_sort_admin_results`` used to be an if/elif chain over eight field names while the
admin table offered thirty-three columns, so twenty-five headers had no order at all
(RFC 0011 §A). This module is the registry both halves read: ``Column.key`` on the
frontend **is** a key of ``SORT_FIELDS`` here, because the page sends
``f"{key}_{direction}"`` and :func:`parse_sort` splits on the LAST underscore.

Three properties are load-bearing and each has a test:

* **missing sorts LAST in both directions.** Achieved by partitioning, not by a ``±inf``
  sentinel — a sentinel has to know ``reverse``, and only ever worked for numbers, so
  blank strings bunched at whichever end the admin was not looking at.
* **condition has a real ordinal rank.** ``str(condition)`` sorted alphabetically and
  ignored ``condition_modifier`` entirely, rendering an ``LP+`` and an ``LP-`` card
  identically — the exact distinction RFC 0008 T2 went to trouble to store in two
  separate fields.
* **an unknown field raises, it does not shrug.** :func:`parse_sort` returns ``None`` and
  the router turns that into a 422. A silently unsorted list is indistinguishable from a
  column that has no order, which is the failure class ``_validate_triage_reason`` was
  written to eliminate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    InventoryItem,
)
from merlins_collection.services.card_text import admin_item_name

#: Worst-to-best, so a bigger rank is a better card and ``asc`` means worst-first — the
#: same direction money sorts in. Modifier offsets apply WITHIN a tier, which is the
#: whole point: an ``LP+`` is an LP, but nicer.
_TIER_ORDER: tuple[Condition, ...] = (
    Condition.DMG,
    Condition.HP,
    Condition.MP,
    Condition.LP,
    Condition.NM,
)

_MODIFIER_OFFSET: dict[ConditionModifier | None, int] = {
    ConditionModifier.MINUS: 0,
    None: 1,
    ConditionModifier.PLUS: 2,
}


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------
#
# Every one of these returns ``None`` for "this item has no value here", and every one
# reaches the field with ``getattr(item, field, None)`` rather than attribute access.
# The four item kinds carry different fields — a sealed box has no ``condition`` and a
# raw single has no ``grade`` — so plain access would raise ``AttributeError`` on a
# perfectly ordinary row.


def _condition_rank(item: InventoryItem) -> int | None:
    """Ordinal condition, modifier included. Higher is better; ``None`` when ungraded."""
    condition = getattr(item, "condition", None)
    if condition is None:
        return None
    try:
        tier = _TIER_ORDER.index(Condition(condition))
    except ValueError:
        return None
    modifier = getattr(item, "condition_modifier", None)
    return tier * 3 + _MODIFIER_OFFSET.get(modifier, 1)


def _money(field: str) -> Callable[[InventoryItem], float | None]:
    def extract(item: InventoryItem) -> float | None:
        value = getattr(item, field, None)
        return None if value is None else float(value)

    return extract


def _text(field: str) -> Callable[[InventoryItem], str | None]:
    def extract(item: InventoryItem) -> str | None:
        value = getattr(item, field, None)
        # An empty string is "not set" for sorting purposes, so it joins the missing
        # bucket rather than sorting to the top of an ascending list — which is what
        # made blank cells cluster at the wrong end before RFC 0011.
        if value is None or value == "":
            return None
        return str(value).lower()

    return extract


def _moment(field: str) -> Callable[[InventoryItem], float | None]:
    def extract(item: InventoryItem) -> float | None:
        value = getattr(item, field, None)
        if isinstance(value, datetime):
            # A naive stored value is read as UTC rather than as local time: these are
            # server-stamped timestamps, and guessing the server's zone would make the
            # order depend on where the process happens to run.
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.timestamp()
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day,
                            tzinfo=timezone.utc).timestamp()
        return None

    return extract


def _flag(field: str) -> Callable[[InventoryItem], bool | None]:
    def extract(item: InventoryItem) -> bool | None:
        value = getattr(item, field, None)
        return None if value is None else bool(value)

    return extract


def _effective_name(item: InventoryItem) -> str | None:
    """The name an admin sees — ``display_name_override`` first, then the fallbacks.

    Delegates to ``services.card_text.admin_item_name``, the ONE server-side authority.
    Inlining ``display_name or product_name`` here would be a fifth copy of a rule
    CLAUDE.md already keeps in four places, and the first one to drift.
    """
    name = admin_item_name(item)
    return name.lower() if name else None


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

SORT_FIELDS: dict[str, Callable[[InventoryItem], Any]] = {
    # Identity / effective name
    "display_name": _effective_name,
    "item_id": _text("item_id"),
    "card_id": _text("card_id"),
    # Classification
    "status": _text("status"),
    "kind": _text("kind"),
    "condition": _condition_rank,
    "condition_modifier": _text("condition_modifier"),
    "language": _text("language"),
    "finish": _text("finish"),
    "location": _text("location"),
    "product_name": _text("product_name"),
    "product_type": _text("product_type"),
    "description": _text("description"),
    # Money
    "cost_basis": _money("cost_basis"),
    "current_market_value": _money("current_market_value"),
    "sticker_price": _money("sticker_price"),
    "listed_price": _money("listed_price"),
    "market_value_at_purchase": _money("market_value_at_purchase"),
    "grade": _money("grade"),
    # Dates
    "acquired_at": _moment("acquired_at"),
    "reviewed_at": _moment("reviewed_at"),
    "cert_verified_at": _moment("cert_verified_at"),
    # RFC 0011 T5 adds this field to the model. Until then `getattr` yields None on
    # every row, so the column simply sorts as all-missing — correct, and harmless.
    "no_catalog_match_at": _moment("no_catalog_match_at"),
    # Flags
    "needs_review": _flag("needs_review"),
    "factory_sealed": _flag("factory_sealed"),
    "no_catalog_match": _flag("no_catalog_match"),
    # Presence, not the terms object: "consigned or owned" is the question the Ownership
    # column asks, and ConsignmentTerms is not comparable.
    "consignment": lambda item: getattr(item, "consignment", None) is not None,
    # Graded
    "company": _text("company"),
    "cert_number": _text("cert_number"),
    "grade_label": _text("grade_label"),
    # Free text
    "notes": _text("notes"),
    "value_note": _text("value_note"),
    "sticker_notes": _text("sticker_notes"),
    "review_reason": _text("review_reason"),
    "display_name_override": _text("display_name_override"),
    "tcg_url": _text("tcg_url"),
    # Provenance
    "acquired_show_id": _text("acquired_show_id"),
    "lineage_id": _text("lineage_id"),
    "predecessor_item_id": _text("predecessor_item_id"),
}

#: Kept for compatibility. ``price`` is what the customer-facing sort has always sent,
#: and ``name`` is what ``_sort_admin_results`` accepted alongside ``display_name``.
#: Dropping either would silently unsort a caller we do not control.
SORT_ALIASES: dict[str, str] = {
    "price": "current_market_value",
    "name": "display_name",
}


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    resolved = SORT_ALIASES.get(field, field)
    return resolved if resolved in SORT_FIELDS else None


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("cost_basis", True)`` for ``"cost_basis_desc"``; ``None`` if unusable.

    ``rsplit`` on the LAST underscore, because field names contain underscores and
    directions do not. **Do not change this without re-checking every ``Column.key``**
    on the frontend — the two are the same string by design.
    """
    parts = sort.rsplit("_", 1)
    if len(parts) != 2 or parts[1] not in ("asc", "desc"):
        return None
    resolved = resolve_sort_field(parts[0])
    if resolved is None:
        return None
    return resolved, parts[1] == "desc"


def sort_items(
    items: list[InventoryItem], sort: str | None
) -> list[InventoryItem]:
    """Sort by the requested field. **Missing values sort LAST in both directions.**

    The partition is the whole trick. ``sorted(reverse=True)`` reverses everything
    including any sentinel you might put in the key, so "missing last" cannot be
    expressed as a key at all — it has to be a separate bucket appended after the sort.

    Callers reach this through the router, which validates first; the ``None`` guard
    below is belt to that's braces rather than a second policy.
    """
    if sort is None:
        return items
    parsed = parse_sort(sort)
    if parsed is None:
        return items
    field, reverse = parsed
    extract = SORT_FIELDS[field]

    present = [i for i in items if extract(i) is not None]
    missing = [i for i in items if extract(i) is None]
    present.sort(key=extract, reverse=reverse)
    return present + missing
