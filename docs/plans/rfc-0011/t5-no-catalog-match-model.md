# T5 — `no_catalog_match` and the triage predicate

**RFC:** 0011 §C · **Layer:** backend · **Depends on:** — · **Blocks:** T6, T7, T8
**Owner report:** *"Since a lot of cards don't have matches in the catalog… there should
be a new tab that is just for cards that do not have a match in TCGdex, so we can send
them from triage to that tab until TCGdex receives an update… this tab would let us move
cards out of triage, so triage is specifically for cards that actually have errors."*

## This is the load-bearing task of the whole RFC

`is_missing_card_id` is a **derived** triage reason (`services/triage.py:38-48`) — it is
`item.card_id is None`, recomputed on every read. There is no stored state anywhere
meaning *"we looked, and TCGdex has no match"*. So a card the catalog does not carry is
in Triage **permanently**, and the queue whose stated goal is to reach zero has a floor
it can never get under.

Everything else on this track is downstream of one line in one function.

## Files

- **Modify:** `backend/src/merlins_collection/models/inventory.py` — two fields on
  `_ItemBase` (line 190-249) and a model validator
- **Modify:** `backend/src/merlins_collection/services/triage.py` — `is_missing_card_id`
  (line 38-48)
- **Modify:** `backend/src/merlins_collection/routers/admin/inventory.py` — a
  `no_catalog_match` query param on the search; stamp `no_catalog_match_at` in the `PUT`
  handler (line 420)
- **Test:** `backend/tests/services/test_triage.py` (existing),
  `backend/tests/models/` (existing inventory model tests), and the router test file

## Interfaces

**Produces** (T6, T7, T8 rely on these exact names):

```python
# models/inventory.py, on _ItemBase
no_catalog_match: bool = False
no_catalog_match_at: datetime | None = None
```

```
GET /admin/inventory/search?no_catalog_match=true   -> the parked cohort
PUT /admin/inventory/{item_id}  body: {"no_catalog_match": true}
```

## Design

### The two fields

```python
    # Stored answer to a question the derived `missing_card_id` reason cannot ask:
    # "we looked, and TCGdex does not carry this card." Without it an unmatchable
    # card sits in Triage forever, because `is_missing_card_id` is recomputed on
    # every read and will keep being true no matter how many times a human confirms
    # there is nothing to match. See RFC 0011 §C.
    #
    # INTERNAL. Deliberately kept OUT of `_CUSTOMER_ITEM_FIELDS`, same rule as
    # `review_reason` — a customer has no use for our cataloguing backlog.
    no_catalog_match: bool = False
    # Stamped by the SERVER when the flag is set; the client never sends it. Drives
    # "parked 3 weeks ago" on the queue and lets the list sort oldest-first.
    no_catalog_match_at: datetime | None = None
```

### The invariant, enforced in the model

**`no_catalog_match=True` implies `card_id is None`.**

```python
    @model_validator(mode="after")
    def _unmatched_implies_unlinked(self):
        """A card that is matched is not unmatched.

        Allowing both to be true creates a row that is simultaneously in Triage's
        "no catalog link" reason and in the queue that exists to hold cards which have
        no link — two answers to one question, which is the state this whole feature
        exists to remove. The admin's route is: unlink first, which T6 does in the same
        click.

        `getattr`, not attribute access: sealed and bulk items have no `card_id` field
        at all, and must never be parkable.
        """
        if self.no_catalog_match and getattr(self, "card_id", None) is not None:
            raise ValueError(
                "no_catalog_match cannot be set on an item that still has a card_id; "
                "unlink the card first"
            )
        return self
```

This lives on `_ItemBase`, so all four kinds inherit it. It raises `ValueError`, which
Pydantic surfaces and FastAPI renders as a **422** on the `PUT` — the message the admin
needs, without a hand-written check in the router.

### Sealed and bulk can never be parked

They have no `card_id` field. The validator's `getattr` handles the linked case, but a
sealed box could still be parked with `card_id` absent. Add the guard in the router's
`PUT` handler:

```python
    if body.get("no_catalog_match") and not hasattr(item, "card_id"):
        raise HTTPException(
            status_code=422,
            detail=(f"A {item.kind} item has no catalog link to be missing. "
                    "Only raw and graded items can be marked as having no catalog match."),
        )
```

Same `hasattr` reasoning `is_missing_card_id` already documents at line 44-46.

### Server-stamping, and the two automatic clears

In the `PUT /admin/inventory/{item_id}` handler:

```python
    # Server-stamped, never client-supplied — the same rule `reviewed_at` follows.
    if patch.get("no_catalog_match") and not item.no_catalog_match:
        patch["no_catalog_match_at"] = datetime.now(tz=timezone.utc)
    if patch.get("no_catalog_match") is False:
        patch["no_catalog_match_at"] = None

    # Pairing is the exit condition. Requiring a SECOND write to leave the queue is
    # how rows get stranded in it, so assigning a card_id clears the flag here rather
    # than asking the caller to remember.
    if patch.get("card_id") is not None:
        patch["no_catalog_match"] = False
        patch["no_catalog_match_at"] = None
```

Note the ordering: the `card_id` clear runs **last**, so a single body carrying both
`card_id` and `no_catalog_match: true` resolves to "paired", not to a validation error.

### The one line that does the work

```python
def is_missing_card_id(item: InventoryItem) -> bool:
    """Derived: a catalog-linkable item that never matched a catalog row.

    ``getattr``, not ``item.card_id``: only the raw and graded kinds carry the
    field at all. Sealed product and bulk lots have no catalog link BY DESIGN,
    so a plain attribute access would both raise ``AttributeError`` and, if
    defaulted to None, drag every sealed box into the queue permanently.

    ``no_catalog_match`` is an admin's explicit answer that TCGdex does not carry this
    card. It is stored precisely because this function is DERIVED: without it, a human
    could confirm "there is nothing to match" a hundred times and the row would return
    to the queue on every read (RFC 0011 §C). A parked item that is ALSO flagged or
    unnamed keeps those reasons and stays in Triage — those are real errors, and
    "the catalog does not have it" is not.
    """
    if not hasattr(item, "card_id"):
        return False
    if item.no_catalog_match:
        return False
    return item.card_id is None
```

Because `GET /admin/inventory/search?triage=true` and `GET /admin/triage/counts` both
route through this function, the list and the sidebar badge cannot disagree about it.
**That is the property `services/triage.py` exists to guarantee — do not add the check
anywhere else.**

### The search parameter

```python
    no_catalog_match: bool | None = Query(None),
```

applied with the other named filters:

```python
    if no_catalog_match is not None:
        items = [i for i in items if getattr(i, "no_catalog_match", False) == no_catalog_match]
```

**No new list endpoint.** The queue is
`GET /admin/inventory/search?no_catalog_match=true`, on the same "reuse before adding"
rule that keeps Triage on the shared search (`routers/admin/triage.py:3-6`).

## RED — write these first, show the failing output, then STOP

In `backend/tests/services/test_triage.py`:

```python
class TestNoCatalogMatch:
    """RFC 0011 §C — the stored answer a derived reason cannot hold."""

    def test_a_parked_item_leaves_the_missing_card_id_reason(self):
        item = raw_item(card_id=None, no_catalog_match=True)
        assert is_missing_card_id(item) is False
        assert "missing_card_id" not in reasons_for(item)

    def test_an_unparked_unlinked_item_still_has_the_reason(self):
        assert is_missing_card_id(raw_item(card_id=None)) is True

    def test_a_parked_item_with_no_other_problem_leaves_triage(self):
        """The whole point: the queue can now reach zero."""
        assert needs_triage(raw_item(card_id=None, no_catalog_match=True)) is False

    def test_a_parked_item_that_is_also_flagged_stays_in_triage(self):
        """Parking answers ONE question. A human's flag is a different, real problem."""
        item = raw_item(card_id=None, no_catalog_match=True, needs_review=True)
        assert needs_triage(item) is True
        assert reasons_for(item) == ["flagged"]

    def test_a_parked_jp_item_with_no_english_name_stays_in_triage(self):
        item = raw_item(card_id=None, no_catalog_match=True,
                        language=Language.JP, display_name_override=None)
        assert "missing_english_name" in reasons_for(item)

    def test_the_list_and_the_counts_agree_about_parked_items(self, repo, admin_client):
        """One predicate, two consumers. A badge that counts differently is worse
        than no badge."""
        repo.put_inventory_item(raw_item(item_id="parked", card_id=None,
                                         no_catalog_match=True))
        repo.put_inventory_item(raw_item(item_id="open", card_id=None))

        listed = admin_client.get("/admin/inventory/search", params={"triage": "true"})
        counts = admin_client.get("/admin/triage/counts")

        assert [i["item_id"] for i in listed.json()["items"]] == ["open"]
        assert counts.json()["total"] == 1
```

In the model tests:

```python
class TestUnmatchedInvariant:
    def test_cannot_park_an_item_that_still_has_a_card_id(self):
        with pytest.raises(ValidationError, match="unlink the card first"):
            raw_item(card_id="en:base1-4", no_catalog_match=True)

    def test_parking_an_unlinked_item_is_fine(self):
        assert raw_item(card_id=None, no_catalog_match=True).no_catalog_match is True

    def test_no_catalog_match_is_not_a_customer_field(self):
        """INTERNAL, same rule as review_reason. A customer has no use for our
        cataloguing backlog."""
        from merlins_collection.routers.inventory import _CUSTOMER_ITEM_FIELDS
        assert "no_catalog_match" not in _CUSTOMER_ITEM_FIELDS
        assert "no_catalog_match_at" not in _CUSTOMER_ITEM_FIELDS
```

In the router tests — **including the one the owner asked for by name**:

```python
def test_the_unmatched_queue_ships_empty(admin_client, repo):
    """Owner requirement, 2026-08-13, verbatim: "make sure that the new tab is empty
    right now, all cards that go there should only be moved under admin supervision."

    Nothing is backfilled and nothing auto-migrates. Unlinked inventory that no admin
    has touched must NOT appear here.
    """
    repo.put_inventory_item(raw_item(item_id="unlinked", card_id=None))

    response = admin_client.get("/admin/inventory/search",
                                params={"no_catalog_match": "true"})

    assert response.json()["items"] == []


def test_parking_stamps_the_server_side_timestamp(admin_client, repo):
    repo.put_inventory_item(raw_item(item_id="x", card_id=None))
    admin_client.put("/admin/inventory/x", json={"no_catalog_match": True})
    assert repo.get_inventory_item("x").no_catalog_match_at is not None


def test_assigning_a_card_id_unparks_automatically(admin_client, repo):
    """Pairing is the exit condition. A second write to leave the queue is how rows
    get stranded in it."""
    repo.put_inventory_item(raw_item(item_id="x", card_id=None, no_catalog_match=True))
    admin_client.put("/admin/inventory/x", json={"card_id": "en:base1-4"})
    item = repo.get_inventory_item("x")
    assert item.no_catalog_match is False
    assert item.no_catalog_match_at is None


def test_unparking_clears_the_timestamp(admin_client, repo):
    """Parking that cannot be undone is just a slower delete."""
    repo.put_inventory_item(raw_item(item_id="x", card_id=None, no_catalog_match=True,
                                     no_catalog_match_at=datetime.now(tz=timezone.utc)))
    admin_client.put("/admin/inventory/x", json={"no_catalog_match": False})
    assert repo.get_inventory_item("x").no_catalog_match_at is None


def test_a_sealed_item_cannot_be_parked(admin_client, repo):
    """Sealed product has no catalog link BY DESIGN — there is nothing missing."""
    repo.put_inventory_item(sealed_item(item_id="box"))
    response = admin_client.put("/admin/inventory/box", json={"no_catalog_match": True})
    assert response.status_code == 422
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/test_triage.py backend/tests/models -q --tb=short
```

## Watch for

- **No migration, no backfill, no script.** Do not write one, do not offer one. The
  owner's requirement is explicit and `test_the_unmatched_queue_ships_empty` pins it.
- **Do not add a fourth `TRIAGE_REASONS` predicate.** A new reason keeps the card in
  Triage, which is the opposite of the ask. The change is a *suppression* inside an
  existing predicate.
- **`_CUSTOMER_ITEM_FIELDS` lives in `routers/inventory.py:192`**, not in the model. It
  is an allowlist, so a new field is excluded by default — the test above pins that it
  stays that way rather than being helpfully added later.
- **`reviewed_at` is the pattern to copy** for server-stamping. Read its comment at
  `models/inventory.py:231-236`.

## Done means

1. `pytest backend/tests/services/test_triage.py backend/tests/models` passes;
2. the router test file passes, including all six new tests;
3. `ruff check backend/src` clean;
4. `progress.md` updated — and add a Notes line saying T6/T7/T8 can now proceed.

Do not run the full suite. Do not merge. Do not push.
