"""Sort keys for the admin Consignors table — RFC 0013 T4d.

Mirrors ``test_shows_sort.py``'s structure via the shared
``table_sort.build_sort_registry`` factory: missing-last in both directions,
an unknown field parses to ``None`` (the router 422s on that), and totality
is structural against ``Consignor.model_fields``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from merlins_collection.models.business import Consignor
from merlins_collection.services.consignors_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_consignors,
)


def consignor(**overrides) -> Consignor:
    defaults: dict = {"name": "Jane Dealer"}
    defaults.update(overrides)
    return Consignor(**defaults)


def ids(consignors: list[Consignor]) -> list[str]:
    return [c.consignor_id for c in consignors]


class TestBasicSort:
    def test_sorts_by_name_ascending(self):
        b = consignor(consignor_id="b", name="Beaverton Cards")
        a = consignor(consignor_id="a", name="Albany Cards")
        result = sort_consignors([b, a], "name_asc")
        assert ids(result) == ["a", "b"]

    def test_sorts_by_payout_percent_descending(self):
        low = consignor(consignor_id="low", payout_percent=Decimal("30"))
        high = consignor(consignor_id="high", payout_percent=Decimal("70"))
        result = sort_consignors([low, high], "payout_percent_desc")
        assert ids(result) == ["high", "low"]

    def test_no_sort_leaves_order_untouched(self):
        a, b = consignor(consignor_id="a"), consignor(consignor_id="b")
        assert sort_consignors([a, b], None) == [a, b]


class TestMissingSortsLast:
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_email_is_last_both_directions(self, direction):
        present = consignor(consignor_id="present", email="jane@example.com")
        blank = consignor(consignor_id="blank", email=None)
        result = sort_consignors([blank, present], f"email_{direction}")
        assert ids(result)[-1] == "blank"

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_phone_is_last_both_directions(self, direction):
        present = consignor(consignor_id="present", phone="555-1234")
        blank = consignor(consignor_id="blank", phone=None)
        result = sort_consignors([blank, present], f"phone_{direction}")
        assert ids(result)[-1] == "blank"


class TestArchivedSort:
    def test_active_before_archived_ascending(self):
        active = consignor(consignor_id="active", archived=False)
        archived = consignor(consignor_id="archived", archived=True)
        result = sort_consignors([archived, active], "archived_asc")
        assert ids(result) == ["active", "archived"]


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("created_at_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("name_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("name") is None

    def test_unknown_sort_leaves_items_untouched(self):
        a, b = consignor(consignor_id="a"), consignor(consignor_id="b")
        assert sort_consignors([a, b], "bogus_asc") == [a, b]

    def test_resolve_sort_field_of_unknown_field_is_none(self):
        assert resolve_sort_field("created_at") is None


class TestRegistryIsTotal:
    """Coverage is structural, not a promise. A new model field fails this test."""

    #: Fields with deliberately no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        # Server-minted id, not a column on /admin/cosigners.
        "consignor_id",
        # Legacy pre-RFC-0010 field, kept for backward compat only; the page
        # never renders it as a column.
        "contact",
        # Free text; not a column.
        "notes",
    }

    def test_every_model_field_is_sortable_or_explicitly_excluded(self):
        declared = set(Consignor.model_fields)
        covered = set(SORT_FIELDS) | self.NOT_SORTABLE
        missing = declared - covered
        assert not missing, f"Consignor fields with no sort and no exclusion: {missing}"
