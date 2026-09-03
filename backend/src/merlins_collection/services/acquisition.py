"""Acquisition economics — RFC 0024 T1.

One authority for the acquisition ratio, mirrored (not shared over the wire)
by ``frontend/lib/acquisition.ts``'s ``acquisitionRatio``. The two are pinned
together by a shared fixture — see ``backend/tests/test_cross_boundary.py``
and ``frontend/lib/__tests__/acquisition.test.ts``, both of which load
``shared/test-fixtures/acquisition-ratio-cases.json``.

``acquisition_ratio`` is deliberately NOT stored on ``InventoryItem``. It is
derived from two stored inputs (``market_value_at_purchase``, ``cost_basis``)
and would go stale the moment either changes — including from this same RFC's
own ``cost_basis`` sync on a transaction edit. Compute it at read time, every
time.
"""

from decimal import ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")


def acquisition_ratio(
    market_value_at_purchase: Decimal | None,
    cost_basis: Decimal | None,
) -> Decimal | None:
    """``market_value_at_purchase / cost_basis``, as a PERCENT.

    The owner's "market at purchase / amount paid" — 312.50 means we paid $32
    for a card the market said was worth $100 at the time.

    ``None`` when either figure is absent, or when ``cost_basis`` is zero. A
    free card (a throw-in, a bulk lot) is a real and routine thing at a buy
    table, and its ratio is not "infinite" or "0" — it is undefined, and
    rendering either number would be a claim nobody made. Every caller must
    handle ``None`` and render an em dash.

    Rounded to two decimal places (``ROUND_HALF_UP``) so cross-language
    precision differences between Python's arbitrary-precision ``Decimal``
    and JavaScript's float64 ``Number`` cannot produce a spurious mismatch on
    a repeating-decimal division (e.g. 10/3) — both sides round to the same
    bounded precision before anything compares them.

    A negative ``cost_basis`` is out of scope: nothing upstream can produce
    one (``parseMoney`` and the backend's own money fields reject negative
    amounts before a value ever reaches storage), so this function only
    special-cases zero, not sign.
    """
    if market_value_at_purchase is None or cost_basis is None:
        return None
    if cost_basis == 0:
        return None

    raw = (market_value_at_purchase / cost_basis) * 100
    return raw.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
