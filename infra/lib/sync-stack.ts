import * as path from 'path'
import * as cdk from 'aws-cdk-lib'
import * as ec2 from 'aws-cdk-lib/aws-ec2'
import * as ecs from 'aws-cdk-lib/aws-ecs'
import * as iam from 'aws-cdk-lib/aws-iam'
import * as logs from 'aws-cdk-lib/aws-logs'
import * as scheduler from 'aws-cdk-lib/aws-scheduler'
import * as targets from 'aws-cdk-lib/aws-scheduler-targets'
import * as sqs from 'aws-cdk-lib/aws-sqs'
import { Construct } from 'constructs'
import { buildSyncEnvironment } from './sync-environment'

/**
 * RFC 0021 §3 — the daily/monthly catalog+price sync, restored after RFC
 * 0014's migration off ECS deleted the schedule that used to invoke
 * `scripts/scheduled_sync.py`. That script has been intact and correct the
 * whole time; it just had no caller (CLAUDE.md's "THE SYNC" incident note).
 *
 * A FOURTH, deliberately independent stack — same reasoning as
 * `CognitoBrandingStack`: it shares NO resource with `MerlinsBackendStack` or
 * `MerlinsFrontendStack`, so a scheduling change is structurally incapable of
 * touching either Lambda's environment map, and cannot trigger the
 * partial-env-export secret wipe CLAUDE.md documents (it happened once via a
 * missing `--exclusively`, and a second time via an accidental cross-stack
 * `Fn::ImportValue` dependency). The DynamoDB table name arrives as a plain
 * string prop from `bin/infra.ts`, exactly like every other stack's — NOT an
 * import from `MerlinsBackendStack`, which would pull that stack into every
 * `cdk deploy MerlinsSyncStack`.
 */
export interface SyncStackProps extends cdk.StackProps {
  readonly awsRegion: string
  readonly dynamoTableName: string
  readonly pokemonPriceTrackerApiKey?: string
  readonly pricingDailyQuota?: string
}

const CONTAINER_NAME = 'SyncTask'

// `python -m scripts.scheduled_sync --job <prices|catalog>` — the existing,
// already-tested dispatcher. Neither list is ever mutated; both schedules
// below pass their own copy as a `containerOverrides` command so neither
// can accidentally inherit the other's job.
const PRICES_COMMAND = ['python', '-m', 'scripts.scheduled_sync', '--job', 'prices']
const CATALOG_COMMAND = ['python', '-m', 'scripts.scheduled_sync', '--job', 'catalog']

export class SyncStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SyncStackProps) {
    super(scope, id, props)

    // No new VPC, no NAT gateway — reuses the account's existing default VPC.
    // Needs real credentials on the FIRST `cdk synth` (it writes
    // `cdk.context.json`); confirmed live 2026-09-02 that this account has one
    // (`aws ec2 describe-vpcs --filters Name=isDefault,Values=true`).
    const vpc = ec2.Vpc.fromLookup(this, 'DefaultVpc', { isDefault: true })

    // Fargate-only, no capacity providers, no EC2 — costs nothing idle.
    const cluster = new ecs.Cluster(this, 'SyncCluster', { vpc })

    // The job's only output is one structured JSON line per run (RFC's own
    // words) — that is the entire observability story, so a month of
    // retention is plenty.
    const logGroup = new logs.LogGroup(this, 'SyncLogGroup', {
      retention: logs.RetentionDays.ONE_MONTH,
    })

    const environment = buildSyncEnvironment({
      dynamoTableName: props.dynamoTableName,
      awsRegion: props.awsRegion,
      pokemonPriceTrackerApiKey: props.pokemonPriceTrackerApiKey,
      pricingDailyQuota: props.pricingDailyQuota,
    })

    // 1 vCPU / 2048 MiB — the catalog walk is network-bound (TCGdex /
    // PokemonPriceTracker HTTP calls), not CPU-bound.
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'SyncTaskDefinition', {
      cpu: 1024,
      memoryLimitMiB: 2048,
    })

    taskDefinition.addContainer(CONTAINER_NAME, {
      // `runtime`, NOT `lambda` — see the class docstring. This stack wants
      // the ECS production stage; sync-stack.test.ts pins this against the
      // synthesized ASSET MANIFEST (the build target is not a CloudFormation
      // template property, so the template alone can't prove it).
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, '..', '..'), {
        file: 'backend/Dockerfile',
        target: 'runtime',
        // Same reason as backend-stack.ts's identical exclude: the asset
        // build context is the repo root, and without this the copy can
        // recurse into its own `infra/cdk.out` output.
        exclude: ['**/cdk.out', '**/cdk.out/**'],
      }),
      environment,
      logging: ecs.LogDrivers.awsLogs({ logGroup, streamPrefix: 'sync' }),
      // A sane default for a manual `RunTask` with no override (the
      // `runtime` stage's own image CMD launches uvicorn, a web server that
      // would sit there doing nothing useful for a scheduled batch job) —
      // but every schedule below still supplies its OWN explicit
      // `containerOverrides` command, so this default is never what
      // actually decides which job runs on a real schedule.
      command: PRICES_COMMAND,
    })

    // Mirrors `deploy/backend-task-role-permissions.json`'s BusinessTable
    // statement — any new action the sync needs goes in BOTH places or they
    // drift. `dynamodb:Scan` is required, not an oversight: the catalog
    // cache and `_scan_catalog` are on this job's path, and CLAUDE.md
    // records a live HTTP 500 from exactly this grant being missing on the
    // old ECS task role.
    taskDefinition.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: 'CatalogTable',
        effect: iam.Effect.ALLOW,
        actions: [
          'dynamodb:Query',
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:BatchWriteItem',
          'dynamodb:Scan',
        ],
        resources: [
          `arn:aws:dynamodb:${props.awsRegion}:${cdk.Stack.of(this).account}:table/${props.dynamoTableName}`,
          `arn:aws:dynamodb:${props.awsRegion}:${cdk.Stack.of(this).account}:table/${props.dynamoTableName}/index/*`,
        ],
      })
    )

    // Shared dead-letter target for both schedules — the durable failure
    // record. A CloudWatch alarm on its depth is a follow-up, not a launch
    // requirement (adversarial review finding 5: cut for launch).
    const deadLetterQueue = new sqs.Queue(this, 'SyncDeadLetterQueue', {
      retentionPeriod: cdk.Duration.days(14),
    })

    // The job must reach api.tcgdex.net and pokemonpricetracker.com over the
    // internet, and a NAT gateway costs ~$32/month to avoid a public IP on a
    // task that runs twice a month.
    const commonTargetProps = {
      taskDefinition,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      assignPublicIp: true,
      deadLetterQueue,
    }

    new scheduler.Schedule(this, 'PricesSchedule', {
      scheduleName: 'merlins-sync-prices',
      // 09:00 UTC = 01:00/02:00 Pacific — overnight in the business's own
      // timezone; carries the ~24-minute weekly catalog cycle inside
      // `run_daily_sync` as its long tail.
      schedule: scheduler.ScheduleExpression.expression('cron(0 9 * * ? *)'),
      target: new targets.EcsRunFargateTask(cluster, {
        ...commonTargetProps,
        input: scheduler.ScheduleTargetInput.fromObject({
          containerOverrides: [{ name: CONTAINER_NAME, command: PRICES_COMMAND }],
        }),
      }),
    })

    new scheduler.Schedule(this, 'CatalogSchedule', {
      scheduleName: 'merlins-sync-catalog',
      // The 2nd at 15:00 UTC — a DIFFERENT day and hour from the nightly
      // job on purpose (adversarial review finding 8): the nightly `prices`
      // run carries its own catalog-writing cycle, and two concurrent
      // catalog writers is not a state either job was designed for. Six
      // hours clear of any plausible overrun is cheaper than building a
      // lock for a job that runs twice a month.
      schedule: scheduler.ScheduleExpression.expression('cron(0 15 2 * ? *)'),
      target: new targets.EcsRunFargateTask(cluster, {
        ...commonTargetProps,
        input: scheduler.ScheduleTargetInput.fromObject({
          containerOverrides: [{ name: CONTAINER_NAME, command: CATALOG_COMMAND }],
        }),
      }),
    })
  }
}
