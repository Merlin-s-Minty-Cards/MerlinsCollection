---
name: first-hand-evidence
description: Verify an artifact first-hand before sign-off. Use before reporting work done, signing off a user-facing change, or writing a PR body.
---

# First-Hand Evidence

Every check you ran is a **proxy**. A green suite says the code runs — it is silent on what a person meets. Sign-off rests on first-hand evidence of the artifact in the form the user encounters it.

## Getting it first-hand

| Surface | Evidence |
|---|---|
| Web page | Render the real route and look at it |
| CLI | Run it and read the output |
| API | Call it and read the body, not the status |
| Generated file | Open the rendered result |

Compare against its nearest sibling — the neighbouring page, command, or endpoint. A surface unlike its neighbours is the finding.

## When the artifact is out of reach

Auth walls, hardware, live databases. Report what you checked and name what you did not: *"tests, lint and build pass; I have not seen the page rendered."*

## The artifact carries its own gaps

What you could not build still belongs on screen — a disabled control naming its blocker, an empty state saying why.

## Symptoms that evidence is missing

- Definition of done lists only machine checks.
- The surface was assembled over several tasks and no task ever opened it.
- "Ready to ship" follows a list of exit codes.
