#!/usr/bin/env bash
# Safe deploy wrapper for MerlinsFrontendStack.
#
# THE TRAP THIS EXISTS TO CLOSE (CLAUDE.md, 2026-08-18): infra/bin/infra.ts
# reads every secret from the DEPLOYER'S OWN SHELL at synth time, and
# `buildFrontendEnvironment` only adds a key when its value is truthy. But
# CloudFormation REPLACES `Lambda::Function.Environment.Variables` wholesale
# on every update — it never merges. So any `cdk deploy` run from a shell
# missing one secret DELETES that secret from production, silently, while
# still reporting UPDATE_COMPLETE. It has already happened once, taking
# NextAuth down with a generic "server configuration" error.
#
# The fix is mechanical rather than remembered: read each secret's CURRENT
# LIVE VALUE straight off the deployed Lambda and re-export it, so a deploy
# can only ever preserve what is already there. Values move through command
# substitution and are never printed.
#
# A SECOND, INDEPENDENT TRAP, found live on 2026-08-26 while diffing this
# very fix: `cdk deploy MerlinsFrontendStack` pulls in its DEPENDENCY stacks
# by default, and `cdk diff` duly reported that it would also update
# MerlinsBackendStack — removing POKEMONPRICETRACKER_API_KEY (same
# omitted-secret mechanism as above, different stack) AND republishing the
# backend container image from whatever is in the working tree, committed or
# not. A frontend-only change must never redeploy the backend as a side
# effect, so this always passes `--exclusively`. The backend secrets are
# recovered anyway, so that an intentional backend deploy from this shell is
# also safe.
#
# Usage: bash scripts/deploy-frontend.sh [extra cdk args...]
set -euo pipefail

SERVER_FN=$(aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'MerlinsFrontendStack-NextjsServerFn')].FunctionName" \
  --output text | head -n1)

if [ -z "$SERVER_FN" ]; then
  echo "No deployed NextjsServerFn found — this looks like a first-time deploy." >&2
  echo "Export AUTH_SECRET and AWS_COGNITO_CLIENT_SECRET by hand, then run cdk deploy directly." >&2
  exit 1
fi

echo "Recovering current secrets from ${SERVER_FN} (values are never printed)…"

live_var() {
  aws lambda get-function-configuration --function-name "$SERVER_FN" \
    --query "Environment.Variables.$1" --output text 2>/dev/null
}

# Only fall back to the live value when the deployer has not deliberately set
# one — an explicit export in this shell still wins, so rotating a secret
# works the normal way.
BACKEND_FN=$(aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'MerlinsBackendStack-BackendFunction')].FunctionName" \
  --output text | head -n1)

backend_live_var() {
  aws lambda get-function-configuration --function-name "$BACKEND_FN" \
    --query "Environment.Variables.$1" --output text 2>/dev/null
}

for key in AUTH_SECRET AWS_COGNITO_CLIENT_SECRET NEXT_PUBLIC_SANITY_PROJECT_ID NEXT_PUBLIC_SANITY_DATASET POKEMONPRICETRACKER_API_KEY ADMIN_API_KEY; do
  current="${!key:-}"
  if [ -z "$current" ]; then
    case "$key" in
      POKEMONPRICETRACKER_API_KEY|ADMIN_API_KEY) value=$(backend_live_var "$key") ;;
      *) value=$(live_var "$key") ;;
    esac
    if [ -n "$value" ] && [ "$value" != "None" ]; then
      export "$key=$value"
      echo "  ${key}: recovered from live Lambda"
    else
      echo "  ${key}: NOT SET live and not exported — deploy would drop it" >&2
    fi
  else
    echo "  ${key}: using the value exported in this shell"
  fi
done

# Fail closed rather than silently shipping a stack that breaks sign-in.
: "${AUTH_SECRET:?refusing to deploy without AUTH_SECRET — it would be wiped from production}"
: "${AWS_COGNITO_CLIENT_SECRET:?refusing to deploy without AWS_COGNITO_CLIENT_SECRET — it would be wiped from production}"

echo
echo "Deploying MerlinsFrontendStack (--exclusively: the backend stack is NOT touched)…"
( cd "$(dirname "$0")/../infra" && npx cdk deploy MerlinsFrontendStack --exclusively "$@" )

echo
echo "Deploy finished — running smoke checks."
bash "$(dirname "$0")/smoke-deployment.sh"
