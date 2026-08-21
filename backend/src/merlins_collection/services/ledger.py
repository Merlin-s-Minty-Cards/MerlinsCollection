"""The ONE countability predicate for the transaction ledger (RFC 0010 T11).

A void honoured by some aggregates and not others produces two disagreeing sets
of books, which is worse than having no void at all. So there is exactly one
definition of "does this row count", it lives here, and every reader calls it.

Every reader, exhaustively — each has a named test in
``backend/tests/routers/admin/test_transaction_void.py``:

===========================  ==========================================
reader                       where
===========================  ==========================================
``summarize_transactions``   ``routers/admin/analytics.py``
``sell_through_rate``        same
``starting_inventory``       same
``daily_analytics``          same
``list_analytics_dates``     same
show snapshot generator      same (``generate_show_analytics``)
the dashboard's Today tile   reads ``GET /analytics/daily``, so it inherits
``GET /admin/transactions``  **does NOT filter** — it is the archive
===========================  ==========================================

``GET /admin/transactions`` and the item timeline are the two deliberate
non-filterers: the point of an archive is to show what was actually written,
and a void is a thing that was written. They say so in a comment at the call
site, which is the only acceptable reason not to filter.
"""

from __future__ import annotations

from collections.abc import Iterable

from merlins_collection.models.business import Transaction


def is_countable(txn: Transaction) -> bool:
    """True if this row counts toward any total.

    A voided transaction is a record that something was written and then
    withdrawn. It stays readable in the archive and on the item's timeline, and
    it counts toward NOTHING.

    Every aggregate calls this. A reader that inlines ``txn.voided_at is None``
    instead is a second definition, and the failure mode is two sets of books
    that disagree by exactly one sale — which nobody notices until a month-end
    number is wrong.
    """
    return txn.voided_at is None


def countable(txns: Iterable[Transaction]) -> list[Transaction]:
    """The countable subset, in order. Sugar over :func:`is_countable` so a
    reader never has to spell the filter (and so cannot spell it differently)."""
    return [t for t in txns if is_countable(t)]
