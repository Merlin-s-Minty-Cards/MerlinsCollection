# Task D: Lesson Capture

**Depends on:** Tasks A, B1, B2, C1, C2, C3, C4 all merged/complete.

**Files:** whatever `lesson-capture` decides — likely `CLAUDE.md` (a new
rule, or an addition to an existing one) or a skill file under
`.claude/skills/`.

- [ ] **Step 1: Invoke the `lesson-capture` skill**

Prompt it with the following context (do not skip straight to writing
CLAUDE.md yourself — let the skill make the generalization call):

> RFC 0012 (`docs/rfcs/0012-layout-width-graded-manual-entry-consignment-ui.md`)
> found that `/admin/trade`'s graded-manual-entry block
> (`IncomingCardForm.tsx`'s `gradedSelectable = !manual && gradedAllowed`,
> and the Buy-mode `gradedAllowed={mode !== 'buy'}` gate) was disabling an
> escape hatch for a reason that had *already been solved elsewhere in the
> same component* — the cert-ownership warning it was "pending"
> (`GET /slabs/certs/{cert}`, lines ~101-123) already existed, already fired
> on `kind === 'graded'` alone, and was simply unreachable behind the two
> gates. Two features had drifted apart inside one file: the safety check
> got built, the gate that was waiting on it never got removed.
>
> CLAUDE.md already has a related rule, "AN ESCAPE HATCH IS NEVER GATED ON
> THE FAILURE OF THE PATH IT ESCAPES" (from RFC 0010/0011's manual-entry
> work) — but that rule is about an escape hatch only being reachable *after
> a primary path fails*. This is a different failure shape: an escape hatch
> disabled for a stated precondition that was quietly satisfied by later
> work in the same file, with nobody circling back to remove the gate. Is
> this generalizable enough to write down (e.g. "when a gate cites a
> specific missing piece as its reason, grep for whether that piece has
> since been built before assuming the gate is still load-bearing"), or is
> it a one-off not worth a permanent rule? Make the call; if it generalizes,
> write it to CLAUDE.md or a skill (not both) following this repo's existing
> tone (see the "ESCAPE HATCH" and "AN ESCAPE HATCH..." sections of
> CLAUDE.md for the house style — concrete quote, `>` blockquote for the
> rule, specific file:line evidence, no vague "be careful" language).

- [ ] **Step 2: Record the outcome**

If the skill writes a new rule, note where in a one-line commit. If it
declines (judges this too narrow to generalize), that's also a valid
outcome — record nothing further, this task is still complete.

- [ ] **Step 3: Commit (only if a rule was written)**

```bash
git add CLAUDE.md  # or whichever file lesson-capture touched
git commit -m "docs(rfc-0012): capture lesson on stale escape-hatch gates"
```
