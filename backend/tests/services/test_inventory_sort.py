"""Sort registry — RFC 0011 T1.

Pure model/function tests: nothing here touches DynamoDB, so no `_clean_aws`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConditionModifier,
    GradedInventoryItem,
    GradingCompany,
    Language,
    RawInventoryItem,
    SealedInventoryItem,
)
from merlins_collection.services.inventory_sort import (
    SORT_FIELDS,
    parse_sort,
    resolve_sort_field,
    sort_items,
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
    return [i.item_id for i in items]


class TestMissingSortsLast:
    """The rule that generalizes the old money-only `±inf` sentinel to every type."""

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_money_is_last_in_both_directions(self, direction):
        cheap = raw(item_id="cheap", current_market_value=Decimal("5"))
        rich = raw(item_id="rich", current_market_value=Decimal("500"))
        blank = raw(item_id="blank", current_market_value=None)

        result = sort_items([blank, rich, cheap], f"current_market_value_{direction}")

        assert ids(result)[-1] == "blank"

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_text_is_last_in_both_directions(self, direction):
        """The half that was broken: a blank used to sort to the TOP ascending."""
        named = raw(item_id="named", notes="alpha")
        other = raw(item_id="other", notes="zulu")
        blank = raw(item_id="blank", notes=None)
        empty = raw(item_id="empty", notes="")

        result = sort_items([blank, other, empty, named], f"notes_{direction}")

        assert set(ids(result)[-2:]) == {"blank", "empty"}

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_missing_date_is_last_in_both_directions(self, direction):
        early = raw(item_id="early", reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        late = raw(item_id="late", reviewed_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        never = raw(item_id="never", reviewed_at=None)

        result = sort_items([never, late, early], f"reviewed_at_{direction}")

        assert ids(result)[-1] == "never"


class TestConditionRank:
    def test_modifiers_order_within_a_tier(self):
        """LP+ beats LP beats LP-. Alphabetical sorting could not express this."""
        plus = raw(item_id="plus", condition=Condition.LP,
                   condition_modifier=ConditionModifier.PLUS)
        flat = raw(item_id="flat", condition=Condition.LP)
        minus = raw(item_id="minus", condition=Condition.LP,
                    condition_modifier=ConditionModifier.MINUS)

        result = sort_items([flat, minus, plus], "condition_desc")

        assert ids(result) == ["plus", "flat", "minus"]

    def test_best_condition_first_when_descending(self):
        nm = raw(item_id="nm", condition=Condition.NM)
        dmg = raw(item_id="dmg", condition=Condition.DMG)
        mp = raw(item_id="mp", condition=Condition.MP)

        assert ids(sort_items([mp, dmg, nm], "condition_desc")) == ["nm", "mp", "dmg"]

    def test_ascending_is_worst_first(self):
        """Same direction money sorts in: asc means the low end of the scale."""
        nm = raw(item_id="nm", condition=Condition.NM)
        dmg = raw(item_id="dmg", condition=Condition.DMG)

        assert ids(sort_items([nm, dmg], "condition_asc")) == ["dmg", "nm"]

    def test_an_item_with_no_condition_sorts_last(self):
        """A sealed box has no `condition` attribute at all — it must not crash."""
        box = sealed(item_id="sealed")
        nm = raw(item_id="nm", condition=Condition.NM)

        assert ids(sort_items([box, nm], "condition_asc"))[-1] == "sealed"


class TestEffectiveName:
    def test_display_name_override_wins(self):
        """One rule everywhere: the override outranks the stored name."""
        overridden = raw(item_id="a", display_name="Zzz", display_name_override="Aaa")
        plain = raw(item_id="b", display_name="Bbb")

        assert ids(sort_items([plain, overridden], "display_name_asc")) == ["a", "b"]

    def test_a_nameless_item_sorts_last(self):
        nameless = raw(item_id="nameless")
        named = raw(item_id="named", display_name="Charizard")

        assert ids(sort_items([nameless, named], "display_name_asc"))[-1] == "nameless"


class TestPresenceAndFlags:
    def test_consignment_sorts_by_presence(self):
        """ConsignmentTerms is not comparable; "consigned or owned" is the question."""
        owned = raw(item_id="owned", consignment=None)
        consigned = raw(item_id="consigned", consignment={
            "consignor_id": "c1", "split_percent": Decimal("80"),
        })

        assert ids(sort_items([owned, consigned], "consignment_desc")) == [
            "consigned", "owned",
        ]

    def test_booleans_sort(self):
        flagged = raw(item_id="flagged", needs_review=True)
        clear = raw(item_id="clear", needs_review=False)

        assert ids(sort_items([clear, flagged], "needs_review_desc")) == [
            "flagged", "clear",
        ]


class TestGradedFields:
    def test_grade_sorts_numerically(self):
        def graded(item_id, grade):
            return GradedInventoryItem(
                item_id=item_id, cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
                company=GradingCompany.PSA, grade=Decimal(grade), cert_number=item_id,
            )

        # As strings "10" sorts before "9". As numbers it does not.
        assert ids(sort_items([graded("nine", "9"), graded("ten", "10")],
                              "grade_desc")) == ["ten", "nine"]

    def test_a_raw_item_has_no_grade_and_sorts_last(self):
        graded = GradedInventoryItem(
            item_id="graded", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
            company=GradingCompany.PSA, grade=Decimal("10"), cert_number="x",
        )
        assert ids(sort_items([raw(item_id="raw"), graded], "grade_asc"))[-1] == "raw"


class TestStability:
    def test_equal_values_keep_their_original_order(self):
        a = raw(item_id="a", cost_basis=Decimal("5"))
        b = raw(item_id="b", cost_basis=Decimal("5"))
        c = raw(item_id="c", cost_basis=Decimal("5"))

        assert ids(sort_items([a, b, c], "cost_basis_asc")) == ["a", "b", "c"]

    def test_no_sort_returns_the_list_untouched(self):
        a, b = raw(item_id="a"), raw(item_id="b")
        assert sort_items([a, b], None) == [a, b]


class TestConsignorNameSort:
    """`consignor_name` sorts by the RESOLVED name, not the opaque `consignor_id`
    the item actually stores — there is no join in DynamoDB, so the caller
    (the router) must supply an id->name map built from `repo.list_consignors()`.

    Deliberately NOT a `SORT_FIELDS` entry: every other extractor there is a
    pure `Callable[[InventoryItem], Any]`, and this field needs data no single
    item carries. It is handled as a special case in `sort_items`/`parse_sort`/
    `resolve_sort_field` instead — see the module docstring additions.
    """

    def test_parses_like_any_other_field(self):
        assert parse_sort("consignor_name_asc") == ("consignor_name", False)
        assert parse_sort("consignor_name_desc") == ("consignor_name", True)

    def test_resolves_as_a_known_field(self):
        assert resolve_sort_field("consignor_name") == "consignor_name"

    def test_sorts_by_the_resolved_name_not_the_id(self):
        # Deliberately named so alphabetical-by-id would give the WRONG answer:
        # "z-consignor" sorts before "a-consignor" by id, but "Alex" is before
        # "Zoe" by name.
        zoe_item = raw(item_id="zoe-item", consignment={
            "consignor_id": "z-consignor", "split_percent": Decimal("0.5"),
        })
        alex_item = raw(item_id="alex-item", consignment={
            "consignor_id": "a-consignor", "split_percent": Decimal("0.5"),
        })
        names = {"z-consignor": "Zoe", "a-consignor": "Alex"}

        result = sort_items(
            [zoe_item, alex_item], "consignor_name_asc", consignor_names=names,
        )

        assert ids(result) == ["alex-item", "zoe-item"]

    def test_reverses_for_desc(self):
        zoe_item = raw(item_id="zoe-item", consignment={
            "consignor_id": "z-consignor", "split_percent": Decimal("0.5"),
        })
        alex_item = raw(item_id="alex-item", consignment={
            "consignor_id": "a-consignor", "split_percent": Decimal("0.5"),
        })
        names = {"z-consignor": "Zoe", "a-consignor": "Alex"}

        result = sort_items(
            [zoe_item, alex_item], "consignor_name_desc", consignor_names=names,
        )

        assert ids(result) == ["zoe-item", "alex-item"]

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_an_owned_unconsigned_item_sorts_last(self, direction):
        """No consignment at all — the ordinary, common case — is missing, not an error."""
        owned = raw(item_id="owned", consignment=None)
        consigned = raw(item_id="consigned", consignment={
            "consignor_id": "c1", "split_percent": Decimal("0.5"),
        })

        result = sort_items(
            [owned, consigned], f"consignor_name_{direction}",
            consignor_names={"c1": "Alex"},
        )

        assert ids(result)[-1] == "owned"

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_a_consignor_id_absent_from_the_map_sorts_last(self, direction):
        """An archived/deleted consignor's id may not resolve. Must not crash,
        and an unresolvable name is exactly as "missing" as no name at all."""
        unresolvable = raw(item_id="unresolvable", consignment={
            "consignor_id": "gone", "split_percent": Decimal("0.5"),
        })
        resolvable = raw(item_id="resolvable", consignment={
            "consignor_id": "c1", "split_percent": Decimal("0.5"),
        })

        result = sort_items(
            [unresolvable, resolvable], f"consignor_name_{direction}",
            consignor_names={"c1": "Alex"},
        )

        assert ids(result)[-1] == "unresolvable"

    def test_missing_consignor_names_kwarg_does_not_crash(self):
        """The router only builds the map when this field is actually requested,
        but a caller that forgets to pass it must degrade, not raise."""
        consigned = raw(item_id="consigned", consignment={
            "consignor_id": "c1", "split_percent": Decimal("0.5"),
        })

        result = sort_items([consigned], "consignor_name_asc")

        assert ids(result) == ["consigned"]

    def test_is_not_a_literal_SORT_FIELDS_key(self):
        """It cannot be a pure `Callable[[InventoryItem], Any]` — sorting it
        needs data no single item carries — so it must not appear in the
        registry dict itself, only in the parse/resolve/sort special-casing."""
        assert "consignor_name" not in SORT_FIELDS


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("not_a_field_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("cost_basis_sideways") is None

    def test_a_bare_field_with_no_direction_does_not_parse(self):
        assert parse_sort("cost_basis") is None

    def test_price_alias_still_resolves(self):
        """The customer-facing sort has always sent `price`. It must keep working."""
        assert resolve_sort_field("price") == "current_market_value"
        assert parse_sort("price_desc") == ("current_market_value", True)

    def test_name_alias_still_resolves(self):
        assert parse_sort("name_asc") == ("display_name", False)


class TestRegistryIsTotal:
    """Coverage is structural, not a promise. A new model field fails this test."""

    #: Fields with deliberately no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        # Provider-supplied URL rendered as an image; not a column and not a
        # question anyone orders a table by.
        "cert_image_url",
        # The pricing vendor's internal product id — an implementation detail.
        "price_source_id",
    }

    def test_every_model_field_is_sortable_or_explicitly_excluded(self):
        members = (RawInventoryItem, GradedInventoryItem,
                   SealedInventoryItem, BulkInventoryItem)
        declared = {name for m in members for name in m.model_fields}
        missing = declared - set(SORT_FIELDS) - self.NOT_SORTABLE
        assert missing == set(), (
            f"model fields with no sort extractor and no documented exclusion: {missing}"
        )

    def test_the_specially_handled_fields_are_present(self):
        for key in ("condition", "consignment", "display_name"):
            assert key in SORT_FIELDS

    def test_no_registry_key_ends_in_a_direction(self):
        """`rsplit('_', 1)` would read the direction off the field name."""
        for key in SORT_FIELDS:
            assert not key.endswith("_asc")
            assert not key.endswith("_desc")


class TestLanguageField:
    def test_language_sorts(self):
        en = raw(item_id="en", language=Language.EN)
        jp = raw(item_id="jp", language=Language.JP)

        assert ids(sort_items([jp, en], "language_asc")) == ["en", "jp"]


class TestFinishAttributesField:
    """RFC 0023 T5 — sorts by COUNT of attributes, not the joined string."""

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_no_attributes_sorts_last_in_both_directions(self, direction):
        none = raw(item_id="none", finish_attributes=[])
        one = raw(item_id="one", finish_attributes=["1st Edition"])
        many = raw(item_id="many", finish_attributes=["1st Edition", "Shadowless", "Signed"])

        result = ids(sort_items([none, many, one], f"finish_attributes_{direction}"))
        assert result[-1] == "none"

    def test_ascending_orders_by_count(self):
        one = raw(item_id="one", finish_attributes=["1st Edition"])
        many = raw(item_id="many", finish_attributes=["1st Edition", "Shadowless"])

        assert ids(sort_items([many, one], "finish_attributes_asc")) == ["one", "many"]
