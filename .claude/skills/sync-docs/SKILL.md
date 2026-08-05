---
name: sync-docs
description: Bring READMEs, API endpoint docs, inline code commentary, and CLAUDE.md tables back in line with code that just changed. Use after implementation work lands, or when documentation looks stale relative to the source.
---

# Sync Docs

After source files change, scan the modifications and update every corresponding documentation layer so explanation and implementation never drift apart.

## Constraints

- **Never change behavior.** Edit documentation, docstrings, and comments only — never executable logic, signatures, or configuration values. If the code itself looks wrong rather than the docs, report it instead of "fixing" it here.
- Documentation must be **derived from the code as it is now**, not from commit messages or intentions. Read the actual implementation before describing it.
- Match each document's existing voice, structure, and formatting. Don't restructure a README to your taste while updating one section.
- Comment only what the code cannot say itself — constraints, invariants, non-obvious "why". Never narrate what the next line does, and never leave a stale comment behind after an edit.
- Never document secret or credential **values** — names and purposes only.

## Step-by-Step Execution

1. **Scope the drift.** Use `git diff`/`git log` against the branch base (or the scope given) to list modified source files across `frontend/`, `backend/`, and `mcp-server/`.
2. **Map code to docs.** For each modified file, find its documentation surfaces: the nearest README, API docs (FastAPI route descriptions/docstrings, endpoint tables), MCP tool descriptions, CLAUDE.md tables (routes, tools, commands) if the change affects them, and any `docs/` pages referencing the touched modules.
3. **Audit each surface.** Compare what the doc says with what the code now does — parameter names, routes, response shapes, defaults, commands, prerequisites. List every mismatch before editing anything.
4. **Update the docs.** Correct each mismatch precisely. Add documentation for genuinely new public surface (new endpoint, new MCP tool, new script). Update stale inline commentary and docstrings in the modified files.
5. **Verify examples.** Run or validate any command or code sample you wrote or touched against the actual schema/manifests.
6. **Report.** Summarize which documents were updated and why, list any doc/code mismatches that need a human decision, and confirm the documentation layers are aligned with the implementation.
