# T2 — PSA cert lookup, behind a Protocol, with an outbound quota guard

**RFC:** 0009 §5.1, §7, §9 · **Layer:** backend · **Depends on:** T0 (fixtures), T1
(model + router) · **Blocks:** T4

## Prerequisite

`docs/plans/rfc-0009/spike-findings.md` exists and T0's verdict is **PROCEED**.
The fixtures in `backend/tests/fixtures/psa/` are the contract you are mapping.
**If they are not there, stop — do not guess the response shape.**

## Files

- **Create:** `backend/src/merlins_collection/services/slab/__init__.py`
- **Create:** `backend/src/merlins_collection/services/slab/psa.py` — client + Protocol + fake
- **Create:** `backend/src/merlins_collection/services/slab/quota.py` — outbound daily counter
- **Modify:** `backend/src/merlins_collection/config.py` — `psa_api_key`, `psa_daily_quota`
- **Modify:** `backend/src/merlins_collection/routers/admin/slabs.py` — `/lookup`, `/quota`
- **Test:** `backend/tests/services/slab/__init__.py` (the sibling test dirs are
  packages — `backend/tests/services/__init__.py` exists — so yours needs one too),
  `backend/tests/services/slab/test_psa.py`,
  `backend/tests/services/slab/test_quota.py`,
  `backend/tests/routers/admin/test_slabs.py` (extend)

## The interface

```python
class CertRecord(BaseModel):
    cert_number: str
    company: GradingCompany          # always PSA from this provider
    grade: Decimal
    grade_label: str | None
    subject: str                     # PSA's card/player name
    year: str | None
    brand: str | None                # PSA's set/brand wording
    card_number: str | None
    image_url: str | None
```

```python
class CertLookup(Protocol):
    def lookup(self, cert_number: str) -> CertRecord | None: ...
```

`None` means "PSA has no such cert" — a normal answer. Failures raise; they are not
`None`. Conflating the two is how a real outage becomes a silent "card not found".

Two implementations: `PsaCertLookup` (HTTP) and `FakeCertLookup` (fixture-backed).
**No test makes a network call.** Wire the real one through a FastAPI dependency so
tests override it, matching how `get_repo` is injected in the sibling routers.

Field names come from **T0's findings**, not from this document — RFC §5.1 lists
what PSA returns but not the exact JSON paths, which is precisely what T0 recorded.

## The quota guard

PSA gives **100 calls/day** and **no rate-limit headers**. We count ourselves.

Reuse `DynamoRateLimiter` (`rate_limit.py:175-278`) — it already does distributed,
restart-safe, TTL-reaped per-day counters against the `merlins-rate-limits` table.
Do not build a second counter.

- Key it per provider, e.g. `outbound:psa:<epoch-day>`, so it can never collide with
  the per-user request limiters.
- **Fixed UTC-day window**, matching PSA's reset.
- Check-then-call: if the counter is at the cap, **do not make the request** — raise
  a typed `QuotaExhausted` the router turns into a degraded response.
- Increment on **attempt**, not on success. A 429 or a timeout still spent your
  allowance as far as PSA is concerned.
- Config default `psa_daily_quota: int = 100`, overridable — the owner may negotiate
  a higher tier, and a hardcoded 100 would then throttle for no reason.

**Fail-open vs fail-closed:** if the *counter* is unavailable
(`RateLimiterUnavailable`), let the call through and log. A broken counter must not
block intake; the worst case is a 429 from PSA, which is handled anyway.

## The lookup endpoint

`GET /admin/slabs/lookup/{cert_number}` — **read-only. It writes nothing.** It
returns a draft the frontend stages; only T3's commit persists anything.

Response:

```json
{
  "cert_number": "12345678",
  "found": true,
  "source": "psa",
  "cert": { "...CertRecord..." },
  "card_id": "base1-4",
  "match_confidence": "exact",
  "already_owned": { "item_id": "...", "status": "sold" },
  "degraded_reason": null
}
```

- `source`: `"psa"` or `"manual"` (degraded).
- `card_id` / `match_confidence`: from the catalog match below. `null` + `"none"`
  when nothing matched — **that is not an error**, the slab is still perfectly good
  inventory and will land in Triage as `missing_card_id`.
- `already_owned`: from T1's `get_item_id_by_cert`.
- `degraded_reason`: one of `"no_key"`, `"quota_exhausted"`, `"provider_error"`,
  `"not_psa"`, or `null`.

**Always `200`.** Every degradation is a normal, expected state that the UI renders
as an editable manual row. A 5xx here breaks a working intake session over a
third-party outage.

## Catalog matching

PSA gives you a name, set wording, number and year. Our catalog is TCGdex-keyed.
Match through the **existing** catalog cache (`services/catalog_cache.py` — read its
docstring first, particularly the ~93 MB resident sizing note). Do not add a scan;
do not add a second cache.

Set `match_confidence` to `"exact"`, `"fuzzy"` or `"none"`. Anything but `"exact"`
must reach the admin as something they confirm, not something applied silently —
CLAUDE.md's binding rule is that assigning a name never writes `card_id`, and the
same spirit applies here: a guessed catalog link is the admin's call.

## Non-PSA slabs

`company != PSA` → return immediately with `found: false`,
`degraded_reason: "not_psa"`, no quota spent, no HTTP call. CGC/BGS/SGC are manual
by design (RFC §9); this is not a gap to fill later.

## RED — write these first, confirm they fail, then STOP

```bash
./.venv/Scripts/python.exe -m pytest \
  backend/tests/services/slab backend/tests/routers/admin/test_slabs.py -q --tb=short
```

**Client** (all against T0 fixtures, no network)

1. A recorded fixture maps to a `CertRecord` with every field correct.
2. The recorded not-found response returns `None`, not an exception.
3. A 500 from PSA raises, and does **not** return `None`.
4. A 429 raises `QuotaExhausted`.
5. The `Authorization: Bearer <key>` header is sent. **Assert the key is not in any
   log record** emitted during the call.
6. A response missing an optional field maps to `None` for it, not a crash.

**Quota**

7. Under the cap, the call proceeds and the counter increments.
8. At the cap, `QuotaExhausted` raises and **no HTTP call is attempted** (assert on
   the fake transport, not on the result).
9. A failed call still increments.
10. Counters for two different epoch-days are independent.
11. `RateLimiterUnavailable` → the call proceeds (fail-open).

**Endpoint**

12. Happy path returns `found: true` with the mapped cert.
13. Unknown cert → `200`, `found: false`, `degraded_reason: null`.
14. Empty `psa_api_key` → `200`, `degraded_reason: "no_key"`, no HTTP attempted.
15. Quota exhausted → `200`, `degraded_reason: "quota_exhausted"`.
16. Provider raises → `200`, `degraded_reason: "provider_error"`. **Assert it is not
    a 5xx** — this is the whole point.
17. `company=CGC` → `200`, `"not_psa"`, quota counter unchanged.
18. A cert already in inventory populates `already_owned`.
19. The endpoint **writes nothing**: assert inventory count is unchanged after a
    successful lookup.

**Quota endpoint** (`GET /admin/slabs/quota`, RFC §7)

20. Returns remaining calls for the day, decreasing after a lookup.
21. **The response contains no API key**, for any provider. Assert on the serialized
    body, not on the model — this endpoint is the easiest place to leak one.
22. Reports the provider as unconfigured, rather than erroring, when no key is set.

## GREEN

Only after the owner confirms failure.

## Commit

```bash
git add backend/src/merlins_collection/services/slab backend/src/merlins_collection/config.py \
        backend/src/merlins_collection/routers/admin/slabs.py backend/tests/
git commit -m "feat(slabs): PSA cert lookup with an outbound daily quota guard"
```

Confirm no key is in the diff. Update [`progress.md`](progress.md).
