# T1 — Generic server-side sort over one field registry

**RFC:** 0011 §A · **Layer:** backend · **Depends on:** — · **Blocks:** T2
**Owner report:** *"I should also be able to sort every column by clicking on the name,
just like how some of the columns already have functionality for."*

## The problem, exactly

`_sort_admin_results` (`backend/src/merlins_collection/routers/admin/inventory.py:1149`)
is an if/elif chain over **eight** field names. The frontend registry declares **33**
columns. So 25 headers either are not clickable or — worse — would silently return an
unsorted list if they were, because the chain's `else` branch returns `""` for every
unknown field and the function returns `items` untouched on an unparseable `sort`.

**The wire format does not change.** It stays `{field}_{direction}`, parsed with
`rsplit("_", 1)`. CLAUDE.md already records why: `Column.key` on the frontend **is** the
backend's sort field, so renaming either breaks the other.

## Files

- **Create:** `backend/src/merlins_collection/services/inventory_sort.py`
- **Modify:** `backend/src/merlins_collection/routers/admin/inventory.py` — replace
  `_sort_admin_results` (line 1149), add `_validate_sort` beside `_validate_triage_reason`
  (line 1221), call it next to the existing `_validate_triage_reason(triage_reason)` at
  line 138
- **Test:** `backend/tests/services/test_inventory_sort.py` (new)

## Interfaces

**Produces** (T2 and T3 rely on these names):

```python
SORT_FIELDS: dict[str, Callable[[InventoryItem], Any]]   # field -> value extractor
SORT_ALIASES: dict[str, str]                             # {"price": "current_market_value", "name": "display_name"}
def resolve_sort_field(field: str) -> str | None          # applies aliases; None if unknown
def sort_items(items: list[InventoryItem], sort: str | None) -> list[InventoryItem]
def parse_sort(sort: str) -> tuple[str, bool] | None      # (resolved_field, reverse) or None
```

## Design

### Three rules, and they are the whole task

**1. Missing sorts LAST, in both directions.** Today money fields do this with a `±inf`
sentinel that depends on `reverse`; strings do not, so blanks bunch at whichever end you
are not looking at. Generalize it by **partitioning instead of sentinel values** — clearer
and correct for every type:

```python
present = [i for i in items if extract(i) is not None]
missing = [i for i in items if extract(i) is None]
present.sort(key=extract, reverse=reverse)
return present + missing
```

**2. Condition sorts by an ordinal rank, not alphabetically.** `str(cond)` makes `LP+`
and `LP-` identical — the exact distinction RFC 0008 T2 went to trouble to store in two
fields. Rank is computed from both, and **higher rank = better condition**, so `asc`
means worst-first exactly as it does for money.

**3. An unknown sort field is a 422.** Not a silently unsorted list. Same precedent as
`_validate_triage_reason` — an ignored parameter is indistinguishable from a broken one.

### The module

```python
"""Sort keys for the admin inventory table — one registry, one extractor.

`_sort_admin_results` used to be an if/elif chain over eight field names while the
admin table offered thirty-three columns, so twenty-five headers had no order at all.
This module is the registry both halves read.

Three properties are load-bearing and each has a test:

* **missing sorts LAST in both directions.** Achieved by partitioning, not by a `±inf`
  sentinel — a sentinel has to know `reverse`, and only worked for numbers, so blank
  strings bunched at whichever end the admin was not looking at.
* **condition has a real ordinal rank.** `str(condition)` sorted alphabetically and
  ignored `condition_modifier` entirely, rendering `LP+` and `LP-` indistinguishable.
* **an unknown field raises, it does not shrug.** See `resolve_sort_field`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from merlins_collection.models.inventory import (
    Condition,
    ConditionModifier,
    InventoryItem,
)
from merlins_collection.services.card_text import admin_item_name

#: Worst-to-best, so a bigger number is a better card and `asc` means worst-first —
#: the same direction money sorts in. Modifier offsets are applied WITHIN a tier.
_TIER_ORDER: tuple[Condition, ...] = (
    Condition.DMG, Condition.HP, Condition.MP, Condition.LP, Condition.NM,
)
_MODIFIER_OFFSET: dict[ConditionModifier | None, int] = {
    ConditionModifier.MINUS: 0,
    None: 1,
    ConditionModifier.PLUS: 2,
}


def _condition_rank(item: InventoryItem) -> int | None:
    """Ordinal condition, modifier included. Higher is better. None when ungraded.

    Only the raw kind carries `condition`, so `getattr` rather than attribute access —
    a sealed box has no condition and must sort into the missing bucket, not crash.
    """
    condition = getattr(item, "condition", None)
    if condition is None:
        return None
    try:
        tier = _TIER_ORDER.index(Condition(condition))
    except ValueError:
        return None
    modifier = getattr(item, "condition_modifier", None)
    return tier * 3 + _MODIFIER_OFFSET.get(modifier, 1)


def _money(field: str) -> Callable[[InventoryItem], float | None]:
    def extract(item: InventoryItem) -> float | None:
        value = getattr(item, field, None)
        return None if value is None else float(value)
    return extract


def _text(field: str) -> Callable[[InventoryItem], str | None]:
    def extract(item: InventoryItem) -> str | None:
        value = getattr(item, field, None)
        # An empty string is "not set" for sorting purposes, so it joins the
        # missing bucket rather than sorting to the top of an ascending list.
        return None if value is None or value == "" else str(value).lower()
    return extract


def _moment(field: str) -> Callable[[InventoryItem], float | None]:
    def extract(item: InventoryItem) -> float | None:
        value = getattr(item, field, None)
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day).timestamp()
        return None
    return extract


def _flag(field: str) -> Callable[[InventoryItem], bool | None]:
    def extract(item: InventoryItem) -> bool | None:
        value = getattr(item, field, None)
        return None if value is None else bool(value)
    return extract
```

Then the registry itself. **Hand-listed rather than derived**, so the file reads as the
contract; a test below proves it is total over the model.

```python
SORT_FIELDS: dict[str, Callable[[InventoryItem], Any]] = {
    # Effective name — override-first, the same resolution every other surface uses.
    "display_name": lambda i: (admin_item_name(i) or "").lower() or None,
    "status": _text("status"),
    "kind": _text("kind"),
    "condition": _condition_rank,
    "location": _text("location"),
    "cost_basis": _money("cost_basis"),
    "current_market_value": _money("current_market_value"),
    "sticker_price": _money("sticker_price"),
    "listed_price": _money("listed_price"),
    "market_value_at_purchase": _money("market_value_at_purchase"),
    "grade": _money("grade"),
    "acquired_at": _moment("acquired_at"),
    "reviewed_at": _moment("reviewed_at"),
    "no_catalog_match_at": _moment("no_catalog_match_at"),
    "needs_review": _flag("needs_review"),
    "factory_sealed": _flag("factory_sealed"),
    "no_catalog_match": _flag("no_catalog_match"),
    # Presence, not the terms object — "consigned or owned" is the question the
    # Ownership column asks, and ConsignmentTerms is not comparable.
    "consignment": lambda i: getattr(i, "consignment", None) is not None,
    "card_id": _text("card_id"),
    "language": _text("language"),
    "finish": _text("finish"),
    "company": _text("company"),
    "cert_number": _text("cert_number"),
    "product_type": _text("product_type"),
    "description": _text("description"),
    "sticker_notes": _text("sticker_notes"),
    "acquired_show_id": _text("acquired_show_id"),
    "notes": _text("notes"),
    "value_note": _text("value_note"),
    "review_reason": _text("review_reason"),
    "display_name_override": _text("display_name_override"),
    "tcg_url": _text("tcg_url"),
    "lineage_id": _text("lineage_id"),
    "predecessor_item_id": _text("predecessor_item_id"),
    "item_id": _text("item_id"),
    "condition_modifier": _text("condition_modifier"),
    "cert_verified_at": _moment("cert_verified_at"),
}

#: Kept for compatibility. `price` is what the customer-facing sort has always sent;
#: `name` is what `_sort_admin_results` accepted alongside `display_name`.
SORT_ALIASES: dict[str, str] = {
    "price": "current_market_value",
    "name": "display_name",
}


def resolve_sort_field(field: str) -> str | None:
    """The registry key this field means, or None if it means nothing."""
    resolved = SORT_ALIASES.get(field, field)
    return resolved if resolved in SORT_FIELDS else None


def parse_sort(sort: str) -> tuple[str, bool] | None:
    """`("cost_basis", True)` for `"cost_basis_desc"`. None if unparseable or unknown.

    `rsplit` on the LAST underscore, because field names contain underscores and
    directions do not. Do not change this without re-checking every `Column.key`.
    """
    parts = sort.rsplit("_", 1)
    if len(parts) != 2 or parts[1] not in ("asc", "desc"):
        return None
    resolved = resolve_sort_field(parts[0])
    return None if resolved is None else (resolved, parts[1] == "desc")


def sort_items(items: list[InventoryItem], sort: str | None) -> list[InventoryItem]:
    """Sort by the requested field. Missing values sort LAST in both directions."""
    if sort is None:
        return items
    parsed = parse_sort(sort)
    if parsed is None:
        return items          # the router validates first; this is belt to that's braces
    field, reverse = parsed
    extract = SORT_FIELDS[field]
    present = [i for i in items if extract(i) is not None]
    missing = [i for i in items if extract(i) is None]
    present.sort(key=extract, reverse=reverse)
    return present + missing
```

### The router change

Replace the body of `_sort_admin_results` with a delegation (keep the name — other call
sites and tests use it), and add the validator:

```python
def _validate_sort(sort: str | None) -> None:
    """422 on a sort field that is not in the registry.

    Never a silent no-op. An ignored `sort` returns the list in table order, which looks
    exactly like "this column has no order" — the same indistinguishable-failure class
    `_validate_triage_reason` was written to eliminate.
    """
    if sort is not None and parse_sort(sort) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown sort {sort!r}. Expected {{field}}_asc or {{field}}_desc, "
                f"where field is one of: {', '.join(sorted(SORT_FIELDS))}."
            ),
        )
```

Call it immediately after `_validate_triage_reason(triage_reason)` at line 138 — before
the table read, because a caller mistake must not cost a full `list_inventory()`.

## RED — write these first, show the failing output, then STOP

`backend/tests/services/test_inventory_sort.py`:

```python
"""Sort registry — RFC 0011 T1."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import (
    BulkInventoryItem,
    Condition,
    ConditionModifier,
    GradedInventoryItem,
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
        cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
        finish="normal", condition=Condition.NM,
    )
    base.update(over)
    return RawInventoryItem(**base)


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
        """The half that was broken: a blank string used to sort to the TOP ascending."""
        named = raw(item_id="named", notes="alpha")
        other = raw(item_id="other", notes="zulu")
        blank = raw(item_id="blank", notes=None)
        empty = raw(item_id="empty", notes="")

        result = sort_items([blank, other, empty, named], f"notes_{direction}")

        assert set(ids(result)[-2:]) == {"blank", "empty"}


class TestConditionRank:
    def test_modifiers_order_within_a_tier(self):
        """LP+ beats LP beats LP-. Alphabetical sorting could not express this at all."""
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

    def test_an_item_with_no_condition_sorts_last(self):
        """A sealed box has no `condition` attribute at all — it must not crash."""
        sealed = SealedInventoryItem(
            item_id="sealed", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
            product_name="Booster Box", product_type="booster_box",
        )
        nm = raw(item_id="nm", condition=Condition.NM)

        assert ids(sort_items([sealed, nm], "condition_asc"))[-1] == "sealed"


class TestEffectiveName:
    def test_display_name_override_wins(self):
        """One rule everywhere: the override outranks the stored name."""
        overridden = raw(item_id="a", display_name="Zzz", display_name_override="Aaa")
        plain = raw(item_id="b", display_name="Bbb")

        assert ids(sort_items([plain, overridden], "display_name_asc")) == ["a", "b"]


class TestUnknownFields:
    def test_unknown_field_does_not_parse(self):
        assert parse_sort("not_a_field_asc") is None

    def test_unknown_direction_does_not_parse(self):
        assert parse_sort("cost_basis_sideways") is None

    def test_price_alias_still_resolves(self):
        """The customer-facing sort has always sent `price`. It must keep working."""
        assert resolve_sort_field("price") == "current_market_value"
        assert parse_sort("price_desc") == ("current_market_value", True)

    def test_name_alias_still_resolves(self):
        assert parse_sort("name_asc") == ("display_name", False)


class TestRegistryIsTotal:
    """Coverage is structural, not a promise. A new model field fails this test."""

    #: Fields that deliberately have no sort. Add here WITH a reason, never silently.
    NOT_SORTABLE = {
        "kind",              # the discriminator, already covered by its own key below
        "consignment",       # covered by a presence extractor, asserted separately
        "condition",         # covered by the rank extractor, asserted separately
        "display_name",      # covered by the effective-name extractor
        "prices",
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
```

And in the router tests (`backend/tests/routers/` — find the file already covering
`GET /admin/inventory/search`), add:

```python
def test_unknown_sort_field_is_a_422(admin_client):
    """A silently-unsorted list is indistinguishable from a column with no order."""
    response = admin_client.get("/admin/inventory/search", params={"sort": "wibble_asc"})
    assert response.status_code == 422
    assert "wibble_asc" in response.json()["detail"]
```

**Run it, show the owner the failures, and WAIT.** Expected: `ModuleNotFoundError: No
module named 'merlins_collection.services.inventory_sort'` on the service tests, and
`200 != 422` on the router test.

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/test_inventory_sort.py -q --tb=short
```

## GREEN

Write `inventory_sort.py` as designed above, then rewire the router. `_sort_admin_results`
keeps its name and signature and becomes:

```python
def _sort_admin_results(items, sort):
    """Sort items by the requested criteria. See `services.inventory_sort`."""
    return sort_items(items, sort)
```

## Watch for

- **`grade` is a `Decimal` on the graded kind only.** `_money` handles the absence via
  `getattr(..., None)`; do not switch it to attribute access.
- **`admin_item_name` lives in `services/card_text.py`.** Do not inline
  `display_name or product_name` — CLAUDE.md names four implementations kept in sync and
  this would be a fifth that drifts.
- **`no_catalog_match` / `no_catalog_match_at` are in the registry but do not exist as
  model fields until T5.** `getattr(..., None)` means they extract as `None` until then,
  which is correct and harmless. The totality test only checks the other direction
  (model → registry), so it passes either way.
- **Existing tests may assert the silent-unsorted behavior.** Search
  `backend/tests` for `_sort_admin_results` and for `sort` params with junk values, and
  update them deliberately. Record what you changed in `progress.md`.

## Done means

1. `pytest backend/tests/services/test_inventory_sort.py` passes, output shown;
2. the router test file you touched passes;
3. `./.venv/Scripts/python.exe -m ruff check backend/src` is clean;
4. `progress.md` updated — status, sha, and a Notes line naming any pre-existing test you
   had to change for the 422.

Do not run the full suite. Do not merge. Do not push.
