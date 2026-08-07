---
name: pr-description
description: Fill the repository's PR template from the current branch's diff into one copy-pasteable markdown block. Use when a branch is finished and the user wants a pull request title, description, or body.
---

# PR Description

Turn a finished branch into a Pull Request description that matches the local repository's template exactly, delivered as one clean codeblock. Describe the change; don't change the change.

## Constraints

- **Read-only.** The deliverable is text; code, commits, pushes, and the PR itself stay untouched unless explicitly asked.
- The output **mirrors the repository's template exactly** — same headings, wording, order, and checkboxes. The set of `##` headings in the output matches the template's set one for one, and information with no natural home goes in the closest existing section.
- Fill every section the template defines; if one genuinely doesn't apply, write `N/A` with a one-line reason.
- Every claim is grounded in the actual diff.
- Check a checkbox only when it's verifiably true — tick "tests pass" only against an observed green run (the `testing` skill covers what makes one trustworthy).
- Wrap the final body in a single fenced codeblock. Since the body itself contains markdown (and possibly triple-backtick fences), use a **quadruple-backtick** fence.

## Step-by-Step Execution

1. **Locate the template.** Search, in order: `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/PULL_REQUEST_TEMPLATE/` (directory of variants), `docs/pull_request_template.md`, repo root. Case-insensitive. If several variants exist, pick the one matching the change type and say which. If none exists, state that and use a sensible default (Summary / Changes / Testing / Notes).
2. **Establish the diff scope.** Compare the current branch against the main branch (`git log main..HEAD`, `git diff main...HEAD --stat`, then the full diff for files needing close reading). Include uncommitted work only if the user says it belongs in the PR.
3. **Analyze the change.** From the commits and diff, determine: intent, user-facing effects, layers touched, schema/API contract changes, new dependencies, and how it was tested.
4. **Fill the template completely.** Summaries lead with the "why", the change list groups related edits, the testing section names exact commands and results.
5. **Verify heading parity before output.** Compare the `##` headings in the draft against the template's one-for-one. Fix any mismatch before continuing.
6. **Output the finished body** as a single quadruple-backtick-fenced markdown block, preceded by one short line suggesting a PR title (`type: summary` if the repo's history follows a convention, otherwise plain). Nothing follows the codeblock.
