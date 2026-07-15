#!/usr/bin/env bash
# Phase 3/3: ALB controller + the app chart + a smoke test that GATES.
# Secrets flow via --set-file (never process args). Smoke failure exits 1 —
# "Demo is UP" is printed only when it actually is (M4 hardening).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo
CHART=deploy/helm/annotated-maps

for tool in terraform aws helm kubectl curl; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name)
VPC_ID=$(terraform -chdir="$TF_DIR" output -raw vpc_id)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
IRSA_ARN=$(terraform -chdir="$TF_DIR" output -raw alb_controller_role_arn)
TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD)}

echo "==> kubeconfig"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"

echo "==> aws-load-balancer-controller (IRSA: $IRSA_ARN)"
helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm repo update eks >/dev/null
# Chart 1.17.1 (appVersion v2.17.1) matches the vendored IAM policy — see
# deploy/terraform/demo/iam-irsa.tf. Unpinned would pull v3.x and mismatch.
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --version 1.17.1 \
  -n kube-system \
  --set clusterName="$CLUSTER" \
  --set region="$REGION" \
  --set vpcId="$VPC_ID" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=$IRSA_ARN" \
  --wait --timeout 5m

echo "==> app secrets (never stored, never on a command line)"
SECRETS_DIR=$(mktemp -d)
trap 'rm -rf "$SECRETS_DIR"' EXIT
if [ -n "${DB_URL_FILE:-}" ] && [ -f "$DB_URL_FILE" ]; then
  tr -d '[:space:]' < "$DB_URL_FILE" > "$SECRETS_DIR/db"
  echo "    (DATABASE_URL read from \$DB_URL_FILE)"
else
  read -r -s -p "Neon demo-branch DATABASE_URL (postgis://...): " DATABASE_URL; echo
  printf '%s' "$DATABASE_URL" > "$SECRETS_DIR/db"
fi
openssl rand -hex 32 > "$SECRETS_DIR/key"

echo "==> deploy the chart (tag $TAG)"
helm upgrade --install annotated-maps "$CHART" \
  -n annotated-maps --create-namespace \
  -f "$CHART/values-demo.yaml" \
  --set image.api.repository="$ECR_API" \
  --set image.api.tag="$TAG" \
  --set image.web.repository="$ECR_WEB" \
  --set image.web.tag="$TAG" \
  --set-file secrets.databaseUrl="$SECRETS_DIR/db" \
  --set-file secrets.djangoSecretKey="$SECRETS_DIR/key" \
  --wait --timeout 10m

echo "==> waiting for the ALB hostname"
ALB=""
for _ in $(seq 1 60); do
  ALB=$(kubectl -n annotated-maps get ingress annotated-maps \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  [ -n "$ALB" ] && break
  sleep 10
done
[ -n "$ALB" ] || { echo "FAIL: ALB hostname never appeared" >&2; exit 1; }

echo "==> smoke (GATES: exits 1 unless the app actually serves)"
HEALTH_OK=""
for _ in $(seq 1 30); do
  if curl -fsS --max-time 10 "http://$ALB/api/v1/health" >/dev/null 2>&1; then
    HEALTH_OK=1; echo "health OK"; break
  fi
  sleep 10
done
[ -n "$HEALTH_OK" ] || { echo "FAIL: health never returned 200 via the ALB" >&2; exit 1; }
curl -fsS --max-time 10 "http://$ALB/" | grep -qi "<!doctype html" \
  || { echo "FAIL: web root did not serve the SPA" >&2; exit 1; }
echo "web OK"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "alb_url=http://$ALB" >> "$GITHUB_OUTPUT"
fi
echo
echo "  Demo is UP:  http://$ALB/"
echo "  THE METER IS RUNNING (~\$0.20/hr). Tear down with: make demo-down"
