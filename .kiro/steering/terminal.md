# Terminal: Windows CMD

Workspace path: `c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary`

## Rules

1. **CMD only.** No `ls`, `export`, `grep`, `cat`, `rm`, `&&`, `$(...)`, heredocs. Use `dir`, `set`, `findstr`, `type`, `del`, `&`.
2. **Single-line commands only.** No multiline args. Git commits: `git commit -m "type(scope): short description"`
3. **Always use `-C` flag for git:** `git -C "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary" status`
4. **Exit code 1 is often fine.** Judge success by output content, not exit code.
5. **If a command fails once, stop.** Ask the user. Two failures = wrong approach.
6. **Quote paths** with spaces. Use `&` not `&&` for chaining (prefer separate tool calls).
7. **Forward slashes in git paths:** `git add .kiro/steering/file.md`

## Quick Reference

| Task | CMD |
|------|-----|
| List | `dir` |
| View file | `type file.txt` |
| Delete file | `del file.txt` |
| Delete dir | `rmdir /s /q dir` |
| Env var | `set VAR=value` |
| Find text | `findstr "text" file.txt` |
| Copy tree | `robocopy src dest /E` |

## Test & Lint Commands

| Scope | Command |
|---|---|
| All tests | `npm test` (root) |
| Frontend | `npm test --workspace=frontend` |
| MCP Server | `npm test --workspace=mcp-server` |
| Backend | `python -m pytest backend/tests -q --tb=short` |
| Lint frontend | `npm run lint --workspace=frontend` |
| Lint backend | `ruff check backend/src` |
| Frontend dev | `npm run dev --workspace=frontend` |
| Backend dev | `uvicorn merlins_collection.main:app --reload` (from backend/) |
