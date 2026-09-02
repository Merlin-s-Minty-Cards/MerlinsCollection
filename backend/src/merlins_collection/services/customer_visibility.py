"""The ONE per-item customer-visibility predicate for shared inventory.

Extracted from ``routers/inventory.py::customer_visible_items`` (RFC 0016
Council r1 checklist item 2). That function's own docstring calls this a
security boundary: leaking sold/held or bulk/sealed stock is the failure
mode, so the predicate must live in exactly one place and every reader —
the filter-mode router, the chat display hydrator, the public featured
endpoint, and any future customer-facing surface — must call this function
rather than re-derive an equivalent condition.

Lives in ``services/``, not ``routers/inventory.py`` itself, because
``services/bedrock.py`` needs it too and cannot import from
``routers/inventory.py`` without a circular import: that module imports
``dependencies.py`` (for ``get_repo``), and ``dependencies.py`` imports
``BedrockChatService`` from ``services/bedrock.py``. A module that only
depends on ``models/`` — like this one, like ``services/condition_pricing.py``
— sits below both and both can import forward from it.
"""

from __future__ import annotations

from merlins_collection.models.inventory import ItemStatus

# Cards-only customer surface (RFC 0001 owner decision, binding): bulk lots are
# internal-only, and sealed products are hidden too — the search surfaces single
# cards, not booster packs. Only available raw/graded items reach a customer.
CUSTOMER_KINDS = {"raw", "graded"}

# Phase 5 (D3, display scoping): only items physically stored in a
# customer-facing location (the glass display case or a toploader binder page)
# are shown. ``factory_sealed`` items (still in original plastic wrap — a
# condition premium, not a physical location) are also visible regardless of
# location. Items in storage, binders, or with no recorded location stay hidden.
CUSTOMER_VISIBLE_LOCATIONS = frozenset({"glass", "toploader"})


def is_customer_visible(item) -> bool:
    """True when a single inventory item belongs to the customer-visible cohort.

    Available items of a customer-visible kind, stored in a customer-visible
    location (or marked ``factory_sealed``, which confers visibility
    regardless of physical location). ``getattr`` is used for
    ``factory_sealed`` because it only exists on ``RawInventoryItem``; graded
    slabs must have a visible location instead.

    A future exclusion (a ``needs_review`` gate, a new ``RESERVED`` status) is
    made once here and applies to every caller automatically.
    """
    return (
        item.status == ItemStatus.AVAILABLE
        and item.kind in CUSTOMER_KINDS
        and (
            getattr(item, "location", None) in CUSTOMER_VISIBLE_LOCATIONS
            or getattr(item, "factory_sealed", False)
        )
    )
