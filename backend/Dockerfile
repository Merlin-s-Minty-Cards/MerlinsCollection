# syntax=docker/dockerfile:1
# Build context is the REPO ROOT (the lockfile and both workspaces live there):
#   docker build -f backend/Dockerfile .

# ---- MCP server: compile TypeScript (dev deps included) ----
FROM node:20-slim AS mcp-build
WORKDIR /build
# .npmrc adds fetch-retry resilience for flaky-network builds (repo-root .npmrc).
COPY package.json package-lock.json .npmrc ./
COPY mcp-server/package.json mcp-server/package.json
COPY frontend/package.json frontend/package.json
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
COPY package.json package-lock.json .npmrc ./
COPY mcp-server/package.json mcp-server/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci --workspace=mcp-server --omit=dev

# ---- Backend + MCP bundle on one image ----
FROM python:3.12-slim AS base
# The backend spawns the MCP server as `node dist/index.js` — it needs a Node
# runtime. Node's V8 dynamically links libstdc++6, which python:3.12-slim
# does not ship, so install it before copying the bare Node binary in.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=mcp-build /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src backend/src
# scripts/ is a namespace package run as `python -m scripts.<name>` (ECS
# scheduled syncs) and loaded off disk by tests/scripts/*.py — both stages
# built from base need it, so it is copied here rather than in either one.
COPY backend/scripts backend/scripts
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
# CWD must be the parent of scripts/ so the ECS scheduled-sync overrides in
# docs/aws-setup.md (`python -m scripts.scheduled_sync --job prices`) resolve
# the namespace package. Safe for the CMD below: merlins_collection is pip
# installed into site-packages, so uvicorn does not depend on the CWD.
WORKDIR /app/backend
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# TRUST BOUNDARY — read before changing.
# Behind the ALB the socket peer is the ALB, so without proxy-header handling
# every anonymous caller collapses into ONE per-IP rate-limit bucket (rate_limit
# .rate_limit_public keys on request.client.host). `--proxy-headers` installs
# uvicorn's ProxyHeadersMiddleware, which rewrites scope["client"] to the real
# client IP from X-Forwarded-For — so rate_limit.py keeps reading
# request.client.host and needs no spoof-prone hand-parsing of its own.
#
# Turning that on means the app now TRUSTS X-Forwarded-For, which is safe ONLY
# because the trust set below is SCOPED. Two things bound the spoofing risk:
#   1. FORWARDED_ALLOW_IPS is never "*". XFF is honoured only when the socket
#      peer is inside these ranges; a direct/public caller's forged header is
#      ignored outright.
#   2. uvicorn walks the XFF chain RIGHT-to-LEFT and stops at the first
#      untrusted hop. The ALB *appends* the true peer, so a client that prepends
#      forged entries still keys to its own real IP.
#
# RESIDUAL RISK (accepted): anything able to originate a request from INSIDE
# these ranges can forge the key, because trusted hops are skipped by the walk.
# The task's security group admitting only the ALB is what actually bounds this
# — the app cannot. Default is RFC1918 because the ALB's container-facing IP is
# not statically known; NARROW this to the real VPC/subnet CIDR at deploy time.
# uvicorn reads this env var natively when --forwarded-allow-ips is absent, so
# the ECS task definition can override it WITHOUT rebuilding the image. (It must
# stay an ENV, not a CMD arg: exec-form CMD gets no shell variable expansion.)
ENV FORWARDED_ALLOW_IPS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
CMD ["uvicorn", "merlins_collection.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
