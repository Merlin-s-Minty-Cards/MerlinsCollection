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
| 2 | T7 | **`CardDetailModal.tsx` and `card/[id]/page.tsx` both still hardcode an English-only TCGplayer link** (`https://www.tcgplayer.com/search/pokemon/product?q=...`), independent of the new `lib/tcgplayer.ts`. Neither is in T7's stated file list, so neither was touched — "the ONE place a TCGplayer URL is built" is not yet literally true across the whole admin panel, only for show-prep and the inventory table. Worth a small follow-up task to adopt `tcgplayerSearchUrl` in both (T3's language-select rollout touching `CardDetailModal.tsx` anyway is a natural place to also do this). |
| 3 | T7 | **`show-prep/page.tsx`'s `_tcg_url` column renders the raw ADMIN-TYPED `item.tcg_url` directly as `<a href>`** (`linkHref = item.tcg_url \|\| generatedUrl`), the exact stored-XSS shape (`javascript:` URI) `admin-inventory-columns.tsx`'s own comment on the identical field warns against. This is **pre-existing**, not introduced by T7 — T7 only replaced the fallback half of that expression, the vulnerable `item.tcg_url \|\|` half is untouched. Worth a dedicated security pass validating `tcg_url` is `http(s)://`-only before it is ever used as an href, on both `show-prep/page.tsx` and anywhere else that renders a stored `tcg_url` as a link. |
