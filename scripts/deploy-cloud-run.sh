#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID.}"
: "${REGION:=asia-northeast1}"
: "${SERVICE_NAME:=graphic-recording-agent-demo}"
: "${APP_PASSWORD:?Set APP_PASSWORD to the demo login password.}"
: "${APP_SECRET_KEY:?Set APP_SECRET_KEY to a long random value.}"
: "${AGENT_BACKEND:=local}"
: "${GEMINI_TEXT_MODEL:=gemini-3.5-flash}"
: "${GEMINI_IMAGE_MODEL:=gemini-3-pro-image-preview}"
: "${GOOGLE_CLOUD_LOCATION:=global}"
: "${ARTICLE_FETCH_MAX_BYTES:=2000000}"
: "${LOG_LEVEL:=INFO}"
: "${GCS_SIGNED_URL_TTL_SECONDS:=28800}"

ENV_VARS="APP_ENV=production,APP_PASSWORD=${APP_PASSWORD},APP_SECRET_KEY=${APP_SECRET_KEY},APP_LOG_FORMAT=json,LOG_LEVEL=${LOG_LEVEL},MOCK_MODE=false,AGENT_BACKEND=${AGENT_BACKEND},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION},GEMINI_TEXT_MODEL=${GEMINI_TEXT_MODEL},GEMINI_IMAGE_MODEL=${GEMINI_IMAGE_MODEL},ARTICLE_FETCH_MAX_BYTES=${ARTICLE_FETCH_MAX_BYTES},GCS_SIGNED_URL_TTL_SECONDS=${GCS_SIGNED_URL_TTL_SECONDS}"

if [[ -n "${AGENT_RUNTIME_RESOURCE_NAME:-}" ]]; then
  ENV_VARS="${ENV_VARS},AGENT_RUNTIME_RESOURCE_NAME=${AGENT_RUNTIME_RESOURCE_NAME},AGENT_RUNTIME_LOCATION=${AGENT_RUNTIME_LOCATION:-us-central1}"
fi

if [[ -n "${GCS_BUCKET:-}" ]]; then
  ENV_VARS="${ENV_VARS},GCS_BUCKET=${GCS_BUCKET},GCS_ARTIFACT_PREFIX=${GCS_ARTIFACT_PREFIX:-artifacts}"
fi

if [[ -n "${GCS_SIGNING_SERVICE_ACCOUNT:-}" ]]; then
  ENV_VARS="${ENV_VARS},GCS_SIGNING_SERVICE_ACCOUNT=${GCS_SIGNING_SERVICE_ACCOUNT}"
fi

gcloud config set project "${PROJECT_ID}"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --max-instances 1 \
  --no-cpu-throttling \
  --startup-probe "httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=2,periodSeconds=10,failureThreshold=3" \
  --liveness-probe "httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=2,periodSeconds=30,failureThreshold=3" \
  --set-env-vars "${ENV_VARS}"
