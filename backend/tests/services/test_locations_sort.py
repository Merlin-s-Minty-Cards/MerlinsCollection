"""Sort keys for the admin Locations table — RFC 0013 T4e.

Mirrors ``test_shows_sort.py``'s structure via the shared
``table_sort.build_sort_registry`` factory: missing-last in both directions,
an unknown field parses to ``None`` (the router 422s on that), and totality
is structural against the row shape ``GET /admin/locations`` actually
returns.

**Scope correction against the RFC's illustrative table:** RFC 0013 names
``item_count`` as a Locations sort field. ``GET /admin/locations``
(``services.locations.get_locations``) returns plain
``{"value": str, "label": str}`` dicts — there is no ``item_count`` on this
response and building one would mean a new aggregate query, which is out of
scope here. This registry sorts what the endpoint actually returns:
``label`` and ``value``. Unlike every other registry in this RFC, the rows
are plain ``dict``s, not a Pydantic model — this is what makes
``table_sort.SortRegistry`` needing to be ``Generic[T]`` (rather than typed
to a model) load-bearing rather than decorative.
"""

from __future__ import annotations

import pytest

from merlins_collection.services.locations_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_locations,
)


def loc(value: str, label: str | None = None) -> dict:
    return {"value": value, "label": label if label is not None else value.title()}


class TestBasicSort:
    def test_sorts_by_label_ascending(self):
        result = sort_locations(
            [loc("box-b", "Box B"), loc("box-a", "Box A")], "label_asc"
        )
        assert [r["value"] for r in result] == ["box-a", "box-b"]

    def test_sorts_by_value_descending(self):
        result = sort_locations([loc("a"), loc("b")], "value_desc")
        assert [r["value"] for r in result] == ["b", "a"]

    def test_no_sort_leaves_order_untouched(self):
        rows = [loc("b"), loc("a")]
        assert sort_locations(rows, None) == rows


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("item_count_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("label_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("label") is None

    def test_unknown_sort_leaves_items_untouched(self):
        rows = [loc("b"), loc("a")]
        assert sort_locations(rows, "bogus_asc") == rows

    def test_resolve_sort_field_of_item_count_is_none(self):
        assert resolve_sort_field("item_count") is None


class TestRegistryIsTotal:
    """Coverage is structural against the actual response shape — a dict with
    exactly two keys, ``value`` and ``label``."""

    def test_every_response_key_is_sortable(self):
        declared = set(loc("x"))
        assert declared == set(SORT_FIELDS)
