#!/usr/bin/env bash
set -euo pipefail

yes="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      yes="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--yes]" >&2
      exit 2
      ;;
  esac
done

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID.}"
: "${REGION:=asia-northeast1}"
: "${SERVICE_NAME:=graphic-recording-agent-demo}"
: "${AGENT_RUNTIME_LOCATION:=us-central1}"
: "${GCS_BUCKET:=${PROJECT_ID}-graphic-recording-artifacts}"

cat <<EOF
This will delete workshop resources in project ${PROJECT_ID}:

- Cloud Run service: ${SERVICE_NAME} (${REGION})
- Cloud Storage bucket: gs://${GCS_BUCKET}
- Agent Runtime: ${AGENT_RUNTIME_RESOURCE_NAME:-not set; skipped}

This script does NOT delete the Google Cloud project.
EOF

if [[ "${yes}" != "true" && "${SKIP_CONFIRM:-}" != "yes" ]]; then
  echo
  read -r -p "Type 'delete' to confirm: " confirm
  if [[ "${confirm}" != "delete" ]]; then
    echo "Cleanup cancelled."
    exit 1
  fi
fi

echo
echo "Deleting Cloud Run service if it exists..."
gcloud run services delete "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --quiet >/dev/null 2>&1 || true

echo "Deleting Cloud Storage bucket if it exists..."
gcloud storage rm --recursive "gs://${GCS_BUCKET}" >/dev/null 2>&1 || true

if [[ -n "${AGENT_RUNTIME_RESOURCE_NAME:-}" ]]; then
  echo "Deleting Agent Runtime..."
  python3 - <<'PY'
import os
import vertexai

client = vertexai.Client(
    project=os.environ["PROJECT_ID"],
    location=os.environ.get("AGENT_RUNTIME_LOCATION", "us-central1"),
)
client.agent_engines.delete(
    name=os.environ["AGENT_RUNTIME_RESOURCE_NAME"],
    force=True,
)
print(f"Deleted {os.environ['AGENT_RUNTIME_RESOURCE_NAME']}")
PY
else
  echo "AGENT_RUNTIME_RESOURCE_NAME is not set; skipping Agent Runtime deletion."
fi

cat <<'EOF'

Cleanup completed.

If this was a disposable workshop project, delete the project separately from
Google Cloud Console or with:

  gcloud projects delete "${PROJECT_ID}"

Only delete the project if you are certain it contains no resources you need.
EOF
