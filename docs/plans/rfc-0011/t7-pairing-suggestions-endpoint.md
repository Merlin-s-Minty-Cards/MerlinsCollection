# T7 — Ranked pairing suggestions

**RFC:** 0011 §E · **Layer:** backend · **Depends on:** T5 · **Blocks:** T8, T10
**Owner ask:** *"Maybe you can think of some way to suggest cards to pair."*
**Owner constraint, 2026-08-13:** *"you must also have the option for the user to search
the whole catalog if none of those candidates match."* — that half is T8's; this task
must not make suggestions the only door.

## Reuse the matcher; relax only its verdict

`spreadsheet_import._match_card` (line 300-361) already normalizes names and numbers on
both sides and indexes by `(name, number, language)`. It answers **"is there exactly one
safe answer?"** and returns `None` for everything ambiguous — correct for an importer
writing `card_id` unattended, wrong for a human picking from a list.

This task builds a sibling that returns **the candidates with a score**, over the same
index. Do not fork the normalizers; import them.

## Files

- **Create:** `backend/src/merlins_collection/services/pairing.py`
- **Create:** `backend/src/merlins_collection/routers/admin/unmatched.py`
- **Modify:** `backend/src/merlins_collection/routers/admin/__init__.py` — register the
  router
- **Test:** `backend/tests/services/test_pairing.py`,
  `backend/tests/routers/test_admin_unmatched.py`

## Interfaces

**Produces** (T8 renders these fields; T10 reads `items_with_candidates`):

```python
class Candidate(BaseModel):
    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str        # "" when TCGdex carries no art — an absent image is a fact
    market_price: Decimal | None
    score: float            # 0.0-1.0
    why: str                # "name and number match", "name matches, number differs"

class ItemSuggestions(BaseModel):
    item_id: str
    candidates: list[Candidate]

class SuggestionsResponse(BaseModel):
    items: list[ItemSuggestions]
    items_with_candidates: int
```

```
GET /admin/unmatched/suggestions?limit=3   -> SuggestionsResponse
```

## Design

### Why this is affordable on list load

The whole catalog is already resident in `services/catalog_cache` (~93 MB, RFC 0008 T9),
and the parked cohort is **tens** of rows, not thousands. So this is an in-memory join,
not 31,603 reads per item. Build the normalized index **once per request** and reuse it
across every parked item — building it per item is the one way to make this slow.

> **Never call the pricing provider here.** A suggestion is a catalog lookup. The graded
> price provider is metered at fifty lookups a day (CLAUDE.md, Third-Party APIs), and a
> page load that spends quota is how a budget disappears without anyone deciding to
> spend it.

### Scoring

Three tiers, and the `why` string exists so the admin can see which tier they are looking
at rather than trusting a bare number:

| score | condition | `why` |
|---|---|---|
| `1.0` | normalized name **and** number match, and the language matches | `"name and number match"` |
| `0.7` | normalized name matches, number differs | `"name matches, number differs"` |
| `0.5` | core name matches (a variant word was dropped), number matches | `"close name, number matches"` |

Below `0.5`, return nothing. **A long list of bad guesses is worse than an empty one** —
it invites the exact "close enough" pairing this whole RFC exists to stop, and the owner
already described that failure: *"cards that are close to the right card but are actually
a promo so the price is completely wrong."*

```python
#: Never suggest below this. A weak candidate presented beside a strong one reads as an
#: option, and the promo-priced mispairing this feature exists to prevent is exactly what
#: happens when a human picks the plausible-looking wrong card off a ranked list.
MIN_SCORE = 0.5
```

### Language is part of the key, never a post-filter

`_match_card`'s docstring says why (line 304-312): a Japanese Seismitoad #38 must resolve
to the Japanese printing, which trades at a different price. Scope by key.

**A JP item can still legitimately have zero candidates** — TCGdex's Japanese coverage is
thin, and that is precisely why the card is parked. Zero is an honest answer here.

### The identity to match against

A parked item has no `card_id`, so the query comes from the item's own fields:

```python
def _identity(item) -> tuple[str, str]:
    """(name, number) to search on, from the item's OWN fields.

    `admin_item_name` first — `display_name_override` is an admin's typed English name
    and is the single best signal we have on a JP card whose stored name is in script
    the matcher cannot normalize. One rule everywhere (CLAUDE.md, name resolution).
    """
    name = admin_item_name(item) or ""
    number = getattr(item, "card_number", None) or _number_from_name(name) or ""
    return name, number
```

### Prices on candidates

**`_market_price(card, "normal")`** — the ONE shared finish-aware lookup
(`models/inventory.py:388`). Do not re-implement price selection; CLAUDE.md records that a
second copy of that fallback walk is how 174 of 213 live items once went unpriced.

**A catalog price is a NEAR MINT figure and is NOT condition-adjusted** — there is no item
condition involved in a catalog row. Do not scale it, and T8 must not present it as a sale
price. **An absent price is `None`, never `0`** — `FinishPrice` bands are written only
when a provider published a figure.

### The endpoint

```python
@router.get("/suggestions", response_model=SuggestionsResponse)
def unmatched_suggestions(
    limit: int = Query(3, ge=1, le=10),
    repo: InventoryRepository = Depends(get_repo),
) -> SuggestionsResponse:
    """Ranked catalog candidates for every parked item.

    Scoped to the parked cohort (`no_catalog_match=True`), which is tens of rows. The
    catalog comes from `catalog_cache`, so this is an in-memory join and the index is
    built ONCE per request rather than once per item.

    `items_with_candidates` is the number the dashboard widget quotes (T10). It is
    computed here, from the same pass, so the widget and the queue page can never
    disagree about how much work is waiting.
    """
```

## RED — write these first, show the failing output, then STOP

`backend/tests/services/test_pairing.py`:

```python
class TestScoring:
    def test_exact_name_and_number_scores_highest(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    set_name="Base Set")
        item = raw_item(display_name="Charizard", card_number="4", card_id=None)

        [best] = candidates_for(item, catalog.index)

        assert best.card_id == "en:base1-4"
        assert best.score == 1.0
        assert best.why == "name and number match"

    def test_name_match_with_a_different_number_ranks_lower(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        item = raw_item(display_name="Charizard", card_number="99", card_id=None)

        [only] = candidates_for(item, catalog.index)

        assert only.score == 0.7
        assert only.why == "name matches, number differs"

    def test_a_weak_match_is_not_offered_at_all(self, catalog):
        """A long list of bad guesses invites the exact promo-mispairing this
        feature exists to stop."""
        catalog.add(card_id="en:base1-58", name="Pikachu", number="58")
        item = raw_item(display_name="Blastoise", card_number="2", card_id=None)

        assert candidates_for(item, catalog.index) == []

    def test_ranked_best_first(self, catalog):
        catalog.add(card_id="en:base1-4", name="Charizard", number="4")
        catalog.add(card_id="en:base2-4", name="Charizard", number="88")
        item = raw_item(display_name="Charizard", card_number="4", card_id=None)

        result = candidates_for(item, catalog.index)

        assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)


class TestLanguage:
    def test_a_jp_item_never_matches_an_english_printing(self, catalog):
        """A JP card trades at a different price. Language is part of the KEY."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    language=Language.EN)
        item = raw_item(display_name="Charizard", card_number="4",
                        language=Language.JA, card_id=None)

        assert [c.card_id for c in candidates_for(item, catalog.index)] == []

    def test_zero_candidates_is_an_honest_answer(self, catalog):
        assert candidates_for(raw_item(display_name="Nothing", card_id=None),
                              catalog.index) == []


class TestPrices:
    def test_an_absent_price_is_none_not_zero(self, catalog):
        """FinishPrice bands are written only when a provider published a figure."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4", prices={})
        item = raw_item(display_name="Charizard", card_number="4", card_id=None)

        assert candidates_for(item, catalog.index)[0].market_price is None

    def test_the_price_is_not_condition_adjusted(self, catalog):
        """A catalog price is a NEAR MINT market figure. There is no item condition
        in a catalog row, so scaling it would be inventing a number."""
        catalog.add(card_id="en:base1-4", name="Charizard", number="4",
                    prices={"normal": {"market": Decimal("100")}})
        item = raw_item(display_name="Charizard", card_number="4", card_id=None,
                        condition=Condition.DMG)

        assert candidates_for(item, catalog.index)[0].market_price == Decimal("100")
```

`backend/tests/routers/test_admin_unmatched.py`:

```python
def test_only_parked_items_are_considered(admin_client, repo):
    """The endpoint answers for the queue, not for every unlinked row in inventory."""
    repo.put_inventory_item(raw_item(item_id="parked", card_id=None,
                                     no_catalog_match=True))
    repo.put_inventory_item(raw_item(item_id="merely_unlinked", card_id=None))

    body = admin_client.get("/admin/unmatched/suggestions").json()

    assert [i["item_id"] for i in body["items"]] == ["parked"]


def test_items_with_candidates_counts_rows_not_candidates(admin_client, repo, catalog):
    """The dashboard quotes this number. It must mean "cards you can act on",
    not "suggestions in total"."""
    catalog.add(card_id="en:base1-4", name="Charizard", number="4")
    catalog.add(card_id="en:base2-4", name="Charizard", number="88")
    repo.put_inventory_item(raw_item(item_id="x", display_name="Charizard",
                                     card_number="4", card_id=None,
                                     no_catalog_match=True))

    body = admin_client.get("/admin/unmatched/suggestions").json()

    assert body["items_with_candidates"] == 1


def test_limit_bounds_the_candidates_per_item(admin_client, repo, catalog):
    for n in range(6):
        catalog.add(card_id=f"en:base{n}-4", name="Charizard", number="4")
    repo.put_inventory_item(raw_item(item_id="x", display_name="Charizard",
                                     card_number="4", card_id=None,
                                     no_catalog_match=True))

    body = admin_client.get("/admin/unmatched/suggestions",
                            params={"limit": 2}).json()

    assert len(body["items"][0]["candidates"]) == 2


def test_every_candidate_carries_an_image_field_and_a_price_field(admin_client, repo, catalog):
    """Owner rule, absolute: a card picker shows name, image AND price. The fields
    must be present even when empty, or T8 cannot render the placeholder."""
    catalog.add(card_id="en:base1-4", name="Charizard", number="4")
    repo.put_inventory_item(raw_item(item_id="x", display_name="Charizard",
                                     card_number="4", card_id=None,
                                     no_catalog_match=True))

    candidate = admin_client.get("/admin/unmatched/suggestions").json()["items"][0]["candidates"][0]

    assert "image_small" in candidate
    assert "market_price" in candidate
```

**Run, show the owner the failures, and WAIT.**

```bash
./.venv/Scripts/python.exe -m pytest backend/tests/services/test_pairing.py backend/tests/routers/test_admin_unmatched.py -q --tb=short
```

## Watch for

- **Build the index once per request.** Per-item index construction over 31,603 rows is
  the difference between a fast page and a timeout.
- **Do not lower `MIN_SCORE` to "give the admin more to look at".** That is the promo
  mispairing, re-introduced.
- **Do not call the pricing provider.** Fifty lookups a day, and a page load must not
  spend them.
- **`ge=1, le=10` on `limit`.** An unbounded limit turns one request into a full
  cross-product.

## Done means

1. both test files pass, output shown;
2. `ruff check backend/src` clean;
3. `progress.md` updated, with a Notes line giving T8 and T10 the exact response field
   names.

Do not run the full suite. Do not merge. Do not push.
