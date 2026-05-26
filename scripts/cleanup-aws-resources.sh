#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${S3_BUCKET:=}"
: "${APP_RUNNER_SERVICE_ARN:=}"

if [[ -n "${APP_RUNNER_SERVICE_ARN}" ]]; then
  echo "Deleting App Runner service: ${APP_RUNNER_SERVICE_ARN}"
  aws apprunner delete-service --service-arn "${APP_RUNNER_SERVICE_ARN}" --region "${AWS_REGION}"
else
  echo "APP_RUNNER_SERVICE_ARN is not set; skipping App Runner deletion."
fi

if [[ -n "${S3_BUCKET}" ]]; then
  echo "Emptying artifact bucket: s3://${S3_BUCKET}"
  aws s3 rm "s3://${S3_BUCKET}" --recursive || true
  echo "Delete the bucket manually if it was created only for this workshop:"
  echo "aws s3 rb s3://${S3_BUCKET}"
else
  echo "S3_BUCKET is not set; skipping artifact cleanup."
fi

echo "Delete the AgentCore Runtime from the AgentCore console or with the AgentCore CLI if it was created only for this workshop."
