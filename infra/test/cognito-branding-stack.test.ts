import { beforeAll, describe, expect, it } from 'vitest'
import * as cdk from 'aws-cdk-lib'
import { Match, Template } from 'aws-cdk-lib/assertions'
import { CognitoBrandingStack } from '../lib/cognito-branding-stack'

/**
 * Fake, non-secret test fixtures only — same convention as
 * backend-stack.test.ts. Real pool/client ids are wired in bin/infra.ts.
 *
 * Constructs `CognitoBrandingStack` directly rather than going through
 * `bin/infra.ts`, so this suite never touches `BackendStack` (whose own
 * synth shells out to a real `docker build` — see backend-stack.test.ts's
 * header comment) and stays fast.
 */
let template: Template

beforeAll(() => {
  const app = new cdk.App()
  const stack = new CognitoBrandingStack(app, 'TestCognitoBrandingStack', {
    env: { account: '000000000000', region: 'us-east-1' },
    cognitoUserPoolId: 'us-east-1_TESTPOOL',
    cognitoClientId: 'test-client-id',
  })
  template = Template.fromStack(stack)
})

function customResourceCreateCall(): { service: string; action: string; params: Record<string, unknown> } {
  const resources = template.findResources('Custom::AWS')
  const resource = Object.values(resources)[0] as { Properties: { Create: string } }
  const create = JSON.parse(resource.Properties.Create)
  return { service: create.service, action: create.action, params: create.parameters }
}

describe('CognitoBrandingStack', () => {
  it('calls SetUICustomization on the cognito-identity-provider service', () => {
    const { service, action } = customResourceCreateCall()
    expect(service).toBe('cognito-identity-provider')
    expect(action).toBe('SetUICustomization')
  })

  it('targets the given user pool and client, not a wildcard', () => {
    const { params } = customResourceCreateCall()
    expect(params.UserPoolId).toBe('us-east-1_TESTPOOL')
    expect(params.ClientId).toBe('test-client-id')
  })

  it('sends CSS matching the site brand palette', () => {
    const { params } = customResourceCreateCall()
    const css = params.CSS as string
    // cream page background, forest-green submit button — the same colors
    // as frontend/tailwind.config.ts and frontend/components/ui/Button.tsx.
    expect(css).toContain('#f2eede')
    expect(css).toContain('#1f6e32')
  })

  it('sends a non-empty base64 logo image in the same call as the CSS', () => {
    // SetUICustomization can't set CSS and the logo separately (API docs),
    // so both MUST be present on every Create/Update call, never just one.
    const { params } = customResourceCreateCall()
    expect(typeof params.ImageFile).toBe('string')
    expect((params.ImageFile as string).length).toBeGreaterThan(1000)
  })

  it('reuses the exact same call for onUpdate, so an update never drops the image or CSS', () => {
    const resources = template.findResources('Custom::AWS')
    const resource = Object.values(resources)[0] as { Properties: { Create: string; Update: string } }
    expect(resource.Properties.Update).toBe(resource.Properties.Create)
  })

  it('grants SetUICustomization scoped to the specific user pool ARN, never a wildcard resource', () => {
    // `Resource` is a constructed `Fn::Join` ARN (partition is a CFN
    // pseudo-parameter, not known at synth time) — the thing that matters
    // is that it names this exact pool, not `Resource: '*'`.
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: 'cognito-idp:SetUICustomization',
            Resource: {
              'Fn::Join': [
                '',
                Match.arrayWith([
                  Match.stringLikeRegexp(':cognito-idp:us-east-1:000000000000:userpool/us-east-1_TESTPOOL$'),
                ]),
              ],
            },
          }),
        ]),
      }),
    })
  })

  it('defines no onDelete call — destroying the stack must not reset live branding', () => {
    const resources = template.findResources('Custom::AWS')
    const resource = Object.values(resources)[0] as { Properties: Record<string, unknown> }
    expect(resource.Properties.Delete).toBeUndefined()
  })
})
