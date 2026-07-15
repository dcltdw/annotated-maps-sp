#!/usr/bin/env bash
# Phase 2/3: build and push the app images to ECR (linux/amd64 — t3 nodes).
# IMAGE_TAG env overrides the default git-SHA tag (CI passes the run's SHA).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo

for tool in terraform aws docker; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD)}

echo "==> docker login (ECR)"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ECR_API%%/*}"

echo "==> build (explicit linux/amd64) + push, tag $TAG"
docker build --platform linux/amd64 -f backend/Dockerfile -t "$ECR_API:$TAG" .
docker build --platform linux/amd64 -f frontend/Dockerfile -t "$ECR_WEB:$TAG" frontend
docker push "$ECR_API:$TAG"
docker push "$ECR_WEB:$TAG"
