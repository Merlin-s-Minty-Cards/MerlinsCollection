"""Sort keys for the admin Locations table — RFC 0013 T4e.

Mirrors ``shows_sort.py``'s pattern via the shared ``table_sort`` factory
(RFC 0013 T4a): missing values sort LAST in both directions, an unknown
field parses to ``None`` (the router turns that into a 422), and
``sort=<field>_<direction>`` splits on the LAST underscore.

**Scope correction against the RFC's illustrative table:** RFC 0013 names
``item_count`` as a Locations field. ``GET /admin/locations``
(``services.locations.get_locations``) returns plain
``{"value": str, "label": str}`` rows — there is no ``item_count`` on that
response, and building one would require a new inventory-count aggregate,
out of scope here. This registry sorts what the endpoint actually returns.

Rows here are plain ``dict[str, str]``, not a Pydantic model — the one table
in this RFC where ``table_sort.SortRegistry`` being ``Generic[T]`` rather
than tied to a model is load-bearing rather than decorative.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from merlins_collection.services.table_sort import build_sort_registry

_LocationRow = dict[str, str]


def _text(field: str) -> Callable[[_LocationRow], str | None]:
    def extract(row: _LocationRow) -> str | None:
        value = row.get(field)
        if value is None or value == "":
            return None
        return value.lower()

    return extract


SORT_FIELDS: dict[str, Callable[[_LocationRow], Any]] = {
    "value": _text("value"),
    "label": _text("label"),
}

#: No aliases yet — nothing external has sent a differently-spelled key for
#: this table. Kept as a seam, same as `shows_sort.SORT_ALIASES`.
SORT_ALIASES: dict[str, str] = {}


_REGISTRY = build_sort_registry(SORT_FIELDS, SORT_ALIASES)


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    return _REGISTRY.resolve_sort_field(field)


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("label", False)`` for ``"label_asc"``; ``None`` if unusable."""
    return _REGISTRY.parse_sort(sort)


def sort_locations(
    rows: list[_LocationRow], sort: str | None
) -> list[_LocationRow]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    return _REGISTRY.sort_items(rows, sort)
