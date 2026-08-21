---
name: tdd
description: Implement a feature or bugfix test-first — red, green, refactor. Use when the task calls for TDD.
user-invocable: true
argument-hint: <task reference or behavior> e.g. 'LIN-123' or 'retry logic for API client'
---

# Test-Driven Development

Behavioral changes where a failing test describes the desired outcome before implementation.

## Workflow

### 1. Understand

Read the request, relevant code, and the active plan's `progress.md` (under `.kiro/plans/`) if driving a roadmap item. Identify: desired behavior, existing contracts, failure paths, edge cases, verification method.

**Ask before writing tests** when missing information would materially change behavior, scope, or contracts. Otherwise state assumptions and proceed.

### 2. Adversarial review — pre-change

Invoke the `adversarial-review` skill (solo-sweep branch) against the plan. Resolve every blocking finding before writing tests.

### 3. Red

Write the smallest failing test that proves the desired behavior or reproduces the bug.

- Name the test after the behavior, not the implementation
- Test one thing
- Earn a real **red** — see `/testing` for what counts

Stop at the failing test. No implementation yet.

### 4. Green

Minimum implementation to pass. Preserve existing contracts unless explicitly changing them. Run narrowly focused tests per `/testing`.

### 5. Adversarial review — post-change

Invoke the `adversarial-review` skill (solo-sweep branch) against the diff. Resolve every blocking finding before refining.

### 6. Refine

Simplify code and tests while green. Remove duplication, improve names, extract helpers. Run the full suite once at the end per `#[[file:.kiro/steering/terminal.md]]`.

**Report:** failing test name, why it failed, passing result, final verification output.

## Rules

- Steps 1–6 in order. Never combine phases.
- Tests describe behavior, not implementation details.
- Prefer real boundaries over mocks when practical.
- Skip TDD for documentation, formatting, or non-behavioral scaffolding.
