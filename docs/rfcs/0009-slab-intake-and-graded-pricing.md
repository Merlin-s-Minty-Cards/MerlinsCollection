# RFC 0009 — Slab intake by barcode, and free graded pricing

**Status:** accepted; **amended 2026-08-08 to manual-first intake** · **Date:** 2026-08-07
· **Owner decisions:** see §2 · **Plan:** [`docs/plans/rfc-0009/`](../plans/rfc-0009/README.md)

> **AMENDMENT, 2026-08-08.** PSA's cert API returns `403 "Access to this API is
> limited to approved customers"` — the account is not entitled and no code change
> reaches it. **Intake is therefore hand-entered first**, with PSA lookup returning
> later as a pre-fill rather than a prerequisite. §5.1's PSA flow, and the parts of
> §7/§8 that assume a cert lookup, are **on hold**; §5.2 pricing is verified and
> proceeding. See
> [the design spec](../superpowers/specs/2026-08-08-slab-manual-entry-design.md) and
> [findings](../plans/rfc-0009/spike-findings.md). **The corrections to §1/§5.1/§5.2/
> §5.3/§9 have now landed** (re-plan Task 7, 2026-08-08), so those sections are
> current. §7's `/admin/slabs/lookup/{cert}` and §8's scan bar are the parts still
> describing the unbuilt PSA flow — for the intake tab **as built**, read the spec.

## 1. What this builds

An `/admin/slabs` tab that turns a stack of graded slabs into priced inventory:

1. **Enter** a slab's cert number — typed by hand, or read into the same field by a
   keyboard-wedge scanner. There is one input and one code path for both.
2. The operator identifies the card through **catalog autocomplete**, with a
   free-text fallback for anything the catalog does not hold. Company, grade and
   cost are typed.
3. Entered slabs **stage** in a batch, client-side. You then commit the batch.
4. Committing writes real `graded` inventory items **and** purchase transactions.
5. A free pricing provider supplies **per-grade market values**, refreshed nightly.

**Intake is manual-first (amended 2026-08-08).** PSA's cert API is blocked at the
account (§5.1), so nothing in this flow requires a lookup: the operator is the
source of identity, grade and cost, and the tab works with no scanner, no camera
and no PSA. **PSA lookup returns as a pre-fill, not a prerequisite** — when the
account is approved it fills the same form the operator otherwise fills by hand,
and everything downstream is unchanged. Nothing built for the manual path is
discarded when it arrives. The camera is deferred for the same reason: it yields a
cert number, which without PSA resolves to nothing.

This is not only a stopgap. §8 already required hand entry to work in every
degraded state, and CGC/BGS/SGC slabs were always going to be manual by design
(§9). Making manual entry the primary path means the fallback is the path everyone
uses, so it cannot rot.

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

> **MEASURED 2026-08-08 (T0): every authenticated call returns `403 {"Message":
> "Access to this API is limited to approved customers."}`.** The bullets below are
> what PSA documents; the corrections under them are what the wire actually did. No
> successful authenticated PSA call has ever been made from this codebase, so
> everything about the response *shape* remains unobserved — see §5.3.

- **Endpoint:** `GET https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}`
- **Auth:** `Authorization: Bearer <token>`; token does not expire. **Confirmed
  correct** — four header variants were tried, and only the two `Bearer` forms are
  recognized at all (§1.2 of the findings)
- **Free quota:** **100 calls/day.** Over it → HTTP 429. *Documented, not verified:
  the account never got far enough to spend a metered call*
- **No `X-RateLimit-*` headers are returned** — we must count our own calls
- **Returns:** subject, year, brand, set/variety, card number, grade, auto grade,
  label type, attributes, image URL
- **`TotalPopulation` and `PopulationHigher` are ALWAYS `null`** on the public API

**Corrections T0 measured — all three are on the wire, not inferred:**

1. **`403 "Access to this API is limited to approved customers"` is a third failure
   mode, and it is the one actually happening.** It reproduced across two endpoints
   (`GetByCertNumber` and `GetImagesByCertNumber`) and across a key the owner
   re-issued on 2026-08-08, so it is the **account**, not the call. There is no
   code-side fix: the remedy is an approval request to `collectors-apis@collectors.com`,
   the address PSA's own error body supplies. §9 carries the failure-path row.
2. **A 429 does carry `Retry-After`** — observed counting **833 → 797 s**, i.e. a
   ~13-minute rolling window rather than a wait until UTC midnight, despite the body
   saying "per Day". **Observed on an anonymous, keyless request and still
   unverified for an authenticated caller**; T2 must re-measure once the account is
   approved rather than build a calendar-day counter on this.
3. **A 429 does not imply a spent quota.** An *unrecognized* credential (no `Bearer`
   scheme, or `X-API-Key`) falls into the shared **anonymous** bucket and 429s,
   while a *recognized but unentitled* token 403s. The two are distinguishable, and
   the UI must not report "quota exhausted" for what is an entitlement problem.

**Consequences, both binding:**

1. **There is no population field in this design.** CLAUDE.md's "Third-Party APIs
   (Planned)" section promises population from this API. That promise is wrong and
   is corrected as part of T8.
2. **A cert's identity is immutable**, and population — the only mutable field —
   is unavailable anyway. So PSA is called **once per slab, ever**, and cached on
   the item. **The nightly sync makes zero PSA calls.** The 100/day quota binds
   only on same-day intake volume.

### 5.2 PokemonPriceTracker — pricing

- **Free tier:** 100 credits/day, 60 requests/min, **2 credits per card**
- **Returns:** PSA 8 / 9 / 10 values derived from **eBay completed (sold)** listings
  — the same sold-comps basis PriceCharting uses
- Population endpoint is Business-tier ($99/mo) — **not used**
- Escape hatch if outgrown: $9.99/mo for 20,000 credits/day

**Billing, measured 2026-08-08 (T0), and wrong twice over in the original draft:**

1. **`costPerCard` is 2, not 1** — the response says so in its own body
   (`"apiCallsConsumed": {"total": 4, …, "costPerCard": 2}`): 1 for the card, 1 for
   `includeEbay`. Confirmed live, no longer an inference from the docs.
2. **You are billed on `limit`, not on hits.** Cost is `2 × limit`, **always** — the
   first probe used `limit=2`, matched **zero** cards, and was still charged 4
   credits. `limit` is the cost dial, not a free breadth knob: **pin `limit=1`**, and
   understand that a careless `limit=5` cuts the daily budget to 10 slabs.
3. **The response self-reports quota** (`x-ratelimit-daily-limit`,
   `x-ratelimit-daily-remaining`, `x-ratelimit-daily-reset`, `x-api-calls-consumed`),
   so T6 needs no call counter of its own. Unlike PSA, **401 = auth and 429 = quota
   are cleanly separable.**

**Quota strategy:** 2 credits per slab per refresh, so the free tier is **50 slab
lookups a day, not 100**. Under 50 slabs, a full nightly refresh fits the free tier.
Above that, refresh the **50 stalest** each night, so every slab refreshes within
`ceil(N/50)` days and the UI shows the value's **age** rather than implying it is
current. **T7's rotation math must be sized off 50, not 100** — the original figure
would have refreshed half as often as promised.

### 5.3 Unverified — T0 must confirm before any mapper is written

> **T0 ran on 2026-08-08 and returned a SPLIT verdict** ([`spike-findings.md`](../plans/rfc-0009/spike-findings.md)):
> **pricing PROCEED** — 19 cards recorded as fixtures, all 200s with graded data,
> **including 3/3 Japanese**, so coverage is better than feared and T6 is unblocked.
> **PSA STOP** — every question below is still open for PSA and **none of it can be
> guessed**, because the account 403s before any body is returned. T2 is a mapper
> with nothing to map. One further finding binds T6: the vendor's **name search
> returns the wrong card roughly a third of the time**, and a wrong answer is
> indistinguishable from a right one, so a price may be auto-attached **only** on a
> verified `externalCatalogId` join.

Neither provider's exact response shape had been observed from this codebase when
this RFC was written. T0 was a spike whose only job was to record real responses as
fixtures and answer:

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
| **PSA 403 — account not approved** | Manual entry. The message must say the fix is **account approval** (a support email to `collectors-apis@collectors.com`), **not** a retry and **not** waiting for UTC midnight. This is the state the system is in today |
| PSA key missing / API down / 429 | Manual entry. **Flagged `cert_lookup_failed` only where automation actually tried and failed** — see the amendment below |
| CGC / BGS / SGC slab | Manual entry, by existing design decision — too rare to justify a per-vendor pipeline |
| Cert verified, no catalog match | `card_id=None` → lands in Triage as `missing_card_id`. Free; no new code |
| No pricing coverage | Manual value, honestly badged, excluded from coverage stats |
| Duplicate cert scanned | Hard warning, override allowed — you can legitimately re-buy a slab you sold |

`cert_lookup_failed` joins `MACHINE_REVIEW_REASONS` (`models/inventory.py:169-174`)
so the existing re-flag guard applies: automation must not re-flag a slab an admin
has already passed.

> **AMENDED 2026-08-08 — a hand-entered slab is NOT review-flagged.** The original
> rule was `cert_verified_at is None` → `cert_lookup_failed`. That assumed PSA
> verification was normal and its absence exceptional; **manual-first intake inverts
> it**, so the rule would flag *every* slab and turn Triage into noise — which is how
> a review queue becomes something people stop reading. `cert_lookup_failed` means
> *automation tried and failed*, and a human deliberately typing a slab in is the
> opposite of that.
>
> **The rule is now: flag only when `card_id` is missing.** That is
> `_review_reason_for_buy`'s existing `no_catalog_link`, which Triage already derives
> as `missing_card_id` at no cost — so this removes work rather than adding it. The
> frontend must therefore **never send `manual_entry`**. `cert_lookup_failed` keeps
> its literal meaning and returns to use when T2 does.

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
