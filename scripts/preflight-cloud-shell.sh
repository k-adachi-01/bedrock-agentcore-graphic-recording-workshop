#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID.}"
: "${REGION:=asia-northeast1}"
: "${AGENT_RUNTIME_LOCATION:=us-central1}"
: "${GCS_BUCKET:=${PROJECT_ID}-graphic-recording-artifacts}"

failures=0

pass() {
  echo "[OK] $*"
}

warn() {
  echo "[WARN] $*" >&2
}

fail() {
  echo "[NG] $*" >&2
  failures=$((failures + 1))
}

section() {
  echo
  echo "== $* =="
}

require_command() {
  local command_name="$1"
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "${command_name} is available"
  else
    fail "${command_name} is not available"
  fi
}

section "Cloud Shell preflight"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Agent Runtime location: ${AGENT_RUNTIME_LOCATION}"
echo "Artifact bucket: gs://${GCS_BUCKET}"

section "Local tools"
require_command gcloud
require_command python3

if command -v python3 >/dev/null 2>&1; then
  if python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
  then
    pass "python3 is 3.10 or newer: $(python3 --version)"
  else
    fail "python3 must be 3.10 or newer. Current: $(python3 --version 2>&1)"
  fi

  if python3 -m venv --help >/dev/null 2>&1; then
    pass "python3 venv module is available"
  else
    fail "python3 venv module is not available. Cloud Shell should include it; restart Cloud Shell or ask workshop staff."
  fi
fi

section "Google Cloud auth"
if gcloud config set project "${PROJECT_ID}" >/dev/null; then
  pass "gcloud project is set"
else
  fail "Could not set gcloud project to ${PROJECT_ID}"
fi

active_account="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null | head -n 1 || true)"
if [[ -n "${active_account}" ]]; then
  pass "active gcloud account: ${active_account}"
else
  fail "No active gcloud account. Run: gcloud auth login"
fi

if gcloud auth application-default print-access-token >/dev/null 2>&1; then
  pass "Application Default Credentials are available"
else
  fail "ADC is missing. Run: gcloud auth application-default login"
fi

if gcloud auth application-default set-quota-project "${PROJECT_ID}" >/dev/null 2>&1; then
  pass "ADC quota project is set"
else
  warn "Could not set ADC quota project automatically. If Gemini calls fail, rerun: gcloud auth application-default set-quota-project \"${PROJECT_ID}\""
fi

section "Project and billing"
if project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null)"; then
  pass "project is accessible: ${project_number}"
else
  fail "Project is not accessible or does not exist: ${PROJECT_ID}"
  project_number=""
fi

gcloud services enable cloudbilling.googleapis.com --project="${PROJECT_ID}" >/dev/null 2>&1 || true
if billing_enabled="$(gcloud beta billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)' 2>/dev/null)"; then
  if [[ "${billing_enabled}" == "True" || "${billing_enabled}" == "true" ]]; then
    pass "billing is enabled"
  else
    fail "billing is not enabled. Link a billing account in Google Cloud Console."
  fi
else
  fail "could not check billing. Confirm billing in Google Cloud Console."
fi

section "Derived values"
if [[ -n "${project_number}" ]]; then
  cloud_run_sa="${project_number}-compute@developer.gserviceaccount.com"
  echo "export PROJECT_NUMBER=\"${project_number}\""
  echo "export CLOUD_RUN_SA=\"${cloud_run_sa}\""
  echo "export GCS_SIGNING_SERVICE_ACCOUNT=\"${cloud_run_sa}\""
fi
echo "export GCS_BUCKET=\"${GCS_BUCKET}\""
echo "export AGENT_RUNTIME_STAGING_BUCKET=\"${GCS_BUCKET}\""

section "Required APIs"
required_apis=(
  serviceusage.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  compute.googleapis.com
  logging.googleapis.com
  run.googleapis.com
  cloudbuild.googleapis.com
  artifactregistry.googleapis.com
  aiplatform.googleapis.com
  storage.googleapis.com
)

enabled_apis="$(gcloud services list --enabled --format='value(config.name)' 2>/dev/null || true)"
for api in "${required_apis[@]}"; do
  if grep -qx "${api}" <<<"${enabled_apis}"; then
    pass "${api}"
  else
    echo "[INFO] ${api} is not enabled yet; bootstrap will enable it."
  fi
done

if (( failures > 0 )); then
  echo
  echo "Preflight failed with ${failures} issue(s). Fix the [NG] items above, then rerun:"
  echo
  echo "  ./scripts/preflight-cloud-shell.sh"
  exit 1
fi

cat <<'EOF'

==================================================
Preflight passed. Next step:

  ./scripts/bootstrap-gcp-project.sh

After bootstrap, continue from "Phase 1: workshop main flow" in docs/workshop-deploy.md.
==================================================
EOF
