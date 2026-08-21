"""Sort keys for the admin Transactions archive (History) — RFC 0013 T4c.

Mirrors ``shows_sort.py``'s pattern via the shared ``table_sort`` factory
(RFC 0013 T4a): missing values sort LAST in both directions, an unknown
field parses to ``None`` (the router turns that into a 422), and
``sort=<field>_<direction>`` splits on the LAST underscore.

**Scope note (RFC 0013 Detailed Design §4):** the History page keeps its
``TransactionGroups`` grouped, lineage-aware rendering — a five-card sale
must read as one line, not five (CLAUDE.md's `batch_id` grouping rules).
This registry sorts the FLAT rows the router returns
(``GET /admin/transactions``); the page's own group-order control is a
separate, lightweight piece built on top of these rows, not a flattening
of the grouped view.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as date_type
from typing import Any

from merlins_collection.models.business import Transaction
from merlins_collection.services.table_sort import build_sort_registry


def _text(field: str) -> Callable[[Transaction], str | None]:
    def extract(txn: Transaction) -> str | None:
        value = getattr(txn, field, None)
        if value is None or value == "":
            return None
        return str(value).lower()

    return extract


def _money(field: str) -> Callable[[Transaction], float | None]:
    def extract(txn: Transaction) -> float | None:
        value = getattr(txn, field, None)
        # Explicit `is None`, never falsiness: `fee` and `amount` can be a
        # real, present `0`, and falsiness would wrongly bucket that as
        # missing and sort it last.
        return None if value is None else float(value)

    return extract


def _date(field: str) -> Callable[[Transaction], date_type | None]:
    def extract(txn: Transaction) -> date_type | None:
        return getattr(txn, field, None)

    return extract


SORT_FIELDS: dict[str, Callable[[Transaction], Any]] = {
    "date": _date("date"),
    "type": _text("type"),
    "category": _text("category"),
    "item_id": _text("item_id"),
    "amount": _money("amount"),
    "fee": _money("fee"),
    "payment_method": _text("payment_method"),
    "show_id": _text("show_id"),
}

#: No aliases yet — nothing external has sent a differently-spelled key for
#: this table. Kept as a seam, same as `shows_sort.SORT_ALIASES`.
SORT_ALIASES: dict[str, str] = {}


_REGISTRY = build_sort_registry(SORT_FIELDS, SORT_ALIASES)


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or ``None`` if it means nothing."""
    return _REGISTRY.resolve_sort_field(field)


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """``("amount", True)`` for ``"amount_desc"``; ``None`` if unusable."""
    return _REGISTRY.parse_sort(sort)


def sort_transactions(txns: list[Transaction], sort: str | None) -> list[Transaction]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    return _REGISTRY.sort_items(txns, sort)
