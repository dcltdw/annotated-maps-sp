#!/usr/bin/env python3
"""
Layer 2 of the documentation-accuracy practice (ADR-0011).

Fact annotations (HTML comments, invisible in rendered Markdown) sit on the
line above the claim they guard:

    <!-- fact: tier=pr cmd="yq '.services | length' render.yaml" expect="3" prose="three" -->
    Render detects `render.yaml` and shows three services:

`tier=pr` commands read only repo files and gate PRs; `tier=scheduled`
commands may touch the network and run only in the scheduled workflow.
Use cmd='...' (single quotes) when the command itself needs double quotes.
`prose=` gives the string the adjacency rule looks for when the claim is
written in words ("three") rather than digits.

Doc-status markers classify every doc in scope:

    <!-- doc-status: living -->     (must be true today; may hold facts)
    <!-- doc-status: dated -->      (true as of its date; never auto-edited)
    <!-- doc-status: historical --> (excluded from accuracy claims)

Exits 1 on failure, 0 on success (or on overridden failure — see Task 5).
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from docs_common import tracked_md_files

LIVING = {
    "README.md",
    "ROADMAP.md",
    "docs/for-reviewers.md",
    "docs/aws-primer.md",
    "docs/kubernetes-primer.md",
    "docs/DEPLOY.md",
    "docs/slos.md",
}

# Workflow artifacts and templates: outside the taxonomy on purpose.
STATUS_EXEMPT_PREFIXES = ("docs/superpowers/",)
STATUS_EXEMPT = {
    "CLAUDE.md",
    ".github/pull_request_template.md",
    "docs/adr/0000-template.md",
}

STATUS_RE = re.compile(r"<!--\s*doc-status:\s*(living|dated|historical)\s*-->")
FACT_RE = re.compile(
    r"<!--\s*fact:\s*tier=(?P<tier>pr|scheduled)\s+"
    r"cmd=(?:\"(?P<cmd_d>[^\"]+)\"|'(?P<cmd_s>[^']+)')\s+"
    r"expect=\"(?P<expect>[^\"]*)\""
    r"(?:\s+prose=\"(?P<prose>[^\"]*)\")?\s*-->"
)
ADJACENT_LINES = 3


@dataclass
class Fact:
    path: Path
    lineno: int
    tier: str
    cmd: str
    expect: str
    prose: str | None
    following: list[str]


def doc_status(path: Path) -> str | None:
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:10])
    m = STATUS_RE.search(head)
    return m.group(1) if m else None


def in_status_scope(path: Path) -> bool:
    s = str(path)
    if s in STATUS_EXEMPT:
        return False
    return not any(s.startswith(p) for p in STATUS_EXEMPT_PREFIXES)


def facts_in(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = FACT_RE.search(line)
        if m:
            yield Fact(
                path=path,
                lineno=i + 1,
                tier=m.group("tier"),
                cmd=m.group("cmd_d") or m.group("cmd_s"),
                expect=m.group("expect"),
                prose=m.group("prose"),
                following=lines[i + 1 : i + 1 + ADJACENT_LINES],
            )


def taxonomy_errors() -> list[str]:
    """Every doc in scope declares a status; facts appear only in living docs;
    the LIVING list and the markers agree."""
    errors = []
    for path in tracked_md_files():
        if not in_status_scope(path):
            continue
        status = doc_status(path)
        if status is None:
            errors.append(f"{path}: missing <!-- doc-status: ... --> marker in first 10 lines")
            continue
        if str(path) in LIVING and status != "living":
            errors.append(f"{path}: listed as living but marked '{status}'")
        if str(path) not in LIVING and status == "living":
            errors.append(f"{path}: marked living but not in the LIVING set")
        if status != "living":
            for f in facts_in(path):
                errors.append(
                    f"{path}:{f.lineno}: fact annotation in a {status} doc — "
                    "facts belong only in living docs"
                )
    return errors
