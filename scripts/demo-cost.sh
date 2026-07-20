#!/usr/bin/env bash
# Month-to-date cost, per service. Fresh dedicated account => the account
# total IS the project total (cost-allocation tags lag ~24h and need console
# activation, so we don't filter by tag).
set -euo pipefail
REGION=us-east-1
START=$(date +%Y-%m-01)
END=$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)  # macOS/Linux
THRESHOLD=0.001

# The >THRESHOLD filter is applied downstream in awk, NOT in JMESPath. Cost
# Explorer returns Amount as a STRING, and awscli's JMESPath refuses
# `string > number` on newer builds ("'>' not supported between instances of
# 'str' and 'float'") where older awscli silently coerced — so a JMESPath
# `Amount > 0.001` filter breaks for the HAS-DATA case, exactly the case this
# tool exists to serve (issue #115). Fetch every service's amount as text and
# let awk's numeric context ($2+0) coerce it. The DataUnavailableException
# graceful path (NO-DATA case, added in PR #52) is preserved below.
# shellcheck disable=SC2016
if ! rows=$(aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region "$REGION" \
  --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output text 2>/tmp/demo-cost-err); then
  if grep -q "DataUnavailableException" /tmp/demo-cost-err; then
    echo "Cost Explorer has no data yet (new accounts ingest ~24h behind)."
    echo "Estimate from resource-hours instead: ~\$0.26/hr while the demo is up."
    exit 0
  fi
  cat /tmp/demo-cost-err >&2
  exit 1
fi

# amount<TAB>service for rows above the threshold, sorted by amount descending.
# awk's numeric context ($2 + 0) coerces the string Amount without a type error.
table=$(printf '%s\n' "$rows" \
  | awk -F'\t' -v t="$THRESHOLD" '($2 + 0) > t { printf "%.4f\t%s\n", $2, $1 }' \
  | sort -rn)

if [ -n "$table" ]; then
  echo "Month-to-date cost by service (> \$$THRESHOLD), $START to today:"
  printf '%s\n' "$table" | awk -F'\t' '{ printf "  %-45s $%s\n", $2, $1 }'
else
  echo "No service above \$$THRESHOLD month-to-date (since $START)."
  echo "Estimate from resource-hours instead: ~\$0.26/hr while the demo is up."
fi
