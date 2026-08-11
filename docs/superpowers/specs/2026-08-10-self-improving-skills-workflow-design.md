# Self-Improving Skills Workflow

Date: 2026-08-10

## Problem

Claude Code sessions on this repo already accumulate lessons ad hoc — e.g.
`81f540e skill(first-hand-evidence): green checks are a proxy, not the artifact`
was a one-off manual response to a specific failure. The owner wants this
formalized into a repeatable process, modeled on how Nous Research's Hermes
Agent closes the loop between "something went wrong" and "the instructions
that would have prevented it get written down" — without the failure mode
Hermes exists partly to avoid: skills that fill up with narrow, one-off
command fixes instead of general lessons.

## Research summary

Full findings are in the conversation transcript; the load-bearing points:

- **Hermes Agent** (Nous Research) runs a two-tier system — a small, hard-capped
  `MEMORY.md` for durable facts, and on-demand skills for procedures — plus a
  separate **Curator** background pass restricted to agent-authored skills,
  which merges near-duplicates and archives stale ones. This is the strongest
  precedent for a periodic anti-bloat pass distinct from the real-time write.
- **Voyager** and **`aviadr1/claude-meta`** both force generality **at write
  time** via an explicit "abstract and generalize" instruction, rather than
  filtering after the fact. `claude-meta` is the closest direct precedent to
  what's being built here, but has no routing logic (everything goes to one
  file) and no dedup/consolidation pass — weaker than Hermes on bloat control.
- **Reflexion** truncates a reflection buffer by recency/size only — no
  general-vs-specific judgment. Named here as a gap, not a pattern to copy.
- No system reviewed (including Anthropic's own Agent Skills docs) has a clean
  algorithmic rule for routing an update to an always-loaded file (CLAUDE.md)
  vs. an on-demand skill file. That routing stays a judgment call everywhere.
- `writing-great-skills`' `Context Pointer` and `Model-Invoked` definitions
  already generalize to cross-skill references, but no named pattern
  distinguished "split a bloated skill into two that reference each other with
  a local delta" from `Router Skill` (which is user-invoked-only and can "hint,
  never fire"). Fixed by naming it **`Delta Pointer`** — since `skill-curator`
  depends on it existing as a citable pattern, not just a latent capability.

## Design

### `lesson-capture` (model-invoked)

Fires on either branch:
- the user reports that something Claude built or decided fell short, or
- Claude notices, unprompted, that it took a long or circuitous path to an
  outcome a clearer skill or CLAUDE.md rule would have reached directly.

Process: name the root cause (not the symptom) → mandatory generalize-or-reject
gate (produce one lesson sentence, or explicitly say "not worth recording" and
write nothing — this is the anti-bloat gate, borrowed from Voyager/claude-meta)
→ route to CLAUDE.md (durable project fact/invariant, true regardless of task
type) or a skill (reusable process/judgment call, would still apply on a
different project) → if a skill, check for an existing one covering the same
territory before creating a new file, and require `writing-great-skills` (never
the superpowers equivalent) for any skill write → surface the diff.

No pre-write approval gate (owner chose autonomous routing over "always ask").

### `skill-curator` (user-invoked, run by hand)

The periodic backstop Hermes has and `claude-meta` lacks. Reviews
`.claude/skills/` and the CLAUDE.md sections `lesson-capture` can touch;
without usage telemetry (unlike Hermes), staleness is judged from content plus
`git log` recency — a weaker signal, noted as such rather than assumed solved.
Flags near-duplicates to merge **and** bloated/unfocused skills to split,
proposing splits use the `Delta Pointer` pattern (see below) so a split
doesn't double total content. Presents a plan and waits for the owner's
go-ahead before touching multiple files — unlike `lesson-capture`'s single
scoped edit, this pass can touch several at once. Edits still go through
`writing-great-skills`.

### `writing-great-skills` patch

Added `Delta Pointer`: a model-invoked skill pointing at another model-invoked
skill plus one local line of delta — distinct from `Router Skill`
(user-invoked-only, hints but never fires) and from `Progressive Disclosure`
(reference disclosed to a file within the *same* skill's folder). This is what
makes `skill-curator`'s split recommendation cheap instead of duplicative.

### CLAUDE.md addendum

A short addition to "Agent Workflow" naming both new skills and their triggers,
so `lesson-capture` fires reliably as a model-invoked skill.

## Out of scope

- No usage telemetry / invocation tracking is being built — `skill-curator`
  works off git history instead, a known-weaker signal than Hermes has.
- No approval gate on `lesson-capture`'s single-file writes.
- No change to the harness-level cross-project auto-memory system
  (`~/.claude/projects/.../memory/`) — that's user-scoped, this is
  project-scoped; they're complementary, not overlapping.
