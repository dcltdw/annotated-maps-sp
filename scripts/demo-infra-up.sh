#!/usr/bin/env bash
# Phase 1/3 of the demo bring-up: infrastructure only (M4 spec §6).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TF_DIR=deploy/terraform/demo

for tool in terraform aws; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done

echo "==> terraform apply (infra: VPC, EKS, ECR, IRSA)"
terraform -chdir="$TF_DIR" apply -auto-approve -input=false
terraform -chdir="$TF_DIR" output
