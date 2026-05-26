#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${S3_BUCKET:?Set S3_BUCKET to the artifact bucket name.}"

section() {
  printf "\n== %s ==\n" "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

section "Commands"
require_command aws
require_command docker
require_command uv
require_command pnpm

section "AWS identity"
aws sts get-caller-identity

section "Bedrock access"
aws bedrock list-foundation-models --region "${AWS_REGION}" --max-results 5 >/dev/null
echo "Bedrock API is reachable in ${AWS_REGION}."

section "S3 bucket"
if aws s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null; then
  echo "S3 bucket exists: s3://${S3_BUCKET}"
else
  echo "Create the bucket before deploy: aws s3 mb s3://${S3_BUCKET} --region ${AWS_REGION}" >&2
  exit 1
fi

section "Exports"
echo "export AWS_REGION=\"${AWS_REGION}\""
echo "export S3_BUCKET=\"${S3_BUCKET}\""
echo "export S3_ARTIFACT_PREFIX=\"${S3_ARTIFACT_PREFIX:-artifacts}\""
