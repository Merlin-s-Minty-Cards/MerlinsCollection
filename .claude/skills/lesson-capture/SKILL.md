---
name: lesson-capture
description: Captures a generalizable lesson into CLAUDE.md or a skill. Use when the user reports something Claude built or decided fell short, or when Claude notices it took a long or circuitous path that a clearer rule would have avoided.
---

# Lesson Capture

A **fix** repairs one instance; a **lesson** is the general form of what caused it, written down so the next instance never happens. Most fixes carry no lesson — this skill's job is telling the two apart, not writing one down every time.

## Step-by-Step Execution

1. **Name the root cause**, not the symptom just fixed — the wrong assumption, missing invariant, or flawed default heuristic behind it. For a self-noticed detour rather than a reported problem, the cause is whichever rule, if it had existed before you started, would have gone straight to the fix instead of circling toward it. Completion criterion: one sentence that is neither "I made a mistake" nor a restatement of the symptom.
2. **State the lesson, or reject it.** The lesson is the root cause phrased so it would still hold on a different file, a different feature, a different day. If no such sentence survives — the cause was a one-off slip, not a pattern — say so explicitly and stop; nothing gets written this run. Completion criterion: either a one-sentence lesson exists, or an explicit "not worth recording" was stated. Silence is not a valid outcome of this step.
3. **Route it.** CLAUDE.md if the lesson is a durable fact or invariant about *this* project, true regardless of what kind of task touches it — test it against the file's own sections ("archiving is one pattern," "customer prices are condition-adjusted"). A skill if the lesson is a reusable process or judgment call that would still apply on a different project.
4. **Write it, once you've checked for a home already claiming it.**
   - CLAUDE.md: match the file's existing voice — bold claim, then evidence for why it matters, then cross-references to what it affects. Confirm no existing section already says this before adding a new one.
   - Skill: search `.claude/skills/` for one already covering this territory and fold the lesson in rather than creating a near-duplicate. Whether folding in or authoring new, invoking [`writing-great-skills`](../writing-great-skills/SKILL.md) first is not optional — never `superpowers:writing-skills` — and its delta pointer pattern is how you keep a new skill from re-explaining what a neighboring one already covers.
5. **Show the diff.** No approval gate before writing — the change lands, visibly, in the same response.

Skills and CLAUDE.md sections drift out of focus even when every individual write above was sound — that drift is [`skill-curator`](../skill-curator/SKILL.md)'s job, not this one's.
