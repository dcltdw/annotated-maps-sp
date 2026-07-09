# Milestone 2 PR-A — OTel Core + Local Harness + In-Cluster Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Env-gated OpenTelemetry instrumentation (traces+metrics+logs, trace↔log join), a docker-compose local verification harness, and the full Tier-2 in-cluster monitoring stack — all verifiable with zero external accounts.

**Architecture:** One `telemetry.py` module configures the OTel SDK when `OTEL_ENABLED=true` (default false = zero change). The structlog chain gains an always-on-but-no-op-without-a-span trace-context processor; `ObservabilityMiddleware` stamps request/tenant/user attributes onto the active span. `/metrics` (django-prometheus) mounts at root — structurally outside the public Ingress's `/api` route. Monitoring CRDs are values-gated in the M1 chart; kube-prometheus-stack is a separate release via `make monitoring-up`.

**Tech Stack:** opentelemetry-sdk + django/psycopg instrumentation + OTLP/HTTP exporters, django-prometheus, structlog, docker-compose (otel-collector, Tempo, Prometheus, Loki, Grafana OSS), kube-prometheus-stack, promtool.

**Spec:** `docs/superpowers/specs/2026-07-08-observability-milestone-design.md` — read it before starting any task.

## Global Constraints

- `OTEL_ENABLED` default **false**; disabled must mean: no OTel providers/handlers installed, log output byte-identical to today. All backend tests keep passing with it unset.
- The app uses **psycopg 3** (`psycopg[binary]>=3.2`) → instrumentation package is `opentelemetry-instrumentation-psycopg` (NOT `-psycopg2`).
- structlog contextvars keys are exactly `request_id`, `tenant_id`, `user_id` (bound in `core/middleware.py:ObservabilityMiddleware`). Span attributes use these names prefixed `app.` (`app.request_id`, …).
- `/metrics` mounts at ROOT (`/metrics`), never under `/api` — the Ingress routes only `/api` to the API service, so the public path can't reach it (structural guarantee, tested both halves).
- Chart: `monitoring.enabled` default **false** (chart must install unchanged on a cluster without Prometheus CRDs). Monitoring CRDs carry label `release: monitoring` (kube-prometheus-stack's default ServiceMonitor/rule selector, matching the `monitoring` release name used by `make monitoring-up`).
- Canonical Prometheus rules + dashboard JSON live in the chart: `deploy/helm/annotated-maps/files/` (templated via `.Files.Get`; promtool tests point at the same files). This consolidates the spec's `deploy/observability/alerts|dashboards` into one location — deviation noted, reason: no duplicate copies to drift.
- Backend gate before every commit (from `backend/`): `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .` (DB via `docker compose up -d db`). Chart gate: `make helm-checks`. New obs gate (Task 4 onward): `make obs-checks`.
- New Python deps (pinned minor): `opentelemetry-sdk~=1.27`, `opentelemetry-instrumentation-django~=0.48b0`, `opentelemetry-instrumentation-psycopg~=0.48b0`, `opentelemetry-exporter-otlp-proto-http~=1.27`, `django-prometheus~=2.3`. If the resolver reports these exact pins conflict, prefer the newest compatible pair (SDK 1.x + matching 0.x instrumentation) and note it — do not silently downgrade Django.
- Repo conventions: `Co-Authored-By` model trailer on commits; PR body sections `## Summary / ## Provenance / ## Reasoning / ## Testing / ## Risk & rollback`.

## File Structure

```
backend/annotated_maps/telemetry.py         OTel setup (env-gated, idempotent, test-injectable)
backend/core/logging.py                     + add_trace_context processor
backend/core/middleware.py                  + span-attribute stamping (3 lines)
backend/annotated_maps/settings.py          telemetry init + django-prometheus wiring
backend/annotated_maps/urls.py              + /metrics mount
backend/core/tests/test_telemetry.py        §9.1 suite (join, off, wire, /metrics gating)
deploy/observability/docker-compose.yml     local stack
deploy/observability/otel-collector.yaml    collector pipelines
deploy/observability/prometheus.yml         scrape/remote-write config
deploy/observability/grafana-datasources.yml provisioned Tempo/Prom/Loki + trace→logs link
scripts/synthetic_traffic.py                drives the API's public endpoints
deploy/helm/annotated-maps/files/prometheus-rules.yaml    canonical alert rules
deploy/helm/annotated-maps/files/dashboards/api-overview.json
deploy/helm/annotated-maps/templates/servicemonitor.yaml  (monitoring.enabled)
deploy/helm/annotated-maps/templates/prometheusrule.yaml  (monitoring.enabled)
deploy/helm/annotated-maps/templates/dashboard-configmap.yaml (monitoring.enabled)
deploy/observability/alert-tests/rules_test.yaml          promtool unit tests
docs/slos.md                                two SLOs + runbook
docs/adr/0008-opentelemetry-over-vendor-sdks.md
Makefile                                    + obs-up / obs-down / obs-checks / monitoring-up
.github/workflows/ci.yml                    helm job += obs-checks; helm-install += /metrics smoke
```

---

### Task 1: Telemetry core + ADR-0008 + the §9.1 pytest suite

**Files:**
- Create: `backend/annotated_maps/telemetry.py`
- Modify: `backend/core/logging.py` (add processor), `backend/core/middleware.py` (stamp span attrs), `backend/annotated_maps/settings.py` (init call), `backend/pyproject.toml` (deps)
- Create: `backend/core/tests/__init__.py` (if absent), `backend/core/tests/test_telemetry.py`
- Create: `docs/adr/0008-opentelemetry-over-vendor-sdks.md`

**Interfaces:**
- Produces: `setup_telemetry(*, enabled: bool, endpoint: str | None = None, service_name: str = "annotated-maps-api", deploy_env: str = "local", span_exporter=None, log_exporter=None, metric_reader=None) -> bool` — idempotent (second call returns False, changes nothing); test-injectable exporters override the OTLP defaults. `add_trace_context(logger, method_name, event_dict) -> dict` structlog processor. Settings env vars: `OTEL_ENABLED` (bool, default False), `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS` (read by the SDK itself), `DEPLOY_ENV` (default `local`).

- [ ] **Step 1: Add dependencies**

In `backend/pyproject.toml` `dependencies`, append:

```toml
    "opentelemetry-sdk~=1.27",
    "opentelemetry-instrumentation-django~=0.48b0",
    "opentelemetry-instrumentation-psycopg~=0.48b0",
    "opentelemetry-exporter-otlp-proto-http~=1.27",
    "django-prometheus~=2.3",
```

Run: `cd backend && uv sync` → resolves (see Global Constraints if pins conflict).

- [ ] **Step 2: Write the failing tests**

```python
# backend/core/tests/test_telemetry.py
"""§9.1 of the M2 spec: the observability robustness matrix."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import structlog
from django.test import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from core.logging import add_trace_context


# ---------- zero-overhead-off (spec 9.1.2) ----------

def test_processor_is_noop_without_active_span():
    """With no active span, the log processor adds NOTHING — off-mode output
    is byte-identical to pre-M2 logs."""
    event = {"event": "hello", "request_id": "r-1"}
    out = add_trace_context(None, "info", dict(event))
    assert out == event  # no trace_id/span_id keys sneak in


def test_disabled_by_default_installs_nothing():
    from annotated_maps.telemetry import setup_telemetry, _is_initialized

    assert setup_telemetry(enabled=False) is False
    assert _is_initialized() is False


# ---------- the join, both directions (spec 9.1.1) ----------

@pytest.fixture()
def memory_otel():
    """Session-unsafe by design: initialize once for this module's join tests
    with in-memory exporters. setup_telemetry is idempotent so a second call
    (e.g. another test module) is a no-op."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from annotated_maps.telemetry import setup_telemetry

    exporter = InMemorySpanExporter()
    setup_telemetry(enabled=True, span_exporter=exporter)
    yield exporter
    exporter.clear()


@pytest.mark.django_db
def test_trace_id_joins_span_to_log_line(memory_otel, capsys):
    client = Client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    spans = memory_otel.get_finished_spans()
    assert spans, "expected at least one span from the request"
    server_span = next(s for s in spans if s.kind.name == "SERVER")
    want_trace_id = format(server_span.get_span_context().trace_id, "032x")

    # the request handler logs at least one structlog line; find one with our trace id
    captured = capsys.readouterr()  # read ONCE — readouterr() consumes
    lines = [
        json.loads(line)
        for line in captured.err.splitlines() + captured.out.splitlines()
        if line.startswith("{")
    ]
    joined = [ln for ln in lines if ln.get("trace_id") == want_trace_id]
    assert joined, f"no log line carried trace_id {want_trace_id}"
    assert all("span_id" in ln for ln in joined)


@pytest.mark.django_db
def test_span_carries_request_attributes(memory_otel):
    client = Client()
    client.get("/api/v1/health", HTTP_X_REQUEST_ID="req-join-test")
    spans = memory_otel.get_finished_spans()
    server_span = next(s for s in spans if s.kind.name == "SERVER")
    assert server_span.attributes.get("app.request_id") == "req-join-test"


# ---------- OTLP wire test (spec 9.1.3) ----------

class _CapturingHandler(BaseHTTPRequestHandler):
    captured: dict[str, int] = {}

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).captured[self.path] = len(body)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # silence test output
        pass


def test_otlp_exporter_delivers_protobuf_over_http():
    """A local (non-global) provider + the REAL OTLP exporter, pointed at an
    in-process HTTP server: proves the wire mechanics our Grafana Cloud
    export will use, with no external service."""
    _CapturingHandler.captured = {}
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        provider = TracerProvider()
        provider.add_span_processor(
            SimpleSpanProcessor(
                OTLPSpanExporter(endpoint=f"http://127.0.0.1:{port}/v1/traces")
            )
        )
        with provider.get_tracer("wire-test").start_as_current_span("ping"):
            pass
        provider.force_flush()
        assert _CapturingHandler.captured.get("/v1/traces", 0) > 0
    finally:
        server.shutdown()


# ---------- /metrics gating (spec 9.1.4) — added in Task 3; placeholder-free:
# Task 3 appends test_metrics_endpoint_* here.
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest core/tests/test_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: annotated_maps.telemetry` / missing `add_trace_context`.

- [ ] **Step 4: Implement**

```python
# backend/annotated_maps/telemetry.py
"""Env-gated OpenTelemetry setup (M2 spec §2; ADR-0008).

Direct OTLP/HTTP export from the process — endpoint/auth are pure env config
(OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS, read by the SDK). Disabled (the
default) installs nothing. Gunicorn runs without --preload, so per-worker
init after fork is safe for the batch-export threads.
"""
from __future__ import annotations

import logging

_initialized = False


def _is_initialized() -> bool:
    return _initialized


def setup_telemetry(
    *,
    enabled: bool,
    endpoint: str | None = None,
    service_name: str = "annotated-maps-api",
    deploy_env: str = "local",
    span_exporter=None,
    log_exporter=None,
    metric_reader=None,
) -> bool:
    """Initialize tracing, metrics, and log export. Idempotent; returns True
    only on the call that performed initialization."""
    global _initialized
    if not enabled or _initialized:
        return False

    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": deploy_env}
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(span_exporter or OTLPSpanExporter(**(
            {"endpoint": f"{endpoint}/v1/traces"} if endpoint else {}
        )))
    )
    trace.set_tracer_provider(tracer_provider)

    reader = metric_reader or PeriodicExportingMetricReader(
        OTLPMetricExporter(**({"endpoint": f"{endpoint}/v1/metrics"} if endpoint else {}))
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(log_exporter or OTLPLogExporter(**(
            {"endpoint": f"{endpoint}/v1/logs"} if endpoint else {}
        )))
    )
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(
        LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    )

    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(skip_dep_check=True)

    _initialized = True
    return True
```

Add the structlog processor to `backend/core/logging.py` (insert into the processors list AFTER `merge_contextvars`):

```python
def add_trace_context(logger, method_name, event_dict):
    """Inject the active OTel trace/span ids. No active span → adds nothing,
    so OTEL-off log output is byte-identical to pre-M2 (M2 spec §9.1.2)."""
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
```

```python
        processors=[
            structlog.contextvars.merge_contextvars,
            add_trace_context,
            structlog.processors.add_log_level,
            ...
```

Stamp span attributes in `backend/core/middleware.py:ObservabilityMiddleware.__call__`, right after `bind_contextvars(...)` (set_attribute on a non-recording span is a no-op, so this is safe with OTel off):

```python
        from opentelemetry import trace

        span = trace.get_current_span()
        span.set_attribute("app.request_id", request_id)
        if getattr(request, "tenant_id", None):
            span.set_attribute("app.tenant_id", str(request.tenant_id))
        if getattr(request, "user_id", None):
            span.set_attribute("app.user_id", str(request.user_id))
```

(Move the `from opentelemetry import trace` to module top with the other imports.)

Wire init at the END of `backend/annotated_maps/settings.py`:

```python
# --- Observability (M2). Default off; see docs/adr/0008 + telemetry.py. ---
from annotated_maps.telemetry import setup_telemetry  # noqa: E402

OTEL_ENABLED = env.bool("OTEL_ENABLED", default=False)
setup_telemetry(
    enabled=OTEL_ENABLED,
    service_name=env("OTEL_SERVICE_NAME", default="annotated-maps-api"),
    deploy_env=env("DEPLOY_ENV", default="local"),
)
```

(Endpoint/headers deliberately NOT passed — the SDK reads `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_EXPORTER_OTLP_HEADERS` itself; the explicit `endpoint` kwarg exists for tests/tools.)

- [ ] **Step 5: Write ADR-0008**

```markdown
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
```

- [ ] **Step 6: Run to green**

Run: `uv run pytest core/tests/test_telemetry.py -v` → all PASS. Then the FULL suite `uv run pytest` (existing 181+ must stay green with OTEL off — this IS the regression proof) and `uv run ruff check . && uv run ruff format --check . && uv run mypy .`.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/annotated_maps/telemetry.py \
  backend/core/logging.py backend/core/middleware.py backend/annotated_maps/settings.py \
  backend/core/tests/ docs/adr/0008-opentelemetry-over-vendor-sdks.md
git commit -m "feat(obs): env-gated OpenTelemetry core with trace<->log join (ADR-0008)"
```

---

### Task 2: Local verification harness

**Files:**
- Create: `deploy/observability/docker-compose.yml`, `deploy/observability/otel-collector.yaml`, `deploy/observability/prometheus.yml`, `deploy/observability/grafana-datasources.yml`
- Create: `scripts/synthetic_traffic.py`
- Modify: `Makefile` (+ `obs-up` / `obs-down`)

**Interfaces:**
- Consumes: Task 1's env contract (`OTEL_ENABLED=true`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`).
- Produces: local Grafana at `http://localhost:3300` (3000 clashes with nothing today, but 3300 avoids future grief), collector OTLP/HTTP on `4318`.

- [ ] **Step 1: Write the compose stack**

```yaml
# deploy/observability/docker-compose.yml
# Local observability stack (M2 spec §3): the SAME app env vars that later
# point at Grafana Cloud point here instead — that's ADR-0008's argument.
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.111.0
    command: ["--config=/etc/otel/config.yaml"]
    volumes:
      - ./otel-collector.yaml:/etc/otel/config.yaml:ro
    ports:
      - "4318:4318"   # OTLP/HTTP in from the app
  tempo:
    image: grafana/tempo:2.6.0
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml:ro
    ports:
      - "3200:3200"
  prometheus:
    image: prom/prometheus:v2.54.1
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --web.enable-remote-write-receiver
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
  loki:
    image: grafana/loki:3.2.0
    ports:
      - "3100:3100"
  grafana:
    image: grafana/grafana-oss:11.2.0
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
    volumes:
      - ./grafana-datasources.yml:/etc/grafana/provisioning/datasources/ds.yml:ro
    ports:
      - "3300:3000"
```

```yaml
# deploy/observability/otel-collector.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls: { insecure: true }
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
  otlphttp/loki:
    endpoint: http://loki:3100/otlp
processors:
  batch: {}
service:
  pipelines:
    traces:  { receivers: [otlp], processors: [batch], exporters: [otlp/tempo] }
    metrics: { receivers: [otlp], processors: [batch], exporters: [prometheusremotewrite] }
    logs:    { receivers: [otlp], processors: [batch], exporters: [otlphttp/loki] }
```

```yaml
# deploy/observability/tempo.yaml
server:
  http_listen_port: 3200
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
storage:
  trace:
    backend: local
    local: { path: /tmp/tempo }
```

```yaml
# deploy/observability/prometheus.yml
global:
  scrape_interval: 15s
scrape_configs: []   # metrics arrive via remote-write from the collector
```

```yaml
# deploy/observability/grafana-datasources.yml
apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    url: http://tempo:3200
    uid: tempo
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        spanStartTimeShift: -5m
        spanEndTimeShift: 5m
        filterByTraceID: true
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    uid: prom
  - name: Loki
    type: loki
    url: http://loki:3100
    uid: loki
    jsonData:
      derivedFields:
        - name: trace_id
          matcherRegex: '"trace_id":"([0-9a-f]+)"'
          datasourceUid: tempo
          url: "$${__value.raw}"
```

(Add `tempo.yaml` to the Files list — it's required by the compose stack.)

- [ ] **Step 2: Synthetic traffic script**

```python
# scripts/synthetic_traffic.py
"""Drive the API's public endpoints to generate realistic telemetry.
Usage: python scripts/synthetic_traffic.py [--base-url http://localhost:8000] [--loops 20]
"""
import argparse
import json
import random
import time
import urllib.request


def get(base: str, path: str) -> int:
    req = urllib.request.Request(base + path, headers={"User-Agent": "synthetic-traffic"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
        return resp.status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--loops", type=int, default=20)
    args = ap.parse_args()

    with urllib.request.urlopen(args.base_url + "/api/v1/maps", timeout=10) as r:
        maps = json.load(r)
    map_id = maps[0]["id"]
    with urllib.request.urlopen(f"{args.base_url}/api/v1/maps/{map_id}/viewers", timeout=10) as r:
        viewer_ids = [v["id"] for v in json.load(r)]

    paths = ["/api/v1/health", "/api/v1/maps", f"/api/v1/maps/{map_id}/notes"]
    paths += [f"/api/v1/maps/{map_id}/notes?preview_as={v}" for v in viewer_ids]

    for i in range(args.loops):
        p = random.choice(paths)
        status = get(args.base_url, p)
        print(f"[{i+1}/{args.loops}] {status} {p}")
        time.sleep(random.uniform(0.1, 0.6))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make targets**

```makefile
obs-up: ## Local observability stack (Grafana http://localhost:3300)
	docker compose -f deploy/observability/docker-compose.yml up -d

obs-down:
	docker compose -f deploy/observability/docker-compose.yml down -v
```

- [ ] **Step 4: Live acceptance (run it)**

```bash
make obs-up
cd backend && docker compose up -d db && \
  OTEL_ENABLED=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 DEPLOY_ENV=local \
  uv run python manage.py runserver 8000 &   # backgrounded server
python3 scripts/synthetic_traffic.py --loops 15
curl -s "http://localhost:3200/api/search?limit=1" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('traces'), 'no traces in Tempo'; print('traces OK')"
curl -s "http://localhost:9090/api/v1/query?query=http_server_duration_milliseconds_count" | grep -q '"result":\[{' && echo "metrics OK"
curl -sG "http://localhost:3100/loki/api/v1/query_range" --data-urlencode 'query={service_name="annotated-maps-api"}' | grep -q trace_id && echo "logs OK (trace_id present)"
```
Expected: `traces OK`, `metrics OK`, `logs OK`. (Metric name may differ by SDK version — if the query returns empty, list names via `curl -s localhost:9090/api/v1/label/__name__/values | grep http` and use the http-server duration/count metric that appears; note the actual name in your report since Task 4's dashboard uses OTel names only for the local stack.) Stop the dev server; `make obs-down` optional — leave up if proceeding to Task 7.

- [ ] **Step 5: Commit**

```bash
git add deploy/observability scripts/synthetic_traffic.py Makefile
git commit -m "feat(obs): local docker-compose verification harness + synthetic traffic"
```

---

### Task 3: /metrics via django-prometheus (+ gating tests)

**Files:**
- Modify: `backend/annotated_maps/settings.py` (INSTALLED_APPS + middleware pair), `backend/annotated_maps/urls.py`
- Modify: `backend/core/tests/test_telemetry.py` (append the gating tests)

**Interfaces:**
- Produces: `GET /metrics` (root mount) serving Prometheus exposition. NOT under `/api`. No DB-engine wrapper (deliberate: HTTP metrics suffice for both SLOs; the pinned PostGIS ENGINE from the #24 fix stays untouched).

- [ ] **Step 1: Append the failing tests**

```python
# append to backend/core/tests/test_telemetry.py

# ---------- /metrics gating (spec 9.1.4) ----------

@pytest.mark.django_db
def test_metrics_endpoint_serves_prometheus_exposition():
    client = Client()
    client.get("/api/v1/health")  # generate at least one sample
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "django_http_responses_total_by_status_total" in body


@pytest.mark.django_db
def test_metrics_is_not_reachable_under_api_prefix():
    """The public Ingress routes only /api to this service — mounting outside
    /api is the structural guarantee that /metrics is cluster-internal."""
    client = Client()
    assert client.get("/api/v1/metrics").status_code == 404
    assert client.get("/api/metrics").status_code == 404
```

Run: `uv run pytest core/tests/test_telemetry.py -k metrics -v` → FAIL (404 on /metrics).

- [ ] **Step 2: Wire django-prometheus**

`settings.py`: add `"django_prometheus"` to `INSTALLED_APPS`; wrap the middleware list — `"django_prometheus.middleware.PrometheusBeforeMiddleware"` as the FIRST entry and `"django_prometheus.middleware.PrometheusAfterMiddleware"` as the LAST.

`urls.py`:

```python
from django.urls import include, path

from annotated_maps.api import api

urlpatterns = [
    path("api/v1/", api.urls),
    # Cluster-internal scrape target. Mounted at root ON PURPOSE: the public
    # Ingress routes only /api here, so no public route reaches it (M2 §4).
    path("", include("django_prometheus.urls")),
]
```

- [ ] **Step 3: Run to green** — the two new tests pass; FULL backend gate (`pytest`, ruff, format, mypy) green. Check exposition metric names now: `uv run python - <<'PY'` … or simply run the test with `-s` and print — confirm `django_http_responses_total_by_status_total` and `django_http_requests_latency_seconds_by_view_method_bucket` exist (Task 4's rules use them; if the installed django-prometheus version names them differently, adjust Task 4's PromQL AND its promtool tests to the real names — they must match the exposition).

- [ ] **Step 4: Commit**

```bash
git add backend/annotated_maps/settings.py backend/annotated_maps/urls.py backend/core/tests/test_telemetry.py
git commit -m "feat(obs): /metrics via django-prometheus, root-mounted outside /api"
```

---

### Task 4: Alert rules + promtool unit tests + SLO doc + dashboard JSON

**Files:**
- Create: `deploy/helm/annotated-maps/files/prometheus-rules.yaml`
- Create: `deploy/observability/alert-tests/rules_test.yaml`
- Create: `deploy/helm/annotated-maps/files/dashboards/api-overview.json`
- Create: `docs/slos.md`
- Modify: `Makefile` (+ `obs-checks`)

**Interfaces:**
- Consumes: metric names verified live in Task 3 Step 3.
- Produces: rules file consumed by Task 5's PrometheusRule template via `.Files.Get`; `make obs-checks` used by CI (Task 6).

- [ ] **Step 1: Write the rules (canonical file, plain Prometheus format)**

```yaml
# deploy/helm/annotated-maps/files/prometheus-rules.yaml
# Canonical alert rules. Templated into the chart's PrometheusRule and
# unit-tested by promtool (deploy/observability/alert-tests). PromQL here
# MUST match docs/slos.md.
groups:
  - name: annotated-maps-slos
    rules:
      - record: am:http_error_ratio:rate5m
        expr: >
          sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[5m]))
          /
          sum(rate(django_http_responses_total_by_status_total[5m]))
      - record: am:http_fast_ratio:rate5m
        expr: >
          sum(rate(django_http_requests_latency_seconds_by_view_method_bucket{le="0.5"}[5m]))
          /
          sum(rate(django_http_requests_latency_seconds_by_view_method_count[5m]))
      - alert: ApiAvailabilityBurn
        expr: am:http_error_ratio:rate5m > 0.005
        for: 10m
        labels: { severity: page }
        annotations:
          summary: "API 5xx ratio above SLO burn threshold"
          runbook: "docs/slos.md#availability"
      - alert: ApiLatencyBurn
        expr: am:http_fast_ratio:rate5m < 0.99
        for: 10m
        labels: { severity: page }
        annotations:
          summary: "API latency SLO burning (<99% of requests under 500ms)"
          runbook: "docs/slos.md#latency"
```

- [ ] **Step 2: Write the promtool unit tests (fires AND stays-green, both alerts)**

```yaml
# deploy/observability/alert-tests/rules_test.yaml
rule_files:
  - ../../helm/annotated-maps/files/prometheus-rules.yaml
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      - series: 'django_http_responses_total_by_status_total{status="200"}'
        values: "0+100x30"
      - series: 'django_http_responses_total_by_status_total{status="500"}'
        values: "0+10x30"     # 10/110 ≈ 9% errors — way over 0.5%
    alert_rule_test:
      - eval_time: 15m
        alertname: ApiAvailabilityBurn
        exp_alerts:
          - exp_labels: { severity: page }
            exp_annotations:
              summary: "API 5xx ratio above SLO burn threshold"
              runbook: "docs/slos.md#availability"
  - interval: 1m
    input_series:
      - series: 'django_http_responses_total_by_status_total{status="200"}'
        values: "0+100x30"
      - series: 'django_http_responses_total_by_status_total{status="500"}'
        values: "0+0x30"      # zero errors — must stay green
    alert_rule_test:
      - eval_time: 15m
        alertname: ApiAvailabilityBurn
        exp_alerts: []
  - interval: 1m
    input_series:
      - series: 'django_http_requests_latency_seconds_by_view_method_bucket{le="0.5"}'
        values: "0+50x30"     # only 50 of 100 under 500ms — 50% fast, SLO 99%
      - series: 'django_http_requests_latency_seconds_by_view_method_count'
        values: "0+100x30"
    alert_rule_test:
      - eval_time: 15m
        alertname: ApiLatencyBurn
        exp_alerts:
          - exp_labels: { severity: page }
            exp_annotations:
              summary: "API latency SLO burning (<99% of requests under 500ms)"
              runbook: "docs/slos.md#latency"
  - interval: 1m
    input_series:
      - series: 'django_http_requests_latency_seconds_by_view_method_bucket{le="0.5"}'
        values: "0+100x30"    # 100% fast — stays green
      - series: 'django_http_requests_latency_seconds_by_view_method_count'
        values: "0+100x30"
    alert_rule_test:
      - eval_time: 15m
        alertname: ApiLatencyBurn
        exp_alerts: []
```

- [ ] **Step 3: docs/slos.md** — two sections (`## Availability`, `## Latency`), each with: the SLO statement (99.5% non-5xx / 99% < 500 ms, both 30-day), the exact recording-rule PromQL from Step 1, the alert that guards it, and a 3-step runbook (`kubectl -n annotated-maps get pods` → `kubectl -n annotated-maps logs deploy/annotated-maps-api --tail=100` → open the api-overview dashboard; plus "check recent deploys: `helm -n annotated-maps history annotated-maps`"). State the error-budget arithmetic (99.5% over 30d ≈ 3.6 h; 99% latency ≈ 7.2 h of slow minutes).

- [ ] **Step 4: Dashboard JSON** (`files/dashboards/api-overview.json`): a valid Grafana dashboard (`schemaVersion` ≥ 39, `title: "Annotated Maps — API Overview"`, uid `am-api-overview`) with four panels wired to the Prometheus datasource: request rate (`sum(rate(django_http_responses_total_by_status_total[5m]))`), error ratio (the `am:http_error_ratio:rate5m` recording rule), p95 latency (`histogram_quantile(0.95, sum by (le) (rate(django_http_requests_latency_seconds_by_view_method_bucket[5m])))`), and fast-ratio vs the 0.99 SLO line (`am:http_fast_ratio:rate5m`). Panel titles exactly: "Request rate", "Error ratio (SLO burn)", "p95 latency", "Fast-request ratio vs SLO". Assemble standard Grafana JSON scaffolding around these — validate with `python3 -m json.tool`.

- [ ] **Step 5: Make target**

```makefile
obs-checks: ## Static observability checks — same commands CI runs
	promtool check rules deploy/helm/annotated-maps/files/prometheus-rules.yaml
	promtool test rules deploy/observability/alert-tests/rules_test.yaml
	python3 -m json.tool deploy/helm/annotated-maps/files/dashboards/api-overview.json > /dev/null
```

If `promtool` is not installed locally: `brew install prometheus` is the source of it — STOP and report BLOCKED for the user to authorize, per repo convention on installing tools (M1 precedent).

- [ ] **Step 6: Run `make obs-checks` to green; commit**

```bash
git add deploy/helm/annotated-maps/files deploy/observability/alert-tests docs/slos.md Makefile
git commit -m "feat(obs): SLO alert rules with promtool unit tests, SLO doc, dashboard-as-code"
```

---

### Task 5: Chart monitoring templates + kube-prometheus-stack target

**Files:**
- Create: `deploy/helm/annotated-maps/templates/servicemonitor.yaml`, `templates/prometheusrule.yaml`, `templates/dashboard-configmap.yaml`
- Modify: `deploy/helm/annotated-maps/values.yaml` (+ `monitoring.enabled: false`), `Makefile` (+ `monitoring-up`)
- Test: `deploy/helm/annotated-maps/tests/monitoring_test.yaml` (new) + one Ingress assertion added to `tests/workloads_test.yaml`

**Interfaces:**
- Consumes: rules + dashboard files from Task 4 (`.Files.Get`).
- Produces: values key `monitoring.enabled` (default false); CRDs labeled `release: monitoring`.

- [ ] **Step 1: Failing tests**

```yaml
# deploy/helm/annotated-maps/tests/monitoring_test.yaml
suite: monitoring gating
templates:
  - templates/servicemonitor.yaml
  - templates/prometheusrule.yaml
  - templates/dashboard-configmap.yaml
tests:
  - it: renders nothing by default (no Prometheus CRDs required)
    asserts:
      - hasDocuments: { count: 0 }
  - it: renders all three when enabled, labeled for the monitoring release
    set: { monitoring: { enabled: true } }
    asserts:
      - hasDocuments: { count: 1 }
      - equal: { path: metadata.labels.release, value: monitoring }
  - it: servicemonitor scrapes the api service's http port
    set: { monitoring: { enabled: true } }
    template: templates/servicemonitor.yaml
    asserts:
      - equal: { path: spec.endpoints[0].path, value: /metrics }
```

Add to `tests/workloads_test.yaml` (the structural half of the /metrics guarantee):

```yaml
  - it: ingress routes ONLY /api to the api service (metrics stays private)
    template: templates/ingress.yaml
    asserts:
      - lengthEqual: { path: spec.rules[0].http.paths, count: 2 }
      - equal: { path: spec.rules[0].http.paths[0].path, value: /api }
      - equal: { path: spec.rules[0].http.paths[1].path, value: / }
```

Run `helm unittest deploy/helm/annotated-maps` → new suite FAILS (templates missing).

- [ ] **Step 2: Templates**

```yaml
# deploy/helm/annotated-maps/templates/servicemonitor.yaml
{{- if .Values.monitoring.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "annotated-maps.fullname" . }}-api
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    release: monitoring   # kube-prometheus-stack's default selector
spec:
  selector:
    matchLabels:
      {{- include "annotated-maps.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: api
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
{{- end }}
```

(The api Service's port needs a `name: http` for ServiceMonitor port-by-name — add `name: http` to `api-service.yaml`'s port entry as part of this task; helm unittest for api service still passes since it asserts values, and add no new behavior.)

```yaml
# deploy/helm/annotated-maps/templates/prometheusrule.yaml
{{- if .Values.monitoring.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: {{ include "annotated-maps.fullname" . }}-slos
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    release: monitoring
spec:
  {{- .Files.Get "files/prometheus-rules.yaml" | nindent 2 }}
{{- end }}
```

```yaml
# deploy/helm/annotated-maps/templates/dashboard-configmap.yaml
{{- if .Values.monitoring.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "annotated-maps.fullname" . }}-dashboard
  labels:
    {{- include "annotated-maps.labels" . | nindent 4 }}
    release: monitoring
    grafana_dashboard: "1"   # picked up by the grafana sidecar
data:
  api-overview.json: |-
    {{- .Files.Get "files/dashboards/api-overview.json" | nindent 4 }}
{{- end }}
```

`values.yaml`: append

```yaml
monitoring:
  enabled: false   # requires kube-prometheus-stack CRDs (make monitoring-up)
```

Makefile:

```makefile
monitoring-up: ## kube-prometheus-stack as a separate release (heavy: ~1GB RAM)
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update prometheus-community
	helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
	  -n monitoring --create-namespace --wait --timeout 10m \
	  --set grafana.sidecar.dashboards.searchNamespace=ALL
```

- [ ] **Step 3: Green + commit** — `make helm-checks` (unittest incl. new suite + kubeconform both values files; note: kubeconform doesn't know Prometheus CRD schemas — add `-ignore-missing-schemas` ONLY if it rejects them, and say so in the report). Then:

```bash
git add deploy/helm/annotated-maps Makefile
git commit -m "feat(helm): values-gated ServiceMonitor, PrometheusRule, dashboard ConfigMap"
```

---

### Task 6: CI wiring

**Files:**
- Modify: `.github/workflows/ci.yml` — `helm` job gains promtool install + `make obs-checks`; `helm-install` job gains a `/metrics` smoke step.

- [ ] **Step 1: In the `helm` job**, after the kubeconform install step, add:

```yaml
      - name: Install promtool
        run: |
          curl -sSL https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.linux-amd64.tar.gz | tar xz
          sudo mv prometheus-2.54.1.linux-amd64/promtool /usr/local/bin/
      - run: make obs-checks
```

- [ ] **Step 2: In the `helm-install` job**, after the web smoke step, add:

```yaml
      - name: Smoke the metrics endpoint (cluster-internal)
        run: |
          kubectl -n annotated-maps port-forward svc/annotated-maps-api 8082:8000 &
          sleep 3
          curl -fsS http://localhost:8082/metrics | grep -q django_http_responses_total_by_status_total
```

- [ ] **Step 3:** YAML-validate (`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`), commit:

```bash
git add .github/workflows/ci.yml
git commit -m "ci: observability static checks (promtool) + live /metrics smoke"
```

(NOTE: the `helm-install` smoke requires OTEL off — it is; the chart doesn't set OTEL_ENABLED. /metrics works regardless of OTel since django-prometheus is unconditional middleware.)

---

### Task 7: End-to-end verification (controller-level)

**Files:** none — verification only.

- [ ] **Step 1:** Full gates: backend suite (with OTel off — regression), `make helm-checks`, `make obs-checks`.
- [ ] **Step 2:** Local Tier-1 dry run (repeat Task 2 Step 4 acceptance if the stack was torn down): traces in Tempo, metrics in Prometheus, `trace_id` in Loki lines — plus the manual click-through: local Grafana → Explore → Tempo trace → "logs for this span".
- [ ] **Step 3:** In-cluster: `make kind-up` (or reuse a running cluster), `make monitoring-up`, `make deploy` with `--set monitoring.enabled=true` (add a note: `helm upgrade --install ... --set monitoring.enabled=true` variant or `make deploy HELM_EXTRA="--set monitoring.enabled=true"` — implement the `HELM_EXTRA` passthrough in the Makefile deploy target as part of this step: `helm upgrade --install ... $(HELM_EXTRA)`). Verify: `kubectl -n annotated-maps get servicemonitor,prometheusrule` exist; port-forward the monitoring Prometheus (`svc/monitoring-kube-prometheus-prometheus 9091:9090`) and confirm the target is UP and `am:http_error_ratio:rate5m` returns a value after some synthetic traffic through `http://localhost/api/...`; port-forward the monitoring Grafana and confirm the api-overview dashboard auto-loaded (sidecar).
- [ ] **Step 4:** Screenshot the in-cluster Grafana dashboard headlessly; Read the PNG to confirm panels render with data.
- [ ] **Step 5:** Branch ready for the PR-A pull request (repo rigor sections; note PR-B follows after the Grafana Cloud checkpoint).
