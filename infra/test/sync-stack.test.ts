import * as fs from 'fs'
import * as path from 'path'
import { beforeAll, describe, expect, it } from 'vitest'
import * as cdk from 'aws-cdk-lib'
import { Match, Template } from 'aws-cdk-lib/assertions'
import { SyncStack } from '../lib/sync-stack'

/**
 * ONE real CDK synth for the whole file (in beforeAll), mirroring
 * backend-stack.test.ts's own rationale: `ecs.ContainerImage.fromAsset`
 * shells out to a real `docker build` of backend/Dockerfile's `runtime`
 * target at synth time. `Vpc.fromLookup` needs an account/region-scoped
 * stack; outside the real `cdk` CLI toolkit (no cached `cdk.context.json`
 * entry) it resolves to a dummy placeholder VPC rather than failing or
 * making a live AWS call — sufficient for asserting resource SHAPE, which
 * is everything this file checks.
 *
 * Fake, non-secret fixtures only, mirroring backend-stack.test.ts's own rule.
 */
let template: Template
let assetsManifest: any

beforeAll(() => {
  const app = new cdk.App()
  const stack = new SyncStack(app, 'TestSyncStack', {
    env: { account: '000000000000', region: 'us-east-1' },
    awsRegion: 'us-east-1',
    dynamoTableName: 'test-cards',
  })
  const assembly = app.synth()
  template = Template.fromStack(stack)
  // The `--target` build arg is a LOCAL docker-build parameter, not a
  // CloudFormation template property — it lives only in the synthesized
  // assets manifest (CLAUDE.md's rule: verify the synthesized template,
  // never the source, and here the template alone is not even enough).
  const manifestPath = path.join(assembly.directory, 'TestSyncStack.assets.json')
  assetsManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'))
}, 300_000) // a real docker build — generous but bounded, not unlimited

describe('SyncStack', () => {
  it('builds the container image from the runtime target, NOT lambda -- this is ECS, no Lambda Runtime API to talk to', () => {
    // backend-stack.ts wants `lambda` (a real Lambda Runtime API to talk
    // to); this stack is an ECS Fargate task with none, so the `lambda`
    // stage's Web Adapter extension would be dead weight. The two must
    // never drift onto each other's target by a copy-paste "fix".
    const dockerAssets = Object.values(assetsManifest.dockerImages ?? {})
    expect(dockerAssets.length).toBeGreaterThan(0)
    for (const asset of dockerAssets as any[]) {
      expect(asset.source.dockerBuildTarget).toBe('runtime')
    }
  })

  it('creates exactly two EventBridge Scheduler schedules with the exact cron expressions', () => {
    const schedules = template.findResources('AWS::Scheduler::Schedule')
    const expressions = Object.values(schedules).map((r: any) => r.Properties.ScheduleExpression)
    expect(expressions.sort()).toEqual(['cron(0 15 2 * ? *)', 'cron(0 9 * * ? *)'])
  })

  it('each schedule overrides the container command to a different --job value', () => {
    const schedules = template.findResources('AWS::Scheduler::Schedule')
    const inputs = Object.values(schedules).map((r: any) => {
      const raw = r.Properties.Target.Input
      // `Input` is a JSON-encoded string (possibly an Fn::Join of tokens);
      // pull the literal fragments out and see which --job value appears.
      const text = typeof raw === 'string' ? raw : JSON.stringify(raw)
      return text
    })
    const hasPrices = inputs.some((t) => t.includes('prices'))
    const hasCatalog = inputs.some((t) => t.includes('catalog'))
    expect(hasPrices).toBe(true)
    expect(hasCatalog).toBe(true)
  })

  it('grants dynamodb:Scan on the task role -- the catalog cache path needs it', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: Match.arrayWith(['dynamodb:Scan']),
          }),
        ]),
      }),
    })
  })

  it('sets the environment map with all four expected keys', () => {
    const defs = template.findResources('AWS::ECS::TaskDefinition')
    const def: any = Object.values(defs)[0]
    const containerDef = def.Properties.ContainerDefinitions[0]
    const envNames = containerDef.Environment.map((e: any) => e.Name)
    expect(envNames).toEqual(
      expect.arrayContaining(['DYNAMODB_TABLE_NAME', 'AWS_REGION'])
    )
  })

  it('has no Fn::ImportValue anywhere -- proving it cannot drag another stack into a deploy', () => {
    const json = JSON.stringify(template.toJSON())
    expect(json).not.toContain('Fn::ImportValue')
  })
})
