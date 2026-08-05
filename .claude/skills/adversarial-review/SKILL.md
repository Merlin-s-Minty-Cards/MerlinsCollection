---
name: adversarial-review
description: Critique a plan or diff from four adversarial angles in one inline pass — broken logic, security exposure, resilience under abuse, and structural bloat. Use when another skill's step calls for a fresh adversarial look before or after implementing, or when asked to red-team a draft.
---

# Adversarial Review

Turn against your own plan or diff and try to break it, across four lenses, in the current context — no subagent spawn, no siloed files. Open with the four mandate questions below, sweep each lens, then rule.

## The four lenses

- **Logic** — *"Assume this will crash on day one."* Unhandled exceptions, non-terminating loops, silent failures (swallowed errors, ignored return values, null-as-success), edge cases (empty/zero/negative/unicode/huge/first-run), false assumptions about inputs, callers, ordering, or external systems.
- **Security** — *"You just leaked data."* Injection (queries, shell/eval, path construction, XSS, prompt injection into Bedrock/chat), missing authorization on any new/changed endpoint or MCP tool, secrets or env values reaching code/logs/error responses/client bundles, newly added dependencies with known advisories.
- **Chaos** — *"What happens when a user clicks submit 50 times in one second, or the database times out mid-call?"* Hostile repetition, idempotency of retried/replayed mutations, race conditions on shared state, mid-flight infrastructure failure, missing timeouts or unbounded retries, malformed/oversized input.
- **Bloat** — *"You wrote 50 lines for something that needs 5."* YAGNI violations, unnecessary dependencies, dead code, duplication against existing utilities, needless ceremony.

## Rule

**Judge the delta, not the world** — a pre-existing weakness the change leaves untouched is a follow-up note, never a blocker; ask "is this worse than before?" for every candidate. A finding needs a concrete trigger (`file:line`, the input/sequence/scenario, the consequence) to count — "feels risky" with no trigger is noise, drop it.

## Step-by-Step Execution

1. **Read** the plan or diff and the touched files.
2. **Sweep all four lenses** against it, citing `file:line` and the concrete trigger for each candidate finding.
3. **Verify** each candidate by tracing it through the actual code path; discard what doesn't survive.
4. **Rule.** State a plain verdict: **PASS**, or a checklist of blocking findings (lens, location, trigger, consequence, what fixing it requires) — list non-blocking notes separately, briefly.
5. **On a blocking checklist:** fix every item, then re-run this sweep once against the patched version before calling it done.
