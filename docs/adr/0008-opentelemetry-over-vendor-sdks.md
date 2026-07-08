# ADR-0008: OpenTelemetry over vendor SDKs (direct OTLP export)
- Status: accepted
- Date: 2026-07-08
## Context
M2 adds telemetry (traces, metrics, logs) to a Django app deployed on Render
free tier, viewed in Grafana Cloud free tier and an in-cluster Prometheus
stack. Instrumentation is a long-lived investment; the export destination is
not.
## Decision
Instrument once with OpenTelemetry and export OTLP/HTTP directly from the
process. Endpoint and auth are env vars; the local docker-compose stack, the
kind cluster, and Grafana Cloud are the same app config with different URLs.
For cluster-native metrics we also expose /metrics via django-prometheus:
pull-based scrape is the Kubernetes-native pattern, OTLP push fits SaaS —
one app feeds both deliberately.
## Consequences
- Swapping observability vendors is a config change, not a re-instrumentation
  (the reason Datadog's SDK was declined in the roadmap).
- In-process batch export sheds telemetry if the backend is down long enough
  to fill the buffer — acceptable for a demo, and invisible to request latency
  (export runs off-thread).
- OTEL_ENABLED=false (default) installs nothing: tests and existing deploys
  are byte-identical to pre-M2 behavior, guaranteed by test.
## Alternatives considered
- **App → OpenTelemetry Collector → backends** — the production topology at
  fleet scale (retry, redaction, fan-out). On Render it means a second
  always-on service for one app. Deferred to Milestone 3 (EKS DaemonSet).
- **Vendor agents/SDKs (Grafana Alloy, Datadog)** — rebuilding on a vendor's
  proprietary layer forfeits the one-instrumentation-many-backends property
  this milestone exists to demonstrate.
