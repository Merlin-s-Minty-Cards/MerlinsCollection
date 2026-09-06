# RFC 0023: Card Identity Vocabulary — Languages, Finish Attributes, TCGplayer Links

**Status:** Draft — written 2026-09-02, adversarially reviewed the same day
(see "Adversarial review findings"). No code written yet.
**Author:** Claude (planning session), owner-directed
**Round:** 9 — see [`docs/plans/round9/README.md`](../plans/round9/README.md)
**Depends on:** RFC 0022 (the language and finish overrides are edit surfaces).
**Owner tasks covered:** "Need to support other languages besides EN and JP";
"The finish dropdown in the buy/sell/trade page needs to be reworked — these
values are not necessarily mutually exclusive and more research needs to be done
to make sure that every possible card finish is covered"; "When generating a
TCGplayer link, English and Japanese cards have different links depending on
language."

## Summary

Three changes to how a physical card's identity is recorded, grouped because they
touch the same models, the same forms and the same tests:

1. **Language grows from 2 values to 18 + a manual escape hatch.** TCGdex speaks
   18 language codes; the enum speaks 2. A new `OTHER` member plus a
   `language_note` free-text field covers a card TCGdex does not carry at all.
2. **Finish splits into a priced key + descriptive attributes.** `finish` stays a
   single string because it is the join key into `card.prices`, and gains
   `finish_attributes: list[str]` for everything that is genuinely not mutually
   exclusive — 1st Edition, Shadowless, Stamped, Full Art, Error, Signed.
3. **TCGplayer links become language-aware.** There are exactly two Pokémon
   categories on TCGplayer — English and Japan — and nothing else. The link
   generator returns the right one, or none, and says why.

## Motivation

### Language

`Language` is a two-member `StrEnum` and its docstring explains why:

> `EN` and `JP` are the only members and that is deliberate — the source
> spreadsheet contains no other language, and every added member is another axis
> of matcher ambiguity for data that does not exist (RFC 0003 §4).

That reasoning was correct when the only data source was a spreadsheet. It is no
longer the situation: the business buys cards at shows, and the owner's own
framing of the problem is the important part:

> "Every language as well as the ability to manually override language as a value
> just like any other field. This is the kind of reason it is important to be able
> to edit everything, as what happens when we get a card that is not supported by
> TCGdex? We need a way to input it into the system."

So the requirement is **two-sided**: 16 more catalog-linkable languages, *and* a
way to record a card whose language the catalog cannot represent at all.

Verified live 2026-09-02, from the TCGdex API's own 404 validation body (the docs
site says 14 and is stale — trust the API):

```
en, fr, es, es-mx, it, pt, pt-br, pt-pt, de, nl, pl, ru, ja, ko, zh-tw, id, th, zh-cn
```

Set coverage varies widely by language — `en` 218 sets, `zh-tw` 98, `ko` 95,
`th` 72, `id` 70, `zh-cn` 57 — but none of the ones checked came back empty.

### Finish

`frontend/components/admin/deal/IncomingCardForm.tsx` offers four options:

```ts
const FINISHES = ['normal', 'holofoil', 'reverseHolofoil', 'firstEditionHolofoil']
```

Two problems, and the second is a live bug.

**The list is not the vocabulary.** `_MARKET_FINISH_FALLBACK`
(`models/inventory.py`) — described in its own comment as "THE CANONICAL FALLBACK
ORDER FOR THE WHOLE PRODUCT, in every language it is implemented in" — reads:

```python
("normal", "holofoil", "reverseHolofoil",
 "1stEditionHolofoil", "1stEditionNormal", "unlimitedHolofoil")
```

**`firstEditionHolofoil` is not in it.** The dropdown offers a finish the pricing
fallback has never heard of, so an item staged with it looks up a key that does
not exist in `card.prices`, falls all the way through the fallback, and quietes
into whatever price happens to be first. `_map_finish` camelizes unknown TCGdex
keys, so `1st-edition-holofoil` → `1stEditionHolofoil` and
`first-edition-holofoil` → `firstEditionHolofoil` are two different internal
strings for the same physical printing, and the frontend picked the one the
backend does not use.

**And the owner's actual point is that these are not alternatives.** A card can be
1st Edition *and* Shadowless *and* holofoil. A modern card can be a Special
Illustration Rare that is also textured. A dropdown cannot express that and never
could.

### TCGplayer links

`frontend/app/(admin)/admin/show-prep/page.tsx` builds one link:

```
https://www.tcgplayer.com/search/pokemon/product?q=<query>&view=grid
```

That is the **English** category. Verified 2026-09-02 against TCGplayer's own
public category registry (`tcgcsv.com/tcgplayer/categories`, which mirrors their
catalog API): of 92 categories site-wide, exactly two are Pokémon —

```json
{"categoryId": 3,  "name": "Pokemon",       "seoCategoryName": "Pokemon"}
{"categoryId": 85, "name": "Pokemon Japan", "seoCategoryName": "Pokémon Trading Card Game - Japan"}
```

There is **no** Korean, Chinese, French, German, Spanish, Italian or Portuguese
Pokémon category. TCGplayer added Japanese Pokémon as a dedicated category in
October 2024 and has added no others.

So a JP card currently gets an English-category search link that will not find it,
and — after this RFC's language work — a Korean card cannot be linked at all,
which is a fact the UI must state rather than paper over.

## Owner decisions (recorded 2026-09-02)

1. **Languages:** "Every language TCGdex offers, plus the ability to manually
   override language as a value just like any other field."
2. **Finish:** one priced finish plus free-form attribute tags. Rejected: a pure
   multi-select with no primary (which would force pricing to pick a finish by
   invented heuristic), and a bigger single dropdown (which the owner had already
   said does not match reality).

## Detailed Design

### 1. Language

#### 1.1 The enum grows; nothing is renamed and nothing is backfilled

`models/inventory.py`'s `Language` keeps `EN = "EN"` and `JP = "JP"` **at their
current stored values** and gains 16 more members plus `OTHER`:

```python
class Language(StrEnum):
    EN = "EN"
    JP = "JP"          # api code "ja" — the value stays "JP", see below
    FR = "FR"
    DE = "DE"
    ES = "ES"
    ES_MX = "ES-MX"
    IT = "IT"
    PT = "PT"
    PT_BR = "PT-BR"
    PT_PT = "PT-PT"
    NL = "NL"
    PL = "PL"
    RU = "RU"
    KO = "KO"
    ZH_TW = "ZH-TW"
    ZH_CN = "ZH-CN"
    ID = "ID"
    TH = "TH"
    OTHER = "OTHER"
```

> **`JP` keeps the value `"JP"` even though the API code is `"ja"`.** Renaming it
> to `JA` would invalidate every stored inventory row and every `ja:`-prefixed
> `card_id`'s reverse lookup in one edit. `LANGUAGE_API_CODE` already exists
> precisely to carry that translation and already reads `{EN: "en", JP: "ja"}`.
> Extend the map; do not touch the values.

`LANGUAGE_API_CODE` gains an entry per new member, using the exact TCGdex code
(`ES_MX: "es-mx"`, `ZH_TW: "zh-tw"`, …). **`OTHER` gets no entry** — it is not
fetchable, and that absence is the mechanism (see 1.2).

`LANGUAGE_LABELS` gains a display name per member ("Korean", "Chinese
(Traditional)", "Other / unsupported").

**No migration, no backfill.** Every existing row is `EN` or `JP` and stays
valid. This is additive in the strictest sense.

#### 1.2 `OTHER` is the escape hatch, and it has one invariant

A card TCGdex does not carry — a regional printing, an oddity, a language the API
does not speak — is entered as `language = OTHER` with a free-text
`language_note` recording what it actually is ("Vietnamese", "Traditional Chinese
promo, not in catalog").

```python
language_note: str | None = Field(default=None, max_length=100)
```

> **Invariant: `language == OTHER` implies `card_id is None`.** Enforced by a
> `model_validator`, a 422 on violation — the exact mirror of the existing
> `no_catalog_match=True implies card_id is None` rule, which was added for the
> same reason and works. There is no catalog language to link to, so a linked
> `OTHER` item is a contradiction, and the composite `card_id` cannot even be
> constructed (`LANGUAGE_API_CODE` has no entry).

**An `OTHER` item belongs in UNMATCHED, not Triage, and that distinction is the
whole reason the Unmatched queue exists.** `missing_card_id` is a *derived*
triage reason, so before RFC 0011 an unmatchable card sat in Triage forever and
"the queue that is meant to reach zero had a floor it could never get under."
An `OTHER` item is unmatchable **by definition** — there is no catalog language
to link it to, ever. Routing it to Triage would rebuild that exact floor.

So **setting `language = OTHER` also sets `no_catalog_match = True`**, in the same
write, server-side. The existing invariant `no_catalog_match=True implies
card_id is None` already holds (§1.2's own invariant guarantees it), and
`services/triage.is_missing_card_id` — the one place that reads
`no_catalog_match` — then parks the item in Unmatched rather than Triage. Clearing
`OTHER` back to a real language does **not** auto-clear `no_catalog_match`: leaving
a queue is a deliberate admin action, and re-pointing the card is what clears it.

Other consequences, all of which the repo already handles for the unmatched
cohort and none of which need new machinery:

- It is **unpriceable by construction**, like a JP slab under the verified-join
  rule. It is hand-valued and carries `HandValuedBadge`.
- **Unlinking clears `current_market_value`** on the existing Unmatched path, for
  the documented reason (the inherited figure came from a card this item is not,
  and no sync will ever correct it once the link is gone). If an item is moved to
  `OTHER` *from* a linked state, that clear applies — which is a second reason
  the move is a deliberate 422-guarded action rather than a silent one.
- An `OTHER` item that is **also** flagged or unnamed keeps its remaining Triage
  chips. Parking answers one question; those are different, real errors.
- Setting `language = OTHER` on an item that *has* a `card_id` is a 422 telling
  the admin to unlink first, not a silent clear. Requiring a second write to leave
  a state is how rows get stranded — but silently destroying a catalog link is
  worse, and unlinking is already a first-class Triage action with its own diff.

`language_note` is **internal**. It must stay out of `_CUSTOMER_ITEM_FIELDS`, for
the same reason `review_reason` does.

#### 1.3 The catalog is seeded per language, on demand — not all 18 at once

**This is the load-bearing scope decision in this RFC.** "Support 18 languages"
means an item can *be* any of them and, where a catalog exists, link to it. It does
**not** mean seeding 18 catalogs tonight.

`en` alone is 31,603 rows. Seeding all 18 would be on the order of a hundred
thousand rows, a many-hour walk, a materially larger `catalog_cache` resident
size (already ~93 MB for one language — read that module's docstring before
going near this), and a much larger surface for the matcher ambiguity the original
`Language` docstring warned about.

So:

```bash
.venv/bin/python scripts/seed_catalog.py --language ko --execute --confirm-table merlins-cards
```

`seed_catalog.py` gains a `--language` flag (repeatable, defaulting to today's
behaviour). The owner seeds a language when there is stock that needs it. Until
then, an item in that language is entered as a manual/unmatched card and lives in
the Unmatched queue — which is exactly what that queue is for.

**`catalog_cache` must not silently balloon.** Its sizing note is explicit. Before
seeding a second language, the seeding task re-reads that docstring and records
the projected resident size in `progress.md`. If a second language would push it
past what the Lambda's memory allows, the cache needs a language-scoped eviction
policy first — and that is a follow-up, not a side errand.

#### 1.4 Where language becomes selectable

| Surface | Change |
|---|---|
| `CardDetailModal` | `language` changes from `type: 'text'` to `type: 'select'`; a new `language_note` text row appears **only** when the language is `OTHER` |
| `INVENTORY_COLUMNS` | the `language` column's `edit.type` is `select` (RFC 0022 supplies the mechanism) |
| `IncomingCardForm` | its existing `language` input becomes the shared select |
| `CardSearchPanel` / `GET /admin/market/search` | gains a language filter, defaulting to EN; **only offers languages that have catalog rows**, read from the `catalog_set` registry rather than from the enum — offering a language with an empty catalog is a search that always returns nothing |
| `frontend/lib/constants.ts` | `LANGUAGE_OPTIONS`, the single frontend list, mirroring `LANGUAGE_LABELS` |

#### 1.5 What must be checked, not assumed

- **`parse_card_id` splits on the FIRST `:`** and `_card_language` uses
  `split(":", 1)[0]`. Hyphenated codes (`es-mx`, `zh-tw`, `pt-br`) contain no
  colon, so both are already correct. **Verify with a test rather than by
  reading** — a `zh-tw:sv1-25` round-trip through `build_card_id` /
  `parse_card_id`.
- **`purge_card_data(languages=...)`** takes language codes to scope a wipe.
  Confirm which spelling (enum value or API code) and add a test for a new code.
- **RFC 0021's purge script reports an "unknown language" cohort** rather than
  deleting it. Those rows shrink to zero as languages land here. The split stays;
  it is what makes the two RFCs safe in either order.

### 2. Finish

#### 2.1 `finish` stays the priced key — and the vocabulary gets measured, not guessed

`finish: str` remains a single value and remains the join key into
`card.prices`. `_market_price` / `market_price_and_finish` are **unchanged**.
Nothing about pricing moves.

What changes is that the dropdown stops being a hand-written guess.

> **The priced-finish list must be derived from the finish keys that actually
> appear in the live catalog, not from anyone's memory of TCGplayer.** The
> evidence that this matters is already in the repo: the frontend offers
> `firstEditionHolofoil` and the canonical fallback tuple says
> `1stEditionHolofoil`. Someone typed a plausible string.

So the first task in this section is a **read-only measurement**: walk the live
catalog and report every distinct key present across `CatalogCard.prices`, with
counts. That list — plus `_MARKET_FINISH_FALLBACK`'s six, which are the fallback
contract — becomes `PRICED_FINISHES`, a constant shared by
`models/inventory.py` and `frontend/lib/constants.ts`, with the measurement date
recorded beside it.

`_map_finish` camelizes unknown TCGdex keys rather than dropping them, so the list
can gain a member later without anything breaking. It is a UI vocabulary, not a
validator: **an unknown `finish` string is still accepted** on write, because the
provider adds keys and rejecting one would make a real card unenterable.

#### 2.2 `finish_attributes` carries everything that is not mutually exclusive

```python
finish_attributes: list[str] = Field(default_factory=list, max_length=10)
# each entry bounded to 40 chars
```

On `RawInventoryItem` (where `finish` lives). Defaults to `[]`, so every existing
row validates unchanged.

A **suggested** vocabulary — offered as chips, not enforced — shared FE/BE:

```
1st Edition · Shadowless · Unlimited · Stamped (Prerelease) · Staff ·
Promo · Full Art · Alt Art · Illustration Rare · Special Illustration Rare ·
Gold / Secret Rare · Rainbow Rare · Textured · Cosmos Holo ·
Poké Ball Pattern · Master Ball Pattern · Jumbo · Error / Miscut · Signed
```

Free text is accepted alongside them. The owner is standing at a table with a card
in hand; a closed vocabulary is the failure mode this whole task exists to fix.

**`finish_attributes` IS customer-visible and goes into `_CUSTOMER_ITEM_FIELDS`.**
It is descriptive identity — "1st Edition", "Full Art" — and it is exactly the
kind of thing a customer looking at a card wants to know. This is the opposite
call from `language_note` and `review_reason`, which are internal, and the
difference is worth stating rather than leaving to whoever adds the field: a
*description of the card* is customer-facing; a *note about our handling of the
record* is not.

**Attributes do not affect pricing.** Say it in the model docstring and in the UI:
they are descriptive. A 1st Edition Shadowless Charizard is worth vastly more than
the `holofoil` band says, and the honest answer is that the operator prices it by
hand — inventing a multiplier per attribute would be a guess wearing a filter's
clothes, which is the same reasoning that killed `stale`/`max_age_days` on the
admin chat tools.

#### 2.3 `FinishPicker`

A new `frontend/components/admin/shared/FinishPicker.tsx`: one `vault-field`
`<select>` for the priced finish, plus a chip multi-select for attributes with an
"add custom" text input.

Used by `IncomingCardForm` (replacing `FINISHES`), `CardDetailModal` (the `finish`
row becomes a select and a new attributes row appears), and the inventory column
editor.

#### 2.4 Registry entries

`finish_attributes` needs, per this repo's totality rules:

- a `SORT_FIELDS` entry in `services/inventory_sort.py` — sort by count, or by
  the joined string; either is fine, but **missing values sort LAST in both
  directions**;
- a `FILTERABLE_FIELDS` entry in `services/inventory_filters.py`. It is a list,
  so it needs a new `FieldKind` — a "contains this attribute" comparison. An
  unknown filter is a **422**, never a silent no-op;
- an `INVENTORY_COLUMNS` entry with a real `columnKey` so its filter rides the
  "filters follow visible columns" mechanism rather than hiding behind the
  advanced toggle;
- **`defaultVisible: true` and `sortable: true`.** CLAUDE.md records the
  consignor column shipping `false`/`false` unconsulted and being reversed the
  next day for violating the "every column sortable, every column filterable"
  rule. Do not repeat it.

Both totality tests (backend registry vs model fields, frontend registry vs
columns) will fail until these land. That is the mechanism working.

### 3. TCGplayer links

A new `frontend/lib/tcgplayer.ts` — the **one** place a TCGplayer URL is built:

```ts
/**
 * TCGplayer has exactly TWO Pokémon categories, verified 2026-09-02 against
 * TCGplayer's own category registry: `pokemon` (id 3, English) and
 * `pokemon-japan` (id 85). There is no Korean, Chinese, French, German,
 * Spanish, Italian or Portuguese Pokémon category — TCGplayer launched
 * Japanese Pokémon in Oct 2024 and has added no others.
 *
 * Returns null for every other language. A null is NOT a bug and must not be
 * papered over with the English link: an English-category search for a Korean
 * card returns the wrong card or nothing, and both are worse than no link.
 */
export function tcgplayerSearchUrl(language: Language, query: string): string | null
```

| Language | URL |
|---|---|
| `EN` | `https://www.tcgplayer.com/search/pokemon/product?q=<q>&view=grid` |
| `JP` | `https://www.tcgplayer.com/search/pokemon-japan/product?productLineName=pokemon-japan&q=<q>&view=grid` |
| everything else, incl. `OTHER` | `null` |

`productLineName` is included on the JP form for parity with real TCGplayer
links; the path segment is what selects the category.

**Where a link cannot be generated, the UI says so in one line** beside the
still-editable manual `tcg_url` field:

> TCGplayer has no Korean Pokémon category — paste a link if you have one.

That is CLAUDE.md's rule for an unavailable control, and it is the difference
between "this feature is broken" and "this is a fact about TCGplayer".

**One incidental fix.** `services/card_text.set_hint_from_url`'s
`_TCG_PRODUCT_RE` strips a leading `pokemon-` from a product slug so a catalog set
name can be token-contained in it. A JP product slug is `pokemon-japan-...`, so
after stripping it becomes `japan-...` and contributes a junk `japan` token to
every JP set hint. Widen the strip to `^pokemon-(japan-)?`. Small, and it will
start mattering the moment JP links are generated at volume.

## API Contracts

No new endpoints. Three model fields are added and are accepted by the existing
partial-update endpoints:

```
InventoryItem.language          : Language     (18 members + OTHER; was 2)
InventoryItem.language_note     : str | None   (≤100 chars, INTERNAL)
RawInventoryItem.finish_attributes : list[str] (≤10 entries, ≤40 chars each)
```

`GET /admin/market/search` gains an optional `language` query parameter,
defaulting to `EN`. An unknown value is a **422**.

`GET /admin/catalog/languages` (new, tiny): the languages that actually have
catalog rows, derived from the `catalog_set` registry, so the search filter
offers only languages that can return something.

## Alternatives Considered

**Make `Language` a plain `str` with no enum.** Maximum flexibility and no
`OTHER` needed — and it deletes the guarantee that `LANGUAGE_API_CODE` can
translate any stored value, which is what `build_card_id` depends on. A typo'd
`"Japanase"` would then be a real, unnoticed language.

**Rename `JP` to `JA` to match the API code.** Tidier, and it invalidates every
stored row and every reverse lookup in one edit for a cosmetic gain.
`LANGUAGE_API_CODE` exists to carry exactly this translation.

**Seed all 18 catalogs.** Rejected in §1.3: hours of walk, a hundred thousand+
rows, a much larger `catalog_cache` resident size, and a much wider matcher
surface — for languages the business may never hold stock in.

**Pure multi-select finish with a pricing heuristic.** Declined by the owner and
rightly: any heuristic that picks which of several selected finishes to price
against is an invented rule on a money path.

**Per-attribute price multipliers** (1st Edition ×N). A guess presented as a
number, on the surface where being wrong costs money. The operator hand-prices;
`HandValuedBadge` already exists to mark that.

**Falling back to the English TCGplayer link for unsupported languages.** It
looks helpful and returns the wrong card. A stated absence beats a wrong answer.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Adding enum members breaks stored-row validation.** | Nothing is renamed and nothing is removed; every addition is additive and every existing row is `EN` or `JP`. A test loads a pre-existing row and asserts it still validates. |
| **`OTHER` items pile up in Triage, which is meant to reach zero.** | Setting `OTHER` also sets `no_catalog_match = True`, so they park in **Unmatched** — the queue built precisely because an unmatchable card gave Triage a floor it could never get under. No new queue either way. |
| **`catalog_cache` resident size grows past the Lambda's memory when a second language is seeded.** | Seeding is per-language and opt-in; the seeding task records the projected size before running. A language-scoped eviction policy is a follow-up if it ever binds. |
| **The finish list is wrong again.** | It is measured from the live catalog rather than typed, with the measurement date recorded beside the constant. An unknown finish is still accepted on write. |
| **`finish_attributes` becomes a free-text swamp.** | Suggested chips lead; free text is the escape hatch, not the default. Bounded at 10 × 40 chars so it cannot threaten the 400 KB item ceiling. |
| **A hyphenated language code breaks `card_id` parsing.** | `partition(":")` and `split(":", 1)` both split on the first colon and hyphenated codes contain none — but this is verified by a round-trip test, not by reading. |
| **A JP TCGplayer link poisons `set_hint_from_url`.** | The regex strip widens to `^pokemon-(japan-)?`, with a test. |

## Adversarial review findings (2026-09-02)

1. **Correctness — the frontend's `firstEditionHolofoil` is not in
   `_MARKET_FINISH_FALLBACK`.** This is a pre-existing live bug found while
   planning: the dropdown offers a finish the canonical pricing fallback has never
   heard of. It is the concrete evidence that the finish list must be measured
   rather than typed, and it is why §2.1 leads with a measurement task.
2. **Scope — "support 18 languages" was read as "seed 18 catalogs".** That would
   be hours of walk, ~100k rows, and a `catalog_cache` several times its already
   documented ~93 MB. Split: the *value* is supported immediately, the *catalog*
   is seeded per language on demand.
3. **Logic — `OTHER` with a `card_id` is a contradiction with no guard.** Added
   the model validator, mirroring the existing `no_catalog_match` invariant that
   solves the identical problem.
3b. **Logic — the first draft routed `OTHER` items to Triage.** An `OTHER` card is
   unmatchable *by definition*, so it would sit in Triage forever and rebuild the
   exact "floor the queue can never get under" that RFC 0011 created the Unmatched
   queue to remove. `OTHER` now also sets `no_catalog_match = True`.
4. **Data safety — renaming `JP` → `JA` was in the first draft.** It would
   invalidate every stored row. Cut; `LANGUAGE_API_CODE` already carries the
   translation.
5. **Bloat — the first draft gave each finish attribute a price multiplier.** Cut.
   It is a guess on a money surface and the repo already has a precedent for
   refusing exactly that shape (`stale`/`max_age_days`).
6. **Correctness — offering all 18 languages in the catalog search filter** would
   produce searches that can only ever return nothing. The filter reads the
   `catalog_set` registry instead, hence `GET /admin/catalog/languages`.
7. **Chaos — a JP product URL breaks `set_hint_from_url`'s `pokemon-` strip**,
   adding a junk `japan` token to every JP set hint. Fixed incidentally, with a
   test, because this RFC is what starts generating those URLs.

## Open Questions

None blocking. Two things are measured during execution rather than assumed: the
real finish-key vocabulary in the live catalog (§2.1), and the `catalog_cache`
resident size projection before a second language is seeded (§1.3).
