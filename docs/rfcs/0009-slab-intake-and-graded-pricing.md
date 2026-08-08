# RFC 0009 — Slab intake by barcode, and free graded pricing

**Status:** accepted, not started · **Date:** 2026-08-07 · **Owner decisions:** all
locked (see §2) · **Plan:** [`docs/plans/rfc-0009/`](../plans/rfc-0009/README.md)

## 1. What this builds

An `/admin/slabs` tab that turns a stack of graded slabs into priced inventory:

1. **Scan** a slab's barcode (keyboard-wedge scanner, or the device camera).
2. The barcode yields a **PSA cert number**; PSA's API turns that into a verified
   card identity and grade.
3. Scanned slabs **stage** in a batch. You fill in cost, then commit the batch.
4. Committing writes real `graded` inventory items **and** purchase transactions.
5. A free pricing provider supplies **per-grade market values**, refreshed nightly.

## 2. Owner decisions locked in during planning (2026-08-07)

| Decision | Detail |
|---|---|
| Cert entry | **Three co-equal input methods**: keyboard-wedge scanner (primary), **typing the cert number by hand** (always available), device camera (convenience). All feed one pipeline |
| What a scan creates | A **staged intake batch**, not one-item-at-a-time and not a bare inventory write |
| Batch commit path | Through the **existing buy session**, so slabs land in purchase history and show analytics like any other acquisition |
| Tab scope | **Intake + slab list + pricing controls**, one home for slab work |
| Price refresh | **Nightly**, joining `daily_sync.py`, snapshotting into price history |
| Pricing vendor | **Not PriceCharting** — owner declined a paid subscription for an estimate. PokemonPriceTracker's free tier instead |

## 3. What already exists (do not rebuild)

This is the single most important section for anyone starting a task.

| Piece | Where | State |
|---|---|---|
| `GradedInventoryItem` — `company`, `grade`, `cert_number`, optional `card_id` | `models/inventory.py:283-291` | ✅ complete |
| `GradingCompany` enum (PSA/BGS/CGC/SGC) | `models/inventory.py:107-113` | ✅ complete |
| `ItemCategory.GRADED` | `models/business.py:30` | ✅ complete |
| **Slab price storage** — `CARD#<id>` / `GRADEDPRICE#<company>#<grade>` rows | `services/dynamodb.py:971-991` | ✅ complete, currently hand-fed |
| `get_graded_market_value()` / `put_graded_market_value()` | `services/dynamodb.py` | ✅ complete |
| Nightly graded history snapshot | `services/catalog_sync.py:58-85` | ✅ complete, `source="manual"` |
| `refresh_inventory_market_values` handles graded | `services/catalog_sync.py:88-111` | ✅ complete |
| Customer surface includes graded, and correctly **skips** the condition multiplier | `routers/inventory.py:51, 393` | ✅ correct — slabs have no `condition` |
| Distributed per-day counters (DynamoDB, restart-safe) | `rate_limit.py:175-278` | ✅ reusable for outbound quota |
| Buy session: create → add items → confirm → items + transactions + timeline | `routers/admin/purchases.py` | ⚠️ see §4 |

**The pricing schema needs no change.** A `graded_price` row is already keyed by
`(card_id, company, grade)` — exactly the granularity a per-grade provider returns.
The work is filling those rows from an API instead of by hand.

## 4. The one real blocker

`confirm_buy_session` (`routers/admin/purchases.py:213-294`) **hardcodes
`"kind": "raw"`** at line 243 and `ItemCategory.RAW` at line 270. The buy flow
physically cannot produce a graded item today.

Extending it — rather than writing a parallel slab-intake router — is what earns
slabs correct purchase transactions, timeline events, show attribution, cost
basis and analytics with no duplicated logic.

## 5. External providers

Both sit behind a Protocol in `services/slab/`, with a fake in tests. **No test
touches the network.** A missing key or a dead provider degrades to manual entry;
it never 500s.

### 5.1 PSA — identity only

- **Endpoint:** `GET https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}`
- **Auth:** `Authorization: Bearer <token>`; token does not expire
- **Free quota:** **100 calls/day.** Over it → HTTP 429
- **No rate-limit headers are returned** — we must count our own calls
- **Returns:** subject, year, brand, set/variety, card number, grade, auto grade,
  label type, attributes, image URL
- **`TotalPopulation` and `PopulationHigher` are ALWAYS `null`** on the public API

**Consequences, both binding:**

1. **There is no population field in this design.** CLAUDE.md's "Third-Party APIs
   (Planned)" section promises population from this API. That promise is wrong and
   is corrected as part of T8.
2. **A cert's identity is immutable**, and population — the only mutable field —
   is unavailable anyway. So PSA is called **once per slab, ever**, and cached on
   the item. **The nightly sync makes zero PSA calls.** The 100/day quota binds
   only on same-day intake volume.

### 5.2 PokemonPriceTracker — pricing

- **Free tier:** 100 credits/day, 60 requests/min, 1 credit per card
- **Returns:** PSA 8 / 9 / 10 values derived from **eBay completed (sold)** listings
  — the same sold-comps basis PriceCharting uses
- Population endpoint is Business-tier ($99/mo) — **not used**
- Escape hatch if outgrown: $9.99/mo for 20,000 credits/day

**Quota strategy:** 1 credit per slab per refresh. Under 100 slabs, a full nightly
refresh fits the free tier. Above that, refresh the **100 stalest** each night, so
every slab refreshes within `ceil(N/100)` days and the UI shows the value's **age**
rather than implying it is current.

### 5.3 Unverified — T0 must confirm before any mapper is written

Neither provider's exact response shape has been observed from this codebase. T0 is
a spike whose only job is to record real responses as fixtures and answer:

- Exact JSON field names and nesting for both providers.
- **Coverage of the actual shelf**, especially **Japanese slabs.** eBay-sold-derived
  pricing for JP graded cards may be thin, and this inventory has a real JP
  component. If coverage is bad, we re-decide the vendor before building on it.
- How a provider card maps to our TCGdex `card_id`.

## 6. Data model changes

All additive and optional, so existing rows validate unchanged and there is no
migration.

On `GradedInventoryItem`:

| Field | Type | Purpose |
|---|---|---|
| `grade_label` | `str \| None` | PSA's own words, e.g. `"GEM MT 10"` |
| `cert_verified_at` | `datetime \| None` | when PSA confirmed this cert; `None` = never verified |
| `cert_image_url` | `str \| None` | PSA's label/card image |
| `price_source_id` | `str \| None` | the pricing provider's product id, resolved once and reused. Deliberately vendor-neutral in name |

**No `population` field.** See §5.1.

Plus a **cert pointer row** — `PK=CERT#<company>#<cert_number>`, `SK=POINTER`,
holding `item_id` — written whenever a graded item is saved. This makes "do I
already own this slab?" an O(1) `get_item`, not a table scan. The catalog-scan
lesson in CLAUDE.md's Ops section applies: never put a scan on a request path.

## 7. Endpoints

New router `routers/admin/slabs.py`:

| Method | Route | Notes |
|---|---|---|
| `GET` | `/admin/slabs/lookup/{cert}` | PSA lookup + catalog match + price. **Read-only — writes nothing.** Returns a staged draft |
| `GET` | `/admin/slabs/certs/{cert}` | Duplicate check against the pointer row |
| `GET` | `/admin/slabs` | Slab list with filters (company, grade, priced/unpriced, status) |
| `POST` | `/admin/slabs/refresh-prices` | Background refresh, mirroring the `/admin/market/sync` pattern |
| `GET` | `/admin/slabs/quota` | Remaining daily calls per provider, so the UI can warn before it fails |

Extended: `BuySessionItem` gains `kind` and slab fields; `confirm_buy_session`
branches on `kind`.

## 8. Frontend

`/admin/slabs`, inserted into `navItems` (`components/admin/AdminShell.tsx:29-45`)
**after Buy** — it is an acquisition flow.

- **Scan bar** — an always-refocusing input serving all three entry methods: it
  recognizes keyboard-wedge bursts (rapid keystrokes terminated by Enter), accepts a
  **hand-typed cert number** submitted by Enter or an explicit **Add** button, and
  offers a "Use camera" button. Submission is **never gated on typing speed** —
  timing may only decide whether to auto-submit, never whether an entry is allowed.
  Hand entry stays available in every degraded state, which is what keeps intake
  working when PSA is down, the quota is spent, or a barcode is unreadable.
- **Staging table** — one row per scan: resolved identity, grade, suggested value,
  editable cost, inline duplicate/failure flags. Unresolved rows stay hand-editable.
  Commit creates + confirms a buy session in one action.
- **Slab list** — cert, company, grade, card art via `TABLE_THUMB_SIZE`, value,
  value age, cost, status.

Card art must use the exported `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN` and
`useCardImages` — CLAUDE.md records what hand-picking a size per page cost last time.

## 9. Failure paths

| Case | Behavior |
|---|---|
| PSA key missing / API down / 429 | Manual entry; item flagged `needs_review`, machine reason `cert_lookup_failed` |
| CGC / BGS / SGC slab | Manual entry, by existing design decision — too rare to justify a per-vendor pipeline |
| Cert verified, no catalog match | `card_id=None` → lands in Triage as `missing_card_id`. Free; no new code |
| No pricing coverage | Manual value, honestly badged, excluded from coverage stats |
| Duplicate cert scanned | Hard warning, override allowed — you can legitimately re-buy a slab you sold |

`cert_lookup_failed` joins `MACHINE_REVIEW_REASONS` (`models/inventory.py:169-174`)
so the existing re-flag guard applies: automation must not re-flag a slab an admin
has already passed.

## 10. Security and secrets

- `PSA_API_KEY` and `POKEMONPRICETRACKER_API_KEY` live in `backend/.env`
  (gitignored) and as ECS secrets in production. **Blank placeholders only** in
  `.env.example`.
- Both keys were pasted into a chat transcript during planning and **should be
  rotated** once the integration is confirmed working.
- Both are bearer tokens spending a metered quota — treat as credentials, never log
  them, never return them from an endpoint (including `/admin/slabs/quota`).
- Provider responses are untrusted input. `cert_image_url` is rendered in the admin
  UI, so it needs the same scheme validation the `tcg_url` finding called for
  (follow-ups: a `javascript:` URI must not be accepted).

## 11. Explicitly out of scope

- PSA population data — unavailable via the API (§5.1).
- Automated cert lookup for CGC/BGS/SGC (§9).
- Grade-multiplier price estimation from raw catalog prices. Rejected: slab premiums
  vary too much by card, and this codebase already learned what a plausible-looking
  wrong multiplier costs (the condition-pricing correction in CLAUDE.md).
- Customer-facing changes. Graded items already appear in `/inventory`; nothing here
  alters that surface.
