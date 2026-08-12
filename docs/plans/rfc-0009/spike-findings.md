# RFC 0009 T0 — Provider spike findings

**Date:** 2026-08-08 · **Task:** [t0-provider-spike.md](t0-provider-spike.md)
**Spend:** 8 PSA calls (every one a 403), 46 of 100 daily pricing credits.
**Fixtures:** `backend/tests/fixtures/pricing/` (19 cards), `backend/tests/fixtures/psa/` (the 403).

## THE GATE — a split verdict

> ### Pricing (PokemonPriceTracker): **PROCEED.** T6 can be built.
>
> Coverage is **better than the RFC feared, not worse**. All 19 cards off the shelf
> returned per-grade PSA sales data — **including all three Japanese slabs**, which
> was the specific risk that justified this spike. JP graded comps exist and are
> current.
>
> ### PSA: **STOP — blocked outside this codebase. T2 cannot be built or verified.**
>
> Every request returns **`HTTP 403 {"Message":"Access to this API is limited to
> approved customers."}`** The token is valid and correctly formatted — it is the
> **account that is not entitled** to the public API. No code change can fix this.
> **The owner must get the account approved by PSA** (`collectors-apis@collectors.com`).
>
> ### And one finding that outranks both, for T6's design
>
> **Auto-pricing from a name search alone picks the WRONG card roughly a third of
> the time** (§3.3). This is not a coverage problem — it is why PSA matters. T6 must
> not silently attach a price to an unverified match.

Recommended order given the above: **build T6's provider client and the price
storage, but gate automatic attachment on a verified identity.** Full reasoning in §5.

---

## 1. PSA — blocked at the account, not the code

### 1.1 What every call returns

```
GET https://api.psacard.com/publicapi/cert/GetByCertNumber/89265056
Authorization: Bearer <the owner's key>

HTTP/1.1 403 Forbidden
{"Message":"Access to this API is limited to approved customers."}
```

Fixture: `backend/tests/fixtures/psa/psa_403_not_approved.json` (+ `.headers.json`).
**Named so it can never be mistaken for a cert response** — it is an error body, and
no mapper should ever be written against it.

### 1.2 It is the entitlement, not the key or the header format

Four auth variants against the same cert, which is how we know where the fault lies:

| What was sent | Result | Reading |
|---|---|---|
| `Authorization: Bearer <key>` | **403** *not approved* | key parsed, account rejected |
| `Authorization: bearer <key>` (lowercase, as PSA's docs write it) | **403** *not approved* | case is not the problem |
| `Authorization: <key>` (no scheme) | 429 *quota exceeded* | falls back to the **anonymous** bucket |
| `X-API-Key: <key>` | 429 *quota exceeded* | not a header PSA reads |

The 403/429 split is the proof: with a recognized bearer token PSA gets far enough to
say *"not approved"*; strip the scheme and it stops recognizing us at all and we land
in the shared anonymous pool. So **`Authorization: Bearer <token>` is the correct
format** — T2 should use exactly that — and the key itself is intact. The key is a
304-character opaque token, not a JWT (checked: one segment, no decodable claims), so
there is no client-side expiry to read.

### 1.3 What has been ruled out

Everything cheap has been tried. **Do not spend more quota re-testing these** — each
attempt costs a call and none of them can succeed while the account is unapproved.

| Tried | Result |
|---|---|
| Four auth header formats (§1.2) | `Authorization: Bearer` confirmed correct |
| Accepting the EULA at `psacard.com/publicapi/accepteula` | page needs a logged-in session; no change to the 403 |
| **A key the owner updated on 2026-08-08 13:08** | **still 403** (fingerprint `sha256[:12] = e4e50f8717d2`, length 304 — same length as the original) |
| A **second endpoint**, `GetImagesByCertNumber` | **also 403** — so it is account-wide, not one route |

The second endpoint is the decisive one: a per-endpoint entitlement would have let one
through. **The account itself is not on PSA's approved list.** PSA's own documentation
describes registration and a EULA but says nothing about an approval step, which is
consistent with public API access having been narrowed to approved customers since
those docs were written.

**The only remaining action is to ask PSA directly** —
`collectors-apis@collectors.com`, the address their own error body supplies.

### 1.4 What this corrects in the RFC and in my own earlier note

RFC §5.1 anticipates two failure modes, missing key and 429. **403 "not approved" is
a third, and it is the one actually happening.** An admin looking at "cert lookup
failed" would have no way to learn that the account needs approval — the fix is a
support email, not a retry, and not waiting for midnight.

This also **corrects a note I recorded on 2026-08-07**: I wrote that PSA cannot
distinguish a bad token from a spent quota. With the real key that is too pessimistic
— an *unrecognized* credential falls into the anonymous 429, but a *recognized but
unentitled* one returns a clearly distinguishable 403. The follow-up row has been
updated rather than left standing.

### 1.5 Consequently unanswered

Every PSA question in T0 remains open, and **none of it can be guessed**: the JSON
paths to subject/year/brand/variety/number/grade/label/image, whether the body is
wrapped, whether `TotalPopulation` is really `null`, what a not-found cert returns,
whether `grade` is a number or a string, and what names the grading company.

**T2 stays blocked.** It is a mapper, and there is still nothing to map.

> **CLOSED 2026-08-10 — these questions will never be answered, and that is fine.**
> PSA's cert API became a **paid** feature and the owner declined it, so **T2 and T5
> are WON'T DO** (RFC 0010 §H). The mapper was never written because its input shape
> was never observed — which, in hindsight, is the reason nothing has to be unwound
> now: refusing to guess a schema is what kept the withdrawal cheap.
>
> **Do not re-run the `psa` probe.** The findings below stay as evidence.

## 2. Pricing — verified, and the coverage question is answered

19 cards, one query each, `limit=1`, `includeEbay=true`. Every one returned
**HTTP 200 with graded sales data**. Raw bodies are in
`backend/tests/fixtures/pricing/card_<cert>.json`, with the exact request in
`card_<cert>.request.json` and status/headers in `card_<cert>.headers.json`.

### 2.1 Addressing, quota and billing

- **Base:** `GET https://www.pokemonpricetracker.com/api/v2/cards`
- **Auth:** `Authorization: Bearer <key>`. A missing key gives `401 {"error":
  "Authorization header missing…"}`, a malformed one `401 {"error":"API key too
  short"}` — so unlike PSA, **401 = auth and 429 = quota are cleanly separable.**
- **Addressed by** `search` (free text), `tcgPlayerId`, or `set`, plus
  `language=english|japanese`.
- **The response self-reports quota**, so T6 needs no call counter of its own:

```
x-ratelimit-daily-limit: 100      x-ratelimit-daily-remaining: 96
x-ratelimit-daily-reset: 1786233600   x-ratelimit-minute-limit: 60
x-api-calls-consumed: 4           x-api-calls-breakdown: cards=2,history=0,ebay=2
```

**Billing is the trap, and it is worse than the RFC assumes twice over:**

```json
"apiCallsConsumed": { "total": 4, "breakdown": {"cards": 2, "ebay": 2}, "costPerCard": 2 }
```

1. **`costPerCard` is 2, not 1** (RFC §5.2) — 1 for the card, 1 for `includeEbay`.
   Confirmed against a live response, no longer an inference from the docs.
2. **You are billed on `limit`, not on hits.** The very first probe used `limit=2`,
   matched **zero** cards, and was still charged **4 credits**. `limit` is the cost
   dial: cost = `2 × limit`, always. The free tier is therefore **50 slab lookups a
   day at `limit=1`**, and a careless `limit=5` would make it 10.

### 2.2 The graded price block — the second doc page was right

`ebay.salesByGrade.<grade>`, exactly as the `psa-pokemon-card-api` page describes.
The `api-reference` page's `ebay.psa10.avg` shape **does not exist**. Recording
fixtures before writing the mapper was worth it on this point alone.

`ebay` top level: `salesByGrade`, `priceHistory`, `gradesTracked`, `totalSales`,
`totalValue`, `salesVelocity`, `smartPriceOutlierByGrade`, `dateRangeStart`,
`dateRangeEnd`, `updatedAt`, `lastScrapedDate`, `lastEbayCheck`.

One real grade block (`card_89787279.json`, Gengar VMAX):

```json
"psa10": {
  "count": 334, "totalValue": 756846.69,
  "averagePrice": 2307.4594207317073, "medianPrice": 2450,
  "minPrice": 1340.4, "maxPrice": 3138.75,
  "marketPrice7Day": 2288.828571428571, "marketPriceMedian7Day": 2479.5,
  "dailyVolume7Day": 2, "marketTrend": "up",
  "lastMarketUpdate": "2026-08-05T08:15:59.231Z",
  "lastSaleDate": "2026-08-04T00:00:00.000Z",
  "smartMarketPrice": { "price": 2479.5, "confidence": "high",
                        "method": "7day_filtered_weighted", "daysUsed": 30 }
}
```

Answers to the specific questions T0 asked:

- **Which figure to store:** `smartMarketPrice.price`, and **carry
  `smartMarketPrice.confidence` with it.** It is the vendor's own outlier-filtered
  number; `averagePrice` is unfiltered and visibly skewed (psa10 average 2307 vs
  median 2450 vs smart 2479.5).
- **Far more than PSA 8/9/10 exist.** A typical card returns ~23 buckets:
  `psa1…psa10` **including half grades** (`psa8_5`, `psa6_5`), plus `bgs*`, `cgc*`,
  `sgc*`, `ace*`, `tag*`, and `ungraded`. **Our storage already fits this natively** —
  `GRADEDPRICE#<company>#<grade>` is keyed by company and grade, and `PricePoint.grade`
  is a `Decimal`, so `8.5` needs no schema change. The RFC's "PSA 8/9/10" framing
  understates what is available, and non-PSA grades are exactly what the CGC/BGS/SGC
  manual-entry path (RFC §9) could lean on later.
- **"No coverage" is an ABSENT KEY, never `0`.** The grade simply does not appear in
  `salesByGrade`. This is the good outcome — T0 flagged a `0` as the dangerous case
  because it would silently price a slab at nothing. **A missing key must still be
  handled as "no value", not defaulted to zero.**
- **Timestamps exist**, so T6's value-age display is well served:
  `smartMarketPrice.daysUsed`, per-grade `lastSaleDate` and `lastMarketUpdate`, and
  block-level `ebay.updatedAt` / `lastScrapedDate`.
- **Currency is ASSUMED, never stated.** There is no currency field anywhere in the
  response. The comps are eBay-US sold listings, so USD is the reasonable reading —
  and it matches our storage, where every stored figure is already USD by contract
  (`models/catalog.py`). **Record the assumption; do not let it become a silent one.**

### 2.3 `price_source_id` should store `tcgPlayerId`

Every card carries `tcgPlayerId` (e.g. `"253266"`) and `tcgPlayerUrl`. Since the API
accepts `tcgPlayerId` as a query parameter, the intended lifecycle is exactly what the
RFC designed: **resolve once by search, store the id, then refresh by id forever
after** — turning every subsequent nightly refresh into an exact, non-fuzzy lookup.

## 3. Mapping a provider card to our `card_id`

### 3.1 `externalCatalogId` is a direct join onto our catalog

This is the spike's most useful discovery. Each card carries an
`externalCatalogId` in TCGdex's own shape, and **`en:<externalCatalogId>` is our
`card_id`**. Verified by point-reading our live catalog:

| `externalCatalogId` | `en:<id>` resolves to |
|---|---|
| `swsh8-271` | Gengar VMAX \| Fusion Strike #271 |
| `xyp-XY96` | Umbreon \| XY Black Star Promos #XY96 |
| `gym1-9` | Misty's Seadra \| Gym Heroes #9 |
| `dp7-99` | Raichu \| Stormfront #99 |

Name, set and number agree in every case. **T2/T6 should try this join first** — it is
a single point read, needs no scan, and is deterministic. `_match_card` stays as the
fallback for cards that have no `externalCatalogId`.

### 3.2 How often it worked, across all 19

| Outcome | Count | Notes |
|---|---|---|
| Joined to a real catalog row via `en:<externalCatalogId>` | **13 / 19** | deterministic, no fuzzy matching |
| `externalCatalogId` present but **absent from our catalog** | 2 | `swsh9-TG23`, `swsh12-TG29` — both **Trainer Gallery** subsets, which TCGdex files under a different set id |
| **No `externalCatalogId` at all** | 4 | **all 3 Japanese cards**, plus one EN "Alternate Art Promos" card |

**The asymmetry matters: the deterministic join is an English-only convenience.**
Every Japanese card came back with `externalCatalogId: null`, so JP slabs fall back to
fuzzy matching against a catalog where JP printings are keyed `ja:…`. Since RFC §9
already sends an unmatched card to Triage as `missing_card_id` at no extra cost, this
degrades correctly — but it means **JP slabs will land in Triage as the norm, not the
exception.** Worth telling the owner before they meet it.

### 3.3 The name search is not safe to trust — the most important design finding

The vendor's `search` is far more literal than "multi-word natural language search"
suggests, and taking `data[0]` is actively dangerous. Measured on the owner's own names:

| Owner's card | Query sent | What came back | Verdict |
|---|---|---|---|
| Umbreon **Gold Star** | `Umbreon Gold Star` | **0 hits** | the full name finds nothing |
| Umbreon Gold Star | `Umbreon Star` | Umbreon **VMAX**, Brilliant Stars TG23 | ❌ wrong card |
| **M**ega **Latias** EX | `M Latias EX` | **Latios** EX, XY72 | ❌ wrong card, and wrong Pokémon |
| **Muk & Alolan Muk GX** | (as written) | **Alolan Muk GX**, Burning Shadows | ❌ wrong card (tag-team vs single) |
| Pikachu Beckett / Pikachu Illustration Contest 2024 | `Pikachu` | XY95 Pikachu, from **592 hits** | ❌ arbitrary |
| Gengar VMAX, Armored Mewtwo, Raichu LV.X, Misty's Seadra, … | (as written) | exact match | ✅ |

Roughly **a third of the shelf resolved to the wrong card**, and every wrong answer
came back looking exactly as confident as a right one — same 200, same populated
price block. Two compounding causes: adding a qualifier (`Gold Star`) can drop the hit
count to zero, while dropping one leaves hundreds of candidates and `limit=1` picks
arbitrarily.

**This is precisely the gap PSA was meant to close.** A verified cert supplies name,
set, number and year, which makes the query specific and gives us something to check
the answer against. Without it, an automated price attach is a coin flip on a third of
the shelf — and mispricing in the *business's* favour is the exact class of bug the
condition-pricing correction already cost this codebase once (CLAUDE.md).

Mitigation available today, and it is a good one: **when `externalCatalogId` joins to
our catalog, the match is self-verifying** — our own row's name, set and number
confirm it. Of the three wrong matches above, that check would have caught them
(`swsh9-TG23` is not in our catalog at all; `en:xyp-XY72` resolves to "Latios EX",
which does not agree with an item the admin called Mega Latias).

## 4. Coverage table — the gate evidence

`PSA resolved` is `n/a` throughout: the PSA API is 403-blocked, so identities are the
**owner's own labels**, not cert-verified. `Priced` means the provider returned a
`salesByGrade` block containing PSA grades.

| Cert | Owner's name | Lang | PSA resolved | Priced | Joined `card_id` |
|---|---|---|---|---|---|
| 89265056 | Pikachu With Grey Felt Hat (Van Gogh) | EN | n/a (403) | ✅ psa1–psa10 | `en:svp-085` ✅ |
| 89787279 | Gengar Vmax | EN | n/a (403) | ✅ psa1–psa10 | `en:swsh8-271` ✅ |
| 16967433 | Bubble Mew EX | **JP** | n/a (403) | ✅ psa6/8/9/10 | — no ext id |
| 150656224 | Seismitoad | **JP** | n/a (403) | ✅ psa3/4/7/8/9/10 | — no ext id |
| 67681781 | Umbreon Gold Star | EN | n/a (403) | ⚠️ wrong card | `en:swsh9-TG23` ✗ not in catalog |
| 151294759 | Arceus V (jp) | **JP** | n/a (403) | ✅ psa4/7/8/9/10 | — no ext id |
| 91318758 | Lugia Ex | EN | n/a (403) | ✅ psa1/5–9 | `en:bwp-BW83` ✅ |
| 114446365 | Rayquaza Vmax | EN | n/a (403) | ✅ psa8/9/10 | `en:swsh12-TG29` ✗ not in catalog |
| 137276480 | Salamence Reverse | EN | n/a (403) | ✅ psa1/4–9 | `en:xyp-XY59` ✅ |
| 135131501 | Mega Latias EX | EN | n/a (403) | ⚠️ wrong card (Latios) | `en:xyp-XY72` ✅ (to the wrong card) |
| 62979605 | Armored Mewtwo Promo | EN | n/a (403) | ✅ psa1–psa10 | `en:smp-SM228` ✅ |
| 119668773 | Raichu Lv. X | EN | n/a (403) | ✅ psa1/3–10 | `en:dp7-99` ✅ |
| 118689135 | Volcanion EX | EN | n/a (403) | ✅ psa1/6–10 | `en:xyp-XY173` ✅ |
| 13278649 | Pikachu **Beckett** | EN | n/a (403) | ⚠️ arbitrary (592 hits) | `en:xyp-XY95` ✅ (to an arbitrary card) |
| 147561799 | Yveltal Ex | EN | n/a (403) | ✅ psa1/6–10 | — no ext id |
| 132738276 | Misty's Seadra 1st Edition | EN | n/a (403) | ✅ psa4/7/8/9/10 | `en:gym1-9` ✅ |
| 126840905 | Muk & Alolan Muk GX | EN | n/a (403) | ⚠️ wrong card | `en:sm3-84` ✅ (to the wrong card) |
| 118461964 | Pikachu Illustration Contest 2024 | EN | n/a (403) | ⚠️ arbitrary (592 hits) | `en:xyp-XY95` ✅ (to an arbitrary card) |
| 57069857 | Eevee & Snorlax GX | EN | n/a (403) | ✅ psa1/4–10 | `en:smp-SM169` ✅ |

**Totals:** priced **19/19** · JP priced **3/3** · deterministic catalog join **13/19**
· visibly wrong or arbitrary card **5/19**.

**Verdict on the gate question, in one line: PokemonPriceTracker's free tier *can*
price this inventory, Japanese slabs included — the constraint is not coverage but
identification.**

Two notes on the sample itself, since they bound how much the table proves:

- **Only 3 of 19 are Japanese**, where T0 asked for at least 5. JP coverage looks
  genuinely good (3/3, with psa9 and psa10 comps on all three) but it rests on three
  cards. Worth widening before T6 leans on it.
- **Cert 13278649 is labelled "Pikachu Beckett"** — a **BGS** slab, not PSA. It could
  never have resolved through PSA's cert API even with an approved account, and RFC §9
  already routes CGC/BGS/SGC to manual entry by design. Fine, but it means the
  effective PSA sample is 18.

## 5. What this means for the plan

- **T2 (PSA lookup) is blocked** and cannot be started, let alone verified. Nothing in
  it can be written honestly until the account is approved.
- **T6 (pricing) can proceed** — the shape is known and recorded as fixtures, the
  quota is self-reported, and coverage is proven on real stock.
- **T6 must not auto-attach a price to an unverified match** (§3.3). The safe rule,
  available without PSA: attach automatically **only** when `externalCatalogId` joins
  to a catalog row whose name/set/number agree; otherwise stage the candidate for
  confirmation or send it to Triage. That preserves the value of the 13/19 that do
  join, without pricing the other third off the wrong comps.
- **T7's rotation math needs halving** — 50 slabs per night, not 100 (§2.1), and
  `limit` must be pinned at 1.
- **RFC §5.2's "1 credit per card" and §5.1's failure list both need correcting** —
  assigned to T8 via [follow-ups.md](follow-ups.md).

## 6. What the owner needs to do

1. **Accept the PSA public-API EULA, then re-issue the token.** This is the only
   blocker on T2, and it is external to this codebase.
   - Sign in to the PSA account that owns the token and accept the EULA at
     **https://www.psacard.com/publicapi/accepteula**. The page returns 403 to an
     anonymous request, so it requires a logged-in session — it cannot be automated
     from here, and accepting a licence agreement is the owner's to do regardless.
   - **Then generate a fresh token and replace `PSA_API_KEY` in `backend/.env`.**
     Re-tested after the EULA page was identified: the existing token still 403s, so
     acceptance does not appear to retro-enable a token issued before it. PSA's docs
     confirm the auth model is OAuth2 password-grant against PSA login credentials,
     and `Authorization: bearer <token>` — which matches what §1.2 measured.
   - If it still 403s with a fresh token, `collectors-apis@collectors.com` is the
     address PSA's own error body gives.
2. **Decide whether T6 proceeds ahead of PSA**, on the terms in §5.
3. **Rotate both keys** once the integration is confirmed working — both were pasted
   into a chat transcript during planning (progress.md).
4. Optionally, **more Japanese certs** to widen the JP sample beyond three.

## Appendix — reproducing this

`spike_slabs.py` in the session scratchpad; **not** in `backend/scripts/`, since it is
not a tool anyone runs twice. Dry-run by default, no retries, aborts on 429, caps its
own spend, skips already-recorded cards, reads keys only from the environment or
`backend/.env`, and strips credential-shaped headers before writing a sidecar.

```bash
cd backend
../.venv/Scripts/python.exe <scratchpad>/spike_slabs.py check   --certs <scratchpad>/certs.txt
../.venv/Scripts/python.exe <scratchpad>/spike_slabs.py psa     --certs <scratchpad>/certs.txt --execute
../.venv/Scripts/python.exe <scratchpad>/spike_slabs.py pricing --names-from <scratchpad>/certs.txt --limit 1 --execute
```

`certs.txt` is `<cert>,<owner's name>[,lang=japanese][,q=<search override>]`. The `q=`
override exists because of §3.3 — the query that finds a card and the owner's name for
it are different strings often enough that conflating them would hide the problem.

~~**Re-run `psa` first thing once the account is approved.** It is the whole of §1.5,
and it costs 21 of the 100 daily calls.~~ **WITHDRAWN 2026-08-10 — the account will
not be approved, because approval is no longer being sought.** The cert API is paid
and the owner declined it (RFC 0010 §H). **Do not re-run the `psa` probe**; it costs
quota and cannot succeed. The `pricing` probe is unaffected and still valid.
