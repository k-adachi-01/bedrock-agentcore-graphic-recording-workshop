#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${S3_BUCKET:=}"
: "${AGENTCORE_RUNTIME_ARN:=}"
: "${ECS_SERVICE_NAME:=}"

echo "=== SUMMARY ==="
aws sts get-caller-identity --query 'Arn' --output text
echo "Region: ${AWS_REGION}"
echo "AgentCore Runtime ARN: ${AGENTCORE_RUNTIME_ARN:-not set}"
echo "S3 bucket: ${S3_BUCKET:-not set}"
echo "ECS Express service: ${ECS_SERVICE_NAME:-not set}"

if [[ -n "${S3_BUCKET}" ]]; then
  echo ""
  echo "=== S3 Bucket ==="
  aws s3api head-bucket --bucket "${S3_BUCKET}" >/dev/null && echo "S3 bucket: ok"
fi

if [[ -n "${ECS_SERVICE_NAME}" ]]; then
  echo ""
  echo "=== ECS Express Service ==="
  SERVICE_JSON=$(aws ecs describe-services \
    --cluster express \
    --services "${ECS_SERVICE_NAME}" \
    --region "${AWS_REGION}" 2>/dev/null || echo '{"services":[{}]}')

  echo "Status: $(echo "${SERVICE_JSON}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['services'][0].get('status','unknown'))" 2>/dev/null || echo "unknown")"
  echo "Default URL: $(echo "${SERVICE_JSON}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['services'][0].get('networkConfiguration',{}).get('defaultEndpoint','not available'))" 2>/dev/null || echo "not available")"
fi

echo ""
echo "=== Logs ==="
echo "ECS task logs are in CloudWatch Logs. Find the log group with:"
echo "  aws logs describe-log-groups --region ${AWS_REGION} --log-group-name-pattern '/ecs/${ECS_SERVICE_NAME}' --query 'logGroups[].logGroupName' --output text"
echo ""
echo "AgentCore Runtime logs are in the log group configured during AgentCore deploy."
echo ""
echo "=== Health Check ==="
if [[ -n "${ECS_SERVICE_NAME}" ]]; then
  echo "Check the ALB target group health via:"
  echo "  aws ecs describe-services --cluster express --services ${ECS_SERVICE_NAME} --region ${AWS_REGION} --query 'services[0].loadBalancers[0].targetGroupArn' --output text"
fi
