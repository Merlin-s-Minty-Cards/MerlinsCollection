# Merlin's Minty Cards

Pokemon card business website with an authenticated inventory search tool.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, NextAuth.js, Sanity |
| Backend | Python 3.12, FastAPI, pydantic-settings, boto3 |
| MCP Server | TypeScript, MCP SDK |
| Database | AWS DynamoDB |
| Auth | AWS Cognito |
| AI | AWS Bedrock (Claude) |
| CDN | AWS CloudFront + S3 |
| CMS | Sanity |

## Local Development

### Prerequisites

- Node.js 20+
- Python 3.12+
- npm 10+

### Frontend

```bash
cd frontend
cp .env.example .env.local   # fill in values
npm install
npm run dev                  # http://localhost:3000
```

### Backend

```bash
cd backend
cp .env.example .env
pip install -e ".[dev]"
uvicorn src.merlins_collection.main:app --reload  # http://localhost:8000
```

### MCP Server

```bash
cd mcp-server
npm install
npm run build
```

## Running Tests

```bash
# All tests
npm test

# Frontend only
npm test --workspace=frontend

# Backend only
python -m pytest backend/tests -q --tb=short

# MCP server only
npm test --workspace=mcp-server
```

## Linting

```bash
# Frontend
cd frontend && npm run lint

# Backend
ruff check backend/src
```

## Environment Variables

See `frontend/.env.example` and `backend/.env.example` for required variables.

## Contributing

All PRs require review from @EthanHarter934. See CLAUDE.md for TDD guidelines and branch protection requirements.
