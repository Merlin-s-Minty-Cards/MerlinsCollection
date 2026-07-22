# Docker Setup — Design

**Date:** 2026-07-14
**Status:** Approved (direction confirmed in brainstorming)

## Goal

Containerize the app so local development, testing, and deployment run the
same way on every machine: `docker compose up` for dev, one command for the
full test suite, and production-ready images for the backend and frontend.

No AWS resources change. Containers talk to the same DynamoDB table, Cognito
pool, and Bedrock models the app uses today, configured through the same
environment variables.

## Key architectural constraint

The MCP server is **not** a network service. The backend spawns it as a stdio
subprocess (`node dist/index.js`, see `backend/src/merlins_collection/dependencies.py`).
Therefore the backend image must contain **both** the Python runtime and
Node.js, plus the built MCP bundle. The MCP server does not get its own
container.

## Components

### 1. `GET /health` endpoint (backend — the TDD piece)

The only behavioral code change. Docker healthchecks and (later) ECS load
balancers need an unauthenticated URL that answers 200 when the app is up.

- Route: `GET /health` → `200 {"status": "ok"}`
- No auth, no AWS calls (a health check must not fail because DynamoDB is
  slow, and must not incur AWS cost per poll).
- Tested first (RED), then implemented (GREEN).

### 2. `backend/Dockerfile` (multi-stage)

- **Stage 1 (`mcp-build`):** `node:20-slim` — `npm ci` + `tsc` build of
  `mcp-server/` → `dist/`.
- **Stage 2 (runtime):** `python:3.12-slim` + Node.js 20 runtime installed.
  Installs the backend package, copies the MCP `dist/` and its production
  `node_modules`. Runs `uvicorn merlins_collection.main:app` as a non-root
  user. `MCP_SERVER_PATH` points at the baked-in bundle.
- Build context is the **repo root** (the image needs both `backend/` and
  `mcp-server/`).

### 3. `frontend/Dockerfile` (multi-stage)

- Standard Next.js pattern: deps → build → runtime on `node:20-slim`.
- Requires `output: 'standalone'` in `next.config.ts` (config-only change,
  no TDD needed) so the runtime image carries only the server bundle, not
  full `node_modules`.
- `NEXT_PUBLIC_*` vars are inlined at build time, so they are passed as
  build args; server-side secrets (`AUTH_SECRET`, Cognito client secret)
  stay runtime env vars.

### 4. `docker-compose.yml` (local dev)

- `backend` service: built from `backend/Dockerfile`, port 8000, source
  bind-mounted with `uvicorn --reload` for hot reload, `~/.aws` mounted
  read-only so boto3 finds credentials (containers can't see the host's
  credential file otherwise), env from `backend/.env`.
- `frontend` service: runs `next dev` with source bind-mounted, port 3000,
  env from `frontend/.env.local`.
- Healthcheck on the backend hitting `/health`.

### 5. `docker-compose.test.yml` (containerized tests)

- One-shot services that run each suite in the same images CI would use:
  backend pytest, frontend vitest, mcp-server vitest. `docker compose -f
  docker-compose.test.yml up` (or `run`) exits nonzero on failure so CI can
  consume it directly.

### 6. `.dockerignore` files

Root-level (plus per-context as needed): excludes `node_modules`, `.next`,
`.venv`, `__pycache__`, `dist`, `.git`, `.env*` so builds are fast and
secrets never end up in image layers.

### 7. CI integration

Add a `docker-build` job to `.github/workflows/ci.yml` that builds both
production images (no push) so a broken Dockerfile fails PRs. Existing test
jobs stay as-is.

## Explicitly out of scope

- ECR push / ECS task definitions / deploy pipeline (future work).
- Emulating AWS locally (DynamoDB Local, LocalStack) — the stack points at
  real AWS, matching how the app is developed today.
- Sanity Studio containerization (hosted service).

## Error handling / gotchas

- **Chat mode in containers requires real AWS credentials** (Bedrock has no
  emulator). The compose credential mount handles this; documented in README.
- Backend image must set `AWS_REGION` etc. via env, never baked in.
- Windows hosts: `~/.aws` mount path uses `${USERPROFILE}`-compatible syntax
  in compose (`~` works in Docker Desktop on Windows).
- MCP subprocess needs `node` on PATH inside the backend image — verified by
  the image build and a smoke check.

## Testing strategy

- `/health`: outside-in TDD (failing FastAPI TestClient test → implement).
- Dockerfiles/compose are non-behavioral scaffolding per TDD guidelines —
  verified by building the images and running the stack + containerized test
  suite, not by unit tests.
- Full verification: `docker compose build`, `docker compose up` smoke test
  (health endpoint answers, frontend serves), containerized test run passes.
