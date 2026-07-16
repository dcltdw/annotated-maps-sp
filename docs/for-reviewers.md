# Evaluating this repo

A three-minute map for anyone assessing this as engineering work. Everything
below links to something you can check yourself — a public CI run, a live
dashboard, an artifact a machine produced. Nothing here asks you to take a
claim on faith.

**What this is:** a real, deployed product — a multi-tenant, permissioned
map-annotation platform ([live demo](https://annotated-maps-web.onrender.com/),
Django/PostGIS + Vite/TypeScript) — plus a
[production-engineering roadmap](../ROADMAP.md) taking it from "solid deployed
app" to production-grade. All four milestones are shipped: Kubernetes/Helm,
OpenTelemetry, Terraform + EKS, and a one-button ephemeral pipeline.

## If you only look at three things

**1. [The one-button pipeline run](m4-pipeline.md)** — one dispatch builds the
entire AWS environment from nothing, deploys, tests against the live URL, and
destroys it: [green, 35 minutes](https://github.com/dcltdw/annotated-maps-sp/actions/runs/29447574490).
The screenshot on that page is *the pipeline's own artifact* — Playwright drove
the ALB the pipeline had just created. Not a screenshot taken by hand.

**2. [The live telemetry dashboard](https://friendlynewt1033.grafana.net/public-dashboards/20407e8eaf204a899c3feb0af005935d)** —
public, no login, real request rate / latency / error ratio from the demo
above. OpenTelemetry instrumentation, exported to Grafana Cloud, with
[SLOs](slos.md) and [dashboards as code](../deploy/observability/dashboards/).

**3. [Lessons learned](lessons-learned.md)** — 21 real bugs, each naming **how
it was found**. **Zero were caught by unit tests.** Several are my own
mistakes, including one that survived an adversarial code review and a green
CI run.

## What each milestone proves

| Milestone | The claim | Evidence |
|---|---|---|
| **1 — Kubernetes & Helm** | The app runs on Kubernetes, from a chart, with probes/HPA/PDB/migration hooks — proven on a real cluster, not just linted | [chart](../deploy/helm/annotated-maps/) · [ADR-0007](adr/0007-migrations-via-helm-hooks.md) · [primer](kubernetes-primer.md) — CI installs it on `kind` and runs `helm test` on every PR |
| **2 — Observability** | Telemetry is real and public: traces, metrics, logs, and a trace↔log join — with SLOs and alert rules that are unit-tested | [public dashboard](https://friendlynewt1033.grafana.net/public-dashboards/20407e8eaf204a899c3feb0af005935d) · [SLOs](slos.md) · [ADR-0008](adr/0008-opentelemetry-over-vendor-sdks.md) |
| **3 — AWS infrastructure as code** | Terraform stands up EKS + VPC + IRSA + ECR, serves traffic through an ALB, and destroys to zero — hand-written IAM, OIDC, no long-lived keys | [demo run + screenshot](m3-demo-run.md) · [terraform](../deploy/terraform/) · [ADR-0009](adr/0009-eks-over-ecs.md) · [primer](aws-primer.md) |
| **4 — One-button pipeline** | The whole lifecycle, automated and safe to fail: scan-gated images, per-run database branches, tests against the live URL, guaranteed teardown | [run record](m4-pipeline.md) · [workflow](../.github/workflows/demo-pipeline.yml) · [ADR-0010](adr/0010-pipeline-apply-role.md) |

Supporting: [10 ADRs](adr/) (decisions, with alternatives and consequences),
[13 design specs](superpowers/specs/), and an
[day-one architectural triage](architecture/2026-06-09-production-lenses.md) recording what would
earn its place as the system grows.

## The honest parts

Everything below links to the evidence behind it, including the parts where
that evidence is a record of something going wrong.

**Teardown was proven by failure, not argued.** The pipeline's central claim is
that a red run can't strand billable infrastructure. **Three of the five live
runs went red — and all five tore themselves down to zero, unattended**,
including one that failed with a live cluster and two nodes already running.
The sweep (EKS, EC2, load balancers, NAT gateways, VPCs, ECR, Terraform state)
read zero every time. That claim was tested by reality rather than asserted.

**The security scan caught a real CVE, and I didn't suppress it.** On its first
live run the Trivy gate failed the web image on a CRITICAL openssl flaw and
**skipped the push**, so the vulnerable image never reached the registry. The
CVE was 32-bit-only and these images run on amd64 — an ignore file would have
been defensible and easy. It was still the wrong call: the gate's policy is
"CRITICAL **and** fixable," this was both, and suppressing a control the first
time it ever fires is how controls become decoration. The base image got patched
instead. ([#18](lessons-learned.md))

**My own adversarial review missed things, and the write-up says so.** A
reviewer *recommended* an IAM Deny and explicitly checked that nothing
legitimate would break; it broke the very first apply, because the dependency
was indirect and caller-relative — invisible in the diff.
([#15](lessons-learned.md))

**A green run once proved nothing, and that's written down too.** The pipeline
went green while uploading a screenshot of a *blank map* — the assertion behind
it (`canvas` is visible) couldn't fail. It survived static gates, code review,
and a full live run. A human opening the PNG caught it. The rule it produced:
*a green run is not evidence; the artifact is.* ([#19](lessons-learned.md))

**The security model is disclosed, not flattered.**
[ADR-0010](adr/0010-pipeline-apply-role.md) states plainly that the pipeline's
deploy role is **AdministratorAccess-equivalent** within the demo account, that
the `annotated-maps-*` IAM prefix is a blast-radius guard and **not** a security
boundary against a malicious principal, and exactly which escalation path
remains open and why that's accepted (a dedicated, disposable account reachable
only by a maintainer). The real fix — a permissions boundary — is
[ticketed, not pretended](https://github.com/users/dcltdw/projects/6).

**A fix that turned out to be wrong, and what replaced it.** A ticket said a
deployment-branch policy would close the risk that a future `pull_request_target`
job hands a fork the deploy role. Acting on it revealed the premise was false:
`pull_request_target` runs in the context of the **default branch**, so its ref
*is* `main` and a `main`-only policy admits it — no OIDC scoping helps, because
the event is designed to look like `main`. The invariant is therefore permanent,
so it became a **CI gate** ([check_workflow_triggers.py](../.github/scripts/check_workflow_triggers.py))
that fails the build if any workflow pairs that trigger with the AWS role — and
the gate was proven by deliberately writing the forbidden workflow and watching
it fail. The branch policy went in anyway, for the honest reason: it stops a
modified pipeline being dispatched from an *unreviewed branch*.
[ADR-0010](adr/0010-pipeline-apply-role.md) records the correction.

**Known gaps, tracked openly:** a permissions boundary to close the IAM path
above, and read-permission gaps in the plan-only CI role that only surface while
a pipeline run is in flight. Both on the
[board](https://github.com/users/dcltdw/projects/6), with the diagnosis written
down.

**What I deliberately didn't build** — service mesh, multi-region, a parallel
ECS implementation, a microservice split, Datadog — and *why*, is
[its own section of the roadmap](../ROADMAP.md#what-i-deliberately-didnt-build).
Each was rejected for cause rather than skipped out of unfamiliarity.

## Cost discipline

The AWS demo is **ephemeral by design**: an estimated **~$0.20–0.30 per full
lifecycle run** (resource-hours; not yet confirmed via Cost Explorer), versus **~$180/month** to leave an equivalent EKS environment
running ([ADR-0009](adr/0009-eks-over-ecs.md)). The entire Milestone 4 live
verification — five runs, three of which failed — cost an estimated **~$1.50**.

Nothing is left running. What persists is free: a Terraform state bucket, an
OIDC provider, two IAM roles, an SNS topic, and a **$10/month budget alarm**.
The guardrails are real code, not intentions: a concurrency group that forbids
overlapping runs, `timeout-minutes` on every job, and teardown on
`if: always()`.

An always-on cluster would be a more impressive screenshot and worse
engineering. The durable artifact is the evidence, not a URL that costs $75/month
to keep warm.

## Verify any of it yourself

The pipeline is public and reproducible:

```sh
gh workflow run demo-pipeline.yml --ref main   # ~35 min, ~$0.25
gh run watch
```

It also runs unattended on the 3rd of each month, so drift surfaces on a
schedule rather than the next time someone needs it to work — which means the
[Actions history](https://github.com/dcltdw/annotated-maps-sp/actions) keeps
proving the claim on this page after it was written.
