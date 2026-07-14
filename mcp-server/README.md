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
MCP client (backend McpToolExecutor, spawning `node dist/index.js`)
        │  stdio
        ▼
   src/index.ts ............ bootstrap: env config, DynamoDB client, stdio connect
        │
        ▼
   src/server.ts ........... buildServer(repo): registers the 5 tools
        │                    (names/schemas pinned to ../shared/tool-contract.json)
        ▼
   src/tools/*.ts .......... pure functions: (repo, args) -> result
        │  depends on
        ▼
   InventoryRepository ..... interface in src/repository.ts
        ▲
        ├── InMemoryInventoryRepository ....... tests (src/__tests__/fixtures/)
        └── DynamoDbInventoryRepository ....... production (src/dynamodb-repository.ts)
```

Each tool is an `async function(repo, ...args)` that returns a plain object. It
has no knowledge of MCP, DynamoDB, or stdio — those concerns live at the edges
(`src/index.ts` for protocol, the repository implementations for data).

## Directory layout

| Path | What it holds |
|------|---------------|
| `src/index.ts` | Entry point: env config (`AWS_REGION`, `DYNAMODB_TABLE_NAME`), DynamoDB client, stdio connect. |
| `src/server.ts` | `buildServer(repo)`: registers each tool with its input schema and adapts results into MCP responses. |
| `src/dynamodb-repository.ts` | Production `InventoryRepository` over the backend's single-table layout. |
| `src/repository.ts` | Domain types (`Card`, `PricePoint`) and the `InventoryRepository` interface. |
| `src/tools/` | One file per tool, plus `index.ts` re-exporting them all. |
| `src/__tests__/` | Vitest specs: per-tool, server registration (in-memory MCP transport), and repository (stubbed DocumentClient). |
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

## Status

Fully wired: the five tools are registered on the server (`src/server.ts`) with
zod-validated input schemas, and `DynamoDbInventoryRepository` reads the
backend's single-table layout in production. The backend spawns this server via
`McpToolExecutor` (`backend/src/merlins_collection/services/mcp_client.py`), so
**run `npm run build` here before starting the backend** — it spawns
`node dist/index.js`.

Two cross-service contracts to keep in mind when changing anything here:

- **Tool names/schemas** are pinned by `../shared/tool-contract.json`; both this
  package's tests and the backend's `test_tool_contract.py` assert against it.
  Change the contract file first, then both sides.
- **Key formats** (and the shard count) mirror
  `backend/src/merlins_collection/services/dynamodb.py` — a schema change there
  must be mirrored in `src/dynamodb-repository.ts`.
