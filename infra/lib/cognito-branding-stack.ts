import * as fs from 'fs'
import * as path from 'path'
import * as cdk from 'aws-cdk-lib'
import * as cr from 'aws-cdk-lib/custom-resources'
import { Construct } from 'constructs'

/**
 * Classic Hosted UI branding for the Cognito login page — cream background,
 * forest-green submit button, the site's logo — matching the public site's
 * "Spriggatito" palette (frontend/tailwind.config.ts) and its primary
 * button style (frontend/components/ui/Button.tsx).
 *
 * Deliberately its OWN stack, with no dependency on MerlinsFrontendStack or
 * MerlinsBackendStack: CLAUDE.md records a real incident where a
 * MerlinsFrontendStack deploy that didn't export every existing secret
 * silently wiped AUTH_SECRET/AWS_COGNITO_CLIENT_SECRET off the live Lambda
 * (CloudFormation replaces that stack's whole Environment.Variables map on
 * every update, not merges it). This stack shares no resource and no
 * `cdk deploy` invocation with that one, so a branding-only deploy can
 * never trigger that failure mode — it isn't merely unlikely, it's
 * structurally impossible.
 *
 * `SetUICustomization` has no native CloudFormation resource (confirmed:
 * `AWS::Cognito::UserPoolUICustomizationAttachment` only exposes `css`, not
 * an image — a known, long-standing CloudFormation gap for this API, not an
 * oversight here). `AwsCustomResource` is CDK's own standard, documented
 * pattern for exactly this situation: an AWS API with no native CFN
 * coverage, still fully declarative and diffable via `cdk diff`.
 *
 * This only affects the CLASSIC Hosted UI branding version (confirmed via
 * the API's own doc: "This operation has no effect on managed login
 * pages"), which is what this user pool's domain already uses — no domain
 * or branding-version change is made or needed.
 */
export interface CognitoBrandingStackProps extends cdk.StackProps {
  readonly cognitoUserPoolId: string
  readonly cognitoClientId: string
}

export class CognitoBrandingStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: CognitoBrandingStackProps) {
    super(scope, id, props)

    const assetsDir = path.join(__dirname, '..', 'assets')
    const css = fs.readFileSync(path.join(assetsDir, 'cognito-hosted-ui.css'), 'utf-8')
    // Base64 per SetUICustomization's own request shape (API reference,
    // ImageFile: "Base64-encoded binary data object") — sent as a plain
    // string, the same way the AWS CLI's own `--image-file` flag encodes it
    // before transmission.
    const logoBase64 = fs.readFileSync(path.join(assetsDir, 'cognito-hosted-ui-logo.png')).toString('base64')

    // `SetUICustomization` requires BOTH CSS and image in the SAME call —
    // the docs are explicit that they can't be set separately, so onCreate
    // and onUpdate must both always send the complete pair, never a partial
    // update. Sharing one object for both is what guarantees that.
    const setUICustomization: cr.AwsSdkCall = {
      service: 'cognito-identity-provider',
      action: 'SetUICustomization',
      parameters: {
        UserPoolId: props.cognitoUserPoolId,
        ClientId: props.cognitoClientId,
        CSS: css,
        ImageFile: logoBase64,
      },
      physicalResourceId: cr.PhysicalResourceId.of('CognitoHostedUIBranding'),
    }

    new cr.AwsCustomResource(this, 'HostedUIBranding', {
      onCreate: setUICustomization,
      onUpdate: setUICustomization,
      // `SetUICustomization` has been part of the Cognito API for years —
      // no need for a newer SDK than what the Lambda runtime already
      // bundles. Explicit `false` rather than accepting CDK's implicit
      // default (`true`, which triggers a warning telling you to make this
      // choice on purpose): installing a newer SDK at deploy time is an
      // extra runtime dependency-install step this doesn't need.
      installLatestAwsSdk: false,
      // No onDelete: destroying this stack leaves the live branding as-is
      // rather than resetting it to Cognito's unstyled default — matches
      // this repo's general "nothing is destroyed by default" convention
      // (the archiving pattern in CLAUDE.md's "ARCHIVING IS ONE PATTERN"
      // section is the same instinct applied elsewhere).
      policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
        resources: [
          cdk.Arn.format(
            { service: 'cognito-idp', resource: 'userpool', resourceName: props.cognitoUserPoolId },
            this,
          ),
        ],
      }),
    })
  }
}
