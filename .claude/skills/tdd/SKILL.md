---
name: tdd
description: Implement a feature or bugfix test-first. Understand the desired behavior, write a failing test, make it pass, then simplify. Use whenever the user asks to implement using TDD, says "write a failing test first", wants test-driven development, mentions red-green-refactor, or asks to add behavior with tests driving the implementation.
user-invocable: true
argument-hint: <task reference or behavior> e.g. 'LIN-123' or 'retry logic for API client'
---

# Test-Driven Development

Use this for behavioral changes where a failing test can describe the desired outcome before implementation.

## Workflow

### 1. Understand

Read the request, task, issue tracker item, plan, spec, and relevant code as available — including `claude-progress.txt`'s active roadmap item, if one is driving this work.

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
- Run it and confirm it fails for the expected reason — a compilation error or wrong assertion message, not an import error or misconfigured test runner

Do not write any implementation code yet.

### 4. Green

Write the minimum implementation needed to pass the test.

- Preserve existing contracts unless the task explicitly changes them
- Don't over-engineer — the goal is passing the test, not a perfect design
- Add failure-path tests where they matter (invalid input, missing dependencies, error states)
- Run all tests to confirm the new one passes and nothing else breaks

### 5. Adversarial Review Post-Changes

Invoke the `adversarial-review` skill against the diff. Resolve every blocking finding before moving on.

### 6. Refine

Consider the adversarial-review findings and refine the implementation. Simplify code and tests while they stay green.

- Remove duplication
- Improve names
- Extract helpers if the intent becomes clearer
- Run the focused suite first, then the project's full checks

**Report:** the failing test name, why it failed, the passing result, the final verification command output — and, if a roadmap item drove this, its updated checkbox/log entry in `claude-progress.txt`.

## Rules

- Follow steps 1-6 in order. Do not skip any steps.
- Tests describe behavior, not implementation details — avoid testing private internals.
- Prefer real boundaries over mocks when practical — mocks that don't match production behavior create false confidence.
- Skip TDD for documentation, pure formatting changes, or non-behavioral scaffolding (config files, type aliases with no logic).
