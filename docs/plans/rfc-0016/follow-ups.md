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
- [ ] (MINOR) Four overlapping catalog projections (`models/chat.py::CardSummary`
      vs. `models/inventory.py::CardSummary`; frontend `DisplayCardSummary`
      vs. `CardSummary`). The stated justification does not hold:
      `image_large` has no reader anywhere. May shrink incidentally once the
      price-derivation fix (checklist item 3) reuses the existing
      projection. — origin: advisor-architect M3
- [ ] (MINOR) `CardPresentation` extraction landed one level too low:
      `DisplayPanel.tsx` and `ChatPanel.tsx` each reimplement identical
      title/condition/price derivations. Two real regressions from it: the
      JP badge disappears for uncatalogued Japanese items in chat
      (`DisplayedCard` carries no `language`), and sealed items show a flat
      "Sealed" instead of the mapped "Booster Box" (no `product_type`). —
      origin: advisor-architect M4, JP badge also advisor-contrarian
- [ ] (MINOR) Wire payload carries fields nothing reads (`image_large`,
      `set_id`, `rarity`, unused `market_price`, `finish`) and has no
      enforceable byte ceiling. — origin: advisor-architect M5,
      advisor-chaos, advisor-security
- [ ] (MINOR) Dead production branch in `routers/chat.py`
      (`isinstance(result, str)`), shaped entirely by a test double; no real
      caller returns a string. Three-line deletion. — origin:
      advisor-architect M6
- [ ] (MINOR) `truncated` is sticky within a request (does not clear when
      cards are later removed) and amnesiac across requests (resets to
      `False` on every new message even if the panel is still capped). —
      origin: advisor-contrarian
- [ ] (NITPICK) `reorder_panel([])` on an empty panel reports success.
      Harmless; confirms a no-op. Likely dissolves with decision 23. —
      origin: advisor-contrarian
- [ ] (MINOR) `max_tokens` / `stop_sequence` stop reasons fall through to a
      generic 502. A `set_display` call listing 50 IDs is large enough to
      make truncation reachable. — origin: advisor-contrarian
- [ ] (MINOR) Dead/unreachable branches: `DisplayPanel`'s internal
      `open !== true` guard (already gated by the parent), and the
      sealed/bulk hydration branches (unreachable while MCP's
      `PUBLIC_KINDS` excludes them from search results). — origin:
      advisor-contrarian, advisor-architect
- [ ] (MINOR) Stale/sold IDs in a restored panel silently disappear with no
      restoration notice distinct from the 50-cap `truncated` flag. —
      origin: advisor-chaos
- [ ] (MINOR) `panel_item_ids` has no shape validation beyond length. Moot
      once the visibility gate lands, since visibility gates regardless of
      input shape. — origin: advisor-security
- [ ] (MINOR) `artifacts` array was unbounded. Now specified as capped at 50
      in the amended RFC — verify the cap actually lands in the r2
      implementation. — origin: advisor-security, folded into blocking
      item 11
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
