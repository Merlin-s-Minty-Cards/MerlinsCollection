# Windows CMD Terminal Rules

This environment is Windows running Command Prompt (CMD).

## Critical Rules

1. **No Bash syntax.** Never use `ls`, `export`, `grep`, `cat`, `rm`, `&&` chaining, `$(...)` subshells, or heredocs. Use Windows equivalents: `dir`, `set`, `findstr`, `type`, `del`, `&` chaining.

2. **No multiline commands.** CMD does not support multiline string arguments. Keep ALL commands on a single line. For git commits, use only a short single-line message:
   ```
   git commit -m "type(scope): short description"
   ```
   Never attempt multi-paragraph commit messages with `-m`.

3. **Always use `-C` flag for git** to specify the repo root explicitly:
   ```
   git -C "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary" status
   ```
   Do NOT rely on the shell's current working directory — it may be a subdirectory (e.g. `frontend/`).

4. **Ignore exit code 1 if output looks correct.** The terminal frequently reports `Exit Code: 1` even on successful commands. Judge success by the actual output content, not the exit code.

5. **If a command fails once, stop.** Do not loop, retry with variations, or try to auto-fix. Ask the user for help. Two failed attempts means something is wrong with your approach.

6. **Quote all paths** with double quotes if they contain spaces.

7. **Use `&` not `&&`** for chaining commands in CMD. But prefer separate tool calls over chaining.

## Common Patterns

| Task | Correct CMD | Wrong (Bash) |
|------|-------------|--------------|
| List files | `dir` | `ls` |
| View file | `type file.txt` | `cat file.txt` |
| Delete file | `del file.txt` | `rm file.txt` |
| Delete dir | `rmdir /s /q dir` | `rm -rf dir` |
| Set env var | `set VAR=value` | `export VAR=value` |
| Find in files | `findstr "text" file.txt` | `grep "text" file.txt` |
| Git from root | `git -C "full\path" ...` | `cd repo && git ...` |

## Git Specifics

- Stage specific files: `git -C "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary" add path/to/file.ext`
- Commit (single line only): `git -C "c:\Users\ethar\.cursor\projects\MerlinsCollection-Secondary" commit -m "feat(scope): description"`
- Always use forward slashes in git paths: `git add .kiro/steering/file.md` (not backslashes)

## Test Commands

| Scope | Command |
|---|---|
| All | `npm test` |
| Frontend | `npm test --workspace=frontend` |
| MCP Server | `npm test --workspace=mcp-server` |
| Backend | `python -m pytest backend/tests -q --tb=short` |
| Lint (FE) | `npm run lint --workspace=frontend` |
| Lint (BE) | `ruff check backend/src` |
