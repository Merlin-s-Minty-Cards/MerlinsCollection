# Round 2 Orchestrator Prompt

You are the orchestrator for Round 2 of the database-interface-enhancements branch on the Merlin's Minty Cards project. Follow the orchestrator rules in .kiro/agents/orchestrator.md.

## Context

- Branch: database-interface-enhancements (based on Polishing-For-Deployment at e58ee47)
- progress.txt is current at the repo root — read it first for full roadmap state
- Implementation-Plan.md has the raw requirements
- Round 1 (planning) is complete. This is Round 2.

## Your tasks this round

1. Dispatch design-doc to write RFC 0007 covering the schema and API design for tasks A1 through A5 (Advanced Trade Engine, Cosigner Management, Transaction History and Lineage, Show Analytics Data Layer, Enhanced Inventory Search). The RFC should reference the existing models/business.py, models/inventory.py, routers/admin/trades.py, and services/dynamodb.py.

2. After the RFC is written, dispatch code-writer for A6 (add LP_PLUS and LP_MINUS to the ConditionModifier enum, or add them as new Condition values, update validation, tests, and any frontend condition dropdowns) and A7 (convert the location free-text field to a standardized set of predefined values via a backend enum or constant list, add a /admin/locations endpoint to serve the list, update the inventory model validation). These two are independent and can run in parallel.

3. After code changes land, dispatch test-qa to verify no regressions.

4. Commit all work, update progress.txt checkboxes, and provide the prompt for the Round 3 orchestrator (save it to .kiro/prompts/round-3.md).

## Rules to carry forward

- TDD process: RED then GREEN then REFACTOR, never combined
- Council Loop is mandatory for behavior-changing code (code-writer submissions)
- The orchestrator owns git (commits, staging). Specialists never touch git.
- Use background processes for tests (see terminal rules in workspace steering files)
- CMD-only terminal. No bash syntax (no ls, grep, cat, rm, &&, export, heredocs)
- Conventional commits: type(scope): description
- Read .kiro/agents/ roster and dispatch to existing agents. Never improvise roles.
