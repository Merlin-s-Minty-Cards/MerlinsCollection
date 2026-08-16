"""Sort keys for the admin Slabs list — RFC 0013 T4, last of six registries.

Mirrors ``locations_sort.py``'s pattern via the shared ``table_sort`` factory:
missing values sort LAST in both directions, an unknown field parses to
``None`` (the router turns that into a 422), and ``sort=<field>_<direction>``
splits on the LAST underscore.

**Rows are plain ``dict``s, not a Pydantic model** — same shape issue as
Locations. ``GET /admin/slabs`` (``routers/admin/slabs.py::_slab_row``)
returns a dict, not a ``GradedInventoryItem``.

**Two fields are STRINGIFIED Decimals in the dict** (``grade``,
``cost_basis`` — ``str(item.grade)`` / ``str(item.cost_basis)``, done so a
Decimal survives JSON without becoming a float). Their extractors parse the
string back to a number; comparing the raw strings would sort ``"9"`` after
``"10"``.

**Scope correction against the RFC's illustrative table:** RFC 0013 names
``buy_price`` — the real dict key is ``cost_basis``. RFC 0013 also lists
``priced`` as a field; it is not a dict key at all. It is DERIVED, exactly
the way the router's own ``?priced=`` query filter already computes it
(``routers/admin/slabs.py`` ~line 159): ``row["market_value"] is not None``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from merlins_collection.services.table_sort import build_sort_registry

_SlabRow = dict[str, Any]


def _text(field: str) -> Callable[[_SlabRow], str | None]:
    def extract(row: _SlabRow) -> str | None:
        value = row.get(field)
        if value is None or value == "":
            return None
        return str(value).lower()

    return extract


def _number_from_string(field: str) -> Callable[[_SlabRow], float | None]:
    """``grade``/``cost_basis`` are stringified Decimals in the dict — parse
    back to a float so ``"9"`` sorts below ``"10"`` instead of above it."""

    def extract(row: _SlabRow) -> float | None:
        value = row.get(field)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return extract


def _priced(row: _SlabRow) -> bool:
    """Mirrors the router's own ``?priced=`` filter: a slab is "priced" iff
    it has a resolved ``market_value``, never a separate stored flag."""
    return row.get("market_value") is not None


SORT_FIELDS: dict[str, Callable[[_SlabRow], Any]] = {
    "cert_number": _text("cert_number"),
    "company": _text("company"),
    "grade": _number_from_string("grade"),
    "cost_basis": _number_from_string("cost_basis"),
    "status": _text("status"),
    "location": _text("location"),
    "name": _text("name"),
    "priced": _priced,
}

#: No aliases yet, but kept as a seam: the RFC's illustrative name
#: (``buy_price``) does NOT alias to ``cost_basis`` here on purpose — nothing
#: external has ever sent that spelling, and adding a silent alias for a name
#: that only ever existed in the RFC's prose would be inventing a contract no
#: caller relies on.
SORT_ALIASES: dict[str, str] = {}


_REGISTRY = build_sort_registry(SORT_FIELDS, SORT_ALIASES)


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    return _REGISTRY.resolve_sort_field(field)


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("grade", True)`` for ``"grade_desc"``; ``None`` if unusable."""
    return _REGISTRY.parse_sort(sort)


def sort_slabs(rows: list[_SlabRow], sort: str | None) -> list[_SlabRow]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    return _REGISTRY.sort_items(rows, sort)
