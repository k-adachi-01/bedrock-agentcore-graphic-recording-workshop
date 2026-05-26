#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${AWS_DEFAULT_REGION:=${AWS_REGION}}"
: "${ECS_SERVICE_NAME:=graphic-recording-agent-demo}"
: "${ECR_REPO_NAME:=graphic-recording-agent-demo}"
: "${APP_PASSWORD:?Set APP_PASSWORD for the web login.}"
: "${APP_SECRET_KEY:?Set APP_SECRET_KEY for signed auth cookies.}"
: "${APP_LOG_FORMAT:=json}"
: "${AGENT_BACKEND:=runtime}"
: "${AGENTCORE_RUNTIME_ARN:?Set AGENTCORE_RUNTIME_ARN after deploying AgentCore Runtime.}"
: "${S3_BUCKET:?Set S3_BUCKET to the artifact bucket name.}"
: "${BEDROCK_TEXT_MODEL_ID:=us.anthropic.claude-sonnet-4-20250514-v1:0}"
: "${S3_ARTIFACT_PREFIX:=artifacts}"
: "${S3_PRESIGNED_URL_TTL_SECONDS:=28800}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

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

echo "=== 1/5: Ensuring ECR repository ==="
aws ecr create-repository --repository-name "${ECR_REPO_NAME}" --region "${AWS_REGION}" 2>/dev/null \
  && echo "Created repository ${ECR_REPO_NAME}" \
  || echo "Repository ${ECR_REPO_NAME} already exists"

echo "=== 2/5: Logging in to ECR ==="
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "=== 3/5: Building and pushing Docker image ==="
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
docker build -t "${ECR_REPO_NAME}:latest" "${SCRIPT_DIR}"
docker tag "${ECR_REPO_NAME}:latest" "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"
echo "Pushed ${ECR_URI}:latest"

echo "=== 4/5: Ensuring ECS Express IAM roles ==="
ensure_role() {
  local role_name="$1"
  local managed_policy_arn="${2:-}"
  if ! aws iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
    aws iam create-role \
      --role-name "${role_name}" \
      --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
          "Effect": "Allow",
          "Principal": { "Service": "ecs.amazonaws.com" },
          "Action": "sts:AssumeRole"
        }]
      }' >/dev/null
    echo "Created role ${role_name}"
    if [[ -n "${managed_policy_arn}" ]]; then
      aws iam attach-role-policy --role-name "${role_name}" --policy-arn "${managed_policy_arn}"
    fi
  else
    echo "Role ${role_name} already exists"
  fi
}

ensure_role "ecsTaskExecutionRole" \
  "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"

ensure_role "ecsInfrastructureRoleForExpressServices" \
  "arn:aws:iam::aws:policy/AmazonECSInfrastructureRolePolicyForExpressService"

echo "=== 5/5: Creating ECS Express Mode service ==="
PRIMARY_CONTAINER_JSON=$(python3 -c "
import json
env = [
  {'name': 'APP_ENV', 'value': 'production'},
  {'name': 'APP_PASSWORD', 'value': '${APP_PASSWORD}'},
  {'name': 'APP_SECRET_KEY', 'value': '${APP_SECRET_KEY}'},
  {'name': 'APP_LOG_FORMAT', 'value': '${APP_LOG_FORMAT}'},
  {'name': 'MOCK_MODE', 'value': 'false'},
  {'name': 'AGENT_BACKEND', 'value': '${AGENT_BACKEND}'},
  {'name': 'AGENTCORE_RUNTIME_ARN', 'value': '${AGENTCORE_RUNTIME_ARN}'},
  {'name': 'AWS_REGION', 'value': '${AWS_REGION}'},
  {'name': 'AWS_DEFAULT_REGION', 'value': '${AWS_DEFAULT_REGION}'},
  {'name': 'BEDROCK_TEXT_MODEL_ID', 'value': '${BEDROCK_TEXT_MODEL_ID}'},
  {'name': 'S3_BUCKET', 'value': '${S3_BUCKET}'},
  {'name': 'S3_ARTIFACT_PREFIX', 'value': '${S3_ARTIFACT_PREFIX}'},
  {'name': 'S3_PRESIGNED_URL_TTL_SECONDS', 'value': '${S3_PRESIGNED_URL_TTL_SECONDS}'},
]
image_model = '${BEDROCK_IMAGE_MODEL_ID:-}'
if image_model:
  env.append({'name': 'BEDROCK_IMAGE_MODEL_ID', 'value': image_model})
print(json.dumps({
  'image': '${ECR_URI}:latest',
  'containerPort': 8080,
  'environment': env
}))
")

aws ecs create-express-gateway-service \
  --service-name "${ECS_SERVICE_NAME}" \
  --execution-role-arn "arn:aws:iam::${ACCOUNT_ID}:role/ecsTaskExecutionRole" \
  --infrastructure-role-arn "arn:aws:iam::${ACCOUNT_ID}:role/ecsInfrastructureRoleForExpressServices" \
  --primary-container "${PRIMARY_CONTAINER_JSON}" \
  --health-check-path "/healthz" \
  --scaling-target "{\"minTaskCount\":1,\"maxTaskCount\":4}" \
  --monitor-resources \
  --region "${AWS_REGION}"

echo ""
echo "=== Deployment submitted ==="
echo "Provisioning takes 3-5 minutes. Check status:"
echo "  aws ecs describe-services --cluster express --services ${ECS_SERVICE_NAME} --region ${AWS_REGION} --query 'services[0].status'"
echo ""
echo "Once RUNNING/ACTIVE, get the default URL:"
echo "  aws ecs describe-services --cluster express --services ${ECS_SERVICE_NAME} --region ${AWS_REGION} --query 'services[0].networkConfiguration.defaultEndpoint' --output text"
echo ""
echo "Open that URL in a browser and log in with APP_PASSWORD."
echo ""
echo "To allow the ECS task to invoke AgentCore Runtime, attach a policy with bedrock-agentcore:InvokeAgentRuntime to ecsTaskExecutionRole:"
echo "  aws iam put-role-policy --role-name ecsTaskExecutionRole --policy-name InvokeAgentCore --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"bedrock-agentcore:InvokeAgentRuntime\",\"Resource\":\"${AGENTCORE_RUNTIME_ARN}\"}]}'"
