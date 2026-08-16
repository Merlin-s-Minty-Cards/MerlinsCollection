"""Sort keys for the admin Shows table — RFC 0013 T4b.

Mirrors ``test_inventory_sort.py``'s structure via the shared
``table_sort.build_sort_registry`` factory: missing-last in both directions,
an unknown field parses to ``None`` (the router 422s on that), and totality
is structural against ``Show.model_fields`` rather than a promise.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.business import Show
from merlins_collection.services.shows_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_shows,
)


def show(**overrides) -> Show:
    defaults: dict = {
        "name": "Portland Card Show",
        "date": date(2026, 8, 1),
    }
    defaults.update(overrides)
    return Show(**defaults)


def ids(shows: list[Show]) -> list[str]:
    return [s.show_id for s in shows]


class TestBasicSort:
    def test_sorts_by_date_ascending(self):
        early = show(show_id="early", date=date(2026, 1, 1))
        late = show(show_id="late", date=date(2026, 12, 1))
        result = sort_shows([late, early], "date_asc")
        assert ids(result) == ["early", "late"]

    def test_sorts_by_date_descending(self):
        early = show(show_id="early", date=date(2026, 1, 1))
        late = show(show_id="late", date=date(2026, 12, 1))
        result = sort_shows([early, late], "date_desc")
        assert ids(result) == ["late", "early"]

    def test_sorts_by_name(self):
        b = show(show_id="b", name="Beaverton Show")
        a = show(show_id="a", name="Albany Show")
        result = sort_shows([b, a], "name_asc")
        assert ids(result) == ["a", "b"]

    def test_no_sort_leaves_order_untouched(self):
        a, b = show(show_id="a"), show(show_id="b")
        assert sort_shows([a, b], None) == [a, b]


class TestMissingSortsLast:
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_venue_is_last_both_directions(self, direction):
        present = show(show_id="present", venue="Lloyd Center")
        blank = show(show_id="blank", venue=None)
        result = sort_shows([blank, present], f"venue_{direction}")
        assert ids(result)[-1] == "blank"

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_sales_goal_is_last_both_directions(self, direction):
        present = show(show_id="present", sales_goal=Decimal("500"))
        blank = show(show_id="blank", sales_goal=None)
        result = sort_shows([blank, present], f"sales_goal_{direction}")
        assert ids(result)[-1] == "blank"


class TestArchivedSort:
    def test_active_before_archived_ascending(self):
        active = show(show_id="active", archived=False)
        archived = show(show_id="archived", archived=True)
        result = sort_shows([archived, active], "archived_asc")
        assert ids(result) == ["active", "archived"]


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("not_a_field_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("date_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("date") is None

    def test_unknown_sort_leaves_items_untouched(self):
        a, b = show(show_id="a"), show(show_id="b")
        assert sort_shows([a, b], "bogus_asc") == [a, b]

    def test_resolve_sort_field_of_unknown_field_is_none(self):
        assert resolve_sort_field("location") is None


class TestRegistryIsTotal:
    """Coverage is structural, not a promise. A new model field fails this test."""

    #: Fields with deliberately no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        # Server-minted id, not a column the Shows page renders.
        "show_id",
        # Free-text notes; not a column on /admin/shows.
        "notes",
        # Internal accounting figures captured at show start; not columns
        # on the Shows list (they surface in Show Analytics instead).
        "cash_at_start",
        "inventory_value_at_start",
    }

    def test_every_model_field_is_sortable_or_explicitly_excluded(self):
        declared = set(Show.model_fields)
        covered = set(SORT_FIELDS) | self.NOT_SORTABLE
        missing = declared - covered
        assert not missing, f"Show fields with no sort and no exclusion: {missing}"
