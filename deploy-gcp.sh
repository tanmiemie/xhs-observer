#!/usr/bin/env bash
set -euo pipefail
project_id="${1:?Usage: ./deploy-gcp.sh PROJECT_ID BUCKET_NAME [REGION]}"
bucket_name="${2:?Supply a globally unique bucket name}"
region="${3:-us-central1}"
job_name="xhs-observer-process"
service_name="xhs-observer-worker"
service_email="${service_name}@${project_id}.iam.gserviceaccount.com"
repo_name="xhs-observer"
image="${region}-docker.pkg.dev/${project_id}/${repo_name}/worker:latest"

gcloud services enable storage.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project="$project_id"
if ! gcloud storage buckets describe "gs://${bucket_name}" --project="$project_id" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${bucket_name}" --project="$project_id" --location="$region" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "gs://${bucket_name}" --versioning --public-access-prevention
if ! gcloud iam service-accounts describe "$service_email" --project="$project_id" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$service_name" --project="$project_id" --display-name="XHS Observer processing worker"
fi
gcloud storage buckets add-iam-policy-binding "gs://${bucket_name}" --member="serviceAccount:${service_email}" --role=roles/storage.objectAdmin
if ! gcloud artifacts repositories describe "$repo_name" --project="$project_id" --location="$region" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$repo_name" --project="$project_id" --location="$region" --repository-format=docker
fi
gcloud builds submit . --project="$project_id" --tag="$image" --gcs-source-staging-dir="gs://${bucket_name}/build-source"
gcloud run jobs deploy "$job_name" --project="$project_id" --region="$region" --image="$image" --service-account="$service_email" --tasks=1 --max-retries=2 --task-timeout=15m --set-env-vars="GOOGLE_CLOUD_PROJECT=${project_id},XHS_GCS_BUCKET=${bucket_name}"
printf '\nDeployed private processing job. Upload a completed batch, then execute:\n'
printf 'gcloud run jobs execute %s --project=%s --region=%s --wait\n' "$job_name" "$project_id" "$region"
