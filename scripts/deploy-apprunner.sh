#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${APP_RUNNER_SERVICE_NAME:=graphic-recording-agent-demo}"
: "${APP_PASSWORD:?Set APP_PASSWORD for the web login.}"
: "${APP_SECRET_KEY:?Set APP_SECRET_KEY for signed auth cookies.}"
: "${AGENT_BACKEND:=runtime}"
: "${AGENTCORE_RUNTIME_ARN:?Set AGENTCORE_RUNTIME_ARN after deploying AgentCore Runtime.}"
: "${S3_BUCKET:?Set S3_BUCKET to the artifact bucket name.}"

reject_placeholder() {
  local name="$1"
  local value="$2"
  if [[ "${value}" == *"CHANGE_ME"* || "${value}" == *"PASTE_HERE"* || "${value}" == *"YOUR_"* || "${value}" == *"ACCOUNT_ID"* ]]; then
    echo "${name} still contains a placeholder: ${value}" >&2
    exit 1
  fi
}

reject_placeholder AGENTCORE_RUNTIME_ARN "${AGENTCORE_RUNTIME_ARN}"
reject_placeholder S3_BUCKET "${S3_BUCKET}"

cat <<EOF
Deploy the web service with AWS App Runner using this repository as the source.

Set these runtime environment variables:
APP_ENV=production
APP_PASSWORD=${APP_PASSWORD}
APP_SECRET_KEY=${APP_SECRET_KEY}
APP_LOG_FORMAT=json
MOCK_MODE=false
AGENT_BACKEND=${AGENT_BACKEND}
AGENTCORE_RUNTIME_ARN=${AGENTCORE_RUNTIME_ARN}
AWS_REGION=${AWS_REGION}
BEDROCK_TEXT_MODEL_ID=${BEDROCK_TEXT_MODEL_ID:-us.anthropic.claude-sonnet-4-20250514-v1:0}
BEDROCK_IMAGE_MODEL_ID=${BEDROCK_IMAGE_MODEL_ID:-}
S3_BUCKET=${S3_BUCKET}
S3_ARTIFACT_PREFIX=${S3_ARTIFACT_PREFIX:-artifacts}
S3_PRESIGNED_URL_TTL_SECONDS=${S3_PRESIGNED_URL_TTL_SECONDS:-28800}

The App Runner console is the most reliable workshop path because participants
can connect their own fork and confirm the service role before creation.
EOF
