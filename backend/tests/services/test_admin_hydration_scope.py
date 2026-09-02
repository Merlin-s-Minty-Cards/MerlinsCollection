"""RED for RFC 0018 item 3 — hydration scope is a parameter, not a second copy.

`_hydrate_item` filters through `is_customer_visible`, which is CORRECT for the
customer chat and was added as a security fix (Council item 2: without it, a
client-supplied `panel_item_ids` could render withheld stock). It is WRONG for
an admin analyst: an aging-stock or profit answer hydrated through it silently
drops raw-in-storage and bulk-lot items, so the operator sees a shorter list
than the number the same answer just quoted.

One hydrator with an explicit scope, not two hydrators. A second copy is how the
two drift, and the copy that would go stale is a security filter.
"""

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import (
    Condition,
    ItemStatus,
    RawInventoryItem,
)
from merlins_collection.services import bedrock
from merlins_collection.services.customer_visibility import is_customer_visible


@pytest.fixture
def withheld_item(dynamo_repo):
    """An item the CUSTOMER must never see, but the owner certainly owns."""
    item = RawInventoryItem(
        item_id="01ADMINONLY0000000000000000",
        card_id=None,
        status=ItemStatus.AVAILABLE,
        listed_price=Decimal("250.00"),
        cost_basis=Decimal("100.00"),
        acquired_at=date.today(),
        finish="normal",
        condition=Condition.NM,
        location=None,   # WITHHELD from customers — raw stock in storage
    )
    dynamo_repo.put_inventory_item(item)
    return item


def test_the_withheld_item_is_genuinely_invisible_to_the_customer(dynamo_repo, withheld_item):
    """Guard: if this ever passes the fixture stopped testing anything."""
    assert not is_customer_visible(withheld_item)
    assert bedrock._hydrate_item(dynamo_repo, withheld_item.item_id) is None


def test_the_admin_scope_hydrates_what_the_customer_scope_withholds(
    dynamo_repo, withheld_item
):
    """The whole point: an admin answer must not silently lose rows.

    `visible=` takes the predicate, so there is exactly one hydrator and the
    customer default is unchanged — the branch that could go stale is the one
    the security fix lives in, so it must not be the copy.
    """
    card = bedrock._hydrate_item(
        dynamo_repo, withheld_item.item_id, visible=bedrock.ADMIN_VISIBILITY
    )
    assert card is not None
    assert card.item_id == withheld_item.item_id


def test_the_default_is_still_the_customer_predicate(dynamo_repo, withheld_item):
    """An unparameterised call must keep failing closed.

    `routers/chat.py` and every display tool call this with no scope argument,
    so a changed default is a silent security regression, not a feature.
    """
    import inspect

    default = inspect.signature(bedrock._hydrate_item).parameters["visible"].default
    assert default is is_customer_visible
