import * as cdk from 'aws-cdk-lib'

/**
 * Turn a Lambda Function URL into a slash-free origin the frontend can safely
 * concatenate slash-prefixed paths onto.
 *
 * Why this is a function with a test rather than an inline string expression:
 * the obvious spelling, `functionUrl.url.replace(/\/$/, '')`, is a SILENT
 * NO-OP. At synth time `functionUrl.url` is an unresolved CDK token, not a
 * URL — it does not end in a slash, so the regex matches nothing and CDK
 * emits the raw `Fn::ImportValue`. AWS then resolves it at deploy time WITH
 * the trailing slash, and `${BASE_URL}${path}` starts requesting
 * `//inventory/search`, which FastAPI 404s. That exact bug shipped and took
 * the production site down on 2026-08-26.
 *
 * A CDK token can only be transformed by CDK's own `Fn.*` intrinsics, which
 * defer the work into the CloudFormation template so it happens after the
 * value actually resolves.
 */
export function backendOriginFromFunctionUrl(functionUrlToken: string): string {
  // `Fn::Split('/', 'https://host/')` => ['https:', '', 'host', ''].
  // Index 2 is the bare host; the trailing empty segment is discarded with it.
  return cdk.Fn.join('', [
    'https://',
    cdk.Fn.select(2, cdk.Fn.split('/', functionUrlToken)),
  ])
}
