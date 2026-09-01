#!/usr/bin/env bash
# Post-deploy smoke check against the LIVE stacks.
#
# Exists because a deploy that reports UPDATE_COMPLETE proves nothing about
# whether the site works. On 2026-08-26 every page of the production site
# 404'd for an extended period behind two green CloudFormation stacks: the
# frontend's baked-in NEXT_PUBLIC_API_URL carried a trailing slash, so every
# request went to `//inventory/search` instead of `/inventory/search`, and
# FastAPI 404s that before it even authenticates.
#
# Run this after EVERY deploy. It is the only check here that exercises the
# deployed reality rather than a synth-time or unit-test approximation.
#
# Usage: bash scripts/smoke-deployment.sh
set -uo pipefail

FAILURES=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

echo "== Resolving live stack outputs =="
BACKEND_URL=$(aws cloudformation describe-stacks --stack-name MerlinsBackendStack \
  --query "Stacks[0].Outputs[?OutputKey=='BackendFunctionUrl'].OutputValue" --output text)
FRONTEND_URL=$(aws cloudformation describe-stacks --stack-name MerlinsFrontendStack \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" --output text)
SERVER_FN=$(aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'MerlinsFrontendStack-NextjsServerFn')].FunctionName" \
  --output text | head -n1)
echo "  backend:  ${BACKEND_URL}"
echo "  frontend: ${FRONTEND_URL}"
echo "  server fn: ${SERVER_FN}"

status() { curl -s -o /dev/null -w '%{http_code}' --max-time 45 "$1"; }

echo
echo "== Backend routes reachable =="
for probe in "/health:200" "/public/shows:200" "/inventory/search:401"; do
  path="${probe%:*}"; want="${probe##*:}"
  got=$(status "${BACKEND_URL%/}${path}")
  if [ "$got" = "$want" ]; then pass "${path} -> ${got}"; else fail "${path} -> ${got} (expected ${want})"; fi
done

echo
echo "== The 2026-08-26 regression: double-slash paths must NOT be what we serve =="
# This is a canary, not a requirement on the backend. `//health` 404ing is
# CORRECT FastAPI behaviour and is not the bug — the bug is the frontend
# ASKING for it. The real assertion is the NEXT_PUBLIC_API_URL check below.
dbl=$(status "${BACKEND_URL%/}//health")
echo "  (context) //health -> ${dbl}; a frontend that builds this path is broken"

echo
echo "== Frontend's baked backend origin has no trailing slash =="
API_URL=$(aws lambda get-function-configuration --function-name "$SERVER_FN" \
  --query 'Environment.Variables.NEXT_PUBLIC_API_URL' --output text)
echo "  NEXT_PUBLIC_API_URL = ${API_URL}"
case "$API_URL" in
  */) fail "NEXT_PUBLIC_API_URL ends in a slash — every API call will 404 (see infra/lib/backend-origin.ts)" ;;
  https://*) pass "no trailing slash" ;;
  *) fail "NEXT_PUBLIC_API_URL is not an https origin: ${API_URL}" ;;
esac

echo
echo "== Frontend secrets survived the deploy =="
# CloudFormation REPLACES a Lambda's whole environment map on every update,
# so a deploy that omitted a secret deletes it silently and NextAuth starts
# failing with a generic "server configuration" page. Presence only — values
# are never printed.
for key in AUTH_SECRET AWS_COGNITO_CLIENT_SECRET NEXT_PUBLIC_SANITY_PROJECT_ID; do
  if aws lambda get-function-configuration --function-name "$SERVER_FN" \
      --query "Environment.Variables.${key}" --output text | grep -q '^None$'; then
    fail "${key} is MISSING from the deployed Lambda"
  else
    pass "${key} present"
  fi
done

echo
echo "== Live pages respond =="
for u in "${FRONTEND_URL}/" "${FRONTEND_URL}/api/auth/session" "https://merlinsmintycards.com/"; do
  got=$(status "$u")
  if [ "$got" = "200" ]; then pass "${u} -> 200"; else fail "${u} -> ${got}"; fi
done

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32mAll smoke checks passed.\033[0m\n'
else
  printf '\033[31m%d smoke check(s) FAILED — the deploy is not good.\033[0m\n' "$FAILURES"
fi
exit "$FAILURES"
