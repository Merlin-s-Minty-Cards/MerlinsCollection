#!/usr/bin/env bash
# Safe deploy wrapper for MerlinsSyncStack (RFC 0021).
#
# THE SAME TRAP AS deploy-frontend.sh, ON A FOURTH SURFACE: this stack's own
# environment map carries POKEMONPRICETRACKER_API_KEY, read from the
# deployer's shell at synth time (infra/bin/infra.ts). A `cdk deploy
# MerlinsSyncStack` run from a shell that doesn't have it exported writes an
# EMPTY key — CloudFormation replaces Environment.Variables wholesale, never
# merges — and `build_pricing_provider()` returns `None`, so the nightly job
# silently stops pricing slabs while reporting success on every other step.
# There is no loud failure here; only a quiet one, which is worse.
#
# The fix is the same mechanical one: read the CURRENT LIVE value straight off
# the deployed sync task definition and re-export it, so a deploy can only
# ever preserve what is already there. An explicit export in this shell still
# wins, so rotating the key works the normal way.
#
# `--exclusively` is always passed. This stack has NO Fn::ImportValue and no
# cross-stack dependency (sync-stack.test.ts pins the absence), so
# `--exclusively` should never actually change what gets deployed — but
# passing it costs nothing and is the same belt-and-suspenders discipline
# deploy-frontend.sh uses for a dependency that genuinely exists there.
#
# Usage: bash scripts/deploy-sync.sh [extra cdk args...]
set -euo pipefail

TASK_DEF_FAMILY=$(aws ecs list-task-definitions \
  --query "taskDefinitionArns[?contains(@,'SyncTaskDefinition')]" \
  --output text | head -n1)

live_var() {
  aws ecs describe-task-definition --task-definition "$TASK_DEF_FAMILY" \
    --query "taskDefinition.containerDefinitions[0].environment[?name=='$1'].value | [0]" \
    --output text 2>/dev/null
}

if [ -z "$TASK_DEF_FAMILY" ]; then
  echo "No deployed SyncTaskDefinition found — this looks like a first-time deploy." >&2
  echo "Export POKEMONPRICETRACKER_API_KEY by hand if you want graded pricing on the" >&2
  echo "nightly job, then run cdk deploy directly (an unset key is a supported state:" >&2
  echo "the job just skips graded pricing and every other step still runs)." >&2
else
  echo "Recovering the current secret from ${TASK_DEF_FAMILY} (value is never printed)…"
  if [ -z "${POKEMONPRICETRACKER_API_KEY:-}" ]; then
    value=$(live_var "POKEMONPRICETRACKER_API_KEY")
    if [ -n "$value" ] && [ "$value" != "None" ]; then
      export POKEMONPRICETRACKER_API_KEY="$value"
      echo "  POKEMONPRICETRACKER_API_KEY: recovered from the live task definition"
    else
      echo "  POKEMONPRICETRACKER_API_KEY: NOT SET live and not exported — deploy would leave it unset" >&2
    fi
  else
    echo "  POKEMONPRICETRACKER_API_KEY: using the value exported in this shell"
  fi
fi

echo
echo "Deploying MerlinsSyncStack (--exclusively)…"
( cd "$(dirname "$0")/../infra" && npx cdk deploy MerlinsSyncStack --exclusively "$@" )

echo
echo "Deploy finished. Verifying…"
bash "$(dirname "$0")/verify-sync.sh"
