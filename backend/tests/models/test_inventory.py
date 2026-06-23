from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    InventoryItemAdapter,
    RawInventoryItem,
)


def test_raw_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "raw",
            "card_id": "swsh1-1",
            "quantity": 3,
            "listed_price": Decimal("10"),
            "cost_basis": Decimal("4"),
            "acquired_at": date(2026, 1, 1),
            "finish": "holofoil",
            "condition": "NM",
        }
    )
    assert isinstance(item, RawInventoryItem)
    assert item.condition is Condition.NM
    assert item.current_market_value is None


def test_graded_item_parses_via_adapter():
    item = InventoryItemAdapter.validate_python(
        {
            "kind": "graded",
            "card_id": "swsh1-1",
            "quantity": 1,
            "listed_price": Decimal("600"),
            "cost_basis": Decimal("300"),
            "acquired_at": date(2026, 1, 1),
            "company": "PSA",
            "grade": Decimal("10"),
            "cert_number": "12345678",
        }
    )
    assert isinstance(item, GradedInventoryItem)
    assert item.grade == Decimal("10")
    assert item.company is GradingCompany.PSA


def test_adapter_rejects_raw_missing_fields():
    with pytest.raises(ValidationError):
        InventoryItemAdapter.validate_python(
            {"kind": "raw", "card_id": "x", "quantity": 1,
             "listed_price": Decimal("1"), "cost_basis": Decimal("1"),
             "acquired_at": "2026-01-01"}
        )


def test_raw_item_rejects_graded_fields_missing():
    with pytest.raises(ValidationError):
        RawInventoryItem(
            kind="raw", card_id="x", quantity=1,
            listed_price=Decimal("1"), cost_basis=Decimal("1"),
            acquired_at=date(2026, 1, 1),
            # missing finish + condition
        )
