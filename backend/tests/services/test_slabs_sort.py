"""Sort keys for the admin Slabs list — RFC 0013 T4 (last of six registries).

Mirrors ``test_locations_sort.py``'s structure via the shared
``table_sort.build_sort_registry`` factory: missing-last in both directions,
an unknown field parses to ``None`` (the router 422s on that), and totality
is structural against the row shape ``GET /admin/slabs`` actually returns.

**Rows are plain ``dict``s, not a Pydantic model** — same shape issue as
Locations. ``GET /admin/slabs`` (``routers/admin/slabs.py::_slab_row``)
returns a dict with ``grade`` and ``cost_basis`` STRINGIFIED (``str(Decimal)``),
not numbers, so their extractors must parse the string back to a number
before comparing — comparing the strings lexicographically would put
``"9"`` after ``"10"``.

**Scope correction against the RFC's illustrative table:** RFC 0013 says
``buy_price``; the actual dict key is ``cost_basis``. RFC 0013 also lists
``priced`` as a field, but it is not a dict key at all — it is DERIVED
exactly the way the existing ``priced`` query param filters
(``routers/admin/slabs.py`` line ~159): ``r["market_value"] is not None``.
"""

from __future__ import annotations

from merlins_collection.services.slabs_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_slabs,
)


def row(
    item_id="itm-1",
    card_id=None,
    cert_number=None,
    company=None,
    grade=None,
    grade_label=None,
    cost_basis=None,
    status=None,
    location=None,
    language=None,
    name=None,
    market_value=None,
    value_as_of=None,
    price_source=None,
    value_confidence=None,
    price_source_id=None,
    price_pinned=False,
) -> dict:
    """Mirrors ``routers/admin/slabs.py::_slab_row``'s exact key set — this
    is what makes ``TestRegistryIsTotal`` below a real totality check
    against the response shape, not a tautology against ``SORT_FIELDS``."""
    return {
        "item_id": item_id,
        "card_id": card_id,
        "name": name,
        "cert_number": cert_number,
        "company": company,
        "grade": grade,
        "grade_label": grade_label,
        "cost_basis": cost_basis,
        "status": status,
        "location": location,
        "language": language,
        "market_value": market_value,
        "value_as_of": value_as_of,
        "price_source": price_source,
        "value_confidence": value_confidence,
        "price_source_id": price_source_id,
        "price_pinned": price_pinned,
    }


class TestBasicSort:
    def test_sorts_by_cert_number_ascending(self):
        result = sort_slabs(
            [row(item_id="a", cert_number="222"), row(item_id="b", cert_number="111")],
            "cert_number_asc",
        )
        assert [r["item_id"] for r in result] == ["b", "a"]

    def test_sorts_by_company_descending(self):
        result = sort_slabs(
            [row(item_id="a", company="CGC"), row(item_id="b", company="PSA")],
            "company_desc",
        )
        assert [r["item_id"] for r in result] == ["b", "a"]

    def test_sorts_by_status_and_location_and_name(self):
        for field in ("status", "location", "name"):
            result = sort_slabs(
                [row(item_id="a", **{field: "zzz"}), row(item_id="b", **{field: "aaa"})],
                f"{field}_asc",
            )
            assert [r["item_id"] for r in result] == ["b", "a"], field

    def test_no_sort_leaves_order_untouched(self):
        rows = [row(item_id="b"), row(item_id="a")]
        assert sort_slabs(rows, None) == rows


class TestGradeSortsNumerically:
    """Grade is a STRING in the dict (``str(Decimal)``). Sorted as text,
    ``"9"`` lands after ``"10"``, which is exactly wrong — a PSA 10 is
    higher than a PSA 9."""

    def test_grade_ten_sorts_above_grade_nine(self):
        result = sort_slabs(
            [row(item_id="nine", grade="9"), row(item_id="ten", grade="10")],
            "grade_desc",
        )
        assert [r["item_id"] for r in result] == ["ten", "nine"]

    def test_half_grade_sorts_between_whole_grades(self):
        result = sort_slabs(
            [
                row(item_id="ten", grade="10"),
                row(item_id="nine", grade="9"),
                row(item_id="nine_five", grade="9.5"),
            ],
            "grade_asc",
        )
        assert [r["item_id"] for r in result] == ["nine", "nine_five", "ten"]


class TestCostBasisSortsNumerically:
    """Same stringified-Decimal trap as grade — ``"9"`` vs ``"100"``."""

    def test_cost_basis_sorts_as_a_number_not_text(self):
        result = sort_slabs(
            [row(item_id="big", cost_basis="100"), row(item_id="small", cost_basis="9")],
            "cost_basis_asc",
        )
        assert [r["item_id"] for r in result] == ["small", "big"]


class TestPricedIsADerivedFlag:
    """``priced`` is not a dict key — it is ``market_value is not None``,
    the same rule the router's ``?priced=`` filter already applies."""

    def test_priced_slabs_sort_ahead_of_unpriced_on_desc(self):
        result = sort_slabs(
            [
                row(item_id="unpriced", market_value=None),
                row(item_id="priced", market_value="2479.50"),
            ],
            "priced_desc",
        )
        assert result[0]["item_id"] == "priced"

    def test_resolve_sort_field_of_priced_is_known(self):
        assert resolve_sort_field("priced") == "priced"


class TestMissingValuesSortLast:
    def test_missing_cert_number_sorts_last_ascending(self):
        result = sort_slabs(
            [row(item_id="none", cert_number=None), row(item_id="has", cert_number="1")],
            "cert_number_asc",
        )
        assert [r["item_id"] for r in result] == ["has", "none"]

    def test_missing_cert_number_sorts_last_descending_too(self):
        result = sort_slabs(
            [row(item_id="none", cert_number=None), row(item_id="has", cert_number="1")],
            "cert_number_desc",
        )
        assert [r["item_id"] for r in result] == ["has", "none"]

    def test_missing_grade_sorts_last(self):
        result = sort_slabs(
            [row(item_id="none", grade=None), row(item_id="has", grade="10")],
            "grade_asc",
        )
        assert [r["item_id"] for r in result] == ["has", "none"]

    def test_missing_cost_basis_sorts_last(self):
        result = sort_slabs(
            [row(item_id="none", cost_basis=None), row(item_id="has", cost_basis="9")],
            "cost_basis_desc",
        )
        assert [r["item_id"] for r in result] == ["has", "none"]


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("buy_price_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("cert_number_sideways") is None

    def test_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("cert_number") is None

    def test_unknown_sort_leaves_items_untouched(self):
        rows = [row(item_id="b"), row(item_id="a")]
        assert sort_slabs(rows, "bogus_asc") == rows

    def test_resolve_sort_field_of_buy_price_is_none(self):
        """The RFC's illustrative name — the real dict key is `cost_basis`."""
        assert resolve_sort_field("buy_price") is None


class TestRegistryIsTotal:
    """Coverage is structural against the REAL response shape — the ``row()``
    helper above mirrors ``routers/admin/slabs.py::_slab_row``'s exact key
    set, so this fails the moment that dict grows a key with no sort and no
    documented exclusion. (A test that instead compared ``SORT_FIELDS``
    against a hand-picked set repeating the same names would be circular —
    it could never catch a new or renamed dict key.)
    """

    #: Fields with deliberately no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        # Server-minted ULID, not a column the Slabs list renders as text.
        "item_id",
        # Identity join key, not a rendered column — `name` is what the list
        # shows for identity.
        "card_id",
        # Display-only refinement of `grade` (e.g. "Mint"); `grade` itself
        # already carries the sortable ordinal.
        "grade_label",
        # Not a column on the Slabs list.
        "language",
        # Superseded by the derived `priced` flag (RFC 0013): the raw figure
        # is a money value but "has a value at all" is the more useful sort,
        # and the RFC's own field list asked for `priced`, not the number.
        "market_value",
        # Timestamp of the price, not of the slab; not a Slabs list column.
        "value_as_of",
        # Provenance of the price (`manual`/`hand_set`/provider name), not a
        # ranked or alphabetized column.
        "price_source",
        "value_confidence",
        "price_source_id",
        # Boolean control state, not a data column to sort by.
        "price_pinned",
    }

    def test_every_response_key_is_sortable_or_explicitly_excluded(self):
        declared = set(row())
        covered = set(SORT_FIELDS) | self.NOT_SORTABLE
        # `priced` is derived (not a dict key), so it is covered but not
        # part of `declared` — that is fine, it does not need an exclusion.
        missing = declared - covered
        assert not missing, f"Slab row keys with no sort and no exclusion: {missing}"
