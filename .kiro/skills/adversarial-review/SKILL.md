---
name: adversarial-review
description: Critique a plan or diff across four lenses in one pass — logic, security, chaos, bloat. Use when a draft needs breaking before it ships, or when another skill calls for an adversarial pass.
---

# Adversarial Review

Turn against the plan or diff and try to break it. Two branches below — one for a solo sweep (one agent, all four lenses), one for a seated Council advisor (one lane only).

## The four lenses (single source of truth for lane vectors)

### Logic

*"Assume this will crash on day one."*

- Unhandled exceptions (I/O, network, parsing, awaits, dict access)
- Infinite loops / non-termination (what guarantees progress?)
- Silent failures (swallowed errors, ignored returns, null-as-success)
- Edge cases (empty, zero, negative, unicode, huge, first-run)
- False assumptions (about inputs, callers, ordering, external systems)

### Security

*"You just leaked data."*

- **Injection:** queries (DynamoDB), shell/eval, path construction, XSS, prompt injection (Bedrock/chat)
- **Auth:** new/changed endpoint/tool — is auth enforced server-side? Wrong-tenant access?
- **Data leaks:** secrets in code/logs/errors/client bundles, over-broad responses, CDN caching sensitive data
- **Credentials:** hardcoded keys, tokens logged, CORS/cookie misconfig
- **Dependencies:** known advisories, typosquat names, unnecessary privilege

### Chaos

*"What happens when a user clicks submit 50 times, or the database times out mid-call?"*

- Hostile repetition: 50 clicks, double submits, replayed requests, parallel sessions
- Idempotency: same mutation twice — converge or corrupt?
- Race conditions: interleaving requests, check-then-act gaps, async out-of-order
- Mid-flight failure: timeout after first of two writes, partial responses, hung calls
- Retry/timeout hygiene: missing timeouts, unbounded retries, non-idempotent retries
- Garbage data: huge, malformed, truncated, wrong type payloads

### Bloat

*"You wrote 50 lines for something that needs 5."*

- YAGNI: abstractions with one implementation, config nothing sets, generic params used one way
- Unnecessary deps: could stdlib/existing framework do it in 10 lines?
- Dead code: unused functions, unreachable branches, commented blocks, unused exports
- Verbosity: 50 lines doing 5 lines of work, ceremony classes, redundant null-checks
- DRY violations: logic duplicated within diff or copy-pasted from elsewhere

## Shared rules

These bind every lens, whether one reviewer sweeps all four (solo branch) or the Council splits them across seats (seated branch).

- **Judge the delta, not the world** — a pre-existing weakness the change leaves untouched is a follow-up note, never a blocker.
- **A finding needs a concrete trigger** — `file:line`, the input or sequence that fires it, the consequence that follows. "Looks fragile" is not a finding.
- **Severity is earned.** Reserve the top two grades for a failure you can construct end to end with real damage. Taste, style, and speculation grade minor and never gate, however many of them there are.
- **Object only on a top-two finding.** A pile of minors is an accepted change with notes attached.

## Branch: Solo sweep

One agent sweeps all four lenses and rules. Use this when another skill invokes `adversarial-review` inline (e.g. `tdd`'s pre- and post-change passes), or when a user asks for a standalone four-lens critique.

1. Read the plan or diff and touched files.
2. Sweep all four lenses, citing `file:line` and concrete trigger for each finding.
3. Verify each finding by tracing it through the actual code path; discard what doesn't survive.
4. Rule: **PASS**, or a checklist of blocking findings (lens, location, trigger, consequence, fix requirement). Non-blocking notes listed separately.
5. On a blocking checklist: fix every item, then re-sweep once.

## Branch: Seated advisor

A Council seat assigned one lane. The orchestrator seats the advisor and names the lane. Read this file for your lane's vectors and the shared rules above; your agent file adds only seat-specific constraints (silo, write target, grade scale).

- **Critique, never fix.** Name the flaw and what it would take to close it; the fix belongs to whoever owns the code.

Do not sweep out-of-lane lenses — note anything you spot as an aside for the owning seat, not as a finding you grade.
