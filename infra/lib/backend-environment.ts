/**
 * Pure construction of the backend Lambda's environment variables — split
 * out from backend-stack.ts so this branchy-but-non-AWS logic (secret
 * inclusion, LWA knobs, the FORWARDED_ALLOW_IPS trust-boundary correction)
 * can be unit tested without paying for a real `docker build` on every
 * assertion (BackendStack's own tests need one real CDK synth; this file's
 * tests need none).
 */
export interface BackendEnvironmentProps {
  readonly dynamoTableName: string
  readonly rateLimitTableName: string
  readonly cognitoUserPoolId: string
  readonly cognitoClientId: string
  readonly corsOrigins: string
  readonly pokemonPriceTrackerApiKey?: string
  readonly adminApiKey?: string
}

export function buildBackendEnvironment(props: BackendEnvironmentProps): Record<string, string> {
  const environment: Record<string, string> = {
    // NOT AWS_REGION: Lambda reserves it and sets it automatically from the
    // function's actual deployed region — CloudFormation rejects an
    // explicit value with ReservedEnvironmentVariable. Settings.aws_region
    // reads whatever the runtime already provides.
    DYNAMODB_TABLE_NAME: props.dynamoTableName,
    RATE_LIMIT_TABLE_NAME: props.rateLimitTableName,
    COGNITO_USER_POOL_ID: props.cognitoUserPoolId,
    COGNITO_CLIENT_ID: props.cognitoClientId,
    CORS_ORIGINS: props.corsOrigins,
    // LWA's own knobs. BUFFERED for launch — /chat returns a single
    // ChatResponse today, not a stream; RESPONSE_STREAM is available later
    // with no app rewrite if streaming chat becomes real (the reason a
    // Function URL was chosen over API Gateway HTTP API, which cannot
    // stream at all).
    AWS_LWA_PORT: '8000',
    AWS_LWA_INVOKE_MODE: 'BUFFERED',
    // NOT the ECS ALB's RFC1918 trust range. Under LWA the app's real peer
    // is the adapter on the loopback interface, inside the same execution
    // environment — see RFC 0014 §1's trust-boundary note.
    FORWARDED_ALLOW_IPS: '127.0.0.1/32',
  }
  if (props.pokemonPriceTrackerApiKey) {
    environment.POKEMONPRICETRACKER_API_KEY = props.pokemonPriceTrackerApiKey
  }
  if (props.adminApiKey) {
    environment.ADMIN_API_KEY = props.adminApiKey
  }
  return environment
}
