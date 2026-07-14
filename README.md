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

## Docker

Everything runs in containers so dev, test, and deploy behave the same on every machine. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### Local dev

```bash
docker compose up --build
```

- Frontend: http://localhost:3000 (hot reload)
- Backend: http://localhost:8000 (autoreload; health at /health)

Your host `~/.aws` credentials are mounted read-only so the backend can reach DynamoDB and Bedrock. Chat mode needs valid AWS credentials — Bedrock has no local emulator. Env vars come from `backend/.env` and `frontend/.env.local` (both optional, see the `.env.example` files).

On Windows, `~/.aws` resolves differently depending on where you run `docker compose up`: PowerShell or cmd resolve `~` to your Windows user profile (`C:\Users\<you>\.aws`), which is correct. Running via WSL2 bash instead resolves `~` to the Linux home directory, which may not contain your AWS credentials. Run `docker compose up` from the same environment where you ran `aws configure`, or replace `~/.aws` with an absolute path in `docker-compose.yml` if your setup differs.

### Containerized tests

```bash
npm run docker:test
```

Runs the backend (pytest), frontend (vitest), and MCP server (vitest) suites inside the same images CI builds.

### Production images

```bash
docker build -f backend/Dockerfile -t merlins-backend .
docker build -f frontend/Dockerfile -t merlins-frontend .
```

Build context must be the repo root (the npm workspaces lockfile lives there). The backend image contains Node 20 alongside Python because the MCP server runs as a stdio subprocess of the backend. `NEXT_PUBLIC_*` values are build args on the frontend image; all server-side secrets are runtime environment variables — never baked into images.

## Contributing

All PRs require review. See CLAUDE.md for TDD guidelines and branch protection requirements.
