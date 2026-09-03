"""Generic, validated filters for the admin inventory search — RFC 0011 §B.

The admin table offers thirty-three columns and the filter panel covered twelve of
them. Closing that gap with one named query parameter per field would have put a
~45-parameter signature on ``GET /admin/inventory/search`` and required a parameter, a
test and a frontend branch for every field added — which is precisely how the panel came
to cover a third of the table in the first place. So coverage is a **data** problem here,
not a code one: :data:`FILTERABLE_FIELDS` declares the field and the KIND of control it
deserves, and the frontend renders from the same declaration.

**One evaluator, two spellings.** The twelve pre-existing named parameters
(``status``, ``min_price``, …) keep working and are re-expressed as :class:`FieldFilter`
objects evaluated by :func:`apply_filters`. Two *implementations* of a filter is the
"two definitions of countability" failure CLAUDE.md warns about under the ledger — one
of them drifts, and two filters that look identical quietly return different sets.

Four named parameters are deliberately NOT expressible here and keep their hand-written
bodies in the router, because each does something a field comparison cannot:

* ``name`` — ``_item_matches_name`` searches notes as well as names, which is what makes
  a Japanese card with no readable name findable at all;
* ``condition`` — ``_parse_condition_query`` splits ``"LP+"`` into tier + modifier, and a
  bare tier means the whole tier including its modifiers;
* ``min_price`` / ``max_price`` — ``_effective_price`` falls back to cost when no market
  figure is known;
* ``set_id`` / ``card_number`` / ``artist`` — catalog joins, not item fields.

**Nothing here is ever a silent no-op.** An unknown field, or an operator the field's
kind does not support, raises — and the router turns that into a 422. A filter that
quietly does nothing is indistinguishable from a list that is pulling everything, which
is the exact report ``_validate_triage_reason`` was written to answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from merlins_collection.models.inventory import InventoryItem


class FilterOp(StrEnum):
    """What a filter does to its field. Mirrored verbatim in TypeScript (T4)."""

    CONTAINS = "contains"
    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    ISNULL = "isnull"
    NOTNULL = "notnull"


class FieldKind(StrEnum):
    """The control a field deserves — the answer to the owner's "max/min, dropdown,
    or text input?" question, declared once and read by both halves."""

    TEXT = "text"
    SELECT = "select"
    RANGE = "range"
    DATE_RANGE = "dateRange"
    PRESENCE = "presence"
    #: RFC 0023 T5 — a `list[str]` field (`finish_attributes`). `contains`
    #: means list MEMBERSHIP ("is one of the tags on this item"), never a
    #: substring inside one entry — the opposite reading `TEXT`'s `contains`
    #: has, which is why this needed its own kind rather than reusing TEXT.
    LIST_CONTAINS = "listContains"


#: Every field an admin can filter on, and the KIND of control it deserves.
#:
#: Two picks were argued for rather than defaulted:
#:
#: * ``card_id`` is PRESENCE, not TEXT. Nobody types ``en:sv3pt5-158`` from memory; the
#:   question actually asked at that column is "which of my cards are unlinked", and
#:   that is one dropdown.
#: * ``acquired_show_id`` is SELECT, on the same reasoning that makes ``location`` one:
#:   the values are a managed list, and a substring match across show names is not a
#:   question anyone has.
FILTERABLE_FIELDS: dict[str, FieldKind] = {
    # --- range: a Min and a Max box ---
    "cost_basis": FieldKind.RANGE,
    "current_market_value": FieldKind.RANGE,
    "sticker_price": FieldKind.RANGE,
    "listed_price": FieldKind.RANGE,
    "market_value_at_purchase": FieldKind.RANGE,
    "grade": FieldKind.RANGE,
    # --- dateRange: a From and a To box ---
    "acquired_at": FieldKind.DATE_RANGE,
    "reviewed_at": FieldKind.DATE_RANGE,
    # Added to the model by RFC 0011 T5. Until then `getattr` yields None on every row,
    # so a filter on it matches nothing — correct, and harmless.
    "no_catalog_match_at": FieldKind.DATE_RANGE,
    # --- select: a closed list of values ---
    "status": FieldKind.SELECT,
    "kind": FieldKind.SELECT,
    "condition": FieldKind.SELECT,
    "condition_modifier": FieldKind.SELECT,
    "location": FieldKind.SELECT,
    "language": FieldKind.SELECT,
    "finish": FieldKind.SELECT,
    # --- listContains: does the list carry this exact tag? ---
    "finish_attributes": FieldKind.LIST_CONTAINS,
    "company": FieldKind.SELECT,
    "product_type": FieldKind.SELECT,
    "factory_sealed": FieldKind.SELECT,
    "needs_review": FieldKind.SELECT,
    "no_catalog_match": FieldKind.SELECT,
    "acquired_show_id": FieldKind.SELECT,
    # --- presence: "has one" / "does not" ---
    "card_id": FieldKind.PRESENCE,
    "consignment": FieldKind.PRESENCE,
    "display_name_override": FieldKind.PRESENCE,
    # --- text: substring, case-insensitive ---
    "display_name": FieldKind.TEXT,
    "product_name": FieldKind.TEXT,
    "description": FieldKind.TEXT,
    "review_reason": FieldKind.TEXT,
    "language_note": FieldKind.TEXT,
    "cert_number": FieldKind.TEXT,
    "grade_label": FieldKind.TEXT,
    "sticker_notes": FieldKind.TEXT,
    "notes": FieldKind.TEXT,
    "value_note": FieldKind.TEXT,
    "tcg_url": FieldKind.TEXT,
    "lineage_id": FieldKind.TEXT,
    "predecessor_item_id": FieldKind.TEXT,
    "item_id": FieldKind.TEXT,
}

#: Which operators each kind accepts. A `contains` on a SELECT is a caller mistake, not
#: a wider match — the whole point of a closed list is that you pick from it.
OPS_BY_KIND: dict[FieldKind, frozenset[FilterOp]] = {
    FieldKind.TEXT: frozenset({FilterOp.CONTAINS, FilterOp.EQ}),
    FieldKind.SELECT: frozenset({FilterOp.EQ}),
    FieldKind.RANGE: frozenset({FilterOp.GTE, FilterOp.LTE}),
    FieldKind.DATE_RANGE: frozenset({FilterOp.GTE, FilterOp.LTE}),
    FieldKind.PRESENCE: frozenset({FilterOp.ISNULL, FilterOp.NOTNULL}),
    FieldKind.LIST_CONTAINS: frozenset({FilterOp.CONTAINS}),
}


@dataclass(frozen=True)
class FieldFilter:
    """One parsed ``{field}:{op}:{value}`` triple."""

    field: str
    op: FilterOp
    value: str


def parse_filter(raw: str) -> FieldFilter:
    """Parse one ``filter=`` triple. Raises ``ValueError`` on a bad shape.

    Split on the FIRST TWO colons only. A card id contains a colon —
    ``card_id:eq:en:base1-4`` is a real query — so an unbounded split loses the value.

    Field validity is NOT checked here; that is :func:`validate_filters`' job, so the
    router can turn an unknown field into a 422 carrying the list of valid ones.
    """
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise ValueError(
            f"Malformed filter {raw!r}. Expected {{field}}:{{op}}:{{value}}."
        )
    field, op, value = parts
    try:
        parsed_op = FilterOp(op)
    except ValueError as exc:
        raise ValueError(
            f"Unknown filter operator {op!r} in {raw!r}. "
            f"Expected one of: {', '.join(sorted(FilterOp))}."
        ) from exc
    return FieldFilter(field=field, op=parsed_op, value=value)


def _validate_value(f: FieldFilter, kind: FieldKind) -> None:
    """Reject a bound the field's kind cannot compare against.

    **Checked here, not during evaluation.** ``apply_filters`` is a list comprehension,
    so on an empty result set it never calls ``_matches`` and a nonsense bound like
    ``acquired_at:gte:yesterday`` sailed through as a 200. That made validity depend on
    how many rows happened to exist — a caller mistake that reports itself only
    sometimes is worse than one that never does, because it teaches the caller the query
    is fine. Validating at parse time also means the 422 lands *before* the full
    ``list_inventory()`` read.
    """
    if f.op not in (FilterOp.GTE, FilterOp.LTE):
        return
    if kind is FieldKind.DATE_RANGE:
        try:
            date.fromisoformat(f.value)
        except ValueError as exc:
            raise ValueError(
                f"Filter field {f.field!r} needs an ISO date (YYYY-MM-DD); "
                f"got {f.value!r}."
            ) from exc
    elif kind is FieldKind.RANGE:
        try:
            Decimal(f.value)
        except InvalidOperation as exc:
            raise ValueError(
                f"Filter field {f.field!r} needs a number; got {f.value!r}."
            ) from exc


def validate_filters(raws: list[str]) -> list[FieldFilter]:
    """Parse and validate every ``filter`` parameter, raising ``ValueError`` on any.

    Four distinct mistakes get four distinct messages — a malformed triple, an unknown
    field, an operator the field's kind does not support, and a bound that kind cannot
    compare against — because "your filter is wrong" without saying how is barely better
    than ignoring it.
    """
    parsed: list[FieldFilter] = []
    for raw in raws:
        f = parse_filter(raw)
        kind = FILTERABLE_FIELDS.get(f.field)
        if kind is None:
            raise ValueError(
                f"Unknown filter field {f.field!r}. "
                f"Expected one of: {', '.join(sorted(FILTERABLE_FIELDS))}."
            )
        if f.op not in OPS_BY_KIND[kind]:
            raise ValueError(
                f"Filter field {f.field!r} is a {kind.value} field and does not support "
                f"{f.op.value!r}. Expected one of: "
                f"{', '.join(sorted(OPS_BY_KIND[kind]))}."
            )
        _validate_value(f, kind)
        parsed.append(f)
    return parsed


def _comparable(value: Any, raw: str) -> tuple[Any, Any]:
    """Both sides as one comparable type. Raises ``ValueError`` on an unparseable bound.

    **``Decimal(str(value))``, never ``float(value)``.** Money on these models is
    ``Decimal``, and routing a bound through binary float is how a ``100.00`` boundary
    starts excluding a $100.00 card.
    """
    if isinstance(value, datetime):
        return value.date(), date.fromisoformat(raw)
    if isinstance(value, date):
        return value, date.fromisoformat(raw)
    try:
        return Decimal(str(value)), Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{raw!r} is not a number") from exc


def _matches(item: InventoryItem, f: FieldFilter) -> bool:
    """Whether one item satisfies one filter.

    ``getattr(item, field, None)`` throughout, never attribute access: the four item
    kinds carry different fields, so a sealed box has no ``condition`` and a raw single
    has no ``grade``. A missing attribute and a ``None`` value are the same answer here
    — the item does not have one.
    """
    value = getattr(item, f.field, None)

    if f.op is FilterOp.ISNULL:
        return value is None
    if f.op is FilterOp.NOTNULL:
        return value is not None

    if value is None:
        # Every remaining op is a positive claim ABOUT a value. A row that has no value
        # cannot satisfy one, and must not fall through to a truthy default.
        return False

    if f.op is FilterOp.CONTAINS:
        # `finish_attributes` (LIST_CONTAINS) is the one field whose value is
        # a list, not a scalar. Checked BEFORE the generic substring branch —
        # `str(["1st Edition"]).lower()` contains "edition" as a plain Python
        # repr, which would make a TEXT-style substring match falsely agree
        # with a whole-tag query and silently collapse the distinction
        # `TestListContains` exists to pin.
        if isinstance(value, list):
            return any(f.value.lower() == str(v).lower() for v in value)
        return f.value.lower() in str(value).lower()
    if f.op is FilterOp.EQ:
        # Booleans arrive as "true"/"false" from a browser select, and StrEnums compare
        # as their value. `str()` on both sides is what lets one branch serve all three.
        return str(value).lower() == f.value.lower()

    left, right = _comparable(value, f.value)
    if f.op is FilterOp.GTE:
        return left >= right
    return left <= right


def apply_filters(
    items: list[InventoryItem], filters: list[FieldFilter]
) -> list[InventoryItem]:
    """AND-combine every filter. Raises ``ValueError`` on an unparseable bound."""
    for f in filters:
        items = [i for i in items if _matches(i, f)]
    return items
