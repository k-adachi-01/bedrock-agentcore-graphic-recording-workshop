#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${S3_BUCKET:=}"
: "${AGENTCORE_RUNTIME_ARN:=}"
: "${APP_RUNNER_SERVICE_ARN:=}"

echo "SUMMARY"
aws sts get-caller-identity --query 'Arn' --output text
echo "Region: ${AWS_REGION}"
echo "AgentCore Runtime ARN: ${AGENTCORE_RUNTIME_ARN:-not set}"
echo "S3 bucket: ${S3_BUCKET:-not set}"
echo "App Runner service ARN: ${APP_RUNNER_SERVICE_ARN:-not set}"

if [[ -n "${S3_BUCKET}" ]]; then
  aws s3api head-bucket --bucket "${S3_BUCKET}" >/dev/null && echo "S3 bucket: ok"
fi

if [[ -n "${APP_RUNNER_SERVICE_ARN}" ]]; then
  aws apprunner describe-service --service-arn "${APP_RUNNER_SERVICE_ARN}" --region "${AWS_REGION}" \
    --query 'Service.{Status:Status,Url:ServiceUrl}' --output table
fi

echo
echo "Recent logs are in CloudWatch Logs. Check the App Runner service log group and the AgentCore runtime log group for permission or model access errors."
