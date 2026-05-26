#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${S3_BUCKET:=}"
: "${ECS_SERVICE_NAME:=}"
: "${ECR_REPO_NAME:=}"

if [[ -n "${ECS_SERVICE_NAME}" ]]; then
  echo "Deleting ECS Express service: ${ECS_SERVICE_NAME}"
  aws ecs delete-service \
    --cluster express \
    --service "${ECS_SERVICE_NAME}" \
    --force \
    --region "${AWS_REGION}" 2>/dev/null || true
  echo "Service deletion initiated. The ALB and CloudWatch Logs will be cleaned up automatically."
else
  echo "ECS_SERVICE_NAME is not set; skipping ECS service deletion."
fi

if [[ -n "${ECR_REPO_NAME}" ]]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
  if [[ -n "${ACCOUNT_ID}" ]]; then
    echo "Deleting ECR repository: ${ECR_REPO_NAME}"
    aws ecr delete-repository \
      --repository-name "${ECR_REPO_NAME}" \
      --region "${AWS_REGION}" \
      --force 2>/dev/null || true
  fi
else
  echo "ECR_REPO_NAME is not set; skipping ECR repository deletion."
fi

if [[ -n "${S3_BUCKET}" ]]; then
  echo "Emptying artifact bucket: s3://${S3_BUCKET}"
  aws s3 rm "s3://${S3_BUCKET}" --recursive || true
  echo "Delete the bucket manually if it was created only for this workshop:"
  echo "aws s3 rb s3://${S3_BUCKET} --force"
else
  echo "S3_BUCKET is not set; skipping artifact cleanup."
fi

echo "Delete the AgentCore Runtime from the AgentCore console or with the AgentCore CLI if it was created only for this workshop."
echo ""
echo "If you created a custom IAM policy for InvokeAgentCore, remove it with:"
echo "  aws iam delete-role-policy --role-name ecsTaskExecutionRole --policy-name InvokeAgentCore"
