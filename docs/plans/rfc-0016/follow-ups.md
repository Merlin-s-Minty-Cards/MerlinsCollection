# Follow-ups — RFC-0016 Chat Display Artifacts

Migrated 2026-08-24 from Kiro's `.kiro/plans/0001-chat-experience/followups.md`
(gitignored, tool-local — see `README.md`'s "Where this came from"). Format
unchanged:

`- [ ] (SEVERITY) description — origin`

Severity: MINOR | LOW | NITPICK. Anything MAJOR belongs in `progress.md` as a
roadmap item, not here.

## Open

- [ ] (LOW) User drag-and-drop reordering of panel cards. Explicitly out of
      scope per decision 1 (model-driven reorder only). Needs a dnd library,
      touch support, and keyboard-accessible reordering for a11y — a
      self-contained follow-on feature.
- [ ] (MINOR) `.kiro/agents/design-doc.md` is sniffed by libmagic as an HTML
      document because its body contains `<Title>` and
      `<kebab-case-title>` placeholders. Benign — noted so nobody
      re-investigates it as a real problem. (Kiro-specific file; irrelevant
      to Claude Code, kept for completeness of the migrated record.)
- [ ] (MINOR) `npm ci` appends `"packageManager": "yarn@1.22.22..."` to
      `package.json` on some hosts, and reformats the `workspaces` array.
      Revert it if it recurs (`git checkout -- package.json`) — this repo is
      npm-workspaces with a `package-lock.json`. If it recurs for other
      contributors, consider pinning `packageManager` to the npm version
      deliberately rather than letting corepack guess yarn. — origin: Kiro
      orchestrator, environment setup

### From Council r1 verdict appendix (non-blocking; full detail in `council-r1-verdict.md`)

Filed verbatim-in-substance from the judge's appendix so end-of-plan triage
does not have to re-read the verdict. Several may dissolve or shrink once
the r2 remediation lands under decision 23 — re-check before acting on any
of them.

- [ ] (MINOR) Tool-contract classification (which tools MCP registers vs.
      which the backend owns) is restated in five places, two via positional
      array slicing that a semantically-empty reorder would break. — origin:
      advisor-architect M2
- [ ] (MINOR) Tool-contract classification (which tools MCP registers vs.
      which the backend owns) is restated in five places, two via positional
      array slicing that a semantically-empty reorder would break. — origin:
      advisor-architect M2. NOT addressed in Council r2 (2026-08-24) —
      real but structural, out of scope for a follow-up triage pass.
- [x] (MINOR, partially resolved 2026-08-24 — Council r2) Four overlapping
      catalog projections (`models/chat.py::CardSummary` vs.
      `models/inventory.py::CardSummary`; frontend `DisplayCardSummary` vs.
      `CardSummary`) — the STRUCTURAL duplication (four separate type
      definitions) is unchanged, still open, and a bigger refactor than
      this pass's scope. What's resolved: the stated justification really
      didn't hold, confirmed by grep before removal — `image_large`,
      `set_id`, `rarity`, and a duplicate `market_price` had zero readers
      on either display surface. All four trimmed from `CardSummary` (see
      M5 below, same fix). — origin: advisor-architect M3
- [x] (MINOR, resolved 2026-08-24 — Council r2) `CardPresentation`
      extraction landed one level too low: `DisplayPanel.tsx` and
      `ChatPanel.tsx` each reimplement identical title/condition/price
      derivations (still true, not addressed — a bigger refactor than this
      pass). Of the two REGRESSIONS this caused: the JP badge fixed —
      `DisplayedCard.language` added (populated from `item.language`,
      independent of any catalog match), both components' `isJapanese` now
      reads it directly instead of inferring from `card.card_id`. The
      sealed "Booster Box" mapping gap is now moot rather than fixed: kind
      narrowing (M6-adjacent, see the dead-branches item below) makes
      `kind === 'sealed'` unreachable on a real `DisplayedCard`, so there
      is no sealed item left to mis-render as "Sealed" in chat. — origin:
      advisor-architect M4, JP badge also advisor-contrarian
- [x] (MINOR, partially resolved 2026-08-24 — Council r2) Wire payload
      carried fields nothing reads: `image_large`, `set_id`, `rarity`,
      `market_price` (duplicated the exact same condition-adjusted figure
      already on `DisplayedCard.listed_price` for a raw item), `finish`.
      All five confirmed dead by grep and trimmed from `CardSummary`/
      `DisplayedCard` (backend `models/chat.py`) and their frontend mirrors
      (`lib/inventory.ts`). **Still open**: no enforceable byte ceiling on
      the payload — trimming these fields shrinks it but doesn't bound it;
      that needs actual limiting logic, not a field count. — origin:
      advisor-architect M5, advisor-chaos, advisor-security
- [x] (MINOR, resolved 2026-08-24 — Council r2) Dead production branch in
      `routers/chat.py` (`isinstance(result, str)`), shaped entirely by a
      test double; no real caller returns a string (verified: the only
      real caller of `BedrockChatService.chat()` is this router, and every
      real implementation returns the dict envelope). Removed; the double
      that motivated it (`test_chat.py`'s `_stub_bedrock`) fixed to return
      the real contract shape instead. **A second, identical double was
      found in `test_rate_limit.py`** during verification (missed on the
      first full-suite run, caught by 6 failures on the second) and fixed
      the same way. — origin: advisor-architect M6
- [x] (MINOR, investigated 2026-08-24 — Council r2, description corrected)
      Re-read `_DisplayState.set_panel`/`__init__` against source rather
      than trusting the original claim: `truncated` is **not** sticky
      within a request — `set_panel` recomputes it fresh on every call
      (`self.panel_truncated = input_truncated or len(deduped) >
      _PANEL_CAP`, a full reassignment, not an OR-accumulation), so a
      later `set_display` call with a shorter list correctly clears it.
      The cross-turn "amnesia" half is real and IS deliberate, per
      `__init__`'s own comment: a restored panel already at 50 doesn't
      re-signal truncation on an unrelated later turn, since the banner
      already told the user once. Left open as a UX design question (not a
      bug) — persisting truncation state across turns is a real feature,
      not a mechanical fix. — origin: advisor-contrarian
- [x] (NITPICK, DISSOLVED — confirmed 2026-08-24) `reorder_panel([])` on an
      empty panel reports success. Confirmed dissolved: `reorder_panel` no
      longer exists post-decision-23 (`set_display` replaced all five
      panel-mutation tools). — origin: advisor-contrarian
- [ ] (MINOR) `max_tokens` / `stop_sequence` stop reasons fall through to a
      generic 502. A `set_display` call listing 50 IDs is large enough to
      make truncation reachable. — origin: advisor-contrarian. NOT
      addressed in Council r2 (2026-08-24) — pre-existing, not worsened by
      this plan's changes.
- [x] (MINOR, resolved 2026-08-24 — Council r2) Dead/unreachable branches:
      `DisplayPanel`'s internal `open !== true` guard is gone (the `open`
      prop was removed from the component entirely by decision 23's
      frontend half). The sealed/bulk hydration branches are now REMOVED,
      not just unreachable-but-present: `bedrock.py::_display_name`'s
      `item.kind == "sealed"/"bulk"` checks deleted (single caller, always
      post the customer-visibility gate), and `DisplayedCard.kind` itself
      narrowed to `Literal["raw","graded"]` so the invariant is enforced by
      pydantic, not just documented. Two consequent frontend dead branches
      (`card.kind === 'sealed' ? 'Sealed' : 'N/A'` in both
      `DisplayPanel.tsx` and `ChatPanel.tsx`) also removed — they'd have
      been a TypeScript "no overlap" error against the narrowed type
      regardless. — origin: advisor-contrarian, advisor-architect
- [ ] (MINOR) Stale/sold IDs in a restored panel silently disappear with no
      restoration notice distinct from the 50-cap `truncated` flag. —
      origin: advisor-chaos. NOT addressed in Council r2 (2026-08-24) — a
      UX nicety, not a correctness/security issue.
- [x] (MINOR, confirmed MOOT 2026-08-24 — Council r2) `panel_item_ids` has
      no shape validation beyond length. Confirmed moot on re-read:
      `_hydrate_item` gates on `is_customer_visible`, which rejects on
      content (status/kind/location) regardless of what shape the input
      took to get there — a malformed-but-length-valid ID just fails to
      resolve to a real item and hydrates to `None`, the same as any other
      unknown ID. — origin: advisor-security
- [x] `artifacts` array was unbounded. Now specified as capped at 50 in the
      amended RFC — the cap landed in the r2 implementation 2026-08-24
      (`_MAX_ARTIFACTS = 50` in `bedrock.py`, `test_artifacts_array_is_bounded`
      passes). — origin: advisor-security, folded into blocking item 11
- [ ] (MINOR) `fs_write` (Kiro's file-write tool) emits CRLF on every file it
      creates. `.gitattributes` normalizes at commit time so nothing wrong
      lands in history, but files are CRLF on disk until then. Kiro-specific
      — Claude Code's Write/Edit tools were not observed to have this
      behavior, but re-check `.gitattributes`' extension coverage if a new
      file type shows phantom diffs.

- [ ] (MINOR) `next lint` is deprecated and removed in Next.js 16 —
      `frontend` lint currently prints a migration notice pointing at
      `npx @next/codemod@canary next-lint-to-eslint-cli .`. Not on the
      Phase 1 critical path; revisit with the Next 16 upgrade. — origin:
      Kiro orchestrator, r2 RED lint run
- [ ] (MINOR) `ruff check backend/tests` reports 76 errors (35 I001
      import-sort, 24 E501, 7 F401, 6 F841, 3 E402, 1 F811), spread across
      pre-existing files unrelated to this plan (`test_cosigners.py` 8,
      `test_inventory.py` 6, `test_purchases.py` 5, ...). The documented
      lint gate is `ruff check backend/src`, which is clean, so tests are
      currently unlinted. Worth deciding whether to bring `backend/tests`
      into the gate; 43 are auto-fixable. Not on the Phase 1 critical path.
      — origin: Kiro orchestrator, r2 RED

## Resolved

- [x] **(MAJOR — found during r2 self-review 2026-08-24; fixed during
      Council r2, same day)** Frontend price display had its precedence
      backwards relative to checklist item 3's backend fix.
      `DisplayPanel.tsx` and `ChatPanel.tsx` both computed
      `card.current_market_value ?? card.listed_price`. Before r2,
      `listed_price` was the item's raw, unadjusted stored price and
      either order was defensible; after r2, `listed_price` is the
      RESOLVED, condition-adjusted display price (mirrors
      `routers/inventory.py::_display_price`) while `current_market_value`
      is a separate, potentially stale, unadjusted pass-through — so the
      frontend was preferring the wrong figure whenever both were present.
      **Fixed**: both surfaces now read `card.listed_price ??
      card.current_market_value ?? 'Price N/A'` — `current_market_value`
      kept as a fallback (not dropped) for the real case where
      `listed_price` is null (`InventoryItem.listed_price` is nullable).
      `DisplayPanel.test.tsx`'s existing price assertion flipped to pin
      `$275.00` (was `$450.00`) plus a negative check that `$450.00` no
      longer renders, a new "falls back to current_market_value when
      listed_price is null" test, and the same pair of assertions added to
      `ChatPanel.test.tsx`. — origin: this session's own
      council-r2-self-review.md
- [x] Phantom CRLF diffs on 4 `.kiro/skills/*/SKILL.md` + `scripts/run-tests.sh`
      — discarded after verifying byte-identical content. (Kiro session)
- [x] Repo-wide line-ending policy — `.gitattributes` added in `c4ae479`.
      (Kiro session)
- [x] CRLF source identified: Kiro's `fs_write` tool, not a Windows editor.
      (Kiro session)
- [x] `.kiro/steering/terminal.md` corrected to the authoritative WSL clone
      and bash tool names — `fc636fd`. (Kiro session; the file itself is
      Kiro-local and not part of this migration's output, but the finding —
      which clone is authoritative — carried over into this directory's
      `progress.md`.)
- [x] Kiro `subagent` tool-grant blocker — resolved same-session, no config
      change needed. (Kiro-specific; N/A to Claude Code.)
- [x] **Root `package.json::test:backend` pointed at a Windows venv path**
      (`.venv\Scripts\python.exe -m pytest`), broken on WSL where the venv
      is `backend/.venv/bin/python`. Previously logged here as an open MINOR
      ("not currently broken by it since CI runs each workspace directly, a
      dev-convenience trap"). **Fixed 2026-08-24** as part of this
      migration: `test:backend` now runs `node scripts/run-backend-tests.js`,
      a small cross-platform resolver that tries the Linux venv, two Windows
      venv layouts, then `python3`/`python` on PATH. — origin: Kiro
      orchestrator, environment setup; resolved during the Kiro→Claude Code
      plan migration
- [x] **CLAUDE.md's Test Commands table hardcoded the same Windows-only
      venv path.** Not previously filed here (found during this migration,
      not by the Kiro session) — fixed alongside the above, same commit
      batch: table now lists both Linux/WSL and Windows commands side by
      side, plus a one-line snippet to check which venv is actually present.
- [x] **`scripts/run-tests.cmd` hardcoded an absolute path to a stale clone**
      (`MerlinsCollection-Secondary`, per `.kiro/steering/terminal.md`'s own
      "which clone" note). Not previously filed here — fixed alongside the
      above: now resolves `%~dp0..` (its own location) instead of a
      hardcoded path.
