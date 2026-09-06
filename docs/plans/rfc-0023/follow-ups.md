# RFC 0023 — Follow-ups

Out-of-scope findings. **Append here; do not fix as a side errand.**

## Deferred deliberately in the RFC

| # | Item | Why deferred |
|---|---|---|
| 1 | **Seeding the other 16 catalogs.** | Per-language and on demand by design — ~100k rows and a much larger `catalog_cache` for languages the business may hold no stock in. The `--language` flag is the mechanism; running it is an owner action driven by real stock. |
| 2 | **A language-scoped `catalog_cache` eviction policy.** | Only binds once a second language is actually seeded. The seeding task records the projected size first; if it would exceed the Lambda's memory, this becomes a blocker rather than a follow-up. |
| 3 | **Per-attribute price multipliers** (1st Edition ×N, Shadowless ×N). | A guess presented as a number on the surface where being wrong costs money. The operator hand-prices and `HandValuedBadge` marks it. |
| 4 | **A TCGplayer product-id link rather than a search link.** | Would need TCGplayer's catalog API and a product-id join we do not have. The search link is what exists today and it works. |
| 5 | **Cardmarket links for European languages.** | The obvious answer to "TCGplayer has no French category" — and a whole new provider integration, not a link-format change. |
| 6 | **Migrating existing `firstEditionHolofoil` items to `1stEditionHolofoil`.** | A data fix, not a code fix. T4's measurement will say how many rows exist; if it is non-trivial it wants its own dry-run script on the standard rail. |
| 7 | **Per-language card-level completeness spot-checks.** | The API confirms all 18 languages return non-empty *set* lists; nobody verified card-level population for the thin ones (`zh-cn` at 57 sets). Worth doing before treating one as fully supported. |
| 8 | **`display_name_override` for non-Latin languages beyond JP.** | The existing override field already works for any language; the Triage-page-only editing restriction and the "assigning a name never writes `card_id`" rule both carry over unchanged. Worth revisiting only if a language turns out to need something JP did not. |

## Found during execution

_(append as tasks discover them — one row each, with the task number that found it)_

| # | Found by | Item |
|---|---|---|
| 1 | planning | **`IncomingCardForm.tsx`'s `firstEditionHolofoil` does not exist in `_MARKET_FINISH_FALLBACK`** (which says `1stEditionHolofoil`). Fixed by T5/T6 for new entries; **existing rows carrying the wrong string are a separate data question — see deferred #6.** |
| 2 | T7 | ~~**`CardDetailModal.tsx` and `card/[id]/page.tsx` both still hardcode an English-only TCGplayer link**~~ — **RESOLVED (Round 9 closeout, 2026-09-03).** Both now route through `tcgplayerSearchUrl` (`lib/tcgplayer.ts`): `CardDetailModal.tsx`'s Quick Info link and `card/[id]/page.tsx`'s "TCGplayer"/"TCGplayer (stored)" buttons are language-aware, and a language with no TCGplayer category shows the same "No TCGplayer link" + tooltip pattern show-prep already used, instead of silently falling back to the English link. 8 new tests across the two files' suites. |
| 3 | T7 | ~~**`show-prep/page.tsx`'s `_tcg_url` column renders the raw ADMIN-TYPED `item.tcg_url` directly as `<a href>`**~~ — **RESOLVED (Round 9 closeout, 2026-09-03).** `lib/tcgplayer.ts` gained `safeTcgHref`, which delegates to the existing `lib/safe-href.ts` (already used to vet Sanity-authored links, parses with the real `URL` constructor rather than a regex) and narrows the result to http(s) only. All three renderers of a stored `tcg_url` — `show-prep/page.tsx`, `CardDetailModal.tsx`, and `card/[id]/page.tsx` (the last of which had its own weaker `startsWith('http')` check, tightened to the same helper) — now use it instead of the raw string, so a `javascript:` value falls back to the generated search link (or the "No TCGplayer link" message) rather than ever reaching an `href`. Regression tests added on all three surfaces plus `lib/__tests__/tcgplayer.test.ts`. |
