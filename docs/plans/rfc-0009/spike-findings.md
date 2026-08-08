# RFC 0009 T0 — Provider spike findings

> ## ⚠️ STATUS: INCOMPLETE — BLOCKED ON THE OWNER. NOT A GATE VERDICT.
>
> **There is no PROCEED/STOP recommendation in this document yet, and nothing here
> may be treated as one.** T0's gate question — *can PokemonPriceTracker's free
> tier price this shelf, including the Japanese slabs?* — is **unanswered**, because
> answering it requires authenticated calls against real cert numbers and neither
> was available.
>
> **Missing prerequisites (T0 §Prerequisites):**
>
> 1. `PSA_API_KEY` and `POKEMONPRICETRACKER_API_KEY` in `backend/.env` — **both absent.**
> 2. ~20 real cert numbers off the shelf, **including at least 5 Japanese slabs** —
>    **not supplied.**
>
> **No fixtures have been recorded.** `backend/tests/fixtures/psa/` and
> `backend/tests/fixtures/pricing/` do not exist yet. T2 and T6 remain blocked.
>
> Everything below is either (a) evidence from **keyless** probes, which is real but
> narrow, or (b) **vendor documentation**, which is explicitly labelled as such and
> is exactly the kind of guessed shape T0 exists to replace. **Do not write a mapper
> against section 3 of this document.**

**Date:** 2026-08-07 · **Task:** [t0-provider-spike.md](t0-provider-spike.md) ·
**Spend so far:** 0 authenticated calls against either quota.

---

## 1. What was actually established

### 1.1 Both endpoints are live, and the two providers fail very differently

Four unauthenticated GETs (no key sent, so nothing was charged to either account).
Full bodies and headers: `keyless_probes.json` in the spike scratchpad.

| Probe | Status | Body |
|---|---|---|
| PSA, no `Authorization` | **429** | `"API calls quota exceeded! maximum admitted 100 per Day. Please contact collectors-apis@collectors.com"` |
| PSA, `Bearer not-a-real-token` | **429** | *identical to the above* |
| PPT, no `Authorization` | **401** | `{"error":"Authorization header missing. Use: Authorization: Bearer YOUR_API_KEY","hint":…,"documentation":…}` |
| PPT, `Bearer not-a-real-token` | **401** | `{"error":"API key too short","hint":…,"documentation":…}` |

Three consequences, and the first two are design inputs for T2:

**(a) PSA does not distinguish a bad key from a spent quota.** Both return the same
429 with the same body. T2's failure handling therefore **cannot infer "our quota is
gone" from a 429**, and cannot report "your key is wrong" honestly on the strength of
a status code. RFC §9 maps *"PSA key missing / API down / 429"* onto one behaviour —
manual entry with `cert_lookup_failed` — which survives this finding intact. But a
quota *counter* that decrements on a 429 would be wrong, and a `/admin/slabs/quota`
endpoint that claims to know why lookups are failing would be lying.

**(b) PSA returns `Retry-After`, and it is not midnight.** The RFC (§5.1) says *"No
rate-limit headers are returned — we must count our own calls."* The first half is
too strong. There is no `X-RateLimit-*` family — confirmed, the full header list is
`retry-after`, `cf-ray`, `cf-cache-status`, `content-type`, `date`, `server`,
`set-cookie`, `strict-transport-security`, `alt-svc`, `x-powered-by` and the CORS
trio — but a 429 carries **`Retry-After`**, and it counted **833 → 797 seconds**
across two probes about 36 s apart.

That is a **~13-minute countdown, not a wait until UTC midnight.** If that also holds
for an authenticated caller, then PSA's window is **rolling, despite the body saying
"per Day"**, and T2's quota guard must not be built as a calendar-day counter that
resets at 00:00 UTC. **This is the single most important thing to re-check with a
real key**, because T0's own budget note ("if you burn the quota you are blocked
until UTC midnight") may itself be wrong.

**Caveat, stated plainly:** these probes hit whatever bucket PSA applies to
anonymous callers — plausibly keyed by egress IP and already exhausted by someone
else. An authenticated bucket may behave completely differently. This is evidence
about *the shape of PSA's throttling response*, not proof about our account.

**(c) PPT returns a clean, machine-readable 401** with distinct messages for a
missing versus a malformed key, and uses Clerk (`x-clerk-auth-status`,
`x-clerk-auth-reason`). So for the pricing provider, **401 = auth, 429 = quota**, and
the two are separable. The documented `X-RateLimit-Daily-Remaining` header was **not**
present on the 401 — presumably authenticated responses only. Verify.

### 1.2 We hold nothing that addresses a card in the pricing provider

Grepped the whole backend: **no `tcgPlayerId`, `product_id` or `productId` anywhere
in `backend/src`.** `CatalogCard` ([models/catalog.py:63-94](../../../backend/src/merlins_collection/models/catalog.py#L63-L94))
stores `card_id`, `set_id`, `number`, `name` — and the TCGdex mapper keeps TCGplayer
*prices* while discarding TCGplayer's *product id*.

The only TCGplayer id in this system is embedded in an inventory item's `tcg_url`
(`/product/<id>/<slug>`, parsed by `set_hint_from_url` in
[card_text.py:149-167](../../../backend/src/merlins_collection/services/card_text.py#L149-L167)),
which is per-item, import- or admin-supplied, and absent on many rows.

PokemonPriceTracker addresses a card by `tcgPlayerId` **or** a free-text `search`.
Since we hold no `tcgPlayerId`, **first contact must be a fuzzy name+number search**,
whose chosen result is then pinned into `price_source_id` and reused. That is
precisely why the RFC made `price_source_id` a stored field, so the design holds —
but the resolution step is fuzzy, unmeasured, and is the main risk T6 inherits.
**Measuring its hit rate is part of what the blocked half of this spike must do.**

### 1.3 The existing matcher is the right one to reuse for `card_id`

Our catalog is TCGdex-keyed and neither provider knows those ids, so a PSA response
must be matched on text. That machinery already exists and is already the shared
authority for it:

- `build_catalog_index` ([card_text.py:216](../../../backend/src/merlins_collection/services/card_text.py#L216))
  keys cards on `(normalize_name, number_key, language)` **and** `(core_name, …)`.
- `_match_card` ([spreadsheet_import.py:300](../../../backend/src/merlins_collection/services/spreadsheet_import.py#L300))
  does exact-then-narrow matching, returns `None` on any ambiguity, and refuses a
  match whose set text contradicts the hit or that only resolved by dropping a
  qualifier like `alt`/`gold`/`1st`.

**T2 should call these, not write a second matcher.** `card_text.py`'s own docstring
records what two matchers that normalize differently already cost this codebase once.
`_match_card` returning `None` is the intended path to Triage's `missing_card_id`
(RFC §9), so unmatched slabs are handled with no new code.

Two things about it are unverified until real PSA data exists, and both are called
out because they are where this will break:

- **Language.** `_match_card` takes language as part of the lookup *key*, so a JP
  slab matched as `EN` does not merely miss — it can hit the English twin, at the
  English price. The spike script infers JP from the string `"japan"` in PSA's brand
  or variety text, which is a guess about a field nobody has seen.
- **Set text.** `_match_card`'s set narrowing expects something `sets_agree` can
  token-contain against a catalog set name. Whether PSA's `Variety`/`Brand` is
  anything like a set name is unknown, and a *contradicting* set text makes
  `_match_card` return `None` — so a badly-shaped set string would suppress matches
  that would otherwise succeed rather than merely failing to help.

## 2. The runner is written and verified as far as it can be

`spike_slabs.py`, in the session scratchpad — **deliberately not in
`backend/scripts/`** (T0: "not a tool anyone runs twice"). It has five subcommands:
`check`, `psa`, `pricing`, `match`, `report`.

Exercised without spending anything: readiness reporting, cert-file parsing
(rejecting a non-numeric cert), the dry-run planner, and the `--max-calls` guard.
The pricing and match commands correctly refuse to run before fixtures exist.

Quota discipline is built in, because the budget is small and unrecoverable:

- **dry run by default** — nothing is sent without `--execute`;
- **no retries at all**, since a timed-out call may already have been counted;
- **a 429 aborts the whole run** rather than continuing into a wall;
- **`--max-calls` (default 25) plus a hard cap of 40** so a typo cannot eat the day;
- **an already-recorded cert is skipped**, so re-running costs nothing;
- keys are read from the environment or `backend/.env` only, and **response headers
  are filtered through a `auth|key|token|cookie|secret` deny-pattern** before being
  written to a sidecar.

Two mechanical decisions worth knowing before the fixtures land:

- **Raw body in `cert_<n>.json`, metadata in `cert_<n>.headers.json`.** T0 requires
  the body be recorded unmodified, and status code and headers are needed too, so
  they go to a sidecar rather than being merged into the body.
- **An empty 204 body cannot be valid JSON.** `cert_not_found.json` will therefore
  hold an explicitly-labelled stub (`_spike_note` + `_raw_body: ""`) with the real
  status in the sidecar, rather than a silently empty file that a later test would
  fail to parse.

A `certs.sample.txt` template sits beside the script: one cert per line, `#`
comments allowed, optional `,label` second column (`jp`/`en` or a card name) that the
coverage table reuses.

## 3. UNVERIFIED — vendor documentation only

> **This section is what T0 exists to replace.** It is recorded so the authenticated
> run has something to check *against*, and to surface a quota problem early. Every
> line is from the vendor's own docs. **None of it has been observed from this
> codebase. Do not build a mapper from it.**

Sources: [api-reference](https://www.pokemonpricetracker.com/api-reference),
[psa-pokemon-card-api](https://www.pokemonpricetracker.com/psa-pokemon-card-api).

### 3.1 A priced slab looks like it costs 2 credits, not 1

The docs list credit costs as **1 credit for basic card data, +1 for eBay graded
data (PSA/CGC/BGS/SGC)**. Graded values are what we are after, so a slab refresh
appears to cost **2 credits**, not the 1 the RFC assumes (§5.2, "1 credit per card").

If that holds, the free tier refreshes **50 slabs a day, not 100**, and T7's
rotation math changes from `ceil(N/100)` to `ceil(N/50)` days for a full sweep. It
does not change the design — stalest-first rotation already handles a smaller
budget — but it halves the inventory size at which nightly refresh stops being
same-day. Logged as a follow-up so the RFC and T7 get corrected together.

### 3.2 The two vendor pages disagree about the graded price shape

| Source | Documented path |
|---|---|
| api-reference | `data.ebay.psa10.avg`, `data.ebay.psa9.avg`, plus `ebay.salesCount`, `ebay.medianPrice`, `ebay.marketTrend` |
| psa-pokemon-card-api | `ebay.salesByGrade.psa10.{count, medianPrice, averagePrice, minPrice, maxPrice, smartMarketPrice, lastSaleDate}` |

Two different nestings and two different value fields for the same number. **This is
the clearest possible argument for recording fixtures before writing T6's mapper.**
Note the second shape carries `lastSaleDate` — if real, that answers T0's "is there a
timestamp on the price?" question, which T6 needs for the value-age display.

### 3.3 Other documented claims to check against the real responses

- **Base URL** `https://www.pokemonpricetracker.com/api/v2`; cards at `GET /cards`.
- **Addressing:** `tcgPlayerId` (we have none — §1.2), `search` (multi-word natural
  language), `set`, plus `language=english|japanese`.
- **Japanese cards are claimed to be supported** via `language=japanese`, across
  "50,000+ English and Japanese cards". **This is the gate question and it is
  precisely what a vendor marketing page cannot settle** — JP *cards* existing in
  their database is not JP *graded sale comps* existing on eBay.
- **Documented headers:** `X-API-Calls-Consumed`, `X-API-Calls-Breakdown`,
  `X-RateLimit-Daily-Remaining`, `X-RateLimit-Minute-Remaining`. If real, the pricing
  provider needs **no** self-counting — unlike PSA. The spike script already records
  them.
- **Free tier:** 100 credits/day, 60 calls/min, 3 days of history.
- **Population** is a separate `GET /population` endpoint (GemRate data), **Business
  plan or above** — consistent with RFC §5.2. No change to the "no population field"
  decision.

## 4. Still unanswered — the whole authenticated half

Every question below is from T0 "What to produce" and needs the real run.

**PSA:** the exact JSON path to subject / year / brand / set-variety / card number /
grade / auto grade / label type / attributes / image URL · whether the body is
wrapped (`{"PSACert": {…}}`) or flat · whether `TotalPopulation` and
`PopulationHigher` are really `null` · what a genuine not-found cert returns
(status **and** body) · what an *authenticated-but-invalid* token returns, given
§1.1(a) shows an anonymous one returns 429 · what identifies the grading company ·
whether `grade` is a number, a string, or only present inside the label text.

**Pricing:** the real path to PSA 8/9/10 and what other grades exist · currency, and
whether it is stated or assumed · how coverage is actually addressed, which decides
what `price_source_id` stores · **what "no coverage" looks like — absent key, `null`,
or `0`** (T0 is right that this matters most; a `0` silently prices a slab at
nothing) · whether a price carries a timestamp · the response for an unknown card.

**Coverage:** the cert → card → JP/EN → PSA-resolved → priced table, and the verdict.

**Card-id mapping:** how often `_match_card` resolved a PSA response to one of our
31,603 catalog rows, split EN vs JP.

## 5. What the owner needs to supply

1. **Both API keys**, into `backend/.env` (gitignored — verified: `.gitignore:12`).
   Not into chat, and not into any tracked file. Note both keys were already pasted
   into a transcript during planning and are due for rotation regardless
   (progress.md, "Blocked / needs the owner").
2. **~20 real cert numbers**, with **at least 5 Japanese slabs** and a spread of
   grades. Made-up certs teach nothing — they return not-found and burn quota.
3. Ideally, one cert the owner **knows** is not in PSA's database, for the not-found
   probe. The script otherwise guesses `10000001`.

With those, the run is `check` → `psa --execute` → `pricing --execute` → `match` →
`report`, costing roughly 22 PSA calls and ~40 pricing credits, and this document
gets its missing sections and its verdict.
