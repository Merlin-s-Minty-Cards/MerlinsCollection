# syntax=docker/dockerfile:1
# Build context is the REPO ROOT (the lockfile and both workspaces live there):
#   docker build -f backend/Dockerfile .

# ---- MCP server: compile TypeScript (dev deps included) ----
FROM node:20-slim AS mcp-build
WORKDIR /build
COPY package.json package-lock.json ./
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
COPY package.json package-lock.json ./
COPY mcp-server/package.json mcp-server/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci --workspace=mcp-server --omit=dev

# ---- Backend + MCP bundle on one image ----
FROM python:3.12-slim AS base
# The backend spawns the MCP server as `node dist/index.js` — it needs a Node
# runtime. Node's V8 dynamically links libstdc++6, which python:3.12-slim
# does not ship, so install it before copying the bare Node binary in.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
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
