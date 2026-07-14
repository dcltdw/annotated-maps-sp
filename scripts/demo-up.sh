#!/usr/bin/env bash
# Bring up the AWS demo environment end-to-end (M3 spec §5).
# Terraform owns infrastructure; this script sequences the rest.
# COST: ~$0.20/hr while up. demo-down when done — never leave it running.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo
CHART=deploy/helm/annotated-maps

for tool in terraform aws helm docker kubectl; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

echo "==> terraform apply (infra: VPC, EKS, ECR, IAM, budgets)"
terraform -chdir="$TF_DIR" apply -auto-approve

REGION=$(terraform -chdir="$TF_DIR" output -raw region)
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name)
VPC_ID=$(terraform -chdir="$TF_DIR" output -raw vpc_id)
ECR_API=$(terraform -chdir="$TF_DIR" output -raw ecr_api_url)
ECR_WEB=$(terraform -chdir="$TF_DIR" output -raw ecr_web_url)
IRSA_ARN=$(terraform -chdir="$TF_DIR" output -raw alb_controller_role_arn)

echo "==> kubeconfig"
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"

echo "==> aws-load-balancer-controller (IRSA: $IRSA_ARN)"
helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm repo update eks >/dev/null
# Pinned to chart 1.17.1 (appVersion v2.17.1) to match the IAM policy Task 3
# vendored at v2.17.1 (deliberately v2, not v3 — our Ingress use case, lower
# PR-2 risk). The unpinned chart would pull v3.x and mismatch the policy.
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

echo "==> build + push images (explicit linux/amd64 — t3 nodes are amd64)"
TAG=$(git rev-parse --short HEAD)
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ECR_API%%/*}"
docker build --platform linux/amd64 -f backend/Dockerfile -t "$ECR_API:$TAG" .
docker build --platform linux/amd64 -f frontend/Dockerfile -t "$ECR_WEB:$TAG" frontend
docker push "$ECR_API:$TAG"
docker push "$ECR_WEB:$TAG"

echo "==> app secrets (never stored; Neon demo-branch URL + generated key)"
# The Neon URL is a secret. Provide it either interactively (prompt) or, for
# non-interactive/automated runs, via a file whose PATH is passed as
# DB_URL_FILE — so it isn't typed into the terminal or captured in shell
# history. (It is still handed to helm below via --set, so it is briefly
# visible in the process table; tightening that to --set-file is tracked as a
# follow-up.)
if [ -n "${DB_URL_FILE:-}" ] && [ -f "$DB_URL_FILE" ]; then
  DATABASE_URL=$(tr -d '[:space:]' < "$DB_URL_FILE")
  echo "    (DATABASE_URL read from \$DB_URL_FILE)"
else
  read -r -s -p "Neon demo-branch DATABASE_URL (postgis://...): " DATABASE_URL; echo
fi
DJANGO_SECRET_KEY=$(openssl rand -hex 32)

echo "==> deploy the chart"
helm upgrade --install annotated-maps "$CHART" \
  -n annotated-maps --create-namespace \
  -f "$CHART/values-demo.yaml" \
  --set image.api.repository="$ECR_API" \
  --set image.api.tag="$TAG" \
  --set image.web.repository="$ECR_WEB" \
  --set image.web.tag="$TAG" \
  --set secrets.databaseUrl="$DATABASE_URL" \
  --set secrets.djangoSecretKey="$DJANGO_SECRET_KEY" \
  --wait --timeout 10m

echo "==> waiting for the ALB hostname"
ALB=""
for _ in $(seq 1 60); do
  ALB=$(kubectl -n annotated-maps get ingress annotated-maps \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  [ -n "$ALB" ] && break
  sleep 10
done
[ -n "$ALB" ] || { echo "ALB hostname never appeared — check the controller logs" >&2; exit 1; }

echo "==> smoke (ALB targets take a minute to pass health checks)"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 10 "http://$ALB/api/v1/health" >/dev/null 2>&1; then
    echo "health OK"
    break
  fi
  sleep 10
done
curl -fsS --max-time 10 "http://$ALB/" | grep -qi "<!doctype html" && echo "web OK"

echo
echo "  Demo is UP:  http://$ALB/"
echo "  THE METER IS RUNNING (~\$0.20/hr). Tear down with: make demo-down"
