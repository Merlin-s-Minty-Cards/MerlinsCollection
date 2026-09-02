#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib'
import { BackendStack } from '../lib/backend-stack'
import { FrontendStack } from '../lib/frontend-stack'
import { backendOriginFromFunctionUrl } from '../lib/backend-origin'
import { CognitoBrandingStack } from '../lib/cognito-branding-stack'
import { SyncStack } from '../lib/sync-stack'

/**
 * RFC 0014 — parallel-deploy phase. Backend (Task 4) is deployed and
 * verified; frontend (Task 6) is now a live spike validating
 * cdk-nextjs-standalone's real NextAuth v5 compatibility (see RFC 0014's
 * Open Questions — this was a real, unconfirmed gap in the tooling
 * research, not assumed away).
 *
 * Non-secret values below mirror deploy/backend-container.json's committed
 * environment block (same convention: real values, no secrets). Secrets
 * (POKEMONPRICETRACKER_API_KEY, ADMIN_API_KEY, AUTH_SECRET,
 * AWS_COGNITO_CLIENT_SECRET) are read from the deployer's OWN environment at
 * synth/deploy time — never literals in this file or in lib/*-stack.ts.
 * Unset is a supported state (matches Settings.pokemonpricetracker_api_key's
 * empty-string default): the nightly sync job already handles a missing key
 * by skipping graded pricing, and this stack omits the env var entirely
 * rather than writing "".
 */
const app = new cdk.App()

const account = process.env.CDK_DEFAULT_ACCOUNT ?? '560151615792'
const region = process.env.CDK_DEFAULT_REGION ?? 'us-east-1'

const backend = new BackendStack(app, 'MerlinsBackendStack', {
  env: { account, region },
  awsRegion: region,
  dynamoTableName: 'merlins-cards',
  rateLimitTableName: 'merlins-rate-limits',
  cognitoUserPoolId: 'us-east-1_Ab945I9ir',
  cognitoClientId: '3vmg0a9lffhc85a2lrskh27b3f',
  // Starting value matched today's ECS CORS_ORIGINS exactly during the
  // parallel-deploy phase, before anything pointed at this stack's Function
  // URL. RFC 0014 §5 step 2 said to add the CloudFront frontend domain here
  // before pointing the new frontend at this backend — that step was
  // documented but never actually done, which is why every admin table on
  // the CloudFront spike came back empty (2026-08-17): the browser silently
  // dropped every fetch response because the Origin wasn't allow-listed.
  //
  // The raw *.cloudfront.net entry above fixed that once, but the
  // distribution ALSO carries two custom-domain aliases —
  // `merlinsmintycards.com` and `www.merlinsmintycards.com` (confirmed via
  // `aws cloudfront list-distributions`) — and DNS for both already resolves
  // to this same distribution. Neither was ever added here, so the exact
  // same "every admin table empty" symptom recurred 2026-08-18 for anyone
  // using the real production domain instead of the raw CloudFront URL:
  // diagnosed from a live browser request whose `Referer` was
  // `https://www.merlinsmintycards.com/` hitting a 400 "Disallowed CORS
  // origin" on every preflight, while an identical request with the
  // `.cloudfront.net` Origin succeeded. CORS rejects on the Origin's exact
  // string — a distribution alias does not implicitly extend the allow-list,
  // so every hostname that can reach this backend must be listed here
  // explicitly, apex and `www` both (browsers treat them as different
  // origins).
  corsOrigins:
    'https://me-736e73de34b349da8d2027e56db0eb8a.ecs.us-east-1.on.aws,http://localhost:3000,https://d3pmro4bgrznx9.cloudfront.net,https://merlinsmintycards.com,https://www.merlinsmintycards.com',
  pokemonPriceTrackerApiKey: process.env.POKEMONPRICETRACKER_API_KEY,
  adminApiKey: process.env.ADMIN_API_KEY,
})

new FrontendStack(app, 'MerlinsFrontendStack', {
  env: { account, region },
  // Points at the already-deployed backend Lambda's real Function URL.
  // AWS always renders a Function URL with a TRAILING SLASH, and both
  // frontend/lib/api.ts and frontend/lib/admin-api.ts concatenate
  // `${BASE_URL}${path}` where every caller's `path` carries its own leading
  // slash — so an untrimmed value here requests `//inventory/search`, a
  // genuinely different route that FastAPI 404s before it even authenticates.
  //
  // THIS LINE USED TO READ `backend.functionUrl.url.replace(/\/$/, '')`, and
  // that silently did nothing for months — it took the whole production site
  // down (every customer page AND every admin tab) until 2026-08-26. At synth
  // time `functionUrl.url` is not a URL at all, it is an unresolved CDK token
  // (`${Token[TOKEN.n]}`) that does not end in a slash, so the regex matched
  // nothing and CDK emitted a bare `Fn::ImportValue` passthrough. The slash
  // only appears when CloudFormation resolves the import at DEPLOY time,
  // which is long after any JavaScript string method could have run.
  //
  // The rule this encodes: a CDK token can only be transformed by CDK's own
  // `Fn.*` intrinsics, which defer the work into the template itself. Plain
  // JS string operations on a token are no-ops that LOOK correct in review.
  //
  // `Fn.split('/', 'https://host/')` yields `['https:', '', 'host', '']`, so
  // index 2 is the bare host — dropping the trailing empty segment along with
  // it — and rejoining under an explicit scheme rebuilds a slash-free origin.
  backendApiUrl: backendOriginFromFunctionUrl(backend.functionUrl.url),
  cognitoClientId: '3vmg0a9lffhc85a2lrskh27b3f',
  cognitoIssuer: `https://cognito-idp.${region}.amazonaws.com/us-east-1_Ab945I9ir`,
  // Cognito Hosted UI domain — NOT the issuer host, see auth.config.ts's own
  // comment on why. Looked up live via `describe-user-pool`, not guessed.
  cognitoDomain: 'https://us-east-1ab945i9ir.auth.us-east-1.amazoncognito.com',
  authSecret: process.env.AUTH_SECRET,
  cognitoClientSecret: process.env.AWS_COGNITO_CLIENT_SECRET,
  // Read from the deployer's own environment at synth/deploy time, same
  // convention as AUTH_SECRET/AWS_COGNITO_CLIENT_SECRET above — not a
  // secret, but there is no real default: an absent value here bakes
  // `undefined` into the Studio's client bundle at build time and
  // sanity.config.ts throws "Configuration must contain `projectId`" the
  // moment /studio mounts (this stack's environment map previously had no
  // field for either var at all, which is exactly what caused that error
  // live). sanityDataset falls back to 'production' inside
  // buildFrontendEnvironment when unset.
  sanityProjectId: process.env.NEXT_PUBLIC_SANITY_PROJECT_ID,
  sanityDataset: process.env.NEXT_PUBLIC_SANITY_DATASET,
  // See FrontendStackProps.skipOpenNextBuild's docstring for why this
  // exists and why it must default to false. Deliberately an explicit,
  // easy-to-grep env var rather than a silent default, so reusing it
  // requires a conscious choice each time, not muscle memory.
  skipOpenNextBuild: process.env.SKIP_OPENNEXT_BUILD === 'true',
})

// Deliberately independent of both stacks above — see
// CognitoBrandingStack's own header comment for why. Deploy on its own:
// `cdk deploy MerlinsCognitoBrandingStack`.
new CognitoBrandingStack(app, 'MerlinsCognitoBrandingStack', {
  env: { account, region },
  cognitoUserPoolId: 'us-east-1_Ab945I9ir',
  cognitoClientId: '3vmg0a9lffhc85a2lrskh27b3f',
})

// RFC 0021 — a FIFTH, deliberately independent stack (see SyncStack's own
// header comment). Deploy on its own: `bash scripts/deploy-sync.sh`, or by
// hand `cdk deploy MerlinsSyncStack --exclusively`. Never deploy this stack
// without `--exclusively` and without exporting POKEMONPRICETRACKER_API_KEY
// first — an omitted secret writes an EMPTY key on this stack too, same
// mechanism as the frontend/backend secret-wipe incidents.
new SyncStack(app, 'MerlinsSyncStack', {
  env: { account, region },
  awsRegion: region,
  dynamoTableName: 'merlins-cards',
  pokemonPriceTrackerApiKey: process.env.POKEMONPRICETRACKER_API_KEY,
  pricingDailyQuota: process.env.PRICING_DAILY_QUOTA,
})
