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
COPY --from=build --chown=node:node /repo/frontend/.next/standalone ./
COPY --from=build --chown=node:node /repo/frontend/.next/static frontend/.next/static
COPY --from=build --chown=node:node /repo/frontend/public frontend/public
USER node
EXPOSE 3000
CMD ["node", "frontend/server.js"]
