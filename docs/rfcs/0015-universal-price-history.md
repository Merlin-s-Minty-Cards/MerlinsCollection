# RFC 0015: Universal, Durable Catalog Price History

**Status:** Draft
**Author:** Claude (with merlinsmintycardsllc@gmail.com)
**Date:** 2026-08-18

## Summary

Price-history recording already exists as infrastructure — a `PricePoint` model, a
DynamoDB write/read path keyed on `card_id`, an MCP tool, and an admin price
chart — and RFC 0010 T17 already extended it to the entire catalog, not just
owned stock. What doesn't yet hold is the *durability* and *correctness* of
that recording: a catalog reseed silently deletes it, nothing bounds its
growth, and one read path resolves the wrong finish and renders an empty
chart for cards that do have data. This RFC closes those three gaps and adds
no new recording mechanism, because none is needed.

## Motivation

The owner's report — "none of the catalog/inventory cards have a price
history" — reads as a missing feature, but the recording pipeline
(`services/catalog_sync.py`'s `refresh_held_prices` and `refresh_catalog_prices`,
both funneling through `_refresh_one_card` → `repo.append_price_points`) has
been live since RFC 0010 T17 (2026-08-10) and confirmed actually scheduled and
firing in production 2026-08-12 through 2026-08-15 (`docs/aws-setup.md`
Phase 8). Investigation for this RFC found three concrete reasons the trail
still looks empty or unreliable:

1. **Reseed data loss.** `services/dynamodb.py`'s `purge_card_data` — the swap
   half of a catalog reseed — treats `price_point` as a
   catalog-generation-scoped entity (`_CATALOG_GEN_ENTITIES`) and deletes any
   row not stamped with the incoming generation, identically to how it treats
   `catalog_card` rows. A `catalog_card` row not in the new generation really
   is an orphan (its card no longer exists in the freshly loaded catalog), but
   a `price_point` row is a historical fact about a `card_id` that is almost
   always still valid after a reseed — TCGdex ids are stable across reseeds.
   Every full reseed (a rare, owner-run action; one landed around 2026-08-06)
   has been discarding whatever history had accumulated up to that point.

2. **Unbounded growth.** No retention policy exists. `price_point` and
   `item_price_point` rows accumulate forever — roughly 31,600 catalog cards ×
   up to ~365 raw points/year once the weekly cycle is in steady state, plus
   the graded and sealed item-level series. The owner does not need more than
   two years of trail.

3. **A finish-mismatch bug in the read path.** `admin_item_price_chart`
   (`routers/admin/inventory.py:754-816`) is the endpoint behind the
   `/admin/card/[id]` price chart. Its raw-item branch queries history with
   `item.finish` as an **exact** match against the stored `PricePoint.finish`
   key. This is the identical failure class already documented and fixed
   elsewhere in this codebase: `models/inventory.py`'s `_market_price`
   docstring records that an exact-match walk "left 174 of 213 live items
   unpriced" until every other caller adopted the shared fallback-aware
   `market_price_and_finish` helper. The price-chart endpoint was never
   migrated to it, so an inventory item whose stored `finish` doesn't
   byte-for-byte match the finish TCGdex actually priced the card under (a
   routine mismatch — see that docstring) renders an empty chart even though
   its card's history is sitting right there under a different finish key.

None of this requires a new recording mechanism, a new schema, or a change to
the weekly cycle's cadence — the owner confirmed "once every 5.7 nights" (the
cycle's actual per-card interval, `31,300 unheld cards ÷ 5,500/night`) already
matches "once a week." This RFC is three narrow, independent fixes to the
system that already exists.

**Architectural point carried through the whole design:** `PricePoint` rows
are keyed on `PK = CARD#<card_id>`, never on an inventory item id. An
inventory item resolves its own `card_id` (+ `finish` for raw, or
`company`+`grade` for graded) and reads the catalog card's history series —
it never owns a private copy. So "a card already has history by the time it
enters inventory" is not new behavior to build; it falls out of the existing
key design once the three gaps above are closed. This RFC does not touch that
relationship — it only makes sure the underlying history is actually there,
survives, and is read correctly.

## Detailed Design

### 1. Reseed preservation

`services/dynamodb.py` currently defines:

```python
_CARD_DATA_ENTITIES = frozenset({
    "catalog_card", "price_point", "inventory_item", "transaction",
})
_CATALOG_GEN_ENTITIES = frozenset({"catalog_card", "price_point"})
```

`purge_card_data`'s scan (`dynamodb.py:685-704`) skips any row whose `entity`
is not in `_CARD_DATA_ENTITIES` at all, and additionally protects rows in
`_CATALOG_GEN_ENTITIES` only when they carry the incoming generation. The
existing docstring already carves out this exact exemption for
hand-curated data: *"neither are hand-curated `graded_price` /
`item_price_point` rows"* — those two entities are never candidates because
they are simply absent from `_CARD_DATA_ENTITIES`. `price_point` gets the same
treatment, for the same reason (it is data the reseed does not own and cannot
correctly regenerate):

```python
_CARD_DATA_ENTITIES = frozenset({
    "catalog_card", "inventory_item", "transaction",
})
_CATALOG_GEN_ENTITIES = frozenset({"catalog_card"})
```

`price_point` rows are simply never scanned as sweep candidates. No change to
how they are written (`_price_point_item` keeps stamping `**self._cat_gen()`
on every row — harmless metadata, just no longer load-bearing for survival)
and no change to `append_price_points`.

**Consequence for `purge_card_data`'s return shape:** `counts` (built from
`dict.fromkeys(self._CARD_DATA_ENTITIES, 0)`) no longer carries a
`price_point` key. Every existing caller (the wipe script's dry-run report,
`test_catalog_wipe.py`) is updated to match — this is a visible, deliberate
change to the reported shape, not an oversight.

### 2. Retention — a 2-year TTL, DynamoDB-native

`config.py` gains one tunable, following the existing style
(`catalog_price_stale_days`, `catalog_refresh_cards_per_night`):

```python
# How long a price-history point (card-level or item-level) is kept before
# DynamoDB's native TTL reaps it. The owner does not need more than two years
# of trend. RFC 0015.
price_history_retention_days: int = 730
```

Both price-history write paths stamp a `ttl` attribute (epoch seconds, the
attribute name DynamoDB's TTL feature will be configured against) at write
time:

- `_price_point_item` (`dynamodb.py:1791-1802`) — `ttl = int(datetime.combine(p.date, datetime.min.time(), tzinfo=timezone.utc).timestamp()) + retention_days * 86400`.
  Note `dynamodb.py` already does `import time` (the module) at the top, so the
  implementation must build this from `datetime.min.time()` rather than a bare
  `time.min` — the module and the stdlib `datetime.time` class would otherwise
  collide under the same name.
- `append_item_price_point` (`dynamodb.py:1775-1781`) — same computation from
  its `day` parameter.

`ttl` is a **storage-only** attribute, added in these two item-building
functions exactly the way `PK`/`SK`/`entity`/`cat_gen` already are — it is
never added to the `PricePoint` Pydantic model, and `PricePoint.model_validate`
on read simply ignores the extra key (Pydantic's default behavior for an
unrecognized field is to drop it, matching how `entity`/`PK`/`SK` are already
handled on every other read path in this file).

**Infra, one-time:**

```bash
aws dynamodb update-time-to-live \
  --table-name merlins-cards \
  --time-to-live-specification "Enabled=true,AttributeName=ttl"
```

The ECS task role needs `dynamodb:UpdateTimeToLive` on `table/merlins-cards`
only for this one-time call (mirrors the existing `merlins-rate-limits`
provisioning pattern in `docs/aws-setup.md` Phase 2b, which already documents
granting this action temporarily and dropping it after). DynamoDB then
expires rows automatically in the background, typically within 48 hours of
their `ttl` timestamp passing — no scheduled job, no pruning script, no read
cost.

**Owner decision, 2026-08-18: backfill existing rows now, not deferred.**
`backend/scripts/backfill_price_history_ttl.py` stamps `ttl` onto every
pre-existing `price_point` / `item_price_point` row that doesn't already carry
one, following this repo's established script shape. The heavier
`--confirm-table` rail (`seed_catalog.py`, `wipe_catalog.py`) is for
*destructive* operations; this one only ever adds an attribute, so it takes
the lighter `backfill_catalog_sets.py` rail instead — dry-run by default,
`--execute` to write. Computed identically to the write-path formula above,
from each row's own stored `date` — a row from a few weeks ago still gets a
`ttl` ~2 years out, not "now," so nothing already-written is made to look
artificially fresh or stale by the backfill itself. The scan-and-update logic
lives on the repository as `backfill_price_history_ttl(dry_run)`, mirroring
where `purge_card_data` itself lives — the script is argument parsing and
printing over that one method.

**Must write via a targeted `update_item` (`UpdateExpression="SET ttl = :ttl"`,
keyed only by the scanned `PK`/`SK`), never a scan-then-`put_item` of the full
row.** The backfill is a full-table walk that can take long enough to overlap
the nightly `merlins-price-sync` run or an admin-triggered reprice writing to
the very rows it's touching (adversarial review, chaos lens). A `put_item` of
a row read earlier in the scan would silently revert whatever price fields a
concurrent writer had just updated; `update_item` touching only `ttl` cannot.
The projected scan itself only needs `PK, SK, #d` (`date`), mirroring
`purge_card_data`'s own light-projection pattern.

### 3. Fix the finish-mismatch bug

`admin_item_price_chart`'s raw-item branch
(`routers/admin/inventory.py:779-790`), current:

```python
if card_id and item.kind == "raw":
    finish = getattr(item, "finish", None)
    history = repo.get_price_history(card_id, finish=finish, start=cutoff)
    ...
```

Fixed to resolve the finish the same way every other price-reading caller in
this codebase already does, via the shared fallback-aware helper:

```python
from merlins_collection.models.inventory import market_price_and_finish

if card_id and item.kind == "raw":
    card = repo.get_catalog_card(card_id)
    finish = getattr(item, "finish", None)
    if card is not None:
        _, resolved_finish = market_price_and_finish(card, finish)
        if resolved_finish is not None:
            finish = resolved_finish
    history = repo.get_price_history(card_id, finish=finish, start=cutoff)
    ...
```

If `card` is `None` (the catalog card is missing) or `market_price_and_finish`
can't resolve anything (no finish on the card carries a current price), the
lookup falls back to the item's own stored `finish` unchanged — the exact
current behavior — so this is additive, not a behavior removal.

**Why resolving against `card.prices` is valid for historical data, not just
the current price:** `to_price_points` (`services/tcgdex.py:559-578`) writes
one history point per finish key present in `card.prices` at sync time, and a
given TCGdex card's set of populated finish keys is stable release to release
(a card doesn't gain a "holofoil" printing after launch). The finish that
carries a current price is, in practice, the same finish every historical
point for that card was recorded under.

The graded branch (`routers/admin/inventory.py:791-804`) is unchanged —
`company`/`grade` are exact identifiers by design (there's no equivalent
"maybe it was written under a slightly different label" ambiguity that a
free-text finish key has).

## Data Schemas

No changes to the `PricePoint` or `CatalogCard` Pydantic models
(`models/catalog.py`). The only schema-adjacent change is storage-level: a new
`ttl` (Number, epoch seconds) attribute on `price_point` and
`item_price_point` DynamoDB items, and the removal of `price_point` from the
set of entities `purge_card_data` will ever delete.

| Item | PK | SK | New attribute |
|---|---|---|---|
| `price_point` (raw) | `CARD#<card_id>` | `PRICE#RAW#<finish>#<date>` | `ttl` (epoch s, `date` + 730d) |
| `price_point` (graded) | `CARD#<card_id>` | `PRICE#GRADED#<company>#<grade>#<date>` | `ttl` (epoch s, `date` + 730d) |
| `item_price_point` | `ITEM#<item_id>` | `PRICE#<date>` | `ttl` (epoch s, `date` + 730d) |

Table-level: `merlins-cards` gains a native TTL specification on attribute
`ttl` (one-time `UpdateTimeToLive` call; no change to any GSI).

## API Contracts

No new endpoints and no request/response shape changes. `GET
/admin/inventory/{item_id}/price-chart` (`PriceChartResponse`) keeps its exact
contract — the fix changes which `finish` is used internally to query
history, not anything the client sees except that previously-empty charts now
populate. `GET /admin/market/card/{card_id}/trend` and `GET
/admin/market/card/{card_id}/confidence` (already used by the Market page's
catalog search — the existing "view a card's history whether you own it or
not" surface) are unaffected; they already query without an item-specific
finish filter in the confidence case and pass `finish` through as given in the
trend case (no bug there — that endpoint takes `finish` as an optional client
query param for a catalog card, not a resolved item finish).

## Alternatives Considered

**Reseed preservation:**
- *Stamp `price_point` rows with the new generation at write time instead of
  exempting them from the sweep entirely* — rejected per the existing
  docstring's own reasoning for the identical question about `catalog_card`:
  "the reseed writes only `catalog_card` rows, so such a stamp could only ever
  record a PAST generation and the next wipe would delete them anyway." The
  same argument applies unchanged to `price_point`.
- *Keep sweeping, but re-derive history for the new generation's cards from
  TCGdex* — not possible; TCGdex has no historical-price endpoint, only
  current prices. Deleting would be a genuine, unrecoverable loss.

**Retention:**
- *Application-level pruning job (a script/cron that deletes rows older than
  730 days)* — rejected in favor of native DynamoDB TTL: it's free (no RCU/WCU
  for the expiry itself), needs no schedule of its own, and this repo already
  uses the identical mechanism for `merlins-rate-limits`. A pruning job would
  duplicate infrastructure that already exists for exactly this purpose.
- *No retention at all* — rejected per the owner's explicit answer; unbounded
  growth on a ~31,600-card catalog accumulating a point roughly weekly (raw)
  plus daily for ~300 held cards is real, if inexpensive, growth with no
  natural ceiling.

**Finish-mismatch fix:**
- *Change how `item.finish` is stored/normalized at write time so it always
  matches a TCGdex finish key* — rejected: this is exactly the class of fix
  `_market_price`'s docstring already rejected in favor of a read-side
  fallback walk, for the same reason (the mismatch is inherent to how items
  get their finish value at intake, e.g. condition sheets, manual entry, and
  a write-side normalization would need to be perfect to fully replace a
  fallback, whereas the fallback is already proven correct in every other
  caller).
- *Duplicate the fallback walk locally in the price-chart endpoint instead of
  importing `market_price_and_finish`* — rejected per that function's own
  docstring, which names this exact codebase's history of second copies
  causing the original 174/213 bug.

## Risks & Mitigations

- **Reseed change is a one-line-of-consequence removal from a delete path.**
  Mitigated by the existing `test_catalog_wipe.py` suite, which already
  exercises `purge_card_data` against seeded `price_point` rows — the test is
  updated to assert *survival* instead of deletion, so a regression back
  toward sweeping is caught the same way the original behavior was proven.
- **`wipe_catalog.py` can no longer nuke price history even when that would be
  genuinely wanted** — e.g. correcting a systemic bad-data episode in the
  price series. Deliberate, per the owner's decision, and low-likelihood; if
  it's ever needed, that's a dedicated one-off script against the `PRICE#`
  range, not a reason to bring `price_point` back into `purge_card_data`'s
  scope.
- **Backfill script must write via targeted `update_item`, not scan-then-`put_item`**
  — see Detailed Design §2; a full-item replace risks reverting a concurrent
  nightly-sync write mid-backfill. Called out here because it's the kind of
  detail a from-scratch implementation of "just like the other backfill
  scripts" would miss (the existing backfill scripts in this repo write
  `catalog_card`/config rows that aren't being concurrently mutated by a
  scheduled job the same way price points are).
- **TTL requires a live-account, one-time `UpdateTimeToLive` call** — same
  operational shape as every other one-time infra step in this repo
  (`docs/aws-setup.md`'s IAM/role/schedule setup), owner-run, not automated by
  this RFC's code changes.
- **DynamoDB TTL deletion is not instantaneous** (typically within 48 hours of
  expiry, per AWS's documented behavior) — acceptable here; a few days of
  slack past exactly 730 days is immaterial for a "doesn't need to grow more
  than 2 years" requirement.
- **The finish-resolution fix changes which points populate a chart for some
  items** — this is the intended effect (previously-empty charts start
  showing data), but it means a chart that rendered from `item.finish`
  literally before will now sometimes render a slightly different finish's
  series if `market_price_and_finish` resolves to a fallback. This mirrors
  exactly the accepted tradeoff `refresh_inventory_market_values` already made
  when it adopted the same helper for `current_market_value` — the fallback
  answer is the correct one, and the previous exact-match answer was routinely
  wrong (empty) rather than differently right.

## Open Questions

Both resolved by the owner, 2026-08-18 — recorded rather than deleted, so the
decision and its reasoning stay attached to the RFC:

1. ~~Backfill `ttl` onto existing price-history rows?~~ **Resolved: yes, now.**
   Moved into Detailed Design §2 as core scope
   (`backend/scripts/backfill_price_history_ttl.py`), not deferred.
2. ~~Should the Market page's existing catalog-card price view be surfaced
   anywhere else (Triage, Unmatched, catalog search results outside
   Market)?~~ **Resolved: no, not now.** No frontend change beyond what
   Detailed Design already specifies (which touches no Market-page code at
   all). Revisit later if wanted — nothing in this RFC forecloses it.
