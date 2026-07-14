#!/usr/bin/env bash
# Tear the demo environment down to zero. SAFE TO RUN REPEATEDLY from any
# half-failed state: every step tolerates already-gone resources. The
# ordering is the point — the ALB is created out-of-band by the in-cluster
# controller, and terraform destroy HANGS if it still exists (M3 spec §5).
set -uo pipefail   # deliberately NOT -e: teardown continues past failures

cd "$(git rev-parse --show-toplevel)" || exit 1
TF_DIR=deploy/terraform/demo

REGION=$(terraform -chdir="$TF_DIR" output -raw region 2>/dev/null || echo "us-east-1")
CLUSTER=$(terraform -chdir="$TF_DIR" output -raw cluster_name 2>/dev/null || echo "annotated-maps-demo")

if aws eks describe-cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1 || true

  echo "==> uninstall the app (controller then deletes its ALB)"
  helm uninstall annotated-maps -n annotated-maps --wait --timeout 5m || true

  echo "==> waiting for the controller-created ALB to actually delete"
  # Fresh dedicated account: ANY load balancer in the region is ours.
  for _ in $(seq 1 60); do
    COUNT=$(aws elbv2 describe-load-balancers --region "$REGION" \
      --query "length(LoadBalancers)" --output text 2>/dev/null)
    rc=$?
    # Only treat a SUCCESSFUL, empty result as "gone". An API error (rc!=0)
    # must NOT be read as zero — that would destroy the VPC out from under a
    # still-present ALB and hang. On error, keep waiting.
    if [ "$rc" -eq 0 ] && [ "$COUNT" = "0" ]; then break; fi
    sleep 10
  done

  echo "==> uninstall the controller"
  helm uninstall aws-load-balancer-controller -n kube-system --wait --timeout 5m || true
else
  echo "==> cluster not reachable/gone — straight to terraform destroy"
fi

echo "==> terraform destroy"
terraform -chdir="$TF_DIR" destroy -auto-approve

if [ -n "${NEON_BRANCH:-}" ]; then
  echo "==> deleting the per-run Neon branch ($NEON_BRANCH)"
  ./scripts/neon-branch.sh delete "$NEON_BRANCH" || true
fi

echo "==> post-destroy sweep (all three MUST be empty)"
echo "state:";        terraform -chdir="$TF_DIR" state list 2>/dev/null || true
echo "load balancers:"; aws elbv2 describe-load-balancers --region "$REGION" \
  --query 'LoadBalancers[].LoadBalancerName' --output text 2>/dev/null || true
echo "nat gateways:"; aws ec2 describe-nat-gateways --region "$REGION" \
  --filter Name=state,Values=available,pending \
  --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null || true
echo "eks clusters:"; aws eks list-clusters --region "$REGION" \
  --query 'clusters' --output text 2>/dev/null || true
echo
echo "  If any line above is non-empty, RE-RUN make demo-down; if it persists,"
echo "  see docs/aws-primer.md troubleshooting (orphaned-ALB entry)."
