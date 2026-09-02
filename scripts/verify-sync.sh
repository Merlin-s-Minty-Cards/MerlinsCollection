#!/usr/bin/env bash
# Post-deploy verification for MerlinsSyncStack (RFC 0021).
#
# Same rule CLAUDE.md already states for the frontend/backend stacks: a green
# `cdk deploy` proves nothing about whether the schedule actually runs. This
# checks the deployed reality — both schedules exist and are ENABLED, the most
# recent ECS task run (if any) is inspected, and the last structured JSON
# summary line is pulled from CloudWatch Logs and asserted to parse with
# `"status": "ok"`.
#
# Usage: bash scripts/verify-sync.sh
set -uo pipefail

FAILURES=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

echo "== Both schedules exist and are ENABLED =="
for name in merlins-sync-prices merlins-sync-catalog; do
  state=$(aws scheduler get-schedule --name "$name" --query 'State' --output text 2>/dev/null)
  if [ "$state" = "ENABLED" ]; then
    pass "${name}: ${state}"
  else
    fail "${name}: ${state:-NOT FOUND}"
  fi
done

echo
echo "== Cluster and most recent task run =="
CLUSTER=$(aws ecs list-clusters --query "clusterArns[?contains(@,'SyncCluster')]" --output text | head -n1)
if [ -z "$CLUSTER" ]; then
  fail "no SyncCluster found"
else
  pass "cluster: ${CLUSTER}"
  TASK=$(aws ecs list-tasks --cluster "$CLUSTER" --desired-status STOPPED \
    --query 'taskArns[0]' --output text 2>/dev/null)
  if [ -n "$TASK" ] && [ "$TASK" != "None" ]; then
    aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
      --query 'tasks[0].{lastStatus:lastStatus,stoppedReason:stoppedReason,startedAt:startedAt,stoppedAt:stoppedAt}' \
      --output table
  else
    echo "  (no stopped task yet — the schedule has not fired, or this is a fresh deploy)"
  fi
fi

echo
echo "== Last structured JSON summary line in CloudWatch Logs =="
LOG_GROUP=$(aws logs describe-log-groups \
  --query "logGroups[?contains(logGroupName,'SyncLogGroup')].logGroupName" \
  --output text | head -n1)
if [ -z "$LOG_GROUP" ]; then
  fail "no SyncLogGroup found"
else
  pass "log group: ${LOG_GROUP}"
  LAST_LINE=$(aws logs tail "$LOG_GROUP" --since 30d --format short 2>/dev/null \
    | grep -o '{"job".*}' | tail -n1)
  if [ -z "$LAST_LINE" ]; then
    echo "  (no structured summary line found yet — the job has not run)"
  else
    echo "  ${LAST_LINE}"
    if echo "$LAST_LINE" | python3 -c 'import json,sys; d=json.load(sys.stdin); exit(0 if d.get("status")=="ok" else 1)' 2>/dev/null; then
      pass "last run reported status: ok"
    else
      fail "last run did NOT report status: ok (see the line above)"
    fi
  fi
fi

echo
echo "== One-shot manual invocation (does not wait for the schedule) =="
echo "  Run either job right now without waiting for 09:00 UTC / the 2nd:"
echo
echo "  aws ecs run-task --cluster <cluster-arn> --task-definition <task-def-arn> \\"
echo "    --launch-type FARGATE --network-configuration \\"
echo "    'awsvpcConfiguration={subnets=[<subnet-id>],assignPublicIp=ENABLED}' \\"
echo "    --overrides '{\"containerOverrides\":[{\"name\":\"SyncTask\",\"command\":[\"python\",\"-m\",\"scripts.scheduled_sync\",\"--job\",\"prices\"]}]}'"
echo
echo "  Swap \"prices\" for \"catalog\" to run the monthly job instead. Cluster,"
echo "  task definition and subnet ids are in the CloudFormation stack outputs"
echo "  / the values printed by scripts/deploy-sync.sh's own cdk deploy run."

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32mAll sync verification checks passed (or are pending a first run).\033[0m\n'
else
  printf '\033[31m%d sync verification check(s) FAILED.\033[0m\n' "$FAILURES"
fi
exit "$FAILURES"
