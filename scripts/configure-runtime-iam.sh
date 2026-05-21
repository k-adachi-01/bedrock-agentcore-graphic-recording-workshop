#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID.}"
: "${GCS_BUCKET:?Set GCS_BUCKET to the artifact bucket name.}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
CLOUD_RUN_SA="${CLOUD_RUN_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

echo "Project: ${PROJECT_ID}"
echo "Project number: ${PROJECT_NUMBER}"
echo "Artifact bucket: gs://${GCS_BUCKET}"
echo "Signed URL signer service account: ${CLOUD_RUN_SA}"

echo "Creating or confirming Vertex AI service identity..."
gcloud beta services identity create \
  --service=aiplatform.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null || true

RUNTIME_IDENTITIES=(
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com"
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
)

if [[ -n "${AGENT_RUNTIME_EFFECTIVE_IDENTITY:-}" ]]; then
  RUNTIME_IDENTITIES+=("${AGENT_RUNTIME_EFFECTIVE_IDENTITY}")
fi

echo "Granting Cloud Run signer access to the artifact bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member "serviceAccount:${CLOUD_RUN_SA}" \
  --role "roles/storage.objectAdmin" \
  --quiet >/dev/null

for runtime_identity in "${RUNTIME_IDENTITIES[@]}"; do
  echo "Granting Runtime identity permissions: ${runtime_identity}"
  gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
    --member "serviceAccount:${runtime_identity}" \
    --role "roles/storage.objectAdmin" \
    --quiet >/dev/null || true

  gcloud iam service-accounts add-iam-policy-binding "${CLOUD_RUN_SA}" \
    --member "serviceAccount:${runtime_identity}" \
    --role "roles/iam.serviceAccountTokenCreator" \
    --quiet >/dev/null || true
done

echo "Runtime IAM configuration completed."
echo "Export these values before deploy:"
echo "export CLOUD_RUN_SA=\"${CLOUD_RUN_SA}\""
echo "export GCS_SIGNING_SERVICE_ACCOUNT=\"${CLOUD_RUN_SA}\""
