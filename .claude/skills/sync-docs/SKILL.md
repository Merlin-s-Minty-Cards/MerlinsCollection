---
name: sync-docs
description: Bring READMEs, API endpoint docs, inline code commentary, and CLAUDE.md tables back in line with code that just changed. Use after implementation work lands, or when documentation looks stale relative to the source.
---

# Sync Docs

After source files change, scan the modifications and update every corresponding documentation layer so explanation and implementation never drift apart.

## Constraints

- **Prose only.** Edit documentation, docstrings, and comments; leave executable logic, signatures, and configuration values exactly as found. If the code itself looks wrong rather than the docs, report it rather than fixing it here.
- Documentation is **derived from the code as it is now**, so read the actual implementation before describing it — commit messages and intentions record what someone meant, not what shipped.
- Match each document's existing voice, structure, and formatting, and confine edits to the sections the code change touches.
- Comment what the code cannot say itself — constraints, invariants, non-obvious "why". Rewrite or drop any comment an edit made stale.
- Document secret and credential **names and purposes** only; values stay out.

## Step-by-Step Execution

1. **Scope the drift.** Use `git diff`/`git log` against the branch base (or the scope given) to list modified source files across `frontend/`, `backend/`, and `mcp-server/`.
2. **Map code to docs.** For each modified file, find its documentation surfaces: the nearest README, API docs (FastAPI route descriptions/docstrings, endpoint tables), MCP tool descriptions, CLAUDE.md tables (routes, tools, commands) if the change affects them, and any `docs/` pages referencing the touched modules.
3. **Audit each surface.** Compare what the doc says with what the code now does — parameter names, routes, response shapes, defaults, commands, prerequisites. List every mismatch before editing anything.
4. **Update the docs.** Correct each mismatch precisely. Add documentation for genuinely new public surface (new endpoint, new MCP tool, new script). Update stale inline commentary and docstrings in the modified files.
5. **Verify examples.** Run or validate any command or code sample you wrote or touched against the actual schema/manifests.
6. **Report.** Summarize which documents were updated and why, list any doc/code mismatches that need a human decision, and confirm the documentation layers are aligned with the implementation.
