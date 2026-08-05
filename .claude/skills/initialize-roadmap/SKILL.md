---
name: initialize-roadmap
description: Audit the workspace and write claude-progress.txt — repo state, dependencies, verification commands, and an ordered roadmap. Use at the very start of a feature or work session before any implementation, or when claude-progress.txt is missing or stale.
---

# Initialize Roadmap

Build an accurate, current snapshot of the workspace and turn the feature goal into a trackable engineering roadmap stored in `claude-progress.txt` at the repository root. Run once, at the start of a feature, before any implementation work begins.

## Constraints

- **Read-only except for one file:** the only file created or modified here is `claude-progress.txt`. Never write, edit, or delete application code, tests, configs, or documentation, and never install/upgrade/remove dependencies — record them, don't change them.
- Every claim in `claude-progress.txt` must come from something actually observed (a file read, a command run) — never invented.
- If a previous `claude-progress.txt` exists, don't blindly overwrite it: read it first, carry forward still-relevant open items, and note that a new baseline superseded the old one.

## Step-by-Step Execution

1. **Audit the workspace structure.** Enumerate the top-level layout and major layers (`frontend/`, `backend/`, `mcp-server/`, `frontend/sanity/`). Note anything unexpected: missing directories, stray build artifacts, uncommitted changes.
2. **Determine dependencies.** Read the dependency manifests (`package.json` at root and per workspace, backend requirements/`pyproject.toml`). Record key frameworks and versions.
3. **Capture repository state.** Record the current branch, latest commit hash and subject, and working-tree cleanliness (`git status`, `git log -1`).
4. **Record the verification baseline.** List the project's canonical test/lint commands (CLAUDE.md's Test Commands table). If a verified baseline is wanted, run the suites and record pass/fail counts; otherwise record the commands as "not yet run".
5. **Establish the roadmap.** From the user's stated feature goal, write an ordered task list with checkbox state. Each item should be expressible as RED → GREEN → REFACTOR phases per the project's outside-in TDD process.
6. **Write `claude-progress.txt`** at the repo root with these sections:
   - `## Feature Goal` — one paragraph, in the user's own terms.
   - `## Workspace Snapshot` — branch, commit, tree cleanliness, layer layout, anomalies.
   - `## Dependencies` — key packages and versions per layer.
   - `## Verification Commands` — test/lint commands per layer and their last known result.
   - `## Roadmap` — ordered `[ ]` checklist, smallest shippable increments first.
   - `## Log` — a dated entry noting the baseline was established.
7. **Report back.** Summarize the baseline: what the project looks like, anything concerning found, and the first roadmap item.
