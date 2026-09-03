# RFC 0023 — Card Identity Vocabulary: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 — **RFC 0023 COMPLETE, all 8 tasks (T1–T8)
done.** All four suites green: backend 2328, frontend 1225, mcp-server 101,
infra 44. CLAUDE.md updated. See "RFC 0023 IS DONE" below for the resume
prompt into the next RFC (0024).
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0023-card-identity-vocabulary.md`](../../rfcs/0023-card-identity-vocabulary.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Language enum + `OTHER` invariant | **DONE** |
| T2 Per-language seeding + `/catalog/languages` | **DONE** |
| T3 Language across the admin UI | **DONE** |
| T4 Measure the live finish vocabulary | **DONE** |
| T5 `finish_attributes` model + registries | **DONE** |
| T6 `FinishPicker` + adoption | **DONE** |
| T7 `lib/tcgplayer.ts` | **DONE** |
| T8 Docs + verification | **DONE** |

## RFC 0023 IS DONE — all eight tasks complete, verified 2026-09-02

Every task (T1–T8) landed in this one session. Full verification, all four
suites: **backend 2328 passed, frontend 1225 passed (110 files), mcp-server
101 passed, infra 44 passed.** `ruff check src` (backend, whole tree),
`npm run lint` (frontend, whole tree) and `npx tsc --noEmit` all clean — the
only warnings present (one `<img>` LCP warning, one pre-existing a11y
warning on an untouched file) predate this session.

CLAUDE.md gained a new section, "CARD IDENTITY GREW ON THREE AXES —
LANGUAGE, FINISH, AND TCGPLAYER LINKS (RFC 0023)", covering the language
vocabulary + `OTHER` invariant, the finish split + no-price-multiplier rule,
and the TCGplayer two-category rule — see that section for the durable
reference; this file stays the execution record.

Two deliberate, logged gaps — not blockers, not silently dropped:
`CardDetailModal.tsx`/`card/[id]/page.tsx` still hardcode the English-only
TCGplayer link, and show-prep's pre-existing raw-`tcg_url`-as-href pattern
is a stored-XSS shape worth its own security pass — both in
`follow-ups.md`.

**Fresh-session resume prompt for the NEXT RFC (round9 order: 0024, since
0021/0022/0023 are all done and 0024 is independent of everything):** "Read
`docs/plans/round9/README.md` for the round's working agreement, then
`docs/plans/rfc-0024/progress.md` and `docs/plans/rfc-0024/README.md`.
RFC 0024 (Acquisition Economics & Transaction Editing) is fully planned,
**T1 is next** — `acquisition_ratio` (both Python and TypeScript, plus the
cross-boundary pin test) — or T3 (`PATCH /admin/transactions/{txn_id}`) if
you'd rather start the backend-edit half instead; T1+T2 and T3+T4 are
independent halves per the task index. Start with the `tdd` skill — the RFC
and progress file already carry the design, no design doc needed. RFC 0023
is fully done (see its own progress.md) and needs no rechecking."

### T3 summary — done 2026-09-02

New `LANGUAGE_OPTIONS` (`frontend/lib/constants.ts`, all 19 members) mirrors
backend `LANGUAGE_LABELS` verbatim and is now the ONE source three surfaces
read from: `admin-inventory-columns.tsx`'s `language` column edit + filter
(previously a hand-typed subset that didn't even use real values — `'ZH'`
isn't a `Language` member, the real codes are `ZH-TW`/`ZH-CN`, and the
hyphenated `ES-MX`/`PT-BR`/`PT-PT` variants were missing outright),
`CardDetailModal.tsx` (`language` goes `text` → `select`; new `language_note`
row appears only when `language === 'OTHER'`, gated in the `visibleFields`
filter), and `IncomingCardForm.tsx` (deleted its own stale `EN`/`JP`-only
`LANGUAGES` constant and its now-wrong "case-sensitive StrEnum: EN/JP only"
comment).

New `GET /admin/market/search?language=` (backend, `routers/admin/market.py`)
defaults to `EN`, typed as the `Language` enum directly so FastAPI validates
an unknown value into a 422 with no manual code; applied to `cards` right
after either fetch branch (`set_id` GSI lookup or the cached full scan),
before the name/number filters, since a Base Set Charizard in EN and JP
share both a name and a set. New `frontend/lib/use-catalog-languages.ts`
(mirrors `use-catalog-sets.ts` exactly — fetch-once-on-mount,
`isAuthenticated`-gated retry, empty-list-on-any-failure) feeds
`CardSearchPanel.tsx`'s new fourth column, a language `<select>` defaulting
to `EN` and disabled while the catalog-languages list is empty/loading.

**Deliberate distinction, matching the RFC's own text exactly:** the
inventory table's language FILTER offers the full 19-member vocabulary (an
admin can legitimately own a Korean card before that catalog is seeded), but
`CardSearchPanel`'s language filter offers ONLY languages with real catalog
rows (`GET /admin/catalog/languages`) — a catalog search for an unseeded
language can only ever return nothing. Same field, two different scopes, by
design.

Verification: backend 2328 passed (4 new), frontend 1203 passed (109
files, 6 new test files/additions), `ruff`/`eslint`/`tsc --noEmit` clean
(pre-existing, untouched I001/F401 findings in `test_market.py`, confirmed
via `git diff` to predate this session, in lines this diff never touches).

### T5 summary — done 2026-09-02

`finish_attributes: list[str]` on `RawInventoryItem` (≤10 entries, ≤40 chars
each, defaults `[]`), customer-visible (`_CUSTOMER_ITEM_FIELDS`). New
`PRICED_FINISHES` (backend `models/inventory.py`, mirrored verbatim in
`frontend/lib/constants.ts`) is T4's measured 8-key union, with the
measurement date in a comment. `FieldKind.LIST_CONTAINS` (backend) /
`'listContains'` (frontend) is a new registry kind — `contains` means list
MEMBERSHIP, not a substring, checked explicitly against the wrong-by-default
substring-on-repr behavior a naive reuse of `TEXT`'s `contains` would have
produced. `SORT_FIELDS['finish_attributes']` sorts by count (missing =
empty list = sorts last both directions, same mechanism every other
extractor uses). Frontend: new `finish_attributes` column
(`defaultVisible: true`, `sortable: true` — the consignor-column lesson,
not repeated), a `multiselect` edit spec (RFC 0022's mechanism, first real
consumer), and a `FINISH_ATTRIBUTE_SUGGESTIONS` constant (the RFC §2.2 chip
list) shared with T6's `FinishPicker`. Verification: backend 2324 passed,
frontend 1186 passed, `ruff`/`eslint`/`tsc --noEmit` clean (one pre-existing,
untouched I001 finding, confirmed via `git diff` to predate this session).

### T6 summary — done 2026-09-02

New `frontend/components/admin/shared/FinishPicker.tsx`: one `vault-field`
`<select>` over `PRICED_FINISHES` plus a chip multi-select over
`FINISH_ATTRIBUTE_SUGGESTIONS` with an "add custom" text input (free text
always accepted, never gated behind the suggestions failing — same
escape-hatch discipline CLAUDE.md already states elsewhere). Exports
`finishAttributeChipVocabulary(selected)` — suggested chips plus any
already-selected custom tag, so a typed tag stays visible and removable —
shared with `CardDetailModal` rather than duplicated (found and fixed during
this task's own post-change adversarial review).

**`IncomingCardForm.tsx`**: deleted the old `FINISHES` array (the live bug —
it offered `firstEditionHolofoil`, a spelling `_MARKET_FINISH_FALLBACK` has
never heard of) and replaced the finish `<select>` with `<FinishPicker>`;
`finish_attributes` threads through `buildIncomingLeg`
(`lib/trade-incoming-form.ts`) as a real `string[]`, raw-kind only, omitted
entirely when empty (same shape as `set_name`/`card_number`/`image_url`).
**Caught by the form-level integration test, not the isolated component
test:** `FinishPicker`'s own "Add" (custom-tag) button collided with the
form's "Add" (submit) button under `getByRole('button', {name: /^add$/i})`
— fixed with a distinct `aria-label`. This is exactly why a component test
alone was not enough here.

**`CardDetailModal.tsx`**: `finish` becomes `type: 'select'` over
`PRICED_FINISHES`, mirroring `language`/`condition`'s existing branches. A
new `finish_attributes` row uses a NEW `'chips'` `FieldType` with its own
`attributesDraft: string[]` state — deliberately NOT routed through the
modal's existing `editValue` (a plain string), because RFC 0022 §1
explicitly rejects smuggling an array through a joined string and this
modal's edit plumbing predates (and is architecturally separate from)
`InlineEditCell`'s dedicated `multiselectValue`/`saveMultiselect` pair. A
chip toggles into the draft immediately; the PUT itself still waits for the
existing Save button, so the commit gesture matches every other field. One
pre-existing test (`'lets a cramped field row stack...'`) used "Finish" as
its example subject for a generic CSS-class contract that has nothing to do
with Finish specifically — updated to use "TCGplayer Link" instead, since
Finish stopped being a plain text input by this task's own design.

**`admin-inventory-columns.tsx`**: the `finish` column's edit options moved
from a hand-typed 3-entry list to `PRICED_FINISHES` (8 entries) — the
`finish_attributes` column itself was already built in T5.

Verification: frontend 1225 passed (110 files, up from 1203), backend
unchanged at 2328 (T6 touched no backend file), `ruff`/`eslint`/
`tsc --noEmit` clean.

### T7 summary — done 2026-09-02

**Files touched**, exactly matching the RFC's own T7 file list plus tests:
`backend/src/merlins_collection/services/card_text.py`,
`backend/src/merlins_collection/routers/admin/show_prep.py`, new
`frontend/lib/tcgplayer.ts`,
`frontend/app/(admin)/admin/show-prep/page.tsx`,
`frontend/lib/admin-inventory-columns.tsx`, and five test files (two new,
three extended).

**Backend regex fix.** `card_text.set_hint_from_url`'s strip widened from
`^pokemon-` to `^pokemon-(japan-)?` — a JP TCGplayer product slug is
`pokemon-japan-...`, so the old strip left a junk `japan` token in every JP
set hint. New test `test_set_hint_from_url_strips_the_japan_category_segment_too`
confirms the fix and that the existing EN case (`test_set_hint_from_url_extracts_set_tokens_from_product_slug`)
is unaffected.

**`GET /admin/show-prep/mispriced` now returns `language`** on every row (both
the percent- and dollar-threshold-mode branches — verified separately, since
this endpoint hand-builds two near-identical dicts rather than sharing one).
It never did before, so the frontend had no way to pick a per-item TCGplayer
category.

**New `frontend/lib/tcgplayer.ts`** — `tcgplayerSearchUrl(language, query)`
returns the EN/JP search URLs exactly per the RFC's table, `null` for
everything else (never falls back to the English link), plus
`TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE`. Typed
`language: string | null | undefined` rather than the RFC's literal
`Language` type — **this repo has no frontend `Language` type yet** (that is
T3's job, `lib/constants.ts`'s `LANGUAGE_OPTIONS`); every current caller's
item type already carries `language` as a plain optional string, so this is
an adaptation to the frontend's actual current type surface, not a deviation
from intent.

**Adopted in two places**, both replacing a hardcoded English-only template
string:
- `show-prep/page.tsx`'s `_tcg_url` column — generates the link from the
  item's own language, and shows a short "No TCGplayer link" label (full
  reason in `title`, **not inline**) when neither a stored `tcg_url` nor a
  generated one exists. The manual `tcg_url` field stays editable either way.
- `admin-inventory-columns.tsx`'s `tcg_url` column — gained a small icon-link
  built ONLY from the generated (safe, fixed-scheme) URL, never the raw
  stored string; a dimmed icon with the same tooltip when unsupported. The
  raw stored value is still never rendered as `<a href>` — that XSS guard
  (`javascript:` URI risk from admin-typed free text) is unchanged.

**Adversarial review caught one real bug during the post-change pass, fixed
before landing:** the first draft of the show-prep "unsupported language"
branch rendered the full ~90-character `TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE`
as inline text inside a `w-32` (128px) column — which would wrap across many
lines and blow that row's height up past its neighbours. Fixed to a short
"No TCGplayer link" label with the full message in `title`, mirroring how the
stored-link branch already handles its own long URL (short "Check Price"
text, full URL in `title`).

**Two findings deliberately NOT fixed, logged in `follow-ups.md` instead:**
`CardDetailModal.tsx` and `card/[id]/page.tsx` still hardcode the
English-only link (outside T7's stated file list); and `show-prep/page.tsx`'s
existing `_tcg_url` column already rendered the raw admin-typed `tcg_url` as
a live `href` before this task — the exact stored-XSS shape
`admin-inventory-columns.tsx`'s own comment warns against for the identical
field — pre-existing, untouched by this diff (T7 only changed the *fallback*
half of `item.tcg_url || generatedUrl`), and out of this task's scope per
"judge the delta, not the world."

**Verification:**
- Backend: `.venv/bin/python -m pytest tests -q` — **2306 passed**.
  `ruff check` on every touched file clean (two pre-existing I001
  import-order findings in two test files, confirmed via
  `git show HEAD:<path>` to predate this diff — left alone).
- Frontend: `npx vitest run` (full suite) — **107 files, 1170 tests
  passed**, run twice (once before, once after the post-review layout fix).
  `npx eslint` on every touched/new file clean. `npx tsc --noEmit` clean.

**T2 done 2026-09-02.** New `GET /admin/catalog/languages` endpoint
(`routers/admin/catalog.py`) alongside the existing `/sets`: groups
`repo.list_catalog_sets()` rows by `language`, returns
`[{code, label, sets}]` sorted by label, labels via `Language(code).label`
(falls back to the raw code rather than 500ing if a registry row somehow
carries a language this build's enum no longer has — should never happen,
nothing removes members, but an admin filter list is the wrong place to find
out). Same registry, same "no scan" guarantee as `/sets`
(`test_does_not_scan_the_catalog` mirrored). A language `Language` names but
nobody has seeded has zero registry rows and correctly never appears —
covered by its own test.

`seed_catalog.py --language <code>` (repeatable) **already existed and
already needed no further code change** — T1's crash-fix (iterate
`LANGUAGE_API_CODE`, not `Language`, in the filter branch; default to
`SEEDED_LANGUAGES`, not `list(Language)`) was, it turns out, the entirety of
T2's "seed_catalog.py --language" scope. Confirmed by re-reading `main()`:
the flag was already `action="append"` (repeatable), already validated
against `sorted(LANGUAGE_API_CODE.values())` (so every one of the 18 real
codes is already an accepted CLI value), and "default behaviour unchanged"
holds literally (still resolves to EN+JP with no flag, now explicit via
`SEEDED_LANGUAGES` rather than incidental via `list(Language)` having only
two members). No new tests needed here beyond T1's own
`test_no_language_flag_defaults_to_seeded_languages_not_every_enum_member`.

**Chunked progress output: checked, already correct, no change needed.**
`seed_language`'s `flush()` (`scripts/seed_catalog.py:190-224`) prints
`"mapped N, written N, preserved N"` every `BATCH_SIZE` (500) cards, inside
the walk loop — not only a final summary. For a ~30k-card language that is
~60 progress lines across the run, matching CLAUDE.md's "a one-time script
looping over live data for more than a few seconds must print progress
between chunks" rule already.

**`catalog_cache.py` resident-size projection, per its own instruction to
record this before a second language is seeded.** Re-read its docstring
(2026-09-02): **~93 MB resident for the CURRENT, already-combined EN+JP
catalog** (31,603 cards total across both languages, ~2.94 KB/card resident
— `93MB / 31,603`), held as ONE shared process-local list
(`repo.list_all_catalog_cards`, `routers/admin/market.py:610` →
`catalog_cache.get_catalog_cards`) — **not per-language.** Seeding a third
language does not create a second cache; it grows the one that exists.

Projected addition per language, using EN's own cards/set ratio (31,603 ÷
218 sets ≈ 145 cards/set) against the planning session's UNVERIFIED
per-language SET counts — **explicitly an optimistic upper bound**, since
EN is very likely TCGdex's most complete language (JP's own measured
completeness is ~50%, per `MIN_EXPECTED_RATIO_BY_LANGUAGE[JP] = 0.4` and its
comment) and no language's real CARD-level count has been measured:

| Language | Sets (measured, unverified at card level) | Projected cards (EN ratio) | Projected added MB | Projected NEW total |
|---|---|---|---|---|
| zh-tw | 98 | ~14,200 | ~+41.7 MB | ~135 MB |
| ko | 95 | ~13,800 | ~+40.5 MB | ~134 MB |
| th | 72 | ~10,400 | ~+30.6 MB | ~124 MB |
| id | 70 | ~10,150 | ~+29.8 MB | ~123 MB |
| zh-cn | 57 | ~8,265 | ~+24.3 MB | ~118 MB |

**None of these push past a typical Lambda memory ceiling on their own**
(even two combined stay under ~250 MB against commonly-provisioned
512 MB-1 GB configurations), but **this table is explicitly not a
go-ahead** — the RFC's own instruction is to re-measure before an actual
seed, and real per-language completeness could differ substantially from
EN's ratio in either direction. Whoever runs an actual
`seed_catalog.py --language <code> --execute` should re-derive this number
from that run's own `cards_seeded` summary (a real count, not a projection)
and record it here, and check it against the Lambda's actual configured
memory (not assumed) before treating a THIRD or later language as free.

**New tests, RED confirmed (404 on the not-yet-existing route) before
implementation:** `TestListCatalogLanguages` in
`tests/routers/admin/test_catalog_sets.py`, 7 tests mirroring
`TestListCatalogSets`'s own shape (one row per registry language, label
resolution, an unseeded enum member never appearing, alphabetical-by-label
sort, empty registry, non-admin 403, no-scan guard).

**Verification:** `tests/routers/admin/test_catalog_sets.py` — 26 passed (19
existing + 7 new). `ruff check` on the one touched file — clean. Full-suite
re-run deferred to T8 per the round guide's "test at RFC boundaries, not
after every file" instruction — this task's own scope is fully covered by
its isolated run plus T1's already-green full-suite baseline (T2 touched no
file T1's full run didn't already cover, other than the one new router
file).

**RFC 0022 is DONE** (its T5 gap is a documented, deliberate scope cut that
does not block this RFC — see `docs/plans/rfc-0022/progress.md`). T3 and T6
are unblocked whenever picked up.

**T1 done 2026-09-02.** Backend only, exactly the RFC's own file list:
`models/inventory.py`, `services/tcgdex.py`, tests. Full detail below.

### T1 summary

`Language` grew from 2 members to 19 (18 real TCGdex codes + `OTHER`), values
unchanged for `EN`/`JP`, per the RFC's §1.1 table exactly.
`LANGUAGE_API_CODE` (`services/tcgdex.py`) gained one entry per new member
using TCGdex's exact codes; `OTHER` deliberately has none. New
`language_note: str | None` field on `_ItemBase` (≤100 chars, internal, blank
normalizes to `None` via the existing `_blank_admin_text_is_none` validator
extended to cover it too). New `_other_language_implies_unlinked` model
validator mirrors `_unmatched_implies_unlinked` exactly: `language == OTHER`
implies `card_id is None`, 422 on violation, message says "unlink the card
first". Router gained `_apply_language_transition` (`routers/admin/
inventory.py`), called before `_apply_no_catalog_match_transition`: setting
`language = OTHER` also sets `no_catalog_match = True` in the same write —
**but only when the item kind actually carries a `card_id` field**
(`hasattr` guard). That guard is a real bug I found and fixed during the
pre-change adversarial review, not in the RFC's literal text: without it, an
admin setting `language = OTHER` on a SEALED item (e.g. a Korean booster box)
would trip `_apply_no_catalog_match_transition`'s existing sealed/bulk kind
guard and 422 with a confusing "no catalog link to be missing" error for a
field the admin never touched. Covered by
`test_setting_other_on_a_sealed_item_is_a_plain_unremarkable_write`.

**A second, more consequential bug found and fixed during the same review,
entirely outside the RFC's stated T1 scope but a DIRECT, immediate
consequence of growing the enum:** three places iterate `for language in
Language` (or `list(Language)`) expecting every member to have a
`LANGUAGE_API_CODE` entry — `services/catalog_sync.py`'s `_sync_new_sets`
(the "check for new sets" button AND the RFC-0021 monthly scheduled catalog
sync), `scripts/purge_catalog_junk.py`'s exclusion precompute, and
`scripts/seed_catalog.py` / `scripts/wipe_catalog.py`'s `--language` argument
resolution. Left alone, `_sync_new_sets` would have started silently WALKING
AND WRITING (`iter_brief_cards` + `batch_upsert_catalog_cards`) every one of
the 18 real languages' full catalogs on the very next "check for new sets"
click — a live, unguarded admin button, reachable today, with no relation to
RFC 0021's not-yet-deployed schedule — directly contradicting §1.3's explicit
"seeded per language, on demand, not all 18 at once" decision.
`seed_catalog.py`/`wipe_catalog.py` additionally KeyError'd immediately on
`Language.OTHER` (confirmed live via the full suite: 16 test failures) in
BOTH the explicit `--language` branch (the dict lookup runs before the `in`
membership check short-circuits it — not just the bare-default branch) —
`wipe_catalog.py` is the DESTRUCTIVE wipe+reseed script, so this was a live
crash-on-first-use regression, not a hypothetical.

**Fix:** a new `SEEDED_LANGUAGES = frozenset({Language.EN, Language.JP})`
constant beside `Language`/`LANGUAGE_LABELS` in `models/inventory.py` —
"languages actually loaded into the catalog today", extended only when
`seed_catalog.py --language <code> --execute` has actually been run for that
language (a manual, deliberate one-line edit alongside the seed, matching the
RFC's own "seeding is a deliberate, owner-directed action" framing). Used to
bound `_sync_new_sets`'s and `purge_catalog_junk.py`'s walks, and as the new
no-flag default for `seed_catalog.py`/`wipe_catalog.py` (previously
`list(Language)`, which meant "EN + JP" only because those were the enum's
only members — now explicit rather than incidental). The `--language <code>`
filtering branch in both scripts now iterates `LANGUAGE_API_CODE` (never
`OTHER`) instead of `Language`, fixing the KeyError outright regardless of
the default-vs-explicit question.

**Considered and rejected:** deriving "seeded languages" live from the
`catalog_set` registry (`repo.list_catalog_sets()`) instead of a hardcoded
constant — this is literally what T2's `GET /admin/catalog/languages` will
do. Rejected for `_sync_new_sets`'s own bound specifically because of a
chicken-and-egg bootstrap problem: `catalog_set` rows for a language are only
written BY `_sync_new_sets` itself, and `seed_catalog.py --language` (T2)
does not write them — so a freshly-seeded new language would have zero
`catalog_set` rows and a registry-derived bound would never pick it up,
ever. A hardcoded, deliberately-extended constant has no such bootstrap gap.

**Cascading test fixes, all confirmed as EXISTING tests whose fixtures used a
now-newly-supported language code as their "not a real/unknown language"
case** (not new bugs — RFC 0021's own T3 planning note anticipated exactly
this: "purging it would be a data-destroying false positive the moment RFC
0023 adds 16 more language codes"):
- `test_tcgdex.py`: two exact-equality assertions on `LANGUAGE_API_CODE`/
  `LANGUAGE_BY_API_CODE` updated to the full 18-entry map; the
  `fr:xy7-54` "unsupported language" parametrize case → `vi:xy7-54`
  (Vietnamese — genuinely outside TCGdex's 18 codes, unlike French now).
- `test_catalog_sync.py`: same `fr:` → `vi:` swap in
  `test_refresh_held_prices_counts_a_legacy_non_composite_card_id_as_unparsable`.
- `test_purge_catalog_junk.py`: same swap, `ko:xy7-54` → `vi:xy7-54`, in
  `test_an_unknown_language_row_is_reported_not_deleted_even_when_executing`
  (this is the exact test RFC 0021's own comment predicted would need this).
- `test_seed_catalog.py`: `test_every_language_has_a_floor_so_none_falls_
  back_to_the_flat_default` rescoped from `set(Language)` to
  `set(SEEDED_LANGUAGES)` — researching a real TCGdex-completeness floor for
  16 unseeded languages is measurement work that belongs WHEN each language
  is actually seeded (extending `SEEDED_LANGUAGES` and this floor table
  together), not speculatively for all 18 in T1.
- `services/inventory_sort.py` / `inventory_filters.py`: the new
  `language_note` field tripped `test_inventory_sort.py`'s registry-totality
  test (a model field with no sort extractor and no documented exclusion).
  Given `language_note` (internal) than `review_reason` (internal) share the
  identical shape, added `language_note: _text("language_note")` to
  `SORT_FIELDS` and `language_note: FieldKind.TEXT` to `FILTERABLE_FIELDS`,
  mirroring `review_reason`'s treatment exactly rather than excluding it —
  consistent with CLAUDE.md's "every column sortable, every column
  filterable" rule and its own recorded incident about a column shipping
  `false`/`false` unconsulted.

**New tests, RED confirmed before each fix** (a fresh KeyError/AssertionError/
422-that-should-be-200, per the mechanism it covers): `models/test_inventory.py`
(enum growth, `EN`/`JP` no-migration round-trip, `TestOtherLanguageInvariant`
×4, `language_note` internal/blank-normalize/length-bound); `test_tcgdex.py`
(full `LANGUAGE_API_CODE` map, `LANGUAGE_BY_API_CODE` exact-inverse, the
explicit `zh-tw` hyphen round-trip the RFC's own task text calls out by
name); `test_catalog_wipe.py` (`purge_card_data` with a hyphenated scope);
`test_inventory.py` router (`TestOtherLanguageTransition` ×5: 422-while-linked,
unlink-and-park-in-one-body, appears-in-Unmatched-not-Triage,
clearing-OTHER-does-not-unpark, sealed-item-is-a-plain-write);
`test_catalog_sync.py` (`_sync_new_sets` bounded to `SEEDED_LANGUAGES` even
with a `Language.KO` set configured in the fake client); `test_wipe_catalog.py`
(no-`--language`-flag default resolves to exactly `en, ja`, not a KeyError).

**Verification, this session:**
- `backend/.venv/bin/python -m pytest backend/tests -q` — **2295 passed**,
  0 failed (one unrelated pre-existing flaky MCP-stdio `BrokenPipeError`
  teardown warning on an unrelated test file, exit code 0 both times it was
  seen — not caused by this session, reproduced green in isolation).
- `backend/.venv/bin/python -m ruff check backend/src backend/scripts` on
  every file this session touched — clean. (6 pre-existing findings in 3
  untouched files — `scripts/import_held_singles.py`,
  `scripts/reprice_catalog.py`, `scripts/scheduled_sync.py` — confirmed via
  `git status` to predate this session; left alone as out of scope.)
- Frontend/mcp-server/infra suites **not re-run this session** — T1 touched
  backend only, zero frontend/TS files changed.

**Environment note, same class already documented for RFC 0021's T3/T4:**
`/tmp` (a 4.9GB tmpfs) filled to 100% from leftover `cdk.out*` scratch
directories **twice** during this session, blocking Bash entirely both
times — `rm -rf /tmp/cdk.out*` fixed it both times (confirmed safe: pure CDK
synth scratch output, not the git working tree). Neither this session nor
RFC 0021's ran a `cdk synth` — the directories were already there or
regenerated by something outside this session's own commands. If Bash starts
failing with `ENOSPC`/"temp filesystem is full" again, `df -h /tmp` and
`rm -rf /tmp/cdk.out*` first, same as RFC 0021's progress file already says.

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
  the date. **DONE — see "T4 summary" below.**
- **T2:** the projected `catalog_cache` resident size before seeding a second
  language.

### T4 summary — measured 2026-09-02

Read-only full scan of `merlins-cards` via
`InventoryRepository.iter_catalog_cards()` (the same paginated
`entity == "catalog_card"` scan `seed_catalog.py`/`backfill_catalog_sets.py`
already use). Script was a scratch file, not committed — this table is the
record. Progress was printed every 2,000 rows per CLAUDE.md's chunked-progress
rule; the whole scan took under two minutes.

```
TOTAL cards scanned: 29123
cards with at least one price band: 22333
cards with NO price band at all: 6790
```

**29,123, not the previously-recorded 31,603** (RFC 0023's own "facts
established during planning" section and CLAUDE.md's Ops section both cite the
older figure). Not investigated further here — most likely explained by
`purge_catalog_junk.py`'s TCG Pocket exclusion cleanup (CLAUDE.md's "Ops"
section) landing between that measurement and this one, which is exactly the
kind of row-count shrink that script is supposed to cause. Flagging rather
than silently overwriting the older number anywhere it's cited, since this
session did not verify the cause.

**Distinct finish keys present, by card count:**

| Key | Cards | In `_MARKET_FINISH_FALLBACK`? |
|---|---|---|
| `normal` | 15,249 | yes |
| `reverseHolofoil` | 12,196 | yes |
| `holofoil` | 6,417 | yes |
| `1stEdition` | 663 | **no** |
| `unlimited` | 663 | **no** |
| `unlimitedHolofoil` | 164 | yes |
| `1stEditionHolofoil` | 156 | yes |

**`1stEditionNormal` — one of the fallback tuple's own six entries — appears
in ZERO live cards.** It is not wrong to keep (the fallback is a fallback
*order*, not a claim every entry is populated), but it means the "canonical
six" and the "measured seven" are not the same set in either direction: the
fallback has one key with no live data behind it, and the live catalog has two
keys (`1stEdition`, `unlimited` — no `Holofoil` suffix) the fallback has never
heard of.

**`PRICED_FINISHES` per §2.1 ("that list — plus `_MARKET_FINISH_FALLBACK`'s
six") is the union, 8 keys:** `normal`, `holofoil`, `reverseHolofoil`,
`1stEdition`, `unlimited`, `unlimitedHolofoil`, `1stEditionHolofoil`,
`1stEditionNormal`.

**Cards by language (incidental, same scan):** `EN` 20,964, `JP` 8,159 — sums
to the 29,123 total, confirming no third language is silently present in the
catalog today (consistent with T1/T2: `SEEDED_LANGUAGES` is still EN+JP only).

**Confirms the RFC's own live bug finding independently:** the frontend's
`firstEditionHolofoil` (no live cards, and not in the fallback tuple either)
is doubly wrong — it matches neither the measured vocabulary nor the pricing
fallback. `FinishPicker` (T5/T6) must offer `1stEditionHolofoil` (camelCase,
capital-first, no space), not the frontend's current spelling.

## Owner gates on this RFC

None, but note that **seeding a new language is a long, live, write-heavy run**
and should be handed to the owner as a command rather than executed, consistent
with Round 9's deploy posture.
