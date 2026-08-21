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

Everything runs in containers so dev, test, and deploy behave the same on every machine. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Docker Compose v2.24+ (the `env_file` optional-file syntax depends on it), which modern Docker Desktop already includes.

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

## Deploying to AWS

Two independent deployment paths exist side by side. **Containers (ECS
Fargate)** is what production actually runs today. **Serverless (Lambda +
CloudFront)** is RFC 0014's in-progress migration off it — deployed and
reachable, but still a parallel validation spike that nothing in production
points at yet (see
[`docs/rfcs/0014-ecs-to-serverless-migration.md`](docs/rfcs/0014-ecs-to-serverless-migration.md)).
Deploying to one never touches the other — they're separate AWS resources
(different Lambda functions, different CloudFront distribution) sharing only
the same DynamoDB tables and Cognito user pool.

### Containers (ECS Fargate) — current production path

Both services run as Docker containers on ECS Fargate in the `merlins`
cluster. Deploy backend first since the frontend calls it.

#### Full Deploy (both services)

Run from the **repo root** (both Dockerfiles use repo root as build context):

```bash
# Authenticate Docker with ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 560151615792.dkr.ecr.us-east-1.amazonaws.com

# Build & push backend
docker build -f backend/Dockerfile -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest .
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-backend:latest

# Build & push frontend
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://me-227b5d9d4f6444e9aea830a909f923c8.ecs.us-east-1.on.aws -t 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest .
docker push 560151615792.dkr.ecr.us-east-1.amazonaws.com/merlins-frontend:latest

# Force ECS to pull the new images
aws ecs update-service --cluster merlins --service merlins-backend --force-new-deployment --region us-east-1
aws ecs update-service --cluster merlins --service merlins-frontend --force-new-deployment --region us-east-1
```

See `frontend/README.md` and `backend/README.md` for single-service deploy commands and environment variable details.

#### Checking Deployment Status

```bash
# Rollout status (COMPLETED / IN_PROGRESS / FAILED)
aws ecs describe-services --cluster merlins --services merlins-backend --region us-east-1 \
  --query 'services[0].deployments'

aws ecs describe-services --cluster merlins --services merlins-frontend --region us-east-1 \
  --query 'services[0].deployments'

# Block until a deployment stabilizes (or times out)
aws ecs wait services-stable --cluster merlins --services merlins-backend --region us-east-1
aws ecs wait services-stable --cluster merlins --services merlins-frontend --region us-east-1

# Confirm the running task is on the image you just pushed
aws ecs describe-tasks --cluster merlins --region us-east-1 \
  --tasks $(aws ecs list-tasks --cluster merlins --service-name merlins-backend --region us-east-1 --query 'taskArns[0]' --output text) \
  --query 'tasks[0].containers[0].image'
```

Or check the ECS console: Clusters → `merlins` → Services → `merlins-backend` / `merlins-frontend` → **Deployments** tab for rollout status, **Tasks** tab for task health.

### Serverless (Lambda + CloudFront) — RFC 0014 spike

The whole app is defined as one CDK app in `infra/` (added to the npm
workspaces, so `npm install` at the repo root also installs it): a backend
Lambda (FastAPI packaged with the Lambda Web Adapter, behind a Function URL)
and a frontend Lambda + CloudFront distribution (Next.js built with OpenNext,
deployed via `cdk-nextjs-standalone`). Two independent stacks,
`MerlinsBackendStack` and `MerlinsFrontendStack` — deploy either on its own.

#### Prerequisites

- AWS CLI configured with credentials for account `560151615792`
- Docker Desktop installed **and running** (the backend Lambda's container
  image is built as a Docker asset during `cdk deploy`)
- One-time per account/region: `cd infra && npx cdk bootstrap`

#### Required environment variables before ANY deploy

`cdk deploy` replaces a Lambda's **entire** environment-variable set with
whatever the current synth produces — it does not merge. `infra/bin/infra.ts`
reads secrets from the deploying shell's own environment, so an unset var
here doesn't just skip a feature, it **silently deletes that variable from
the live Lambda** if one was already set from a previous deploy. Export these
first:

```bash
export AUTH_SECRET=...                    # frontend: NextAuth encryption key
export AWS_COGNITO_CLIENT_SECRET=...       # frontend: Cognito app client secret
export NEXT_PUBLIC_SANITY_PROJECT_ID=...   # frontend: optional, needed for /studio to mount
export NEXT_PUBLIC_SANITY_DATASET=...      # frontend: optional, defaults to 'production'
export POKEMONPRICETRACKER_API_KEY=...     # backend: optional, graded pricing (RFC 0009)
export ADMIN_API_KEY=...                   # backend: optional, Retool admin access
```

#### Deploy Backend

```bash
cd infra
npx cdk deploy MerlinsBackendStack
```

#### Deploy Frontend

Plain `cdk deploy` triggers the OpenNext build itself, but on this project's
Windows dev machines that build hangs indefinitely when invoked through
`cdk`'s nested `ts-node → execSync → npm → next build` process chain (a
confirmed, Windows-specific quirk — see `infra/lib/frontend-stack.ts`'s
`skipOpenNextBuild` doc comment). The reliable path is to build directly
first, then have `cdk deploy` reuse that output:

```bash
npm run build:opennext --workspace=frontend
cd infra
SKIP_OPENNEXT_BUILD=true npx cdk deploy MerlinsFrontendStack
```

(On a machine without that quirk, `cd infra && npx cdk deploy
MerlinsFrontendStack` alone is enough — `SKIP_OPENNEXT_BUILD` just skips a
build step that would otherwise happen automatically.)

#### After the first frontend deploy — manual, not part of `cdk deploy`

`cdk-nextjs-standalone` assigns the CloudFront domain at deploy time, so it
can't be pre-registered. Two things live outside CDK entirely and won't
update themselves:

1. **Cognito app client callback URL** — add
   `https://<distribution>.cloudfront.net/api/auth/callback/cognito` to the
   app client's allowed callback URLs (`aws cognito-idp
   update-user-pool-client --callback-urls ...` — this call replaces the
   whole list, so include the existing URLs too, not just the new one).
2. **Backend CORS** — add `https://<distribution>.cloudfront.net` to
   `corsOrigins` in `infra/bin/infra.ts`, then redeploy
   `MerlinsBackendStack`. Until this is done, every browser fetch from the
   CloudFront frontend to the backend Lambda is silently blocked by CORS —
   the requests succeed server-side but the browser refuses to hand back the
   response, which looks exactly like "the API is returning nothing."

#### Checking Deployment Status

```bash
# Dry-run: does the next deploy match what's actually live?
cd infra && npx cdk diff MerlinsBackendStack
cd infra && npx cdk diff MerlinsFrontendStack

# Tail a Lambda's logs directly (MSYS_NO_PATHCONV=1 needed on Git Bash —
# otherwise it silently mangles the leading /aws/lambda/... into a Windows path)
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/<function-name> --since 20m --format short

# Current stack outputs (Function URL, CloudFront domain)
aws cloudformation describe-stacks --stack-name MerlinsBackendStack --query "Stacks[0].Outputs"
aws cloudformation describe-stacks --stack-name MerlinsFrontendStack --query "Stacks[0].Outputs"
```

Status right now: both stacks are deployed and reachable, but nothing in
production points at them — this is a parallel validation spike (RFC 0014
Task 6), not a cutover. See the RFC for what's still open before that
changes.

## Contributing

All PRs require review. See CLAUDE.md for TDD guidelines and branch protection requirements.
