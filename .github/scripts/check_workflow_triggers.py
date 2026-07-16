#!/usr/bin/env python3
"""Forbid the one workflow shape that would hand a fork our AWS deploy role.

WHY THIS EXISTS
---------------
`annotated-maps-deployer` is AdministratorAccess-equivalent inside the demo
account (ADR-0010 says so plainly). Its OIDC trust accepts exactly one
subject: `repo:dcltdw/annotated-maps-sp:environment:aws-deploy`. That subject
is **environment-scoped, not ref-scoped** — any job naming that Environment
while holding `id-token: write` can mint it.

That is safe today only because of a property of *trigger types*, not of any
setting:

  * `pull_request` from a fork  -> GitHub downgrades every `write` permission
    to `read` (unless "Send write tokens to workflows from pull requests" is
    enabled — it is not). So `id-token: write` is refused and no token exists.
  * `pull_request_target`       -> runs with FULL base-repo permissions and is
    NOT downgraded, while executing a workflow file from the base branch. Its
    `github.ref` is the default branch, so a deployment-branch policy does
    NOT stop it either.

So a `pull_request_target` job that named `environment: aws-deploy` would hand
a fork's pull request an admin-equivalent role, with no approval. Nothing in
GitHub prevents someone adding that job months from now for an unrelated
reason. ADR-0010 records this as a human invariant on the workflow files.

This script turns that invariant into a gate. A human invariant that nobody
checks is a wish; the repo already learned this twice (lessons-learned #20:
hand-maintained gate lists rot; #21: an unpinned linter is a gate whose rules
change without a commit).

Exits non-zero if any workflow combines a dangerous trigger with either an
AWS Environment or `id-token: write`.
"""

import sys
from pathlib import Path

import yaml

# Triggers that run with full base-repo permissions on PR-derived content.
# `pull_request` is deliberately NOT here: fork PRs get write perms downgraded
# to read, so they cannot obtain an OIDC token at all.
DANGEROUS_TRIGGERS = {"pull_request_target"}

# Environments whose OIDC subject an AWS role trusts.
AWS_ENVIRONMENTS = {"aws-deploy", "aws-plan"}

WORKFLOWS = Path(".github/workflows")


def job_environment_names(job):
    """`environment:` may be a string, a mapping with `name`, or a list."""
    env = job.get("environment")
    if env is None:
        return []
    if isinstance(env, str):
        return [env]
    if isinstance(env, dict):
        return [env["name"]] if "name" in env else []
    if isinstance(env, list):
        out = []
        for e in env:
            out.extend([e] if isinstance(e, str) else ([e["name"]] if isinstance(e, dict) and "name" in e else []))
        return out
    return []


def wants_id_token(perms):
    """`permissions:` may be a mapping, or the shorthand `write-all`."""
    if perms == "write-all":
        return True
    if isinstance(perms, dict):
        return perms.get("id-token") == "write"
    return False


def triggers_of(wf):
    # PyYAML parses the bare key `on:` as the boolean True (YAML 1.1 truthiness).
    on = wf.get("on", wf.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def main() -> int:
    problems = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        wf = yaml.safe_load(path.read_text())
        if not isinstance(wf, dict):
            continue
        bad_triggers = triggers_of(wf) & DANGEROUS_TRIGGERS
        if not bad_triggers:
            continue

        trig = ", ".join(sorted(bad_triggers))
        if wants_id_token(wf.get("permissions")):
            problems.append(f"{path}: workflow-level `id-token: write` with trigger `{trig}`")

        for name, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for env in job_environment_names(job):
                if env in AWS_ENVIRONMENTS:
                    problems.append(f"{path}: job `{name}` names environment `{env}` with trigger `{trig}`")
            if wants_id_token(job.get("permissions")):
                problems.append(f"{path}: job `{name}` requests `id-token: write` with trigger `{trig}`")

    if problems:
        print("FORBIDDEN WORKFLOW SHAPE — this would hand a fork's pull request an")
        print("AdministratorAccess-equivalent AWS role. See docs/adr/0010-pipeline-apply-role.md.\n")
        for p in problems:
            print(f"  - {p}")
        print(
            "\n`pull_request_target` runs with FULL base-repo permissions (unlike\n"
            "`pull_request` from a fork, whose write permissions are downgraded to\n"
            "read), and its github.ref is the default branch — so neither the\n"
            "permission downgrade nor a deployment-branch policy protects you here.\n"
            "If you genuinely need this, change the AWS role's trust policy first."
        )
        return 1

    print(f"OK: no workflow combines {sorted(DANGEROUS_TRIGGERS)} with an AWS environment or id-token: write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
