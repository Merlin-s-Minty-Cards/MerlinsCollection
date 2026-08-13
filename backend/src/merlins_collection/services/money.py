"""One money parser for the API boundary, mirroring ``frontend/lib/money.ts``.

The frontend has a hard rule that every money field goes through one
``parseMoney`` and that ``parseFloat`` is banned. This is the same rule on the
server side: routers that accept an amount call ``coerce_decimal`` rather than
spelling the conversion themselves.

It lived as a private ``_coerce_decimal`` in ``routers/admin/purchases.py``
until a second router needed it. Two implementations of "read an amount off a
request" is a divergence this repo has already paid for — see CLAUDE.md's Ops
note on bare floats reaching DynamoDB, which is the same class of bug arriving
from the other direction.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

__all__ = ["coerce_decimal"]


def coerce_decimal(
    value: Any,
    field: str,
    *,
    required: bool,
    minimum: Decimal | None = None,
) -> Decimal | None:
    """Coerce a JSON number or numeric string to an exact ``Decimal``.

    Raises ``ValueError`` with an operator-readable message rather than letting
    ``InvalidOperation`` escape as an unhandled 500.

    Two traps this exists for:

    * ``Decimal("NaN")`` and ``Decimal("Infinity")`` both PARSE. A bare
      try/except around the conversion is not enough — ``is_finite()`` is part
      of the check, not a nicety.
    * conversion goes through ``str()`` so a JSON float lands as an exact
      ``Decimal`` rather than its binary approximation (CLAUDE.md, Ops).

    Accepts a number or a numeric string on purpose: MCP and curl are real
    clients, and the backend is the last line rather than a mirror of one
    form's habits.

    ``minimum`` is opt-in and defaults to off, so a caller that has never
    rejected a negative keeps accepting one until it decides otherwise. Pass
    ``Decimal(0)`` to refuse negatives. Note the bound is inclusive: **zero is
    a legitimate amount** — a free throw-in at a show is real, which is why the
    frontend's ``parseMoney('0')`` returns ``0`` rather than ``null`` and why
    nothing here may test falsiness.
    """
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        dec = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an amount, got {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"{field} must be a finite amount, got {value!r}")
    if minimum is not None and dec < minimum:
        raise ValueError(f"{field} must be at least {minimum}, got {value!r}")
    return dec
