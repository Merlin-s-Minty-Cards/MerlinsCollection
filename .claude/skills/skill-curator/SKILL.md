---
name: skill-curator
description: Review .claude/skills/ (and the lessons lesson-capture has written into CLAUDE.md) for near-duplicate skills to merge, bloated skills to split, and narrow one-off fixes that never should have generalized — then propose a consolidation plan. Run by hand periodically; not autonomous.
disable-model-invocation: true
---

# Skill Curator

[`lesson-capture`](../lesson-capture/SKILL.md) writes one lesson at a time and can still get an individual call right while the collection drifts — two lessons that each made sense alone turn out to overlap once both exist, or a skill grown from repeated small edits ends up covering ground its name no longer promises. This skill is the periodic pass that catches that drift. It has no usage telemetry to work from — unlike a system that tracks real invocation counts, staleness here is read off content and `git log` recency/touch frequency, a weaker signal, worth naming as weaker rather than treating as settled.

## Step-by-Step Execution

1. **Enumerate.** List every skill under `.claude/skills/`, and every CLAUDE.md section that reads like an accumulated lesson rather than original project documentation.
2. **Sweep each skill for four things**, citing the skill(s)/section(s) involved for every candidate:
   - **Merge candidates** — two or more skills whose descriptions or bodies cover the same territory (duplication, not just topical overlap).
   - **Split candidates** — a skill that has grown unfocused (`Sprawl`, distinct unrelated branches under one name); propose the split use the [`writing-great-skills`](../writing-great-skills/SKILL.md) delta pointer pattern so the halves reference each other's shared part instead of duplicating it.
   - **Over-narrow entries** — a skill or CLAUDE.md line that encodes a single command or one-off fix rather than a generalizable lesson: exactly what `lesson-capture`'s generalize-or-reject gate exists to keep out, flagged here for whatever slipped through anyway.
   - **Stale entries** — content that no longer bears on the codebase as it now stands.
3. **Present a plan, not edits.** List every proposed merge, split, generalization, removal, or archive — each with its reasoning — and stop. Do not touch a second file until the plan is confirmed; unlike `lesson-capture`'s single scoped write, this pass spans multiple files at once.
4. **On confirmation, apply the plan.** Every rewrite goes through `writing-great-skills`, same as any other skill edit. An archived skill moves to `.claude/skills/.archive/` rather than being deleted — nothing this pass removes is unrecoverable.
