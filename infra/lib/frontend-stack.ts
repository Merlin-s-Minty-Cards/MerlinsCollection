import * as path from 'path'
import * as cdk from 'aws-cdk-lib'
import * as acm from 'aws-cdk-lib/aws-certificatemanager'
import { Construct } from 'constructs'
import { Nextjs } from 'cdk-nextjs-standalone'
import { buildFrontendEnvironment } from './frontend-environment'

/**
 * RFC 0014 §4 / Task 6 spike — the frontend on Lambda + CloudFront via
 * OpenNext, deployed in parallel with the existing ECS frontend service
 * (same posture as BackendStack: nothing points at this yet).
 *
 * Deployment mechanism: `cdk-nextjs-standalone` (see RFC 0014's Open
 * Questions for the full research trail on why this over the OpenNext CDK
 * reference implementation, a same-named-but-unrelated `cdklabs/cdk-nextjs`
 * package, or SST). It builds the CloudFront distribution, the server
 * Lambda, the image-optimization Lambda, and the SQS-backed ISR
 * revalidation queue for us — OpenNext's own docs are explicit that none of
 * that topology comes from `@opennextjs/aws` itself.
 *
 * This stack's SPECIFIC, stated purpose is validating one real unknown
 * flagged during the tooling research: `cdk-nextjs-standalone`'s NextAuth
 * compatibility claim is only a generic, unversioned README line — nothing
 * in its issue history confirms NextAuth v5 (only v4-era reports exist).
 * Getting real sign-in working through this exact deployed topology is the
 * spike's success criterion, not just a successful `cdk deploy`.
 */
export interface FrontendStackProps extends cdk.StackProps {
  readonly backendApiUrl: string
  readonly cognitoClientId: string
  readonly cognitoIssuer: string
  readonly cognitoDomain: string
  readonly authSecret?: string
  readonly cognitoClientSecret?: string
  readonly sanityProjectId?: string
  readonly sanityDataset?: string
  /**
   * RESOLVED 2026-08-26 — root cause found, and it was NOT what this docstring
   * used to claim. The old text recorded a "Windows nested-child-process
   * proxy/DNS/socket" theory based on "direct build succeeds, CDK-driven build
   * hangs, reproduced twice each way". Both observations were real; the
   * conclusion was wrong, because the comparison was uncontrolled.
   *
   * `NextjsBuild.getBuildEnvVars()` swaps every UNRESOLVED `NEXT_PUBLIC_*`
   * token for a literal `{{ KEY }}` placeholder. So a CDK-driven build runs
   * with `NEXT_PUBLIC_API_URL="{{ NEXT_PUBLIC_API_URL }}"`, while a hand-run
   * build from a plain shell has it UNSET and falls back to localhost. The
   * arms differed by the backend URL, not by the process tree. Reproduced on
   * Linux, both arms direct: placeholder => hangs, localhost => 24/24 pages.
   *
   * Mechanism: bare `fetch` rejects that URL in ~23ms, but `lib/public.ts`
   * fetches with `next: { revalidate: 300 }` and Next's ISR fetch wrapper
   * turns the rejection into a HANG, burning staticPageGenerationTimeout on
   * whichever public page got there first (hence "a different page each
   * time"). Fixed properly in `frontend/lib/api-base.ts`: `apiFetch` now
   * rejects before constructing a request when the base URL is not a real
   * http(s) origin, so callers' existing fallbacks actually fire.
   *
   * **`skipOpenNextBuild` should no longer be needed.** It stays as an escape
   * hatch, and if you do use it, note the footgun the old instructions
   * omitted: run the manual build with
   * `NEXT_PUBLIC_API_URL='{{ NEXT_PUBLIC_API_URL }}'` (plus the Sanity vars)
   * or the bundle bakes `http://localhost:8000` into production, since there
   * will be no placeholder left for the deploy-time substitution to replace.
   * `scripts/deploy-frontend.sh` + `scripts/smoke-deployment.sh` are the safe
   * path. See CLAUDE.md, "THE FRONTEND BUILD HANG IS AN UNBOUNDED FETCH".
   */
  readonly skipOpenNextBuild?: boolean
}

export class FrontendStack extends cdk.Stack {
  public readonly nextjs: Nextjs

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props)

    const environment = buildFrontendEnvironment(props)

    // Repo root: infra/lib -> ../.. — same pattern BackendStack uses.
    // `buildPath: repoRoot` runs the build from the monorepo root (matches
    // cdk-nextjs-standalone's own documented monorepo pattern) so npm
    // workspace-hoisted node_modules resolve correctly; `buildCommand`
    // targets the frontend workspace's own `build:opennext` script (added
    // alongside its ordinary `build`, which still drives the ECS image and
    // must stay untouched).
    const repoRoot = path.join(__dirname, '..', '..')

    this.nextjs = new Nextjs(this, 'Nextjs', {
      nextjsPath: path.join(repoRoot, 'frontend'),
      buildPath: repoRoot,
      buildCommand: 'npm run build:opennext --workspace=frontend',
      environment,
      // See FrontendStackProps.skipOpenNextBuild's docstring — a deliberate,
      // temporary, non-default escape hatch, not the normal path.
      skipBuild: props.skipOpenNextBuild ?? false,
      // Streaming left at its default (false) for this spike — the backend
      // Lambda's own streaming question (RFC 0014 §1) doesn't extend to the
      // frontend automatically, and turning it on is an easy follow-up once
      // the auth question is answered, not a prerequisite for answering it.
      overrides: {
        // Real, confirmed failure (2026-08-17): the static-assets bucket
        // deployment custom resource — a Lambda that downloads the built
        // assets zip and extracts it into the destination S3 bucket — hit
        // `ENOSPC: no space left on device` extracting this app's asset
        // bundle. Default ephemeral storage (/tmp) for this Lambda is 512
        // MiB (cdk-nextjs-standalone's own documented default), and this
        // app's static output (Sanity Studio alone is 1.5+ MB pre-gzip,
        // times every chunk/font/image across 24 routes) exceeds that once
        // the downloaded zip and its extracted contents coexist in /tmp
        // simultaneously. Bumped to 2 GiB — comfortably above the observed
        // failure, not tuned to a minimum, since a custom-resource Lambda
        // that occasionally fails on assets growing over time is a worse
        // outcome than a few extra pennies of unused /tmp allocation.
        //
        // The override path is NOT the top-level `overrides.
        // nextjsBucketDeployment` its name suggests — that key exists but
        // isn't what NextjsStaticAssets actually reads (confirmed by
        // reading cdk-nextjs-standalone's own source,
        // node_modules/cdk-nextjs-standalone/lib/NextjsStaticAssets.js: it
        // reads `this.props.overrides?.nextjsBucketDeploymentProps`, nested
        // under nextjsStaticAssets's OWN overrides, which itself has a
        // further `overrides.functionProps`). A first attempt using the
        // top-level key type-checked cleanly (both keys are real, valid
        // paths on the type — just for different resources) and silently
        // applied to nothing; only inspecting the synthesized template's
        // actual Lambda resources caught that it hadn't worked. Applied to
        // both the static-assets AND server bucket deployments — only
        // static-assets failed this time, but both run the identical
        // download-then-extract code path and the server's asset bundle
        // will grow the same way.
        nextjsStaticAssets: {
          nextjsBucketDeploymentProps: {
            overrides: {
              functionProps: {
                ephemeralStorageSize: cdk.Size.gibibytes(2),
              },
            },
          },
        },
        nextjsServer: {
          nextjsBucketDeploymentProps: {
            overrides: {
              functionProps: {
                ephemeralStorageSize: cdk.Size.gibibytes(2),
              },
            },
          },
        },
        // `merlinsmintycards.com` / `www` were attached to this
        // distribution by hand, outside CDK, some time before this stack
        // existed in its current form — nothing in this file ever declared
        // `Aliases` or a `ViewerCertificate`. CloudFormation manages the
        // FULL property set of AWS::CloudFront::Distribution on every
        // update, so a template that's silent on those two properties
        // resets them to empty/default on every deploy — confirmed the hard
        // way 2026-08-25: a routine `cdk deploy MerlinsFrontendStack`
        // silently stripped both, and the domain served CloudFront's
        // default `*.cloudfront.net` cert (a hostname mismatch, not a
        // renewal failure) until manually restored via
        // `aws cloudfront update-distribution`.
        //
        // NOT using `Nextjs`'s own top-level `domainProps` here: that path
        // requires a Route53 hosted zone in this account (`HostedZone.
        // fromLookup`, plus it writes A/AAAA alias records itself) and this
        // IAM user has no route53:ListHostedZones grant — confirmed via a
        // live AccessDenied, not assumed. `overrides.nextjsDistribution.
        // distributionProps` is the documented escape hatch for exactly
        // this case ("DNS setups where you cannot use a Route53 hosted zone
        // in the same account") — it only sets the two CloudFront-side
        // properties and never touches DNS, which already correctly points
        // at this distribution from wherever it's actually managed.
        //
        // Reuses the existing ISSUED cert rather than provisioning a new
        // one: `*.merlinsmintycards.com` with `merlinsmintycards.com` as an
        // additional SAN, so both the apex and `www` are covered.
        nextjsDistribution: {
          distributionProps: {
            domainNames: ['merlinsmintycards.com', 'www.merlinsmintycards.com'],
            certificate: acm.Certificate.fromCertificateArn(
              this,
              'CustomDomainCertificate',
              'arn:aws:acm:us-east-1:560151615792:certificate/ec514ed8-8b19-496e-a1ad-82c6f3d2d765',
            ),
          },
        },
      },
    })

    new cdk.CfnOutput(this, 'FrontendUrl', { value: this.nextjs.url })
  }
}
