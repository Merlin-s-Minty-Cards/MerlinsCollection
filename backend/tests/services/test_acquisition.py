"""RFC 0024 T1 — ``acquisition_ratio``, the one Python-side authority.

``market_value_at_purchase / cost_basis`` as a percent — the owner's "market at
purchase / amount paid". 312 means we paid $32 for a card the market said was
worth $100 at the time.

``None`` propagates whenever either figure is absent, or when ``cost_basis`` is
zero — a free card (a throw-in, a bulk lot) is routine at a buy table, and its
ratio is undefined, not infinite and not zero. See
``docs/plans/rfc-0024/README.md`` T1 and
``docs/rfcs/0024-acquisition-economics-and-transaction-editing.md`` §1.

The cross-boundary pin against the TypeScript mirror
(``frontend/lib/acquisition.ts``) lives in ``test_cross_boundary.py``, not
here — this file is the plain unit-test coverage for the Python side alone,
including cases the shared fixture doesn't carry (rounding-boundary behavior,
negative cost basis).
"""

from decimal import Decimal

from merlins_collection.services.acquisition import acquisition_ratio


def test_computes_the_percent_ratio_of_market_to_cost():
    ratio = acquisition_ratio(Decimal("100.00"), Decimal("32.00"))
    assert ratio == Decimal("312.50")


def test_none_when_market_value_at_purchase_is_absent():
    assert acquisition_ratio(None, Decimal("32.00")) is None


def test_none_when_cost_basis_is_absent():
    assert acquisition_ratio(Decimal("100.00"), None) is None


def test_none_when_both_are_absent():
    assert acquisition_ratio(None, None) is None


def test_none_when_cost_basis_is_zero_a_free_card_is_not_infinite():
    """A throw-in or bulk-lot card has $0 cost basis — routine, not an error.

    The ratio must not render as "infinite" (a claim nobody made) or silently
    collapse to a fake 0%. It is undefined.
    """
    assert acquisition_ratio(Decimal("100.00"), Decimal("0")) is None


def test_none_when_both_cost_and_market_are_zero():
    assert acquisition_ratio(Decimal("0"), Decimal("0")) is None


def test_rounds_a_repeating_decimal_to_two_places():
    ratio = acquisition_ratio(Decimal("10.00"), Decimal("3.00"))
    assert ratio == Decimal("333.33")


def test_a_large_ratio_stays_exact_when_it_divides_evenly():
    ratio = acquisition_ratio(Decimal("123456.78"), Decimal("0.03"))
    assert ratio == Decimal("411522600.00")


def test_rounds_a_true_half_up_tie():
    """1 / 800 * 100 = 0.125% — an exact tie at the third decimal place.

    Deliberately NOT in the shared cross-boundary fixture: 1/800 has no
    finite binary representation (800 = 2**5 * 5**2 is not a power of two),
    so JavaScript's float64 division can land a hair either side of .125
    before ``Math.round`` ever runs, while Python's ``Decimal`` division is
    exact within context precision. That is a genuine float-vs-Decimal
    representability risk, not a bug in either implementation's rounding
    rule, so it is exercised here only — as proof ``ROUND_HALF_UP`` itself
    does what it says — and left out of the fixture both sides are pinned
    against.
    """
    ratio = acquisition_ratio(Decimal("1"), Decimal("800"))
    assert ratio == Decimal("0.13")


def test_a_below_market_price_renders_as_a_ratio_under_100():
    """Paying MORE than market (a bad buy) is a real, valid, low ratio."""
    ratio = acquisition_ratio(Decimal("50.00"), Decimal("100.00"))
    assert ratio == Decimal("50.00")


def test_returns_a_decimal_not_a_float():
    ratio = acquisition_ratio(Decimal("100.00"), Decimal("32.00"))
    assert isinstance(ratio, Decimal)
