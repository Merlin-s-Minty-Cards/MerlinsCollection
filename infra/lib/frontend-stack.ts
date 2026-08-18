import * as path from 'path'
import * as cdk from 'aws-cdk-lib'
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
  /**
   * KNOWN, UNRESOLVED, CONFIRMED-REAL ISSUE (2026-08-17), not a hypothetical:
   * on this Windows dev machine, `next build`'s static-generation fetches to
   * a live HTTPS backend hang indefinitely (Next's own 60s-per-page watchdog
   * fires 3x, then aborts) when the build is invoked through
   * cdk-nextjs-standalone's nested child-process chain (CDK CLI -> ts-node
   * -> execSync -> npm -> next build). The exact same build, same machine,
   * same backend, invoked DIRECTLY (`npm run build:opennext --workspace=
   * frontend`) succeeds every time — reproduced twice each way. Root cause
   * not yet identified (suspect a proxy/DNS/socket difference somewhere in
   * that specific nested-child-process tree on Windows); this is NOT a
   * cdk-nextjs-standalone bug report, just an observed fact about running it
   * from this kind of machine. Defaults to false (the correct long-term
   * behavior — always build fresh) so nobody has to know about this to get
   * a real deploy; set `skipOpenNextBuild: true` ONLY as a deliberate,
   * temporary escape hatch when you've already run
   * `npm run build:opennext --workspace=frontend` yourself directly and want
   * `cdk synth`/`deploy` to reuse that known-good `.open-next` output rather
   * than re-triggering a build that will hang. Do not let this quietly
   * become the permanent way this gets deployed.
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
      },
    })

    new cdk.CfnOutput(this, 'FrontendUrl', { value: this.nextjs.url })
  }
}
