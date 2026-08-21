# T9 — Catalog search: DIAGNOSED. 11.2s per request.

**RFC:** 0008 §E (issues #6, #14) · **Layer:** full-stack · **Depends on:** nothing (diagnostic is done)

## Diagnosis — measured 2026-08-05 against the live `merlins-cards` table

The RFC left this as an open question. It is now answered with real numbers.
**Do not re-run the investigation.**

### What is NOT wrong (all ruled out by measurement)

| Theory | Verdict |
|---|---|
| Catalog table empty | **No** — 31,603 `catalog_card` rows present |
| Rows mis-tagged / stale `entity` | **No** — all 31,603 tagged `catalog_card` correctly |
| A bad row crashes `CatalogCard.model_validate` | **No** — 31,603/31,603 validate, zero failures |
| Name matching / casing bug | **No** — `Pikachu` → 204 hits, `charizard` → 125, case-insensitive works |
| Frontend hitting the wrong path (404) | **No** — `admin-api.ts:45` prefixes `/admin`, so `/market/search` → `/admin/market/search`, correct |
| Pydantic validation is the bottleneck | **No** — 0.15s of the 11.4s |

### What IS wrong

```
pages=12  rows=31603
  DynamoDB scan (network+IO):  11.21s   <-- THIS
  Pydantic validation:          0.15s
  TOTAL:                       11.36s   per /market/search request
```

`market_search()` with no `set_id` calls `_scan_catalog()` → `list_all_catalog_cards()`
→ `iter_catalog_cards()`, which pulls **the entire 11.7 MB table across 12
sequential 1 MB scan pages, on every single request**, then filters by name in
Python. There is no index, no cache, and no pagination cutoff.

Two things turn "slow" into "appears completely broken":

1. **Overlapping out-of-order responses.** `searchCatalog` (`admin/buy/page.tsx:78-95`)
   debounces at 300ms with **no abort and no stale-response guard**. Typing
   "Pikachu" fires several 11-second requests; whichever resolves last wins, which
   is often the response for `"Pik"` — or the UI just sits empty long enough that
   the owner concludes it found nothing.
2. **Every failure renders as "no results."** The bare `catch { setCatalogResults([]) }`
   makes a timeout, a 500, and a genuine zero-match visually identical. Same bug on
   the Trade page. This is why the problem was un-diagnosable from the UI.

Measured from a workstation; from ECS in-region the scan will be faster (fewer
network round-trips) but it is still 12 sequential 1 MB reads per keystroke-batch,
and the ordering bug is latency-independent.

## Fix — two parts. Part 1 is not optional and is not blocked on Part 2.

### Part 1 — make failures visible and responses ordered (do this first)

Applies to **both** `admin/buy/page.tsx` and `admin/trade/page.tsx`:

- Replace the bare `catch` with real state: distinguish `idle` / `searching` /
  `error` / `empty` / `results`. Render an actual error message with a retry
  affordance on `error`. Never let a thrown request render as "no matches".
- Add a stale-response guard: keep a request sequence number (or an
  `AbortController` that the next keystroke aborts) and drop any response that is
  not for the current query.
- Add server-side timing to `market_search` — log elapsed ms and result count, so
  this is observable next time instead of requiring a workstation investigation.

### Part 2 — stop scanning the whole table (owner decision needed, see below)

**Recommended: an in-process catalog cache.** The catalog only changes when a sync
runs. Cache the parsed rows in the API process with a TTL, and invalidate at the
end of `sync_new_sets` / the catalog seed.

- 11.7 MB in memory is trivial for the container.
- Deployment is explicitly single-worker (see the `_SYNC_STATUS` module-level dict
  comment at the top of `admin/market.py`), so a process-local cache is coherent.
- **Substring search keeps working exactly as it does today** — this is the decisive
  advantage.
- First request after boot/sync pays ~11s; every one after is ~50ms. Warm it on
  startup and after a sync to remove even that.
- Cheap to build, no schema change, no backfill, no GSI.

**Alternative: a name GSI.** `GSI2` is currently unused by catalog rows (only
transactions write `GSI2PK = SHOW#…`), so catalog cards could write
`GSI2PK = "CATNAME#<lang>"` / `GSI2SK = "<lowercased name>#<card_id>"` and query
with `begins_with`. Millisecond queries and it scales past a cache.
**But DynamoDB cannot substring-match** — `"pika"` would find `Pikachu` and never
`Surfing Pikachu`. That is a real functional downgrade from today's behaviour, and
it needs a full catalog re-write to backfill.

**Not recommended: OpenSearch.** New infrastructure and cost for 31k rows that fit
in 11.7 MB of RAM. Revisit at 10x scale.

> **Ask the owner to pick before building Part 2.** Recommendation: cache. Ship
> Part 1 regardless — it is correct under every option.

## RED — write these first, confirm they fail, then stop

Backend (`backend/tests`):
1. `market_search` with `name=` returns matching cards from a seeded fake repo
   (passes today — pin current behaviour before optimising).
2. Two consecutive `market_search` calls hit the underlying scan **once**, not
   twice (cache option). Fails today.
3. Cache invalidates after a catalog sync completes — a card added post-sync is
   findable without a restart. Fails today. **This is the test that stops the cache
   from becoming a correctness bug.**
4. `set_id`-scoped search still uses the GSI path and does **not** populate/consult
   the full-catalog cache.

Frontend (`frontend`, vitest):
5. Buy page shows a distinct **error** state when `/market/search` rejects — asserts
   it does *not* say "no matches". Fails today.
6. Buy page ignores a resolved response whose query is no longer current
   (type "Pik", then "Pikachu"; resolve "Pik" last; results must be Pikachu's).
   Fails today.
7. Same two for the Trade page.

## Verify (narrow)

```bash
python -m pytest backend/tests -q --tb=short -k "market or catalog"
cd frontend && npx vitest run buy trade
ruff check backend/src
```

## Done when

- Buy and Trade visibly distinguish error from empty, and never show a stale result.
- A repeat search does not re-scan (if cache chosen).
- Owner has confirmed catalog search works on all four surfaces: **Buy, Trade,
  Watchlist add, Catalog view**. The RFC is explicit that a regression here is a
  four-surface outage — do not sign off on the Buy page alone.
