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
   - **Real catalog data**: get a free API key at https://dev.pokemontcg.io,
     set `POKEMONTCG_API_KEY` in `backend/.env`, then run:

     ```python
     from datetime import date
     from merlins_collection.services.catalog_sync import run_daily_sync
     from merlins_collection.services.dynamodb import InventoryRepository
     from merlins_collection.services.pokemontcg import PokemonTcgClient

     repo = InventoryRepository("merlins-cards", region_name="us-east-1")
     client = PokemonTcgClient(api_key="<your POKEMONTCG_API_KEY>")
     run_daily_sync(repo, client, date.today())
     ```

     This fills catalog cards + price points, then runs
     `refresh_inventory_market_values`.
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

## Phase 4 — Cognito (customer auth) (30 min)

The backend verifies Cognito **access tokens** (`services/cognito.py`); the
frontend has NextAuth v5 ready for a Cognito provider (wiring it up is the
remaining frontend task — see "What's not done yet" below).

1. Cognito → User pools → Create:
   - Sign-in options: **Email**
   - Password policy / MFA: your call (email-code MFA is fine to start)
   - App client: type **Public client**, name `merlins-frontend`,
     **generate a client secret** (NextAuth uses it),
     Allowed callback URL `http://localhost:3000/api/auth/callback/cognito`
     (add the production URL later), enable **Authorization code grant** with
     scopes `openid`, `email`, `profile`.
   - Add a **domain** (App integration → Domain → Cognito domain) so the
     hosted login UI works.
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
   `frontend/next.config.ts` (pokemontcg.io images already work without this).

## Phase 6 — Hosting (when ready to go live)

Simplest architecture that fits this codebase:

| Piece | Service | Notes |
|-------|---------|-------|
| Frontend | **AWS Amplify Hosting** (or Vercel) | Connect the GitHub repo, root dir `frontend/`. Set all `frontend/.env` vars in the console. |
| Backend + MCP server | **App Runner** or a small **EC2/Lightsail** instance | The two must live together: the backend spawns `node mcp-server/dist/index.js` as a subprocess, so the image/instance needs Python 3.12+, Node 20+, and a built `mcp-server/dist`. Attach an IAM **role** (DynamoDB + Bedrock access) instead of access keys. |

Production settings to remember:
- `CORS_ORIGINS=https://your-domain.com` on the backend (comma-separated for
  multiple origins; localhost is only the dev default).
- `MCP_SERVER_PATH` should be an **absolute** path in production.
- **Never set `AUTH_DISABLED` in production** — it bypasses login entirely
  (the backend logs a loud warning at startup whenever it's on).
- Add the production callback URL to the Cognito app client.
- API Gateway in front of the backend is optional at this stage; App Runner /
  a load balancer with HTTPS is enough to start.

## Phase 7 — Tighten IAM (after everything works)

Replace `merlins-dev`'s full-access policies with least privilege:
- DynamoDB: `dynamodb:GetItem, Query, BatchGetItem, BatchWriteItem, PutItem, DeleteItem` on `table/merlins-cards` and `table/merlins-cards/index/GSI1`
- Bedrock: `bedrock:InvokeModel` on the Claude model ARN
- S3: `s3:GetObject, PutObject` on the images bucket

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
`AUTH_DISABLED`, `POKEMONTCG_API_KEY`. AWS credentials are **not** read from
this file — see Phase 1 (`aws configure` / an IAM role in production).

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (backend base URL),
`AUTH_URL`/`AUTH_SECRET` (NextAuth), `AWS_COGNITO_*` (provider),
`NEXT_PUBLIC_CLOUDFRONT_URL`, `NEXT_PUBLIC_SANITY_*` (CMS, independent of AWS).
