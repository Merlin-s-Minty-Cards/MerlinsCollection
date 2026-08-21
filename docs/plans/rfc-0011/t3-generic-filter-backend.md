# T3 — A generic, validated filter layer

**RFC:** 0011 §B · **Layer:** backend · **Depends on:** — · **Blocks:** T4
**Owner report:** *"each column should have a dedicated filter… All filters should be
analyzed for whether they should be a max/min filter, a dropdown, a text input, or some
other kind of filter."*

## Why not 25 more named query parameters

`GET /admin/inventory/search` already has 20 parameters. Adding one (or two, for a range)
per remaining column puts it near 45, and every new field then needs a parameter, a test
and a frontend branch — which is precisely how the filter panel came to cover 12 of 33
columns in the first place. One validated generic parameter makes coverage a **data**
problem instead of a **code** problem.

## The rule this task must not break

**One evaluator.** The twelve existing named parameters keep working and are
re-expressed as sugar that builds the *same* `FieldFilter` objects the generic parameter
builds. Two spellings of a filter is fine; two *implementations* is the "two definitions
of countability" failure CLAUDE.md warns about under the ledger. A test asserts the two
forms return identical sets.

## Files

- **Create:** `backend/src/merlins_collection/services/inventory_filters.py`
- **Modify:** `backend/src/merlins_collection/routers/admin/inventory.py` — add the
  `filter` query parameter to `admin_inventory_search` (line 96-128), apply the parsed
  filters after the existing named ones (around line 268), add `_validate_filters`
  beside `_validate_triage_reason`
- **Test:** `backend/tests/services/test_inventory_filters.py` (new), plus the router
  test file covering `GET /admin/inventory/search`

## Interfaces

**Produces** (T4 mirrors these strings exactly in TypeScript):

```python
class FilterOp(StrEnum):
    CONTAINS = "contains"; EQ = "eq"; GTE = "gte"; LTE = "lte"
    ISNULL = "isnull"; NOTNULL = "notnull"

class FieldKind(StrEnum):
    TEXT = "text"; SELECT = "select"; RANGE = "range"
    DATE_RANGE = "dateRange"; PRESENCE = "presence"

FILTERABLE_FIELDS: dict[str, FieldKind]
OPS_BY_KIND: dict[FieldKind, frozenset[FilterOp]]

@dataclass(frozen=True)
class FieldFilter:
    field: str
    op: FilterOp
    value: str

def parse_filter(raw: str) -> FieldFilter          # raises ValueError on a bad shape
def apply_filters(items: list[InventoryItem], filters: list[FieldFilter]) -> list[InventoryItem]
```

## Design

### Wire format

A **repeatable** query parameter: `?filter=notes:contains:foil&filter=cost_basis:gte:100`.
Split on the **first two** colons only (`raw.split(":", 2)`), because a value can contain
a colon — `card_id:eq:en:base1-4` is a real query and the naive split loses it.

### The field registry

```python
#: Every field an admin can filter on, and the KIND of control it deserves.
#: This is the "analyzed for whether they should be a max/min filter, a dropdown, a
#: text input" answer from RFC 0011 §B, in the one place both halves read.
FILTERABLE_FIELDS: dict[str, FieldKind] = {
    # range — a min and a max box
    "cost_basis": FieldKind.RANGE,
    "current_market_value": FieldKind.RANGE,
    "sticker_price": FieldKind.RANGE,
    "listed_price": FieldKind.RANGE,
    "market_value_at_purchase": FieldKind.RANGE,
    "grade": FieldKind.RANGE,
    # dateRange — a from and a to box
    "acquired_at": FieldKind.DATE_RANGE,
    "reviewed_at": FieldKind.DATE_RANGE,
    "no_catalog_match_at": FieldKind.DATE_RANGE,
    # select — a closed list of values
    "status": FieldKind.SELECT,
    "kind": FieldKind.SELECT,
    "condition": FieldKind.SELECT,
    "location": FieldKind.SELECT,
    "language": FieldKind.SELECT,
    "finish": FieldKind.SELECT,
    "company": FieldKind.SELECT,
    "factory_sealed": FieldKind.SELECT,
    "needs_review": FieldKind.SELECT,
    "no_catalog_match": FieldKind.SELECT,
    "acquired_show_id": FieldKind.SELECT,
    # presence — "which of my cards are unlinked", the only question anyone asks
    # of card_id. Nobody types `en:sv3pt5-158` from memory.
    "card_id": FieldKind.PRESENCE,
    "consignment": FieldKind.PRESENCE,
    "display_name_override": FieldKind.PRESENCE,
    # text — substring, case-insensitive
    "display_name": FieldKind.TEXT,
    "review_reason": FieldKind.TEXT,
    "cert_number": FieldKind.TEXT,
    "product_type": FieldKind.TEXT,
    "description": FieldKind.TEXT,
    "sticker_notes": FieldKind.TEXT,
    "notes": FieldKind.TEXT,
    "value_note": FieldKind.TEXT,
    "tcg_url": FieldKind.TEXT,
    "lineage_id": FieldKind.TEXT,
    "predecessor_item_id": FieldKind.TEXT,
    "item_id": FieldKind.TEXT,
}

OPS_BY_KIND: dict[FieldKind, frozenset[FilterOp]] = {
    FieldKind.TEXT: frozenset({FilterOp.CONTAINS, FilterOp.EQ}),
    FieldKind.SELECT: frozenset({FilterOp.EQ}),
    FieldKind.RANGE: frozenset({FilterOp.GTE, FilterOp.LTE}),
    FieldKind.DATE_RANGE: frozenset({FilterOp.GTE, FilterOp.LTE}),
    FieldKind.PRESENCE: frozenset({FilterOp.ISNULL, FilterOp.NOTNULL}),
}
```

### Evaluation

Per-op predicates over `getattr(item, field, None)` — `getattr`, never attribute access,
because the four item kinds carry different fields and a sealed box has no `condition`.

```python
def _matches(item: InventoryItem, f: FieldFilter) -> bool:
    value = getattr(item, f.field, None)

    if f.op is FilterOp.ISNULL:
        return value is None
    if f.op is FilterOp.NOTNULL:
        return value is not None
    if value is None:
        # Every other op is a positive claim about a value. A row with no value
        # cannot satisfy one, and must not fall through to a truthy default.
        return False

    if f.op is FilterOp.CONTAINS:
        return f.value.lower() in str(value).lower()
    if f.op is FilterOp.EQ:
        # Booleans arrive as "true"/"false" from the browser; StrEnums compare as
        # their value. str() on both sides is what makes one branch serve all three.
        return str(value).lower() == f.value.lower()
    if f.op in (FilterOp.GTE, FilterOp.LTE):
        left, right = _comparable(value, f.value)
        return left >= right if f.op is FilterOp.GTE else left <= right
    return False
```

`_comparable` coerces both sides to `Decimal` for the range kinds and to `date` for the
date kinds, raising `ValueError` on junk so the router can 422 rather than silently
dropping every row:

```python
def _comparable(value, raw: str):
    """Both sides as one comparable type. Raises ValueError on an unparseable bound."""
    if isinstance(value, (datetime, date)):
        parsed = date.fromisoformat(raw)          # ValueError on junk
        left = value.date() if isinstance(value, datetime) else value
        return left, parsed
    return Decimal(str(value)), Decimal(raw)      # InvalidOperation is a ValueError
```

> **`Decimal(str(value))`, never `float(value)`.** Money on these models is `Decimal`,
> and routing a bound through binary float is how a `100.00` boundary starts excluding a
> `$100.00` card.

### Validation — 422, never a silent no-op

```python
def _validate_filters(raws: list[str]) -> list[FieldFilter]:
    """Parse and validate every `filter` param, or 422.

    Three distinct mistakes, three distinct messages: a malformed triple, an unknown
    field, and an op the field's kind does not support. A filter that quietly does
    nothing is indistinguishable from a list that is pulling everything — which is the
    exact report `_validate_triage_reason` was written to answer.
    """
    parsed: list[FieldFilter] = []
    for raw in raws:
        try:
            f = parse_filter(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        kind = FILTERABLE_FIELDS.get(f.field)
        if kind is None:
            raise HTTPException(
                status_code=422,
                detail=(f"Unknown filter field {f.field!r}. Expected one of: "
                        f"{', '.join(sorted(FILTERABLE_FIELDS))}."),
            )
        if f.op not in OPS_BY_KIND[kind]:
            raise HTTPException(
                status_code=422,
                detail=(f"Filter field {f.field!r} is a {kind.value} field and does not "
                        f"support {f.op.value!r}. Expected one of: "
                        f"{', '.join(sorted(OPS_BY_KIND[kind]))}."),
            )
        parsed.append(f)
    return parsed
```

Called next to `_validate_triage_reason(triage_reason)` at line 138, **before** the table
read.

### The named parameters become sugar

Keep every existing named parameter in the signature — other pages and the MCP server
send them. Re-express them as `FieldFilter`s so one evaluator runs:

```python
def named_filters(*, status=None, kind=None, location=None, min_price=None, ...) -> list[FieldFilter]:
    """The legacy named params, expressed in the generic vocabulary.

    One EVALUATOR, two spellings. Two evaluators is how a named filter and its generic
    twin come to disagree about the same question.
    """
```

**Four named parameters must NOT be routed through this and must keep their existing
bodies**, because they are not plain field comparisons:

| param | why it stays hand-written |
|---|---|
| `name` | `_item_matches_name` searches notes as well as names — that is what makes an unreadable JP card findable |
| `condition` | `_parse_condition_query` splits `LP+` into tier + modifier, and a bare tier means the whole tier |
| `min_price` / `max_price` | `_effective_price` falls back to cost when no market figure exists |
| `set_id` / `card_number` / `artist` | catalog joins, not item fields |

`ownership` **is** convertible: `owned` → `consignment:isnull:`, `cosigned` →
`consignment:notnull:`. That is the pair the equivalence test below uses.

## RED — write these first, show the failing output, then STOP

`backend/tests/services/test_inventory_filters.py`:

```python
"""Generic filter layer — RFC 0011 T3."""

from datetime import date
from decimal import Decimal

import pytest

from merlins_collection.models.inventory import (
    Condition, ConsignmentTerms, RawInventoryItem, SealedInventoryItem,
)
from merlins_collection.services.inventory_filters import (
    FILTERABLE_FIELDS, OPS_BY_KIND, FieldFilter, FieldKind, FilterOp,
    apply_filters, parse_filter,
)


def raw(**over):
    base = dict(cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
                finish="normal", condition=Condition.NM)
    base.update(over)
    return RawInventoryItem(**base)


def ids(items):
    return sorted(i.item_id for i in items)


class TestParsing:
    def test_splits_on_the_first_two_colons_only(self):
        """A card_id contains a colon: `en:base1-4`. A naive split loses it."""
        f = parse_filter("card_id:eq:en:base1-4")
        assert f == FieldFilter(field="card_id", op=FilterOp.EQ, value="en:base1-4")

    def test_a_malformed_triple_raises(self):
        with pytest.raises(ValueError):
            parse_filter("notes:contains")

    def test_an_unknown_op_raises(self):
        with pytest.raises(ValueError):
            parse_filter("notes:sortof:foil")


class TestOps:
    def test_contains_is_case_insensitive(self):
        hit = raw(item_id="hit", notes="Signed FOIL promo")
        miss = raw(item_id="miss", notes="ordinary")
        result = apply_filters([hit, miss], [parse_filter("notes:contains:foil")])
        assert ids(result) == ["hit"]

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
        result = apply_filters([exact], [parse_filter("cost_basis:gte:100")])
        assert ids(result) == ["exact"]

    def test_isnull_and_notnull_answer_the_linked_question(self):
        linked = raw(item_id="linked", card_id="en:base1-4")
        unlinked = raw(item_id="unlinked", card_id=None)
        assert ids(apply_filters([linked, unlinked],
                                 [parse_filter("card_id:isnull:")])) == ["unlinked"]
        assert ids(apply_filters([linked, unlinked],
                                 [parse_filter("card_id:notnull:")])) == ["linked"]

    def test_a_missing_value_never_satisfies_a_positive_op(self):
        """A row with no notes must not fall through into a `contains` result."""
        blank = raw(item_id="blank", notes=None)
        assert apply_filters([blank], [parse_filter("notes:contains:anything")]) == []

    def test_a_field_the_kind_does_not_carry_is_simply_excluded(self):
        """A sealed box has no `condition` attribute. getattr, not attribute access."""
        sealed = SealedInventoryItem(
            item_id="sealed", cost_basis=Decimal("1"), acquired_at=date(2026, 1, 1),
            product_name="Booster Box", product_type="booster_box",
        )
        assert apply_filters([sealed], [parse_filter("condition:eq:NM")]) == []

    def test_filters_and_combine(self):
        both = raw(item_id="both", notes="foil", cost_basis=Decimal("50"))
        one = raw(item_id="one", notes="foil", cost_basis=Decimal("5"))
        result = apply_filters(
            [both, one],
            [parse_filter("notes:contains:foil"), parse_filter("cost_basis:gte:10")],
        )
        assert ids(result) == ["both"]


class TestRegistryShape:
    def test_every_field_kind_declares_its_ops(self):
        for kind in FieldKind:
            assert OPS_BY_KIND[kind], f"{kind} declares no operators"

    def test_every_filterable_field_has_a_known_kind(self):
        for field, kind in FILTERABLE_FIELDS.items():
            assert isinstance(kind, FieldKind), field
```

And in the router test file, the three that matter most:

```python
def test_unknown_filter_field_is_a_422(admin_client):
    r = admin_client.get("/admin/inventory/search", params={"filter": "wibble:eq:x"})
    assert r.status_code == 422
    assert "wibble" in r.json()["detail"]


def test_an_op_the_field_does_not_support_is_a_422(admin_client):
    """`status` is a select. `contains` on it is a caller mistake, not a wide match."""
    r = admin_client.get("/admin/inventory/search",
                         params={"filter": "status:contains:avail"})
    assert r.status_code == 422


def test_the_named_param_and_its_generic_twin_agree(admin_client, seeded_inventory):
    """ONE evaluator. Two implementations is how the two forms come to disagree."""
    named = admin_client.get("/admin/inventory/search", params={"ownership": "owned"})
    generic = admin_client.get("/admin/inventory/search",
                               params={"filter": "consignment:isnull:"})
    assert named.status_code == generic.status_code == 200
    assert ([i["item_id"] for i in named.json()["items"]]
            == [i["item_id"] for i in generic.json()["items"]])
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/test_inventory_filters.py -q --tb=short
```

## GREEN

Build `inventory_filters.py`, then wire the router: add
`filter: list[str] = Query(default_factory=list)`, validate at line 138, and apply the
parsed filters immediately **before** the `_sort_admin_results` call at line 271 — after
the named filters, so an admin combining both gets the intersection.

## Watch for

- **`no_catalog_match` and `no_catalog_match_at` are in `FILTERABLE_FIELDS` but do not
  exist as model fields until T5.** `getattr(..., None)` means a filter on them matches
  nothing until then. That is correct, not a bug, and T5 does not have to come back here.
- **Do not convert `name`, `condition`, `min_price`/`max_price`, or the catalog filters
  into generic filters.** Each does something a field comparison cannot — the table above
  says what. Converting them is the one way this task can break existing behavior.
- **`Query(default_factory=list)`** — a mutable `[]` default on a FastAPI parameter is
  shared across requests.

## Done means

1. `pytest backend/tests/services/test_inventory_filters.py` passes, output shown;
2. the router test file passes, including the three new tests;
3. `ruff check backend/src` clean;
4. `progress.md` updated, with a Notes line confirming which named params were left
   hand-written and why.

Do not run the full suite. Do not merge. Do not push.
