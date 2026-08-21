"""``table_sort.py`` — the generic factory behind every admin sort registry.

RFC 0013 T4a. ``inventory_sort.py`` proved the pattern (missing-last,
unknown-field-is-None, ``rsplit`` on the last underscore) for one table; this
factory carries those three invariants into a ``SortRegistry`` instance so the
five new tables (Shows, Transactions, Consignors, Locations, Slabs) don't each
re-derive them. Pure functions/dataclasses: nothing here touches DynamoDB.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from merlins_collection.services.table_sort import build_sort_registry


@dataclass
class Row:
    row_id: str
    name: str | None = None
    amount: float | None = None


def ids(rows):
    return [r.row_id for r in rows]


FIELDS = {
    "name": lambda r: r.name.lower() if r.name else None,
    "amount": lambda r: r.amount,
}


class TestBasicSort:
    def test_sorts_ascending(self):
        registry = build_sort_registry(FIELDS)
        a = Row("a", amount=5)
        b = Row("b", amount=1)
        assert ids(registry.sort_items([a, b], "amount_asc")) == ["b", "a"]

    def test_sorts_descending(self):
        registry = build_sort_registry(FIELDS)
        a = Row("a", amount=5)
        b = Row("b", amount=1)
        assert ids(registry.sort_items([a, b], "amount_desc")) == ["a", "b"]

    def test_no_sort_returns_untouched(self):
        registry = build_sort_registry(FIELDS)
        a, b = Row("a"), Row("b")
        assert registry.sort_items([a, b], None) == [a, b]


class TestMissingSortsLast:
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_value_is_last_both_directions(self, direction):
        registry = build_sort_registry(FIELDS)
        present = Row("present", amount=5)
        blank = Row("blank", amount=None)
        result = registry.sort_items([blank, present], f"amount_{direction}")
        assert ids(result)[-1] == "blank"


class TestUnknownField:
    def test_unknown_field_does_not_parse(self):
        registry = build_sort_registry(FIELDS)
        assert registry.parse_sort("not_a_field_asc") is None

    def test_unknown_direction_does_not_parse(self):
        registry = build_sort_registry(FIELDS)
        assert registry.parse_sort("amount_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        registry = build_sort_registry(FIELDS)
        assert registry.parse_sort("amount") is None

    def test_unknown_sort_leaves_items_untouched(self):
        registry = build_sort_registry(FIELDS)
        a, b = Row("a"), Row("b")
        assert registry.sort_items([a, b], "bogus_asc") == [a, b]


class TestAliases:
    def test_alias_resolves_to_the_real_field(self):
        registry = build_sort_registry(FIELDS, aliases={"value": "amount"})
        assert registry.resolve_sort_field("value") == "amount"
        assert registry.parse_sort("value_desc") == ("amount", True)

    def test_unrecognized_field_resolves_to_none(self):
        registry = build_sort_registry(FIELDS)
        assert registry.resolve_sort_field("nope") is None


class TestStability:
    def test_equal_values_keep_original_order(self):
        registry = build_sort_registry(FIELDS)
        a, b, c = Row("a", amount=5), Row("b", amount=5), Row("c", amount=5)
        assert ids(registry.sort_items([a, b, c], "amount_asc")) == ["a", "b", "c"]


class TestIndependentRegistries:
    def test_two_registries_do_not_share_fields(self):
        """Each ``build_sort_registry`` call is its own instance — a table
        must not accidentally sort by another table's field."""
        registry_a = build_sort_registry({"amount": lambda r: r.amount})
        registry_b = build_sort_registry({"name": lambda r: r.name})
        assert registry_a.parse_sort("name_asc") is None
        assert registry_b.parse_sort("amount_asc") is None
