"""Sort keys for the admin Consignors table — RFC 0013 T4d.

Mirrors ``shows_sort.py``'s pattern via the shared ``table_sort`` factory
(RFC 0013 T4a): missing values sort LAST in both directions, an unknown
field parses to ``None`` (the router turns that into a 422), and
``sort=<field>_<direction>`` splits on the LAST underscore.

**Field list corrected against ``models.business.Consignor``, not the RFC's
illustrative table.** RFC 0013's Detailed Design section names a
``created_at`` field — ``Consignor`` has no such field (no field on the
model records when a consignor was created).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from merlins_collection.models.business import Consignor
from merlins_collection.services.table_sort import build_sort_registry


def _text(field: str) -> Callable[[Consignor], str | None]:
    def extract(c: Consignor) -> str | None:
        value = getattr(c, field, None)
        if value is None or value == "":
            return None
        return str(value).lower()

    return extract


def _money(field: str) -> Callable[[Consignor], float | None]:
    def extract(c: Consignor) -> float | None:
        value = getattr(c, field, None)
        return None if value is None else float(value)

    return extract


def _flag(field: str) -> Callable[[Consignor], bool | None]:
    def extract(c: Consignor) -> bool | None:
        value = getattr(c, field, None)
        return None if value is None else bool(value)

    return extract


SORT_FIELDS: dict[str, Callable[[Consignor], Any]] = {
    "name": _text("name"),
    "email": _text("email"),
    "phone": _text("phone"),
    "payout_percent": _money("payout_percent"),
    "archived": _flag("archived"),
}

#: No aliases yet — nothing external has sent a differently-spelled key for
#: this table. Kept as a seam, same as `shows_sort.SORT_ALIASES`.
SORT_ALIASES: dict[str, str] = {}


_REGISTRY = build_sort_registry(SORT_FIELDS, SORT_ALIASES)


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    return _REGISTRY.resolve_sort_field(field)


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("name", False)`` for ``"name_asc"``; ``None`` if unusable."""
    return _REGISTRY.parse_sort(sort)


def sort_consignors(consignors: list[Consignor], sort: str | None) -> list[Consignor]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    return _REGISTRY.sort_items(consignors, sort)
