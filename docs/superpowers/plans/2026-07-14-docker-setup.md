# Docker Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the app — dev compose stack, containerized test suite, and production images for backend and frontend — plus the `/health` endpoint they require.

**Architecture:** The backend image bundles Python 3.12 AND Node 20 because the backend spawns the MCP server as a stdio subprocess (`node dist/index.js`); the MCP server is NOT a separate container. The frontend image uses Next.js standalone output. Both Dockerfiles use the **repo root as build context** because the only `package-lock.json` lives at the repo root (npm workspaces).

**Tech Stack:** Docker multi-stage builds, docker compose v2, FastAPI, Next.js 15, npm workspaces.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-14-docker-setup-design.md`
- Build context for BOTH Dockerfiles is the repo root (lockfile lives there).
- Node version in images: `node:20-slim`. Python: `python:3.12-slim`.
- The final (default) stage of every Dockerfile must be the production `runtime` stage — test/dev stages go earlier so a bare `docker build` produces the prod image.
- No AWS emulators. Containers use real AWS via env vars + mounted `~/.aws`.
- Never bake secrets or `.env` files into images (`.dockerignore` excludes `.env*`).
- **Docker is NOT installed on the development machine.** Every step marked "(requires Docker)" is verified in CI (Task 6's `docker-build` job) or after the user installs Docker Desktop. Do not fail the task if `docker` is missing — note it and move on; all non-Docker verification (pytest, config validity) must still pass.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: `GET /health` endpoint (TDD)

The only behavioral code change. Docker `HEALTHCHECK` and ECS load balancers poll it. Must be unauthenticated and make no AWS calls.

**Files:**
- Test: `backend/tests/routers/test_health.py` (create)
- Create: `backend/src/merlins_collection/routers/health.py`
- Modify: `backend/src/merlins_collection/main.py` (import + `include_router`)

**Interfaces:**
- Consumes: `client` fixture from `backend/tests/conftest.py` (a `fastapi.testclient.TestClient` around the app).
- Produces: `GET /health` → `200` with JSON body `{"status": "ok"}`. Task 2's `HEALTHCHECK` and Task 4's compose healthcheck depend on this exact route.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/routers/test_health.py`:

```python
"""GET /health — unauthenticated liveness probe for containers/load balancers."""


def test_health_returns_ok_without_auth(client):
    # No Authorization header on purpose: orchestrators poll anonymously.
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run (from repo root): `python -m pytest backend/tests/routers/test_health.py -v`
Expected: FAIL — `assert 404 == 200` (route doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/merlins_collection/routers/health.py`:

```python
"""Unauthenticated liveness probe for Docker healthchecks and load balancers.

Deliberately does no I/O: a health check must not fail because DynamoDB is
slow, and must not incur an AWS call per poll.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

In `backend/src/merlins_collection/main.py`, change the router import line:

```python
from merlins_collection.routers import auth, chat, health, inventory
```

and add alongside the existing `include_router` calls:

```python
app.include_router(health.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/routers/test_health.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest backend/tests -q --tb=short`
Expected: all pass, no regressions. Also run `ruff check backend/src` — clean.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/routers/test_health.py backend/src/merlins_collection/routers/health.py backend/src/merlins_collection/main.py
git commit -m "Add unauthenticated GET /health liveness endpoint"
```

---

### Task 2: Root `.dockerignore` + backend Dockerfile

Multi-stage backend image: build MCP bundle with Node, then a Python runtime that also carries the Node binary so the backend can spawn the MCP subprocess. Includes a `test` stage (backend pytest) and an `mcp-test` stage (MCP vitest) that Task 5 reuses.

**Files:**
- Create: `.dockerignore` (repo root)
- Create: `backend/Dockerfile`

**Interfaces:**
- Consumes: `GET /health` from Task 1 (Dockerfile `HEALTHCHECK`).
- Produces: image stages named `mcp-build`, `mcp-test`, `mcp-deps`, `base`, `test`, `runtime` (default/last). Task 4 builds `runtime`; Task 5 builds `test` and `mcp-test`; Task 6 builds `runtime`. Backend listens on port 8000. `MCP_SERVER_PATH=/app/mcp-server/dist/index.js` is set in the image.

- [ ] **Step 1: Create root `.dockerignore`**

```
# Dependencies / build output (rebuilt inside the image)
node_modules
**/node_modules
.next
**/.next
dist
**/dist
*.tsbuildinfo

# Python
.venv
venv
**/__pycache__
*.pyc
.pytest_cache
.ruff_cache
**/*.egg-info

# Secrets — never in image layers
.env
**/.env
**/.env.*

# Repo noise
.git
.github
.claude
.superpowers
docs
coverage
**/coverage
```

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Build context is the REPO ROOT (the lockfile and both workspaces live there):
#   docker build -f backend/Dockerfile .

# ---- MCP server: compile TypeScript (dev deps included) ----
FROM node:20-slim AS mcp-build
WORKDIR /build
COPY package.json package-lock.json ./
COPY mcp-server/package.json mcp-server/package.json
RUN npm ci --workspace=mcp-server
COPY mcp-server/tsconfig.json mcp-server/tsconfig.json
COPY mcp-server/src mcp-server/src
RUN npm run build --workspace=mcp-server

# ---- MCP server: vitest stage (used by docker-compose.test.yml) ----
FROM mcp-build AS mcp-test
COPY mcp-server/vitest.config.ts mcp-server/vitest.config.ts
CMD ["npm", "test", "--workspace=mcp-server"]

# ---- MCP server: production node_modules only ----
FROM node:20-slim AS mcp-deps
WORKDIR /build
COPY package.json package-lock.json ./
COPY mcp-server/package.json mcp-server/package.json
RUN npm ci --workspace=mcp-server --omit=dev

# ---- Backend + MCP bundle on one image ----
FROM python:3.12-slim AS base
# The backend spawns the MCP server as `node dist/index.js` — it needs a Node
# runtime. The bare binary from the build stage is enough (same Debian base).
COPY --from=mcp-build /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src backend/src
RUN pip install --no-cache-dir ./backend
# package.json carries "type": "module" — Node needs it to load dist/ as ESM.
COPY mcp-server/package.json mcp-server/package.json
COPY --from=mcp-build /build/mcp-server/dist mcp-server/dist
COPY --from=mcp-deps /build/node_modules node_modules
ENV MCP_SERVER_PATH=/app/mcp-server/dist/index.js

# ---- Backend pytest stage (used by docker-compose.test.yml) ----
FROM base AS test
RUN pip install --no-cache-dir "./backend[dev]"
COPY backend/tests backend/tests
WORKDIR /app/backend
CMD ["pytest", "-q", "--tb=short"]

# ---- Production runtime (LAST stage = default build target) ----
FROM base AS runtime
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
CMD ["uvicorn", "merlins_collection.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Verify (requires Docker)**

If Docker is available:

```bash
docker build -f backend/Dockerfile -t merlins-backend .
docker run --rm -d -p 8000:8000 -e AUTH_DISABLED=true --name mb merlins-backend
sleep 3 && curl -s http://localhost:8000/health   # expect {"status":"ok"}
docker rm -f mb
```

If Docker is NOT available (current machine): state that verification is deferred to the CI `docker-build` job (Task 6). Sanity-check instead that every path referenced in COPY lines exists in the repo (`package.json`, `package-lock.json`, `mcp-server/package.json`, `mcp-server/tsconfig.json`, `mcp-server/src`, `mcp-server/vitest.config.ts`, `backend/pyproject.toml`, `backend/src`, `backend/tests`).

- [ ] **Step 4: Commit**

```bash
git add .dockerignore backend/Dockerfile
git commit -m "Add backend Dockerfile (Python + Node for MCP subprocess) and root .dockerignore"
```

---

### Task 3: Next.js standalone output + frontend Dockerfile

**Files:**
- Modify: `frontend/next.config.ts` (add `output: 'standalone'`)
- Create: `frontend/Dockerfile`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: image stages `deps`, `build`, `dev`, `test`, `runtime` (default/last). Task 4 uses `dev`; Task 5 uses `test`; Task 6 builds `runtime`. Frontend listens on port 3000. `NEXT_PUBLIC_*` values are **build args** (they are inlined into the JS bundle at build time); server-side secrets stay runtime env.

- [ ] **Step 1: Add standalone output to `frontend/next.config.ts`**

```typescript
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker runtime image doesn't
  // need the full node_modules tree.
  output: 'standalone',
  images: {
    remotePatterns: [
      // pokemontcg.io card art (returned by the inventory backend)
      { protocol: 'https', hostname: 'images.pokemontcg.io' },
      // Add CloudFront domain here when provisioned:
      // { protocol: 'https', hostname: '<id>.cloudfront.net' }
    ],
  },
}

export default nextConfig
```

- [ ] **Step 2: Verify the build still works natively**

Run (from repo root): `npm run build --workspace=frontend`
Expected: build succeeds and `frontend/.next/standalone/` now exists. Because this is an npm-workspaces repo, Next traces from the repo root: the server entry lands at `frontend/.next/standalone/frontend/server.js` — the Dockerfile paths below depend on this monorepo layout.

- [ ] **Step 3: Create `frontend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Build context is the REPO ROOT (the lockfile lives there):
#   docker build -f frontend/Dockerfile .

# ---- Workspace dependencies ----
FROM node:20-slim AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
RUN npm ci --workspace=frontend

# ---- Production build ----
FROM deps AS build
COPY frontend frontend
# NEXT_PUBLIC_* values are inlined into the client bundle AT BUILD TIME —
# they must be build args, not runtime env. Server-side secrets (AUTH_SECRET,
# Cognito client secret, SANITY_API_TOKEN) are runtime env on the container.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SANITY_PROJECT_ID=""
ARG NEXT_PUBLIC_SANITY_DATASET=production
ARG NEXT_PUBLIC_CLOUDFRONT_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SANITY_PROJECT_ID=$NEXT_PUBLIC_SANITY_PROJECT_ID \
    NEXT_PUBLIC_SANITY_DATASET=$NEXT_PUBLIC_SANITY_DATASET \
    NEXT_PUBLIC_CLOUDFRONT_URL=$NEXT_PUBLIC_CLOUDFRONT_URL
RUN npm run build --workspace=frontend

# ---- Dev server with hot reload (used by docker-compose.yml) ----
FROM deps AS dev
COPY frontend frontend
EXPOSE 3000
CMD ["npm", "run", "dev", "--workspace=frontend", "--", "-H", "0.0.0.0"]

# ---- Vitest stage (used by docker-compose.test.yml) ----
FROM deps AS test
COPY frontend frontend
CMD ["npm", "test", "--workspace=frontend"]

# ---- Production runtime (LAST stage = default build target) ----
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
# Workspace-aware standalone output mirrors the repo layout:
# server entry is frontend/server.js, shared deps in node_modules.
COPY --from=build /repo/frontend/.next/standalone ./
COPY --from=build /repo/frontend/.next/static frontend/.next/static
COPY --from=build /repo/frontend/public frontend/public
USER node
EXPOSE 3000
CMD ["node", "frontend/server.js"]
```

- [ ] **Step 4: Verify (requires Docker)**

If Docker is available:

```bash
docker build -f frontend/Dockerfile -t merlins-frontend .
docker run --rm -d -p 3000:3000 --name mf merlins-frontend
sleep 3 && curl -s -o /dev/null -w "%{http_code}" http://localhost:3000   # expect 200
docker rm -f mf
```

If not: defer to CI (Task 6); confirm Step 2's native build passed and `frontend/.next/standalone/frontend/server.js` exists — that's the strongest local signal the runtime stage COPY paths are right.

- [ ] **Step 5: Run frontend tests natively (regression check on the config change)**

Run: `npm test --workspace=frontend` — expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/next.config.ts frontend/Dockerfile
git commit -m "Add frontend Dockerfile with Next.js standalone output"
```

---

### Task 4: `docker-compose.yml` (local dev stack)

`docker compose up` → backend on :8000 with autoreload, frontend on :3000 with Next hot reload, host AWS credentials mounted read-only.

**Files:**
- Create: `docker-compose.yml` (repo root)

**Interfaces:**
- Consumes: `backend/Dockerfile` stage `runtime` (Task 2), `frontend/Dockerfile` stage `dev` (Task 3), `GET /health` (Task 1).
- Produces: services named `backend` and `frontend`. README (Task 6) documents usage.

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
# Local dev stack: `docker compose up`
# - backend  → http://localhost:8000 (uvicorn --reload; source bind-mounted)
# - frontend → http://localhost:3000 (next dev; source bind-mounted)
# AWS access: your host ~/.aws is mounted read-only. Chat mode (Bedrock) and
# real DynamoDB work only if those credentials are valid.
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
      target: runtime
    ports:
      - "8000:8000"
    env_file:
      - path: backend/.env
        required: false
    environment:
      # The mounted source shadows the site-packages install so --reload
      # picks up edits without rebuilding the image.
      PYTHONPATH: /app/backend/src
    volumes:
      - ./backend/src:/app/backend/src:ro
      - ~/.aws:/home/appuser/.aws:ro
    command:
      [
        "uvicorn", "merlins_collection.main:app",
        "--host", "0.0.0.0", "--port", "8000",
        "--reload", "--reload-dir", "/app/backend/src",
      ]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 30s
      timeout: 3s
      start_period: 10s
      retries: 3

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      target: dev
    ports:
      - "3000:3000"
    env_file:
      - path: frontend/.env.local
        required: false
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    volumes:
      - ./frontend:/repo/frontend
      # Mask host node_modules/.next (Windows-built binaries must not leak in).
      - /repo/frontend/node_modules
      - /repo/frontend/.next
    depends_on:
      backend:
        condition: service_healthy
```

- [ ] **Step 2: Verify config syntax (works without Docker Engine only if the CLI is installed)**

If Docker is available: `docker compose config --quiet` (expect exit 0), then `docker compose up --build -d`, check `curl http://localhost:8000/health` and `curl -s -o /dev/null -w "%{http_code}" http://localhost:3000`, then `docker compose down`.
If not: review the YAML against the stage names actually defined in Tasks 2–3 (`runtime`, `dev`) and note verification is deferred.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "Add docker compose dev stack with hot reload and AWS credential mount"
```

---

### Task 5: `docker-compose.test.yml` + root test script

One-shot containers running each suite in the same images CI uses. `docker compose run --rm <service>` propagates the suite's exit code.

**Files:**
- Create: `docker-compose.test.yml` (repo root)
- Modify: `package.json` (repo root — add `docker:test` script)

**Interfaces:**
- Consumes: backend Dockerfile stages `test` and `mcp-test` (Task 2), frontend Dockerfile stage `test` (Task 3).
- Produces: services `backend-tests`, `frontend-tests`, `mcp-tests`; root script `npm run docker:test`. CI and README (Task 6) reference these names.

- [ ] **Step 1: Create `docker-compose.test.yml`**

```yaml
# Containerized test suites — run each as a one-shot container so the exit
# code propagates:
#   docker compose -f docker-compose.test.yml run --rm backend-tests
#   docker compose -f docker-compose.test.yml run --rm frontend-tests
#   docker compose -f docker-compose.test.yml run --rm mcp-tests
# Or all three: npm run docker:test
services:
  backend-tests:
    build:
      context: .
      dockerfile: backend/Dockerfile
      target: test

  frontend-tests:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      target: test

  mcp-tests:
    build:
      context: .
      dockerfile: backend/Dockerfile
      target: mcp-test
```

- [ ] **Step 2: Add the `docker:test` script to root `package.json`**

The `scripts` block becomes:

```json
"scripts": {
  "test": "npm run test --workspaces --if-present && python -m pytest backend/tests -q --tb=short",
  "test:frontend": "npm run test --workspace=frontend",
  "test:mcp": "npm run test --workspace=mcp-server",
  "test:backend": "python -m pytest backend/tests -q --tb=short",
  "docker:test": "docker compose -f docker-compose.test.yml run --rm backend-tests && docker compose -f docker-compose.test.yml run --rm frontend-tests && docker compose -f docker-compose.test.yml run --rm mcp-tests"
}
```

- [ ] **Step 3: Verify (requires Docker)**

If Docker is available: `npm run docker:test` — expect all three suites to pass with the same results as the native runs.
If not: run the native equivalents as a baseline (`npm test` from repo root) so we know the suites the containers will run are green; defer container verification to CI.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.test.yml package.json
git commit -m "Add containerized test suite via docker-compose.test.yml"
```

---

### Task 6: CI docker-build job + README documentation

A broken Dockerfile must fail PRs. GitHub runners have Docker, so this job is also the authoritative build verification while the dev machine lacks Docker.

**Files:**
- Modify: `.github/workflows/ci.yml` (append job)
- Modify: `README.md` (add Docker section)

**Interfaces:**
- Consumes: both Dockerfiles (Tasks 2–3), compose files (Tasks 4–5).
- Produces: CI job `docker-build`; README instructions for `docker compose up` / `npm run docker:test`.

- [ ] **Step 1: Append the `docker-build` job to `.github/workflows/ci.yml`**

Add at the end of the `jobs:` map (same indentation as the existing jobs):

```yaml
  docker-build:
    name: Docker Images Build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Build backend image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: backend/Dockerfile
          target: runtime
          push: false
          cache-from: type=gha,scope=backend
          cache-to: type=gha,scope=backend,mode=max
      - name: Build frontend image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: frontend/Dockerfile
          target: runtime
          push: false
          cache-from: type=gha,scope=frontend
          cache-to: type=gha,scope=frontend,mode=max
```

- [ ] **Step 2: Add a Docker section to `README.md`**

Append (adjusting heading level to match the file's existing structure):

````markdown
## Docker

Everything runs in containers so dev, test, and deploy behave the same on every machine. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

### Local dev

```bash
docker compose up --build
```

- Frontend: http://localhost:3000 (hot reload)
- Backend: http://localhost:8000 (autoreload; health at /health)

Your host `~/.aws` credentials are mounted read-only so the backend can reach DynamoDB and Bedrock. Chat mode needs valid AWS credentials — Bedrock has no local emulator. Env vars come from `backend/.env` and `frontend/.env.local` (both optional, see the `.env.example` files).

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
````

- [ ] **Step 3: Validate the workflow YAML**

Run: `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); print('valid')"`
Expected: `valid`. (If PyYAML isn't installed, `pip install pyyaml` first or eyeball indentation against the existing jobs.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "Add CI docker-build job and Docker documentation"
```

---

## Final Verification

- [ ] `python -m pytest backend/tests -q --tb=short` — all pass
- [ ] `npm test` (repo root) — all workspaces pass
- [ ] `ruff check backend/src` — clean
- [ ] `cd frontend && npm run lint` — clean
- [ ] If Docker available: `docker compose up --build` smoke test + `npm run docker:test`; otherwise push the branch and confirm the CI `docker-build` job goes green — that is the authoritative image verification for this machine.
