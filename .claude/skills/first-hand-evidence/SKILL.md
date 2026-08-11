---
name: first-hand-evidence
description: Getting first-hand evidence of an artifact before sign-off. Use before reporting work done, signing off a user-facing change, or writing a PR body.
---

# First-Hand Evidence

Every check you ran is a **proxy**. A green suite, a clean lint, a passing type-check and a successful build all say one narrow thing: the code runs. They are silent on what a person meets — whether the page is legible, the control reachable, the output shaped right, the gap visible. Sign-off rests on **first-hand** evidence of the artifact in the form the user encounters it.

[`testing`](../testing/SKILL.md) governs whether a green result is real. This governs whether green is enough.

## Getting it first-hand

Match the observation to the surface:

| Surface | First-hand evidence |
|---|---|
| Web page | Render the real route and look at it |
| CLI | Run it and read the output |
| API | Call it and read the body, not the status |
| Generated file or doc | Open the rendered result |

Then compare it against its nearest sibling — the neighbouring page, command, or endpoint. A surface that reads unlike its neighbours is the finding; convention lives in the working example next door, not in inference.

## When the artifact is out of reach

Auth walls, hardware, a live database you must not write to. Report what you checked and name what you did not: *"tests, lint and build pass; I have not seen the page rendered."* A scoped claim hands the reader a risk they can act on, where "ready to ship" hides it.

## The artifact carries its own gaps

What you could not build still belongs on screen — a disabled control naming its blocker, an empty state saying why. A gap the user cannot see reads as one nobody noticed.

## Symptoms that first-hand evidence is missing

- The definition of done lists only machine checks. It is a floor; clearing it answers "did anything break?", never "is this good?"
- The surface was assembled over several tasks and no task ever opened it.
- The phrase "ready to ship" is about to follow a list of exit codes.
- Confidence in the writeup outruns the evidence: a measured result and an inferred one, reported in the same voice.
