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

- [x] **GREEN item 1 (FATAL)** — 2026-08-24. Added `itemId: string` to the MCP
      `Card` type (`repository.ts`), `item_id: string` to `CardResult`
      (`tools/search-inventory.ts`, mapped from `card.itemId`), and populated
      `itemId: String(row.item_id)` in both branches of `toCard()`
      (`dynamodb-repository.ts` — sealed and raw/graded; sealed is confirmed
      dead code today per `isPublicInventory`'s kind gate, added anyway for
      type correctness). Two pre-existing tests needed a companion update
      (exact `.toEqual` assertions that didn't yet know about the new field):
      `search-inventory.test.ts`'s "returns all cards" case, and
      `dynamodb-repository.test.ts`'s "joins inventory items with catalog
      metadata" case — the latter is the one that actually proves `toCard()`
      populates `itemId` through the real `DynamoDbInventoryRepository` path,
      not just the in-memory test double `item-id-field.test.ts` uses.
      Pre-change and post-change adversarial review both PASS (no blocking
      findings either pass). Verified: `tsc --noEmit` clean,
      `npx vitest run` — **101/101 passing** (was 99/101), including both
      `item-id-field.test.ts` cases and `server.test.ts`'s contract-shape
      test. Backend/frontend untouched by this item (RFC §6: "the MCP server
      keeps its existing 5 query tools unchanged... display tools are purely
      backend-side" — item 1 is producer-side only).
- [x] **GREEN items 2-6, 9 (reduced), 11, and the frontend half of decision
      23 — 2026-08-24.** Delivered as one rewrite, per the verdict's own
      grouping ("items 1-6 all touch `_hydrate_item`/`_DisplayState.__init__`/
      `_run_display_tool` and should be delivered as one rewrite").

      **Item 2** (customer-visibility predicate): extracted into a new
      module, `services/customer_visibility.py::is_customer_visible` —
      logic is byte-for-byte what `customer_visible_items` already had, just
      given one shared home. It could NOT live in `routers/inventory.py`
      itself as the verdict's own wording suggested: `bedrock.py` cannot
      import from there without a circular import (`routers/inventory.py`
      imports `dependencies.py` for `get_repo`, and `dependencies.py`
      imports `BedrockChatService` from `bedrock.py`). The new module sits
      below both, like `services/condition_pricing.py` already does — both
      `routers/inventory.py::customer_visible_items` and
      `bedrock.py::_hydrate_item` now call the one function.
      `test_display_ownership.py` (7 tests, storage/bulk/factory-sealed/
      graded-glass cases) all pass.

      **Item 3** (price derivation): `_hydrate_item` now resolves
      `DisplayedCard.listed_price` the same way
      `routers/inventory.py::_display_price` does — for raw items, the live
      catalog price via `market_price_and_finish` (the same shared lookup
      `CardSummary.from_catalog` uses internally), condition-adjusted via
      `apply_condition_adjustment` exactly as `_condition_adjust` applies it
      at enrichment, falling back to the item's own `listed_price` when no
      catalog price exists. For graded, always `listed_price` (a slab's
      grade premium, never the ungraded catalog figure) — matches
      `_display_price`'s own graded branch. **Mirrored, not imported**: same
      circular-import constraint as item 2 blocks importing
      `_display_price`/`_enrich` directly (`_enrich` lives in
      `routers/inventory.py` too). Documented explicitly in `_hydrate_item`'s
      docstring so a future reader isn't left to guess why. `current_market_value`
      is unchanged — a separate, raw pass-through of the item's own stored
      figure, not the resolved display price. `test_display_price_derivation.py`
      (4 tests: DMG-adjustment, live-vs-stale, graded-skips-catalog,
      uncatalogued-fallback) all pass, after fixing two genuine fixture bugs
      unrelated to the behavior under test (see "Fixture bugs found and
      fixed" below).

      **Item 4** (error isolation): `_hydrate_item` never raises — wraps its
      body in `try/except (ClientError, ValidationError, AttributeError,
      TypeError, KeyError)`, logs a warning, returns `None` (treated as "not
      available" by every caller). Broader than the verdict's literal
      `ClientError`/`ValidationError` pairing because the RED test's
      `CorruptRepo` returns a bare dict rather than a validated model,
      which fails attribute access with `AttributeError`, not
      `ValidationError` — matches this codebase's existing
      `except Exception as exc:  # noqa: BLE001` precedent elsewhere
      (`catalog_sync.py`, `spreadsheet_import.py`) for exactly this class of
      per-item isolation boundary. `test_display_error_isolation.py` (4
      tests: throttled restore, corrupt data, tool-call throttle, 50-card
      partial-throttle) all pass.

      **Item 5** (`cert_image_url`): removed from `DisplayedCard`
      (`models/chat.py`) entirely — not nulled, not filtered at
      serialization, the field does not exist on the model — and from the
      frontend's `DisplayedCard` type (`lib/inventory.ts`). `_hydrate_item`
      never sets it (it was never added to the new hydration code).

      **Item 6** (JSON safety): every tool-result string in `bedrock.py` is
      now built with `json.dumps`, not f-string interpolation — verified
      against `test_display_tool_json.py`'s quoted/backslash item_id and
      display_name cases (6 tests) and `test_display_security.py`'s
      matching pair.

      **Item 9, reduced** (panel contents told to the model): two
      mechanisms. (a) At `chat()`'s start, if the restored panel is
      non-empty, a text block naming each card (`"Charizard (item-1),
      Pikachu (item-2)"`) is inserted before the user's message — both the
      names (useful) and the raw item_ids (composable) per
      `test_panel_context_includes_card_names_not_just_ids` and
      `test_restored_panel_item_ids_are_injected_into_initial_messages`.
      (b) `set_display`'s tool result always echoes the resulting panel's
      `item_id` + name per card (or `{"status":"closed","cards":[]}` for an
      empty list), so "remove the Charizard" composes as
      `set_display(echoed_ids - {that one})` without a read tool. Verified
      via `test_set_display_composes_remove_operation` (the actual use case)
      plus `test_display_panel_context_injection.py` and
      `test_display_panel_visibility.py`.

      **Item 11** (work ceiling): two independent bounds, both checked
      BEFORE I/O, not after. `_DisplayState.__init__` dedupes+caps
      `panel_item_ids` before any repository read (50 duplicate IDs now cost
      1 read, not 50). `_run_set_display` dedupes+caps `item_ids` before
      hydrating (100 IDs now cost ≤50 reads, not 100). A new per-request
      ceiling, `_MAX_HYDRATION_BLOCKS_PER_REQUEST = 10`, bounds the number of
      display-tool *invocations* (not items hydrated within one) — 60
      separate `display_card` calls in one turn now execute only the first
      10. `artifacts` is capped at `_MAX_ARTIFACTS = 50`, matching
      `panel.cards`'s existing cap. `test_display_work_ceiling.py` (5 tests)
      all pass.

      **The `set_display` collapse itself (decision 23):** `_TOOLS` now
      lists exactly 7 entries (5 query + `display_card` + `set_display`);
      the five panel-mutation tools and their `_DisplayState` methods
      (`open_panel`/`close_panel`/`add_to_panel`/`remove_from_panel`/
      `reorder_panel`) are deleted, replaced by one `set_panel(cards)` that
      replaces the panel wholesale (dedupe by item_id, cap at 50, self-detects
      truncation when called directly with >50 — or accepts an explicit
      `input_truncated` flag from a caller that already capped IDs before
      hydrating, so the truncation notice survives item 11's "cap before I/O"
      requirement even though the hydrated list arrives already ≤50).
      `DisplayPanel.open` deleted from the model (verified via
      `not hasattr`, not just a default check). `_MAX_TOOL_TURNS` reverted
      to 5. `test_set_display_state_machine.py` (11 tests) and
      `test_bedrock_display_tools.py`'s updated set_display cases pass.

      **Frontend (item 10 in this directory's numbering):**
      `DisplayPanel.tsx` takes no `open` prop, renders `null` when
      `cards.length === 0`; `ChatPanel.tsx` gates the `<DisplayPanel>` render
      on `displayPanel.cards.length > 0` and drops `open` from its
      `EMPTY_PANEL`/close-handler state; `lib/inventory.ts` drops `open` from
      `DisplayPanelState` and `cert_image_url` from `DisplayedCard`.

      **Fixture bugs found and fixed (not behavioral changes):** three
      RED test files constructed `GradedInventoryItem` with a field name
      that doesn't exist (`grader="PSA"` instead of `company=GradingCompany.PSA`,
      and `grade="10"` as a string instead of `Decimal("10")`) —
      `test_display_ownership.py`, `test_display_price_derivation.py`,
      `test_display_security.py`. One (`test_display_price_derivation.py`'s
      `_catalog_card` helper) was also missing the required `last_synced_at`
      field and used a non-existent `tcg_player_normal` kwarg instead of the
      real `prices={"normal": FinishPrice(market=...)}` shape — meaning even
      once the missing-field error was fixed, the fixture still wouldn't
      have exercised the price-adjustment path it exists to test, since
      `catalog.prices` would have stayed empty. One test in
      `test_display_panel_visibility.py`
      (`test_set_display_empty_list_closes_panel_and_echoes_closed_state`)
      had a mock `converse()` `side_effect` queue one response short (each
      of the test's two `chat()` calls needs its own tool_use + end_turn
      pair; only 3 responses were queued for 4 needed calls), causing
      `StopIteration` on the second call — added the missing `end_turn`.
      None of these touched an assertion; all were setup-code bugs unrelated
      to the behavior each test exists to verify. Also updated
      `tests/test_cross_boundary.py`'s import of `_CUSTOMER_VISIBLE_LOCATIONS`
      (a pre-existing, non-RFC-0016 test) to the new
      `services/customer_visibility.py` home — the assertion itself is
      untouched.

      **Verified, full suites, all three:**

      | Suite | Result |
      |---|---|
      | Backend (pytest) | **2087 passed, 0 failed** |
      | Frontend (vitest) | **1020 passed, 0 failed** (100/100 files) |
      | MCP server (vitest) | **101 passed, 0 failed** |
      | `ruff check backend/src` | clean |
      | `tsc --noEmit` (mcp-server) | clean |
      | `next lint` | 0 errors, 2 pre-existing warnings (unrelated files) |

      Matches the plan's stated "Definition of done" exactly.

      Pre-change and post-change adversarial review both done inline
      (logic/security/chaos/bloat), per item and again across the full
      diff at the end. No blocking findings either pass. See
      `council-r2-self-review.md` for the systematic per-checklist-item
      walkthrough and two findings surfaced (not silently fixed):

      1. `DisplayedCard.kind` still admits `'sealed'`/`'bulk'` on the wire —
         unchanged from the original flag in `council-r1-verdict.md`.
      2. **New finding**: the frontend's price display
         (`card.current_market_value ?? card.listed_price` in both
         `DisplayPanel.tsx` and `ChatPanel.tsx`) now has its precedence
         backwards relative to what item 3 just fixed on the backend.
         `listed_price` is now the resolved, condition-adjusted display
         price (mirroring `_display_price`); `current_market_value` is a
         separate, potentially-stale raw pass-through. The frontend still
         prefers the stale one. Not fixed here: no current test pins either
         behavior, and changing it means updating an assertion in
         `DisplayPanel.test.tsx` that predates this remediation — a real
         call, but one for the owner/Council to make rather than a
         unilateral change during a "make RED green" pass.
- [x] **Council r2 — genuine independent re-review, 2026-08-24.** A fresh
      session (no memory of writing the GREEN code) re-read every touched
      file from source rather than trusting `council-r2-self-review.md`'s
      account of it, cross-referenced `follow-ups.md` and
      `council-r1-verdict.md`'s appendix against the actual current code
      (not the verdict's original file/line citations, which had moved),
      and used the `adversarial-review` skill for a second, formal sweep
      over the resulting fix diff. Verified with grep/read, not assumed:
      every claimed "no reader" in M3/M5 (see below), the sole production
      call site of `DisplayedCard(...)` (confirms the kind-narrowing fix is
      fully contained inside `_hydrate_item`'s try/except), and the sole
      real caller of `BedrockChatService.chat()` (confirms removing the
      dead `isinstance(result, str)` branch could only affect
      `routers/chat.py`, not some other, unaudited caller).

      Both r1-carried findings resolved, plus three more follow-ups picked
      up along the way — five fixes in total:

      1. **Frontend price-precedence bug (MAJOR, r2 self-review finding
         2).** `DisplayPanel.tsx` and `ChatPanel.tsx` both computed
         `card.current_market_value ?? card.listed_price`; swapped to
         `card.listed_price ?? card.current_market_value ?? 'Price N/A'` —
         `listed_price` is the resolved, condition-adjusted figure since
         item 3, `current_market_value` a separate, potentially-stale
         pass-through kept only as a fallback for the real case where an
         item has no `listed_price` at all (`InventoryItem.listed_price` is
         nullable). New tests: `DisplayPanel.test.tsx`'s existing "renders
         hydrated cards" assertion flipped to pin `$275.00` (not `$450.00`)
         plus an explicit `queryByText('$450.00')).not.toBeInTheDocument()`
         negative check, a new "falls back to current_market_value when
         listed_price is null" case, and the same pair of assertions added
         to `ChatPanel.test.tsx`'s inline-artifact test.
      2. **`DisplayedCard.kind` narrowed** from
         `Literal["raw","graded","sealed","bulk"]` to
         `Literal["raw","graded"]` (`models/chat.py`, mirrored in
         `lib/inventory.ts`) — the r1-carried "known consequence," now
         ruled on rather than left open. `is_customer_visible`'s
         `CUSTOMER_KINDS` is `{"raw","graded"}` and `_hydrate_item` returns
         `None` before ever constructing a `DisplayedCard` of another kind,
         so the wider literal admitted values that were provably
         unreachable. Narrowing makes that a second, independent
         enforcement layer: a future regression in the visibility gate now
         fails closed (a pydantic `ValidationError`, caught by
         `_hydrate_item`'s own broad `except`) instead of silently
         constructing a `DisplayedCard` the wire was never meant to carry.
         New test: `test_displayed_card_kind_is_narrowed_to_reachable_values`
         (`test_chat_response_envelope.py`). Two now-genuinely-dead branches
         removed as a consequence: `_display_name`'s `item.kind ==
         "sealed"/"bulk"` checks (`bedrock.py` — single caller, always
         post-gate) and `DisplayPanel.tsx`/`ChatPanel.tsx`'s
         `card.kind === 'sealed' ? 'Sealed' : 'N/A'` ternaries (would have
         been a TypeScript "no overlap" error against the narrowed type
         regardless; replaced with a flat `'N/A'`).
      3. **JP badge fixed for uncatalogued items (advisor-architect M4 /
         advisor-contrarian, carried from r1).** The badge was inferred
         from `card.card_id.startsWith('ja:')` — unavailable whenever the
         item has no catalog match (`card: null`), which is exactly the
         uncatalogued-JP case the bug report was about. Added
         `DisplayedCard.language` (backend `models/chat.py` +
         `lib/inventory.ts`), populated in `_hydrate_item` from
         `item.language` (the `Language` enum already on the base
         `InventoryItem` model, independent of any catalog join); both
         frontend components' `isJapanese` prop now reads
         `card.language === 'JP'` directly. New backend tests:
         `test_hydration_carries_language_so_uncatalogued_jp_items_keep_the_badge`,
         `test_hydration_carries_english_language_by_default`
         (`test_display_hydration.py`). New frontend test: "shows the JP
         badge for an uncatalogued Japanese item" (`DisplayPanel.test.tsx`).
      4. **Dead wire fields trimmed (advisor-architect M5).** `CardSummary`
         (`models/chat.py` / `DisplayCardSummary` in `lib/inventory.ts`)
         lost `set_id`, `rarity`, `image_large`, and `market_price` — the
         last a literal duplicate of the exact same condition-adjusted
         figure already on `DisplayedCard.listed_price` for a raw item
         (both were set from the same local variable in `_hydrate_item`).
         `DisplayedCard` lost `finish`. All five confirmed as genuinely
         dead by grep before removal — zero readers anywhere in
         `DisplayPanel.tsx`, `ChatPanel.tsx`, or `CardPresentation.tsx`
         (`card_id` survives despite losing its only reader to fix #3
         above — a defensible general-purpose identity field on its own,
         unlike the other four, and the only one of the five M5 explicitly
         named). Existing tests updated to match (assertion targets moved
         from `.card.market_price` to `.listed_price`, fixture literals
         trimmed, `not hasattr(displayed, "finish")` added alongside the
         existing `cert_image_url` pattern).
      5. **Dead `isinstance(result, str)` branch removed (advisor-architect
         M6).** `routers/chat.py`'s compatibility branch for a
         string-returning `chat()` had no real caller — every production
         path returns the dict envelope — and was kept alive only by two
         test doubles that predated the envelope shape. **Discovered while
         verifying this fix**: a THIRD such double existed in
         `test_rate_limit.py` (missed on the first full-suite pass, caught
         by 6 failures on the second) — all three (`test_chat.py`'s
         `_stub_bedrock`, `test_rate_limit.py`'s inline `bedrock` mock)
         fixed to return `{"reply": ..., "artifacts": [], "panel":
         {"cards": [], "truncated": False}}`, matching the real contract,
         rather than restoring the branch to accommodate them.

      **Left open, with reasoning** (updated in `follow-ups.md` alongside
      this entry): the structural duplication across four separate
      catalog-projection type definitions (M3) — trimming the dead fields
      above shrinks the immediate concern but the duplication itself is a
      bigger refactor, out of scope for a follow-up triage pass; the wire
      payload's lack of an enforceable byte ceiling (M5's other half);
      `truncated`'s per-turn (not cross-turn) freshness, confirmed
      deliberate on re-reading `_DisplayState.__init__`'s own comment, not
      a bug; `max_tokens`/`stop_sequence` Bedrock stop reasons falling
      through to a generic 502 — pre-existing, not worsened by this plan;
      a restoration notice for stale/sold IDs dropped from a restored
      panel. `reorder_panel([])` and the `open !== true` guard are
      confirmed DISSOLVED (the underlying tools/fields no longer exist).
      `panel_item_ids` shape validation is confirmed MOOT (the visibility
      gate rejects on content regardless of shape).

      **Verified, full suites, all three, after all five fixes:**

      | Suite | Result |
      |---|---|
      | Backend (pytest) | **2090 passed, 0 failed** |
      | Frontend (vitest) | **1022 passed, 0 failed** |
      | MCP server (vitest) | **101 passed, 0 failed** (untouched by this round) |
      | `ruff check backend/src` | clean |
      | `tsc --noEmit` (frontend) | clean |
      | `next lint` | 0 errors, 2 pre-existing warnings (unrelated files) |

      Adversarial review (via the `adversarial-review` skill, formally
      invoked) against the fix diff: **PASS**, no blocking findings.
      Verified rather than assumed: no other consumer of any trimmed
      field exists (grep across both `backend/src`+`backend/tests` and the
      frontend tree); the kind-narrowing's only production call site is
      inside `_hydrate_item`'s try/except; the `language.value if language
      is not None else None` pattern mirrors the existing `company` field's
      idiom two lines above it in the same function; no caller of
      `BedrockChatService.chat()` exists outside `routers/chat.py`.

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
- 2026-08-24 — GREEN for checklist items 1-6, 9 (reduced), 11, and the
  `set_display` collapse (decision 23), both backend and frontend halves.
  All three suites closed to 0 failures (backend 2087/2087, frontend
  1020/1020, MCP 101/101); `ruff`/`tsc`/`next lint` all clean. Full detail
  under "Items" above. Self-review only at this point
  (`council-r2-self-review.md`) — flagged two findings rather than fixing
  them: the carried-forward `DisplayedCard.kind` sealed/bulk admission, and
  a newly-found frontend price-precedence bug. Both deferred to an
  independent Council r2 pass.
- 2026-08-24 — **Council r2**, a genuinely independent re-review (fresh
  session, re-verified every claim from source rather than trusting the
  self-review's account). Both deferred findings resolved, plus three more
  follow-ups (M4's JP badge bug, M5's dead wire fields, M6's dead branch)
  picked up in the same pass. Five fixes total, full TDD (RED confirmed
  failing, then GREEN) for the two behavioral ones (price precedence, JP
  badge/language) and verified-safe refactor for the other three (kind
  narrowing, dead-field trim, dead-branch removal). One regression caught
  mid-pass and fixed before it could ship: a third bare-string bedrock test
  double in `test_rate_limit.py`, missed on the first full-suite run after
  removing the dead branch, caught by 6 failures on the second run. Final:
  backend 2090/2090, frontend 1022/1022, MCP 101/101 (untouched), all
  lint/typecheck clean. Formal `adversarial-review` skill pass against the
  fix diff: PASS, no blocking findings. Full detail under "Items" above.
