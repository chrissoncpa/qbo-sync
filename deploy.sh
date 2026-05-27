#!/usr/bin/env bash
# One-line deploy of the qbo-sync service to Cloud Run.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (`gcloud auth login`)
#   - Project set: `gcloud config set project YOUR_GCP_PROJECT_ID`
#   - APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Secret Manager,
#                   Cloud Scheduler, Sheets, Drive
#   - Service account `qbo-bridge` exists with the roles listed in design doc §2.3
#
# Override defaults via env vars: REGION=us-east1 ./deploy.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-qbo-sync}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-qbo-bridge@${PROJECT_ID}.iam.gserviceaccount.com}"
ENVIRONMENT="${ENVIRONMENT:-sandbox}"

echo "Deploying ${SERVICE_NAME} to ${REGION} in ${PROJECT_ID} (env=${ENVIRONMENT})..."

gcloud run deploy "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --source=. \
    --service-account="${SERVICE_ACCOUNT}" \
    --no-allow-unauthenticated \
    --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},ENVIRONMENT=${ENVIRONMENT}" \
    --memory=512Mi \
    --cpu=1 \
    --concurrency=4 \
    --max-instances=2 \
    --min-instances=0 \
    --timeout=300

URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format='value(status.url)')

echo ""
echo "==> Service URL: ${URL}"
echo "==> Test:        curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${URL}/health"
echo ""
echo "Next: update your Intuit Developer app's redirect URI to:"
echo "      ${URL}/oauth/callback"
