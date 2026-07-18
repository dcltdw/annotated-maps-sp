<!-- doc-status: living -->

# SLOs

Service-level objectives for the Annotated Maps API, the recording rules and
burn alerts that guard them, and the runbook to follow when a burn alert
pages. Alert rules live in
[`deploy/helm/annotated-maps/files/prometheus-rules.yaml`](../deploy/helm/annotated-maps/files/prometheus-rules.yaml)
and are proven with promtool unit tests in
[`deploy/observability/alert-tests/rules_test.yaml`](../deploy/observability/alert-tests/rules_test.yaml)
(`make obs-checks`). The PromQL below MUST match that rules file exactly.

## Availability

**SLO:** 99.5% of API responses are non-5xx over a rolling 30-day window.

Recording rule (`am:http_error_ratio:rate5m`):

```promql
sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[5m]))
/
sum(rate(django_http_responses_total_by_status_total[5m]))
```

**Guarding alert:** `ApiAvailabilityBurn` fires when
`am:http_error_ratio:rate5m > 0.005` for 10 minutes (`severity: page`).

**Error budget:** 100% − 99.5% = 0.5% of requests may fail. Over a 30-day
window (30 × 24 h = 720 h), that budget is 720 h × 0.005 ≈ 3.6 h of
full-outage-equivalent downtime (or a proportionally larger amount of
partial-error time).

### Runbook — Availability {#availability}

1. `kubectl -n annotated-maps get pods` — confirm the API pods are Running
   and not crash-looping.
2. `kubectl -n annotated-maps logs deploy/annotated-maps-api --tail=100` —
   look for the stack traces or 5xx responses driving the error rate.
3. Open the `api-overview` dashboard
   (`deploy/helm/annotated-maps/files/dashboards/api-overview.json`) and
   check the "Error ratio (SLO burn)" and "Request rate" panels to see
   whether the spike is broad or isolated.

   Also check recent deploys: `helm -n annotated-maps history annotated-maps`
   — a burn that started right after a rollout points at the new release.

## Latency

**SLO:** 99% of API requests complete in under 500 ms over a rolling 30-day
window.

Recording rule (`am:http_fast_ratio:rate5m`):

```promql
sum(rate(django_http_requests_latency_seconds_by_view_method_bucket{le="0.5"}[5m]))
/
sum(rate(django_http_requests_latency_seconds_by_view_method_count[5m]))
```

**Guarding alert:** `ApiLatencyBurn` fires when
`am:http_fast_ratio:rate5m < 0.99` for 10 minutes (`severity: page`).

**Error budget:** 100% − 99% = 1% of requests may be slow (≥ 500 ms). Over a
30-day window (720 h), that budget is 720 h × 0.01 ≈ 7.2 h of
all-requests-slow-equivalent time.

### Runbook — Latency {#latency}

1. `kubectl -n annotated-maps get pods` — confirm the API pods are Running
   and not under CPU/memory pressure (check `kubectl -n annotated-maps top
   pods` if available).
2. `kubectl -n annotated-maps logs deploy/annotated-maps-api --tail=100` —
   look for slow-query warnings or timeouts.
3. Open the `api-overview` dashboard
   (`deploy/helm/annotated-maps/files/dashboards/api-overview.json`) and
   check the "p95 latency" and "Fast-request ratio vs SLO" panels to see
   which views are slow and how far below the SLO line the ratio has
   dropped.

   Also check recent deploys: `helm -n annotated-maps history annotated-maps`
   — a burn that started right after a rollout points at the new release.
