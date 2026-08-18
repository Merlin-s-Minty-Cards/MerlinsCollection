#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib'
import { BackendStack } from '../lib/backend-stack'
import { FrontendStack } from '../lib/frontend-stack'

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
  corsOrigins:
    'https://me-736e73de34b349da8d2027e56db0eb8a.ecs.us-east-1.on.aws,http://localhost:3000,https://d3pmro4bgrznx9.cloudfront.net',
  pokemonPriceTrackerApiKey: process.env.POKEMONPRICETRACKER_API_KEY,
  adminApiKey: process.env.ADMIN_API_KEY,
})

new FrontendStack(app, 'MerlinsFrontendStack', {
  env: { account, region },
  // Points at the already-deployed backend Lambda's real Function URL —
  // `functionUrl.url` already includes the https:// scheme (confirmed
  // against the live BackendFunctionUrl output, which reads the same
  // property) but ALSO a trailing slash. frontend/lib/api.ts's `apiFetch`
  // concatenates `${BASE_URL}${path}` with no separator handling and every
  // caller's `path` starts with its own leading slash, so a trailing slash
  // here would produce a double slash the backend's router 404s on. Strip
  // it — this is exactly the kind of copy-paste-shaped bug the RFC's own
  // FORWARDED_ALLOW_IPS correction already warned about repeating.
  backendApiUrl: backend.functionUrl.url.replace(/\/$/, ''),
  cognitoClientId: '3vmg0a9lffhc85a2lrskh27b3f',
  cognitoIssuer: `https://cognito-idp.${region}.amazonaws.com/us-east-1_Ab945I9ir`,
  // Cognito Hosted UI domain — NOT the issuer host, see auth.config.ts's own
  // comment on why. Looked up live via `describe-user-pool`, not guessed.
  cognitoDomain: 'https://us-east-1ab945i9ir.auth.us-east-1.amazoncognito.com',
  authSecret: process.env.AUTH_SECRET,
  cognitoClientSecret: process.env.AWS_COGNITO_CLIENT_SECRET,
  // See FrontendStackProps.skipOpenNextBuild's docstring for why this
  // exists and why it must default to false. Deliberately an explicit,
  // easy-to-grep env var rather than a silent default, so reusing it
  // requires a conscious choice each time, not muscle memory.
  skipOpenNextBuild: process.env.SKIP_OPENNEXT_BUILD === 'true',
})
