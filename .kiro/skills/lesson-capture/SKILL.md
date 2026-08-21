---
name: lesson-capture
description: Capture a generalizable lesson into steering or a skill when something Claude built fell short, or when a long circuitous path could have been avoided by a clearer rule.
---

# Lesson Capture

A **fix** repairs one instance; a **lesson** is the general form, written so the next instance never happens. Most fixes carry no lesson — this skill tells the two apart.

## Execution

1. **Name the root cause** — the wrong assumption, missing invariant, or flawed heuristic behind the problem. Not "I made a mistake" nor a restatement of the symptom.
2. **State the lesson, or reject it.** Phrase the root cause so it holds on a different file, feature, or day. If no such sentence survives (one-off slip, not a pattern), say so and stop — nothing gets written.
3. **Route it.** Steering (`#[[file:.kiro/steering/]]`) if the lesson is a durable project fact true regardless of task type. A skill if it's a reusable process that would apply on a different project.
4. **Write it** after checking no existing file already claims it. Match existing voice. For skills, follow the principles in `/writing-great-skills`.
5. **Show the diff.** The change lands visibly in the same response.

## Triggers

- User reports something the agent built or decided fell short.
- Agent notices it took a circuitous path a clearer rule would have avoided.
- A "fix" request signals a previous conversation got something wrong.
