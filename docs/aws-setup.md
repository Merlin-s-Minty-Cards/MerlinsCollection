# AWS Setup Guide — Merlin's Minty Cards

A step-by-step path from "fresh AWS account" to a fully working site. Written
against this codebase's actual configuration (see `backend/.env.example` and
`frontend/.env.example` for every variable named here).

The order below matters: each phase unblocks the next, and you can verify the
stack locally after Phase 3 — before touching Cognito or hosting.

> **Region:** everything assumes `us-east-1` (the code's default). If you pick
> another region, set `AWS_REGION` everywhere and note that **Bedrock model
> availability varies by region** — `us-east-1` is the safest choice.

---

## Phase 0 — Account hygiene (15 min, do this first)

1. **Secure the root user**: enable MFA on the root account (IAM → root user →
   enable MFA). Never use root for daily work.
2. **Create an admin IAM user for yourself** (or better, enable IAM Identity
   Center): IAM → Users → Create user → attach `AdministratorAccess` → enable
   console access + MFA.
3. **Set a billing alarm**: Billing → Budgets → create a monthly budget
   (e.g. $25) with email alerts. Bedrock + DynamoDB on this scale should cost
   only a few dollars/month, but alerts catch mistakes early.

## Phase 1 — Credentials for local development (10 min)

1. IAM → Users → Create user `merlins-dev` (no console access).
2. Attach these managed policies for now (tighten later, Phase 7):
   - `AmazonDynamoDBFullAccess`
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess`
3. Create an **access key** (Use case: "Local code"), then run:

   ```powershell
   aws configure
   # AWS Access Key ID: AKIA...
   # AWS Secret Access Key: ...
   # Default region name: us-east-1
   ```

   This writes `~/.aws/credentials`, which is what boto3 actually reads.
   **Do not put `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in `backend/.env`**
   — nothing in this codebase reads those two settings fields; every
   `boto3.client`/`boto3.resource` call here is built with no explicit
   credentials, so it relies entirely on boto3's own default chain
   (env vars in the real OS environment → `~/.aws/credentials` → IAM role).
   `backend/.env` is loaded by pydantic-settings, which never exports its
   values to `os.environ`, so boto3 (and the MCP server subprocess, which
   inherits `os.environ` plus an explicit `AWS_REGION`/`DYNAMODB_TABLE_NAME`
   override — see `dependencies.py:get_mcp_executor`) would never see them.
4. Copy `backend/.env.example` → `backend/.env` and set `AWS_REGION=us-east-1`
   there (this one *is* read, by `config.py`, for the region passed to boto3
   client/resource constructors).

## Phase 2 — DynamoDB table (5 min)

One single-table design holds catalog, inventory, and price history
(`backend/src/merlins_collection/services/dynamodb.py` documents the layout).

Easiest: let the repo's own code create it —

```powershell
cd backend
python -c "from merlins_collection.services.dynamodb import InventoryRepository; InventoryRepository('merlins-cards', region_name='us-east-1').create_table()"
```

Or in the console: DynamoDB → Create table →
- Table name `merlins-cards`, Partition key `PK` (String), Sort key `SK` (String)
- Capacity mode: **On-demand** (pay per request)
- After creation, add a **Global Secondary Index** named `GSI1`:
  partition key `GSI1PK` (String), sort key `GSI1SK` (String), projection **All**.

### Phase 2b — the rate-limit table (`merlins-rate-limits`)

The app-side rate limiter (`backend/src/merlins_collection/rate_limit.py`) keeps
its counters in a **separate** DynamoDB table — deliberately NOT `merlins-cards`,
so ephemeral counters are never swept as business data by the importer. Provision
it once (name it `merlins-rate-limits`, or match `RATE_LIMIT_TABLE_NAME`):

```powershell
cd backend
python -c "from merlins_collection.rate_limit import DynamoRateLimiter; DynamoRateLimiter('merlins-rate-limits', region_name='us-east-1').create_table()"
```

Then **enable TTL** so expired per-minute/per-day counter items auto-delete
(there is no IaC; this is a one-time manual step):

```powershell
aws dynamodb update-time-to-live --table-name merlins-rate-limits `
  --time-to-live-specification "Enabled=true,AttributeName=expires_at"
```

Console equivalent: table `merlins-rate-limits`, partition key `PK` (String), no
sort key, On-demand; then Additional settings → Time to Live → attribute
`expires_at`. TTL is a cleanup optimization only — correctness does not depend on
it (each new window uses a new item), it just stops the table growing forever.

> **Launch-critical:** `/chat` **fails closed** — if the backend's role cannot
> write to this table, EVERY chat request returns 503 the moment the link goes
> public. Grant the scoped IAM permission below (Phase 7) BEFORE the table goes
> live, and do **not** paper over a missing grant with a broad `dynamodb:*`.

## Phase 3 — Bedrock model access + first end-to-end run (20 min)

1. Bedrock console (us-east-1) → **Model access** → request access to
   **Anthropic Claude Sonnet 4.5**. Approval for Anthropic models is
   usually instant. The backend's default model id is
   `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (`BEDROCK_MODEL_ID` to
   change). Note the `us.` prefix — current-generation models require
   invoking them through a **cross-region inference profile** id rather
   than the bare model id; the bare id fails with "on-demand throughput
   isn't supported." Run `aws bedrock list-foundation-models --region
   us-east-1 --by-provider anthropic` to see what your account can currently
   access — Anthropic periodically retires old model versions (they start
   failing with `ResourceNotFoundException: ... reached the end of its
   life`), so if chat mode 502s, this is the first thing to check.
2. Seed some data. Two options:
   - **Real catalog data**: TCGdex needs no API key. From `backend/`:

     ```bash
     python scripts/seed_catalog.py                     # DRY RUN, both languages
     python scripts/seed_catalog.py --language en       # DRY RUN, English only
     # actually write (the table name must be repeated back):
     python scripts/seed_catalog.py --execute --confirm-table merlins-cards
     ```

     That is the identity-only pass (one request per language). TCGdex serves
     prices only from its per-card detail endpoint, so prices are fetched
     separately for the cards actually held.

     **The seed is a dry run unless you pass both `--execute` and a
     `--confirm-table` that matches the configured target.** The target defaults
     to the live table that serves `/inventory`, and the seed writes ~23,444 rows
     into it. It will not overwrite a row a depth pass has already priced
     (`detail="full"`), and it exits non-zero rather than reporting success if
     the catalog comes back implausibly short or most rows fail to map.
   - **Daily job** (price snapshots + market-value denormalization):

     ```bash
     python scripts/daily_sync.py
     ```

     Runs the graded-slab snapshot, the sealed snapshot, and
     `refresh_inventory_market_values`. Read-only against TCGdex — it works off
     data already in DynamoDB. This is what a scheduler should invoke.
   - **Manual**: `put_inventory_item` / `batch_upsert_catalog_cards` from a
     Python shell for a handful of cards (see `backend/tests/routers/test_inventory.py`
     for exact model construction).
3. **Run the whole stack locally** (Cognito doesn't exist yet, so use the dev
   bypass):

   ```powershell
   # 1. Build the MCP server (the backend spawns node mcp-server/dist/index.js)
   npm run build --workspace=mcp-server

   # 2. Backend — AUTH_DISABLED only until Cognito exists (Phase 4)
   cd backend
   $env:AUTH_DISABLED='true'
   python -m uvicorn merlins_collection.main:app --port 8000

   # 3. Frontend (second terminal)
   cd frontend
   npm run dev
   ```

   Visit http://localhost:3000/inventory — filter search should return your
   seeded cards, and chat mode should answer questions using the MCP tools.

### Phase 3b — Bedrock cost guardrail (must-do before sharing the link)

Bedrock bills per token, on-demand, no matter how tight the app-side rate
limits (Phase 2b / Phase 7) are — a bug or a burst of legitimate traffic can
still run up a real bill within a day. Two things to set up before the
`/inventory` link goes out publicly:

1. **Keep Bedrock on-demand.** Do not switch to Provisioned Throughput — that
   trades a bill that scales with actual usage for a fixed hourly commitment,
   the wrong tradeoff for a small business with bursty, unpredictable traffic.
2. **An AWS Budgets *Action*, not just an alert.** This is the only
   AWS-native **hard stop** on spend: a plain budget *alert* only sends an
   email — nothing stops the next Bedrock call, and by the time the email is
   read the bill has already grown. An Action actually revokes the
   permission to call Bedrock until it's manually restored. The Budgets
   console does **not** let you author policy JSON inline, so this needs two
   pieces created ahead of time:
   - **The deny policy itself.** IAM → Policies → Create policy → JSON:
     ```json
     {"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"bedrock:InvokeModel","Resource":"*"}]}
     ```
     Name it something like `DenyBedrockInvoke`. This is the policy the
     Action attaches to the backend's role when the budget threshold is hit.
   - **A one-time Budgets service role.** AWS Budgets can't execute *any*
     Action until it has permission to make IAM changes on your behalf:
     IAM → Create role → attach the managed policy
     `AWSBudgetsActions_RolePolicyForResourceAdministrationWithSSM`. This is
     a separate role from the target role above — it's the role you select
     as "the IAM role" *for Budgets itself* when adding the Action, not the
     role the deny policy gets attached to.
   - **Then create the budget and Action.** Billing → Budgets → create a
     **daily** budget (e.g. **$20/day**) → add an **Action** of type **IAM
     policy**, referencing the `DenyBedrockInvoke` policy's ARN, targeting
     the role the backend runs as, using the Budgets service role above,
     triggered at 100% of the budget.

**Bedrock "Guardrails" is a different feature** (content filtering / PII
redaction on model input and output) — it does **not** limit spend. Don't
mistake configuring a Guardrail for having a cost control in place.

## Phase 4 — Cognito (customer auth) (30 min)

The backend verifies Cognito **access tokens** (`services/cognito.py`); the
frontend has NextAuth v5 ready for a Cognito provider (wiring it up is the
remaining frontend task — see "What's not done yet" below).

1. Cognito → User pools → Create:
   - Sign-in options: **Email**
   - Password policy / MFA: your call (email-code MFA is fine to start)
   - App client: **Application type = "Traditional web application"**, name
     `merlins-frontend`. **Do not pick "Public client"** — only the
     "Traditional web application" and "Machine-to-machine application"
     profiles generate a client secret; "Public client" (the SPA-style
     profile) never does, and this codebase's NextAuth config genuinely reads
     `AWS_COGNITO_CLIENT_SECRET` (`frontend/lib/auth.config.ts`, both for the
     initial sign-in and for refreshing the access token), so picking Public
     client here would leave you stuck later with no secret to put in
     `frontend/.env.local`. Set the callback URL to
     `http://localhost:3000/api/auth/callback/cognito` (add the production
     URL later).
   - After the user pool is created, the OAuth details aren't part of that
     same wizard anymore: go to **App clients** → select `merlins-frontend` →
     **Hosted UI / Login pages** settings, and confirm **Authorization code
     grant** is checked under OAuth grant types, with scopes `openid`,
     `email`, `profile` under OpenID Connect scopes.
   - Add a **domain** (Branding → Domain → Create Cognito domain) so the
     hosted login UI works. The console now offers two branding options here:
     **managed login** (newer, currently the recommended default) and
     **classic hosted UI** (older, still works). Either gets you a working
     login page; managed login is the one AWS points you toward today.
2. Create an admin group (optional, gates future admin routes): User pool →
   Groups → create `admin`, add yourself.
3. Fill in the env files:

   ```env
   # backend/.env
   COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
   COGNITO_CLIENT_ID=<app client id>
   AUTH_DISABLED=false          # bypass off from here on

   # frontend/.env.local
   AUTH_SECRET=<openssl rand -base64 32>
   AWS_COGNITO_CLIENT_ID=<app client id>
   AWS_COGNITO_CLIENT_SECRET=<app client secret>
   AWS_COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX
   ```

## Phase 5 — S3 + CloudFront (card images) (30 min)

1. S3 → Create bucket `merlins-card-images-<something-unique>` — keep
   **Block all public access ON** (CloudFront will read it, not the public).
2. CloudFront → Create distribution → origin = the bucket, with
   **Origin Access Control** (CloudFront creates the bucket policy for you).
3. Put `NEXT_PUBLIC_CLOUDFRONT_URL=https://dxxxxxxxx.cloudfront.net` in
   `frontend/.env.local`, and add that hostname to `images.remotePatterns` in
   `frontend/next.config.ts` (TCGdex images already work without this).

## Phase 6 — Hosting (when ready to go live)

**AWS App Runner is closed to new customers as of 2026-04-30** — it is no
longer an option for either side of this app. Its named replacement is
**Amazon ECS Express Mode** (GA November 2025): point it at a container
image and one call provisions Fargate + an Application Load Balancer +
health checks + autoscaling, the same "just deploy the container" experience
App Runner used to offer. This codebase already builds a production Docker
image for each side (`frontend/Dockerfile`, `backend/Dockerfile`, both
already smoke-tested by CI's `docker-build` job), so Express Mode is used
for **both**:

| Piece | Service | Notes |
|-------|---------|-------|
| Frontend | **ECS Express Mode**, from `frontend/Dockerfile` | Health check path `/` — the Next.js app has no dedicated `/health` route. |
| Backend + MCP server | **ECS Express Mode**, from `backend/Dockerfile` | Health check path `/health`. Size the task **~1 vCPU / 2 GB** — it runs the Python/FastAPI process AND spawns a Node MCP **subprocess** at the same time, so it needs more headroom than a bare API container. |

Why not the old framing:
- **Amplify Hosting (or Vercel) for the frontend — dropped.** Amplify's
  Next.js hosting is a **git-based build service**: it clones the repo and
  runs its own build, rather than deploying the Docker image this repo
  already builds and smoke-tests in CI. It also has silent build-minute and
  response-size caps that don't surface until you hit them. Deploying the
  same tested image via ECS Express Mode is more predictable.
- **App Runner for the backend — closed to new customers**, so Express Mode
  is the direct successor.

Two ways to drive Express Mode — the console wizard (recommended for a
first-time, tight-deadline deploy) and the CLI (better once you're
scripting/automating deploys). Either way, push the image to ECR first —
Express Mode deploys from an ECR image, not straight from a Dockerfile.

### Console path (recommended)

`console.aws.amazon.com/ecs/v2` → left nav **"Express mode"** → fill in the
**Image URI** (the ECR image you pushed) and the rest of the wizard. For the
**Task execution role** and **Infrastructure role** dropdowns, choose
**"Create new role"** — the console auto-creates both required IAM roles for
you (the equivalents of `ecsTaskExecutionRole` and
`ecsInfrastructureRoleForExpressServices` below), so there's nothing to
pre-create by hand on this path.

Repeat the wizard once per image — frontend and backend are two independent
Express services (two ECR images, two wizard runs), not one combined task.

### CLI path (for scripting/automation)

Unlike the console wizard, the CLI does **not** create the required IAM
roles for you — confirm these two roles already exist in the account before
the first Express call (Express Mode assumes them on this path):
- `ecsTaskExecutionRole` — lets ECS pull the image from ECR and write logs.
- `ecsInfrastructureRoleForExpressServices` — lets Express Mode provision the
  ALB, target group, and autoscaling on your behalf.

Steps, run once per image:
1. Push the built image to **ECR** (`aws ecr create-repository`, then
   `docker push`) — Express Mode deploys from an ECR image, not straight
   from a Dockerfile.
2. Run `aws ecs create-express-gateway-service` against that image. This one
   command provisions the Fargate service, the ALB, the health check, and
   autoscaling — no separate ALB / target group / service setup needed.
3. Repeat for the other image. Frontend and backend are two independent
   Express services (two ECR images, two `create-express-gateway-service`
   calls), not one combined task.

Production settings to remember:
- `CORS_ORIGINS=https://your-domain.com` on the backend (comma-separated for
  multiple origins; localhost is only the dev default).
- `MCP_SERVER_PATH` should be an **absolute** path in production (the
  backend image already sets `MCP_SERVER_PATH=/app/mcp-server/dist/index.js`
  via `ENV` in `backend/Dockerfile` — nothing to change here unless that
  image's layout changes).
- **Never set `AUTH_DISABLED` in production** — it bypasses login entirely
  (the backend logs a loud warning at startup whenever it's on).
- Add the production callback URL to the Cognito app client.
- Attach the backend's task IAM **role** (DynamoDB + Bedrock access, see
  Phase 7) so credentials never need to live in the container — this is
  separate from `ecsTaskExecutionRole` above, whose only job is pulling the
  image and writing logs.
- API Gateway in front of the backend is still optional at this stage; the
  ALB Express Mode provisions (with HTTPS) is enough to start.

### Edge rate limiting — AWS WAF (recommended fast-follow, deferred for launch)

The app already enforces its own limits (Phase 2b / Phase 7) — a
DynamoDB-backed cap per authenticated Cognito user plus a global daily
Bedrock ceiling. The recommended complement is an **AWS WAF rate-based rule
on the backend's ALB** (the one Express Mode provisions above): it caps
requests **per source IP at the network edge**, before they ever reach the
app. That catches what the app-side limiter can't — a pre-auth flood, or one
IP hammering multiple backend instances — and it keeps working across app
restarts, since the count lives in WAF, not in the app's own counters.

**Deferred for this launch** (owner decision): WAF costs roughly **$5/month
per Web ACL + $1/month per rule + ~$0.60 per million requests inspected** —
real but small money, not worth blocking the first show over. Treat it as
the first post-launch hardening step: create a Web ACL scoped to the
backend's ALB, add a rate-based rule (e.g. N requests per 5-minute window
per IP), and associate the Web ACL with the ALB. The app-side limiter above
is what actually caps Bedrock spend per user and globally; WAF adds
pre-auth / multi-IP flood protection on top of it, not a replacement for it.

## Phase 7 — Tighten IAM (after everything works)

Replace `merlins-dev`'s full-access policies with least privilege:
- DynamoDB (business table): `dynamodb:GetItem, Query, BatchGetItem, BatchWriteItem, PutItem, DeleteItem` on `table/merlins-cards` and `table/merlins-cards/index/GSI1`
- DynamoDB (rate-limit table): `dynamodb:UpdateItem` on `table/merlins-rate-limits` — **required**; without it `/chat` fails closed and 503s for all users. Add `dynamodb:CreateTable` + `dynamodb:UpdateTimeToLive` on the same ARN only while running the one-time Phase 2b provisioning step (drop them after).
- Bedrock: `bedrock:InvokeModel` on the Claude model ARN
- S3: `s3:GetObject, PutObject` on the images bucket

Scoped statement for the rate-limit table (swap in your account id / region /
table name; the runtime action is just `UpdateItem` — the limiter never reads,
scans, or deletes, and TTL handles cleanup):

```json
{
  "Sid": "RateLimitCounters",
  "Effect": "Allow",
  "Action": "dynamodb:UpdateItem",
  "Resource": "arn:aws:dynamodb:us-east-1:<ACCOUNT_ID>:table/merlins-rate-limits"
}
```

The rate-limit table is **separate** from `merlins-cards`, so an existing narrow
policy scoped to the business table does NOT cover it — the grant above is an
additional statement, not an edit to the business-table one. **Never** substitute
`dynamodb:*` on `*` as a deadline shortcut.

Also rotate the Phase 1 access key once production runs on IAM roles.

## Deferred (not needed to launch)

- **Lambda + API Gateway** (price lookup / image processing) — the daily sync
  currently runs manually via `run_daily_sync`; a scheduled Lambda (EventBridge
  cron) is its natural home later.
- **Rekognition** — future card-from-photo identification.
- **Frontend Cognito login UI** — NextAuth provider wiring + a sign-in page +
  passing the session's access token into `searchInventory`/`sendChat` (the
  token plumbing already exists in `frontend/lib/api.ts`; nothing sends a
  token yet, which is why `AUTH_DISABLED` is required for local testing).

## What each env var maps to

Backend (`backend/.env`): `AWS_REGION`, `DYNAMODB_TABLE_NAME`, `BEDROCK_MODEL_ID`,
`COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `MCP_SERVER_PATH`, `CORS_ORIGINS`,
`AUTH_DISABLED`, `EUR_USD_RATE`. AWS credentials are **not** read from
this file — see Phase 1 (`aws configure` / an IAM role in production).

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (backend base URL),
`AUTH_URL`/`AUTH_SECRET` (NextAuth), `AWS_COGNITO_*` (provider),
`NEXT_PUBLIC_CLOUDFRONT_URL`, `NEXT_PUBLIC_SANITY_*` (CMS, independent of AWS).
