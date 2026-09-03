"""Generic filter layer — RFC 0011 T3.

Pure function tests: nothing here touches DynamoDB, so no `_clean_aws`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import (
    Condition,
    GradedInventoryItem,
    GradingCompany,
    RawInventoryItem,
    SealedInventoryItem,
)
from merlins_collection.services.inventory_filters import (
    FILTERABLE_FIELDS,
    OPS_BY_KIND,
    FieldFilter,
    FieldKind,
    FilterOp,
    apply_filters,
    parse_filter,
    validate_filters,
)


def raw(**over):
    base = dict(
        cost_basis=Decimal("1"),
        acquired_at=date(2026, 1, 1),
        finish="normal",
        condition=Condition.NM,
    )
    base.update(over)
    return RawInventoryItem(**base)


def sealed(**over):
    base = dict(
        cost_basis=Decimal("1"),
        acquired_at=date(2026, 1, 1),
        product_name="Booster Box",
        product_type="booster_box",
    )
    base.update(over)
    return SealedInventoryItem(**base)


def ids(items):
    return sorted(i.item_id for i in items)


class TestParsing:
    def test_splits_on_the_first_two_colons_only(self):
        """A card_id contains a colon: `en:base1-4`. A naive split loses it."""
        assert parse_filter("card_id:eq:en:base1-4") == FieldFilter(
            field="card_id", op=FilterOp.EQ, value="en:base1-4",
        )

    def test_a_malformed_triple_raises(self):
        with pytest.raises(ValueError):
            parse_filter("notes:contains")

    def test_an_unknown_op_raises(self):
        with pytest.raises(ValueError):
            parse_filter("notes:sortof:foil")

    def test_an_empty_value_is_legal(self):
        """`isnull` and `notnull` carry no value at all."""
        assert parse_filter("card_id:isnull:").value == ""


class TestTextOps:
    def test_contains_is_case_insensitive(self):
        hit = raw(item_id="hit", notes="Signed FOIL promo")
        miss = raw(item_id="miss", notes="ordinary")

        result = apply_filters([hit, miss], [parse_filter("notes:contains:foil")])

        assert ids(result) == ["hit"]

    def test_eq_is_exact(self):
        # `cert_number` lives on the GRADED kind only — a raw single silently drops it,
        # which is exactly the cross-kind trap `getattr` exists to survive.
        def graded(item_id, cert_number):
            return GradedInventoryItem(
                item_id=item_id, cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
                company=GradingCompany.PSA, grade=Decimal("10"),
                cert_number=cert_number,
            )

        exact = graded("exact", "12345678")
        longer = graded("longer", "123456789")

        result = apply_filters(
            [exact, longer], [parse_filter("cert_number:eq:12345678")],
        )

        assert ids(result) == ["exact"]


class TestRangeOps:
    def test_gte_and_lte_bound_a_range(self):
        cheap = raw(item_id="cheap", cost_basis=Decimal("5"))
        mid = raw(item_id="mid", cost_basis=Decimal("50"))
        dear = raw(item_id="dear", cost_basis=Decimal("500"))

        result = apply_filters(
            [cheap, mid, dear],
            [parse_filter("cost_basis:gte:10"), parse_filter("cost_basis:lte:100")],
        )

        assert ids(result) == ["mid"]

    def test_a_boundary_value_is_included(self):
        """Decimal on both sides. Through float, a 100.00 bound can drop a $100 card."""
        exact = raw(item_id="exact", cost_basis=Decimal("100.00"))

        assert ids(apply_filters([exact], [parse_filter("cost_basis:gte:100")])) == [
            "exact",
        ]

    def test_a_money_bound_is_compared_as_decimal_not_float(self):
        """0.1 + 0.2 != 0.3 in binary float. Money bounds must not inherit that."""
        item = raw(item_id="x", cost_basis=Decimal("0.30"))

        assert ids(apply_filters([item], [parse_filter("cost_basis:gte:0.3")])) == ["x"]

    def test_grade_compares_numerically_not_as_a_string(self):
        def graded(item_id, grade):
            return GradedInventoryItem(
                item_id=item_id, cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
                company=GradingCompany.PSA, grade=Decimal(grade), cert_number=item_id,
            )

        # As strings, "10" < "9". As numbers it is not.
        result = apply_filters(
            [graded("nine", "9"), graded("ten", "10")], [parse_filter("grade:gte:10")],
        )

        assert ids(result) == ["ten"]


class TestDateOps:
    def test_a_date_range_bounds_by_calendar_day(self):
        early = raw(item_id="early", acquired_at=date(2026, 1, 1))
        late = raw(item_id="late", acquired_at=date(2026, 6, 1))

        result = apply_filters(
            [early, late], [parse_filter("acquired_at:gte:2026-03-01")],
        )

        assert ids(result) == ["late"]

    def test_a_datetime_field_compares_on_its_date(self):
        reviewed = raw(
            item_id="reviewed",
            reviewed_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        result = apply_filters(
            [reviewed], [parse_filter("reviewed_at:gte:2026-06-01")],
        )

        assert ids(result) == ["reviewed"]

    def test_an_unparseable_bound_raises(self):
        """The router turns this into a 422 rather than silently dropping every row."""
        with pytest.raises(ValueError):
            apply_filters(
                [raw(item_id="x")], [parse_filter("acquired_at:gte:not-a-date")],
            )


class TestPresenceOps:
    def test_isnull_and_notnull_answer_the_linked_question(self):
        linked = raw(item_id="linked", card_id="en:base1-4")
        unlinked = raw(item_id="unlinked", card_id=None)

        assert ids(apply_filters([linked, unlinked],
                                 [parse_filter("card_id:isnull:")])) == ["unlinked"]
        assert ids(apply_filters([linked, unlinked],
                                 [parse_filter("card_id:notnull:")])) == ["linked"]

    def test_consignment_presence_is_the_ownership_question(self):
        owned = raw(item_id="owned", consignment=None)
        consigned = raw(item_id="consigned", consignment={
            "consignor_id": "c1", "split_percent": Decimal("0.8"),
        })

        assert ids(apply_filters([owned, consigned],
                                 [parse_filter("consignment:isnull:")])) == ["owned"]


class TestMissingValues:
    def test_a_missing_value_never_satisfies_a_positive_op(self):
        """A row with no notes must not fall through into a `contains` result."""
        blank = raw(item_id="blank", notes=None)

        assert apply_filters([blank], [parse_filter("notes:contains:anything")]) == []

    def test_a_field_the_kind_does_not_carry_is_simply_excluded(self):
        """A sealed box has no `condition` attribute. getattr, not attribute access."""
        box = sealed(item_id="box")

        assert apply_filters([box], [parse_filter("condition:eq:NM")]) == []

    def test_isnull_matches_a_field_the_kind_does_not_carry(self):
        """A sealed box genuinely has no card_id — "missing" is the honest answer."""
        box = sealed(item_id="box")

        assert ids(apply_filters([box], [parse_filter("card_id:isnull:")])) == ["box"]


class TestCombining:
    def test_filters_and_combine(self):
        both = raw(item_id="both", notes="foil", cost_basis=Decimal("50"))
        one = raw(item_id="one", notes="foil", cost_basis=Decimal("5"))

        result = apply_filters(
            [both, one],
            [parse_filter("notes:contains:foil"), parse_filter("cost_basis:gte:10")],
        )

        assert ids(result) == ["both"]

    def test_no_filters_returns_everything(self):
        items = [raw(item_id="a"), raw(item_id="b")]

        assert apply_filters(items, []) == items


class TestEnumFields:
    def test_status_matches_by_value(self):
        available = raw(item_id="available", status="available")
        sold = raw(item_id="sold", status="sold")

        result = apply_filters([available, sold], [parse_filter("status:eq:sold")])

        assert ids(result) == ["sold"]

    def test_a_boolean_matches_the_browsers_string_form(self):
        """A select sends "true"/"false", not a JSON boolean."""
        flagged = raw(item_id="flagged", needs_review=True)
        clear = raw(item_id="clear", needs_review=False)

        assert ids(apply_filters([flagged, clear],
                                 [parse_filter("needs_review:eq:true")])) == ["flagged"]
        assert ids(apply_filters([flagged, clear],
                                 [parse_filter("needs_review:eq:false")])) == ["clear"]


class TestRegistryShape:
    def test_every_field_kind_declares_its_ops(self):
        for kind in FieldKind:
            assert OPS_BY_KIND[kind], f"{kind} declares no operators"

    def test_every_filterable_field_has_a_known_kind(self):
        for field, kind in FILTERABLE_FIELDS.items():
            assert isinstance(kind, FieldKind), field

    def test_the_presence_fields_are_the_ones_argued_for(self):
        """Card ID is a dropdown, not a text box — nobody types `en:sv3pt5-158`."""
        assert FILTERABLE_FIELDS["card_id"] is FieldKind.PRESENCE
        assert FILTERABLE_FIELDS["consignment"] is FieldKind.PRESENCE


class TestBoundValidationIsEager:
    """A bad bound must be rejected regardless of how many rows exist.

    `apply_filters` is a list comprehension, so on an empty result set it never calls
    `_matches` and a nonsense bound used to sail through as a 200. Validity that
    depends on the data teaches the caller a broken query is fine.
    """

    def test_a_nonsense_date_bound_is_rejected_with_no_items_at_all(self):
        with pytest.raises(ValueError, match="ISO date"):
            validate_filters(["acquired_at:gte:yesterday"])

    def test_a_nonsense_number_bound_is_rejected_with_no_items_at_all(self):
        with pytest.raises(ValueError, match="needs a number"):
            validate_filters(["cost_basis:gte:lots"])

    def test_a_legal_bound_passes(self):
        assert validate_filters(["cost_basis:gte:100", "acquired_at:lte:2026-01-01"])

    def test_an_unknown_field_is_still_rejected(self):
        with pytest.raises(ValueError, match="Unknown filter field"):
            validate_filters(["wibble:eq:x"])

    def test_an_unsupported_op_is_still_rejected(self):
        with pytest.raises(ValueError, match="does not support"):
            validate_filters(["status:contains:avail"])


class TestListContains:
    """RFC 0023 T5 — finish_attributes is a list, so `contains` means "is one
    of the list's entries", not a substring search over the whole list."""

    def test_field_kind_is_registered(self):
        assert FILTERABLE_FIELDS["finish_attributes"] is FieldKind.LIST_CONTAINS

    def test_only_contains_is_supported(self):
        assert OPS_BY_KIND[FieldKind.LIST_CONTAINS] == frozenset({FilterOp.CONTAINS})

    def test_matches_an_item_carrying_the_exact_attribute(self):
        tagged = raw(item_id="tagged", finish_attributes=["1st Edition", "Shadowless"])
        untagged = raw(item_id="plain", finish_attributes=[])

        result = apply_filters(
            [tagged, untagged], [parse_filter("finish_attributes:contains:1st Edition")]
        )
        assert ids(result) == ["tagged"]

    def test_matches_case_insensitively(self):
        tagged = raw(item_id="tagged", finish_attributes=["1st Edition"])

        result = apply_filters(
            [tagged], [parse_filter("finish_attributes:contains:1ST EDITION")]
        )
        assert ids(result) == ["tagged"]

    def test_a_substring_of_one_entry_does_not_match(self):
        """`contains` means list MEMBERSHIP, not a substring inside one entry —
        the opposite of the TEXT kind's `contains`, which the docstring above
        exists to distinguish."""
        tagged = raw(item_id="tagged", finish_attributes=["1st Edition"])

        result = apply_filters([tagged], [parse_filter("finish_attributes:contains:Edition")])
        assert ids(result) == []

    def test_an_unknown_op_on_the_field_is_rejected(self):
        with pytest.raises(ValueError, match="does not support"):
            validate_filters(["finish_attributes:eq:1st Edition"])
