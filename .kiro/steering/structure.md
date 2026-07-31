# Repository Structure & Conventions

## Directory Layout
```
.
├── .kiro/                  # Kiro config (steering, agents, settings, skills)
├── .claude/                # Claude Code artifacts (council reviews, submissions, verdicts)
│   ├── agents/             # Agent role definitions
│   ├── council/            # Active council submission + reviews
│   └── skills/             # Skill definitions (TDD, etc.)
├── backend/                # Python FastAPI backend
│   ├── src/merlins_collection/
│   │   ├── models/         # Pydantic models
│   │   │   ├── catalog/    # TCGdex card catalog models
│   │   │   ├── inventory/  # Inventory item models
│   │   │   └── business/   # Business logic models
│   │   ├── services/       # Business logic layer
│   │   │   ├── tcgdex/     # External TCGdex API client
│   │   │   ├── dynamodb/   # DynamoDB data access
│   │   │   ├── catalog_sync/
│   │   │   └── spreadsheet_import/
│   │   └── routers/        # FastAPI route handlers
│   │       ├── inventory.py
│   │       ├── public.py
│   │       ├── chat.py
│   │       ├── auth.py
│   │       └── health.py
│   ├── scripts/            # CLI tools (seed_catalog, import_spreadsheet, daily_sync, build_review)
│   └── tests/              # pytest test suites
├── frontend/               # Next.js 14 application
│   ├── app/                # App Router pages and layouts
│   ├── components/         # React components
│   ├── lib/                # Shared utilities and helpers
│   ├── public/images/      # Static images (logo/, brand/, shows/, cards/)
│   └── sanity/             # Sanity CMS schema and config
├── mcp-server/             # MCP SDK server (TypeScript)
│   └── src/                # Tool definitions, repository layer, handlers
├── shared/                 # Cross-boundary contracts
│   └── tool-contract.json  # MCP tool interface definitions
├── data/                   # Spreadsheet data and enrichment artifacts
├── docs/                   # RFCs, learning materials, design decisions
│   └── rfcs/               # Request for Comments documents
└── deploy/                 # Deployment configurations
```

## Conventions

### State Tracking
- `claude-progress.txt` at repo root is the central roadmap and state file
- All active work items, phase tracking, and completion logs live here
- Read this file before starting any task

### Code Review
- Council review loop: 4 advisors (contrarian, security, chaos, architect) + judge
- Submissions go to `.claude/council/submission.md`
- Verdict appears in `.claude/council/verdict.md`
- Archived reviews in `_archive_*` subfolders

### Naming & Style
- **Python**: snake_case, ruff for linting, pydantic for data validation
- **TypeScript**: camelCase for variables/functions, PascalCase for components/types
- **Files**: kebab-case for frontend files, snake_case for backend files
- **Tests**: co-located in `tests/` directories mirroring source structure

### Documentation
- RFCs in `docs/rfcs/` for substantial design decisions
- README.md at repo root for project overview
- CLAUDE.md at repo root for AI agent working instructions

### Docker
- Docker used for dev/test/prod parity
- `.dockerignore` at repo root

### Dependencies
- Frontend deps managed via npm workspaces
- Backend deps managed via Python (requirements or pyproject.toml)
- Flag any new dependency additions prominently
