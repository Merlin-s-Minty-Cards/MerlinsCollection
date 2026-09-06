# RFC 0023 — Task Index

**RFC:** [`docs/rfcs/0023-card-identity-vocabulary.md`](../../rfcs/0023-card-identity-vocabulary.md)
**Round guide:** [`docs/plans/round9/README.md`](../round9/README.md) — read it first.
**Progress:** [`progress.md`](progress.md) · **Follow-ups:** [`follow-ups.md`](follow-ups.md)

**Do RFC 0022 first.** T4 and T7 below both assume the `EditSpec`/`select`
mechanism exists; without it they mean building bespoke forms that 0022 would
then replace.

| Task | Title | Depends on | Suite |
|---|---|---|---|
| T1 | Language enum + `language_note` + the `OTHER` invariant | — | backend |
| T2 | `seed_catalog.py --language` + `GET /admin/catalog/languages` | T1 | backend |
| T3 | Language across the admin UI | T1, 0022-T1 | frontend |
| T4 | Measure the live finish vocabulary | — | none (read-only, live) |
| T5 | `finish_attributes` model + registries | T4 | backend |
| T6 | `FinishPicker` + adoption | T5, 0022-T1 | frontend |
| T7 | `lib/tcgplayer.ts` + `set_hint_from_url` fix | T1 | frontend, backend |
| T8 | Docs + full-suite verification | all | all |

**T4 and T7 are independent** and are good short-session picks.

---

## T1 — Language enum + `language_note` + the `OTHER` invariant

**Files:** `backend/src/merlins_collection/models/inventory.py`,
`backend/src/merlins_collection/services/tcgdex.py` (the `LANGUAGE_API_CODE` map),
`backend/src/merlins_collection/services/customer_visibility.py` context, tests.

Add the 16 new members plus `OTHER` exactly as the RFC's §1.1 lists.

> **Do not rename `JP`.** Its stored value is `"JP"` and its API code is `"ja"`.
> `LANGUAGE_API_CODE` already carries that translation. A rename invalidates every
> stored inventory row and every reverse lookup in one edit.

`LANGUAGE_API_CODE` gains one entry per new member, using the exact TCGdex code.
**`OTHER` gets no entry** — that absence is the mechanism.

`LANGUAGE_LABELS` gains a display name per member.

New field on `_ItemBase` beside `language`:

```python
language_note: str | None = Field(default=None, max_length=100)
```

**Internal.** Assert in a test that it is not in `_CUSTOMER_ITEM_FIELDS`, the same
way `review_reason` is guarded.

**The invariant**, as a `model_validator`, mirroring the existing
`no_catalog_match=True implies card_id is None` rule (read that one first — it is
the pattern):

> `language == OTHER` implies `card_id is None`. A violation is a 422.

And, in the router (not the model — it is a transition rule, like
`_apply_no_catalog_match_transition` beside it): **setting `language = OTHER`
also sets `no_catalog_match = True`.** An `OTHER` card is unmatchable by
definition, so it belongs in Unmatched; leaving it to Triage's derived
`missing_card_id` reason would give that queue a floor it can never get under —
which is the exact problem RFC 0011 built Unmatched to solve.

**RED first.** Tests:
- A stored `EN` row and a stored `JP` row still validate unchanged (the
  no-migration guarantee).
- `Language("KO")` works; `Language("KLINGON")` raises.
- `build_card_id(Language.ZH_TW, "sv1-25")` → `"zh-tw:sv1-25"`, and
  `parse_card_id` round-trips it back to `(Language.ZH_TW, "sv1-25")`.
  **This is the hyphen test — do not skip it by reading the code.**
- `_card_language("CARD#pt-br:sv1-25")` → `"pt-br"`.
- `OTHER` + a `card_id` → 422. `OTHER` + no `card_id` → valid.
- Setting `language=OTHER` on an item that has a `card_id`, through
  `PUT /admin/inventory/{id}`, is a 422 with a message telling the admin to unlink
  first.
- Setting `language = OTHER` also sets `no_catalog_match = True` in the same
  write, so the item parks in **Unmatched**, not Triage. Assert it appears in
  `GET /admin/unmatched`-backing queries and **not** in the Triage list.
- Clearing `OTHER` back to a real language does **not** auto-clear
  `no_catalog_match`.
- `purge_card_data(languages=[...])` — confirm the spelling it expects and add a
  case for a new code.

---

## T2 — `seed_catalog.py --language` + `GET /admin/catalog/languages`

**Files:** `backend/scripts/seed_catalog.py`,
`backend/src/merlins_collection/routers/admin/catalog.py`, tests.

`--language <code>` (repeatable) scoping the seed. Default behaviour unchanged.
Keep the existing `--execute --confirm-table` rail. Keep — and check — the
chunked progress output; a second language is another multi-hour walk.

**Before running a seed for a second language, re-read
`services/catalog_cache.py`'s docstring and record the projected resident size in
`progress.md`.** It is ~93 MB for one language. If a second would push the Lambda
past its memory, stop and write a follow-up rather than seeding.

New endpoint:

```
GET /admin/catalog/languages -> [{"code": "EN", "label": "English", "sets": 284}]
```

Derived from the `catalog_set` registry — the languages that **actually have
catalog rows**, not the enum. The search filter reads this, so it can only ever
offer a language that can return results.

---

## T3 — Language across the admin UI

**Files:** `frontend/lib/constants.ts` (new `LANGUAGE_OPTIONS`),
`frontend/components/admin/shared/CardDetailModal.tsx`,
`frontend/lib/admin-inventory-columns.tsx`,
`frontend/components/admin/deal/IncomingCardForm.tsx`,
`frontend/components/admin/shared/CardSearchPanel.tsx`.

- `CardDetailModal`: `language` goes `type: 'text'` → `type: 'select'`. A
  `language_note` text row appears **only when the language is `OTHER`** — a
  permanently visible note field on 99% of cards is noise.
- `INVENTORY_COLUMNS`: the `language` column's `edit.type` becomes `select`
  (RFC 0022 supplies the mechanism), and its filter becomes an enum filter over
  the same options.
- `IncomingCardForm`: shared select.
- `CardSearchPanel` + `GET /admin/market/search`: a language filter defaulting to
  EN, its options from `GET /admin/catalog/languages`.

**The hook that fetches `/admin/catalog/languages` must gate on
`api.isAuthenticated` and put it in the effect's dependency array.** CLAUDE.md
names four hooks that shipped permanently empty from exactly this, and no jsdom
test can see it because a mocked session resolves synchronously.

---

## T4 — Measure the live finish vocabulary

**No code changes. Read-only against live.**

Walk the catalog and report every distinct key present across
`CatalogCard.prices`, with a row count per key. A script under `/tmp` is fine —
this is a measurement, not a deliverable.

Report it in `progress.md` with the date. That list, unioned with
`_MARKET_FINISH_FALLBACK`'s six, becomes `PRICED_FINISHES` in T5.

**Why this task exists:** the frontend currently offers `firstEditionHolofoil`
and the canonical fallback tuple says `1stEditionHolofoil`. Someone typed a
plausible string and it has been silently mispricing ever since. Do not type
another one.

---

## T5 — `finish_attributes` model + registries

**Files:** `models/inventory.py`, `services/inventory_sort.py`,
`services/inventory_filters.py`, plus tests for each.

```python
finish_attributes: list[str] = Field(default_factory=list, max_length=10)
# each entry ≤40 chars
```

On `RawInventoryItem`, where `finish` lives. Defaults to `[]` so every existing
row validates.

`PRICED_FINISHES` constant from T4's measurement, with the measurement date in a
comment beside it. **It is a UI vocabulary, not a validator** — an unknown
`finish` string is still accepted on write, because `_map_finish` camelizes new
provider keys and rejecting one would make a real card unenterable.

Registry entries, all three required by this repo's totality tests:

- `SORT_FIELDS` — missing values sort **LAST in both directions**.
- `FILTERABLE_FIELDS` — a new `FieldKind` for "list contains". An unknown filter
  is a **422**, never a silent no-op.
- `INVENTORY_COLUMNS` — with a real `columnKey`, `defaultVisible: true`,
  `sortable: true`. CLAUDE.md records the consignor column shipping `false/false`
  unconsulted and being reversed the next day; do not repeat it.

**Attributes do not affect pricing.** State it in the model docstring.
`_market_price` and `market_price_and_finish` are untouched — add a test asserting
that an item with attributes prices identically to one without.

---

## T6 — `FinishPicker` + adoption

**Files:** new `frontend/components/admin/shared/FinishPicker.tsx`,
`IncomingCardForm.tsx`, `CardDetailModal.tsx`, `admin-inventory-columns.tsx`.

One `vault-field` `<select>` for the priced finish + a chip multi-select for
attributes with an "add custom" text input.

The suggested chip vocabulary is in the RFC's §2.2. Free text is accepted
alongside — the operator is standing at a table with a card in hand and a closed
vocabulary is the failure this task exists to fix.

Delete the `FINISHES` array in `IncomingCardForm.tsx`. It is the bug.

**Every control gets `vault-field`.**

---

## T7 — `lib/tcgplayer.ts` + `set_hint_from_url` fix

**Files:** new `frontend/lib/tcgplayer.ts`,
`frontend/app/(admin)/admin/show-prep/page.tsx`,
`frontend/lib/admin-inventory-columns.tsx`,
`backend/src/merlins_collection/services/card_text.py`, tests.

The one place a TCGplayer URL is built. Two categories exist, verified
2026-09-02 against TCGplayer's own category registry — `pokemon` (id 3, English)
and `pokemon-japan` (id 85). Nothing else.

| Language | Result |
|---|---|
| `EN` | `https://www.tcgplayer.com/search/pokemon/product?q=<q>&view=grid` |
| `JP` | `https://www.tcgplayer.com/search/pokemon-japan/product?productLineName=pokemon-japan&q=<q>&view=grid` |
| everything else, incl. `OTHER` | `null` |

**A `null` is not a bug and must not fall back to the English link.** An
English-category search for a Korean card returns the wrong card or nothing, and
both are worse than no link. Where the link is absent, render one line beside the
still-editable manual `tcg_url` field saying why:

> TCGplayer has no Korean Pokémon category — paste a link if you have one.

**Backend fix:** `card_text._TCG_PRODUCT_RE` strips a leading `pokemon-` from a
product slug. A JP slug is `pokemon-japan-...`, so it leaves a junk `japan` token
in every JP set hint. Widen to `^pokemon-(japan-)?` with a test.

---

## T8 — Docs + full-suite verification

- `CLAUDE.md`: the language vocabulary and the `OTHER` invariant; the finish
  split and that attributes do not price; the two TCGplayer categories and that
  nothing else has one; the per-language seeding decision.
- Every suite in the round guide.
