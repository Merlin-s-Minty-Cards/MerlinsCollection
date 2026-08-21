"""Sort keys for the admin Shows table — RFC 0013 T4b.

Mirrors ``inventory_sort.py``'s registry pattern via the shared
``table_sort.build_sort_registry`` factory (RFC 0013 T4a): missing values
sort LAST in both directions, an unknown field parses to ``None`` (the
router turns that into a 422), and ``sort=<field>_<direction>`` splits on
the LAST underscore because field names may contain underscores and
directions never do.

**Field list corrected against ``models.business.Show``, not the RFC's
illustrative table.** RFC 0013's Detailed Design section names a
``location`` field — ``Show`` has no such field. The real structured
location is two separate optional fields, ``venue`` and ``city`` (RFC 0008),
which is what ``/admin/shows`` actually renders as columns.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as date_type
from typing import Any

from merlins_collection.models.business import Show
from merlins_collection.services.table_sort import build_sort_registry


def _text(field: str) -> Callable[[Show], str | None]:
    def extract(show: Show) -> str | None:
        value = getattr(show, field, None)
        # An empty string is "not set" for sorting purposes, same rule as
        # inventory_sort._text — a blank joins the missing bucket rather
        # than sorting to the top of an ascending list.
        if value is None or value == "":
            return None
        return str(value).lower()

    return extract


def _money(field: str) -> Callable[[Show], float | None]:
    def extract(show: Show) -> float | None:
        value = getattr(show, field, None)
        return None if value is None else float(value)

    return extract


def _flag(field: str) -> Callable[[Show], bool | None]:
    def extract(show: Show) -> bool | None:
        value = getattr(show, field, None)
        return None if value is None else bool(value)

    return extract


def _date(field: str) -> Callable[[Show], date_type | None]:
    def extract(show: Show) -> date_type | None:
        return getattr(show, field, None)

    return extract


SORT_FIELDS: dict[str, Callable[[Show], Any]] = {
    "name": _text("name"),
    "date": _date("date"),
    "venue": _text("venue"),
    "city": _text("city"),
    "sales_goal": _money("sales_goal"),
    "archived": _flag("archived"),
}

#: No aliases yet — unlike inventory, nothing external has ever sent a
#: differently-spelled Shows sort key. Keep the seam anyway so one can be
#: added the same way inventory's `price`/`name` aliases were.
SORT_ALIASES: dict[str, str] = {}


#: The one registry instance for this table. Built via the shared factory
#: (RFC 0013 T4a) so the missing-last / unknown-field-is-None / last-underscore
#: behaviors live in one place; ``SORT_FIELDS``/``SORT_ALIASES`` above stay the
#: source of truth for what this table can sort by.
_REGISTRY = build_sort_registry(SORT_FIELDS, SORT_ALIASES)


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    return _REGISTRY.resolve_sort_field(field)


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("date", True)`` for ``"date_desc"``; ``None`` if unusable."""
    return _REGISTRY.parse_sort(sort)


def sort_shows(shows: list[Show], sort: str | None) -> list[Show]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    return _REGISTRY.sort_items(shows, sort)
