# Slab intake by hand — design

**Date:** 2026-08-08 · **Amends:** [RFC 0009](../../rfcs/0009-slab-intake-and-graded-pricing.md)
· **Plan:** [`docs/plans/rfc-0009/`](../../plans/rfc-0009/README.md)
**Status:** approved by the owner 2026-08-08

## Why this exists

RFC 0009 built slab intake around PSA's cert API: scan a barcode, PSA returns a
verified identity, the operator supplies only cost. **That path is unavailable.**
T0 measured `HTTP 403 {"Message":"Access to this API is limited to approved
customers."}` on every call, across two endpoints and a re-issued key — the account
is not entitled, and no code change reaches it
([spike-findings.md §1](../../plans/rfc-0009/spike-findings.md)).

Rather than wait, intake becomes **hand-entered first**. This is not only a
stopgap: RFC §8 already required hand entry to work in every degraded state, and
CGC/BGS/SGC slabs were always going to be manual by design (RFC §9). Making it the
primary path means the fallback is the path everyone uses, so it cannot rot.

**Nothing here is thrown away when PSA arrives.** PSA lookup returns as an
enhancement that pre-fills the same form.

## Decisions

| Decision | Detail |
|---|---|
| Card identity | **Catalog autocomplete with a free-text fallback.** Picking a catalog card sets `card_id`; free text leaves it `None` |
| Barcode scanner | **Stays in scope**, wired only to the cert field. No API involved, so it works today |
| T2 (PSA lookup) | **Deferred whole**, not hollowed out — see below |
| Review flagging | **A hand-entered slab is NOT flagged `needs_review`.** Amends T3 |
| Camera (T5) | Deferred further — it yields a cert number, which still resolves to nothing |

### Why T2 is deferred rather than stubbed

The obvious move is a PSA-free `/admin/slabs/lookup/{cert}` so T4's contract never
changes. **Rejected: without PSA, a cert number identifies nothing**, so the
endpoint would return an empty shell on every call — code written only to be
rewritten, and a false suggestion to its callers that a lookup happened.

The manual flow needs no new backend endpoint:

| Need | Endpoint | Status |
|---|---|---|
| Catalog autocomplete | `GET /admin/market/search?name=` | exists — the Buy page uses it |
| Duplicate cert check | `GET /admin/slabs/certs/{cert}?company=` | **exists — T1 built it** |
| Commit the batch | `POST /admin/purchases`, `/items`, `/confirm` | **T3** |

So the critical path is **T3 → T4**, and T3 is already unblocked.

### Why hand-entered slabs are not review-flagged

T3 specifies `cert_verified_at is None` → flag `needs_review` with
`cert_lookup_failed`. That rule assumed PSA verification was normal and its absence
exceptional. **That is now inverted** — every slab would be flagged, and Triage
would fill with items that need nothing, which is how a review queue becomes noise
people stop reading.

`cert_lookup_failed` means *automation tried and failed*. A human deliberately
typing a slab in is the opposite. The codebase already holds this principle: the
`reviewed_at` guard exists so automation cannot re-flag what a human has passed
(CLAUDE.md, Triage).

**The rule becomes:** flag only when `card_id` is missing. That is `missing_card_id`,
which Triage already derives at no cost. `cert_lookup_failed` is reserved for its
literal meaning and returns to use when T2 does.

## Revised task graph

| # | Was | Now |
|---|---|---|
| T0 | provider spike | **DONE** — pricing PROCEED, PSA STOP |
| T1 | slab model + cert pointer | **DONE** |
| T2 | PSA lookup + quota; **blocks T4** | **DEFERRED**, blocked on PSA approval. Enhances the tab; no longer enables it |
| T3 | buy session → graded | **Unchanged in scope, now the critical path.** One amendment: the review rule above |
| T4 | scan → lookup → stage → commit | **Manual entry → stage → commit. Depends on T3 only** |
| T5 | camera scan | Deferred further |
| T6 | pricing + slab list | Unchanged; still needs T4 |
| T7/T8/T-FINAL | — | Unchanged |

## T4 — the Slabs tab

### Components

- `frontend/app/(admin)/admin/slabs/page.tsx` — owns batch state and the commit flow
- `frontend/components/admin/slabs/SlabEntryForm.tsx` — the entry form; emits one
  staged row via `onAdd`
- `frontend/components/admin/slabs/CertInput.tsx` — the cert field; accepts a wedge
  scanner's burst and hand typing through one code path
- `frontend/components/admin/slabs/StagingTable.tsx` — the batch, with per-row edit
  and remove

Sidebar entry after **Buy** in `AdminShell.tsx` `navItems` (it is an acquisition
flow), using the `ScanLine` lucide icon.

### The form

| Field | Behaviour |
|---|---|
| Cert number | Scanned or typed. **Required** — `GradedInventoryItem.cert_number` is `str`, not optional (`models/inventory.py:307`), and it is the key of T1's `CERT#` pointer row, so there is nothing to store a slab under without it. Duplicate check on blur |
| Card | Catalog autocomplete, 300 ms debounce. `useAdminApi` prefixes `/admin`, so the call is `api.get('/market/search', { name })` → `GET /admin/market/search`. Selecting sets `card_id` |
| *(fallback)* Name / Set / Number | Free text, revealed by "Can't find it? Enter manually". Leaves `card_id` unset |
| Grade | Numeric, half grades allowed (`9.5`). Required |
| Company | Defaults `PSA`, editable — this is what makes CGC/BGS/SGC ordinary rather than special |
| Grade label | Optional free text, e.g. `GEM MT 10` |
| Cost | Required. **Never guessed** |
| Location | `useLocations()`. Never a hardcoded list |

No condition control — conditions are meaningless for a slab, and the customer
surface already skips the condition multiplier for graded items.

### `CertInput` — one path for scanner and keyboard

A wedge scanner is a keyboard that types fast and ends with Enter. **Submission is
never gated on typing speed**; timing may only decide whether to *auto*-submit, never
whether an entry is *allowed*. A cert typed slowly over ten seconds is exactly as
valid as one scanned in 40 ms, and an unreadable barcode makes hand entry the only
way in — which, since the cert is required, is the difference between entering that
slab and not.

Trailing `\r`/`\n`/spaces are stripped — some scanners append both.

### Duplicate check

On cert blur, `GET /admin/slabs/certs/{cert}?company=`. T1's contract: **`owned:
false` is a 200**, not a 404. A hit renders a warning naming the item and its
status, and **never blocks** — re-buying a slab you sold is legitimate (RFC §9).

### Staging table and commit

Rows are **client state only** until commit; nothing is persisted before then.
Commit is disabled while any row lacks a cost or a grade, and the button says which.

Commit is one action, three calls, in order — note the router prefix is
`/purchases`, though the id is called `buy_id`:

1. `POST /admin/purchases` → `buy_id`
2. `POST /admin/purchases/{buy_id}/items` per row, `kind: "graded"`
3. `POST /admin/purchases/{buy_id}/confirm`

**`buy_price` and `grade` go as JSON numbers**, not strings. That is the path that
500'd in production once, and the existing tests all send strings and missed it
(CLAUDE.md Ops).

**Partial failure must not half-commit.** If step 2 fails on row 4 of 10, stop, keep
every staged row on screen, name the failed row, and leave the session unconfirmed —
an unconfirmed draft creates no inventory, so "do nothing" is the safe state. Offer
retry.

On success: toast with count and total, clear the table, refocus the cert field.

### Conventions to follow, not reinvent

Read `frontend/app/(admin)/admin/buy/page.tsx` first — it already implements
catalog autocomplete with a `manualMode` toggle, a sequence guard so a slow search
cannot overwrite a newer one, and the loading and error states. Use `useAdminApi`;
call `adminItemName` for names; use `TABLE_THUMB_SIZE` / `TABLE_THUMB_COLUMN` with
`useCardImages` for art.

## Testing

Frontend, `cd frontend && npx vitest run components/admin/slabs app/\(admin\)/admin/slabs`:

- **CertInput** — a scanner burst emits once, never twice; characters typed slowly
  over a simulated multi-second span then Enter still emit (this is the regression a
  speed-gated implementation introduces); the Add button submits without Enter;
  trailing `\r\n` stripped; refocus after submit; works with no scanner present.
- **SlabEntryForm** — autocomplete selection sets `card_id`; the manual fallback
  leaves it unset and still adds a row; grade accepts `9.5`; company defaults to PSA
  and can be changed to CGC; **cert, grade and cost are all required**; a duplicate
  cert warns and still allows the add.
- **StagingTable** — a row missing cost blocks commit and says why; removing the row
  re-enables it; rows are editable after staging.
- **Page** — commit posts create → items → confirm in order with `kind: "graded"`;
  `buy_price` is a JSON number; a failure on the second item does **not** call
  confirm and leaves rows on screen; success clears and reports count + total.
- **End-to-end manual path** — a typed cert, a hand-typed card with no catalog
  match, a grade and a cost commit a valid graded item. This is the proof the
  feature works with no scanner, no camera and no PSA.

Backend, T3's suite gains: a graded item with `cert_verified_at=None` is **not**
flagged `cert_lookup_failed`, and one with no `card_id` **is** flagged for the
missing catalog link.

## Documentation to update

- **RFC 0009** — §5.1/§5.2 corrections T0 found (2 credits per card, billing on
  `limit`, the 403 failure mode), and a note that intake is manual-first.
- **`docs/plans/rfc-0009/t4-*.md`** — rewritten to this design.
- **`docs/plans/rfc-0009/t3-*.md`** — the review-flagging amendment.
- **`progress.md`** — the revised graph and dependencies.
- **CLAUDE.md** — `/admin/slabs` joins the Admin Panel route table (T8 owns this).

## Out of scope

- PSA cert lookup and its quota guard — deferred, not cancelled.
- Camera capture.
- Any change to the customer-facing surface. Graded items already appear in
  `/inventory` and nothing here alters that.
- Grade-multiplier price estimation, still rejected (RFC §11).
