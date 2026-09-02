---
name: tdd
description: Implement a feature or bugfix test-first, red through green to refactor. Use when the task calls for TDD.
user-invocable: true
argument-hint: <task reference or behavior> e.g. 'LIN-123' or 'retry logic for API client'
---

# Test-Driven Development

Use this for behavioral changes where a failing test can describe the desired outcome before implementation.

## Workflow

### 1. Understand

Read the request, task, issue tracker item, plan, spec, and relevant code as available — including `claude-progress.md`'s active roadmap item, if one is driving this work.

Identify:
- The desired behavior
- Existing contracts (function signatures, return types, error handling)
- Failure paths and edge cases
- How the behavior will be verified

If a spec exists, note its invariants, decisions, and testing strategy.

**Ask before writing tests** when missing information would materially change behavior, scope, safety, contracts, data shape, or verification. If the task is clear enough to proceed with a reasonable assumption, make it explicit and keep moving.

### 2. Adversarial Review Pre-Changes

Invoke the `adversarial-review` skill against the plan. Resolve every blocking finding before moving on.

### 3. Red

Consider the adversarial-review findings and write the smallest failing test that proves the desired behavior or reproduces the bug.

- Name the test after the behavior, not the implementation
- Test one thing
- Earn a real **red** — see the `testing` skill for what counts as one, and for finding the tests that already cover this code

Stop at the failing test — implementation begins in step 4.

### 4. Green

Write the minimum implementation needed to pass the test.

- Preserve existing contracts unless the task explicitly changes them
- Write only what the test demands — the goal is passing it, not a perfect design
- Add failure-path tests where they matter (invalid input, missing dependencies, error states)
- Run the narrow selection covering the change; the `testing` skill covers scope, invocation, and reading the result against the baseline

### 5. Adversarial Review Post-Changes

Invoke the `adversarial-review` skill against the diff. Resolve every blocking finding before moving on.

### 6. Refine

Consider the adversarial-review findings and refine the implementation. Simplify code and tests while they stay green.

- Remove duplication
- Improve names
- Extract helpers if the intent becomes clearer
- Close with the full suite once, per the `testing` skill

**Report:** the failing test name, why it failed, the passing result, the final verification command output — and, if a roadmap item drove this, its updated checkbox/log entry in `claude-progress.md`.

## Rules

- Work steps 1-6 in order, finishing each before starting the next.
- Tests describe behavior, not implementation details — avoid testing private internals.
- Skip TDD for documentation, pure formatting changes, or non-behavioral scaffolding (config files, type aliases with no logic).
