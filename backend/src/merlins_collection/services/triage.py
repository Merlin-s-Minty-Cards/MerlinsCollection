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

from merlins_collection.models.inventory import InventoryItem, Language


def is_flagged(item: InventoryItem) -> bool:
    """Stored: someone (a human or an importer) put this here on purpose."""
    return item.needs_review


def is_missing_card_id(item: InventoryItem) -> bool:
    """Derived: a catalog-linkable item that never matched a catalog row.

    ``getattr``, not ``item.card_id``: only the raw and graded kinds carry the
    field at all. Sealed product and bulk lots have no catalog link BY DESIGN,
    so a plain attribute access would both raise ``AttributeError`` and, if
    defaulted to None, drag every sealed box into the queue permanently.
    """
    if not hasattr(item, "card_id"):
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


def needs_triage(item: InventoryItem) -> bool:
    """True if ANY reason applies — the union the Triage list is built from.

    Every other filter on the admin search is AND-combined, which cannot express
    "flagged OR unlinked OR unnamed". This is the one OR, and it deliberately
    yields each item ONCE however many reasons it qualifies under: parallel
    per-reason queues would show the same card repeatedly and get it "fixed"
    twice.
    """
    return any(matches(item) for matches in TRIAGE_REASONS.values())


def count_by_reason(items: Iterable[InventoryItem]) -> dict[str, int]:
    """Per-reason hit counts. Reasons overlap, so these do NOT sum to the total."""
    items = list(items)
    return {name: sum(1 for i in items if matches(i)) for name, matches in TRIAGE_REASONS.items()}
