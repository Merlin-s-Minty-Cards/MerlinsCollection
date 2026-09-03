"""Sort keys for the admin Transactions archive (History) — RFC 0013 T4c.

Mirrors ``test_shows_sort.py``'s structure via the shared
``table_sort.build_sort_registry`` factory: missing-last in both directions,
an unknown field parses to ``None`` (the router 422s on that), and totality
is structural against ``Transaction.model_fields``.

Per RFC 0013 Detailed Design §4, History's frontend keeps `TransactionGroups`
grouping — this registry sorts the flat archive rows the router returns
(``GET /admin/transactions``); the History page's own group-order control is
a separate, lightweight piece built on top, not this module's concern.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import ItemCategory, Transaction, TransactionType
from merlins_collection.services.transactions_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_transactions,
)


def txn(**overrides) -> Transaction:
    defaults: dict = {
        "type": TransactionType.SALE,
        "item_id": "item-1",
        "category": ItemCategory.RAW,
        "date": date(2026, 8, 1),
        "amount": Decimal("10.00"),
        "payment_method": "cash",
    }
    defaults.update(overrides)
    return Transaction(**defaults)


def ids(txns: list[Transaction]) -> list[str]:
    return [t.txn_id for t in txns]


class TestBasicSort:
    def test_sorts_by_amount_ascending(self):
        cheap = txn(txn_id="cheap", amount=Decimal("5"))
        rich = txn(txn_id="rich", amount=Decimal("500"))
        result = sort_transactions([rich, cheap], "amount_asc")
        assert ids(result) == ["cheap", "rich"]

    def test_sorts_by_amount_descending(self):
        cheap = txn(txn_id="cheap", amount=Decimal("5"))
        rich = txn(txn_id="rich", amount=Decimal("500"))
        result = sort_transactions([cheap, rich], "amount_desc")
        assert ids(result) == ["rich", "cheap"]

    def test_sorts_by_date(self):
        early = txn(txn_id="early", date=date(2026, 1, 1))
        late = txn(txn_id="late", date=date(2026, 12, 1))
        result = sort_transactions([late, early], "date_asc")
        assert ids(result) == ["early", "late"]

    def test_sorts_by_type(self):
        sale = txn(txn_id="sale", type=TransactionType.SALE)
        purchase = txn(txn_id="purchase", type=TransactionType.PURCHASE)
        result = sort_transactions([sale, purchase], "type_asc")
        assert ids(result) == ["purchase", "sale"]

    def test_sorts_by_payment_method(self):
        venmo = txn(txn_id="venmo", payment_method="venmo")
        cash = txn(txn_id="cash", payment_method="cash")
        result = sort_transactions([venmo, cash], "payment_method_asc")
        assert ids(result) == ["cash", "venmo"]

    def test_no_sort_leaves_order_untouched(self):
        a, b = txn(txn_id="a"), txn(txn_id="b")
        assert sort_transactions([a, b], None) == [a, b]


class TestMissingSortsLast:
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_show_id_is_last_both_directions(self, direction):
        present = txn(txn_id="present", show_id="show-1")
        blank = txn(txn_id="blank", show_id=None)
        result = sort_transactions([blank, present], f"show_id_{direction}")
        assert ids(result)[-1] == "blank"

    def test_fee_zero_is_a_real_value_not_treated_as_missing(self):
        # `fee` defaults to Decimal("0"), never None. A `_money`-style
        # extractor that used falsiness instead of an explicit `is None`
        # check would wrongly bucket a $0 fee as "missing" and sort it last.
        zero = txn(txn_id="zero", fee=Decimal("0"))
        present = txn(txn_id="present", fee=Decimal("5"))
        result = sort_transactions([present, zero], "fee_asc")
        assert ids(result) == ["zero", "present"]


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("not_a_field_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("date_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("date") is None

    def test_unknown_sort_leaves_items_untouched(self):
        a, b = txn(txn_id="a"), txn(txn_id="b")
        assert sort_transactions([a, b], "bogus_asc") == [a, b]

    def test_resolve_sort_field_of_internal_id_is_none(self):
        assert resolve_sort_field("voided_by") is None


class TestRegistryIsTotal:
    """Coverage is structural, not a promise. A new model field fails this test."""

    #: Fields with deliberately no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        # Server-minted id; not a column the History archive renders as such
        # (the row IS its own identity, not something ordered by id).
        "txn_id",
        # Session/lineage ids — internal grouping keys, not archive columns.
        "trade_id",
        "batch_id",
        # Consignor payout is a derived money detail shown inline on a row,
        # not a column header in the archive.
        "consignor_payout",
        # Free text.
        "notes",
        # Void metadata: the archive renders a voided row struck through
        # with its reason inline, not as a sortable column — see CLAUDE.md's
        # "THE LEDGER HAS A CORRECTION PATH" section.
        "voided_at",
        "voided_by",
        "void_reason",
        # Edit metadata (RFC 0024 T3): the same shape as the void fields
        # above — rendered inline (an "edited …" note, `edit_history`
        # entries) on the leg/detail popup, not as an archive column to sort
        # a whole table by.
        "edited_at",
        "edited_by",
        "edit_history",
    }

    def test_every_model_field_is_sortable_or_explicitly_excluded(self):
        declared = set(Transaction.model_fields)
        covered = set(SORT_FIELDS) | self.NOT_SORTABLE
        missing = declared - covered
        assert not missing, f"Transaction fields with no sort and no exclusion: {missing}"
