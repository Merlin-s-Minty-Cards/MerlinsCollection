"""Condition-aware pricing — multipliers applied to the raw market figure.

TCGdex relays TCGplayer USD / Cardmarket EUR as ONE market figure per finish,
and that figure is effectively a Near Mint price. This module applies a
condition-based multiplier so a Lightly Played card does not display the same
price as a Near Mint one.

The multiplier table was researched via secondary sources (convergent ranges
from multiple collector-market references + one real shipped buylist formula)
and OWNER-APPROVED 2026-07-30. Confidence is MEDIUM, not high — these are
triangulated launch defaults, not measured constants. The research write-up
behind them lived in the pre-RFC scratch roadmap and is no longer tracked; the
surviving record is CLAUDE.md's condition-pricing section and
``docs/plans/rfc-0008/follow-ups.md`` (the 2026-08-06 decision to apply these
customer-side, measured live at -18.5% across 73 of 228 items).

The age/era dimension was investigated and DROPPED (not supported by evidence,
not deferred). Do not add it without explicit owner direction.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from merlins_collection.models.inventory import Condition, ConditionModifier

# Anchor: NM = 1.00 (the market figure IS a NM price).
# Each tier below is the researched percentage of NM the condition commands.
_TIER_MULTIPLIERS: dict[Condition, Decimal] = {
    Condition.NM: Decimal("1.00"),
    Condition.LP: Decimal("0.82"),
    Condition.MP: Decimal("0.58"),
    Condition.HP: Decimal("0.33"),
    Condition.DMG: Decimal("0.15"),
}

# Ordered from best to worst, for midpoint computation between adjacent tiers.
_TIER_ORDER: list[Condition] = [
    Condition.NM, Condition.LP, Condition.MP, Condition.HP, Condition.DMG,
]


def _midpoint(a: Decimal, b: Decimal) -> Decimal:
    """Exact midpoint of two decimals, rounded to 2 decimal places."""
    return ((a + b) / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def condition_multiplier(
    condition: Condition,
    modifier: ConditionModifier | None = None,
) -> Decimal:
    """Return the multiplier for a given condition + optional modifier.

    The base tier multiplier is taken from the research-backed table. A ``+``
    modifier returns the midpoint between the tier and the tier above; a ``-``
    modifier returns the midpoint between the tier and the tier below.

    Edge cases (owner-approved clamp behavior):
    - NM+ has no tier above → clamps to NM's multiplier (1.00).
    - DMG- has no tier below → clamps to DMG's multiplier (0.15).

    Raises ``ValueError`` for an unrecognized condition (the enum is exhaustive,
    so this should never fire in practice — but it must fail loudly, not
    silently default to 1.0, per Phase 19 acceptance criteria).
    """
    base = _TIER_MULTIPLIERS.get(condition)
    if base is None:
        raise ValueError(f"Unrecognized condition tier: {condition!r}")

    if modifier is None:
        return base

    idx = _TIER_ORDER.index(condition)

    if modifier == ConditionModifier.PLUS:
        # Midpoint between this tier and the one above (lower index = better).
        if idx == 0:
            # NM+ → clamp to NM (no tier above).
            return base
        above = _TIER_MULTIPLIERS[_TIER_ORDER[idx - 1]]
        return _midpoint(base, above)

    if modifier == ConditionModifier.MINUS:
        # Midpoint between this tier and the one below (higher index = worse).
        if idx == len(_TIER_ORDER) - 1:
            # DMG- → clamp to DMG (no tier below).
            return base
        below = _TIER_MULTIPLIERS[_TIER_ORDER[idx + 1]]
        return _midpoint(base, below)

    # Defensive: ConditionModifier is a 2-member enum; reaching here would mean
    # a new member was added without updating this function.
    raise ValueError(f"Unrecognized condition modifier: {modifier!r}")


def apply_condition_adjustment(
    market_price: Decimal,
    condition: Condition,
    modifier: ConditionModifier | None = None,
) -> tuple[Decimal, str | None]:
    """Apply the condition multiplier to a raw market price.

    Returns:
        (adjusted_price, value_note) — the adjusted figure and an explanatory
        note for the ``value_note`` field (``None`` when no adjustment was made,
        i.e. NM without a modifier).

    The note makes the adjustment VISIBLE to both the customer and the owner,
    per Phase 19's visibility requirement.
    """
    mult = condition_multiplier(condition, modifier)

    adjusted = (market_price * mult).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )

    # NM with no modifier → multiplier is exactly 1.00 → no adjustment.
    if mult == Decimal("1.00"):
        return adjusted, None

    cond_label = condition.value
    if modifier is not None:
        cond_label += modifier.value

    note = f"Condition-adjusted ({cond_label}, {mult}x NM)"
    return adjusted, note
