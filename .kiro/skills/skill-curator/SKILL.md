---
name: skill-curator
description: Periodic hand-run pass over .kiro/ skills, agents, and steering — finds near-duplicates to merge, sprawl to split, one-off fixes that never should have generalized, and stale content, then proposes a consolidation plan.
disable-model-invocation: true
---

# Skill Curator

[`lesson-capture`](../lesson-capture/SKILL.md) writes one lesson at a time and can still get an individual call right while the collection drifts — two lessons that each made sense alone turn out to overlap once both exist, or a skill grown from repeated small edits ends up covering ground its name no longer promises. This skill is the periodic pass that catches that drift. It has no usage telemetry to work from — unlike a system that tracks real invocation counts, staleness here is read off content and `git log` recency/touch frequency, a weaker signal, worth naming as weaker rather than treating as settled.

## Step-by-Step Execution

1. **Enumerate.** List every skill under `.kiro/skills/`, every agent under `.kiro/agents/`, and every `.kiro/steering/` section that reads like an accumulated lesson rather than original project documentation. Agents and skills share one namespace for this pass: an agent definition drifts the same ways a skill does, and an agent restating a skill is duplication like any other.
2. **Sweep each file for four things**, citing the file(s)/section(s) involved for every candidate:
   - **Merge candidates** — two or more files whose descriptions or bodies cover the same territory (duplication, not just topical overlap).
   - **Split candidates** — a file that has grown unfocused (`Sprawl`, distinct unrelated branches under one name); propose that the split use the [`writing-great-skills`](../writing-great-skills/SKILL.md) delta pointer pattern so the halves reference each other's shared part instead of duplicating it.
   - **Over-narrow entries** — a skill, agent, or steering line that encodes a single command or one-off fix rather than a generalizable lesson: exactly what `lesson-capture`'s generalize-or-reject gate exists to keep out, flagged here for whatever slipped through anyway.
   - **Stale entries** — content that no longer bears on the codebase as it now stands.
3. **Present a plan, not edits.** List every proposed merge, split, generalization, removal, or archive — each with its reasoning — and stop. Do not touch a second file until the plan is confirmed; unlike `lesson-capture`'s single scoped write, this pass spans multiple files at once.
4. **On confirmation, apply the plan.** Every rewrite goes through `writing-great-skills`, same as any other skill edit. Agent frontmatter is configuration: prune bodies freely, leave the keys — `name`, `description`, `model`, `tools` — intact. An archived file moves to `.kiro/skills/.archive/` or `.kiro/agents/.archive/` rather than being deleted, so nothing this pass removes is unrecoverable.
