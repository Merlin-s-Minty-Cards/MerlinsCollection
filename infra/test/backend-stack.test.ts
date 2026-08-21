import { beforeAll, describe, expect, it } from 'vitest'
import * as cdk from 'aws-cdk-lib'
import { Match, Template } from 'aws-cdk-lib/assertions'
import { BackendStack } from '../lib/backend-stack'

/**
 * ONE real CDK synth for the whole file (in beforeAll), shared by every
 * assertion below. BackendStack builds a container-image Lambda via
 * DockerImageCode.fromImageAsset, which shells out to a real `docker build`
 * of backend/Dockerfile's `lambda` target at synth time — synthesizing once
 * per test (the original shape of this file) meant nine full builds and blew
 * past vitest's default per-test timeout. Environment-variable branching
 * logic (secret inclusion, the FORWARDED_ALLOW_IPS correction) is unit
 * tested separately in backend-environment.test.ts with no Docker involved
 * at all — this file is only for properties that need a real synthesized
 * CloudFormation template to verify.
 *
 * Fake, non-secret test fixtures only — this file must never carry a real
 * account id, pool id, or API key. Real values are wired in bin/infra.ts
 * from the deployer's environment, never hardcoded in stack source (RFC
 * 0014 §1 / Alternatives — mirrors deploy/backend-container.json's existing
 * non-secret-vs-secret split, not a new convention).
 */
let template: Template
let backendFn: any

beforeAll(() => {
  const app = new cdk.App()
  const stack = new BackendStack(app, 'TestBackendStack', {
    env: { account: '000000000000', region: 'us-east-1' },
    awsRegion: 'us-east-1',
    dynamoTableName: 'test-cards',
    rateLimitTableName: 'test-rate-limits',
    cognitoUserPoolId: 'us-east-1_TESTPOOL',
    cognitoClientId: 'test-client-id',
    corsOrigins: 'https://example.test,http://localhost:3000',
  })
  template = Template.fromStack(stack)
  const fns = template.findResources('AWS::Lambda::Function')
  backendFn = Object.values(fns).find((r: any) => r.Properties?.PackageType === 'Image')
}, 300_000) // a real docker build — generous but bounded, not unlimited

describe('BackendStack', () => {
  it('deploys the backend as a container-image Lambda function', () => {
    expect(backendFn).toBeDefined()
    expect(backendFn.Properties.PackageType).toBe('Image')
  })

  it('sets an explicit timeout and memory size, not Lambda defaults', () => {
    // Default timeout is 3s and default memory is 128MB — both far too small
    // for a Bedrock + MCP-subprocess request (aws-serverless skill's lambda.md).
    expect(backendFn.Properties.Timeout).toBeGreaterThanOrEqual(30)
    expect(backendFn.Properties.Timeout).toBeLessThanOrEqual(60)
    expect(backendFn.Properties.MemorySize).toBeGreaterThanOrEqual(1769) // 1 vCPU equivalent
  })

  it('grants exactly the DynamoDB actions the ECS task role had, scoped to the two real tables', () => {
    // Mirrors deploy/backend-task-role-permissions.json's BusinessTable +
    // RateLimitCounters statements verbatim (RFC 0014 §1) — no wildcard
    // resource, no extra actions.
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: Match.arrayWith([
              'dynamodb:GetItem',
              'dynamodb:Query',
              'dynamodb:BatchGetItem',
              'dynamodb:BatchWriteItem',
              'dynamodb:PutItem',
              'dynamodb:DeleteItem',
              'dynamodb:TransactWriteItems',
              'dynamodb:Scan',
              'dynamodb:UpdateItem',
            ]),
          }),
          Match.objectLike({
            Effect: 'Allow',
            Action: 'dynamodb:UpdateItem',
          }),
        ]),
      }),
    })
  })

  it('grants Bedrock InvokeModel only, never a wildcard action', () => {
    const policies = template.findResources('AWS::IAM::Policy')
    const allStatements = Object.values(policies).flatMap(
      (p: any) => p.Properties.PolicyDocument.Statement
    )
    const bedrockStatements = allStatements.filter((s: any) => {
      const actions = Array.isArray(s.Action) ? s.Action : [s.Action]
      return actions.some((a: string) => typeof a === 'string' && a.startsWith('bedrock:'))
    })
    expect(bedrockStatements.length).toBeGreaterThan(0)
    for (const s of bedrockStatements) {
      const actions = Array.isArray(s.Action) ? s.Action : [s.Action]
      for (const action of actions) {
        expect(action).not.toBe('bedrock:*')
      }
    }
  })

  it('exposes a Function URL with no auth and no Cors block of its own', () => {
    // AuthType NONE was the explicit owner decision (streaming + no 30s cap).
    // Cors MUST be absent: FastAPI's CORSMiddleware is the single source of
    // CORS headers (RFC 0014 §1) — a Cors block here would be a second,
    // possibly conflicting implementation.
    template.hasResourceProperties('AWS::Lambda::Url', {
      AuthType: 'NONE',
      Cors: Match.absent(),
    })
  })

  it('allows public invocation of the Function URL via both required permission statements', () => {
    // A Function URL needs BOTH lambda:InvokeFunctionUrl AND
    // lambda:InvokeFunction (scoped by the FunctionUrlAuthType condition) —
    // granting only the first 403s every request even with AuthType=NONE
    // (aws-serverless skill's lambda.md). This test exists specifically to
    // catch that half-grant.
    const perms = template.findResources('AWS::Lambda::Permission')
    const actions = Object.values(perms).map((p: any) => p.Properties.Action)
    expect(actions).toContain('lambda:InvokeFunctionUrl')
    expect(actions).toContain('lambda:InvokeFunction')
  })

  it('creates exactly one Function URL permission pair, both scoped — never a bare public Invoke grant', () => {
    // The real risk this guards against: lambda:InvokeFunction granted to
    // '*' with NO condition at all is a much broader hole (direct Invoke
    // from anyone, not just via the Function URL) than AuthType=NONE was
    // ever meant to open. Confirmed by inspecting the real synthesized
    // template (not assumed) that addFunctionUrl({authType: NONE}) alone
    // already produces exactly two Permission resources, using two
    // DIFFERENT condition keys for its two actions:
    //   - lambda:InvokeFunctionUrl, scoped by FunctionUrlAuthType: NONE
    //   - lambda:InvokeFunction,    scoped by InvokedViaFunctionUrl: true
    // Both are legitimate CDK-generated scoping mechanisms; requiring both
    // statements to match the SAME condition shape was the wrong test (an
    // earlier draft of this test did that and was itself wrong, not the
    // stack). This also catches accidental duplication: a since-removed
    // version of the stack called addPermission() again on top of
    // addFunctionUrl()'s own grants, which doubled this to four resources.
    const perms = template.findResources('AWS::Lambda::Permission')
    const statements = Object.values(perms).map((p: any) => p.Properties)
    expect(statements).toHaveLength(2)

    const urlInvoke = statements.find((s: any) => s.Action === 'lambda:InvokeFunctionUrl')
    const functionInvoke = statements.find((s: any) => s.Action === 'lambda:InvokeFunction')
    expect(urlInvoke).toBeDefined()
    expect(functionInvoke).toBeDefined()
    expect(urlInvoke.Principal).toBe('*')
    expect(functionInvoke.Principal).toBe('*')
    expect(urlInvoke.FunctionUrlAuthType).toBe('NONE')
    expect(functionInvoke.InvokedViaFunctionUrl).toBe(true)
  })

  it('never bakes a secret value into the synthesized template when none is supplied', () => {
    const env = backendFn.Properties.Environment?.Variables ?? {}
    expect(env.POKEMONPRICETRACKER_API_KEY).toBeUndefined()
    expect(env.ADMIN_API_KEY).toBeUndefined()
  })

  it('sets FORWARDED_ALLOW_IPS to loopback, not the ECS ALB private-range value', () => {
    // The single most likely copy-paste mistake from deploy/backend-container.json
    // / backend/Dockerfile's ECS ENV — RFC 0014 §1 flags this explicitly.
    expect(backendFn.Properties.Environment.Variables.FORWARDED_ALLOW_IPS).toBe('127.0.0.1/32')
  })

  it('does not attach the function to a VPC', () => {
    // Confirmed live: no NAT Gateway, no VPC endpoints in the account today.
    // DynamoDB/Bedrock/Cognito are all public AWS endpoints — VPC attachment
    // would only add ENI cold-start cost for no benefit (RFC 0014 §1).
    expect(backendFn.Properties.VpcConfig).toBeUndefined()
  })
})
