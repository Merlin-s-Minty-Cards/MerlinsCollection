"""Triage reasons — the one place that decides why an item needs attention.

Triage IS the ``needs_review`` queue (docs/plans/rfc-0008/t11-triage-tab.md). No
second flag exists. What this module adds is the *derived* reasons, which are
computed rather than stored, and the single predicate set shared by the two
consumers that must never disagree:

* ``GET /admin/inventory/search?triage=true`` — the list itself;
* ``GET /admin/triage/counts`` — the sidebar badge.

A badge that counts differently from the list it links to is worse than no badge:
the admin clicks through, finds fewer cards than promised, and stops trusting it.

**Stored vs derived.** ``flagged`` is stored state an admin clears explicitly.
The other two are pure functions of fields the repair tools already write, so
they are *self-healing* — link the card or type the name and the row leaves the
list on its own, with nothing to clean up. That is why they stay computed instead
of being baked into ``needs_review`` at write time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from merlins_collection.models.inventory import (
    MACHINE_REVIEW_REASONS,
    InventoryItem,
    ItemStatus,
    Language,
)


def is_flagged(item: InventoryItem) -> bool:
    """Stored: someone (a human or an importer) put this here on purpose."""
    return item.needs_review


def is_missing_card_id(item: InventoryItem) -> bool:
    """Derived: a catalog-linkable item that never matched a catalog row.

    ``getattr``, not ``item.card_id``: only the raw and graded kinds carry the
    field at all. Sealed product and bulk lots have no catalog link BY DESIGN,
    so a plain attribute access would both raise ``AttributeError`` and, if
    defaulted to None, drag every sealed box into the queue permanently.

    ``no_catalog_match`` is an admin's explicit answer that TCGdex does not carry
    this card. It is STORED precisely because this function is derived: without
    it a human could confirm "there is nothing to match" a hundred times and the
    row would return to the queue on the very next read (RFC 0011 §C).

    Note this is a SUPPRESSION inside an existing predicate, not a fourth
    ``TRIAGE_REASONS`` entry. A new reason would keep the card in Triage, which
    is the opposite of what parking is for. A parked item that is ALSO flagged or
    unnamed keeps those reasons and stays — those are real errors, and "the
    catalog does not have it" is not.
    """
    if not hasattr(item, "card_id"):
        return False
    if item.no_catalog_match:
        return False
    return item.card_id is None


def is_missing_english_name(item: InventoryItem) -> bool:
    """Derived: a Japanese item showing a name a customer cannot read.

    A JP item resolves to a JP catalog row by design (``Language`` docstring), so
    the catalog name is Japanese script and the only fix is an admin-authored
    ``display_name_override`` (T10). Not gated on ``card_id``: an unmatched JP
    item still renders its Japanese ``display_name``.
    """
    return item.language is not Language.EN and item.display_name_override is None


# Ordered so the counts payload and the UI's filter dropdown agree without
# either restating the list. Stored reason first, derived after.
TRIAGE_REASONS: dict[str, Callable[[InventoryItem], bool]] = {
    "flagged": is_flagged,
    "missing_card_id": is_missing_card_id,
    "missing_english_name": is_missing_english_name,
}


def reasons_for(item: InventoryItem) -> list[str]:
    """Every reason this item is in the queue, in ``TRIAGE_REASONS`` order.

    ``needs_triage(item)`` is exactly ``bool(reasons_for(item))``, and the two are
    expressed in terms of each other below so they cannot drift: **a row in the
    list with no reason is the defect this function exists to make impossible**,
    and it is the owner's own report (a WHY column reading empty).

    This is also what the API emits, rather than the frontend recomputing the
    same three rules in TypeScript. That mirror was faithful — it was probed, not
    assumed — which is precisely why the drift would have been silent.
    """
    return [name for name, matches in TRIAGE_REASONS.items() if matches(item)]


def needs_triage(item: InventoryItem) -> bool:
    """True if ANY reason applies — the union the Triage list is built from.

    Every other filter on the admin search is AND-combined, which cannot express
    "flagged OR unlinked OR unnamed". This is the one OR, and it deliberately
    yields each item ONCE however many reasons it qualifies under: parallel
    per-reason queues would show the same card repeatedly and get it "fixed"
    twice.
    """
    return bool(reasons_for(item))


def count_by_reason(items: Iterable[InventoryItem]) -> dict[str, int]:
    """Per-reason hit counts. Reasons overlap, so these do NOT sum to the total."""
    items = list(items)
    return {name: sum(1 for i in items if matches(i)) for name, matches in TRIAGE_REASONS.items()}


# ---------------------------------------------------------------------------
# Scope — which items are even eligible for the queue
# ---------------------------------------------------------------------------

#: An item in one of these states will never be corrected, because the card is
#: gone: it has been sold, lost, or handed back to its consignor. Its data
#: quality is history, not work, and leaving it in a queue whose stated goal is
#: to reach zero means the queue can never get there.
TERMINAL_STATUSES = frozenset({
    ItemStatus.SOLD,
    ItemStatus.LOST,
    ItemStatus.RETURNED_TO_CONSIGNOR,
})


def in_triage_scope(item: InventoryItem, *, include_terminal: bool = False) -> bool:
    """Whether this item is in scope for the queue at the requested breadth.

    Called by BOTH the list and ``GET /admin/triage/counts``, for the same reason
    the predicates above are: a badge that counts a different set from the page
    it links to is worse than no badge. Scoping one of the two and forgetting the
    other is the easiest possible way to reintroduce that.
    """
    return include_terminal or item.status not in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Bulk clear — the narrow, safe subset
# ---------------------------------------------------------------------------

#: ``blank_condition`` is EXCLUDED, and this is a money rule, not tidiness. The
#: importer stored ``Condition.NM`` — the most expensive tier — for every card
#: whose condition the sheet left blank, and every customer-facing price scales
#: down from it (LP x0.82, MP x0.58). So an LP card in that state is listed at
#: 1.22x what it is worth and an MP card at 1.72x, in the business's favour.
#: Clearing those flags in bulk silently ratifies that price on every card
#: nobody has checked. Only someone holding the card can fix it, which is why
#: the Triage page grows a condition control instead.
BULK_CLEARABLE_REASONS = frozenset(MACHINE_REVIEW_REASONS - {"blank_condition"})


def is_bulk_clearable(item: InventoryItem) -> bool:
    """Whether a bulk clear may drop this item's ``needs_review`` flag.

    Two conditions, both narrowing:

    1. ``flagged`` is its ONLY reason — an item that is also unlinked or unnamed
       keeps that problem, so clearing the flag would not remove it from the list
       anyway and would only destroy information;
    2. the stored reason is one automation writes. A human's free-text note is
       the one thing in this queue a person deliberately recorded, and a bulk
       button that eats it is strictly worse than no bulk button. Absence of a
       reason is NOT a machine reason: a bare flag carries no evidence of who set
       it, so it is left alone too.
    """
    return reasons_for(item) == ["flagged"] and item.review_reason in BULK_CLEARABLE_REASONS
