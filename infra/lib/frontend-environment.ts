/**
 * Pure construction of the frontend's build+runtime environment variables —
 * split out from frontend-stack.ts for the same reason
 * backend-environment.ts is separate from backend-stack.ts: this branchy,
 * non-AWS logic (secret inclusion, which Cognito values are safe to inline)
 * is unit-testable without paying for a real OpenNext build on every
 * assertion. cdk-nextjs-standalone's `environment` prop feeds BOTH the
 * `next build` step (so NEXT_PUBLIC_* vars actually get inlined into the
 * client bundle — those are baked in at build time, not read at runtime)
 * and the deployed server Lambda's runtime environment, from the same map.
 */
export interface FrontendEnvironmentProps {
  readonly backendApiUrl: string
  readonly cognitoClientId: string
  readonly cognitoIssuer: string
  readonly cognitoDomain: string
  readonly authSecret?: string
  readonly cognitoClientSecret?: string
}

export function buildFrontendEnvironment(props: FrontendEnvironmentProps): Record<string, string> {
  const environment: Record<string, string> = {
    // NOT AUTH_URL: auth.config.ts sets `trustHost: true` specifically
    // because this stack's CloudFront domain isn't known until after the
    // first deploy (cdk-nextjs-standalone assigns it, we don't choose it
    // ahead of time). Auth.js derives the correct callback host from the
    // incoming request's Host header instead — this is the thing the spike
    // exists to actually verify works through CloudFront + Lambda, not
    // assume.
    NEXT_PUBLIC_API_URL: props.backendApiUrl,
    AWS_COGNITO_CLIENT_ID: props.cognitoClientId,
    AWS_COGNITO_ISSUER: props.cognitoIssuer,
    AWS_COGNITO_DOMAIN: props.cognitoDomain,
    // Must match the REAL Cognito group name, not a guess: `aws cognito-idp
    // list-groups` on this pool returns exactly one group, named `admin`
    // (singular) — confirmed 2026-08-17 while diagnosing why the CloudFront
    // spike wasn't recognizing an admin sign-in. The ECS frontend task def
    // sets this same env var to `admin` for the identical reason; this had
    // drifted to the wrong plural guess and was never checked against the
    // pool itself.
    COGNITO_ADMIN_GROUP: 'admin',
  }
  if (props.authSecret) {
    environment.AUTH_SECRET = props.authSecret
  }
  if (props.cognitoClientSecret) {
    environment.AWS_COGNITO_CLIENT_SECRET = props.cognitoClientSecret
  }
  return environment
}
