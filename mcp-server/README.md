# MCP Server

The Model Context Protocol (MCP) server for Merlin's Minty Cards. It exposes the
card inventory to Claude as a set of callable **tools**, so that the chat mode of
the inventory search tool (`/inventory`) can answer natural-language questions
like _"what's my most valuable Base Set card?"_ or _"flag anything I've listed
below market."_

An MCP client (the backend's AWS Bedrock chat integration) launches this server
as a subprocess and talks to it over stdio.

## Architecture

The guiding idea is that **tools never talk to a data source directly** — they
depend only on the `InventoryRepository` interface. This keeps the business logic
pure and trivially testable, and lets the data source change (in-memory today,
DynamoDB in production) without touching a single tool.

```
MCP client (Bedrock chat)
        │  stdio
        ▼
   src/index.ts ............ creates the McpServer, registers tools  ← see "Status" below
        │
        ▼
   src/tools/*.ts .......... pure functions: (repo, args) -> result
        │  depends on
        ▼
   InventoryRepository ..... interface in src/repository.ts
        ▲
        ├── InMemoryInventoryRepository ... tests (src/__tests__/fixtures/)
        └── DynamoDB-backed repository ..... production (not yet written)
```

Each tool is an `async function(repo, ...args)` that returns a plain object. It
has no knowledge of MCP, DynamoDB, or stdio — those concerns live at the edges
(`src/index.ts` for protocol, the repository implementations for data).

## Directory layout

| Path | What it holds |
|------|---------------|
| `src/index.ts` | Server entry point: builds the `McpServer` and connects it over stdio. |
| `src/repository.ts` | Domain types (`Card`, `PricePoint`) and the `InventoryRepository` interface. |
| `src/tools/` | One file per tool, plus `index.ts` re-exporting them all. |
| `src/__tests__/tools/` | A Vitest spec per tool. |
| `src/__tests__/fixtures/` | The `card(...)` builder and `InMemoryInventoryRepository`. |

## Domain model

Defined in [`src/repository.ts`](src/repository.ts):

- **`Card`** — `id`, `name`, `set`, `condition`, `quantity`, `value` (current
  listed price per unit), and `marketPrice` (external market reference per unit).
- **`PricePoint`** — a single historical `{ date, price, source }` observation.
- **`InventoryRepository`** — the data-access boundary: `listCards()` and
  `getPriceHistory(cardId)`.

Two value conventions used throughout the tools:

- **Per-unit value** is `card.value` for a single card.
- **Holding value** is `card.value * card.quantity` (what the whole stack is worth).

## Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `getInventorySummary` | `(repo)` | Total card count, total value, unique-set count, and the top five cards by per-unit value. |
| `searchInventory` | `(repo, filters)` | Cards matching all provided filters (name substring, set, condition, inclusive per-unit value range), AND semantics. |
| `getCardPriceHistory` | `(repo, cardId)` | A card's price history sorted oldest-to-newest; throws if the id is unknown. |
| `calculateInventoryValue` | `(repo)` | Total holding value with breakdowns by set and by condition, plus an ISO-8601 timestamp. |
| `flagUnderpricedCards` | `(repo, thresholdPercent)` | Cards listed below `thresholdPercent` of market price (strict less-than; skips non-positive market prices). |

Each function and its result type carries JSDoc with the precise edge-case
semantics (tie-breaking, inclusive vs. exclusive bounds, etc.).

## Development

```bash
npm install                      # from this folder, or the repo root
npm run build                    # tsc -> dist/
npm test                         # vitest run (also: npm run test --workspace=mcp-server from root)
npm run test:watch               # vitest in watch mode
npm run test:coverage            # vitest with v8 coverage
```

TypeScript is configured strictly (`strict` + `noUncheckedIndexedAccess`) and
emits ES modules (`NodeNext`), so intra-package imports use explicit `.js`
extensions even though the sources are `.ts`.

### Testing approach

Tests use a real in-memory `InventoryRepository` (`InMemoryInventoryRepository`)
rather than mocks, so they exercise each tool against a genuine implementation of
the boundary. The fake returns **copies** of its seeded data, which guarantees a
tool cannot accidentally mutate shared state. Seed cards with the `card(...)`
builder and override only the fields a test cares about.

This package follows the repo-wide outside-in TDD process (see the root
`CLAUDE.md`): write a failing test, make it pass, then refactor.

## Status & roadmap

The five tools are fully implemented and tested, but the server is still a
**skeleton**: `src/index.ts` creates the `McpServer` and connects it, yet does
not register any tools, so a client currently sees an empty tool list. Two pieces
remain (each best driven by TDD):

1. **A production `InventoryRepository`** — a DynamoDB-backed implementation of
   the interface to inject into the tools.
2. **Tool registration** — a `server.registerTool(...)` call per tool that
   declares the input schema (validating the args these functions currently trust)
   and adapts each function's return value into an MCP tool response.
