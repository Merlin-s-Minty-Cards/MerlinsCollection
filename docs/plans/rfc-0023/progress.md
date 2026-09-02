# RFC 0023 — Card Identity Vocabulary: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0023-card-identity-vocabulary.md`](../../rfcs/0023-card-identity-vocabulary.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Language enum + `OTHER` invariant | NOT STARTED |
| T2 Per-language seeding + `/catalog/languages` | NOT STARTED |
| T3 Language across the admin UI | NOT STARTED — needs 0022-T1 |
| T4 Measure the live finish vocabulary | NOT STARTED |
| T5 `finish_attributes` model + registries | NOT STARTED |
| T6 `FinishPicker` + adoption | NOT STARTED — needs 0022-T1 |
| T7 `lib/tcgplayer.ts` | NOT STARTED |
| T8 Docs + verification | NOT STARTED |

## Next: T1

**RFC 0022 must land first for T3 and T6.** T1, T2, T4, T5 and T7 do not need it.

## Facts established during planning (do not re-derive these)

Verified live 2026-09-02:

- **TCGdex speaks 18 language codes**, enumerated by the API's own 404 validation
  body: `en, fr, es, es-mx, it, pt, pt-br, pt-pt, de, nl, pl, ru, ja, ko, zh-tw,
  id, th, zh-cn`. The docs site says 14 and is **stale**.
- **Set coverage per language:** en 218, zh-tw 98, ko 95, th 72, id 70, zh-cn 57.
  None checked came back empty. Per-language *card-level* completeness was **not**
  verified — spot-check before treating a low-count language as fully supported.
- **TCGplayer has exactly two Pokémon categories**, from their own category
  registry (`tcgcsv.com/tcgplayer/categories`, 92 categories site-wide):
  `{"categoryId": 3, "name": "Pokemon"}` and
  `{"categoryId": 85, "name": "Pokemon Japan", "seoCategoryName": "Pokémon Trading Card Game - Japan"}`.
  **No Korean, Chinese, French, German, Spanish, Italian or Portuguese category
  exists.** TCGplayer launched Japanese Pokémon in Oct 2024 and has added no
  others. A bogus slug returns HTTP 200 because the site is a client-rendered
  SPA, so the registry is the only reliable check — do not "verify" a slug by
  curling it.

Verified in this repo 2026-09-02:

- **`frontend/components/admin/deal/IncomingCardForm.tsx` offers
  `firstEditionHolofoil`. `models/inventory.py`'s `_MARKET_FINISH_FALLBACK` — the
  self-described canonical order for the whole product — says
  `1stEditionHolofoil`.** They are different strings. An item staged with the
  frontend's spelling looks up a key that does not exist and falls through the
  whole fallback. **This is a live bug, found while planning, and it is why T4 is
  a measurement task.**
- **`TCGDEX_FINISH_MAP` has only three entries** (`normal`, `holofoil`,
  `reverse-holofoil` → `reverseHolofoil`); `_map_finish` camelizes everything else
  rather than dropping it, so the internal vocabulary is open-ended by design.
- **`parse_card_id` splits on the FIRST `:`** and `_card_language` uses
  `split(":", 1)[0]`. Hyphenated codes contain no colon, so both should already be
  correct — **but verify with a round-trip test, do not conclude it from reading.**
- **`Language`'s docstring argues against exactly this change** ("every added
  member is another axis of matcher ambiguity for data that does not exist").
  That reasoning was correct for a spreadsheet-only data source and is now
  superseded by the owner's requirement. Update the docstring; do not leave it
  contradicting the code.

## Decisions made autonomously (with the rejected alternative)

- **`JP` keeps the value `"JP"` despite the API code being `"ja"`.** Rejected
  renaming to `JA`: it invalidates every stored row and every reverse lookup for a
  cosmetic gain, and `LANGUAGE_API_CODE` exists to carry the translation.
- **The catalog is seeded per language, on demand — not all 18 at once.** Rejected
  seeding everything: ~100k rows, a multi-hour walk, and a `catalog_cache` several
  times its documented ~93 MB. "Support 18 languages" means the *value* is
  supported; the *catalog* follows the stock.
- **`OTHER` implies `card_id is None`, enforced by a validator.** Rejected a soft
  convention: the composite `card_id` cannot even be built for `OTHER` (no API
  code), so a linked `OTHER` row is a contradiction that would silently break
  pricing.
- **Setting `OTHER` also sets `no_catalog_match = True`, so the item parks in
  UNMATCHED, not Triage.** Rejected letting it fall into Triage via the derived
  `missing_card_id` reason: an `OTHER` card is unmatchable by definition and would
  sit there forever, rebuilding the floor RFC 0011 created the Unmatched queue to
  remove. Clearing `OTHER` does **not** auto-clear `no_catalog_match` — leaving a
  queue is a deliberate action.
- **Setting `OTHER` on a linked item is a 422, not a silent unlink.** Rejected
  auto-clearing `card_id`: silently destroying a catalog link is worse than one
  extra deliberate step, and unlinking is already a first-class Triage action.
- **The catalog search language filter reads the `catalog_set` registry, not the
  enum.** Rejected offering all 18: a filter for an unseeded language is a search
  that can only return nothing.
- **Finish attributes carry no price multiplier.** Rejected per-attribute
  multipliers: a guess presented as a number on a money surface, the same shape
  the repo already refused for the chat's `stale`/`max_age_days`.
- **An unknown `finish` string is still accepted on write.** Rejected validating
  against `PRICED_FINISHES`: the provider adds keys and a rejection would make a
  real card unenterable.

## Measurements to record here during execution

- **T4:** the distinct finish keys present in the live catalog, with counts and
  the date.
- **T2:** the projected `catalog_cache` resident size before seeding a second
  language.

## Owner gates on this RFC

None, but note that **seeding a new language is a long, live, write-heavy run**
and should be handed to the owner as a command rather than executed, consistent
with Round 9's deploy posture.
