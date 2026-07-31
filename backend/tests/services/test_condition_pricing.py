"""Tests for condition-aware pricing multipliers (Phase 19).

Outside-in TDD: these were written RED first, then the implementation made them
green. Every Condition member must have a defined multiplier; edge cases (NM+,
DMG-) clamp rather than defaulting silently.
"""

from decimal import Decimal

import pytest

from merlins_collection.models.inventory import Condition, ConditionModifier
from merlins_collection.services.condition_pricing import (
    apply_condition_adjustment,
    condition_multiplier,
)


class TestConditionMultiplier:
    """Each tier and modifier resolves to the owner-approved table."""

    def test_nm_base(self):
        assert condition_multiplier(Condition.NM) == Decimal("1.00")

    def test_lp_base(self):
        assert condition_multiplier(Condition.LP) == Decimal("0.82")

    def test_mp_base(self):
        assert condition_multiplier(Condition.MP) == Decimal("0.58")

    def test_hp_base(self):
        assert condition_multiplier(Condition.HP) == Decimal("0.33")

    def test_dmg_base(self):
        assert condition_multiplier(Condition.DMG) == Decimal("0.15")

    def test_lp_plus_is_midpoint_of_lp_and_nm(self):
        # midpoint(0.82, 1.00) = 0.91
        assert condition_multiplier(Condition.LP, ConditionModifier.PLUS) == Decimal("0.91")

    def test_lp_minus_is_midpoint_of_lp_and_mp(self):
        # midpoint(0.82, 0.58) = 0.70
        assert condition_multiplier(Condition.LP, ConditionModifier.MINUS) == Decimal("0.70")

    def test_mp_plus_is_midpoint_of_mp_and_lp(self):
        # midpoint(0.58, 0.82) = 0.70
        assert condition_multiplier(Condition.MP, ConditionModifier.PLUS) == Decimal("0.70")

    def test_mp_minus_is_midpoint_of_mp_and_hp(self):
        # midpoint(0.58, 0.33) = 0.46 (rounded)
        result = condition_multiplier(Condition.MP, ConditionModifier.MINUS)
        assert result == Decimal("0.46") or result == Decimal("0.45")
        # Exact: (0.58 + 0.33) / 2 = 0.455, rounds to 0.46
        assert result == Decimal("0.46")

    def test_hp_plus_is_midpoint_of_hp_and_mp(self):
        # midpoint(0.33, 0.58) = 0.455 -> 0.46
        assert condition_multiplier(Condition.HP, ConditionModifier.PLUS) == Decimal("0.46")

    def test_hp_minus_is_midpoint_of_hp_and_dmg(self):
        # midpoint(0.33, 0.15) = 0.24
        assert condition_multiplier(Condition.HP, ConditionModifier.MINUS) == Decimal("0.24")

    def test_nm_plus_clamps_to_nm(self):
        """NM+ has no tier above — clamps to NM's own multiplier."""
        assert condition_multiplier(Condition.NM, ConditionModifier.PLUS) == Decimal("1.00")

    def test_dmg_minus_clamps_to_dmg(self):
        """DMG- has no tier below — clamps to DMG's own multiplier."""
        assert condition_multiplier(Condition.DMG, ConditionModifier.MINUS) == Decimal("0.15")

    def test_nm_minus_is_midpoint_of_nm_and_lp(self):
        # midpoint(1.00, 0.82) = 0.91
        assert condition_multiplier(Condition.NM, ConditionModifier.MINUS) == Decimal("0.91")

    def test_dmg_plus_is_midpoint_of_dmg_and_hp(self):
        # midpoint(0.15, 0.33) = 0.24
        assert condition_multiplier(Condition.DMG, ConditionModifier.PLUS) == Decimal("0.24")


class TestApplyConditionAdjustment:
    """The adjustment function returns (adjusted_price, value_note)."""

    def test_nm_no_adjustment(self):
        """NM cards get no adjustment and no note."""
        price, note = apply_condition_adjustment(Decimal("10.00"), Condition.NM)
        assert price == Decimal("10.00")
        assert note is None

    def test_nm_plus_no_adjustment(self):
        """NM+ also gets no adjustment (clamps to 1.00)."""
        price, note = apply_condition_adjustment(
            Decimal("10.00"), Condition.NM, ConditionModifier.PLUS
        )
        assert price == Decimal("10.00")
        assert note is None

    def test_lp_adjustment(self):
        """LP applies 0.82x multiplier."""
        price, note = apply_condition_adjustment(Decimal("100.00"), Condition.LP)
        assert price == Decimal("82.00")
        assert note is not None
        assert "LP" in note
        assert "0.82" in note

    def test_lp_plus_adjustment(self):
        """LP+ applies 0.91x multiplier."""
        price, note = apply_condition_adjustment(
            Decimal("100.00"), Condition.LP, ConditionModifier.PLUS
        )
        assert price == Decimal("91.00")
        assert note is not None
        assert "LP+" in note
        assert "0.91" in note

    def test_mp_adjustment(self):
        """MP applies 0.58x multiplier."""
        price, note = apply_condition_adjustment(Decimal("50.00"), Condition.MP)
        assert price == Decimal("29.00")
        assert note is not None
        assert "MP" in note

    def test_hp_adjustment(self):
        """HP applies 0.33x multiplier."""
        price, note = apply_condition_adjustment(Decimal("100.00"), Condition.HP)
        assert price == Decimal("33.00")
        assert note is not None
        assert "HP" in note

    def test_dmg_adjustment(self):
        """DMG applies 0.15x multiplier."""
        price, note = apply_condition_adjustment(Decimal("200.00"), Condition.DMG)
        assert price == Decimal("30.00")
        assert note is not None
        assert "DMG" in note
        assert "0.15" in note

    def test_dmg_minus_clamps(self):
        """DMG- clamps to DMG's multiplier."""
        price, note = apply_condition_adjustment(
            Decimal("200.00"), Condition.DMG, ConditionModifier.MINUS
        )
        assert price == Decimal("30.00")
        assert note is not None
        assert "DMG-" in note

    def test_rounding(self):
        """Sub-cent results are rounded to 2 decimal places."""
        # 77.73 * 0.82 = 63.7386 -> 63.74
        price, _ = apply_condition_adjustment(Decimal("77.73"), Condition.LP)
        assert price == Decimal("63.74")

    def test_every_condition_has_a_multiplier(self):
        """No Condition member silently defaults — all must be handled."""
        for cond in Condition:
            # Must not raise
            mult = condition_multiplier(cond)
            assert mult > Decimal(0)
            assert mult <= Decimal("1.00")
