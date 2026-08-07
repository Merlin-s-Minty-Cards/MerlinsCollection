---
name: testing
description: Locate the tests covering a change, run them, and establish that a green result is real. Use when writing or running tests, before reporting a suite result, or when another skill needs work verified.
---

# Testing

A test you have never watched fail proves nothing. **Red** is the evidence that a test can detect what it claims to detect; green means something only after red. Every rule here serves earning a real red, then reading the green honestly.

## Earning red

- Run a new test before the code that satisfies it exists, and read the failure. It must fail on its **assertion** — an import error, a missing fixture, or a misconfigured runner fails for reasons that survive the feature working, so they prove nothing.
- **A test that passes the first time you run it is a claim to check, not a win.** Either the behaviour already existed — you have written a guard, and saying so is useful — or the test asserts nothing.
- When red is unavailable because the code already works — backfilling coverage, rewriting a stale test — **mutate**: break the covered code, confirm the test fails, restore. A test suite rewritten to green without ever going red is unverified.
- Against a live endpoint or real system, a `200` is not a pass. Check that the response reflects the input: identical output across different inputs means the input was ignored.
- Prefer a real boundary over a mock where practical. A mock encodes what you believe the dependency does, so it goes green on a belief the real system may not share — the one failure it can never show you is the mismatch itself.

## Finding the tests that cover a change

- Map each changed source file to its test file before editing either. Which changed behaviour has assertions and which does not is the difference between a safe change and a hopeful one.
- **Read a neighbouring test in the target file before writing a new one.** Fixture arity, helper signatures, and seeding conventions are local; copy them from a working example rather than inferring them.
- A **skip is not a pass.** A skip marks behaviour nobody is checking. For any skip you did not just write, find out whether the code it covers is still live — a long-skipping test can leave live code unprotected for months.

## Running them

- Take the canonical commands from CLAUDE.md's Test Commands table, which also records this repo's interpreter traps (a bare `python` resolves to an unrelated environment, and the worktree can shadow the package).
- Run the **narrow selection** while iterating, and the full suite once at the end. A full run here costs minutes; paying that per edit buys nothing.
- Launch a long suite in the background writing to a file **unpiped**: `| tail` buffers, leaving the file empty until the command exits, so progress is invisible.
- Do other work while it runs and let the completion notification arrive. Polling a buffered file returns nothing and spends turns.

## Reading the result

- Establish the **baseline** first: a failure that predates the change is a finding, a new one is a regression that blocks. Check whether a pre-existing failure touches the files you changed before concluding it is unrelated.
- Carry pass/skip counts across a change (`1353 → 1370`). The delta shows what you added and confirms nothing vanished quietly.
- **A change that breaks an existing test is a decision.** Read that test's intent first: if the intent still holds, the change is wrong; if the intent is now obsolete, update the test and record inside it why the expectation moved.
