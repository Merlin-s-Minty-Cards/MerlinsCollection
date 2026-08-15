---
name: design-doc
description: Draft an architecture RFC before implementing a substantial feature — technical constraints, data schemas, API contracts, and service structure into docs/rfcs/NNNN-*.md. Use before writing code for a new service, a schema or contract change, or any multi-component feature.
---

# Design Doc

Compile a feature's technical constraints, data schemas, API contracts, and service structure into one standard markdown RFC before implementation begins. This is what `initialize-roadmap`'s roadmap and the implementation work get built against.

## Constraints

- **Produce exactly one artifact:** the RFC file. Application code, tests and configuration come later, from the implementation work this RFC is built for.
- Ground the design in the real project. Read the existing architecture (Next.js 14 `frontend/`, FastAPI `backend/`, MCP `mcp-server/`, Sanity CMS, the AWS services in CLAUDE.md) before proposing structures — an RFC that contradicts the existing stack is wrong by default.
- Be concrete: schemas get real field names and types, endpoints get real routes/methods/example payloads, components get real file paths. "TBD" belongs only in Open Questions.
- Design to the requirement, not beyond it. Flag any genuinely necessary new service, layer, or dependency prominently rather than adding it quietly.
- **Scope and mechanism are separate approvals.** A user picking *which* problems to fix (e.g. from a multi-select) has not picked *how* to fix each one. If investigation already surfaced more than one viable mechanism for an item — a scheduled job vs. an on-event trigger, a full redesign vs. a narrower wire-up — that mechanism choice is still open. Put it to the user with `AskUserQuestion` before `Detailed Design` commits to one, rather than silently choosing the most obvious option and relegating the rest to `Alternatives Considered`.
- Save as `docs/rfcs/NNNN-<kebab-case-title>.md` (next available number; create the directory if needed) unless the user names another location.

## Step-by-Step Execution

1. **Collect the inputs.** Gather the feature requirements from the user, plus anything relevant in `claude-progress.txt`, prior RFCs, and the affected source directories. List the hard constraints (auth requirements, existing API shapes, DynamoDB schema flexibility, CMS content models). Check this list against the mechanism-choice constraint above — resolve any open ones now, before drafting.
2. **Survey the current state.** Read the code at the integration points the feature will touch. Note existing patterns the design should follow rather than reinvent.
3. **Draft the RFC** with this structure:
   - `# RFC NNNN: <Title>` — status (`Draft`), author, date.
   - `## Summary` — the change in one paragraph.
   - `## Motivation` — the problem and why now.
   - `## Detailed Design` — component/service structure, request flows, where each piece lives in the repo. Include a mermaid diagram when a flow spans layers.
   - `## Data Schemas` — tables/collections/document shapes with field names, types, indexes.
   - `## API Contracts` — routes, methods, auth requirements, request/response examples; MCP tool signatures if applicable.
   - `## Alternatives Considered` — the realistic options and why they lost.
   - `## Risks & Mitigations` — failure modes, migration concerns, security surface.
   - `## Open Questions` — decisions that need a human call.
4. **Self-check.** Verify every schema and contract is internally consistent and consistent with the existing codebase — no route defined twice, no field referenced but never declared.
5. **Write the file and report.** Save the RFC, then summarize its key decisions and open questions in a few sentences so the user can review without opening the file first.
