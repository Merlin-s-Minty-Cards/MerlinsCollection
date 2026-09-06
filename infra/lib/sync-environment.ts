/**
 * Pure construction of the sync task's environment variables — split out from
 * sync-stack.ts for the same reason backend-environment.ts is split from
 * backend-stack.ts: this branchy-but-non-AWS logic (secret inclusion) can be
 * unit tested with no real CDK synth / docker build involved.
 */
export interface SyncEnvironmentProps {
  readonly dynamoTableName: string
  readonly awsRegion: string
  readonly pokemonPriceTrackerApiKey?: string
  readonly pricingDailyQuota?: string
}

export function buildSyncEnvironment(props: SyncEnvironmentProps): Record<string, string> {
  const environment: Record<string, string> = {
    DYNAMODB_TABLE_NAME: props.dynamoTableName,
    // Unlike backend-environment.ts's Lambda function, AWS_REGION is NOT
    // reserved for an ECS Fargate task definition — nothing sets it
    // automatically here, so it has to be supplied explicitly or
    // `Settings.aws_region` falls back to boto3's own default-chain guess.
    AWS_REGION: props.awsRegion,
  }
  if (props.pokemonPriceTrackerApiKey) {
    environment.POKEMONPRICETRACKER_API_KEY = props.pokemonPriceTrackerApiKey
  }
  if (props.pricingDailyQuota) {
    environment.PRICING_DAILY_QUOTA = props.pricingDailyQuota
  }
  return environment
}
