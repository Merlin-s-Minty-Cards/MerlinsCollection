# T0 — Provider spike: verify both APIs before anything is built on them

**RFC:** 0009 §5.3 · **Layer:** spike (throwaway scripts + recorded fixtures) ·
**Depends on:** nothing · **Blocks:** T2, T6

## Why this task exists

Neither provider's response shape has ever been observed from this codebase.
Everything in T2 and T6 is a mapper from a JSON shape to our model — and a mapper
written against a guessed shape is worse than no mapper, because it looks like it
works.

There is also a **real chance the pricing vendor cannot price this shelf.** The
inventory has a meaningful Japanese component, and PokemonPriceTracker's graded
values derive from eBay *completed US listings*. If JP slab coverage is near zero,
the owner needs to know **before** T6 is built, not after.

**This task writes no production code.** Output is fixtures and a findings doc.

## Prerequisites — stop if these are missing

1. `backend/.env` contains `PSA_API_KEY=...` and `POKEMONPRICETRACKER_API_KEY=...`.
   **If either is absent, stop and ask the owner.** Do not hardcode a key anywhere.
   Do not create `.env` from a key pasted in chat without confirming.
2. A list of **~20 real cert numbers** off the owner's shelf, deliberately including
   **at least 5 Japanese slabs** and a mix of grades. Ask for these; do not invent
   cert numbers (a made-up cert returns 204 and teaches you nothing).

## Quota budget for this task

PSA free tier is **100 calls/day** and returns **no rate-limit headers**, so you
cannot ask how many remain. 20 certs is a fifth of the day's budget. **Do not loop.
Do not retry on failure more than once.** If you burn the quota you are blocked
until UTC midnight.

PokemonPriceTracker is 100 credits/day, 60/min.

## What to produce

### 1. Recorded fixtures

- `backend/tests/fixtures/psa/cert_<n>.json` — one file per cert, the **raw**
  response body, unmodified.
- `backend/tests/fixtures/psa/cert_not_found.json` — a 204/empty response.
- `backend/tests/fixtures/pricing/card_<n>.json` — raw pricing responses.

**Redact nothing except keys.** These become the fixtures every later test runs
against, so a field you tidy away is a field T2 will get wrong.

### 2. `docs/plans/rfc-0009/spike-findings.md`

It must answer all of these, with evidence pasted in:

**PSA**

- Exact JSON path to: subject/name, year, brand, set/variety, card number, grade,
  auto grade, label type, attributes, image URL.
- Is the response wrapped (e.g. `{"PSACert": {...}}`) or flat?
- Confirm `TotalPopulation` and `PopulationHigher` are `null`. If they are **not**,
  say so loudly — it reopens a design decision.
- What a **not-found** cert returns: status code and body.
- What an **invalid/expired token** returns.
- What field, if any, identifies the grading company (all responses are PSA, but
  the model stores `company` explicitly).
- Is `grade` a number, a string, or embedded in the label text?

**Pricing provider**

- Exact JSON path to PSA 8 / 9 / 10 values, and whether other grades exist.
- Currency, and whether it is stated in the response or assumed.
- How a card is addressed — provider id, set+number, name search? This determines
  what `price_source_id` stores.
- What "no coverage" looks like: absent key, `null`, or `0`? **`0` vs `null` matters
  enormously** — a zero silently prices a slab at nothing.
- Is there a timestamp on the price? T6 shows value age.
- Response for an unknown card.

**Coverage — the gate**

A table: cert → card → JP or EN → did PSA resolve it → did the pricing provider
return a value for that grade.

Then a one-line verdict: **is PokemonPriceTracker's free tier good enough to price
this inventory?**

### 3. Card-id mapping note

Our catalog is TCGdex-based (31,603 rows, `card_id` keys). Neither provider knows
our ids. Record how you would go from a PSA response to our `card_id`, and how
often it worked across the 20 certs. This is the input to T2's matching step and
the reason unmatched slabs fall to Triage.

## How to run it

A throwaway script under the scratchpad, **not** in `backend/scripts/` — this is not
a tool anyone runs twice:

```bash
cd backend
../.venv/Scripts/python.exe <your-scratchpad>/spike_psa.py
```

Load keys from the environment. **Never** paste a key into the script.

## Verification

There is no test suite for a spike. It is done when `spike-findings.md` answers
every question above with pasted evidence, and the fixture files exist.

## The gate

End your report to the owner with an explicit recommendation:

- **PROCEED** — coverage is adequate, T2 and T6 can be built as designed; or
- **STOP** — coverage is inadequate. Then propose alternatives (eBay Browse API for
  asking prices, the $9.99/mo tier, or manual-only pricing) and **wait for a
  decision.** Do not silently build on a source that cannot price the shelf.

## Commit

```bash
git add backend/tests/fixtures/psa backend/tests/fixtures/pricing docs/plans/rfc-0009/spike-findings.md
git commit -m "spike(slabs): record real PSA + pricing API responses and coverage findings"
```

Confirm `git status` shows no `.env` and no file containing a key before committing.

Then update [`progress.md`](progress.md): set T0 to `DONE`, and put the
PROCEED/STOP verdict in its Notes cell.
