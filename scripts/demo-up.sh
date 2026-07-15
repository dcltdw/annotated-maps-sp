#!/usr/bin/env bash
# Bring up the AWS demo environment end-to-end — chains the three phases.
# The CI pipeline runs the same phases as separate jobs (M4 spec §3/§6).
# COST: ~$0.20/hr while up. demo-down when done — never leave it running.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
./scripts/demo-infra-up.sh
./scripts/demo-images.sh
./scripts/demo-app-deploy.sh
