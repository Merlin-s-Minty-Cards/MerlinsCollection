import * as path from 'path'
import * as cdk from 'aws-cdk-lib'
import * as iam from 'aws-cdk-lib/aws-iam'
import * as lambda from 'aws-cdk-lib/aws-lambda'
import { Construct } from 'constructs'
import { buildBackendEnvironment } from './backend-environment'

/**
 * Non-secret configuration, mirroring deploy/backend-container.json's
 * committed environment block. Secrets (pokemonPriceTrackerApiKey,
 * adminApiKey) are separate, optional props — read from the deployer's
 * environment by bin/infra.ts at synth time, never literals here. An unset
 * secret is a supported state (matches Settings.pokemonpricetracker_api_key's
 * own empty-string default): the corresponding env var is simply omitted
 * rather than written as an empty string, so a stray "" doesn't shadow a
 * value set some other way later.
 */
export interface BackendStackProps extends cdk.StackProps {
  readonly awsRegion: string
  readonly dynamoTableName: string
  readonly rateLimitTableName: string
  readonly cognitoUserPoolId: string
  readonly cognitoClientId: string
  readonly corsOrigins: string
  readonly pokemonPriceTrackerApiKey?: string
  readonly adminApiKey?: string
}

/**
 * RFC 0014 §1 — the backend Lambda: same container image the ECS service
 * already runs (backend/Dockerfile's `lambda` stage, built on top of the
 * shared `base` stage), fronted by a public Lambda Function URL instead of
 * an ALB. No VPC attachment (DynamoDB/Bedrock/Cognito are all public AWS
 * endpoints; confirmed live that the account has no NAT Gateway or VPC
 * endpoint today, so there is nothing this would gain from being private).
 */
export class BackendStack extends cdk.Stack {
  public readonly functionUrl: lambda.FunctionUrl
  public readonly backendFunction: lambda.DockerImageFunction

  constructor(scope: Construct, id: string, props: BackendStackProps) {
    super(scope, id, props)

    const environment = buildBackendEnvironment(props)

    // Build context MUST be the repo root — backend/Dockerfile's own header
    // comment says so (the lockfile and both mcp-server/frontend workspaces
    // it COPYs from live there). infra/lib -> ../.. is that root.
    //
    // `exclude` is NOT optional here. CDK auto-excludes a directory named
    // after Stage.of(this).outdir, but that value is an ABSOLUTE path (e.g.
    // C:\...\infra\cdk.out when run via the real `cdk` CLI, since cdk.json
    // lives in infra/), while the asset-staging copy matches exclude
    // patterns against paths RELATIVE to this build context — so the
    // auto-exclude never actually matches and is silently a no-op. The root
    // .dockerignore's bare `infra/cdk.out` entry doesn't save it either:
    // under the default IgnoreMode.GLOB, a pattern with no trailing `/**`
    // does not recurse into the directory's contents. Net effect, confirmed
    // by actually running `cdk bootstrap` (unit tests can't catch this: see
    // below): the asset copy walks into infra/cdk.out/asset.<hash>/, which
    // is itself inside the very tree being copied, and recurses into itself
    // until a Windows path-length error kills it.
    //
    // The explicit `**/cdk.out/**` here matches regardless of ignoreMode or
    // where the App's outdir happens to resolve.
    //
    // backend-stack.test.ts's beforeAll cannot exercise this bug: a bare
    // `new cdk.App()` constructed directly (not via the `cdk` CLI / cdk.json)
    // gets a random OS-temp outdir with no relation to the repo tree, so the
    // recursive-self-copy condition never arises there — this is the same
    // "fast test path doesn't touch the real code path" gap the Dockerfile
    // `lambda` stage bug hit earlier; only a real `cdk synth`/`bootstrap`
    // proves this.
    const backendFunction = new lambda.DockerImageFunction(this, 'BackendFunction', {
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '..', '..'), {
        file: 'backend/Dockerfile',
        target: 'lambda',
        exclude: ['**/cdk.out', '**/cdk.out/**'],
      }),
      // 2048 MB matches the ECS task's existing sizing (1 vCPU / 2048 MB) —
      // the dual Python+Node runtime needs the same headroom here it needed
      // there. 1,769 MB is Lambda's 1-vCPU-equivalent breakpoint; this sits
      // above it deliberately, not at the minimum.
      memorySize: 2048,
      // Default Lambda timeout is 3s — nowhere near enough for a Bedrock +
      // MCP-subprocess round trip. No API Gateway 30s ceiling to work
      // around here (that's the point of the Function URL choice), so this
      // is bound only by what's reasonable for an interactive request.
      timeout: cdk.Duration.seconds(30),
      environment,
      // No `vpc` prop — see class docstring.
    })
    this.backendFunction = backendFunction

    // Same three statements as deploy/backend-task-role-permissions.json,
    // verbatim — resource-scoped, no wildcard actions.
    backendFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'BusinessTable',
        effect: iam.Effect.ALLOW,
        actions: [
          'dynamodb:GetItem',
          'dynamodb:Query',
          'dynamodb:BatchGetItem',
          'dynamodb:BatchWriteItem',
          'dynamodb:PutItem',
          'dynamodb:DeleteItem',
          'dynamodb:TransactWriteItems',
          'dynamodb:Scan',
          'dynamodb:UpdateItem',
        ],
        resources: [
          `arn:aws:dynamodb:${props.awsRegion}:${cdk.Stack.of(this).account}:table/${props.dynamoTableName}`,
          `arn:aws:dynamodb:${props.awsRegion}:${cdk.Stack.of(this).account}:table/${props.dynamoTableName}/index/*`,
        ],
      })
    )
    backendFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'RateLimitCounters',
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:UpdateItem'],
        resources: [
          `arn:aws:dynamodb:${props.awsRegion}:${cdk.Stack.of(this).account}:table/${props.rateLimitTableName}`,
        ],
      })
    )
    backendFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'BedrockInvoke',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
          `arn:aws:bedrock:${props.awsRegion}:${cdk.Stack.of(this).account}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0`,
        ],
      })
    )

    // AuthType NONE — owner decision (RFC 0014 Alternatives Considered):
    // no response streaming or 30s hard cap under API Gateway HTTP API,
    // and this matches the ALB's own current no-WAF posture rather than
    // regressing it. No `cors` prop: FastAPI's CORSMiddleware is the single
    // source of CORS headers (see backend-stack.test.ts for why a second
    // implementation here would be a bug, not redundancy).
    const functionUrl = backendFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    })
    this.functionUrl = functionUrl
    // addFunctionUrl() with authType NONE already generates BOTH required
    // permission statements on its own — lambda:InvokeFunctionUrl (scoped
    // by a FunctionUrlAuthType condition) and lambda:InvokeFunction (scoped
    // by an InvokedViaFunctionUrl condition). Confirmed by inspecting the
    // synthesized template rather than assumed: an earlier version of this
    // code added both grants again explicitly, believing addFunctionUrl()
    // didn't cover them (true in some older CDK versions per the
    // aws-serverless skill's lambda.md) — that produced four permission
    // resources instead of two. Do not re-add addPermission() calls here
    // without re-checking the synthesized template first.

    new cdk.CfnOutput(this, 'BackendFunctionUrl', { value: functionUrl.url })
  }
}
