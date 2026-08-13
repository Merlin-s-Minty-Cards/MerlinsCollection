# T9 — `first_seen_at`, and noticing new cards in sets we already hold

**RFC:** 0011 §F.1, §F.2 · **Layer:** backend · **Depends on:** — · **Blocks:** T10
**Owner ask:** *"if there could be some kind of widget on the dashboard to show any new
cards from TCGdex, that would be great, and then we can look at the new tab to see which
card can now be paired."*

## Two gaps, and both have to close for the widget to mean anything

**1. Nothing records when a catalog card was first seen.** `CatalogCard.last_synced_at`
is bumped by *any* write — a price refresh re-stamps a row from 2024. So "new" is
unanswerable at the card level.

**2. `_sync_new_sets` cannot see a new card inside a set we already hold.** It early-outs
on `missing_set_ids` (`catalog_sync.py:1031`) and walks `iter_brief_cards` **only** when
some set is entirely absent. Its own docstring is honest about the scope: *"a new Pokemon
set releases, we hold none of it yet."* A promo finally catalogued into an existing set —
**the exact case driving this RFC** — is invisible to it.

## Files

- **Modify:** `backend/src/merlins_collection/models/catalog.py` — one field on
  `CatalogCard` (line 63-94)
- **Modify:** `backend/src/merlins_collection/services/dynamodb.py` — the conditional
  write in `_upsert_catalog_cards_preserving_priced` (line 783-810) and
  `upsert_catalog_card_preserving_prices` (line 811)
- **Modify:** `backend/src/merlins_collection/services/catalog_sync.py` —
  `_sync_new_sets` (line 941-1077)
- **Create:** the `GET /admin/catalog/new-cards` route in
  `backend/src/merlins_collection/routers/admin/catalog.py`
- **Test:** `backend/tests/services/test_catalog_sync.py` (existing),
  `backend/tests/routers/test_admin_catalog.py` (existing)

## Interfaces

**Produces** (T10 renders these):

```python
# models/catalog.py
first_seen_at: datetime | None = None

# GET /admin/catalog/new-cards?since_days=30&limit=6
class NewCardsResponse(BaseModel):
    count: int                      # cards first seen within the window
    since: date                     # the window's start, so the UI need not recompute it
    cards: list[dict[str, Any]]     # a few, each with card_id/name/set_name/number/image/price
```

## Design

### `first_seen_at` — written once, never re-stamped

```python
    #: When this row first appeared in our catalog. `last_synced_at` cannot answer that
    #: question — it is bumped by ANY write, so a price refresh re-stamps a row from
    #: 2024 and every card looks new.
    #:
    #: `None` means "predates this field", NOT "new". All 31,603 rows seeded before
    #: RFC 0011 carry None, and every reader must count only non-null values — the same
    #: honesty `detail: brief|full` already keeps between "never fetched" and "no
    #: provider covers this".
    first_seen_at: datetime | None = None
```

**The write must be conditional, and this is the whole subtlety.** Two writers touch
catalog rows and they behave differently:

| writer | what it does | what must happen to `first_seen_at` |
|---|---|---|
| `batch_upsert_catalog_cards(preserve_priced=False)` — the full reseed | whole-item `put_item`, rewrites every row | **must not reset it** |
| `_upsert_catalog_cards_preserving_priced` / `upsert_catalog_card_preserving_prices` | conditional put, then a follow-up update on conflict | **must set it only on insert** |

A plain `put_item` carrying `first_seen_at=<now>` would reset all 31,603 rows on the next
reseed — the field would then mean "when we last rebuilt the catalog", which is useless.

So: **never write `first_seen_at` in the item body.** Set it with a separate conditional
update after the put:

```python
    def _stamp_first_seen(self, pk: str, sk: str, moment: datetime) -> None:
        """Set `first_seen_at` only if the row does not already have one.

        `attribute_not_exists` is what makes this idempotent. Writing the value in the
        item body instead would reset every row on the next full reseed — which
        whole-item `put_item`s every card — and the field would come to mean "when we
        last rebuilt the catalog", answering nobody's question.
        """
        try:
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET first_seen_at = :now",
                ConditionExpression="attribute_not_exists(first_seen_at)",
                ExpressionAttributeValues={":now": moment.isoformat()},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            # Already stamped. That is the expected outcome for every existing row.
```

### `_sync_new_sets` learns to walk

Two changes to `_sync_new_sets`:

**1. Always walk the brief cards**, not only when `missing_set_ids` is non-empty. Compare
each card id against what we already hold, and write identity-only rows for ids we have
never seen.

```python
        # Held ids for THIS language, gathered once. The membership test has to be a set
        # lookup — one `get_catalog_card` per brief card is 31,603 reads and turns a
        # button into a timeout.
        held_ids = {c.card_id for c in repo.list_cards_by_language(language)}

        for raw in client.iter_brief_cards(language):
            ...
            if card.card_id in held_ids:
                continue
            if card.set_id in missing_set_ids:
                added_by_set[card.set_id] = added_by_set.get(card.set_id, 0) + 1
            else:
                # The case this RFC exists for: a promo finally catalogued into a set
                # we already hold. `_sync_new_sets` could not see these at all — it
                # early-outed on `missing_set_ids` and never walked.
                cards_added_to_existing_sets += 1
            buffer.append(card)
```

**2. Report it.** The summary gains `cards_added_to_existing_sets`, so the Market page's
"check for new sets" button can say what the extra walk actually bought.

> **This is the one real cost increase in RFC 0011.** One full brief-card walk per
> language per run, on every run rather than only on runs that find a new set. It is a
> button and a monthly job, on the same list endpoint the breadth seed already uses.
> Recorded in the RFC's Risks; do not "optimize" it away by restoring the early-out,
> which is the bug.

**Prices stay out of it.** These are identity-only rows via `to_catalog_card_brief`, as
they already are. `refresh_held_prices` owns prices once a card is actually held, and
`refresh_catalog_prices` picks up the rest on the weekly cycle.

### The endpoint

```python
@router.get("/new-cards", response_model=NewCardsResponse)
def new_catalog_cards(
    since_days: int = Query(30, ge=1, le=365),
    limit: int = Query(6, ge=1, le=25),
    repo: InventoryRepository = Depends(get_repo),
) -> NewCardsResponse:
    """Catalog cards first seen inside the window.

    Counts only rows carrying a `first_seen_at`. A null means "predates the field", not
    "new" — every one of the 31,603 rows seeded before RFC 0011 has one, so counting
    nulls would report the entire catalog as new on the first load.

    Served from `catalog_cache`, so this is an in-memory filter rather than a scan.
    """
```

Cards are returned newest-first with image and price, because T10 renders a few of them
and **a card is never identified by name alone**. Price via `_market_price(card,
"normal")` — the one shared finish-aware lookup; never a second copy of that walk.

## RED — write these first, show the failing output, then STOP

In `backend/tests/services/test_catalog_sync.py`:

```python
class TestFirstSeenAt:
    def test_a_new_card_is_stamped(self, repo):
        repo.batch_upsert_catalog_cards([brief_card("en:base1-4")], preserve_priced=True)
        assert repo.get_catalog_card("en:base1-4").first_seen_at is not None

    def test_an_existing_card_is_not_re_stamped(self, repo):
        """The whole point. `last_synced_at` already answers "when did we last touch
        this"; this field must answer "when did it first appear"."""
        repo.batch_upsert_catalog_cards([brief_card("en:base1-4")], preserve_priced=True)
        original = repo.get_catalog_card("en:base1-4").first_seen_at

        repo.batch_upsert_catalog_cards([brief_card("en:base1-4")], preserve_priced=True)

        assert repo.get_catalog_card("en:base1-4").first_seen_at == original

    def test_a_full_reseed_does_not_reset_it(self, repo):
        """A reseed whole-item put_items every row. If first_seen_at rode in the body,
        it would come to mean "when we last rebuilt the catalog"."""
        repo.batch_upsert_catalog_cards([brief_card("en:base1-4")], preserve_priced=True)
        original = repo.get_catalog_card("en:base1-4").first_seen_at

        repo.batch_upsert_catalog_cards([brief_card("en:base1-4")], preserve_priced=False)

        assert repo.get_catalog_card("en:base1-4").first_seen_at == original

    def test_a_pre_existing_row_reads_as_none_not_as_new(self, repo):
        repo.put_raw_catalog_row(without_first_seen("en:base1-4"))
        assert repo.get_catalog_card("en:base1-4").first_seen_at is None


class TestNewCardsInExistingSets:
    def test_a_new_card_in_a_held_set_is_added(self, repo, fake_client):
        """The case driving RFC 0011: a promo finally catalogued into a set we hold.
        `_sync_new_sets` early-outed on missing_set_ids and never saw these."""
        repo.batch_upsert_catalog_cards([brief_card("en:base1-1", set_id="en:base1")],
                                        preserve_priced=True)
        fake_client.set_brief_cards(Language.EN, [
            raw_brief("base1-1", set_id="base1"),
            raw_brief("base1-4", set_id="base1"),     # new
        ])

        summary = sync_new_sets(repo, fake_client)

        assert summary["cards_added_to_existing_sets"] == 1
        assert repo.get_catalog_card("en:base1-4") is not None

    def test_an_unchanged_catalog_adds_nothing(self, repo, fake_client):
        repo.batch_upsert_catalog_cards([brief_card("en:base1-1", set_id="en:base1")],
                                        preserve_priced=True)
        fake_client.set_brief_cards(Language.EN, [raw_brief("base1-1", set_id="base1")])

        summary = sync_new_sets(repo, fake_client)

        assert summary["cards_added_to_existing_sets"] == 0

    def test_an_existing_priced_row_is_never_overwritten(self, repo, fake_client):
        """The guarantee `preserve_priced=True` exists for. Walking every card now
        means the writer sees rows it used to skip entirely."""
        repo.upsert_catalog_card_preserving_prices(priced_card("en:base1-1"))
        fake_client.set_brief_cards(Language.EN, [raw_brief("base1-1", set_id="base1")])

        sync_new_sets(repo, fake_client)

        assert repo.get_catalog_card("en:base1-1").prices != {}
```

In `backend/tests/routers/test_admin_catalog.py`:

```python
def test_new_cards_counts_only_stamped_rows(admin_client, repo):
    """A null first_seen_at means "predates the field", not "new". Counting nulls
    would report all 31,603 rows as new on the very first load."""
    repo.put_raw_catalog_row(without_first_seen("en:old-1"))
    repo.batch_upsert_catalog_cards([brief_card("en:new-1")], preserve_priced=True)

    body = admin_client.get("/admin/catalog/new-cards").json()

    assert body["count"] == 1


def test_new_cards_respects_the_window(admin_client, repo):
    repo.put_raw_catalog_row(stamped("en:ancient-1", days_ago=200))
    repo.batch_upsert_catalog_cards([brief_card("en:new-1")], preserve_priced=True)

    body = admin_client.get("/admin/catalog/new-cards", params={"since_days": 30}).json()

    assert [c["card_id"] for c in body["cards"]] == ["en:new-1"]


def test_each_returned_card_carries_an_image_and_a_price_field(admin_client, repo):
    repo.batch_upsert_catalog_cards([brief_card("en:new-1")], preserve_priced=True)
    card = admin_client.get("/admin/catalog/new-cards").json()["cards"][0]
    assert "images" in card
    assert "market_price" in card
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/test_catalog_sync.py backend/tests/routers/test_admin_catalog.py -q --tb=short
```

## Watch for

- **`repo.list_cards_by_language` may not exist.** Check `services/dynamodb.py` before
  writing the membership set. If it does not, the honest options are a GSI query or
  reusing `catalog_cache`'s resident map — **not** a per-card `get_catalog_card`, which
  is 31,603 reads. Record which you chose in `progress.md`.
- **Do not fetch prices during the sync walk.** Identity rows only, as today.
- **Do not restore the `missing_set_ids` early-out.** It is the bug, and it will look
  like an optimization to the next reader — leave a comment saying so.
- **The set registry write must still run**, and its `card_count` must still be the rows
  **we** hold, never TCGdex's advertised `cardCount.total` (108 of 177 JP sets advertise
  a count while carrying zero rows).
- **`catalog_cache.invalidate()`** already runs in `sync_new_sets`'s `finally`. Leave it.

## Done means

1. both test files pass, output shown;
2. `ruff check backend/src` clean;
3. `progress.md` updated, with a Notes line stating how the language membership set was
   built and confirming the extra walk's cost was accepted deliberately.

Do not run the full suite. Do not merge. Do not push.
