#!/usr/bin/env bash
# Month-to-date cost, per service. Fresh dedicated account => the account
# total IS the project total (cost-allocation tags lag ~24h and need console
# activation, so we don't filter by tag).
set -euo pipefail
REGION=us-east-1
START=$(date +%Y-%m-01)
END=$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)  # macOS/Linux
# JMESPath query below, not shell expansion.
# shellcheck disable=SC2016
aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region "$REGION" \
  --query 'ResultsByTime[0].Groups[?Metrics.UnblendedCost.Amount>`0.001`].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output table
