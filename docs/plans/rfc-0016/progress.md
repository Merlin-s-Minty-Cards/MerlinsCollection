# RFC 0016 Progress — Chat Display Artifacts

Migrated 2026-08-24 from Kiro's `.kiro/plans/0001-chat-experience/progress.md`
(gitignored, tool-local). This file is now the plan of record; see the parent
`README.md` for the full migration note.

## Goal

Three sequenced features on the chat surface (Plan 0001, of which this RFC is
Phase 1):

1. **Display artifacts** (RFC-0016, this file) — the model renders individual
   cards inline in the chat and controls a pop-out panel for larger result
   sets, instead of writing card details out as prose.
2. **Conversation history** (RFC-0017, not started) — per-user, persisted,
   with new/rename/delete-one/clear-all.
3. **Admin analyst chat** (RFC-0018, not started) — same capabilities as the
   inventory chat, plus read-only access to every admin domain, computed
   aggregates, and charts.

Phases are strictly ordered: 3 depends on 1 and 2 ("all the capabilities of
the inventory chat"), and 1's panel persistence depends on 2's storage
schema, so 1 was designed with 2's schema already sketched (see RFC-0016
§12, "Panel Persistence Shape").

## Done-when (Phase 1 / RFC-0016)

- A card can be displayed inline with name, set, number, image, market
  price, and condition/grade, sourced from DynamoDB rather than
  model-authored text.
- The model can set the panel's contents (open/close/reorder, via a single
  `set_display(item_ids)` call per decision 23 below).
- Backend, frontend, and mcp-server suites green. Lint clean both sides.

(Phase 2/3 done-when criteria are recorded under "Decisions on record" below
for continuity; they are not this RFC's scope.)

## Baseline (observed 2026-08-24, this migration)

- Repo: `/home/ethar/kiro/projects/MerlinsCollection`, WSL2
  (`Linux ... 6.18.33.1-microsoft-standard-WSL2`). The user switched from
  Windows to WSL as the primary dev environment around this date; see
  "Environment notes" below for what that changed.
- Branch `Inventory-Chat-Design`, commit `f35393c` (RED, from the prior
  session) plus `06d86f1` (unrelated docs cleanup made during this
  migration — see "Housekeeping" below). Tree otherwise clean, 13 commits
  ahead of `origin/Inventory-Chat-Design`.
- `frontend/package.json`: next ^15.3.0, react ^18.3.0, next-auth
  5.0.0-beta.31, chart.js 4.4.7 + react-chartjs-2 5.3.0 already pinned (no
  new dependency needed for Phase 3's charts, when that starts).
- Backend deploys as a single `lambda.DockerImageFunction`
  (`infra/lib/backend-stack.ts`) whose execution role holds full read/write
  DynamoDB. The MCP server runs as a child process of that Lambda
  (`services/mcp_client.py`), inheriting those credentials.
- `shared/tool-contract.json` is the single source of truth for tool
  contracts; both `services/bedrock.py::_TOOLS` and `mcp-server/src/server.ts`
  assert against it. **Change the contract first, then both sides.** Verified
  2026-08-24: the contract already declares the 7-tool surface (5 query +
  `display_card` + `set_display`) and a
  `resultShapes.search_inventory.requiredFields = ["id", "item_id", "name"]`
  declaration — this was done in the RED commits, GREEN has not caught up.
- DynamoDB single-table: `PK`/`SK` + `GSI1` + `GSI2`, every item carries an
  `entity` tag.
- `rate_limit.py` is DynamoDB-backed and distributed; `/chat` **fails
  closed** (503) because Bedrock costs money per call.
- Verification commands: see CLAUDE.md's "Test Commands" section (updated
  2026-08-24 for WSL — see "Environment notes"). Backend ~2-3 min (measured
  live this session: 2m35s for 2087 tests), frontend ~25-30s, MCP ~1s.

## Blocking constraints found in existing code (still true)

- **No structured model→UI channel.** `ChatResponse` was `{reply: str}`
  before this RFC; `BedrockChatService.chat()` returned a joined string and
  MCP tool results were flattened to text before re-entering the model's
  context. Artifacts require a new response envelope, not just new tools —
  the envelope is designed (RFC-0016 §1) but not yet implemented.
- **History is client-owned today.** `ChatPanel.buildHistory()` rebuilds
  turns from React state and ships them every request; the backend validates
  strict alternation and replays them. Phase 2 (server-side persistence)
  will make `/chat` take a `conversation_id` instead — a breaking change to
  `ChatRequest`, not this phase's problem.
- **`_MAX_TOOL_TURNS = 5`** currently. Display tools and (later) analyst
  tools both consume turns; RFC-0016 keeps this at 5 (see decision 23 below —
  the `set_display` collapse removed the need to raise it).

## Decisions on record

All confirmed by the owner during original planning. Do not re-litigate
these.

### Display (RFC-0016 — this phase)
| # | Decision |
|---|---|
| 1 | Reorder is **model-driven**. User drag-and-drop is explicitly out of scope. (Superseded in mechanism, not intent, by decision 23: reorder is now expressed via `set_display`'s list order, not a standalone `reorder_display` tool.) |
| 2 | Panel state **persists** per conversation; resuming a conversation restores its panel. |
| 3 | **No panel on mobile** — cards render inline only. |
| 4 | Panel entries **re-hydrate live** on load; prices and availability are current, not snapshots. |
| 5 | Panel caps at **50 cards**; the tool returns a truncation notice the model must relay. |
| 6 | `_MAX_TOOL_TURNS`: exact ceiling reviewed by the adversarial pass — **resolved by decision 23**, stays at 5. |
| 20 | Admin chat (Phase 3) is a slide-over from every admin page, full-screen expand. Model may open/close; **fullscreen is a user-only gesture**. |
| — | **Model passes IDs only, never card data.** Display tools take `item_id`; the backend hydrates from `InventoryRepository` during the tool loop. Prevents hallucinated prices — the actual mechanism for "stop writing details in prose". |
| 23 | **Collapse the four/five panel-mutation tools into one `set_display(item_ids)`.** Owner decision, taken after Council r1 (verdict FAIL) surfaced the architect's cross-cutting recommendation as an owner question. `add_to_display`, `remove_from_display`, `reorder_display`, and `open_display_panel`/`close_display_panel` are replaced by a single tool receiving the complete intended panel contents in intended order. **Supersedes decision 1's tool-surface mechanism, not its intent** — reorder stays model-driven via list order. Empty list means closed. Rationale: collapses "1 search + 1 open + 8 adds" from ~10 turns to 2, resolving the `_MAX_TOOL_TURNS`/30s-Lambda-timeout conflict and the ~26k-calls/day cost item outright, and removes the round-tripped panel state that Council items 7-8 were defects in. `display_card` (inline, single card) is unaffected. Final tool count: 5 query + `display_card` + `set_display` = **7**. |

### History (RFC-0017 — Phase 2, not started)
| # | Decision |
|---|---|
| 7 | 6-month TTL on conversations. |
| 8 | Cap 50 conversations per user, oldest auto-pruned. |
| 9 | Titles are free — first ~50 chars of the opening message. No extra Bedrock call. User can rename. |
| 10 | Hard delete, not soft. |
| 11 | Admins cannot read other users' conversations. No route exposes them. |
| 12 | Chat requires login. History keys on Cognito `sub`. |
| — | Schema: `PK=USER#<sub>` / `SK=CONV#<created_at>#<conv_id>` for the index; `PK=CONV#<conv_id>` / `SK=MSG#<seq>` one item per message (artifacts inflate payloads; 400KB item limit is a real ceiling). Every read/write asserts owning `sub` == caller. |

### Admin analyst (RFC-0018 — Phase 3, not started)
| # | Decision |
|---|---|
| 13 | Same model (Claude Sonnet 4.5). "Upgraded" = more tools, not a different tier. |
| 14 | Option A — STS session credentials. One new read-only IAM role; backend calls `sts:AssumeRole` and passes temporary creds to the analyst MCP subprocess via env. Writes become impossible at the IAM layer, not by prompt. |
| 15 | All 15 admin domains, read-only: inventory, market, sales, purchases, trades, show_prep, analytics, cosigners, locations, slabs, triage, unmatched, vault, catalog, shows. |
| 16 | Analyst scope = the ten questions in the original RFC brainstorm (revenue trends, margin, sell-through, per-show profitability, overpay/underprice, capital concentration, buy-vs-trade outcomes, consignor performance, market-price drift, restock suggestions). Owner may add more. |
| 17 | Low-confidence signal on thin data. Aggregate tools return an explicit minimum-sample flag; the prompt requires the model to surface it. |
| 18 | Charts: line, bar, stacked bar, pie/doughnut, scatter. Via a typed `render_chart(type, series, labels)` tool rendered by the already-installed Chart.js. No model-authored code or images. |
| 19 | Admin is exempt from the per-minute burst cap, the per-user daily cap, and the global customer ceiling. Retain one high circuit breaker purely as runaway-loop protection. |
| — | Aggregates are computed in Python, not by the model. Margin, sell-through rate, days-in-inventory, velocity-by-set all arrive as numbers. |

### Process
| # | Decision |
|---|---|
| 22 | Plan state originally lived in `.kiro/plans/` (Kiro-local, gitignored). **Superseded 2026-08-24**: this directory (`docs/plans/rfc-0016/`) is now the plan of record. RFCs continue the existing `docs/rfcs/` numbering as 0016 / 0017 / 0018. |
| 23 | See "Display" table above — the `set_display` collapse. |

## Items

### Phase 0 — housekeeping (Kiro session)
- [x] Discard phantom CRLF diffs on 5 files (verified byte-identical; pure EOL churn)
- [x] Normalize all 13 `.kiro/agents/*.md` to LF; add scoped `.gitattributes` — `c4ae479`
- [x] Resolve the Kiro `subagent` tool-grant blocker (Kiro-specific, not applicable to Claude Code)

### Housekeeping (this migration, 2026-08-24)
- [x] Restored 8 RFCs (0009-0016) and `.claude-pr-description-rfc-0013.md` that had
      been deleted from disk but still tracked in git with no other pending changes —
      the owner confirmed the deletion was intentional cleanup but, per an age check
      against today's date, most of `docs/rfcs/` was under two weeks old and RFC-0016
      itself (this one) was only 3 days old and actively in-progress. Committed the
      narrower deletion (`docs/rfcs/0001-0008` + `docs/superpowers/`, genuinely
      2+ weeks old) as `06d86f1`.
- [x] Fixed three WSL/Linux cross-platform gaps in test tooling (see "Environment
      notes" below): CLAUDE.md's Test Commands table, `scripts/run-tests.cmd`'s
      hardcoded stale-clone path, and root `package.json`'s `test:backend` script.
- [x] Migrated this plan from `.kiro/plans/0001-chat-experience/` to
      `docs/plans/rfc-0016/`.

### Phase 1 — RFC-0016 display artifacts (Kiro session, pre-Council)
- [x] RFC-0016 written to `docs/rfcs/0016-chat-display-artifacts.md` — `80c317b`.
- [x] Extended `shared/tool-contract.json` with the display tools (contract first) — `a3954d0`.
      (First draft: 11 tools total. Later collapsed to 7 by decision 23 — see below.)
- [x] RED (first draft): failing tests for envelope, hydration, 50-cap, ownership — `a3954d0`.

      | Suite | Result |
      |---|---|
      | Backend (pytest) | 70 failed, 1986 passed in 3m48s |
      | Frontend (vitest) | 21 failed, 1002 passed (4 of 100 files) |
      | MCP (vitest) | 7 files passed, 0 failed (correct: display tools must never register there) |
      | `ruff check backend/src` | clean |

- [x] GREEN (first draft) — `bd66abc`. Backend 2056 passed / 0 failed, frontend
      100 files / 1023 tests, MCP 7 files / 98 tests, `ruff` clean, `next lint` exit 0.
- [x] `{reply, artifacts, panel}` response envelope; `ChatResponse` keeps `reply`
- [x] Server-side hydration of `item_id` → full card record (**defective — see
      Council r1 below, fixed by GREEN items 1-3**)
- [x] Display tools (first draft, later collapsed): `display_card`,
      `open_display_panel`, `close_display_panel`, `add_to_display`,
      `remove_from_display`, `reorder_display`
- [x] `_MAX_TOOL_TURNS` raised to 12 (first draft — **reverted to 5 by decision 23**)
- [x] Extracted shared card presentation from `CardTile.tsx` into `CardPresentation.tsx`
- [x] Panel UI: closed / docked / fullscreen; desktop only

**Written, but NOT accepted — Council r1 returned FAIL.** See
[`council-r1-verdict.md`](council-r1-verdict.md) for the full 11-item
blocking checklist. Owner resolved the open architect question with decision
23 (the `set_display` collapse) rather than keeping the original six-tool
surface.

### Phase 1 remediation (post-r1, Kiro session — RED only, GREEN not started)
- [x] Amended RFC-0016 to reflect decision 23 — `a2b83dc`. Two passes: first
      amended only the front matter, leaving the risks table / open questions /
      test plan / implementation checklist describing the superseded six-tool
      design and `_MAX_TOOL_TURNS = 12`; second pass reconciled the whole
      document, marking deltas `[AMENDED POST-R1]` / `[DISSOLVED POST-R1]`.
      Note: the customer-visibility predicate lives in
      `routers/inventory.py::customer_visible_items`, not `services/dynamodb.py`
      — a brief in the Kiro session said the latter and was wrong; verify
      against source, not against any brief, when implementing item 2.
- [x] Filed the verdict's 12 non-blocking minors to `follow-ups.md`
- [x] Updated `shared/tool-contract.json` to the 7-tool surface — `91116db`.
- [x] RED (r2, first draft): integration test composing a real
      `search_inventory` result into a display call; visibility-predicate
      tests; `set_display` state tests — `91116db`.

      | Suite | Result |
      |---|---|
      | Backend (pytest) | 49 failed, 2038 passed (2087) in 2m43s |
      | Frontend (vitest) | 10 failed, 1010 passed (1020) |
      | MCP (vitest) | 2 failed, 98 passed (100) |
      | `ruff check backend/src` | clean |
      | `next lint` | 0 errors, 2 pre-existing warnings |

      **This RED draft was wrong and had to be corrected** — see next entry.
      It pinned the superseded design: three backend tests asserted
      `panel.open is True`, direct inverse of RFC-0016's `len(cards) == 0`
      means closed. Now pinned by `"open" not in DisplayPanel.model_fields`.

- [x] **RED correction** — `f858564`. `code-writer` (Kiro's implementation
      agent) BLOCKED GREEN on four defects in `91116db`; all four verified
      against source and real:

      1. The integration test for checklist item 1 pinned the **forbidden
         fix** — it had the model pass a `card_id` to `display_card`, which
         would only be satisfiable by widening the backend to accept
         card_ids (the exact fix the verdict rules out). Rewritten so the
         mocked search result carries a per-unit `item_id` and the model
         passes that. **This backend test now PASSES by design** — it's a
         consumer-contract regression guard, not RED, since mocking the tool
         executor bypasses the actual MCP-side bug. **The real RED for item
         1 is `mcp-server/src/__tests__/item-id-field.test.ts`** (a real MCP
         client/server over `InMemoryTransport`).
      2. An unconditional `pytest.fail()` describing the fix in prose,
         unsatisfiable by any implementation. Deleted.
      3. Two Phase-1-era test files were never migrated off the superseded
         design and were passing while pinning it — the dangerous kind,
         since GREEN would satisfy them by keeping the old design:
         `cert_image_url` presence (item 5 removes it), and a tri-state
         `DisplayPanel.open` field (decision 23 deletes it entirely).
      4. Three more `.open` leftovers the agent's own audit reported as zero
         matches. Fixed directly rather than a fourth dispatch.

      **Process lesson, carried forward:** an agent's audit of its own work
      is not evidence; the grep is. Three separate rounds each reported "0
      matches" while leftovers remained. Also check
      `git --no-pager diff --stat` for non-test files before trusting any
      RED report — one dispatch edited `ChatPanel.tsx` and `lib/inventory.ts`
      during RED; both were reverted.

      | Suite | Result |
      |---|---|
      | Backend (pytest) | 50 failed, 2037 passed (2087) |
      | Frontend (vitest) | 10 failed, 1010 passed (1020) |
      | MCP (vitest) | 2 failed, 99 passed (101) |

- [x] **RED correction round 2** — `8edbf7f`. Fixed RED fixtures and the
      sealed-item visibility expectation for checklist item 2: fixtures
      across `test_display_hydration.py`, `test_bedrock_display_tools.py`,
      `test_display_state.py` etc. didn't set `location` on their
      `RawInventoryItem` fixtures, which would fail post-fix for the wrong
      reason once `_hydrate_item` enforces the full visibility predicate.
      Also inverted one test that asserted a sealed product (booster box)
      successfully hydrates — RFC-0016's amended predicate adopts RFC-0001's
      binding `_CUSTOMER_KINDS = {"raw", "graded"}`, so hydration must now
      **refuse** a sealed item.
- [x] **RED correction round 3** — `f35393c`. One more leftover, caught only
      on a broader audit: `test_chat.py` asserted the JSON wire response
      includes `"panel": {"open": None, ...}` — a Python dict-literal shape
      earlier greps (for `.open is`, `open: null`, `DisplayPanel(open=`)
      hadn't matched. Removed.

      **Current verified-failing baseline at `f35393c`** (per the handoff;
      backend re-confirmed live during this migration at 53/2034/2087, one
      test off — see README.md's Status section):

      | Suite | Failed | Passed | Total |
      |---|---|---|---|
      | Backend (pytest) | 52 | 2035 | 2087 |
      | Frontend (vitest) | 10 | 1010 | 1020 |
      | MCP server (vitest) | 2 | 99 | 101 |

- [ ] **GREEN: checklist items 1-6, 9 (reduced), 11 — not started.** See
      README.md's task table for the compressed list, `council-r1-verdict.md`
      for full detail.
- [ ] Council r2 — re-review per the verdict's re-review scope (all four
      lenses: contrarian, architect, chaos, security)

### Phase 2 — RFC-0017 history (not started)
- [ ] RFC-0017 written
- [ ] RED: ownership isolation, TTL, 50-cap pruning, hard delete
- [ ] Conversation + message items, TTL, prune-at-50
- [ ] `/chat` takes `conversation_id`; retire client-sent history
- [ ] Routes: list, fetch, rename, delete-one, clear-all, new
- [ ] Panel state persisted per conversation (closes the loop with Phase 1)
- [ ] Frontend history sidebar
- [ ] Adversarial pass, then GREEN

### Phase 3 — RFC-0018 admin analyst (not started)
- [ ] RFC-0018 written
- [ ] CDK: read-only IAM role + `sts:AssumeRole` grant
- [ ] Credential vending + refresh for the analyst MCP subprocess
- [ ] RED: prove a write is rejected at the IAM layer, not just absent from the tool list
- [ ] Read-only analyst MCP server / tool registry across all 15 domains
- [ ] Python-computed aggregates with minimum-sample confidence flags
- [ ] `render_chart` typed tool + Chart.js renderer
- [ ] Admin rate-limit tier: exempt from user + global caps, one high circuit breaker
- [ ] Slide-over on every admin page, fullscreen expand
- [ ] Adversarial pass, then GREEN
- [ ] Review the `_MAX_TOOL_TURNS` ceiling chosen in Phase 1 (per decision 6)

## Council r1 — summary (full detail in `council-r1-verdict.md`)

Convened on `bd66abc` (the first GREEN). All four seats filed across two
passes (security's first attempt hit a network error and had to be
re-spawned on the unchanged submission). **Verdict: FAIL**, 11-item ordered
blocking checklist, plus 12 non-blocking minors filed to `follow-ups.md`.

Four independent gating defects, on four different lanes (contrarian,
architect, chaos, security), converging on the same handful of functions
(`_hydrate_item`, `_DisplayState`, and the display-tool dispatch) — not a
close call. Items 1-6 are one rewrite of `_hydrate_item` and the card
projection; items 7-9 are the panel state machine; items 10-11 are the
turn/work ceiling.

**Owner resolved the architect's cross-cutting recommendation as decision
23** (the `set_display` collapse). Effect on the checklist: items 7 and 8
(tri-state `open` write-only; close-then-add) dissolve entirely — no
incremental panel state is left to desynchronize. Item 10 (12 turns vs 30s
Lambda timeout) is resolved by the turn reduction, not per-call budgeting.
Item 9 shrinks but doesn't vanish — `set_display` still needs the model told
current contents, satisfied by echoing resulting panel contents in the tool
result and injecting restored contents at request start. Items 1-6 and 11
are unaffected by the collapse.

## Environment notes

**This migration (2026-08-24) is a Windows → WSL move.** Three clones
existed historically per the Kiro session's own notes (this WSL one at
`/home/ethar/kiro/projects/MerlinsCollection`, plus two stale ones under
`/mnt/c/Users/ethar/.cursor/projects/...`) — this WSL clone is the one this
plan now lives in. Fixed as part of this migration:

- **CLAUDE.md's Test Commands table** hardcoded a Windows-only venv path
  (`./.venv/Scripts/python.exe`) that does not exist on this host — the
  actual Linux venv is `backend/.venv/bin/python` (verified working,
  Python 3.14.4, pytest 9.1.1, ruff 0.16.4). Table now lists both platforms
  side by side with a one-line "check which one is present first" snippet.
- **`scripts/run-tests.cmd`** (the Windows counterpart to
  `scripts/run-tests.sh`, which was already WSL-correct — see below)
  hardcoded an absolute path to `MerlinsCollection-Secondary`, one of the
  two stale clones. Now resolves `%~dp0..` (its own location's parent)
  instead, so it works from whichever clone it's copied into.
- **Root `package.json`'s `test:backend` script** was Windows-only
  (`.venv\Scripts\python.exe`), a known pre-existing gap the Kiro session
  had already logged as a non-blocking follow-up. Replaced with
  `node scripts/run-backend-tests.js`, a small cross-platform resolver
  (tries `backend/.venv/bin/python`, then two Windows venv layouts, then
  `python3`/`python` on PATH) — Node is available under both `cmd.exe` and
  `sh`, so this is the one thing that can branch correctly regardless of
  which shell npm picks for the OS.

`scripts/run-tests.sh` itself needed no fix — it already prefers
`backend/.venv/bin/python`, falling back to `python3`/`python3` on PATH, and
fails loudly with no interpreter rather than silently reporting zero tests.
It was fixed for this in the Kiro session (`fba5dc0`) before this migration
started.

**On "the owner runs all tests" (Kiro's `terminal.md`): this does not apply
to Claude Code.** That was a workaround for Kiro's `execute_bash` having a
hard ~10-15s effective timeout with no way to wait for a background job
except polling (which is separately billed and once burned a quarter of a
month's budget). Claude Code's Bash tool can run a suite directly and be
notified on completion without polling — this migration's own backend
re-run (2m35s, no manual polling) demonstrates that directly. Do not import
the "hand it to the owner" rule into a Claude Code session; it solves a
problem this tool doesn't have.

**Never let git open a pager.** Kiro's session hit this hard: a bare
`git diff` opened `less`, which stayed resident and silently swallowed
subsequent commands as keystrokes. Use `git --no-pager <cmd>`. This applies
regardless of tool.

**Line endings:** `.gitattributes` pins authored file types to LF. Before it
existed, Windows-side edits produced phantom diffs (every line "changed" but
byte-identical) on 13 agent files, 4 skill files, and `scripts/run-tests.sh`.
If a diff's `--numstat` is symmetrical (e.g. `26 26`), suspect line endings
before content.

## Log

- 2026-08-24 — Migrated plan from Kiro's `.kiro/plans/0001-chat-experience/`
  to this directory per the repo owner's request, following the handoff at
  (the now-deleted) `HANDOFF-to-claude-code.md`. Along the way: restored 8
  RFCs that had been deleted from disk but not committed (owner confirmed
  intentional cleanup, narrowed to genuinely-old files after an age check),
  committed that narrower deletion as `06d86f1`, and fixed three WSL/Linux
  cross-platform gaps in test tooling. Backend suite re-run live as a
  one-time sanity check: 53 failed / 2034 passed / 2087 total, matching the
  handoff's claimed baseline closely enough to trust it. GREEN work
  (checklist items 1-6, 9 reduced, 11) has not started.
