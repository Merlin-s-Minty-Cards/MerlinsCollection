# TDD Guidelines
Always follow the outside-in Test-Driven Development (TDD) process.
1. RED: Write failing tests first. Do NOT implement the feature.
2. GREEN: Write minimal code to make the tests pass.
3. REFACTOR: Improve code quality, ensuring tests remain green.
Never combine phases. Wait for user confirmation after confirming tests fail.

# Agent Workflow
Development stays in the main thread — no subagent-driven orchestration. Custom skills live in `.claude/skills/`; the two remaining custom agents (`.claude/agents/test-qa.md`, `.claude/agents/web-browser.md`) exist only because their output is long-running or heavy and belongs off the main thread, not because they get orchestrated.

For **non-trivial feature work** (new functionality, multi-step changes, anything touching more than a couple of files), default to this flow without waiting to be asked:
1. `initialize-roadmap` skill — audit the workspace, create/update `claude-progress.md`, unless one already exists and is current for the active feature.
2. `design-doc` skill for architecture/schema/contract design on substantial features.
3. `tdd` skill for implementation — it nests `adversarial-review` as an inline pre- and post-change critique step (logic, security, chaos, bloat), no subagent spawn.
4. `sync-docs` then `pr-description` skills to close out.
5. `test-qa` and `web-browser` agents dispatch only when their isolation is actually needed (a long test run, heavy research output).

Skip this default for small fixes, one-off questions, or anything the user frames as quick — go straight to the relevant skill (or none) instead. The user can also override explicitly at any time (e.g. "skip the roadmap step", "just write the code").

**When the user explicitly invokes `subagent-driven-development` as that override, design stays with the driving model and only mechanical implementation delegates down.** RFC-writing, the implementation plan, and any task-brief authoring are done by the model already running the conversation — never handed to a subagent, because a fresh subagent re-derives context that model already has. Only the per-task implementer dispatches (the code-writer loop the skill drives once briefs exist) go to subagents, and each of those dispatches **must pass an explicit `model` override** — omitting it silently inherits the calling session's own model, which defeats the skill's own "Model Selection" section rather than merely skipping an optimization. Diagnosed 2026-08-14 on RFC 0012: the first implementer dispatches ran on Opus by default via the `code-writer` agent's own frontmatter, for tasks whose briefs already contained the exact code to write — pure transcription-plus-testing, the skill's own stated cheapest-tier case. Knowing the skill's rule was not enough; the fix was to make the check mechanical rather than remembered — the driving model treats "no explicit `model` on this dispatch" as an incomplete call, the same way a missing required argument would be.

**Closing the loop is a separate, always-on concern, not part of the feature flow above.** `lesson-capture` fires whenever the user reports that something Claude built or decided fell short, or Claude itself notices it took a long or circuitous path a clearer rule would have avoided — it writes the generalized lesson (never a narrow one-off fix) to CLAUDE.md or a skill, gated on the lesson actually generalizing. `skill-curator` is the periodic, hand-run counterpart that reviews `.claude/skills/` for drift — near-duplicates to merge, bloated skills to split, over-narrow entries that slipped past the gate. Any skill file either one touches goes through `writing-great-skills`, never `superpowers:writing-skills`.

## ESCALATE ON MISSING INFORMATION, NEVER ON UNCERTAINTY — THE OWNER SETS DIRECTION, NOT IMPLEMENTATION

Owner rule, stated 2026-08-27: *"My goal is to lay out a design idea, you ask
questions to help me nail down the details, then from then on, you do
everything without needing my input, with the exception of some very critical
cases."*

**The test for interrupting the owner is NOT "am I uncertain?" It is "does the
owner hold information I cannot obtain?"** Those come apart constantly, and
mistaking the first for the second is what produces a stream of questions the
owner experiences as being made to do the work they delegated.

Diagnosed on RFC 0018's kickoff, where two questions went up that should never
have left the session:

- *"Should the carried-forward visual verification run before RFC-0018's code
  or alongside it?"* — a **reversible ordering preference** with no
  information asymmetry at all. Pick one, say which and why, revisit if it
  turns out wrong.
- *"RFC-0018 says every money figure routes through `services/ledger.py`'s
  `is_countable`, but `mcp-server-admin/` is a Node process — mirror the
  predicate in TypeScript, or call back into the backend?"* — **answerable
  from the repo**, and from files already read in that same session:
  `ledger.py`, `mcp-server/src/condition-pricing.ts`, and
  `backend/tests/test_cross_boundary.py`, which is the existing precedent for
  exactly this Python↔TypeScript problem. The owner was handed a research
  task, not a decision.

Both had a determinable answer. Neither needed a human. `AskUserQuestion`'s
own description already says to reserve it for choices the codebase cannot
settle — **knowing that rule was not enough**, the same way knowing the
`model`-override rule was not enough above. So the check is mechanical:
**before escalating, name the specific fact the owner has that you do not.**
If you cannot name one, you are escalating on uncertainty and the question
does not go up.

**What DOES go up:** a change to what the feature *is* or who it is for; a
decision that spends money or is hard to reverse (a production write, a
deploy, a paid API, deleting owner data); a genuine conflict between two
things the owner has previously asked for; and anything the owner has
explicitly reserved. Note the asymmetry — *reversible* is the operative word.
An ordering choice is reversible; `POST /chat/` billing Bedrock and writing
rows to the live table is not, which is why **that** one was correctly held
back in the same session.

**When you want a second opinion, spawn an adversarial agent — do not use the
owner as one.** This is a deliberate, narrow exception to "development stays
in the main thread" above: it covers a *decision review*, never orchestrating
implementation. `adversarial-review` still runs inline inside `tdd` as its
pre- and post-change passes; this is the additional case where a design call
is genuinely close and an independent read is worth more than another lap of
self-critique. A subagent costs a few minutes; a question costs the owner a
context switch and their confidence that the work is being carried.

**Write the decision down where the next session will find it** — the
`claude-progress.md` roadmap item, the RFC, or a comment at the code it
governs — with the reasoning and the rejected alternative. A decision made
autonomously and left unrecorded is indistinguishable from one nobody made,
and it is what turns the owner's next question into an interrogation.

## `claude-progress.md` IS GITIGNORED AND ROLLING — NOTHING TRACKED MAY CITE IT

The roadmap file is scratch. `.gitignore` excludes it, so a fresh clone has
none of it, and every `initialize-roadmap` run **overwrites** the previous
baseline — the current file opens by saying it "supersedes the previous
baseline in this file". Last month's Section/Phase numbering is not archived
anywhere; it is gone.

So a citation to it from tracked source, tests or docs is a pointer nobody but
that week's author can resolve. Found 2026-08-27 while renaming the file from
`.txt`: **15 such citations across `backend/`** — `Section 3, Phase 12`,
`CONCURRENCY warning`, `KNOWN BUGS`, `DEFERRED — OTHER TABS`, `Phase 19`,
`LOG 2026-07-28`, `D4`. Every anchor had been overwritten several RFCs
earlier; **zero** of them still existed in the file. All 15 were removed, and
removing them cost nothing, because the substance each one carried — the
measurement, the rule, the reasoning — was already written inline in the
comment beside it. The citation was pure decoration over prose that already
stood on its own.

**Put the durable "why" in the comment itself**, and cite only targets that
survive: an RFC in `docs/rfcs/`, a plan in `docs/plans/`, a CLAUDE.md section,
or a dated measurement. If a fact is worth citing from source, it is worth
writing down somewhere tracked.

Same lesson, still visible: `RFC 0003 §7` is cited ~10 times across `backend/`
but `docs/rfcs/0001`–`0008` were deleted in `06d86f1`. Those are recoverable
from git history rather than gone, so they are an annoyance rather than a dead
end — but they were produced the same way.

## THIS WORKING TREE HABITUALLY HOLDS HOURS OF UNCOMMITTED WORK — INVESTIGATION IS READ-ONLY

`claude-progress.md`'s Workspace Snapshot has said "**Working tree: dirty, and
it matters**" across multiple features: two or three distinct bodies of
in-flight work, some staged and some not, routinely coexist here for days.
That is normal for this project and will be true again next session.

So a working-tree-mutating git command is **destructive here even when its
name sounds gentle**. `git stash` is the trap — it reads as "set this aside for
a second", it carries none of the `--hard`/`--force` signals that invite
caution, and it reverts every uncommitted change in the tree in one step. Run
2026-08-27 as an idle reflex while reading lint output, with nothing in the
task calling for it, it swallowed an entire in-flight RFC-0017 backend
implementation plus an RFC-0016 remediation tail. Recovery needed a full
manual rebuild from `stash@{0}` and `stash@{0}^2`, and was only possible
because `--keep-index` happened to preserve an index snapshot.

**While investigating, use read-only commands only** — `git status`,
`git diff`, `git log`, `git show`, `git stash list`, `git cat-file`. Anything
that writes the index or the working tree (`stash`, `reset`, `checkout --`,
`restore`, `clean`) alters the user's unsaved work and deserves the same
deliberation as editing their files by hand: only when the task actually calls
for it, and never as a step in figuring something out.

**If a recovery is ever needed:** `git stash pop --index` is what restores the
staged/unstaged split rather than flattening it. When it refuses — as it did
here, because `.gitignore`'s blob in HEAD is CRLF while `.gitattributes`
mandates LF, leaving that one file permanently "modified" and blocking the
merge check — `git checkout <stash> -- .` followed by `git reset <stash>^2 -- .`
rebuilds the identical end state without going through the merge at all.
Verify with `git diff <stash>` and `git diff --cached <stash>^2`; both empty
means the restore is exact.

## Context usage — stay under ~40% of the window, and say so before you don't

A model has no built-in sense of its own context usage — it cannot "just tell"
what percent full the conversation is without an explicit signal. This
project's `.claude/settings.json` sets `totalTokensReminder: "countdown"` +
`totalTokensReminderAfterUserTurn: true`, which is what supplies that signal:
a `<total_tokens>N tokens left</total_tokens>` marker gets injected after tool
results and after each user turn. That marker is the ONLY reliable usage
signal available — never estimate context usage from turn count, message
length, or "this feels like a long conversation" instead.

**On the first such marker seen in a session, record its value as that
session's baseline window size.** There is no direct readout of the model's
total context-window size, so the first reading is the only usable reference
point. Context-used percentage from then on is `1 - (current remaining /
baseline)`.

**Once usage crosses ~40% (remaining drops below ~60% of baseline), flag it
before continuing the requested work** — one line, not a wall of text — and
give the user two options: run `/compact` now, or wrap up the current point
and start a fresh session for the next task. Don't silently keep working past
that point without having flagged it at least once. Re-flag at ~60% and again
as usage nears wherever this session's auto-compact would fire on its own, so
the warnings escalate with how urgent it actually is.

**Flagging is not enough on its own — at high usage, actively DRIVE TO A
STOPPING POINT and hand off.** Owner correction, 2026-08-27: *"you should
still stop the conversation when the context is too high… Get to a stopping
point so I can compact the conversation."* A one-line warning that is followed
by another hour of work leaves the owner choosing between interrupting
mid-change and letting the window run out. So past roughly 45-50%, finish the
increment in flight, then stop:

1. **Land the work at a green boundary** — suites passing, nothing half-edited.
2. **Tear down anything the session started** — dev servers, temporary harness
   routes, background jobs — and confirm `git status --porcelain` holds only
   intentional changes. A compact must not strand a running process or a
   scratch file nobody will remember.
3. **Write state into `claude-progress.md`**, because that file is the handoff
   and the conversation is about to be summarized away.
4. **Offer a paste-ready resume prompt** — but which kind depends on where the
   stopping point falls, and the two are not interchangeable:

   - **Mid-task** (the increment in flight isn't done, or the very next step
     still needs everything just discussed — the failure mode, the design
     tradeoffs, the code just read): offer `/compact` with a resume prompt
     that continues the SAME task. The old context still has work left to do;
     compacting keeps a compressed version of it around for that work.
   - **Between tasks** (this task just landed at a green boundary and the
     next one hasn't started yet — the exact moment this section's own
     numbered list describes): the old task's context has nothing further to
     contribute to the next task. Owner correction, 2026-08-28: compacting
     here just to carry forward context the next task will never touch is
     wasted motion — write a **handoff** instead (a dated entry in
     `claude-progress.md` if one is already driving this work, otherwise a
     scratch handoff file) capturing exactly what a fresh session needs to
     pick up the next task cold, and offer a short prompt that points at that
     file and names the next task — not a `/compact` prompt. A fresh session
     with no prior context plus a good handoff costs less than compacting a
     full task's worth of exploration the next task will never use again.

**Still not a hard gate**: if the owner says keep going, keep going. The rule
is that the *stopping point* is prepared and offered, not that work halts
unilaterally — and never mid-edit, which is worse than either alternative.

`totalTokensReminder` is an undocumented/internal Claude Code setting (not
part of the public settings schema's stable surface) — if a future Claude
Code version stops honoring it, the marker simply stops appearing and this
section becomes a no-op rather than something that errors. There is no other
project-level way to give the model real numbers here; a pure "use your best
judgment" instruction without this setting cannot produce an actual
percentage, only a guess.

# Project Overview
Merlin's Minty Cards — a Pokemon card business website.
- Public website: Home, Shows, About, Collectors Dictionary, Articles
- Authenticated inventory search tool (filter mode + AI chat mode)
- Article/content hub for beginner collectors, managed via Sanity CMS

# Architecture

| Layer       | Language   | Framework       | Location       |
|-------------|------------|-----------------|----------------|
| Frontend    | TypeScript | Next.js 14      | `frontend/`    |
| Backend API | Python     | FastAPI         | `backend/`     |
| MCP Server  | TypeScript | MCP SDK         | `mcp-server/`  |
| CMS         | -          | Sanity          | `frontend/sanity/` |

# Site Pages

| Route                | Auth Required | Purpose                              |
|----------------------|---------------|--------------------------------------|
| `/`                  | No            | Home — brand intro, highlights       |
| `/shows`             | No            | Upcoming and past card show events   |
| `/about`             | No            | Business story, team, contact        |
| `/dictionary`        | No            | Collectors Dictionary (beginner terminology) |
| `/articles`          | No            | Article listing (Cluster Hub)        |
| `/articles/[slug]`   | No            | Individual article (SSG via Sanity)  |
| `/inventory`         | Yes           | Inventory search (filter + chat)     |
| `/admin`             | Yes (admin)   | Admin panel — see Admin Panel below  |

# Admin Panel

`/admin` (gated by admin Cognito group) covers inventory ops end to end.

**The sidebar is THREE GROUPS, not a flat list** (RFC 0010 T13,
`frontend/components/admin/AdminShell.tsx`). Sixteen flat tabs had outgrown the
viewport; they are now Dashboard on its own plus three collapsible groups named
for *when* you are using them. **Every route path is unchanged** —
`/admin/outgoing` included — because grouping is a sidebar concern and renaming
would break every bookmark to fix a URL nobody types.

| Group | Route | Label | Purpose |
|---|---|---|---|
| — | `/admin` | Dashboard | Quick actions, needs-attention queues, position, today, coverage |
| **At the show** | `/admin/inventory` | Inventory | Inventory CRUD, granular filters, ownership column |
| | `/admin/trade` | **Buy / Sell / Trade** | One surface, three modes via `?mode=`. See "Buy / Sell / Trade" below |
| | `/admin/slabs` | Slabs | Graded intake (cert → staged batch → commit → priced) + the slab list. See "Slabs" below |
| **Back office** | `/admin/outgoing` | **Prep Queue** | See "Prep Queue" below — route path is unchanged, the UI/purpose is not |
| | `/admin/show-prep` | Show Prep | Bulk-move to a show location, inline sticker/TCG-link editing, location filter + sort |
| | `/admin/shows` | Shows | Show CRUD — see "Shows" below |
| | `/admin/triage` | Triage | See "Triage" below — the `needs_review` queue + the four repair tools |
| | `/admin/unmatched` | Unmatched | Cards TCGdex does not carry — parked from Triage, paired when the catalog catches up. See "Unmatched" below |
| | `/admin/market` | Market | Prices, sync trigger, coverage/confidence, "check for new sets" |
| | `/admin/vault` | Vault | Sortable inventory table, ownership column |
| **Data** | `/admin/analytics` | Show Analytics | Tabbed Daily / Shows dashboard (see below) |
| | `/admin/history` | History | Transaction history with profit visibility (see below) |
| | `/admin/cosigners` | Cosigners | Cosigner CRUD + payout link tool |
| | `/admin/locations` | Locations | Admin-managed location list — see "Locations" below |
| — | `/admin/card/[id]` | (card detail) | Single-item detail, price chart, timeline — not in sidebar, reached via links |
| — | *(no route)* | **Analyst** | Read-only analyst chat, a slide-over in the sticky header of **every** tab — see "THE ADMIN ANALYST CHAT" below |

Three rules the grouping carries, all of which have a test in
`AdminShell.test.tsx`:

- **Groups default to OPEN**, and the group holding the active route is forced
  open regardless of what was saved. Shut-by-default makes every destination
  unreachable on a first visit.
- **The Triage badge rolls onto its group header only while that group is
  SHUT.** With the group open the count is on the Triage row itself, and the
  same number twice trains the eye to stop reading it.
- **The mobile bar is an explicit `mobileItems` list, never a `.slice()` of the
  groups.** Flattening the three groups and taking five yields *Trade* where
  Slabs used to be.

**Prep Queue gotcha:** the route path is still `/admin/outgoing` (unchanged
since before Round 3) but the page itself was repurposed in Task 3.4 from a
sold/shipment tracker into a queue of unstickered available inventory
(`GET` filtered to `status=available, missing_sticker=true`). Reading the URL
alone will mislead — it no longer tracks outgoing shipments.

**Pricing an item inline PATCHES the row and drops it — it does not refetch**
(RFC 0010 T7), which is what stops the list jumping under the cursor. Two
consequences follow and both are deliberate: the toast is **conditional**
(setting a price says "Priced → removed"; *clearing* one says "Sticker price
cleared" and the row stays, because a cleared row still meets this queue's
`missing_sticker=true` criterion), and the priced id is pruned from
`selectedIds` so the bulk bar cannot count a card nobody can see. The page also
filters and sorts **by location**, and both summary cards carry the scope in
their label (`In queue (Glass)`) — an unqualified total beside a scoped count is
the same misread through a different card.

**First header click sorts ASCENDING here, unlike `/admin/inventory`, whose
`handleSort` opens `desc`.** The two pages genuinely disagree; this is a
page-level default, not a `DataTable` change. And the column keys **are** the
backend's sort fields, because `_sort_admin_results` splits on the LAST
underscore — do not rename a `Column.key` on this page without re-checking that
split.

**Every inventory column is sortable and every column has its own filter**
(RFC 0011). Both are registry-driven: `SORT_FIELDS`
(`services/inventory_sort.py`) and `FILTERABLE_FIELDS`
(`services/inventory_filters.py`) on the backend, `INVENTORY_COLUMNS` /
`INVENTORY_FILTERS` on the frontend. Totality is enforced by tests on both
sides, so a new model field fails a test rather than silently arriving
without a sort or a filter.

**A `consignor_id` filter joined this registry in RFC 0012** — same
`services/inventory_filters.py` / `INVENTORY_FILTERS` +
`admin-inventory-columns.tsx` shape as any other field, letting an admin scope
the inventory table to one consignor's items.

**The consignor filter was unreachable for months, RFC 0013 T2 found —
present, wired, and invisible.** It had `columnKey: null`, so it only
appeared behind the separate "Show all filters" advanced toggle (default
off), and there was no Consignor **column** at all, so even a filtered view
couldn't show which consignor owned a row. Fixed with a new `consignor_name`
column (`admin-inventory-columns.tsx`) that resolves the id via the existing
`useCosigners()` id→name map; giving the filter entry a real `columnKey:
'consignor_name'` is what lets it ride the existing "filters follow visible
columns" mechanism (RFC 0011/Q9) instead of the separate advanced toggle.

**That fix shipped the column `defaultVisible: false` and `sortable: false`
— both unconsulted, and both reversed 2026-08-15.** RFC 0013 T2 landed
"every column sortable, every column filterable" as a stated universal rule
elsewhere in this file; leaving one column's own filter effectively
unreachable by default (a filter follows its column's visibility, and the
column was off) and its sort silently unbuilt was a quiet exception to that
same rule, never surfaced to the owner as a decision to make. Both are now
`true`. Sorting works via a small special case rather than a `SORT_FIELDS`
entry: `services/inventory_sort.py`'s `CONSIGNOR_NAME_FIELD` handles
`consignor_name` outside the registry, because every `SORT_FIELDS` extractor
is a pure `Callable[[InventoryItem], Any]` and this one needs data no single
item carries (the item stores `consignor_id`, not a name). The router builds
an id→name map from `repo.list_consignors()` — one bounded `Query` against
the `CONSIGNORLIST` partition, not a Scan — and **only when `consignor_name`
is the requested sort field**, so every other sort and every unsorted search
pays nothing extra. `services/table_sort.py`, the factory shared by the other
five sort registries, is untouched. `ctx.consignorName` (the id→name lookup)
is threaded through the same `render(item, ctx)` context every other
id-resolving column already uses.

**`CardDetailModal`'s read-only Consignor row had the identical bug, worse:
it rendered the raw `consignor_id` ULID, unconditionally** — never resolved
to a name at all, on any item, not even a discoverability gap. Fixed the same
day by giving the modal its own `useCosigners()` lookup (same pattern as
`ctx.consignorName`), falling back to the raw id only when it can't resolve
(e.g. an archived consignor, invisible to `useCosigners()` by design) — an
admin can still trace the row rather than losing the reference entirely.

**Card number (the catalog print number, "25" in "sv1-25") had the SAME
"present, wired, invisible" shape as the Consignor filter above, on TWO
surfaces at once — fixed 2026-09-04.** `admin-inventory-columns.tsx` already
had a `cardNumber` filter with `columnKey: null`, reachable only behind
"Show all filters", and no `_card_number` column existed for it to follow.
Separately, `/admin/card/[id]`'s header and its "Set"/"Card Number"
`DetailRow`s had been written against `item.set_name`/`item.card_number`
since the page was created, but `GET /admin/inventory/{item_id}`
(`admin_get_item`) returned a raw dump of the stored item with **no catalog
join at all** — so both fields were always `undefined` and both pieces of UI
silently rendered nothing, on every item, the whole time.

Two independent fixes, not one, because the two gaps needed different
remedies:
- `admin_get_item` now attaches `set_name`/`card_number` by reading
  `repo.get_catalog_card(item.card_id)` once, mirroring how it already
  attaches the derived `condition_multiplier`. **Deliberately not added to
  `_serialize_item` itself** — that function also backs `admin_search_items`
  (the LIST endpoint), which returns hundreds of unpaginated rows, and a
  catalog point-read per row there would add real latency to the busiest
  page in the admin panel. A single-item fetch pays for exactly one extra
  read.
- The admin inventory table gets a new `_card_number` column
  (`defaultVisible: false`, same as `_image`), resolved client-side via a
  new `useCardNumbers` hook + `POST /admin/inventory/card-numbers` — **a
  separate endpoint/hook from `/card-images`, not folded into it**, because
  the table gates each fetch on its OWN column's visibility
  (`visible.has(columnKey)`); tying Card # to the Image fetch would mean an
  admin wanting one without the other pays for both or neither. The
  `cardNumber` filter's `columnKey` now points at `'_card_number'` — the
  identical fix shape as the Consignor filter/column pairing above.
  `useCardImages` and `useCardNumbers` are both thin wrappers over a new
  shared `useBatchedCardLookup<T>` (extracted, not duplicated, from
  `useCardImages`'s pre-existing resolved/pending/failed-id bookkeeping) —
  `useCardImages`'s own public contract (`imageMap`/`getImageUrl`) is
  unchanged, so none of its ~16 existing callers needed to change.

`Set`/`Artist` remain column-less filters on purpose (unlike `cardNumber`) —
neither has a rendered column, so there's nothing for `columnKey` to point
at yet.

## A FETCH-ONCE ADMIN DROPDOWN HOOK CAN LOSE THE SESSION RACE — depend on `isAuthenticated`

Diagnosed 2026-08-15 while chasing why the Consignor filter's dropdown showed
**zero options** even after the fix above made it reachable. Root cause:
`components/providers/SessionProvider.tsx` mounts NextAuth's client
`SessionProvider` with **no initial `session` prop**, so `useSession()`
genuinely starts at `status: 'loading'` on every fresh page load — even on a
route the SERVER already gated behind a valid admin session
(`app/(admin)/layout.tsx`'s own `auth()` call happens server-side and tells
you nothing about the CLIENT `SessionProvider`'s own async timing).

**`useCosigners`, `useLocations`, `useShows`, and `useCatalogSets` all fetched
once on mount with a `useEffect(..., [])`.** If that fetch fires during the
loading window, `admin-api.ts`'s `request()` throws
`AdminApiError(401, 'No access token available')`, the hook's own `.catch()`
swallows it into an empty (or hardcoded-fallback) list — and because the
effect has no dependency to ever re-run on, **it never retries**, for the
rest of that page's life. The `/admin/cosigners` PAGE never showed this
symptom, which is what made it look consignor-specific: its own fetch is a
`useCallback` depending on `api` (from `useAdminApi()`), and `api`'s identity
changes the moment `isAuthenticated` flips — same self-healing pattern
`useCardImages` (`lib/use-card-images.ts`) already used correctly. The four
one-shot hooks had neither the `isAuthenticated` guard nor that dependency.

**Fix: gate the fetch on `api.isAuthenticated` and put it in the effect's
dependency array**, not `[]`. All four hooks now read:

```ts
useEffect(() => {
  if (!api.isAuthenticated) return
  // ...fetch, with the same cancelled-flag cleanup as before
}, [api.isAuthenticated])
```

`api.get` itself stays safe to call from an effect created on an earlier,
unauthenticated render — it reads the current token through a ref at call
time (`admin-api.ts`'s `tokenRef`), not at closure-creation time — so the
only thing that needed fixing was **when** the effect re-fires, not the
request itself. Depending on the boolean rather than the whole `api` object
avoids an incidental refetch on every session poll (`refetchInterval={4 *
60}` on the provider) while still catching the one transition that matters.

**Any new admin dropdown hook that fetches through `useAdminApi()` must use
this pattern from the start** — a hook that "works in testing" (where a mock
session resolves synchronously) can still ship permanently empty on a real
fresh page load. `use-cosigners.test.ts` carries the regression test; the
other three hooks' test files mirror it.

**Missing values sort LAST in both directions**, for every type — not just
money. A column where the blanks bunch at whichever end you are not looking
at is a column people stop clicking.

**Condition sorts by rank, not alphabetically:** NM > LP+ > LP > LP- > MP >
HP > DMG. Alphabetical sorting made `LP+` and `LP-` identical, which is the
exact distinction RFC 0008 T2 stored in two fields.

**An unknown `sort` field or `filter` triple is a 422, never a silent
no-op** — same rule as `triage_reason`. Two spellings of a filter exist (the
legacy named params and the generic `filter=`), but **one evaluator**: the
named params build the same `FieldFilter` objects. Four of them stay
hand-written because they do more than a field comparison — `name` searches
notes, `condition` splits `LP+`, `min_price` falls back to cost, and the
catalog filters join the catalog.

## SORTING IS UNIVERSAL — six backend registries, not one (RFC 0013)

`inventory_sort.py` was the first registry; RFC 0013 T4 gave five more tables
their own — **Shows** (`shows_sort.py`), **Transactions**
(`transactions_sort.py`, the flat archive History reads), **Consignors**
(`consignors_sort.py`), **Locations** (`locations_sort.py`), and **Slabs**
(`slabs_sort.py`) — each built via the shared `services/table_sort.py` factory
so the three invariants above (missing sorts LAST in both directions, an
unknown field is a 422 not a silent no-op, `{field}_{direction}` splits on the
LAST underscore) live in one place instead of six copies. Each registry still
owns its own `SORT_FIELDS`/`SORT_ALIASES` and its own totality test — the
factory shares behavior, never state, across tables.

Two registries sort a **plain `dict`, not a Pydantic model** —
`locations_sort.py` (`GET /admin/locations` returns
`{"value": str, "label": str}` rows) and `slabs_sort.py` (`GET /admin/slabs`
returns `_slab_row()` dicts, not `GradedInventoryItem`s) — which is what makes
`table_sort.SortRegistry` being `Generic[T]` load-bearing rather than
decorative. `slabs_sort.py` also has two fields **stringified in the
response** (`grade`, `cost_basis` — `str(Decimal)`, so a Decimal survives JSON
without becoming a float): their extractors parse back to a number, or
`"9"` would sort after `"10"`. Its `priced` field is not a dict key at
all — it is DERIVED, `market_value is not None`, mirroring the router's own
`?priced=` filter rather than sorting the raw money figure (an unpriced slab
is the ordinary state of a JP slab after the verified-join rule, not a gap to
rank by size).

**A totality test must compare against the REAL response shape, not against
`SORT_FIELDS` itself.** `test_slabs_sort.py`'s first draft asserted
`set(SORT_FIELDS) == {the same fields hand-typed again}` — circular, and
incapable of ever catching a renamed or added dict key. The fix mirrors
`test_locations_sort.py`: a `row()` test helper that mirrors the real
`_slab_row()` key set, checked against `SORT_FIELDS` plus a documented
`NOT_SORTABLE` exclusion set (same shape as `shows_sort.py`'s).

**Frontend rollout, RFC 0013 T4:** every DataTable-backed admin list is now
sortable — Triage, Unmatched, Shows, Locations, Cosigners joined
Inventory/Prep Queue's existing wiring, and Market's watchlist and the Slabs
list (`SlabList`) and Show Analytics' Shows-tab were redesigned from bespoke
markup into sortable `DataTable`s. Show Analytics' Shows-tab sorts by `date`/
`name` (the two `shows_sort.py` fields it renders); the Sold/Bought/Net/Items
columns come from a separate `ShowAnalytics` join that registry does not
cover and stay display-only.

**Vault and Show Prep were deliberately NOT converted to server-side sort.**
Both were suspected to call `/inventory/search` (which would have inherited
`inventory_sort.py` for free) — they do not. `/vault` and
`/show-prep/mispriced` are bespoke, **unpaginated** endpoints (no `limit`)
returning computed fields (`dollar_net`/`percent_net`/`consigned`;
`delta_pct`/`delta_dollar`) that no registry covers. Sorting an endpoint's
FULL, already-fetched response client-side is identical in correctness to
sorting it server-side — the failure mode server-side sort exists to prevent
is a `limit` truncating the page BEFORE the sort runs, and neither endpoint
truncates. Converting them would have meant inventing two more backend
registries outside RFC 0013's five-table scope for zero behavioral gain.
Same reasoning applies to the Market watchlist (`GET /watchlist`, also
unpaginated) — its new DataTable sorts client-side too, via the shared
`lib/client-table-sort.ts` helper (mirrors `table_sort.py`'s missing-last
invariant client-side; `lib/vault-sort.ts` predates it and already matched
that invariant on its own, so it was left as-is rather than merged in).

**History's `TransactionGroups` got a group-level sort control, not a
DataTable header** — sorting must never flatten a group's legs into rows.
The control (Date / Total buttons, `TransactionGroups.tsx`) defaults to
`groupTransactions`'s own "must not reorder the archive" order until clicked.
It lives where `TransactionGroups` actually renders — **Show Analytics'
Daily tab** (`/admin/analytics`), not `/admin/history`, which has no
`TransactionGroups` usage at all and renders its own per-item chronological
timeline instead (reordering THAT would misrepresent a transaction history,
which is the entire reason the page exists).

**Triage** (`/admin/triage`) — the one place to correct data the automation got
wrong. It **is** the `needs_review` queue, not a second flag: "Send to Triage"
sets `needs_review = True`. Two things were added to that bare boolean —
`review_reason` (why; **internal**, deliberately NOT in `_CUSTOMER_ITEM_FIELDS`)
and `reviewed_at` (stamped server-side when an admin clears the flag, so
automation cannot re-flag what a human already passed).

One list, with a chip per reason — items routinely qualify under several at once:

| Reason | Kind | Cleared by |
|---|---|---|
| `flagged` | stored `needs_review` | an admin, explicitly |
| `missing_card_id` | derived: no catalog link | self-healing — re-point the card |
| `missing_english_name` | derived: JP item, no `display_name_override` | self-healing — assign a name |

The list is `GET /admin/inventory/search?triage=true` (the one OR on that
endpoint), **not** a parallel endpoint; `GET /admin/triage/counts` backs the
sidebar badge.

**The SERVER decides why a row is there — never recompute it in the client.**
`services/triage.reasons_for()` is the authority, `needs_triage(i)` is literally
`bool(reasons_for(i))`, and `?triage=true` rows carry `triage_reasons` (plus
`bulk_clearable`) in the response. `frontend/lib/triage.ts`'s `reasonsFor()`
survives **only** as a prediction for optimistic updates before a refetch; its
docstring says so. Filtering is **one** parameter, `triage_reason`, validated
against the predicate set (**422** on an unknown key, never a silent no-op); the
older `needs_review` / `missing_card_id` / `missing_english_name` params still
work but Triage no longer sends them. Scope comes from `in_triage_scope`, which
the list **and** the counts endpoint both call — sold, lost and
returned-to-consignor rows are out unless `include_terminal=true`, and scoping
one of the two without the other is how the badge starts lying.

`POST /admin/inventory/bulk-clear-review` drops machine flags, and it is
deliberately narrow: only items whose **only** reason is `flagged` **and** whose
`review_reason` is in `MACHINE_REVIEW_REASONS` minus **`blank_condition`**. That
exclusion is a money rule — the importer stored `Condition.NM`, the most
expensive tier, for every blank condition, so bulk-clearing those would ratify an
inflated customer price on cards nobody has graded. A human's free-text flag, and
a bare flag with no reason at all, are never touched. "Send to Triage" lives in `CardDetailModal`, so it reaches the
five pages that mount it (inventory, outgoing, show-prep, vault, triage) —
the old separate `/admin/sell` mounted it too, but that page was deleted in
RFC 0011 T16 and the unified `/admin/trade` does not mount it.
The row-level quick action with undo (`TriageRowAction`) is on **Prep Queue
only**. `/admin/trade` (all three modes), Market, History, Cosigners and
`/admin/card/[id]` do not mount the modal and have **no** send-to-triage path
at all — the "every tab" goal is not met yet; see
`docs/plans/rfc-0008/follow-ups.md` (T5 row 1).

`display_name_override` is editable **only from the Triage page**, not from
`CardDetailModal` — the modal's "Display Name" row still edits `display_name`,
the import-materialized fallback, which is a silent no-op on a catalog-matched
item (follow-ups.md, T10 row 3).

**"Send to Vault" (RFC 0022 T7) lives beside Send to Triage in the same
modal, on the same reach** — the five pages above, no new wiring per page.
It PUTs `{status: 'on_hold'}` through the existing
`PUT /admin/inventory/{item_id}` (no new endpoint) and reads **"In Vault"**
once the server confirms `status === 'on_hold'`, offering to return the item
to `available`. Sending TO the vault has no note to type, so — unlike Send
to Triage — it writes directly on click with no inline form. Same undo
affordance (a 5-second-equivalent toast restoring the previous status), and
the button's state is derived from the refetched item, never an optimistic
local flag — the exact rule `writeTriage`'s own comment already states.

## UNIVERSAL ADMIN INLINE EDITING (RFC 0022)

Every value in every admin table is click-to-edit where it makes sense, via
one shared mechanism: `InlineEditCell` (`components/admin/shared/`, 9 input
types — `text|textarea|money|number|date|select|multiselect|checkbox|url`)
rendered by `DataTable` when a `Column<T>` carries an `edit: EditSpec<T>`.
The read-only presentation is byte-identical to before; the affordance is a
hover background + pencil on hover/focus, and the cell stays
keyboard-focusable (Enter opens the editor) because hover may never be the
only route to a control.

**`multiselect` is array-typed on purpose, not a delimiter-joined string** —
`InlineEditCell` takes separate `multiselectValue: string[]` /
`onSaveMultiselect: (v: string[]) => …` props for it, and `EditSpec<T>`
mirrors that split (`multiselectValue`/`saveMultiselect`, alongside the
scalar `value`/`save` every other type uses). Built ahead of any real
consumer in this RFC specifically so RFC 0023's `finish_attributes` column
has a mechanism to use rather than bolting on a second one.

**Undo, not confirmation** (owner decision): `EditSpec.undoLabel`, when set,
shows a 5-second "`‹label›` → `‹new value›` · Undo" toast after a successful
commit; Undo re-issues `save` with the value captured *before* the edit. Set
only on `status`, `cost_basis`, `sticker_price`, `listed_price`, `location`
(consignor reassignment has no inline column yet — see the exclusion note
below). Everything else commits silently. The toast lives inside
`DataTable` itself, not a separate component — it needs the row/column/
previous-value context only the table has.

**A `Column<T>` with `edit` conflicts with `onRowClick` on the SAME
cell** — `InlineEditCell`'s click handler calls `stopPropagation()`, so an
editable cell silently eats a row-level click. Found live on
`/admin/cosigners` (rows are click-to-select; making `name` editable broke
selecting a consignor entirely — reverted) and on the Analytics Shows tab
(kept `date` editable, dropped `name`, which is that tab's click-to-detail
target). **Before adding `edit` to a column on a page with `onRowClick`,
check whether that column is the actual click target for row navigation** —
DataTable-level tests cannot catch this because they don't exercise both
features on one cell at once.

**`INVENTORY_COLUMNS` (`lib/admin-inventory-columns.tsx`) is the reference
registry and the only one with a totality test today**
(`lib/__tests__/admin-inventory-columns.test.ts`): every column carries
either `edit` or a `notEditable` reason string ≥10 characters, never both —
the length check is the point, mirroring the `admin-tool-contract.json`
lesson elsewhere in this file where a parity test diffed key sets while
every value was an empty stub. **Only `card_id` and consignment/
`consignor_name` are excluded by owner decision** ("everything except
card_id and consignment"); every other exclusion (`current_market_value`,
identity/audit fields, derived columns) has its own stated reason.
`/admin/shows`, `/admin/cosigners`, `SlabList` gained real inline editing
too but **not yet a formal registry + totality test of their own** — a
known, deliberate gap (not an oversight), left as a follow-up.

**`SlabList` gotcha, same one `slabs_sort.py` already documents:** `grade`
and `cost_basis` are `str(Decimal)` on the wire. The component has no
`api`/side-effect capability of its own — it takes an optional
`onEditField(row, field, value)` prop, and the PARENT PAGE
(`/admin/slabs`) is what parses the string back to a JSON number before the
PUT, never re-sending the display string and never a bare Python float.

**The one rule that must not be broken:** assigning an English display name
writes `display_name_override` and **never** `card_id`. Re-pointing a card is a
separate, confirmed action with a before/after diff and warnings for trade
lineage and cross-language links.

**Unmatched** (`/admin/unmatched`) — the queue for cards the catalog does not
have. RFC 0011. It exists because **`missing_card_id` is a DERIVED triage
reason**, so before this an unmatchable card sat in Triage forever and the
queue that is meant to reach zero had a floor it could never get under.

**`no_catalog_match` is the stored fact, and `services/triage.is_missing_card_id`
is the only place that reads it.** The list and the sidebar badge both route
through that one function; adding the check anywhere else is how they start
disagreeing.

**The invariant: `no_catalog_match=True` implies `card_id is None`**, enforced
by a model validator. Setting it on a linked item is a 422; assigning a
`card_id` clears it automatically, because requiring a second write to leave a
queue is how rows get stranded in one.

**Nothing was backfilled and nothing auto-migrates** — owner requirement,
2026-08-13: *"all cards that go there should only be moved under admin
supervision."* There is a permanent test asserting the queue is empty on an
untouched table. Do not write a migration for this later.

**Unlinking clears `current_market_value`.** The card was pointed at a
close-but-wrong promo, so the figure it inherited is that promo's price and no
sync will ever correct it once the link is gone. A parked card is hand-valued
and carries `HandValuedBadge`.

A parked item that is **also** flagged or unnamed stays in Triage with its
remaining chips. Parking answers one question; those are different, real
errors.

**Slabs** (`/admin/slabs`, sidebar position: **last in "At the show", after
Trade**) — graded intake and the slab list, from RFC 0009. Intake is one cert
field serving both a keyboard-wedge scanner and the keyboard, a
catalog-autocomplete card picker with a free-text fallback, a client-side staging
batch, then a commit that runs the ordinary buy session's create → items →
confirm. `GET /admin/slabs/certs/{cert}` warns on a cert already owned — a
**warning with override**, never a gate, because a slab sold and bought back is a
legitimate re-entry. `/admin/slabs?priced=false` is the unpriced worklist. The
per-grade pricing behind it is documented under "Third-Party APIs" below.

**Sold/lost/returned_to_consignor slabs are hidden by default, 2026-08-15.**
Owner report: *"sold cards are not being automatically removed from our slab
inventory."* Root cause was never the data — `sales.py` correctly flips
`status` to `SOLD` — it was that `GET /admin/slabs` intentionally never
filters by status unless asked
(`test_status_narrows_the_list_and_nothing_is_hidden_by_default`,
`backend/tests/routers/admin/test_slabs.py` — a sold slab is still real
purchase history, so the endpoint keeps it), and
the page never gave the admin any way to ask. Fixed **client-side only**: the
page already fetches every status (no `status` param is ever sent), so a
"Show sold / gone" checkbox — unchecked by default — filters `sold`, `lost`
and `returned_to_consignor` out of what "Slabs on the shelf (N)" counts and
renders, with no refetch on toggle. `on_hold` and `out_for_grading` stay
visible either way: the slab is still owned and still accounted for. Same
"hidden by default, visible on request" shape as the archiving pattern
below — the backend's "nothing hidden" contract is unchanged and still
correct for what it is (an archive), the gap was a missing view on top of it.

**The intake toolbar has ONE button: "Manual entry".** It is a disclosure — the
form is **put away by default**, like the other admin tabs, and stays open across
adds because intake is a batch workflow. RFC 0010 T12 deleted the other three.
"Camera scan" and "Auto-fill from cert" went because PSA's cert API became a
**paid** feature the owner declined, so the gap they marked is now permanent and
a disabled button implies a roadmap that does not exist. "Scan cert" went for a
different reason, and it is the one that matters:

> **A wedge scanner is just a fast keyboard, so the ordinary cert field already
> IS the scan target.** That is true **only** while `CertInput`
> (`frontend/components/admin/slabs/CertInput.tsx`) keeps two things: `onEnter`
> **advances** focus rather than submitting (the scanner's trailing Enter arrives
> long before card, grade and cost are filled), and the input strips the
> scanner's trailing `\r\n` on the way in (`replace(/[\r\n]/g, '')`). **Delete
> either and wedge scanning breaks while hand-typing keeps working** — an
> invisible failure nobody finds until they are standing at a table with a
> scanner. There is deliberately **no timing logic**: a cert typed slowly over
> ten seconds is exactly as valid as one scanned in 40 ms.

**A slab is priced AFTER the commit, never inside its loop.** The commit returns
`item_ids` and the page then fires `POST /admin/slabs/refresh-prices` scoped to
them, un-awaited, on its own status line — a metered third-party HTTP call inside
the write loop would rebuild the partial-write bug T0 fixed, on the same money
path. The commit's success message is set *before* that call, so it lands first
and unconditionally; a pricing failure must never reach the commit's `catch`,
which says "Nothing was created". **An unmatched (free-text) slab is unpriceable
by construction** — pricing needs a verified `card_id` join — so it commits, says
so, and appears under `?priced=false`.

`SlabEntryForm` takes cost through `MoneyInput`, so `1,300` stages as
`$1,300.00` (see "Money input" below) — and `StagedSlab.buy_price` is a
**number**, not a string.

The page uses the **vault design system** (`vault-panel`, `vault-field`,
`text-pine-*`, `bg-mint/15`) like every other admin tab. It previously used none
of it, which is why its dropdowns rendered light-green-on-white: the admin theme
is dark (`.vault-scope`, `#06150b`) with light-green text, so an unstyled
`<select>` inherited the theme's text colour over the browser's default white
background. **Never ship an admin control without `vault-field`.**

Two gaps remain live and deliberate — **no per-row editing in the staging table**
(so its commit gating is unbuilt on purpose) and **no pin control**. Full list:
`docs/plans/rfc-0009/follow-ups.md`.

**Buy / Sell / Trade** (`/admin/trade?mode=buy|sell|trade`) — one surface,
three modes. RFC 0011 Part 2. `/admin/buy` and `/admin/sell` were **removed**,
not redirected (owner decision 10). That departs from the `/admin/outgoing`
precedent recorded above, and the distinction is real: that precedent covers
*renaming a page that still exists*, while these two genuinely stopped
existing.

**`mode` lives in the query string**, which is what lets one route serve the
dashboard's three quick actions and keeps the toggle bookmarkable.

**`lib/deal-session.ts` is the ONLY place that knows which API a mode
drives.** `purchases.py`, `sales.py` and `trades.py` stay separate (decision
16) because they are the highest-risk money paths in the repo. A
`if (mode === 'buy')` at a call site is three code paths coming back in
disguise.

**Switching mode with a non-empty session confirms first.** A session
belongs to one API and there is no migration between them.

**`POST /admin/trades/{id}/confirm` and `POST /admin/purchases/{id}/confirm`
now return `item_ids` in the response** (RFC 0012), the same shape the Slabs
commit has always returned — it is what lets a post-confirm step (e.g. linking
a staged consignor) target the exact items a deal just created without a
second lookup.

**A slab can now come IN through a trade.** Trading one OUT always worked —
outgoing legs reference an existing `item_id` and never inspect `kind`.
Incoming was hardcoded to `kind: "raw"`, so a PSA 10 arrived as a raw NM card
with its cert gone. Graded pricing joins on `(card_id, company, grade)`, so a
graded leg with no `card_id` is unpriceable by construction — but as of RFC
0012, that no longer makes it a rejected leg. **A manually entered graded item
is now accepted**, the same backend 422 and frontend raw-only gate that used to
enforce "manual entry can only ever be raw" were both removed, and the item
lands unpriceable and self-routes to Triage via the existing
`services/triage.is_missing_card_id` check — the same path an unmatched slab
already takes.

**Condition and grade are never rendered together.** They are alternatives,
and the backend 422s a raw leg carrying graded fields.

**A trade's incoming cost basis is fully automatic — no mode, no manual
entry.** `_compute_basis_pool` (`routers/admin/trades.py`) is always
`outgoing legs' cost basis + cash we pay − cash they pay`, floored at zero,
then allocated pro-rata across incoming legs exactly as before. This
retired an earlier three-mode system (Transfer/Split/Manual) that required
a human to type a basis whenever cash was part of the trade — the owner
reviewed the pre-mode history (visible in old test comments) and asked for
the automatic version back, deliberately, with no exceptions for cash. The
`GET /admin/trades/{id}/balance` preview uses the identical function, so
the number an operator sees before confirming always matches what gets
stored. The already-separately-retired `margin_split` field stays storable
via `PATCH /admin/trades/{id}` (unrelated tests cover that) but has no
effect on the pool; `basis_mode`/`manual_basis` are no longer accepted
fields at all — sending them is a silent no-op, not a 422, matching how any
other unlisted key on that endpoint is already treated.

**The displayed trade `balance` NETS cash against the card totals — it does
not add them.** Diagnosed 2026-08-14 (RFC 0013): a $125-in / $1025-out /
$900-cash-received trade — genuinely settled at $0 — displayed as **+$1800**,
because the frontend's own formula was `outgoingTotal - incomingTotal +
cashNet` where it needed to be `- cashNet` (`cashNet` is already signed
positive when the counterparty pays cash to us, so adding it double-counted
the cash leg). The backend's own independent implementation of the same
figure (`routers/admin/trades.py`, `total_out - total_in - cash_delta`) was
correct the whole time — the frontend recomputes this as a live display value
rather than calling that endpoint, and the two had drifted. The confirmed
transaction legs themselves were never wrong (computed straight from each
cash component's direction/amount, not from this display figure); the risk
was purely operational — an operator trusting a wrong on-screen balance might
"correct" an already-balanced trade's cash entry to force the display to
zero, which would make the real trade wrong.

**Shows** (`/admin/shows`) — CRUD for show/event days. Note this is a
*different page* from Show Prep (`/admin/show-prep`, which moves inventory into
show boxes) and from Show Analytics' Shows tab (`/admin/analytics`, which reads
per-show numbers). Routes live in `routers/admin/analytics.py`, not a new
module: `GET/POST /admin/shows`, `PUT /admin/shows/{id}`,
`POST /admin/shows/{id}/archive` and `/unarchive`.

**"Delete" is an archive, by owner decision** (RFC 0008 Q6). `Show.archived`
is a boolean; nothing is ever destroyed, so there is no repo-level show delete
and **no 409 in-use guard** — a show with transactions behind it archives like
any other, and its analytics snapshot never dangles. `GET /admin/shows` hides
archived shows unless `?include_archived=true`; `repo.list_shows()` and
`repo.get_show()` stay archive-agnostic so `/shows/{id}/analytics` keeps
resolving for an archived show.

## ARCHIVING IS ONE PATTERN — every archivable entity behaves identically

Owner rule, 2026-08-10: *"if there are other things that get archived, they
should be the same… Archived entities are hidden by default but can be viewed in
case they need to be pulled back or referenced."*

**`/admin/shows` is the reference implementation. Copy it; do not reinvent it.**
The contract, all six parts:

1. a boolean `archived` field on the model (never a status enum value, never a
   second "active" flag meaning the inverse);
2. `DELETE`/archive sets it — **nothing is ever destroyed**, and there is **no
   409 in-use guard**, because nothing dangles when nothing is removed;
3. an `unarchive` route, because archiving that cannot be undone is just a
   slower delete;
4. the list endpoint **hides archived rows unless `?include_archived=true`**;
5. the UI has a **"Show archived"** toggle, and while it is on the archived rows
   are visibly marked (`Archived` badge + dimmed) rather than silently mixed in;
6. the confirm dialog says *archive*, and says what is preserved — see
   `frontend/app/(admin)/admin/shows/page.tsx:264-274, 416` for the exact
   wording to mirror.

**An `Archived` badge never reuses inventory-status vocabulary.** Rendering an
archived *person* or *event* as `SOLD` is the bug this rule exists to prevent —
it shipped on `/admin/cosigners`, which showed a deactivated consignor as
"SOLD", and RFC 0010 T2 fixed it. `StatusBadge` now carries two entity-lifecycle
styles, **`active`** and **`archived`**; pass those for a person or an event and
never `available`/`sold`.

Entities on this pattern: **`Show`**, **`Consignor`** (RFC 0010 T2). Entities
deliberately NOT on it: **`Location`**, which hard-deletes behind a 409 in-use
guard because a location is a label with no history of its own. `DELETE
/admin/inventory/{item_id}` is a third thing again — its soft mode sets
`ItemStatus.LOST`, a real lifecycle state rather than an archive flag; see
`docs/plans/rfc-0010/follow-ups.md` before treating it as one.

**`put_show` gotcha:** the SK embeds the show DATE and, during an import, the
generation. Both move underneath an ordinary admin edit, so `put_show` now
sweeps superseded rows for the same `show_id` after writing — otherwise
rescheduling a show, or editing any import-created show, forks it into two
rows. The sweep is skipped mid-import, where coexisting generations are the
whole point of load-then-swap.

**A show's analytics snapshot auto-generates on archive (RFC 0013).** Before
this, `ShowAnalyticsSnapshot` was written only by the manual "Generate"
button, so every un-generated show's Shows-tab row read 0 — the archive
route now calls `generate_show_analytics` itself. Generation failure is
**caught and logged, never surfaced as an archive failure**: archiving is
the real state change and must not roll back over a reporting side-effect.
The manual button still works, for re-generating a stale snapshot (see
`ShowAnalyticsSnapshot.stale` below) or one from before this shipped —
**nothing was backfilled automatically**, on the same "admin supervision
only" precedent as Unmatched; `scripts/backfill_show_analytics.py` (dry-run
by default) is the one-time catch-up for shows archived before this landed.

**Show Analytics** (`/admin/analytics`) — tabbed `Daily` / `Shows` view. Daily
tab shows a single day's dashboard (`GET /analytics/daily`); Shows tab lists
the show archive (`GET /admin/shows`) with a detail drill-in per show, now as
a sortable `DataTable` (RFC 0013 T4e — see "SORTING IS UNIVERSAL" above).

**History** (`/admin/history`) — searches an item's full transaction timeline
and trade lineage. Shows `step_profit` per lineage hop (color-coded, guarded
against a $0 cost-basis overstating profit on consigned items) and a rolled-up
"Chain Profit" summary when a chain has more than one hop; lineage nodes are
clickable to navigate the chain.

## THE LEDGER HAS A CORRECTION PATH — a VOID, never a delete

RFC 0010 T11. A mistaken sale used to be uncorrectable. It is now voidable, and
**void is the only shape allowed**: a deleted sale leaves no trace it existed and
silently disagrees with every analytics snapshot already generated. Same
precedent as archiving a show.

**ONE countability predicate: `services/ledger.is_countable`, and every
aggregate calls it.** `countable(rows)` is the sugar over it that readers
actually use, so nobody can spell the filter differently. Its module docstring
lists every reader exhaustively, and each has a named test.

> **Never let an aggregate inline its own `txn.voided_at is None` check.** That
> is a second definition of countability, and the failure mode is two sets of
> books disagreeing by exactly one sale — which nobody notices until a month-end
> number is wrong.

**Two readers deliberately do NOT filter, and say so at the call site:**
`GET /admin/transactions` (the archive) and the item timeline. The point of an
archive is to show what was actually written, and a void is a thing that was
written. A voided row renders struck through, with its reason. **Do not "fix"
them into filtering** — that is how the archive stops being one.

**SALES ONLY.** `POST /admin/transactions/{id}/void` refuses a **purchase** with
a `400`, and the UI does not offer the action there rather than offering one that
always fails. A **trade cannot be voided at all**, because its legs share a
`batch_id` and one of them is a purchase. Consequence, recorded because it is
real: **a mistaken buy still has no correction path.** Voiding a purchase means
removing an item that may since have been sold, traded, re-priced or consigned,
and a void that leaves a phantom item in stock is worse than no void at all.

Four routes, not two — `/transactions/{id}/void|restore` and
`/transactions/batch/{batch_id}/void|restore`. The batch pair exists because a
five-card sale must void as one action: `reverse_sales` issues **one**
`transact_write_items` for every leg and guards every leg before writing
anything, so a batch containing one card that has moved on since voids nothing at
all. Five separate POSTs could half-succeed, which is the partial-write class T0
was created to eliminate. **A batch over 50 legs is refused with a 422** telling
the operator to void one at a time — DynamoDB caps a transaction at 100 actions
and a reversal spends two per leg, and chunking would silently reintroduce
partial write.

`Transaction` gains `voided_at` / `voided_by` / `void_reason`, and
`ShowAnalyticsSnapshot` gains `stale` (rendered on `/admin/analytics`, because a
flag no page shows is a silent serve). `voided_by` stores `email or username or
sub` — one value with a fallback chain, never client-supplied.

**`attribute_not_exists(voided_at)` is NOT the "not voided yet" guard.**
`put_transaction` writes every model field including the `None`s, so a row
carries `voided_at` as a DynamoDB **NULL, which exists**. The guard is
`attribute_not_exists(voided_at) OR attribute_type(voided_at, "NULL")`; the
restore side checks `attribute_type(voided_at, "S")`.

**One timeline event per transaction, keyed `<txn_id>#void`**, re-put as
`void_restored` on restore rather than appended. The original sale event is keyed
`TIMELINE#<date>#<txn_id>`, so a void on the same day — the common case — would
otherwise **overwrite the sale itself**.

**`Transaction.batch_id`** (T10) is what makes a five-card buy read as one line.
It is optional, defaults to `None`, and **nothing is backfilled** — a null-batch
row groups on its own `txn_id`, one code path with no legacy branch. No
`(date, payment_method, type)` heuristic is allowed: two separate cash sales on
one show day are indistinguishable from one two-card sale, and inventing
transactions is not acceptable in the one view where being wrong costs money.
Grouping is **client-side** in `TransactionGroups`, which replaces `DataTable` on
that table only. A mixed-direction group (a trade) renders a **net** total —
summing magnitudes would report a $50-for-$30 trade as `$80`, a number that
exists nowhere.

## A TYPO IN THE LEDGER GETS A DIFFERENT TOOL THAN "THIS DID NOT HAPPEN" — EDIT, NOT VOID

RFC 0024 T3/T4. Void says *"this sale did not happen."* It is the wrong tool
for *"this sale happened, I typed $150 instead of $105"* — voiding and
re-entering loses the original date, breaks the `batch_id` grouping, breaks
the item's timeline continuity, and leaves a struck-through phantom in the
archive that misrepresents what occurred.

`PATCH /admin/transactions/{txn_id}` accepts any subset of `amount`, `date`,
`payment_method`, `fee`, `show_id`, `notes`. **Never `item_id`, `type` or
`category`** — re-pointing a leg rewrites two items' histories from one edit;
the correct expression of "this was the wrong card" is a void plus a fresh
entry, unchanged by this feature. Refusals: a **voided** transaction is `409`
(restore first — editing a row that counts toward nothing is incoherent); a
**trade leg** is `400`, for the same reason a trade cannot be voided at all —
`_compute_basis_pool` allocated the incoming cost basis pro-rata across every
leg at confirm time, so a single-leg amount edit would leave that allocation
inconsistent with its own inputs, and re-running it would rewrite cost bases
on items that may since have moved on. **A mistaken trade still has no
correction path** — the exact same recorded limitation the void feature
already states for a mistaken purchase. An unknown `txn_id` is `404`; a
disallowed field or an unreadable value is `422`.

**A date change moves the row between DynamoDB month partitions in ONE
`transact_write_items`, never two calls** — the SK embeds the date
(`PK = TXN#<YYYY-MM>`, `SK = <ISO date>#<txn_id>`), so a half-applied move
would duplicate or destroy the ledger row, the exact partial-write class
`reverse_sales` already exists to prevent. Same date stays a plain
`put_transaction`, which whole-item `put_item`s and so correctly drops the
GSI2 show attributes when `show_id` is cleared.

**`cost_basis` follows a corrected PURCHASE amount, guarded on equality with
the OLD amount.** If the item's current `cost_basis` no longer equals what
the ledger said before the edit, the sync is skipped and
`cost_basis_skipped_reason` explains why (`"cost basis was changed manually
since"`, or `"item not found"`) — never a silent overwrite of a hand
correction, and never a silent skip either. **RFC 0022 made this the COMMON
case, not a rare one**: once `cost_basis` is inline-editable on six admin
tables, an admin correcting the item directly is routine, and every such
correction breaks the equality the guard checks. `cost_basis_skipped_reason`
is rendered as plain information in `TransactionEditDialog` (`role="status"`,
not an error), the same way this file's Universal Inline Editing section
already documents. Sales never touch `cost_basis` — a sale's `amount` is
revenue, not an acquisition cost.

Three new `Transaction` fields, mirroring the void feature's shape exactly:
`edited_at`, `edited_by` (**server-stamped** from `email or username or sub`,
never client-supplied — same rule as `voided_by`), `edit_history` (a
`TransactionEdit` per EDIT, not per changed field — a six-field correction is
one thing that happened, capped at 20 entries for the same 400 KB item-size
reason `review_reason`/`void_reason` are bounded). **One timeline event per
transaction, keyed `<txn_id>#edit`, re-put rather than appended** — the sale's
own event is `TIMELINE#<date>#<txn_id>`, so a same-day edit would otherwise
overwrite it, identical to how a same-day void is keyed `#void`.
`ShowAnalyticsSnapshot.stale` is marked for both the OLD and NEW show/date,
reusing void's own marking function twice rather than a second resolver.
**`services/ledger.is_countable` is untouched** — an edited transaction still
counts toward everything it counted toward before; there is no
`edited_at is None` check anywhere, on the same "one countability definition"
rule the void section above already states.

The UI is a **dialog** (`TransactionEditDialog`, opened from a per-leg Edit
button in `SaleDetailModal`, beside the existing Void/Restore), not an RFC
0022 inline cell — an amount edit here has a side effect on another entity,
can move a row between DynamoDB partitions, and marks a report stale, which
needs a surface that can show `cost_basis_skipped_reason` on the way back. It
sends only the fields that actually changed from the leg's own current value,
never the whole form.

## THE ACQUISITION RATIO — market at purchase over what we paid, one authority per side

RFC 0024 T1. The owner's *"market @ purchase / amount paid"* — pay $32 for a
card the market said was worth $100 and the ratio is 312%. Two
implementations, deliberately, in the same shape as `itemTitle` /
`adminItemName` / `admin_item_name` / MCP's `toCard`: `acquisition_ratio`
(`backend/src/merlins_collection/services/acquisition.py`) and
`acquisitionRatio` (`frontend/lib/acquisition.ts`), pinned together by a
shared cross-boundary fixture
(`shared/test-fixtures/acquisition-ratio-cases.json`) rather than by trust —
`mcp-server/src/condition-pricing.ts`'s unchecked cross-language parity claim
is the cautionary precedent this test exists to not repeat.

**`None`/`null` when either figure is absent, or when the cost basis is
zero** — a free card (a throw-in, a bulk lot) is routine at a buy table, and
its ratio is undefined, not infinite and not zero. Every caller renders an
em dash, never a guessed number. Tone bands, defined once in `ratioTone()`:
≥200% good, 100–200% neutral, <100% bad (paid over market), `null` → no chip
at all, never a grey zero.

**Never stored** — it is derived from `market_value_at_purchase` and
`cost_basis`, both already on `InventoryItem`, and would go stale the moment
either changes, including from the transaction-edit `cost_basis` sync
directly above. Rendered on every deal row (`DealCardRow`'s third line,
`Market $100.00 · Paid $32.00 · 312%`) and in the richer transaction detail
`POST /admin/inventory/items-brief` now returns.

**Customer view hides the ratio AND `Paid`; `Market` stays visible.** Price
paid is our cost basis, and showing a customer that we paid $32 for the card
we're trading them at $100 is strictly worse than showing them the margin
percentage — the owner's instruction to hide "percent" is read as "hide what
tells them our margin." `customerView` is the same page-state prop already
threaded through `DealSummary`, now also threaded into `DealSearchPanel`,
`DealStagedColumn` and `DealCardRow` by the same name. **The suppression
happens at RENDER time, not at stage time** — `DealStagedColumn` strips
`pricePaid` and forces `showRatio={false}` only while the toggle is on, while
the staged row's OWN state always keeps the real values, because the
operator can flip Customer View after cards are already staged.

**Cosigners** (`/admin/cosigners`) — CRUD + payout-link tool for consignors;
card assignment is still raw item-ID entry (no picker UI, deliberately out of
scope) on this page specifically. RFC 0012 added assign/unassign elsewhere
too: `CardDetailModal.tsx` (a per-item panel calling
`POST /admin/cosigners/{id}/link` and `DELETE .../assets/{item_id}` directly)
and, on the incoming side of Buy/Trade, `IncomingCardForm.tsx` via
`CosignorPicker` — both share the same `split_percent` convention as this
page's link form (typed as a percent, divided by 100 before the request).
"Delete" is an **archive** on the six-part contract above, and
`Consignor.archived` **replaced `Consignor.active`** in RFC 0010 T2 — a
`model_validator(mode="before")` reads a legacy stored `active: False` as
`archived: True`, because the owner had already soft-deleted one. There is no
writable `active` field any more; an `active` key on an inbound payload is
migrated, not rejected.

**Editing a consignor used to FORK the row**, exactly as editing a show once
did: `put_consignor` generation-scopes its SK, so an import-written consignor
lives at `CONSIGNOR#<id>#<gen>` while an admin edit (no generation) writes
`CONSIGNOR#<id>`. It now sweeps superseded rows after writing, on the same rules
as `put_show` — **write first, then delete**, and **never sweep mid-import**.
`scripts/reconcile_consignors.py` collapses the forks that already exist (dry
run by default, `--execute --confirm-table`); it keeps the **unsuffixed** row,
which is the admin's edit and the newest, falling back to the highest generation
only when no admin edit exists. `put_payout` and `put_debt` share the shape and
are **not** fixed — no UI can trigger them yet; see
`docs/plans/rfc-0010/follow-ups.md`.

Consignor names carry a **409 duplicate guard** (case- and
whitespace-insensitive, scoped to *another* consignor, and an archived consignor
still collides — otherwise unarchiving resurrects a duplicate).

## MONEY INPUT — one parser, and `parseFloat` is banned

RFC 0010 T0/T1. Every admin money field goes through `MoneyInput`
(`frontend/components/admin/shared/MoneyInput.tsx`) or `InlineEditCell`'s
`type="money"`, both backed by **`parseMoney`** in `frontend/lib/money.ts`. The
owner types `1,300`; that has to be accepted.

> **Never use `parseFloat` on money.** Measured: `parseFloat("1,300")` is **1**,
> `parseFloat("1,300.50")` is **1**, and **neither is `NaN`** — so it sails
> through every `isNaN` guard in the codebase and converts a loud 500 into a
> silent $1,299 loss. A wrong number that passes validation is strictly worse
> than a crash.

> **Never put `type="number"` on a money field.** A native number input does not
> accept a comma, so it makes the owner's input un-typeable rather than correct
> — it satisfies the machine and fails the person. Rejecting negatives is
> `parseMoney`'s job, not `min="0"`'s.

Two more rules that are easy to get wrong:

- **`parseMoney('0')` is `0`, not `null`.** Test `=== null`, never falsiness —
  `!parseMoney(cost)` rejects a legitimately free card, which is a real thing at
  a buy table (a throw-in, a bulk lot).
- **The wire format did not change.** Where a string went, `String(parsed)` still
  goes (`sticker_price`, `manual_basis`, `minimum_price`); Buy and Trade already
  sent JSON numbers and still do. `MONEY_PARSE_MESSAGE` lives in `lib/money.ts`
  so the surfaces that render it cannot drift. Percent fields are deliberately
  untouched.

`formatMoney` (`1300` → `$1,300.00`) groups by hand rather than through
`toLocaleString`, so output does not depend on which ICU data the runtime shipped
with.

## DATES — `frontend/lib/dates.ts`, and never `new Date()` on a date-only string

RFC 0010 T8. If a date is rendered or defaulted anywhere, it goes through
`lib/dates.ts`: `formatISODate`, `parseISODateLocal`, `todayLocal`,
`toLocalISODate`, `formatTimestamp`.

> **Never pass a date-only string to `new Date()`.** `new Date('2026-08-10')`
> parses as **UTC midnight**, so it renders as **Aug 9** in every US timezone —
> every admin date read a day early.

> **Never derive "today" with `toISOString()`.** Both `.split('T')[0]` and
> `.slice(0, 10)` give the **UTC** date, so after 5pm Pacific every new
> transaction defaulted to **tomorrow** — on Buy, Sell, Trade and the dashboard.
> The business sells at evening shows, which is exactly when it was wrong. Use
> `todayLocal()`.

Local zone first, `America/Los_Angeles` (`BUSINESS_TIME_ZONE`) as the fallback —
an **IANA name, never a fixed `-08:00`**: Pacific is PDT (−7) in August and PST
(−8) in January, so a hardcoded offset is wrong from March to November. For
date-only values no zone is involved at all once you stop routing them through
`new Date()`.

**Tests that render a date must pin a negative-offset TZ** via
`frontend/lib/__tests__/_timezone.ts` — a non-test file inside `__tests__` so
vitest does not collect it and `next build` does not typecheck it. Use
`vi.useFakeTimers({ toFake: ['Date'] })`, never the default: full fake timers
deadlock `waitFor`. `mcp-server/` has no date helper and needs none — it returns
ISO strings and never formats a calendar date.

## THE CUSTOMER PRICE IS THE STICKER — CONDITION ADJUSTMENT NO LONGER APPLIES TO IT (RFC 0025)

**Superseded 2026-09-03.** Until RFC 0025, the customer price was a **Near
Mint catalog figure, condition-adjusted at read time** — see the "history"
subsection below for what that meant and why it existed; none of it is
current behaviour any more, and nothing below the line describes the live
system.

**The customer price is now `sticker_price`, full stop, and a card with none
is not shown at all.** `sticker_price` is what the business actually sells
the card for — an admin typed it by hand, holding the card and its
condition. The owner's framing: *"sticker price is essentially the price we
sell the cards at."* A live catalog estimate is not that, and scaling it by
condition doesn't make it that either.

`services/customer_visibility.py::is_customer_visible` — the ONE per-item
predicate behind `customer_visible_items` (filter search, the authed
dashboard summary), `routers/public.py` (the anonymous featured endpoint),
and `services/bedrock.py` (chat hydration, both the customer AND — since
`_hydrate_item` is one shared hydrator by design — the admin analyst
surfaces) — now requires `item.sticker_price is not None`. **A stickerless
card in the vault is a routine state, not an edge case**: `/admin/outgoing`
(Prep Queue) exists specifically to find unstickered available inventory.
Measured against the live table 2026-09-03 before this shipped: 247
customer-visible items, 232 stickered (93.9%), 15 not — reported to the
owner per the RFC's own gate, and the decision to hide the 15 stood.

`_display_price` (`routers/inventory.py`) — the single authority for the
price **filter** and the price **sort** — is now `return item.sticker_price`.
**No fallback**: `is_customer_visible` already guarantees a visible item has
one, so `None` there means a caller is holding an item it should never have
had. `hidden_no_price` is consequently **structurally always `0`** — kept in
the response and the counting code stays live, as a tripwire (a test asserts
the zero) rather than a deletion for a false economy.

**The tile itself gained the field one round later — RFC 0025 follow-ups #7,
closed at Round 9 closeout (2026-09-03).** The RFC shipped `_display_price` as
the filter/sort authority but never added `sticker_price` to
`_CUSTOMER_ITEM_FIELDS`, so the actual price text a customer read on a card
tile was still `frontend/lib/inventory.ts::toPresentedCard`'s pre-RFC
computation (`item.card?.market_price ?? item.listed_price`) — a customer
could filter or sort by the sticker and see a different number rendered.
`sticker_price` now joins the allowlist (additive; nothing else moved) and
`toPresentedCard` reads it directly, so the tile can no longer disagree with
what it was just filtered/sorted by. The chat-mode path needed no change:
`services/bedrock.py::_hydrate_item` already set `listed_price =
item.sticker_price` under the original T2 task, so only the filter-mode
search tile had drifted.

**Condition adjustment does NOT apply to a sticker price**, and this is the
subtle, easy-to-get-backwards part: `apply_condition_adjustment` exists
because a *catalog* figure is a Near Mint price and needs scaling down for a
worse-condition card. A sticker is not a catalog figure — a human already
priced the specific card in the specific condition they were holding.
Applying the multiplier to it would be the identical double-application
error this file already warned about for `current_market_value`
("the nightly denormalizer already baked the multiplier in — adjusting that
would apply it twice"), just arriving through a different field.
`_condition_adjust`/`apply_condition_adjustment` were removed from
`routers/inventory.py`'s customer enrichment path and from
`services/bedrock.py`'s `_hydrate_item` entirely — **`apply_condition_adjustment`
itself is not deleted and must not be**: `catalog_sync.refresh_inventory_market_values`
still bakes it into the stored `current_market_value`, `routers/admin/inventory.py`
still uses it for admin-facing figures, and `mcp-server/src/condition-pricing.ts`
still backs the MCP admin path. Its authority over *market* estimates is
unchanged; it simply no longer decides what a customer is charged.

**MCP mirrors this with a SPLIT, not a collapse.** `Card.value` (the
customer-visible "what we sell it for" figure `search_inventory`/
`calculate_inventory_value`/chat quote) reads `sticker_price` only, same as
`_display_price`. `Card.marketPrice` **keeps its old computation
unchanged** (live catalog price, condition-adjusted, denormalized/graded/
listed fallbacks) — it is a genuinely different, still-needed figure:
`flag_underpriced_cards` compares `value` against `marketPrice` to find
stock priced below a condition-adjusted market estimate, and collapsing the
two into one number would make every card look correctly priced by
definition. Before this RFC the two fields happened to share one
computation; that was incidental, not a rule to preserve.

<details>
<summary>History — the pre-RFC-0025 mechanism (for context only, not current behaviour)</summary>

Customer prices used to be CONDITION-ADJUSTED. The catalog relays one market
figure per finish and that figure is a **Near Mint** price. Every
customer-facing surface scaled it by the item's condition
(`services/condition_pricing.py` — LP ×0.82, MP ×0.58, HP ×0.33, DMG ×0.15,
`+`/`-` take the midpoint with the neighbouring tier). Before THAT change, a
DMG card was shown to a buyer at ~6.7× what the business valued it at, wrong
in the business's favour. Measured on live stock 2026-08-06: this moved the
customer-visible total from $6,143 to $5,005 (−18.5%) across 73 of 228 items.

The adjustment used to be applied in exactly one place per surface:
`_condition_adjust` in `routers/inventory.py` rewrote `summary.market_price`
at enrichment, so the tile, the sort and the price bound all inherited the
same number (RFC 0008 T1's single-authority invariant, at the time). MCP
mirrored it via `mcp-server/src/condition-pricing.ts`. **All of this is
retired for the customer price path** — see above for what replaced it.
</details>

**Name resolution: `display_name_override` wins EVERYWHERE.** One rule, four
implementations, kept deliberately in sync — `itemTitle`
(`frontend/lib/inventory.ts`, customer tiles), `adminItemName`
(`frontend/lib/admin-item-name.ts`, every admin list), `admin_item_name`
(`backend/services/card_text.py`, admin API responses) and MCP's `toCard`
(chat). Never inline `display_name || product_name` in new code; call the
helper. `CardDetailModal` shows **both** name fields, since editing
`display_name` on a catalog-matched item is a silent no-op.

## A CARD IS NEVER IDENTIFIED BY NAME ALONE — a card search MUST show image AND price

**Owner rule, 2026-08-10, and it is absolute:** *"when searching for a card, name
alone is not sufficient, it needs to have an image"* — extended the same day:
*"I also want prices displayed as well."*

**Three fields, always: name, image, price.** This applies to **every** surface
where a human picks a card out of a list of candidates — catalog autocompletes,
repair-tool pickers, watchlist add, search results, anywhere a set of cards is
offered and one must be chosen. The image answers *"is this the card?"*; the price
answers *"what do I do about it?"*, which at a buy table is the only question that
matters. A picker missing either field is incomplete.

Why it is a rule and not a preference: Pokémon names collide relentlessly across
sets, printings, finishes and languages, so a list of names is a list of things
the operator cannot tell apart. They are standing at a table with the physical
card in hand.

**And not only in pickers — wherever a card APPEARS.** Owner, 2026-08-13: *"card
image, name, and price should all be shown when searching for cards, as well as
when added to coming in or going out."* The first version of this rule was scoped
to the moment of *choosing*, so surfaces showing an **already-chosen** card — a
staged trade leg, a sale cart, a commit dialog — were read as out of scope and
shipped without art. That reading was wrong: identity is needed **continuously**,
not once. The operator builds a five-card deal over several minutes and
re-verifies every row against the physical cards in their hand before confirming.
A staged row is not a receipt; it is a thing still being checked.

> **A HOVER NEVER SATISFIES THIS RULE.** `/admin/sell` rendered its art from
> `onMouseEnter` into a side panel captioned *"Hover or select a card"*, and that
> counted as "has an image" for months. It does not: a hover needs a mouse, shows
> exactly one card when the operator is comparing several, shows **nothing** to
> someone reading the list, and vanishes the moment the pointer moves. RFC 0011 §J
> **deletes** that panel rather than restyling it. Hover may change a background
> colour. It may never be the only way to see an image, a price, or a control.

**Both fields are already in the response.** `CatalogCard.images` and
`CatalogCard.prices` (`models/catalog.py`) are both populated and
`GET /admin/market/search` returns them via `model_dump`. A picker without art or
a price is not missing data; it is discarding data it was handed.

**`CardPickerRow` is the reference row**: `CardImage size="sm"` beside a
two-line block — name on line 1, `set · #number · rarity` on line 2, with
`min-w-0 flex-1` + `truncate` so a long name shrinks instead of shoving the
image. Three of the five original pickers were built from this pattern and
dropped the image on the way, which is why this is a component and a rule
rather than a habit. (This used to point at `/admin/buy`'s inline dropdown —
that page was deleted in RFC 0011 T16; `CardPickerRow` is now the only copy
of the pattern.)

**`CardSearchPanel` is the one card search** — name + card number + set
combobox, adopted by Slabs intake, Triage re-point, Market and Unmatched, and
**composed** by the deal page's `DealSearchPanel` rather than duplicated.
`GET /admin/market/search` always accepted all three fields; the pickers just
never sent them. **Manual entry is a permanent control**, not something that
appears after a failed search — the owner's report was finding a card that
exists whose catalog row is the wrong printing, at which point a gated button
is unreachable. It is offered only where creating an off-catalog item is
meaningful: the deal page (Buy/Trade modes) and Slabs.

**Price rendering — the honest cases are the ones that get this wrong:**

- The figure comes from the **backend**, chosen with `_market_price(card,
  "normal")` — the ONE shared finish-aware lookup (`models/inventory.py:388`).
  Passing a default finish buys its whole fallback walk for free. **Never
  re-implement price selection in the frontend**: a catalog result has no item and
  therefore no finish, and a second copy of that walk is exactly how 174 of 213
  live items once went unpriced.
- **An absent price is never `$0.00`, never blank, and never a guess.**
  `FinishPrice` bands are written only when a provider published a figure, so
  absent means absent — the same discipline the graded prices already document.
- **`detail: "brief"` vs `"full"` is a real distinction and the UI must keep it.**
  `brief` = *we have never fetched a price for this card*; `full` with no band =
  *no provider covers this card*. The model preserves that difference
  deliberately; collapsing both to "—" throws away the only signal that says
  whether waiting will help.
- **Show the age when the figure is stale.** A price from six days ago is fine; a
  three-month-old one is a different claim and must not look identical.
- **A catalog price is a NEAR MINT market figure and is NOT condition-adjusted** —
  there is no item and therefore no condition. Never present it as a sale price.

Catalog prices are filled by the **weekly cycle** (`refresh_catalog_prices`, RFC
0010 T17): every catalog card is re-priced at least once a week, by Friday. Before
that job runs, most of the 31,603 catalog rows have **no** price at all — which is
why the rules above lead with the absent cases instead of treating them as edges.

**Adding these fields is not finished when they render. The layout has to be
better, not merely more informative.** Owner: *"the UI has to be thought about so
that adding an image next to the name is still readable, not squished into a page,
and looks very clean from a design perspective so that users can do things as
quickly as possible."* So: the text block gets `min-w-0` and truncates; the image
never shrinks and never grows; real card proportions (5:7) — a stretched thumbnail
misrepresents what the operator is comparing against; a card-less or failed id
renders the **placeholder**, never a collapsed row, because rows that change height
as art loads make the list jump under the cursor mid-click. Speed is the point:
keep the debounce, keep the batching, never fire a request per row.

**The three fields are required wherever a card appears, not only in
pickers** — search results *and* staged/selected rows. **No hover may carry
information.** A hover needs a mouse, shows one card at a time, shows nothing
to someone reading the list, and vanishes. The Sell page's `onMouseEnter`
preview panel was deleted rather than restyled (RFC 0011 §J).

**Check this rule before writing any card-picking UI, and check it in review.**

## AN ESCAPE HATCH IS NEVER GATED ON THE FAILURE OF THE PATH IT ESCAPES

Owner rule, stated twice — 2026-08-13: *"There should always be an option for
manual entry, not just when the catalog search returns no results"*, and again
the same day for the merged deal surface.

**Manual entry on `/admin/buy` appeared only after a search returned nothing.**
That affordance was designed for the case that *motivated* it — the catalog has
no such card — and not for the case that actually happens: **the search succeeds
and every result is the wrong printing.** A Pokémon that exists, found, with no
correct catalog row behind it. In exactly that state the button was unreachable,
because the search had "worked".

The general form, and it applies to any fallback, override or manual path:

> **If the escape hatch is only reachable when the primary path fails, it cannot
> be reached in the case where the primary path succeeds and is wrong** — which is
> the more common and more expensive failure, because the operator has no signal
> that anything went wrong.

So: **a permanent control, put away by default.** Present before any search runs,
while results are showing, and when there are none. `/admin/slabs`' "Manual entry"
disclosure is the reference implementation — it is a button that is always there,
the form is closed until asked for, and **it stays open across adds** because
intake is a batch workflow and a control that closes after every entry fights the
person using it.

A disabled escape hatch is worse than none: it implies a roadmap. Either it works,
or it is gone (RFC 0010 T12 deleted three buttons on exactly this reasoning). If
it must be unavailable in some state, **say why in one line beside it** — e.g.
(historically) manual entry forcing Raw because a graded item needs a `card_id`
for pricing to join on, which is exactly the example the next paragraph shows
going stale.

**That one-line "say why" comment is a promise, and promises go stale.** RFC
0012 found the promise above already broken: `IncomingCardForm.tsx`'s comment
said Buy-mode graded intake stayed off "until that lands" — meaning until a
cert-ownership warning existed — but the warning (`GET /slabs/certs/{cert}`,
firing on `kind === 'graded'` alone) had *already been built*, in the same
file, and nobody had come back to remove the gate it was blocking. The safety
check and the restriction waiting on it were two separate pieces of code with
no link between them but a sentence, so they drifted: one got finished, the
other didn't notice. RFC 0012 then removed the gate itself — a manually
entered graded item is accepted now, not just found stale (see "Buy / Sell /
Trade" above for the current behavior).

> **When a gate's own comment names the specific thing it's waiting on, that
> named thing can be built later without the gate ever being revisited** —
> nothing forces the two to move together. Before trusting a "not yet" comment,
> grep the file for whether the missing piece has since landed; a comment is
> not a dependency, and code review rarely re-checks old justifications, only
> new ones.

This is a different failure than the escape-hatch rule above (that one is about
reachability depending on a *sibling path's outcome*; this one is about a gate's
justification going out of date). Same fix both times, though: a disabled
control's reason is either still true or the control comes out — never left
standing on a stale comment.

**Card art: import the size, never re-pick it.** `TABLE_THUMB_SIZE` (`xs`,
56×78 — real card proportions) and `TABLE_THUMB_COLUMN` (`w-16`) are exported
from `components/admin/shared/CardImage.tsx`. Every admin list row uses them.
Hand-picking a size per page is what went wrong before: Inventory, Vault and
Show Prep each chose `md` (160×224) while Prep Queue chose `lg` (224×320), and
their columns disagreed too, so every one of them rendered an image several
times wider than its own cell.

Art now appears on Inventory, Vault, Show Prep, Prep Queue (behind each page's
`ImageToggle`) and — always on, no toggle, because the list is short and
identifying the card *is* the task — Triage, History (search hits, the item
header, and every trade-lineage node) and Trade (both staged legs). All of them
resolve through `useCardImages`, which batches the lookup and, since
2026-08-07, **attempts each id once**: callers pass a freshly-mapped array so
the hook's effect re-runs every render, and re-queueing failed ids meant one
POST per keystroke on Trade. A failed or card-less id renders the placeholder.

**Show Analytics' Daily tab joined this list 2026-08-15 — `SaleDetailModal`**
(`frontend/components/admin/shared/SaleDetailModal.tsx`). Owner report:
*"listed sales should have details of the cards sold including image, name,
and price... instead of an arrow to reveal the individual sales, [let] users
click on the bundled sale to view the individual components... in a popup
similar to how you would click on an inventory item."* `TransactionGroups`'
old inline chevron-expand rendered a bare `item_id` ULID per leg — no image,
no name, a direct instance of this rule going unenforced on a real surface.
Replaced, not patched: clicking a group's "N cards" cell (every group, not
just multi-leg ones — a one-card sale showed no card identity inline
either) opens the popup, which resolves each leg's name and `card_id` in ONE
batched call to the new `POST /admin/inventory/items-brief`
(`routers/admin/inventory.py`, same cap-at-100/null-not-omitted shape as the
pre-existing `/card-images`) and reads its image through the same
`useCardImages` every other surface uses. Price is `leg.amount`, not
re-fetched — the transaction leg already carries the authoritative
sold/bought figure. Per-leg void/restore moved into the popup along with the
identity it now shows; the group-level Void/Restore in the table row is
unchanged.

> **A popup must key on group IDENTITY, not a captured object.** The first
> version stored the clicked `TransactionGroup` object in state. Voiding a
> leg from inside the still-open popup calls the page's `refetchDay()`,
> which rebuilds every group as a new object — so the popup kept rendering
> the stale pre-void object until closed and reopened. Fixed by storing the
> group's `key` and re-deriving the current object from `groups` on every
> render, the same way the old chevron's `expanded: Set<string>` already
> did. Any popup/panel that displays a live, mutable list item should key on
> an id and re-derive, not hold the object itself, once anything inside that
> popup can trigger a refetch of the list behind it.

**Model fields added by RFC 0008.** On `InventoryItem`:
`display_name_override` (admin-typed English name; **customer-facing**, bounded
200 chars, outranks the catalog name — nothing in sync/import ever writes it),
`review_reason` (**internal**, bounded 500 chars, must stay out of
`_CUSTOMER_ITEM_FIELDS`), and `reviewed_at` (server-stamped on clear). On
`Show`: `archived` (bool). Plus a new `catalog_set` entity backing
`GET /admin/catalog/sets`.

There is **no `name_en` and no `dex_number`.** The RFC originally specified an
automated `dexId`/Pokédex-map pipeline for Japanese names; the owner dropped it
on 2026-08-05 in favour of the hands-on `display_name_override` above. If a doc
or comment still claims those fields exist, it is stale — the pipeline was never
built.

**Condition vocabulary.** Display strings are `NM, LP+, LP, LP-, MP, HP, DMG`,
but storage is ALWAYS two separate fields — `condition` (the tier: `NM/LP/MP/
HP/DMG`, `Condition` enum) plus `condition_modifier` (`ConditionModifier`:
`"+"`/`"-"`/`null`) — never a combined `"LP+"` enum value. That combined form
used to be sent straight to the backend and failed enum validation (the Round 1
bug); `normalize_condition()` (`backend/src/merlins_collection/models/
inventory.py`) now splits a display string into the two stored fields, mirrored
on the frontend by `parseCondition`/`formatCondition` (`frontend/lib/
constants.ts`).

**Locations.** Admin-managed, DB-backed list — not a hardcoded enum. Seeded
once from the legacy `InventoryLocation` enum unioned with distinct location
values already present on inventory, then editable by admins. Endpoints
(`backend/src/merlins_collection/routers/admin/locations.py`):
`GET /admin/locations`, `POST /admin/locations`, `PATCH /admin/locations/
{value}` (RFC 0022 T6 — `label` only, any other key including `value` itself
is a 422 via `extra="forbid"`, never a silent no-op), `DELETE /admin/locations/
{value}` (blocked with 409 if the location is still in use by any item).
**`value` is permanently not editable at any price** — it's the join key
stored on every inventory item pointing at that location, and there is no
rename-and-migrate path; the frontend cell carries a `title` explaining why,
per the "a disabled control states why" rule. Frontend reads it via
`useLocations()`; never hardcode a location list in new code.

## CARD IDENTITY GREW ON THREE AXES — LANGUAGE, FINISH, AND TCGPLAYER LINKS (RFC 0023)

**Language went from 2 members to 19** (`Language` StrEnum,
`models/inventory.py`) — the 18 real TCGdex codes plus `OTHER`, the manual
escape hatch for a card TCGdex cannot represent at all. Nothing is renamed
and nothing is backfilled: every existing row is `EN` or `JP` and stays
valid unchanged. `JP` keeps the stored value `"JP"` even though the TCGdex
API code is `"ja"` — `LANGUAGE_API_CODE` already exists to carry that
translation, and renaming the enum member would invalidate every stored row
and every `ja:`-prefixed `card_id`'s reverse lookup for a cosmetic gain.
`frontend/lib/constants.ts`'s `LANGUAGE_OPTIONS` mirrors backend
`LANGUAGE_LABELS` verbatim and is the one shared source three surfaces read
from: `CardDetailModal`'s language select (a new `language_note` row — free
text, **internal**, appears only when the language is `OTHER`),
`admin-inventory-columns.tsx`'s `language` column edit + filter (previously
a hand-typed subset that didn't even use real enum values — `'ZH'` is not a
`Language` member, the real codes are `ZH-TW`/`ZH-CN`), and
`IncomingCardForm.tsx` (previously hardcoded to `EN`/`JP` only).

**`OTHER` implies `card_id is None`, and setting it also parks the item in
Unmatched, not Triage** — the exact mirror of the existing `no_catalog_match`
invariant, for the same reason: there is no catalog language to link an
`OTHER` item to (`LANGUAGE_API_CODE` has no entry for it — that absence is
the mechanism), so a linked `OTHER` row is a contradiction, and routing it
to Triage's derived `missing_card_id` reason would rebuild the exact "floor
the queue can never get under" that RFC 0011 built Unmatched to remove. A
422 with "unlink the card first" on a linked item; clearing `OTHER` back to
a real language does **not** auto-clear `no_catalog_match` — leaving a queue
is a deliberate action.

**The catalog is seeded per language, on demand — not all 18 at once.**
`SEEDED_LANGUAGES` (currently `{EN, JP}`) bounds `sync_new_sets`'s and
`purge_catalog_junk.py`'s walks; extending it is a manual, deliberate edit
alongside actually running `scripts/seed_catalog.py --language <code>
--execute`. `GET /admin/catalog/languages` (new) returns only languages that
actually have `catalog_set` registry rows — `CardSearchPanel`'s language
filter (`frontend/components/admin/shared/CardSearchPanel.tsx`, defaulting
to `EN`) uses **only** that scoped list, because a catalog search for an
unseeded language can only ever return nothing. The admin inventory table's
own `language` filter is deliberately **not** scoped this way — it offers
the full 19-member vocabulary, because an admin can legitimately own a
Korean card before that catalog is ever seeded. Same field, two different
filter scopes, by design.

**`finish` stays the single priced join key into `card.prices`** —
`_market_price`/`market_price_and_finish` are unchanged. What changed is
that the dropdown offering it stopped being a hand-written guess:
`PRICED_FINISHES` (`models/inventory.py`, mirrored verbatim in
`frontend/lib/constants.ts`) is **measured, not typed** — a full scan of the
live catalog on 2026-09-02 (29,123 `CatalogCard` rows) found 7 distinct
finish keys actually present, unioned with `_MARKET_FINISH_FALLBACK`'s own 6
for 8 total. The two sets do not fully overlap: `1stEditionNormal` (one of
the fallback's six) had **zero** live cards, and `1stEdition`/`unlimited`
(no `Holofoil` suffix) exist live but were never in the fallback. This is
the concrete evidence the measurement exists to prevent:
`IncomingCardForm.tsx` used to hardcode a fourth option,
`firstEditionHolofoil`, a spelling neither list has ever contained, so an
item staged with it silently fell through the entire pricing fallback.

**`finish_attributes: list[str]`** (`RawInventoryItem`, ≤10 entries, ≤40
chars each, defaults `[]`) carries everything about a printing that is
genuinely NOT mutually exclusive with `finish` — 1st Edition, Shadowless,
Full Art, Signed, ... **Customer-facing** (in `_CUSTOMER_ITEM_FIELDS`) — the
opposite call from `language_note`/`review_reason` above: this describes the
CARD, not the business's own handling of the record. **Carries no price
multiplier, by design** — stated in the model docstring, the same reasoning
that already killed the admin chat's `stale`/`max_age_days` idea: a 1st
Edition Shadowless Charizard is worth vastly more than the `holofoil` band
says, and the honest answer is that the operator hand-prices it
(`HandValuedBadge` marks it), not that this field invents a guessed number.
`FINISH_ATTRIBUTE_SUGGESTIONS` (`frontend/lib/constants.ts`) is a
**suggested**, not enforced, chip vocabulary — free text is always accepted
alongside it via an "add custom" input, the same "an escape hatch is a
permanent control" rule this file states elsewhere.

**`FinishPicker`** (`frontend/components/admin/shared/FinishPicker.tsx`) is
the one priced-finish-select-plus-attribute-chips control, used by
`IncomingCardForm` (which deleted its old `FINISHES` array — see above) and
the admin inventory table's `finish_attributes` column via RFC 0022's
`multiselect` `EditSpec` mechanism, its first real consumer.
`CardDetailModal` has its own parallel chip implementation rather than
embedding `FinishPicker` itself — its edit plumbing predates (and is
architecturally separate from) `InlineEditCell`'s array-typed
`multiselectValue`/`saveMultiselect` pair, so routing a `string[]` through
its own single-string `editValue` would have meant smuggling an array
through a joined string, which RFC 0022 §1 explicitly rejects. The two
implementations share `finishAttributeChipVocabulary` (exported from
`FinishPicker.tsx`) rather than duplicating the suggested-plus-selected chip
computation.

**TCGplayer has exactly two Pokémon categories**, verified 2026-09-02
against their own category registry (`tcgcsv.com/tcgplayer/categories`, 92
categories site-wide): `pokemon` (id 3, English) and `pokemon-japan` (id
85). There is no Korean, Chinese, French, German, Spanish, Italian or
Portuguese Pokémon category — TCGplayer added Japanese as a dedicated
category in October 2024 and has added no others since.
`frontend/lib/tcgplayer.ts`'s `tcgplayerSearchUrl(language, query)` is now
the one place a TCGplayer URL is built, adopted on four surfaces —
`show-prep/page.tsx`'s TCG Price column, `admin-inventory-columns.tsx`'s
`tcg_url` column, and — closed at Round 9 closeout (2026-09-03),
RFC 0023 follow-ups #2 — `CardDetailModal.tsx`'s Quick Info link and
`card/[id]/page.tsx`'s TCGplayer buttons, both of which used to hardcode the
English-only category regardless of the item's actual language. All four
show the real link for `EN`/`JP`, `null` for everything else including
`OTHER`. **A `null` must never fall back to the English link** — an
English-category search for a Korean card returns the wrong card or
nothing, and both are worse than no link; every adoption site shows a
one-line reason (`TCGPLAYER_UNSUPPORTED_LANGUAGE_MESSAGE`) instead.

**A stored `tcg_url` is admin-typed free text and must never be used as an
`<a href>` unvalidated — RFC 0023 follow-ups #3, closed the same day.**
`show-prep/page.tsx` originally rendered `item.tcg_url` directly as an href
(a `javascript:` value is a stored-XSS sink that fires on one click, the
exact shape `admin-inventory-columns.tsx`'s own comment on the identical
field already warned against); `CardDetailModal.tsx` had the same gap, and
`card/[id]/page.tsx` had only a weaker `startsWith('http')` check. All three
now go through `lib/tcgplayer.ts`'s `safeTcgHref`, which delegates to the
existing `lib/safe-href.ts` (already used to vet Sanity-authored article
links — parses with the real `URL` constructor rather than a regex, so it
also catches whitespace/case tricks a naive `^https?:\/\//` check would
miss) and narrows the result to http(s) only. An unsafe or malformed stored
value now falls back to the generated search link exactly as if nothing
were stored, on all three surfaces.

**Incidental backend fix, needed because this RFC is what starts generating
JP links at volume:** `services/card_text.set_hint_from_url`'s marketplace-
prefix strip widened from `^pokemon-` to `^pokemon-(japan-)?` — a JP product
slug is `pokemon-japan-...`, not `pokemon-...`, so the old strip left a junk
`japan` token in every JP set hint with no relationship to the actual set
name.

## AN OVERLAY MOUNTED INSIDE A `backdrop-blur` ANCESTOR IS NOT FIXED TO THE VIEWPORT — PORTAL IT

Measured in a real browser 2026-08-27 (RFC-0018 item 9b), on a defect that had
passed every component test. `AdminChat`'s slide-over is
`fixed right-0 top-0 z-40`, and it was rendered inside `AdminShell`'s
`sticky top-0 z-30 … backdrop-blur-md` header. **A non-`none`
`backdrop-filter` (or `filter`, `transform`, `perspective`, `will-change`,
`contain: paint`) does two things at once to every `position: fixed`
descendant**, and both bit:

1. **The blurred element becomes their containing block.** `fixed top-0`
   anchors to *it*, not the viewport. Measured at `y = 67` the moment anything
   sat above `<main>`, so a `h-screen` panel ran 67px past the fold and took
   its message input with it.
2. **It opens a stacking context.** The panel's own `z-40` is resolved
   *inside* `z-30`, so it can never out-rank a sibling of the header.
   `AdminShell`'s mobile bottom nav is `z-50`, so at **390x844 and 430x932**
   `document.elementFromPoint` at the centre of the composer returned the
   nav's `<a>`. The analyst chat opened, rendered and read correctly on a
   phone, and **tapping the input navigated to another tab** — it could not be
   typed into at all.

**The fix is `createPortal(…, document.body)`, not a bigger z-index.** Raising
the number inside a trapped stacking context does nothing; the portal takes
the node out of the subtree so `fixed` means the viewport again and the
z-index is comparable with the nav's. Gate it on a mount-only flag —
`createPortal` needs a real `document`, and a render that disagrees with the
server's markup is a hydration error on every admin page.

**Four live `backdrop-blur` ancestors are waiting to do this again**, so check
before mounting any new overlay: `AdminShell.tsx:243` (sidebar), `:350`
(mobile nav), `:377` (sticky header), and `Navbar.tsx:41`. The two modals
(`CardDetailModal`, `SaleDetailModal`) are safe as they stand — their blur is
on their own `fixed inset-0` backdrop, which is already viewport-anchored.

**No jsdom test can catch either half**, which is why this shipped green:
jsdom computes no layout and no stacking. `AdminChat.test.tsx` pins the
structural half (the dialog is not a descendant of the blurred wrapper) and
that is the most a unit test can do — **reachability of a control is a browser
measurement**, and `document.elementFromPoint` at an element's own centre is
the check that distinguishes "rendered" from "usable". `getBoundingClientRect`
does not: it reported the composer comfortably inside the viewport the whole
time it was unclickable.

Same family as the hover rule above — a control that exists but cannot be
operated is not a control.

**Superseded 2026-08-28 — the panel is no longer `fixed` at all.** Owner
report: it overlapped the tab instead of shrinking it ("reduce the width...
with no overlap"). `fixed` was never load-bearing for anything the panel
actually needed — decision 2 only required the tab underneath to stay
*mounted*, which ordinary flow content does just as well — so the fix removes
`position: fixed` (and therefore the trap above) entirely rather than
re-solving it: the panel now portals into a slot `AdminShell` renders as a
flex sibling of `<main>`, taking real layout space so `<main>` genuinely
shrinks. Width is `min(<configured>, 100vw)` so a phone still gets full
coverage instead of clipping, and `pb-20 md:pb-0` (the same classes `<main>`
already carries) clears the mobile bottom nav by reserving space above its
band rather than by winning a stacking fight normal-flow content structurally
cannot win. **The measurement and the general rule above are still true and
still the thing to check before mounting any NEW `fixed` overlay** — this
paragraph records only that `AdminChat` itself stopped being one of them.

# Ops

**The catalog is NOT empty.** An earlier version of this file claimed the live
`merlins-cards` table had an empty card catalog and that this was why market
prices and the Buy page's catalog search came back blank. **That was wrong** —
measured 2026-08-05, the table holds **31,603 catalog rows**. The real cause was
performance, not missing data: `GET /admin/market/search` has no index on card
name, so every keystroke triggered a full-table scan — 11.7 MB over 12
sequential 1 MB pages, **11.2 seconds per request**, on a 300ms debounce. RFC
0008 T9 fixed it with an in-process catalog cache
(`services/catalog_cache.py`); read that module's docstring before touching it,
especially the ~93 MB resident sizing note. Do not go looking for missing data
here — this dead end has already cost one investigation.

**The ECS task role must grant `dynamodb:Scan` and `dynamodb:UpdateItem`.**
Diagnosed 2026-08-07 from CloudWatch: catalog search was returning **HTTP 500**
on the live site, not failing to connect. `merlins-backend-task-role` had
neither action on `table/merlins-cards`, so everything routed through
`_scan_catalog` died — `GET /admin/market/search`, `GET /admin/market/coverage`,
and (via `upsert_catalog_card_preserving_prices`) the price sync. The catalog
cache T9 added is what introduced the Scan dependency; the policy was never
updated to match. `deploy/backend-task-role-permissions.json` is the source of
truth — apply it with `aws iam put-role-policy` (no ECS redeploy needed, task
roles are read per request). **A blank catalog dropdown is far more likely to be
this than missing data.**

**Never write a bare `float` to DynamoDB.** boto3 rejects it outright
("Float types are not supported"), and `_serialize`
(`services/dynamodb.py`) is the one place that coerces `float` → `Decimal`,
via `str()` so a price still round-trips. This matters because the sell/buy/
trade session routers persist **raw request JSON**, where a price arrives as a
float — `POST /admin/sales/{id}/items` 500'd in production for exactly this
reason. Tests missed it for months because they all send prices as **strings**;
when testing a money path, send a JSON **number**, which is what the frontend
actually sends.

## A PLAIN JS STRING OPERATION ON A CDK TOKEN IS A SILENT NO-OP — USE `Fn.*`

Diagnosed 2026-08-26, after it had taken the **entire production site** down —
every customer page and every admin tab at once — for an unknown period behind
two `UPDATE_COMPLETE` stacks.

`infra/bin/infra.ts` fed the frontend its backend origin as
`backend.functionUrl.url.replace(/\/$/, '')`, with a long comment correctly
explaining that a Lambda Function URL always carries a trailing slash and that
`frontend/lib/api.ts` concatenates `${BASE_URL}${path}` where every caller's
`path` starts with its own slash. The diagnosis was right. **The fix never
executed.**

**At synth time `functionUrl.url` is not a URL. It is an unresolved CDK token**
— a placeholder string of the form `${Token[TOKEN.n]}` that CDK swaps for a
CloudFormation intrinsic when it writes the template. It does not end in a
slash, so the regex matched nothing, `.replace()` returned the token unchanged,
and CDK emitted a bare passthrough:

```json
"NEXT_PUBLIC_API_URL": {"Fn::ImportValue": "MerlinsBackendStack:...FunctionUrl"}
```

The slash only exists after CloudFormation resolves that import at **deploy**
time, which is long after any JavaScript could have run. Every request then
went to `//inventory/search`, which FastAPI treats as a different, nonexistent
route and 404s **before it even authenticates** — so the symptom is a 404, not
a 401, on endpoints that plainly exist. Measured live: `/health` → 200,
`//health` → 404.

**The rule: a token can only be transformed by CDK's own `Fn.*` intrinsics**,
which defer the work into the template so it happens after the value resolves.
`.replace()`, `.split()`, `.slice()`, `.endsWith()`, `.toLowerCase()` and
template literals carrying logic all fail this way — and they fail *silently
and plausibly*, which is what makes this worse than a crash. There is no error,
the types are all `string`, and the code reads as obviously correct in review.
`infra/lib/backend-origin.ts` is the fixed shape to copy.

**`cdk.Token.isUnresolved(value)` is how you check** before trusting a
construct property as a real string. Anything CDK computes from a deployed
resource — `.url`, `.functionArn`, `.bucketName`, `.tableName`,
`.distributionDomainName`, every `Fn.importValue` — is a token. Literals you
wrote yourself are not.

**And verification here has to be the synthesized template, never the source.**
`cdk synth -o <dir>` then read the emitted JSON for the property in question: a
transformation that worked shows up as `Fn::Join`/`Fn::Select` structure, and
one that no-opped shows up as the bare `Fn::ImportValue` above. A unit test on
the TypeScript cannot catch this on its own, because at test time the token is
just as unresolved as it is at synth. `infra/test/backend-origin.test.ts` pins
the emitted structure via `stack.resolve()` for exactly that reason.

**`bash scripts/smoke-deployment.sh` is the standing post-deploy check** and
exists because of this incident: it asserts the *deployed* Lambda's
`NEXT_PUBLIC_API_URL` has no trailing slash, probes real backend routes, and
confirms the frontend's secrets survived. **A green `cdk deploy` proves
nothing about whether the site works — run it every time.**

## THE FRONTEND BUILD HANG IS AN UNBOUNDED FETCH, NOT A WINDOWS SOCKET QUIRK

Diagnosed 2026-08-26, **correcting a diagnosis this repo had recorded as
fact** (`infra/lib/frontend-stack.ts`'s `skipOpenNextBuild` docstring, and the
`staticPageGenerationTimeout: 180` comment in `frontend/next.config.ts`). The
old note read: *"on this Windows dev machine, `next build`'s static-generation
fetches to a live HTTPS backend hang indefinitely … when invoked through
cdk-nextjs-standalone's nested child-process chain … the exact same build
invoked DIRECTLY succeeds every time … suspect a proxy/DNS/socket
difference."* Every observation in it is real. The conclusion drawn from them
is wrong, and it sent the fix in the wrong direction for nine days.

**The comparison was not controlled.** `cdk-nextjs-standalone`'s
`NextjsBuild.getBuildEnvVars()` replaces every **unresolved** `NEXT_PUBLIC_*`
token with a literal `{{ KEY }}` placeholder, substituting the real value into
the built files at *deploy* time. So a CDK-driven build runs with
`NEXT_PUBLIC_API_URL="{{ NEXT_PUBLIC_API_URL }}"`, while a hand-run
`npm run build:opennext` from a plain shell has the variable **unset** and
falls back to `http://localhost:8000`. "Direct vs nested" also changed the
backend URL — which is the variable that actually mattered.

Measured on Linux, both invocations direct:

| `NEXT_PUBLIC_API_URL` during build | Result |
|---|---|
| unset → `http://localhost:8000` | succeeds, 24/24 static pages |
| `{{ NEXT_PUBLIC_API_URL }}` | **hangs**, 3× the watchdog, build fails |

**The mechanism:** bare `fetch("{{ NEXT_PUBLIC_API_URL }}/public/shows")`
rejects in **23 ms** with `TypeError: Failed to parse URL`. But
`frontend/lib/public.ts` fetches with `next: { revalidate: 300 }`, and inside
**Next's ISR fetch wrapper that rejection becomes a hang.** Static generation
then burns the entire `staticPageGenerationTimeout`, three times, and fails on
whichever public page reached it first — which is exactly why the old note
observed "a different page each time" and read it as flakiness. It is not
flakiness; it is a race between equally-doomed pages.

> **A page-level `try/catch` fallback does not cover a hang.**
> `FeaturedFinds.tsx` has said `// On ANY error, fall through to the static
> set` since it was written, and it never once rescued this build, because a
> promise that never settles raises nothing. Any "fall back on failure" path
> guarding I/O needs the I/O to be *bounded* before the fallback means
> anything.

**The fix is `isUsableBaseUrl` in `frontend/lib/api-base.ts`:** `apiFetch`
rejects *before constructing a request* when the base URL is not an absolute
http(s) origin. Callers' existing fallbacks then do the job they were written
for. Do not "fix" this by raising `staticPageGenerationTimeout` again — that
buffers the symptom and costs 9 minutes per failed build.

**The general rule, and the reason this section is long:** when two runs
differ, the recorded cause must be a variable you actually held everything
else constant against. "Direct succeeds, nested fails" was reproduced twice
each way and was still wrong, because both arms silently changed a second
variable. Reproducibility is not control.

## A PAGE'S CACHE LIFETIME MUST BE DECLARED, NEVER INFERRED FROM A FETCH

Same day, found while verifying the fix above actually worked end to end.

`frontend/app/(public)/page.tsx` had **no `export const revalidate`**. Its
freshness came entirely from `getFeaturedCards`' own
`next: { revalidate: 300 }`. When that fetch stops running at build time — as
it now correctly does whenever the base URL is a build-time placeholder — Next
observes no revalidating fetch, concludes the page is **fully static**, and
emits `cache-control: s-maxage=31536000`. CloudFront then pins the build-time
*fallback* content at the edge **for a year**, and ISR at the origin never
dislodges it.

Measured live after a deploy: `/shows` (`export const revalidate = 300`) and
`/articles` (`= 60`) both self-healed within ~2 minutes; `/` was still serving
placeholder card art 12 minutes later, with `x-nextjs-cache: HIT` and
`age: 1046`.

| Page | Page-level `revalidate` | `Cache-Control` served |
|---|---|---|
| `/shows`, `/articles` | declared | `s-maxage=2, stale-while-revalidate=2592000` |
| `/` (before the fix) | **absent** | `s-maxage=31536000` |

**Every page that renders remote data declares its own `revalidate`.** A page
whose cache policy is a side effect of whether a fetch inside it happened to
succeed will, on the one deploy where that fetch fails, cache the failure
permanently. `/about` and `/dictionary` correctly have none — they fetch
nothing, so a year-long static cache is the right answer for them.

## A PARTIAL ENV EXPORT ON `cdk deploy` SILENTLY DELETES SECRETS FROM THE LIVE LAMBDA

Diagnosed 2026-08-18 on `MerlinsFrontendStack` (RFC 0014's CloudFront+Lambda
spike, `infra/`). Redeploying to add `NEXT_PUBLIC_SANITY_PROJECT_ID` with only
that var and `SKIP_OPENNEXT_BUILD` exported wiped `AUTH_SECRET` and
`AWS_COGNITO_CLIENT_SECRET` off the already-working server Lambda. NextAuth
then failed with its generic "Server error / problem with the server
configuration" page, and — more confusingly — the Studio route's own admin
gate (`frontend/app/studio/layout.tsx`) started returning a bare `404`
instead of redirecting to sign-in, because `auth()` itself was failing
without `AUTH_SECRET`.

**Root cause:** `infra/bin/infra.ts` reads every secret (`AUTH_SECRET`,
`AWS_COGNITO_CLIENT_SECRET`, `POKEMONPRICETRACKER_API_KEY`, `ADMIN_API_KEY`)
from the deployer's OWN shell at synth time — by design, so nothing sensitive
is ever a literal in `lib/*-stack.ts`. But `buildFrontendEnvironment` only
*adds* a key to the environment map when its prop is truthy, and
CloudFormation's `Lambda::Function.Environment.Variables` is a full
**replace** on every stack update, never a merge. **Any deploy that omits a
previously-set secret deletes it from production, silently — CDK gives no
warning, and the stack still reports `UPDATE_COMPLETE`.**

Before running `cdk deploy` on `MerlinsFrontendStack` for *any* reason —
including a change that has nothing to do with auth — export every secret
this stack uses, not just the one being changed: `AUTH_SECRET`,
`AWS_COGNITO_CLIENT_SECRET`, and (if relevant to `MerlinsBackendStack`)
`POKEMONPRICETRACKER_API_KEY` / `ADMIN_API_KEY`. Same failure mode applies to
any future secret added to either stack's environment map.

**`bash scripts/deploy-frontend.sh` closes this mechanically rather than by
memory, and it is the way to deploy this stack.** It reads each secret's
current live value straight off the deployed Lambda and re-exports it (through
command substitution — the values are never printed), so a deploy can only
preserve what is already there; an explicit export in your own shell still
wins, so rotating a secret works normally. It refuses to run at all if
`AUTH_SECRET` or `AWS_COGNITO_CLIENT_SECRET` would end up empty, and it runs
the smoke check afterwards. Note that this repo's clones do **not** all have a
`frontend/.env.local` — the WSL clone has none, which is precisely why
recovering the values from the live Lambda beats depending on a file that may
not exist.

**A second, independent route to the same wipe, found 2026-08-26:
`cdk deploy MerlinsFrontendStack` also deploys its DEPENDENCY stacks.**
`MerlinsFrontendStack` imports the backend's Function URL, so CDK pulls
`MerlinsBackendStack` into the deploy — and a `cdk diff` for a
*frontend-only* change duly reported that it would remove
`POKEMONPRICETRACKER_API_KEY` from the backend Lambda **and** republish the
backend container image from whatever is in the working tree, uncommitted
changes included. **Always pass `--exclusively`** when deploying one stack;
`deploy-frontend.sh` does. And always `cdk diff` before a deploy: reading
that diff is what caught this, not reasoning about it.

## A MANUAL DOCKER REBUILD OF THE BACKEND IMAGE MUST PASS `--target lambda` — THE DEFAULT STAGE LOOKS FINE AND ISN'T

Diagnosed 2026-08-26. `backend/Dockerfile` has two stages built from the same
`base`: `lambda` (adds the AWS Lambda Web Adapter binary at
`/opt/extensions/lambda-adapter` plus `AWS_LWA_PORT`/`AWS_LWA_INVOKE_MODE`) and
`runtime` (the ECS production stage, no adapter) — `runtime` is the **last**
stage in the file, so a bare `docker build` with no `--target` silently builds
`runtime` instead. `infra/lib/backend-stack.ts`'s own `fromImageAsset` call
gets this right (`target: 'lambda'`), and its comment already flags "the
Dockerfile `lambda` stage bug hit earlier" as a **prior, distinct incident** —
this is a recurring failure class, not a one-off typo.

**Why this is the trap it is:** the wrong-stage image runs perfectly well
under a plain `docker run` — uvicorn logs `Application startup complete` same
as always, because nothing about the app itself is broken. Only the platform
integration is missing. Under **real** Lambda, the runtime API has nothing to
talk to without the adapter extension, so every single invocation hangs until
the function's configured timeout and returns a `502` — cold start *and* warm.
That symptom (clean startup logs, then a hard timeout on every request) reads
exactly like a slow-cold-start or resource problem, not a wrong-image problem,
which is what makes it slow to diagnose under production pressure rather than
what makes it happen in the first place.

**This bites specifically when hand-recovering from the "Docker manifest not
supported by Lambda" media-type error** (modern `docker build` attaches
provenance/SBOM attestations Lambda rejects — fix: delete the bad ECR tag,
rebuild with `--provenance=false --sbom=false`, push, retry `cdk deploy`). That
recipe is a bare `docker build` command with no stage named — copy it
literally and the rebuild lands on `runtime`, silently overwriting the correct
image under the exact tag CDK still believes holds the `lambda`-target build.
**Every manual rebuild of this image is `docker build --target lambda
--provenance=false --sbom=false -f backend/Dockerfile -t <repo>:<tag> .`, full
stop** — never the bare command. Verify before pushing, every time:
`docker run --rm --entrypoint /bin/sh <tag> -c "ls /opt/extensions/"` must
show `lambda-adapter`; empty output means the wrong stage got built.

If this has already shipped: `cdk deploy` alone will **not** fix it —
CloudFormation tracks the image *URI string*, not its content, so a corrected
push under the same tag reports `no changes` and the live function keeps
running the bad code. Mitigate first with `aws lambda update-function-code
--image-uri <repo>:<last-known-good-tag>` (found via `aws ecr describe-images
--query "sort_by(imageDetails,& imagePushedAt)"`), rebuild the broken tag
correctly, push, then `update-function-code` a second time to point back at
that now-fixed tag — the second manual call is required precisely because the
first `cdk deploy` after the fix will see no template diff and do nothing.

## A RUNTIME FILE READ RESOLVED FROM THE REPO ROOT IS UNTESTED BY CONSTRUCTION

Diagnosed 2026-08-27 on RFC-0018's admin analyst chat, before it shipped.
`services/bedrock._admin_tool_schemas()` read `shared/admin-tool-contract.json`
**at request time**, finding it by walking up from `bedrock.py.__file__` to the
repository root. Correct in this clone. Broken in production, on the first
request, with nothing local able to see it.

Two facts about the deployed artifact, both measured rather than reasoned about:

- **`backend/Dockerfile` never `COPY`s `shared/`** — `grep -c "COPY shared"`
  returns **0**. It copies `backend/pyproject.toml`, `backend/src`,
  `backend/scripts` and the built `mcp-server/dist`, and nothing else from the
  repo root.
- **The image installs the package NON-editable** (`RUN pip install
  ./backend`), so `__file__` lives under `site-packages/` and the walk lands
  outside any checkout entirely.

| layout | the walk resolves to |
|---|---|
| this dev clone (editable install) | `<repo>/shared/admin-tool-contract.json` ✅ |
| image, if `backend/src` were on `sys.path` | `/app/shared/…` ❌ never copied |
| **image, actual** | **`/usr/local/lib/shared/…`** ❌ |

So the first `POST /admin/chat/` would have raised `FileNotFoundError` before
Bedrock was ever called. **The whole test suite passed**, and always would
have: every test runs in the one layout where the path is correct, so no test
could distinguish "resolves the file" from "happens to be standing next to it".
That is what makes this class different from an ordinary bug — it is not
under-tested, it is *untestable in place*.

**The rule: a package reads its own data through `importlib.resources`, and the
file lives inside the package.** Then it ships with the wheel automatically and
resolves identically under an editable install, a wheel, a container image or a
zipimport — no `COPY` line for anyone to remember, and no path relationship for
a packaging change to break. `Path(__file__).parents[N]` is fine for reaching
*within* the package and is a bug the moment it climbs out of it.

**`shared/` is for values crossing the Python/TypeScript boundary — nothing
else.** `shared/tool-contract.json` belongs there because `mcp-server/`
(TypeScript) reads it. The admin contract never had a non-Python reader: RFC
0018 assumed a TypeScript admin server, roadmap item 4 chose Python instead, and
the file was left in the directory whose only justification that decision had
just removed. Same family as the stale-gate-comment lesson above — **when a
decision removes the reason something is where it is, the thing does not move
itself**, and here the leftover was not merely untidy, it was the bug.

**Verification has to be the built artifact, never the source** — the same rule
this file already records for `cdk synth`. `pip wheel --no-deps -w /tmp ./backend`
then `unzip -l` the result and look for the file; better, unpack it somewhere
with **no repo checkout in scope**, put that on `sys.path`, and import. That is
a two-minute check and it is the only one that distinguishes the three rows of
the table above. `backend/tests/test_admin_contract_ships.py` pins the invariant
so the file cannot drift back out of the package.

**`MerlinsCognitoBrandingStack` (`infra/lib/cognito-branding-stack.ts`) is a
third, deliberately independent stack — this incident is exactly why.** It
applies classic Hosted UI CSS branding (cream background, forest-green
submit button, the site logo — matching `frontend/tailwind.config.ts`'s
Spriggatito palette) to the Cognito login page via `SetUICustomization`,
called through an `AwsCustomResource` since the native CloudFormation
resource (`AWS::Cognito::UserPoolUICustomizationAttachment`) exposes only
`css`, not the logo image, and Cognito's own docs say the two can't be set
separately. It shares no resource with `MerlinsFrontendStack` or
`MerlinsBackendStack` and is deployed on its own
(`cdk deploy MerlinsCognitoBrandingStack`), so a branding-only change is
structurally incapable of ever touching those stacks' Lambda environment
variables — the general shape to copy whenever a new piece of infra has a
meaningfully different blast radius than what already exists, rather than
folding it into a stack that also carries this secret-wipe risk.

**Catalog seed (one-time owner action).** Needed only for a fresh/empty
table, which the live one is not. With AWS creds, from `backend/`:

```bash
cd backend
# Linux/WSL: .venv/bin/python   Windows: ../.venv/Scripts/python.exe
.venv/bin/python scripts/seed_catalog.py --help    # dry-run by default
.venv/bin/python scripts/seed_catalog.py --execute --confirm-table merlins-cards
```

then press **Sync Prices** on `/admin/market`, or run `scripts/daily_sync.py`
the same way. This is not the scheduled sync — seeding is a one-time bootstrap
that populates catalog IDENTITY rows; it does not run on a schedule and does
not price anything.

**The daily/monthly price and catalog sync IS scheduled (RFC 0021), via
`MerlinsSyncStack`** — see "MerlinsSyncStack — the restored daily/monthly
sync" below. Before RFC 0021 this section read "not scheduled" because it
genuinely wasn't: RFC 0014's migration off ECS deleted the schedule that used
to invoke `scripts/scheduled_sync.py`, and nothing replaced it until now.

**Every script here needs the venv interpreter spelled out.** A bare `python`
resolves to an unrelated environment that cannot import `merlins_collection`,
and these files have no shebang — so `scripts/foo.py` hands the file to the
shell, which tries to run its docstring as commands.

**A one-time script that loops over live table data for more than a few
seconds must print progress between chunks, never only a final summary.**
Diagnosed 2026-08-19 on `backfill_price_history_ttl.py` (RFC 0015): a
single-call scan-then-serially-`update_item` loop against ~70,000 real rows
ran for ~90 minutes printing nothing between `"scanning…"` and the final
summary — genuinely working the whole time (confirmed live via CloudWatch
write-capacity metrics and a direct table scan showing steady completion),
but indistinguishable from a hang to the owner watching the terminal.
`reprice_catalog.py` (RFC 0010 T17) already solved exactly this class of
problem — select candidates once, then apply them in bounded chunks with a
line printed after each one (`chunk N/M: done/total, ETA`) — and its own task
doc already states the rule outright: *"progress output every chunk... this
runs unattended for two hours; silence is indistinguishable from a hang."`
The new script matched the wrong sibling on the wrong axis: it correctly
copied `backfill_catalog_sets.py`'s lighter `--execute`-only rail (right
call — additive-only work doesn't need `--confirm-table`), but a script has
independent axes to match precedent on — write-safety rail is one, loop
duration/shape is another — and only the first was checked.
**Before writing a new one-time script, estimate the real data volume it
will walk (not an assumed-small one) and, if the loop will run more than a
few seconds, copy `reprice_catalog.py`'s chunked-progress shape regardless of
which sibling's write-safety rail is otherwise the right match.**

**Catalog set registry backfill (one-time owner action).** The admin
inventory page's Set filter lists every set in the catalog — including ones we
own nothing from, which is the whole point of it — from a `catalog_set`
registry rather than from a full catalog scan. `sync_new_sets` (the **check
for new sets** button on `/admin/market`) maintains that registry going
forward, but it deliberately never walks a set that already has cards, so it
will not backfill a catalog seeded before the registry existed.

**DONE — run against `merlins-cards` on 2026-08-06**, registering **284 sets**
from 31,603 card rows; `GET /admin/catalog/sets` now returns all 284, of which
94 have owned cards. Re-running is a harmless upsert that refreshes the counts:

```bash
cd backend
# Linux/WSL: .venv/bin/python   Windows: ../.venv/Scripts/python.exe
.venv/bin/python scripts/backfill_catalog_sets.py            # DRY RUN
.venv/bin/python scripts/backfill_catalog_sets.py --execute
```

Until it has run, `GET /admin/catalog/sets` honestly returns `[]` and the Set
dropdown is empty. This is the one place a full catalog scan is acceptable —
offline, once, from a CLI; never on a request path.

**`CatalogCard.first_seen_at` answers "when did this row appear";
`last_synced_at` does not** — it is bumped by any write, so a price refresh
re-stamps a 2024 row. `None` means **predates the field**, not "new", and
every reader counts only non-null values. It is written with a conditional
`attribute_not_exists` update, **never in the item body**, because a full
reseed whole-item `put_item`s every row and would otherwise reset all 31,603
of them.

**`sync_new_sets` now always walks the brief card list** for both languages,
instead of only when a set is entirely absent. That early-out is why a promo
catalogued into a set we already hold was invisible. The extra walk is the
accepted cost; **restoring the early-out will look like an optimization and
is the bug.**

**TCG Pocket (digital-only) sets are excluded at INGEST, not just at query
time (RFC 0021) — a DIFFERENT filter from the `sync_new_sets` early-out
above, and the two must not be confused.** TCGdex carries Pokémon TCG Pocket
under series `tcgp`; both `sync_new_sets` and `seed_catalog.seed_language`
now resolve that series' set ids (`services.catalog_sync.excluded_set_ids`,
one `GET /{lang}/series/tcgp` call per language, cached per run) and skip
them before ever walking their cards. A TCG Pocket card is not physical
inventory — no TCGplayer/Cardmarket pricing, no card to buy/sell/grade — and
it used to pollute every catalog autocomplete an operator uses at a buy
table. `scripts/purge_catalog_junk.py` is the one-time cleanup for rows
ingested before this exclusion existed; the exclusion above is what stops it
recurring.

## MerlinsSyncStack — the restored daily/monthly sync (RFC 0021)

A FIFTH, deliberately independent stack (`infra/lib/sync-stack.ts`), on the
same "shares no resource, can't drag another stack into a deploy" reasoning
as `MerlinsCognitoBrandingStack`. EventBridge Scheduler → ECS Fargate
`RunTask`, invoking the existing, already-tested
`python -m scripts.scheduled_sync --job <prices|catalog>` dispatcher — the
job was never broken, it just had no caller after RFC 0014 deleted the ECS
constructs that used to invoke it.

| Schedule | Cron (UTC) | Job | Why |
|---|---|---|---|
| `merlins-sync-prices` | `0 9 * * ? *` (09:00 = 01:00/02:00 Pacific) | `--job prices` → `run_daily_sync` | Overnight in the business's own timezone; carries the ~24-minute weekly catalog cycle as its long tail |
| `merlins-sync-catalog` | `0 15 2 * ? *` (15:00 on the 2nd) | `--job catalog` → `sync_new_sets` | New sets release monthly at most. **Deliberately a different day/hour from `prices`** — two concurrent catalog writers is not a state either job was designed for; six hours of separation is cheaper than building a lock for a job that runs twice a month |

Task role grants `Query`/`GetItem`/`PutItem`/`UpdateItem`/`BatchWriteItem`/
`Scan` on `merlins-cards` — mirrors
`deploy/backend-task-role-permissions.json`'s `BusinessTable` statement;
**any new action the sync needs goes in both places or they drift.** The
image asset builds `backend/Dockerfile`'s **`runtime`** target, not
`lambda` — this is an ECS task with no Lambda Runtime API to talk to, the
exact opposite of `MerlinsBackendStack`'s own image, and
`infra/test/sync-stack.test.ts` pins the target against the synthesized
**asset manifest** (the `--target` build arg is not a CloudFormation
template property, so the template alone can't prove it — same "verify the
built artifact" discipline as the Lambda-stage trap this repo already
documents, applied in reverse). No `Fn::ImportValue` anywhere: the table
name is a plain string prop from `infra/bin/infra.ts`, same as every other
stack, specifically so a sync-only change can never pull `MerlinsBackendStack`
into its deploy.

`assignPublicIp: true` in public subnets, no NAT gateway — the job needs to
reach `api.tcgdex.net` and `pokemonpricetracker.com`, and a NAT gateway costs
~$32/month to avoid a public IP on a task that runs twice a month.

**Deploy only via `bash scripts/deploy-sync.sh`** (mirrors
`deploy-frontend.sh`'s secret-recovery pattern, scoped to this stack's one
secret, `POKEMONPRICETRACKER_API_KEY`) — a hand-run `cdk deploy
MerlinsSyncStack` from a shell missing that export writes an EMPTY key,
silently degrading the nightly job's graded pricing while every other step
still reports success. Always `--exclusively`. `bash scripts/verify-sync.sh`
is the standing post-deploy check (schedule state, most recent task run, the
last structured JSON summary line in CloudWatch Logs, and a one-shot manual
invocation command so the first run doesn't have to wait for the schedule).

# Test Commands

**Two venv layouts coexist across this project's clones — check which one is
present before picking a command.** Windows clones keep the venv at the repo
root (`.venv/Scripts/python.exe`); the WSL clone (this one, as of the
2026-08-24 migration off Windows) keeps it at `backend/.venv/bin/python`.
Never assume — check first:

```bash
test -x backend/.venv/bin/python && echo "Linux venv: backend/.venv/bin/python"
test -x .venv/Scripts/python.exe && echo "Windows venv: .venv/Scripts/python.exe"
```

| Layer      | Command (Linux/WSL)                                    | Command (Windows)                                      |
|------------|----------------------------------------------------------|----------------------------------------------------------|
| All        | `npm test` (from repo root)                               | `npm test` (from repo root)                               |
| Frontend   | `npm test --workspace=frontend`                            | `npm test --workspace=frontend`                            |
| MCP Server | `npm test --workspace=mcp-server`                          | `npm test --workspace=mcp-server`                          |
| Infra (CDK) | `npm test --workspace=infra`                              | `npm test --workspace=infra`                              |
| Backend    | `backend/.venv/bin/python -m pytest backend/tests -q --tb=short` | `./.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short` |
| Lint (FE)  | `cd frontend && npm run lint`                              | `cd frontend && npm run lint`                              |
| Lint (BE)  | `backend/.venv/bin/python -m ruff check backend/src`       | `./.venv/Scripts/python.exe -m ruff check backend/src`     |

**Use the venv interpreter explicitly, not bare `python`.** A bare `python`
on PATH can resolve to an unrelated environment with no pytest and no ruff
installed, failing with "No module named pytest" rather than a clear error.
This checkout is also a git worktree, and a global editable install can make
Python import the **sibling** repo's backend — if results look impossible,
check which package actually loaded before debugging anything else:

```bash
# Linux/WSL
backend/.venv/bin/python -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"
# Windows
./.venv/Scripts/python.exe -c "import merlins_collection,os;print(os.path.dirname(merlins_collection.__file__))"
```

`bash scripts/run-tests.sh {all|backend|frontend|mcp}` (Linux/WSL) already
encodes this resolution — it prefers `backend/.venv/bin/python`, falls back to
`python3`/`python` on PATH, and fails loudly rather than silently running zero
tests. `scripts/run-tests.cmd` is the Windows equivalent. Both write to
`test-results.txt` at the repo root, ending with `[test-runner] Status: DONE`.

## Running Tests in Kiro/Cursor (Agent-Specific)

The shell tool (`execute_pwsh`) has a hard ~10-15s effective timeout. Tests
take longer than that, so you MUST use **background processes** to capture
full output.

### Pattern: Start → Wait → Poll

```
# Backend (runs from workspace root — cwd works here)
control_pwsh_process start:
  command: "python -m pytest backend/tests -q --tb=short 2>&1"

# Frontend (use cmd /c wrapper — cwd param is broken for subdirs)
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\frontend & npx vitest run --reporter=verbose" 2>&1

# MCP Server
control_pwsh_process start:
  command: cmd /c "cd /d c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary\mcp-server & npx vitest run --reporter=verbose" 2>&1
```

Then use `get_process_output` (with `terminalId`) to poll for results.
Wait 30s+ for backend, 15s+ for frontend/mcp before first poll.

### Approximate Runtimes
Measured 2026-08-07, after the fixture rework below:
- Backend: **~2 minutes** (1515 tests) — was ~10 minutes
- Frontend: **~29 seconds** (609 tests, 80 files)
- MCP Server: **~1 second** (98 tests, 7 files)

**Do not reintroduce a per-test `mock_aws()`.** The backend suite spent **93% of
its wall time in fixture setup** until 2026-08-07. Entering a fresh `mock_aws()`
invalidates botocore's service-model caches, so the next
`boto3.resource("dynamodb")` pays a full model reload — measured **507ms** per
test to build the repo + table that way versus **15ms** inside a long-lived
mock. `tests/conftest.py` now starts **one** `mock_aws()` for the session and an
autouse `_clean_aws` fixture resets the moto DynamoDB backend between tests,
which wipes every table exactly as leaving the old context did. Isolation is
verified: a probe that wrote rows in one test and asserted an empty table in the
next goes red if the reset is removed. The RSA signing key is session-scoped for
the same reason (2048-bit keygen is ~53ms, and ~700 tests take a token).

Anything creating a table must depend on `_clean_aws` **explicitly**, not rely
on autouse ordering — nothing else drops a table now that the mock outlives the
test, so a second `create_table` with the same name raises `ResourceInUseException`.

Frontend: the ~20 pure-logic test files carry `// @vitest-environment node`,
since constructing a jsdom per file was the suite's largest single cost.
`vitest.setup.ts` guards its DOM work behind `HAS_DOM` and imports
testing-library dynamically — keep both if you add a setup step.

**`vi.clearAllMocks()` does NOT drain a `mockResolvedValueOnce` queue, and a
queued `Once` value outranks a later `mockResolvedValue`.** Measured 2026-08-10
with a two-test probe: after `clearAllMocks`, the next test received the previous
test's leftover value instead of its own fixture. So any test that ends without
consuming everything it queued — a timeout, an early assertion failure — hands
its leftovers to the tests after it, which then fail on another test's data.
**In a `beforeEach`, reset the mock (`mockReset()`), don't clear it.**

This is what made `ChatPanel.test.tsx` look flaky for weeks. One test typed ~120
characters through `userEvent` at its default per-keystroke delay, taking 3.3s of
the 5s budget **with the machine idle**; under full-suite parallel load it
crossed the timeout, and its 12 queued replies then cascaded into four
neighbours. The failure *count* changed run to run, which is the tell that one
failure is causing the others. Fixed 2026-08-11 by `mockReset()` plus a shared
`userEvent.setup({ delay: null })` — same events, without a macrotask per
character (3317ms → 994ms). **Reach for `delay: null` in any test that types
more than a few characters.**

### Quick commands that DO work with execute_pwsh
- `ruff check backend/src` (lint, ~3s)
- `npm run lint --workspace=frontend` (~5s)
- `dir`, `git status`, `type <file>` (instant)

# Inventory Search Tool
Located at `/inventory` — authenticated customers only.
Two distinct modes (user picks one at a time):
- **Filter mode**: dropdowns (set, condition, rarity), price range, name search → `GET /inventory/search`
- **Chat mode**: plain text to Claude via Bedrock + MCP tools → `POST /chat/`

**The transcript is SERVER-owned (RFC 0017).** The client sends a
`conversation_id`, never a `history` array — the backend replays the thread
from DynamoDB, which is also what stops a client forging assistant turns.
`ChatRequest.history` is still *accepted and ignored* for one release; nothing
reads it. Threads are keyed on the caller's Cognito `sub`, capped at 50 with
least-recently-used pruning, and expire on the existing `ttl` attribute after
six months.

| Route | Purpose |
|---|---|
| `POST /chat/` | Send a message; creates a thread implicitly, returns `conversation_id` + `title` |
| `GET /chat/conversations` | The caller's own threads, ≤50, `updated_at` descending |
| `GET /chat/conversations/{id}` | One transcript (≤200 messages) + its live-rehydrated panel |
| `PATCH /chat/conversations/{id}` | Rename — deliberately does NOT touch `updated_at` |
| `DELETE /chat/conversations/{id}` | Hard delete: index row first, then the message sweep |
| `DELETE /chat/conversations` | Clear all |

**A thread the caller does not own answers 404, never 403** — a 403 would
confirm the id exists. (The *route* `POST /admin/chat/` answers 403 to a
non-admin; that is a different question, asked before any id is looked at.)

**These routes are customer-private, and the tripwire that guards that was
NARROWED, not deleted, when RFC 0018 mounted `/admin/chat/conversations`.**
`test_no_admin_route_exposes_a_conversation` used to assert that no admin route
path contained the string "conversation" — which the admin analyst chat
legitimately now does. Replacing a string check with nothing would have been
exactly the weakening the test exists to prevent, so it asserts the property
the string stood in for instead: **an admin route must never return a
`surface="customer"` thread**, checked against real stored rows. Stricter than
before, and no longer defeated by renaming a path.

**A returned `conversation_id` is not proof the thread was written.**
`routers/chat.py` sets it unconditionally, *after* the deliberately-broad
`except` that swallows a persistence failure rather than discard a paid-for
Bedrock reply. So a client holding that id must treat a later 404 as "this
thread is gone" and start a new one — `ChatPanel` does exactly that. Holding it
instead wedges the chat on a permanent 404 that only a page reload clears.

## THE ADMIN ANALYST CHAT IS A SECOND SURFACE, ISOLATED BY PROCESS (RFC 0018)

`/admin` carries a read-only analyst slide-over — `AdminChat.tsx`, mounted in
`AdminShell`'s sticky header so it is reachable from **every** admin tab, with
the tab underneath staying mounted while it is open (that is why it is not a
route). It answers questions over the business's own numbers: profit and
margin, aging stock, consignor position, pricing outliers.

| Route | Purpose |
|---|---|
| `POST /admin/chat/` | Ask the analyst; same request/response shape as `POST /chat/` |
| `GET/PATCH/DELETE /admin/chat/conversations[/{id}]` | The same five conversation routes, scoped to the admin surface |

**The isolation is STRUCTURAL, not an `isAdmin` flag** (owner decision 6). Four
things differ from the customer chat and none of them is a runtime boolean: a
different **subprocess** (`python -m merlins_collection.mcp_admin`, spawned by
`get_admin_mcp_executor()`), a different **tool contract**, a different
**system prompt** (read-only analyst), and `ADMIN_VISIBILITY` hydration. A
customer conversation cannot name an admin tool because the process serving it
never loaded one. If a refactor starts collapsing these into one server with a
flag because it is less code, that is the alternative the RFC explicitly
rejected.

**That isolation is about the money/security boundary — server process, tool
contract, system prompt — not about UI components, which should be SHARED.**
`AdminChat.tsx` originally hand-rolled its own conversation-history dropdown
instead of generalizing the customer surface's `HistoryMenu`
(`frontend/components/inventory/HistoryMenu.tsx`, RFC 0017), and shipped
missing three things `HistoryMenu` already had: click-outside-to-close,
rename/delete, and a last-edited date (owner report 2026-08-28). `HistoryMenu`
now takes an optional `client?: ConversationsClient` prop (default
`customerConversations`; the admin panel passes `adminConversations`) so both
surfaces read the identical, better-tested flyout. **"Structural isolation"
naming the four things that must differ is not license to rebuild everything
else too** — a component with no privileged data of its own (it only ever
renders what its `client` prop fetches) drifting into two maintained copies is
pure cost with no isolation benefit to show for it.

**The admin MCP server is PYTHON, not TypeScript** — `mcp` is already a backend
dependency, so it needs no npm workspace, no Dockerfile stage and no CI job,
and far more importantly its tools import `services/ledger.py` and
`services/condition_pricing.py` **directly**. A TypeScript mirror could pin a
*value* with a parity test; it could not pin a *call graph*, and
`services/ledger.py`'s docstring enumerates its readers exhaustively precisely
because the failure mode is a reader that forgets to call it.

**A contract-parity test that diffs only KEY SETS cannot catch a VALUE
collapsing to a meaningless stub.**
`test_each_tool_takes_exactly_the_arguments_the_contract_declares` has always
correctly asserted that `admin-tool-contract.json`'s `properties`/`required`
names match what the server implements — but `services/bedrock._admin_tool_schemas()`
built every one of those properties as a bare `{}` when handing them to
Bedrock, because the contract carried no per-property `type`/`description` at
all. The test was green the whole time; it was never able to see the
difference between a real schema and an empty one, because it was never
told to look at property VALUES, only property NAMES. The model, in
practice, was told a parameter named `start` exists and nothing else — which
is why "what's our most profitable show, all time?" kept getting answered
with a demand for exact dates (owner report 2026-08-28; fixed by giving every
admin tool property a real `type`/`description`, some an `enum`, and passing
them through instead of discarding them). This is the SAME failure shape as
`mcp-server/src/condition-pricing.ts` claiming cross-language pinning that no
test ever checked — a docstring or a test's own scope can both create false
confidence, and "a test exists and passes" is not the same claim as "the test
checks the thing that matters." Before trusting a parity test, check what it
actually diffs.

**`surface` scopes every conversation read, and `services/conversations.owned_rows()`
is the one place that does it.** `list_summaries`, `get_owned`, `prune_to_cap`
and `clear_all` all route through it — `prune_to_cap` especially, because it
DELETES: an unscoped 50-thread LRU cap would drop a quarterly margin analysis
as soon as that sub's combined thread count passed 50. Admin threads keep a
**two-year** TTL against the customer surface's six months, and that branch
lives in `_conversation_ttl` and nowhere else.

**`rate_limit_admin_chat` raises only the PER-USER tiers (30/min, 500/day) and
shares the same `global#chat` key.** A separate global counter would look
tidier and would let the two surfaces together spend twice the ceiling that
exists to bound the account's Bedrock bill — the ceiling is about dollars, and
Bedrock does not care which surface spent them.

**One chat request is bounded by three things, and the 30s Lambda timeout is
the weakest of them.** `_MAX_TOOL_TURNS = 5` / `_MAX_QUERY_TOOL_CALLS_PER_REQUEST
= 10` (`services/bedrock.py`) are the CUSTOMER-chat module defaults — one
assistant turn may emit any number of `toolUse` blocks, so without the second
guard forty of them run forty full inventory walks. Both are also
`BedrockChatService` CONSTRUCTOR parameters (RFC 0020 item 6, same seam
`tools`/`system_prompt` already use), so raising them for the admin analyst
does not silently widen the customer surface too: `get_admin_bedrock_service`
(`dependencies.py`) passes `max_tool_turns=6, max_query_tool_calls_per_request=14`
instead of the module defaults. The third guard, `McpToolExecutor`'s per-call
timeout, is shared by both surfaces — derived from
`LAMBDA_REQUEST_BUDGET_SECONDS` and pinned to the CDK stack's actual value by a
cross-boundary test.

Measured 2026-08-27 (customer/original four admin tools) via
`backend/scripts/measure_admin_chat_latency.py` against the live table: no tool
on either server exceeds **1.0s**, and the worst five-call sequence the OLD
5/10 ceiling permits is **3.6s** (round-trip-bound from a home connection —
`list_inventory` is ten *sequential* shard queries at ~82ms each here versus
~5ms in-region). Re-measured 2026-08-30 after RFC 0020's four raw-listing
tools (`list_shows`/`list_transactions`/`list_inventory`/`list_consignors`)
joined the admin surface: a 14-call sequence mixing all eight admin tools
measured **~15.6-16.9s** across two runs (52-57% of the 30s budget, same
home-connection caveat — production is faster, not slower). `list_shows` is
the single slowest admin tool (**~2.4s** median, an N+1 `get_show_analytics`
call per show) — still well under the per-call timeout, but the reason the
14-call total isn't as cheap as a flat "~1.0s per tool" estimate would
suggest.

# MCP Tools

**Two servers, two contracts, two processes.** The customer server is
TypeScript (`mcp-server/`, pinned to `shared/tool-contract.json`); the admin
server is Python (`backend/src/merlins_collection/mcp_admin/`, pinned to
`merlins_collection/admin-tool-contract.json` — inside the package, because
nothing outside the backend reads it and a repo-relative read does not survive
the image). They share **no tool name**, and there is a test asserting it.

**Customer** (`mcp-server/`, reached from `/inventory` chat mode):
- `get_inventory_summary` — total count, value, top cards
- `search_inventory` — filter by name, set, condition, value range
- `get_card_price_history` — historical price data for a card
- `calculate_inventory_value` — full valuation with breakdown by set/condition
- `flag_underpriced_cards` — cards listed below market price threshold

**Admin** (`mcp_admin/`, reached from the `/admin` analyst slide-over; every
tool is `readOnlyHint: true` and nothing here writes):
- `get_profit_summary` — gross, cost, net, margin for a date range, optionally
  one show. Bounds inclusive both ends; `margin_pct` is `None` on zero sales,
  never `0.0`
- `find_aging_stock` — held stock only, oldest first (a sold card is not
  "sitting on a shelf")
- `get_consignor_position` — what is held on each consignor's behalf.
  **`split_percent` is OUR cut, so the consignor's share is its complement**;
  archived consignors are included, because archiving is not settlement
- `find_pricing_outliers` — `over` / `under` / `unpriced`. An unknown direction
  raises rather than returning `[]`, and `unpriced` is its own direction rather
  than an infinite deviation

**`stale` / `max_age_days` are deliberately NOT built**, though RFC 0018's tool
table lists them: no inventory model carries a per-item price timestamp.
`value_note` mentions an age in *prose*, and parsing a number back out of a
sentence to drive a money answer is a guess wearing a filter's clothes.

**Four more admin tools joined in RFC 0020 — raw, filterable "librarian"
listings, not aggregates.** The four above stay unchanged (each encodes a
money/business rule cheap to keep correct in code and risky to re-derive from
a system prompt); these hand back rows and let the model do its own research,
scanning/summing/grouping/filtering over them itself where CLAUDE.md's
math-trust boundary allows (see `_ADMIN_SYSTEM_PROMPT` below):
- `list_shows` — every show, joined with its analytics snapshot when one
  exists, newest first. `has_analytics: false` (not `$0`) for a show never
  archived or manually analyzed
- `list_transactions` — raw ledger rows in a date range. Every row carries
  `is_countable`/`is_trade_cash_leg` so a raw sum, if ever unavoidable, can
  still exclude voids and trade cash legs correctly; capped at 100 rows with
  `total_matched`/`truncated` always present
- `list_inventory` — raw admin-visible inventory rows (cost basis,
  consignment terms, review flags), reusing the SAME
  `services.inventory_filters`/`services.inventory_sort` registries
  `GET /admin/inventory/search` validates against. A non-null `consignment`
  field means exclude that row before summing `cost_basis` as the business's
  own capital — stated in the tool description itself
- `list_consignors` — every consignor's identity and default
  `payout_percent` (THEIR share as a percent — the OPPOSITE convention from
  an item's `ConsignmentTerms.split_percent`, OUR cut as a 0-1 fraction).
  Not for computing a payout; call `get_consignor_position` for that

**`_ADMIN_SYSTEM_PROMPT` is "librarian" framing, not a lookup-table
instruction** (RFC 0020 item 7): broad read access, encouraged to
cross-reference and iterate rather than declare a question unanswerable; a
stated preference for the four narrow aggregate tools when one directly
answers, the four raw `list_*` tools for a breakdown/comparison/filter no
narrow tool offers; and the math-trust boundary itself as an instruction —
never sum `amount` across `list_transactions` rows for a profit/revenue
figure, call `get_profit_summary` instead.

# AWS Services
| Service         | Purpose                                              |
|-----------------|------------------------------------------------------|
| S3              | Card image storage, inventory data exports           |
| CloudFront      | CDN for serving card images                          |
| DynamoDB        | Card inventory database (flexible schema)            |
| Lambda          | Serverless price lookup and image processing         |
| API Gateway     | REST API gateway for the backend                     |
| Cognito         | Customer authentication                              |
| Rekognition     | Image analysis (future: identify cards from photos)  |
| Bedrock         | Claude AI integration for chat mode queries          |

# Third-Party APIs

Authority: [`docs/rfcs/0009-slab-intake-and-graded-pricing.md`](docs/rfcs/0009-slab-intake-and-graded-pricing.md),
with per-task status in [`docs/plans/rfc-0009/progress.md`](docs/plans/rfc-0009/progress.md).
An earlier version of this section pointed at "claude-progress.md Phase 4" — that
file has no Phase 4 and never will; the admin-enhancement rounds replaced it.

**Slab intake is MANUAL-FIRST, and that is the shipped design, not a stopgap.**
An admin types (or wedge-scans) the cert number, identifies the card through
catalog autocomplete with a free-text fallback, types company/grade/cost, stages
a batch and commits it through the existing buy session — so slabs land in
purchase history, timeline and show analytics like any other acquisition. There
is **no camera** (never built) and **no cert lookup** (see PSA below). Every
grading company goes down the same manual path; CGC/BGS/SGC are not a special
case any more.

- **PokemonPriceTracker — the graded price source, and the one that is LIVE.**
  Per-grade market values from eBay sold comps. Not PriceCharting: the owner
  declined a paid subscription on 2026-08-07, and any doc still naming
  PriceCharting is stale. Free tier is **100 credits per UTC day**, and a graded
  lookup costs **2 credits** (1 card + 1 `includeEbay`, `costPerCard: 2` read off
  a live response) — so the real ceiling is **FIFTY lookups a day**. You are
  billed on `limit` **even when the search matches zero cards**, which is why
  `limit=1` is pinned. Key: `POKEMONPRICETRACKER_API_KEY`; budget knob:
  `PRICING_DAILY_QUOTA` (credits, default 100).
- **PSA cert API — WITHDRAWN on 2026-08-10. This is a closed decision, not a
  gap.** The cert API became a **paid** feature and the owner declined it, so
  approval is **not coming** and nothing is waiting on it. RFC 0009 T2 (the
  lookup) and T5 (camera scan) are **WON'T DO**; RFC 0010 §H is the authority.
  - **Do not call it, do not email `collectors-apis@collectors.com`, and do not
    add a `psa_api_key` setting.** Every authenticated call ever made returned
    `403 {"Message":"Access to this API is limited to approved customers."}` —
    the key was valid, the **account was never entitled**, and no code change
    reaches it. Re-confirmed 2026-08-10 against their Swagger with both bearer
    spellings.
  - **`PSA_API_KEY` is read by no code and never will be.** There is no
    `psa_api_key` field on `Settings` and `model_config`'s `extra="ignore"`
    swallows the env var, so setting it does nothing at all. It was removed from
    `backend/.env.example` by RFC 0010 T14 for exactly that reason — a blank
    placeholder reads as *"configure me"* and cannot work.
    `test_config.py::test_there_is_still_no_psa_setting_to_configure` is a
    **permanent** tripwire on that absence, not a temporary one.
  - Nothing about its response shape was ever observed, so the mapper was never
    guessed at. Had it landed it would have supplied identity only:
    **`TotalPopulation`/`PopulationHigher` are always `null`** on the public API,
    so there is no population feature and no field for one.
  - The historical evidence — the 403 fixture, the key fingerprint, the Swagger
    findings — stays in `docs/plans/rfc-0009/`. It is the record of a decision
    made properly; deleting it would make the decision look casual.

**How a slab gets priced** (`services/slab/pricing.py`, wired by
`services/catalog_sync.py`):

- Prices live in the **pre-existing** `CARD#<card_id>` / `GRADEDPRICE#<company>#
  <grade>` rows. RFC 0009 added **no pricing schema** — the work was filling those
  rows from an API instead of by hand.
- `refresh_graded_prices` runs **nightly inside `run_daily_sync`** (step 3 of
  six) and also behind `POST /admin/slabs/refresh-prices` and the Market page's
  Sync Prices button. It walks owned slabs **stalest-first** (never-priced first),
  deduped by `(card_id, company, grade)`, capped at what today's credits can pay
  for. **It never calls PSA** — a cert's identity is immutable.
- **A price attaches only on a VERIFIED JOIN**: the vendor's `externalCatalogId`,
  read as `en:<id>`, must equal the item's own `card_id`. The vendor's name search
  returns the wrong card roughly a third of the time and a wrong answer looks
  exactly like a right one, so this rule is load-bearing. Japanese cards carry no
  `externalCatalogId` at all, so **JP slabs are unpriceable by construction** and
  are *not* Triage-flagged for it — they surface at `/admin/slabs?priced=false`.
- **A hand-typed graded price is REPLACED by the provider unless it is pinned**
  (owner decision, 2026-08-09). `PUT /admin/slabs/{id}/price/pin` sets the pin —
  but **no frontend control calls it yet**, so in practice nothing is pinned and
  the provider always wins. Anyone typing a graded value today should know it will
  be overwritten on the next run.

Both keys are bearer tokens spending a metered daily quota: never log one, never
return one from an endpoint. Real values live in `backend/.env` (gitignored) and,
in production, in the ECS task definition's plain `environment` array — owner
decision, 2026-08-12, explicitly declining Secrets Manager for these two keys
in favor of the same mechanism every other non-AWS config value already uses
(see `docs/aws-setup.md`'s "Outbound third-party credentials" section). Do not
reintroduce a `secrets`/Secrets Manager reference for these. An empty key
is a supported state: `build_pricing_provider()` returns `None`, the nightly job
skips graded pricing and every other step still runs, while the admin button
reports `state: "failed"` because a human is standing there waiting.

# Design System
- Color scheme based on Spriggatito (forest greens, cream whites)
- Business/brand images stored in `frontend/public/images/` organized by:
  - `logo/` — logo variants
  - `brand/` — business photos, team, storefront
  - `shows/` — card show photos
  - `cards/` — card reference images

# Code Review
All PRs require review. CODEOWNERS enforces review by @EthanHarter934.
Branch protection rules must be enabled in GitHub Settings > Branches:
- Require a pull request before merging
- Require status checks (CI) to pass
- Require review from Code Owners

# AWS Guidance

- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.
