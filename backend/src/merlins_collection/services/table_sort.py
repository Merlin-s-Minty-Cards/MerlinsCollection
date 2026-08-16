"""Generic sort-registry factory — RFC 0013 T4a.

``inventory_sort.py`` proved this pattern for one table (RFC 0011 T1):
missing values sort LAST in both directions, an unknown field parses to
``None`` rather than shrugging, and ``sort=<field>_<asc|desc>`` splits on the
LAST underscore because field names may contain underscores and directions
never do. Five more tables (Shows, Transactions, Consignors, Locations,
Slabs) need exactly those three properties, so this factory carries them
once — each table still gets its OWN registry instance and its own totality
test; nothing here shares state between tables. ``inventory_sort.py`` itself
is refactored onto this factory in the same change, so its existing test
suite is the regression guard that the refactor is behavior-identical.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SortRegistry(Generic[T]):
    """A table's own ``field name -> extractor`` map, plus the three
    load-bearing behaviors bound to it as methods.

    ``fields`` and ``aliases`` are exposed directly so a totality test can
    assert every column has an entry, the same way
    ``test_inventory_sort.py::TestRegistryIsTotal`` does today.
    """

    fields: dict[str, Callable[[T], Any]]
    aliases: dict[str, str] = field(default_factory=dict)

    def resolve_sort_field(self, field_name: str) -> str | None:
        """The registry key ``field_name`` means, or ``None`` if it means nothing."""
        resolved = self.aliases.get(field_name, field_name)
        return resolved if resolved in self.fields else None

    def parse_sort(self, sort: str) -> tuple[str, bool] | None:
        """``("amount", True)`` for ``"amount_desc"``; ``None`` if unusable.

        Splits on the LAST underscore — do not change this without checking
        every field name this registry serves for a trailing ``_asc``/``_desc``.
        """
        parts = sort.rsplit("_", 1)
        if len(parts) != 2 or parts[1] not in ("asc", "desc"):
            return None
        resolved = self.resolve_sort_field(parts[0])
        if resolved is None:
            return None
        return resolved, parts[1] == "desc"

    def sort_items(self, items: list[T], sort: str | None) -> list[T]:
        """Sort by the requested field. Missing values sort LAST in both
        directions — a partition, not a sentinel, because a sentinel would
        need to know ``reverse`` and only ever works for numbers.

        An unsortable ``sort`` string (``None``, or one that fails to parse)
        returns ``items`` untouched; the router is what turns a bad ``sort``
        into a 422, not this function.
        """
        if sort is None:
            return items
        parsed = self.parse_sort(sort)
        if parsed is None:
            return items
        field_name, reverse = parsed
        extract = self.fields[field_name]

        present = [i for i in items if extract(i) is not None]
        missing = [i for i in items if extract(i) is None]
        present.sort(key=extract, reverse=reverse)
        return present + missing


def build_sort_registry(
    fields: dict[str, Callable[[T], Any]],
    aliases: dict[str, str] | None = None,
) -> SortRegistry[T]:
    """Build a table's own, independent sort registry.

    Each call returns a fresh :class:`SortRegistry` — two tables' registries
    never share a ``fields`` dict, so a field name that means something on one
    table cannot accidentally resolve on another.
    """
    return SortRegistry(fields=dict(fields), aliases=dict(aliases or {}))
