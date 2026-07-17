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
import shlex
import subprocess
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
ALLOWLIST = {
    "pr": {"grep", "ls", "wc", "cat", "yq", "jq", "git", "python3"},
    "scheduled": {"grep", "ls", "wc", "cat", "yq", "jq", "git", "python3", "gh", "aws"},
}
FORBIDDEN_RE = re.compile(r"[;&<>`]|\$\(")
COMMAND_TIMEOUT_S = 30


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


GIT_READONLY_SUBCOMMANDS = {"diff", "describe", "log", "ls-files", "rev-parse", "show"}


def _pipe_segments(cmd: str) -> list[list[str]]:
    """Tokenize with shell-like quoting, treating `|` as punctuation — a
    pipe inside a quoted argument (yq '.a | b') is data, not a pipeline.
    Operator runs other than a lone `|` (e.g. `||`) are rejected."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars="|")
    lex.whitespace_split = True
    words = list(lex)
    segments: list[list[str]] = []
    current: list[str] = []
    for w in words:
        if w == "|":
            segments.append(current)
            current = []
        elif set(w) == {"|"}:
            raise ValueError(f"forbidden shell operator {w!r}")
        else:
            current.append(w)
    segments.append(current)
    return segments


def validate_cmd(cmd: str, tier: str) -> str | None:
    if FORBIDDEN_RE.search(cmd):
        return f"forbidden shell metacharacter in cmd: {cmd!r}"
    try:
        segments = _pipe_segments(cmd)
    except ValueError as e:
        return f"unparseable cmd ({e}): {cmd!r}"
    for words in segments:
        if not words:
            return f"empty pipe segment in cmd: {cmd!r}"
        if words[0] not in ALLOWLIST[tier]:
            return f"'{words[0]}' is not allowlisted for tier={tier}"
        if words[0] == "python3" and (
            len(words) < 2
            or not words[1].startswith(".github/scripts/")
            or ".." in Path(words[1]).parts
        ):
            return "python3 facts may only run scripts under .github/scripts/"
        if words[0] == "git" and (
            len(words) < 2 or words[1] not in GIT_READONLY_SUBCOMMANDS
        ):
            return (
                "git facts may only use read-only subcommands "
                f"({', '.join(sorted(GIT_READONLY_SUBCOMMANDS))}) with no global flags"
            )
    return None


def check_fact(fact: Fact) -> str | None:
    """Return an error string, or None if the fact holds."""
    where = f"{fact.path}:{fact.lineno}"
    if not fact.expect:
        return f"{where}: expect must be non-empty"
    err = validate_cmd(fact.cmd, fact.tier)
    if err:
        return f"{where}: {err}"
    try:
        p = subprocess.run(fact.cmd, shell=True, capture_output=True,
                           text=True, timeout=COMMAND_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"{where}: command timed out after {COMMAND_TIMEOUT_S}s: {fact.cmd!r}"
    if p.returncode != 0:
        return (f"{where}: command exited {p.returncode}: {fact.cmd!r} "
                f"stderr: {p.stderr.strip()[:200]}")
    actual = p.stdout.strip()
    if actual != fact.expect:
        return (f"{where}: expected '{fact.expect}' got '{actual}' — update the "
                "prose AND the annotation, or re-run the command to re-derive")
    needle = fact.prose if fact.prose is not None else fact.expect
    if not any(needle in line for line in fact.following):
        return (f"{where}: adjacency rule — '{needle}' not found in the "
                f"{ADJACENT_LINES} lines after the annotation; the prose and "
                "the annotation have drifted apart")
    return None
