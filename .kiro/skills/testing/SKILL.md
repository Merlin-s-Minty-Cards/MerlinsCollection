---
name: testing
description: Run tests covering a change and establish that a green result is real. Use when writing or running tests, before reporting a suite result, or when another skill needs work verified.
---

# Testing

A test you have never watched fail proves nothing. **Red** is evidence a test can detect what it claims; green means something only after red.

## Earning red

- Run a new test before satisfying code exists. It must fail on its **assertion**, not on an import error or misconfigured runner.
- A test that passes first time is a claim to check — either the behavior already existed (a guard) or the test asserts nothing.
- When red is unavailable (backfilling coverage): **mutate** the covered code, confirm the test fails, restore.
- Against a live endpoint, `200` is not a pass — check the response reflects the input.

## Finding tests that cover a change

- Map each changed source file to its test file before editing either.
- Read a neighboring test in the target file before writing a new one — copy fixture conventions from working examples.
- A **skip is not a pass** — find whether the code it covers is still live.

## Running

- Use canonical commands from `#[[file:.kiro/steering/terminal.md]]` (Test & Lint Commands table).
- Run the **narrow selection** while iterating; the full suite once at the end.
- Launch long suites as background processes per the terminal steering rules.

## Reading the result

- Establish the **baseline** first: a pre-existing failure is a finding, a new one is a regression that blocks.
- Carry pass/skip counts across a change (`1353 → 1370`) — the delta confirms nothing vanished.
- A change that breaks an existing test is a decision: read the test's intent. If intent holds, the change is wrong; if obsolete, update the test and record why.
