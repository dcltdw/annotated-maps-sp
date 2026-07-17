# Documentation-Accuracy Practice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the repo's docs-link-to-verifiable-truth principle with four layers: a PR-blocking link checker, registered fact annotations split by determinism, a scheduled drift job that files issues, and the codified human review + ADR-0011 policy.

**Architecture:** Two stdlib-only Python checkers in `.github/scripts/` (mirroring `check_pr_body.py`), sharing helpers via `docs_common.py`. Facts live as HTML-comment annotations beside the claims they guard, with an adjacency rule binding annotation to prose. A new `docs` CI job gates PRs and main pushes; `docs-accuracy.yml` runs weekly/monthly crons. Spec: `docs/superpowers/specs/2026-07-17-docs-accuracy-practice-design.md`.

**Tech Stack:** Python 3 stdlib only (`re`, `subprocess`, `shlex`, `unittest`, `urllib`), `yq` v4.44.3 (pinned), GitHub Actions, `gh` CLI.

## Global Constraints

- **Python stdlib only** in `.github/scripts/` — no pip installs in the docs CI job.
- **Pin every downloaded tool** (repo rule — see the shellcheck comment in `ci.yml`): yq is `v4.44.3`.
- **Glob-derived file lists only** — file sets come from `git ls-files '*.md'`, never a hand-maintained list.
- **Never edit dated/historical docs** to match current code — under any circumstances, including the watched-fail demos.
- **Command allowlist** — pr tier: `grep ls wc cat yq jq git python3`; scheduled tier adds `gh aws`. `python3` may only run scripts under `.github/scripts/`. No `; & > < ` ` $( ` anywhere in a fact cmd.
- **PR bodies** use this repo's exact headings: `## Summary`, `## Provenance`, `## Reasoning`, `## Testing`, `## Risk & rollback` (CI-enforced).
- **Commits** end with `Co-Authored-By: <current model> <noreply@anthropic.com>`.
- **Branch → PR → wait for approval** per PR below; branch off freshly pulled `main` each time.
- **Watched-fail acceptance:** each PR delivering a CI-gating checker (PR A, PR B) must include a break-commit, the red run URL in the PR body's Testing section, and a revert.
- **The seven living docs:** `README.md`, `ROADMAP.md`, `docs/for-reviewers.md`, `docs/aws-primer.md`, `docs/kubernetes-primer.md`, `docs/DEPLOY.md`, `docs/slos.md`.
- **Status-marker scope:** all tracked `*.md` EXCEPT `docs/superpowers/**`, `CLAUDE.md`, `.github/pull_request_template.md`, `docs/adr/0000-template.md`.

**PR map:** Task 1–2 → PR A (Layer 1). Task 3–7 → PR B (Layer 2). Task 8 → PR C (scheduled). Task 9–10 → PR D (Layer 3 + policy). Merge in order; each later PR assumes the earlier ones are on `main`.

---

### Task 1: Layer-1 link checker (`check_doc_links.py` + `docs_common.py`)

**Files:**
- Create: `.github/scripts/docs_common.py`
- Create: `.github/scripts/check_doc_links.py`
- Test: `.github/scripts/test_check_doc_links.py`

**Interfaces:**
- Produces: `docs_common.tracked_md_files() -> list[Path]` (repo-relative paths from `git ls-files '*.md'`); `check_doc_links.check_file(path: Path) -> list[str]` (error strings); `check_doc_links.links_in(path) -> Iterator[tuple[int, str]]`; `check_doc_links.external_urls() -> list[str]`; CLI: `python3 .github/scripts/check_doc_links.py [--list-external]`, exit 1 on failure.
- Consumes: nothing (first task).

- [ ] **Step 1: Write the failing tests**

Create `.github/scripts/test_check_doc_links.py`:

```python
"""Tests for the Layer-1 doc link checker (ADR-0011)."""
import tempfile
import unittest
from pathlib import Path

import check_doc_links as mod


class LinkCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_valid_relative_link_passes(self):
        self.write("other.md", "# Other\n")
        doc = self.write("doc.md", "See [other](other.md).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_broken_link_detected(self):
        doc = self.write("doc.md", "See [missing](nope.md).\n")
        errors = mod.check_file(doc)
        self.assertEqual(len(errors), 1)
        self.assertIn("broken link", errors[0])
        self.assertIn("doc.md:1", errors[0])

    def test_valid_anchor_passes(self):
        self.write("other.md", "# Other\n\n## My Section Name\n")
        doc = self.write("doc.md", "See [sec](other.md#my-section-name).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_broken_anchor_detected(self):
        self.write("other.md", "# Other\n")
        doc = self.write("doc.md", "See [sec](other.md#no-such-anchor).\n")
        errors = mod.check_file(doc)
        self.assertEqual(len(errors), 1)
        self.assertIn("broken anchor", errors[0])

    def test_same_file_anchor(self):
        doc = self.write("doc.md", "## Target Heading\n\nJump [here](#target-heading).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_anchor_slug_strips_punctuation(self):
        # GitHub's algorithm drops non-alnum chars (except space/hyphen) and
        # turns EACH space into a hyphen, so "Risk & rollback" ->
        # "risk--rollback" (double hyphen: the "&" vanishes, both spaces stay).
        doc = self.write("doc.md", "## Risk & rollback\n\n[x](#risk--rollback)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_duplicate_headings_get_numeric_suffix(self):
        doc = self.write("doc.md", "## Setup\n\n## Setup\n\n[a](#setup) [b](#setup-1)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_links_inside_code_fences_ignored(self):
        doc = self.write("doc.md", "```\n[fake](nope.md)\n```\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_external_and_mailto_skipped(self):
        doc = self.write("doc.md", "[a](https://x.test/) [b](mailto:x@y.z)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_directory_link_passes(self):
        (self.dir / "sub").mkdir()
        doc = self.write("doc.md", "[dir](sub/)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_image_link_checked(self):
        doc = self.write("doc.md", "![shot](img/missing.png)\n")
        self.assertEqual(len(mod.check_file(doc)), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_doc_links'`

- [ ] **Step 3: Write the implementation**

Create `.github/scripts/docs_common.py`:

```python
"""Shared helpers for the documentation-accuracy checkers (ADR-0011)."""
import subprocess
from pathlib import Path


def tracked_md_files() -> list[Path]:
    """Every tracked Markdown file, derived from git — never hand-maintained."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.splitlines() if p]
```

Create `.github/scripts/check_doc_links.py`:

```python
#!/usr/bin/env python3
"""
Layer 1 of the documentation-accuracy practice (ADR-0011): every internal
link and #anchor in every tracked Markdown file must resolve. External URLs
are NOT checked here — they belong to the scheduled workflow, which cannot
gate a PR. `--list-external` prints them for that workflow to consume.

Exits 1 on failure, 0 on success.
"""
import argparse
import re
import sys
from pathlib import Path

from docs_common import tracked_md_files

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")

_anchor_cache: dict[Path, set[str]] = {}


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [text](url) -> text
    return re.sub(r"[*_`]", "", text)


def _slugify(heading: str) -> str:
    """GitHub's anchor algorithm: lowercase, drop non-alnum except space and
    hyphen, spaces -> hyphens."""
    text = _strip_inline_md(heading).lower().strip()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors_for(path: Path) -> set[str]:
    if path not in _anchor_cache:
        slugs: set[str] = set()
        seen: dict[str, int] = {}
        in_fence = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = HEADING_RE.match(line)
            if not m:
                continue
            slug = _slugify(m.group(1))
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            slugs.add(slug if n == 0 else f"{slug}-{n}")
        _anchor_cache[path] = slugs
    return _anchor_cache[path]


def links_in(path: Path):
    """Yield (lineno, target) for every Markdown link, skipping code fences."""
    in_fence = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in LINK_RE.finditer(line):
            yield lineno, m.group(1)


def check_file(path: Path) -> list[str]:
    errors = []
    for lineno, target in links_in(path):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        base, _, frag = target.partition("#")
        dest = path if not base else (path.parent / base).resolve()
        if base and not dest.exists():
            errors.append(f"{path}:{lineno}: broken link -> {target}")
            continue
        if frag and dest.suffix == ".md" and frag.lower() not in anchors_for(dest):
            errors.append(f"{path}:{lineno}: broken anchor -> {target}")
    return errors


def external_urls() -> list[str]:
    urls = set()
    for path in tracked_md_files():
        for _, target in links_in(path):
            if target.startswith(("http://", "https://")):
                urls.add(target)
    return sorted(urls)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-external", action="store_true",
                    help="print external URLs instead of checking internal links")
    args = ap.parse_args()

    if args.list_external:
        print("\n".join(external_urls()))
        return

    files = tracked_md_files()
    errors: list[str] = []
    for path in files:
        errors += check_file(path)
    if errors:
        print("Doc link check failed:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Doc link check passed ({len(files)} files).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: all PASS. If `test_anchor_slug_strips_punctuation` fails, fix `_slugify` (not the test) — the expected slug for `Risk & rollback` is `risk--rollback` (the `&` is dropped, both flanking spaces become hyphens).

- [ ] **Step 5: Run the checker against the real repo**

Run: `python3 .github/scripts/check_doc_links.py`
Expected: `Doc link check passed (NN files).` — the pilot found zero broken links, so a clean pass is expected. If real breakage appears, fix the doc (living docs) or the link target (dated docs keep their prose; only repair genuinely broken relative paths — that is internal accuracy, not content rewriting).

- [ ] **Step 6: Commit**

```bash
git add .github/scripts/docs_common.py .github/scripts/check_doc_links.py .github/scripts/test_check_doc_links.py
git commit -m "feat(docs-accuracy): Layer-1 internal link/anchor checker"
```

---

### Task 2: CI wiring for Layer 1 + `make docs-checks` + watched-fail demo → PR A

**Files:**
- Modify: `.github/workflows/ci.yml` (add `docs` job after `pr-rigor`, ~line 68)
- Modify: `Makefile` (add `docs-checks` target + `.PHONY`)
- Modify: `ROADMAP.md` (CI quality-gate list, ~line 30–34: add a docs bullet)

**Interfaces:**
- Consumes: `check_doc_links.py` CLI from Task 1.
- Produces: CI job named `docs`; `make docs-checks` target. Task 7 appends fact steps to this same `docs` job; Task 8 reuses the yq install block verbatim.

- [ ] **Step 1: Add the `docs` job to `ci.yml`**

Insert after the `pr-rigor` job (no `if:` — it must also run on pushes to `main`; that is the merge-race net from the spec):

```yaml
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Checker unit tests
        run: python3 -m unittest discover -s .github/scripts -v
      - name: Doc link check (Layer 1 — internal links/anchors only)
        run: python3 .github/scripts/check_doc_links.py
```

- [ ] **Step 2: Add the Makefile target**

Add `docs-checks` to the `.PHONY` line, and after the `obs-checks` target:

```make
docs-checks: ## Documentation accuracy — same commands CI runs (ADR-0011)
	python3 -m unittest discover -s .github/scripts
	python3 .github/scripts/check_doc_links.py
```

- [ ] **Step 3: Update ROADMAP's CI gate list**

In `ROADMAP.md` (~line 30), the "CI quality gates" numbered list of what the suite covers: append one item, matching the list's existing voice:

```markdown
5. Documentation accuracy — internal link/anchor integrity and registered doc-fact checks (ADR-0011)
```

(Plain text "ADR-0011", NOT a Markdown link: the ADR file doesn't exist until PR D, and a link to it now would fail this very PR's link checker. PR D upgrades the mention to a real link. Match the list's existing numbering style.)

- [ ] **Step 4: Verify locally**

Run: `make docs-checks`
Expected: unit tests pass, then `Doc link check passed (NN files).`

- [ ] **Step 5: Commit and push the branch**

```bash
git add .github/workflows/ci.yml Makefile ROADMAP.md
git commit -m "feat(docs-accuracy): docs CI job (Layer 1) + make docs-checks"
git push -u origin docs-accuracy-l1-links
```

- [ ] **Step 6: Watched-fail demo — break a link**

```bash
# In README.md change the link target docs/for-reviewers.md to docs/for-reviewersXX.md
git add README.md
git commit -m "test(docs-accuracy): DEMO break a link — expect red docs job (will be reverted)"
git push
gh run watch --exit-status  # or: gh run list --branch docs-accuracy-l1-links
```

Expected: the `docs` job FAILS with `README.md:<line>: broken link -> docs/for-reviewersXX.md`. Copy the run URL.

- [ ] **Step 7: Revert the break**

```bash
git revert HEAD --no-edit
git push
gh run watch --exit-status
```

Expected: `docs` job green.

- [ ] **Step 8: Open PR A**

Body uses the repo's five headings. In `## Testing`, include the red-run URL from Step 6 and the green-run URL from Step 7, labeled "watched-fail acceptance (spec § Testing & acceptance)". Wait for approval; after merge, do the post-merge ritual (pull, grep main for `check_doc_links`, delete branch both sides).

---

### Task 3: Fact/status parsing + taxonomy enforcement (`check_doc_facts.py`, part 1)

**Files:**
- Create: `.github/scripts/check_doc_facts.py`
- Test: `.github/scripts/test_check_doc_facts.py`

**Interfaces:**
- Consumes: `docs_common.tracked_md_files()`.
- Produces (used by Tasks 4–7): `LIVING: set[str]` (the seven living docs, repo-relative strings); `STATUS_EXEMPT: set[str]`; `doc_status(path) -> str | None`; `facts_in(path) -> Iterator[Fact]` where `Fact` is a `dataclass` with fields `path: Path`, `lineno: int`, `tier: str`, `cmd: str`, `expect: str`, `prose: str | None`, `following: list[str]` (the next 3 lines); `taxonomy_errors() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `.github/scripts/test_check_doc_facts.py`:

```python
"""Tests for the Layer-2 doc facts checker (ADR-0011)."""
import tempfile
import unittest
from pathlib import Path

import check_doc_facts as mod


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_status_marker_parsed(self):
        p = self.write("a.md", "<!-- doc-status: living -->\n# A\n")
        self.assertEqual(mod.doc_status(p), "living")

    def test_status_must_be_in_first_ten_lines(self):
        p = self.write("a.md", ("x\n" * 12) + "<!-- doc-status: living -->\n")
        self.assertIsNone(mod.doc_status(p))

    def test_fact_double_quoted_cmd(self):
        p = self.write("a.md",
            '<!-- fact: tier=pr cmd="yq \'.services | length\' render.yaml" expect="3" prose="three" -->\n'
            "Render shows three services.\n")
        facts = list(mod.facts_in(p))
        self.assertEqual(len(facts), 1)
        f = facts[0]
        self.assertEqual(f.tier, "pr")
        self.assertEqual(f.cmd, "yq '.services | length' render.yaml")
        self.assertEqual(f.expect, "3")
        self.assertEqual(f.prose, "three")
        self.assertEqual(f.lineno, 1)

    def test_fact_single_quoted_cmd_allows_inner_double_quotes(self):
        p = self.write("a.md",
            "<!-- fact: tier=scheduled cmd='gh api \"repos/x\"' expect=\"5\" -->\n"
            "Five runs.\n")
        f = list(mod.facts_in(p))[0]
        self.assertEqual(f.cmd, 'gh api "repos/x"')
        self.assertIsNone(f.prose)

    def test_following_lines_captured(self):
        p = self.write("a.md",
            '<!-- fact: tier=pr cmd="ls" expect="x" -->\nl1\nl2\nl3\nl4\n')
        self.assertEqual(list(mod.facts_in(p))[0].following, ["l1", "l2", "l3"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_doc_facts'` (Task 1's link tests still pass).

- [ ] **Step 3: Write the implementation**

Create `.github/scripts/check_doc_facts.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: all PASS (both test modules).

- [ ] **Step 5: Commit**

```bash
git add .github/scripts/check_doc_facts.py .github/scripts/test_check_doc_facts.py
git commit -m "feat(docs-accuracy): fact/status parsing + taxonomy enforcement"
```

---

### Task 4: Allowlist validation, execution, adjacency rule (`check_doc_facts.py`, part 2)

**Files:**
- Modify: `.github/scripts/check_doc_facts.py`
- Test: `.github/scripts/test_check_doc_facts.py` (append)

**Interfaces:**
- Produces (used by Task 5): `validate_cmd(cmd: str, tier: str) -> str | None` (error string or None); `check_fact(fact: Fact) -> str | None`; `ALLOWLIST: dict[str, set[str]]`.

- [ ] **Step 1: Append failing tests**

Append to `test_check_doc_facts.py`:

```python
class AllowlistTests(unittest.TestCase):
    def test_pr_tier_allows_repo_readers(self):
        self.assertIsNone(mod.validate_cmd("yq '.a' f.yml", "pr"))
        self.assertIsNone(mod.validate_cmd("grep -c x f.md | wc -l", "pr"))

    def test_gh_rejected_in_pr_tier_allowed_in_scheduled(self):
        self.assertIsNotNone(mod.validate_cmd("gh run list", "pr"))
        self.assertIsNone(mod.validate_cmd("gh run list", "scheduled"))

    def test_every_pipe_segment_validated(self):
        self.assertIsNotNone(mod.validate_cmd("ls | curl http://x", "pr"))

    def test_forbidden_metacharacters(self):
        for cmd in ("ls; rm -rf /", "ls && ls", "ls > f", "ls `x`", "ls $(x)"):
            self.assertIsNotNone(mod.validate_cmd(cmd, "pr"), cmd)

    def test_python3_restricted_to_repo_scripts(self):
        self.assertIsNone(mod.validate_cmd("python3 .github/scripts/fact_demo_runs.py", "pr"))
        self.assertIsNotNone(mod.validate_cmd("python3 evil.py", "pr"))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def fact(self, cmd, expect, prose=None, following=None):
        return mod.Fact(path=Path("x.md"), lineno=1, tier="pr", cmd=cmd,
                        expect=expect, prose=prose,
                        following=following if following is not None else [expect])

    def test_matching_fact_passes(self):
        f = (self.dir / "v.txt"); f.write_text("42\n")
        self.assertIsNone(mod.check_fact(self.fact(f"cat {f}", "42", following=["The value is 42."])))

    def test_value_mismatch_fails_with_expected_vs_actual(self):
        f = (self.dir / "v.txt"); f.write_text("41\n")
        err = mod.check_fact(self.fact(f"cat {f}", "42", following=["The value is 42."]))
        self.assertIn("expected '42'", err)
        self.assertIn("got '41'", err)

    def test_adjacency_rule_expect_must_appear_in_prose(self):
        f = (self.dir / "v.txt"); f.write_text("42\n")
        err = mod.check_fact(self.fact(f"cat {f}", "42", following=["No number here."]))
        self.assertIn("adjacency", err)

    def test_adjacency_rule_uses_prose_attr_when_present(self):
        f = (self.dir / "v.txt"); f.write_text("3\n")
        fact = self.fact(f"cat {f}", "3", prose="three", following=["It shows three services."])
        self.assertIsNone(mod.check_fact(fact))

    def test_command_failure_reported(self):
        err = mod.check_fact(self.fact("cat /nonexistent-x", "1", following=["1"]))
        self.assertIn("exited", err)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: FAIL — `AttributeError: module 'check_doc_facts' has no attribute 'validate_cmd'`

- [ ] **Step 3: Implement**

Append to `check_doc_facts.py` (after `ADJACENT_LINES`, add the constants; after `taxonomy_errors`, the functions):

```python
ALLOWLIST = {
    "pr": {"grep", "ls", "wc", "cat", "yq", "jq", "git", "python3"},
    "scheduled": {"grep", "ls", "wc", "cat", "yq", "jq", "git", "python3", "gh", "aws"},
}
FORBIDDEN_RE = re.compile(r"[;&<>`]|\$\(")
COMMAND_TIMEOUT_S = 30
```

```python
import shlex
import subprocess


def validate_cmd(cmd: str, tier: str) -> str | None:
    if FORBIDDEN_RE.search(cmd):
        return f"forbidden shell metacharacter in cmd: {cmd!r}"
    for segment in cmd.split("|"):
        words = shlex.split(segment)
        if not words:
            return f"empty pipe segment in cmd: {cmd!r}"
        if words[0] not in ALLOWLIST[tier]:
            return f"'{words[0]}' is not allowlisted for tier={tier}"
        if words[0] == "python3" and (
            len(words) < 2 or not words[1].startswith(".github/scripts/")
        ):
            return "python3 facts may only run scripts under .github/scripts/"
    return None


def check_fact(fact: Fact) -> str | None:
    """Return an error string, or None if the fact holds."""
    where = f"{fact.path}:{fact.lineno}"
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
```

(Move the `import shlex` / `import subprocess` lines up with the other imports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/scripts/check_doc_facts.py .github/scripts/test_check_doc_facts.py
git commit -m "feat(docs-accuracy): allowlisted execution + adjacency rule"
```

---

### Task 5: CLI, tier selection, and the override escape hatch (`check_doc_facts.py`, part 3)

**Files:**
- Modify: `.github/scripts/check_doc_facts.py` (add `main()`)
- Modify: `.github/scripts/docs_common.py` (add `override_reason()`)
- Modify: `.github/scripts/check_doc_links.py` (honor the override)
- Test: `.github/scripts/test_check_doc_facts.py` (append)

**Interfaces:**
- Produces: `docs_common.override_reason(body: str) -> str | None`; CLI `python3 .github/scripts/check_doc_facts.py --tier {pr,scheduled,all} [--allow-override]`; `check_doc_links.py --allow-override`. Override reads the `PR_BODY` env var (same convention as `check_pr_body.py`). With a valid override, failures print as warnings and exit 0; an override line with no reason is itself a hard failure.

- [ ] **Step 1: Append failing tests**

```python
class OverrideTests(unittest.TestCase):
    def test_reason_extracted(self):
        from docs_common import override_reason
        body = "## Summary\nstuff\nDocs-Checks-Override: mid-restructure, tracked in #99\n"
        self.assertEqual(override_reason(body), "mid-restructure, tracked in #99")

    def test_no_override_line(self):
        from docs_common import override_reason
        self.assertIsNone(override_reason("## Summary\nstuff\n"))

    def test_empty_reason_is_not_a_valid_override(self):
        from docs_common import override_reason
        self.assertIsNone(override_reason("Docs-Checks-Override:   \n"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s .github/scripts -v`
Expected: FAIL — `ImportError: cannot import name 'override_reason'`

- [ ] **Step 3: Implement**

Append to `docs_common.py`:

```python
import re

_OVERRIDE_RE = re.compile(r"^Docs-Checks-Override:[ \t]*(\S.*?)\s*$", re.MULTILINE)


def override_reason(body: str) -> str | None:
    """The PR-body escape hatch (ADR-0011). Overrides DEFER failures — main-push
    and scheduled runs ignore them — and require a non-empty reason."""
    m = _OVERRIDE_RE.search(body or "")
    return m.group(1) if m else None
```

Append `main()` to `check_doc_facts.py`:

```python
import argparse
import os

from docs_common import override_reason


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["pr", "scheduled", "all"], default="pr")
    ap.add_argument("--allow-override", action="store_true",
                    help="honor a Docs-Checks-Override line in $PR_BODY (PR runs only)")
    args = ap.parse_args()

    errors = taxonomy_errors()
    n_facts = 0
    for name in sorted(LIVING):
        path = Path(name)
        for fact in facts_in(path):
            if args.tier != "all" and fact.tier != args.tier:
                continue
            n_facts += 1
            err = check_fact(fact)
            if err:
                errors.append(err)

    if not errors:
        print(f"Doc facts check passed ({n_facts} facts, tier={args.tier}).")
        return

    if args.allow_override:
        reason = override_reason(os.environ.get("PR_BODY", ""))
        if reason:
            print(f"OVERRIDDEN ({len(errors)} failure(s)) — reason: {reason}")
            print("Deferred, not erased: the main-push and scheduled runs ignore overrides.")
            for e in errors:
                print(f"  warning: {e}")
            return

    print("Doc facts check failed:", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

In `check_doc_links.py`, extend `main()` the same way: add the `--allow-override` argument, and where errors are printed, first check `args.allow_override and override_reason(os.environ.get("PR_BODY", ""))` — if set, print the same `OVERRIDDEN` block and `return` instead of `sys.exit(1)`. Add `import os` and `from docs_common import tracked_md_files, override_reason`.

- [ ] **Step 4: Run tests, then exercise the CLI**

Run: `python3 -m unittest discover -s .github/scripts -v` → all PASS.
Run: `python3 .github/scripts/check_doc_facts.py --tier pr`
Expected at this point: FAILURES — every in-scope doc is missing its `doc-status` marker (Task 6 adds them). That output list is exactly the work list for Task 6. Confirm the error format matches, e.g. `README.md: missing <!-- doc-status: ... --> marker in first 10 lines`.

- [ ] **Step 5: Commit**

```bash
git add .github/scripts/check_doc_facts.py .github/scripts/docs_common.py .github/scripts/check_doc_links.py .github/scripts/test_check_doc_facts.py
git commit -m "feat(docs-accuracy): CLI tiers + Docs-Checks-Override escape hatch"
```

---

### Task 6: Doc-status markers + fact triage + annotations in the living docs

**Files:**
- Modify: all 21 in-scope docs (add one marker line each — list from Task 5 Step 4's failure output)
- Modify: `docs/for-reviewers.md`, `docs/DEPLOY.md`, `docs/aws-primer.md` (annotations)
- Create: `.github/scripts/fact_demo_runs.py`
- Modify: `Makefile` (`docs-checks`: add the facts line)

**Interfaces:**
- Consumes: the full `check_doc_facts.py` CLI.
- Produces: a green `python3 .github/scripts/check_doc_facts.py --tier all` on a machine with authenticated `gh`; `fact_demo_runs.py` prints exactly `runs=5 red=3`.

- [ ] **Step 1: Add status markers**

Line 1 (or immediately after an existing title-comment) of each in-scope doc:

- `<!-- doc-status: living -->` — the seven living docs.
- `<!-- doc-status: dated -->` — `docs/adr/0001`…`0010`, `docs/lessons-learned.md`, `docs/m3-demo-run.md`, `docs/m4-pipeline.md`.
- `<!-- doc-status: historical -->` — `docs/architecture/2026-06-09-production-lenses.md`.

Adding a marker line is a mechanical prepend, not a content edit — it does not violate never-edit-dated.

- [ ] **Step 2: Run the checker to confirm taxonomy is green**

Run: `python3 .github/scripts/check_doc_facts.py --tier pr`
Expected: `Doc facts check passed (0 facts, tier=pr).`

- [ ] **Step 3: Create the run-stats helper**

`gh --jq` needs nested double quotes, which the annotation grammar can't hold — so the flagship fact uses the `python3 .github/scripts/` escape valve. Create `.github/scripts/fact_demo_runs.py`:

```python
#!/usr/bin/env python3
"""Fact helper (ADR-0011): the M4 verification-run record quoted in
docs/for-reviewers.md. The createdAt bound freezes the set to the five
verification runs — later cron/dispatch runs must not shift this record."""
import json
import subprocess

out = subprocess.run(
    ["gh", "run", "list", "--workflow", "demo-pipeline.yml", "--limit", "100",
     "--json", "conclusion,createdAt"],
    capture_output=True, text=True, check=True,
).stdout
runs = [r for r in json.loads(out) if r["createdAt"] < "2026-07-16"]
red = [r for r in runs if r["conclusion"] == "failure"]
print(f"runs={len(runs)} red={len(red)}")
```

Run: `python3 .github/scripts/fact_demo_runs.py`
Expected: `runs=5 red=3`. **If it prints anything else, STOP** — re-read the actual run list (`gh run list --workflow demo-pipeline.yml`) and reconcile with the maintainer before annotating; the doc claim itself may need correcting first.

- [ ] **Step 4: Register the facts (the triage table)**

Candidates from the brief, with dispositions. Register only the ★ rows; the rest are deliberate non-registrations (record them in the ADR's "not registered" note in Task 10).

| Claim | Doc | Disposition |
|---|---|---|
| ★ "Three of the five live runs went red … all five tore themselves down" | for-reviewers | register, scheduled |
| ★ "runs unattended on the 3rd of each month" | for-reviewers | register, pr |
| ★ "shows three services" | DEPLOY | register, pr |
| ★ `preDeployCommand` quoted as `sh predeploy.sh` | DEPLOY | register, pr |
| ★ demo Terraform file inventory table | aws-primer | register, pr (count) |
| "~35 min / ~$0.25 / ~$1.50" cost-duration figures | ROADMAP, for-reviewers | already softened to estimates (PR #68); measured figure has a board ticket; Layer 3 watches consistency |
| "all four milestones shipped" | README, ROADMAP, for-reviewers | terminal state, drift risk nil — Layer 3 |
| CI job-count claim | ROADMAP | already detied by PR #68 (names the suite, links ci.yml — no number to guard) |

Annotations to add (exact lines; place each directly ABOVE the claim's line; verify each `expect` by running the command first — if a command's real output differs, the doc claim is wrong: stop and reconcile):

`docs/for-reviewers.md` (~line 53, the red-runs claim):

```markdown
<!-- fact: tier=scheduled cmd="python3 .github/scripts/fact_demo_runs.py" expect="runs=5 red=3" prose="Three of the five" -->
```

`docs/for-reviewers.md` (~line 139, the monthly-cron claim):

```markdown
<!-- fact: tier=pr cmd="yq '.on.schedule[0].cron' .github/workflows/demo-pipeline.yml" expect="0 14 3 * *" prose="3rd of each month" -->
```

`docs/DEPLOY.md` (~line 43, the three-services claim):

```markdown
<!-- fact: tier=pr cmd="yq '.services | length' render.yaml" expect="3" prose="three" -->
```

`docs/DEPLOY.md` (beside the doc's verbatim quote of the pre-deploy command — find it with `grep -n "predeploy" docs/DEPLOY.md`):

```markdown
<!-- fact: tier=pr cmd="grep -c 'preDeployCommand: sh predeploy.sh' render.yaml" expect="1" prose="predeploy" -->
```

`docs/aws-primer.md` (above the demo-stack file table, ~line 100): first run
`ls deploy/terraform/demo/*.tf | wc -l` (call the result N, spelled `<N-word>`), then add an intro sentence + annotation:

```markdown
<!-- fact: tier=pr cmd="ls deploy/terraform/demo/*.tf | wc -l" expect="<N>" prose="<N-word>" -->
The demo stack is <N-word> `.tf` files:
```

- [ ] **Step 5: Extend the Makefile target**

Append to `docs-checks` (spec § Layer 3: the local sweep runs BOTH tiers):

```make
	python3 .github/scripts/check_doc_facts.py --tier all
```

- [ ] **Step 6: Verify everything is green locally**

Run: `make docs-checks`
Expected: unit tests pass; link check passes; `Doc facts check passed (5 facts, tier=all).` (scheduled tier needs your authenticated `gh`).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(docs-accuracy): doc-status taxonomy markers + 5 registered facts"
```

---

### Task 7: CI wiring for Layer 2 + watched-fail demo → PR B

**Files:**
- Modify: `.github/workflows/ci.yml` (the `docs` job from Task 2)

**Interfaces:**
- Consumes: `check_doc_facts.py --tier pr [--allow-override]`, `PR_BODY` env.
- Produces: PR-blocking pr-tier facts; override honored on PRs only.

- [ ] **Step 1: Append fact steps to the `docs` job**

```yaml
      - name: Install yq (pinned, like every other tool here)
        run: |
          sudo curl -fsSL https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64 -o /usr/local/bin/yq
          sudo chmod +x /usr/local/bin/yq
      - name: Doc facts, pr tier (Layer 2)
        if: github.event_name == 'pull_request'
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
        run: python3 .github/scripts/check_doc_facts.py --tier pr --allow-override
      - name: Doc facts, pr tier (Layer 2 — main; overrides do not apply here)
        if: github.event_name != 'pull_request'
        run: python3 .github/scripts/check_doc_facts.py --tier pr
```

Also move the yq install step ABOVE the link-check step (order: checkout → yq → unit tests → links → facts).

- [ ] **Step 2: Commit, push, open the branch's first green run**

```bash
git add .github/workflows/ci.yml
git commit -m "feat(docs-accuracy): gate pr-tier doc facts in CI"
git push -u origin docs-accuracy-l2-facts
gh run watch --exit-status
```

Expected: `docs` job green (pr-tier facts only; the scheduled-tier fact does not run in this job).

- [ ] **Step 3: Watched-fail demo — break a fact**

Edit `docs/DEPLOY.md`: change the three-services annotation to `expect="4"` (leave the prose saying three — this simulates real drift).

```bash
git add docs/DEPLOY.md
git commit -m "test(docs-accuracy): DEMO break a registered fact — expect red docs job (will be reverted)"
git push
gh run watch --exit-status
```

Expected: `docs` job FAILS with `docs/DEPLOY.md:<line>: expected '4' got '3' — update the prose AND the annotation...`. Copy the run URL.

- [ ] **Step 4: Revert and confirm green**

```bash
git revert HEAD --no-edit
git push
gh run watch --exit-status
```

- [ ] **Step 5: Open PR B**

Repo headings; `## Testing` includes both run URLs (red + green) labeled as the watched-fail acceptance, plus the local `make docs-checks` output line. `## Risk & rollback`: note the override escape hatch exists from this PR onward and that dated docs got only a prepended marker line. Wait for approval; post-merge ritual after.

---

### Task 8: Scheduled drift workflow (`docs-accuracy.yml`) → PR C

**Files:**
- Create: `.github/workflows/docs-accuracy.yml`
- Create: `.github/scripts/check_external_urls.py`
- Modify: `.github/workflows/ci.yml` (add `docs-accuracy.yml` to the actionlint list, ~line 125)

**Interfaces:**
- Consumes: `check_doc_links.py --list-external`, `check_doc_facts.py --tier all`.
- Produces: weekly full-suite drift run + tracking issue (label `docs-accuracy`); monthly Layer-3 reminder issue.

- [ ] **Step 1: Write the external-URL checker**

Create `.github/scripts/check_external_urls.py`:

```python
#!/usr/bin/env python3
"""Scheduled-only (ADR-0011): external-URL liveness for the LIVING docs.
Never a PR gate — the public demo sleeps and takes ~30 s to wake, so this
retries patiently and only the scheduled workflow runs it."""
import sys
import time
import urllib.request
from pathlib import Path

from check_doc_facts import LIVING
from check_doc_links import links_in

ATTEMPTS = 3
TIMEOUT_S = 45
SLEEP_BETWEEN_S = 20


def alive(url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "docs-accuracy-check"})
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                if resp.status < 400:
                    return True
        except Exception as e:
            print(f"  attempt {attempt + 1}/{ATTEMPTS} for {url}: {e}")
        time.sleep(SLEEP_BETWEEN_S)
    return False


def main() -> None:
    urls = set()
    for name in sorted(LIVING):
        for _, target in links_in(Path(name)):
            if target.startswith(("http://", "https://")):
                urls.add(target)
    dead = [u for u in sorted(urls) if not alive(u)]
    if dead:
        print("External URLs unreachable after retries:", file=sys.stderr)
        for u in dead:
            print(f"  {u}", file=sys.stderr)
        sys.exit(1)
    print(f"External URL check passed ({len(urls)} URLs).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/docs-accuracy.yml`:

```yaml
name: docs-accuracy
# ADR-0011: scheduled drift detection. Failures file an issue, never a red PR.
on:
  schedule:
    - cron: "0 9 * * 1"   # weekly — full mechanical suite vs main + external URLs
    - cron: "0 9 1 * *"   # monthly — Layer-3 human review reminder
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  drift-checks:
    if: github.event_name == 'workflow_dispatch' || github.event.schedule == '0 9 * * 1'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install yq (pinned, like every other tool here)
        run: |
          sudo curl -fsSL https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64 -o /usr/local/bin/yq
          sudo chmod +x /usr/local/bin/yq
      - name: Full mechanical suite vs main (links + all fact tiers)
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          python3 .github/scripts/check_doc_links.py
          python3 .github/scripts/check_doc_facts.py --tier all
      - name: External URL liveness (tolerant — the demo sleeps ~30 s)
        run: python3 .github/scripts/check_external_urls.py
      - name: File or update the tracking issue
        if: failure()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh label create docs-accuracy --color D93F0B \
            --description "docs drifted from reality (ADR-0011)" --force
          RUN_URL="${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
          EXISTING=$(gh issue list --label docs-accuracy --state open \
            --json number --jq '.[0].number // empty')
          if [ -n "$EXISTING" ]; then
            gh issue comment "$EXISTING" --body "Still failing: $RUN_URL"
          else
            gh issue create --title "docs-accuracy: scheduled drift check failed" \
              --label docs-accuracy \
              --body "The scheduled documentation-accuracy run failed: $RUN_URL. Includes anything deferred past the PR gate via Docs-Checks-Override. See ADR-0011."
          fi

  review-reminder:
    if: github.event.schedule == '0 9 1 * *'
    runs-on: ubuntu-latest
    steps:
      - name: Open the monthly Layer-3 review reminder
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh issue create --repo "${{ github.repository }}" \
            --title "Monthly docs fact-check review ($(date -u +%Y-%m))" \
            --body "Run the Layer-3 review (/docs-fact-check — see ADR-0011). Close when the review lands."
```

- [ ] **Step 3: Add the new workflow to the actionlint list**

In `ci.yml`'s infra job (~line 125):

```yaml
          ./actionlint .github/workflows/ci.yml .github/workflows/demo-pipeline.yml .github/workflows/docs-accuracy.yml
```

- [ ] **Step 4: Verify locally**

Run: `python3 .github/scripts/check_external_urls.py`
Expected: `External URL check passed (N URLs).` (May take a couple of minutes if the demo is asleep.)
Run: `python3 -m unittest discover -s .github/scripts` — still green (the new script has no tests of its own logic beyond what execution proves; it is scheduled-only and non-gating).

- [ ] **Step 5: Commit, push, open PR C**

```bash
git add .github/workflows/docs-accuracy.yml .github/scripts/check_external_urls.py .github/workflows/ci.yml
git commit -m "feat(docs-accuracy): scheduled drift workflow + external-URL liveness"
git push -u origin docs-accuracy-scheduled
```

Open PR C (repo headings). `## Testing`: after merge, trigger `gh workflow run docs-accuracy.yml` once and link the green run in a follow-up comment — `workflow_dispatch` requires the workflow to exist on the default branch first, so this verification lands post-merge by design. `## Risk & rollback`: workflow only files issues; it cannot gate PRs.

- [ ] **Step 6: Post-merge verification (part of this task, not optional)**

```bash
gh workflow run docs-accuracy.yml
gh run watch --exit-status
```

Expected: green `drift-checks` job (the scheduled-tier fact runs with the workflow's GH_TOKEN). Comment the run URL on the merged PR.

---

### Task 9: Layer-3 slash command (`/docs-fact-check`)

**Files:**
- Create: `.claude/commands/docs-fact-check.md`

**Interfaces:**
- Consumes: `check_doc_facts.LIVING` (conceptually — the command's doc list must match it), `make docs-checks`.
- Produces: the repeatable Layer-3 review procedure, referenced by ADR-0011 and the monthly reminder issue.

- [ ] **Step 1: Write the command**

Create `.claude/commands/docs-fact-check.md`:

```markdown
# /docs-fact-check — Layer-3 documentation review (ADR-0011)

The judgment layer of the documentation-accuracy practice. Run monthly (a
reminder issue is opened automatically), after any milestone-sized merge, or
before sharing the repo with a reader.

## Procedure

1. **Mechanical sweep first:** run `make docs-checks` (link integrity + all
   registered fact tiers). Fix or ticket anything red before proceeding —
   the human pass must not waste attention on machine-checkable drift.
2. **Scope:** the living docs — the `LIVING` set in
   `.github/scripts/check_doc_facts.py` is the source of truth for the list.
   Dated and historical docs are checked ONLY for internal accuracy (broken
   claims about their own time) and are NEVER edited to match current code.
3. **Adversarial audit, one agent per doc:** dispatch a subagent per living
   doc with the instruction: "Verify every factual claim in this doc against
   its source (the file, config, API, or command output it describes). You
   are trying to prove the doc WRONG. Report each finding with the claim,
   the source checked, and the evidence." Include the error taxonomy from
   the spec (`docs/superpowers/specs/2026-07-17-docs-accuracy-practice-design.md`
   § "The error taxonomy") so agents know the drift classes.
4. **Verify findings before acting:** re-check every reported finding against
   the source yourself. Agents produce false positives; the pilot's rule is
   controller-verified corrections only.
5. **Corrections are their own PR** (never mixed with feature work), using the
   repo's PR-body headings. For each corrected claim, apply the triage order
   before re-writing a number: delete → soften to estimate → detie to a
   CI-tested source → register a fact annotation.
6. **Close the loop:** ticket anything deferred; close the reminder issue with
   a one-line result ("N findings / M corrected / clean").

## Honesty rules

- "Fix the claim, not the phrasing you first noticed" — grep for every
  restatement of a corrected fact across all docs.
- Estimates must be labeled as estimates; a rough figure stated as measured
  fact is a finding even when the number is roughly right.
```

- [ ] **Step 2: Verify the command loads**

Run: `ls .claude/commands/` and confirm `docs-fact-check.md` is listed. (Slash commands are picked up from this directory by Claude Code; there is no build step.)

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/docs-fact-check.md
git commit -m "feat(docs-accuracy): /docs-fact-check Layer-3 review command"
```

---

### Task 10: ADR-0011 + CLAUDE.md policy → PR D

**Files:**
- Create: `docs/adr/0011-documentation-accuracy-practice.md`
- Modify: `CLAUDE.md` (add a "Documentation accuracy" section)
- Modify: `ROADMAP.md` (turn Task 2's plain "ADR-0011" mention into a real link)

**Interfaces:**
- Consumes: everything shipped in PRs A–C.
- Produces: the durable policy record; the CLAUDE.md rule future sessions follow.

- [ ] **Step 1: Write ADR-0011**

Create `docs/adr/0011-documentation-accuracy-practice.md` (template format: `# ADR-NNNN: title`, `- Status:`, `- Date:`, `## Context`, `## Decision`, `## Consequences` — and a `<!-- doc-status: dated -->` marker line first):

```markdown
<!-- doc-status: dated -->
# ADR-0011: The documentation-accuracy practice — docs have tests

- Status: accepted
- Date: <TODAY'S DATE — the date this ADR is committed>

## Context

The repo's principle is that every doc claim links to something a reader can
verify. The fact-check pilot (PR #68) showed care alone fails: 14 inaccuracies
across 6 of 8 audited docs. The two clean docs were clean because their
subject matter is already under automated test — claims stay true when their
source of truth is tested, not when authors are careful. Full design:
[the spec](../superpowers/specs/2026-07-17-docs-accuracy-practice-design.md).

## Decision

Four layers (details and error taxonomy in the spec):

1. **Link integrity** (`check_doc_links.py`) — every internal link/anchor in
   every tracked doc resolves; PR-blocking; file list derived by glob.
2. **Registered facts** (`check_doc_facts.py`) — load-bearing claims carry an
   in-place annotation (command + expected value + tier). `tier=pr` reads only
   repo files and blocks PRs (and re-runs on every main push — the merge-race
   net). `tier=scheduled` may touch network/live state and runs weekly,
   filing a `docs-accuracy` issue on failure — never gating a PR. An
   adjacency rule binds each annotation to its prose so neither drifts alone.
3. **Human review** (`/docs-fact-check`) — the judgment layer: monthly
   (automated reminder), after milestone-sized merges, on demand before
   sharing. `make docs-checks` is the mechanical sweep that precedes it.
4. **Taxonomy** — every in-scope doc declares `<!-- doc-status: living|dated|
   historical -->`. Facts live only in living docs. Dated/historical docs are
   never edited to match current code — updating a record of the past would
   make it wrong.

**The load-bearing rule.** Register a claim only if (1) it states a specific
verifiable value, (2) a reader finding it wrong would distrust the doc, and
(3) it survived the mandatory triage: **delete → soften to estimate → detie
to a CI-tested source → register.** Registration is last resort; the set
stays small (~5–10). Deliberately NOT registered: the cost/duration
estimates (labeled estimates; measured figure ticketed), "all four
milestones shipped" (terminal state), the CI job list (already detied).

**The override.** `Docs-Checks-Override: <reason>` in a PR body downgrades
Layer-1/2 failures to warnings for that PR only. Main-push and scheduled runs
ignore overrides — the debt surfaces there and in the weekly issue until a
follow-up clears it. The override cannot expand the command allowlist and
cannot authorize edits to dated docs.

## Consequences

- Editing a registered number means editing prose + annotation together; the
  red CI message says exactly that. Small authoring friction, bought: the
  "four vs three" class of error now fails a check instead of shipping.
- The annotation grammar cannot hold nested double quotes; complex commands
  become small helpers under `.github/scripts/` (e.g. `fact_demo_runs.py`).
- A wrong-but-registered claim fails loudly; an unregistered wrong claim
  still relies on Layer 3. The triage rule is what keeps that residue small.
- Every gating checker was watched to fail before merge (red-run links in
  PRs A and B) — a check nobody has seen fail is not yet a check.
```

Replace `<TODAY'S DATE — the date this ADR is committed>` with the actual commit date in `YYYY-MM-DD`.

- [ ] **Step 2: Add the CLAUDE.md section**

After the "## After a PR merges" section of `CLAUDE.md`:

```markdown
## Documentation accuracy (ADR-0011)

- Before any docs-touching PR: `make docs-checks` (links + registered facts —
  the same commands CI runs).
- Editing a number guarded by a `<!-- fact: ... -->` annotation? Update the
  prose AND the annotation together; CI enforces both.
- New load-bearing claim? Triage first — delete → soften → detie to a
  CI-tested source → register — in that order (see
  [ADR-0011](docs/adr/0011-documentation-accuracy-practice.md)).
- Never edit dated/historical docs (`<!-- doc-status: dated -->`) to match
  current code.
- After milestone-sized merges, run `/docs-fact-check` (the monthly reminder
  issue covers the calendar cadence).
- Escape hatch when legitimately blocked mid-restructure:
  `Docs-Checks-Override: <reason>` in the PR body — it defers, never erases.
```

- [ ] **Step 3: Link the ROADMAP mention**

In `ROADMAP.md`, Task 2's bullet — change the plain `(ADR-0011)` to `([ADR-0011](docs/adr/0011-documentation-accuracy-practice.md))`.

- [ ] **Step 4: Verify**

Run: `make docs-checks`
Expected: all green — including the link checker resolving the three new ADR links, and the taxonomy checker accepting the new ADR's `dated` marker.

- [ ] **Step 5: Commit, push, open PR D**

```bash
git add docs/adr/0011-documentation-accuracy-practice.md CLAUDE.md ROADMAP.md .claude/commands/docs-fact-check.md
git commit -m "docs(adr): ADR-0011 documentation-accuracy practice + CLAUDE.md policy"
git push -u origin docs-accuracy-policy
```

Open PR D (repo headings). After approval + merge: post-merge ritual, move the board card "Durable documentation-verification practice (PARENT…)" to **Done** (option `98236657`), and ticket any deferred follow-ups (per the board convention: deferred work gets a ticket, not a PR note) — known candidates: the measured-cost annotation once Cost Explorer data lands, and `aws`-tier facts if live-infra claims ever get registered (needs a creds story in the scheduled workflow).

---

## Deviations discovered in execution

- **Task 1:** the checker's first real-repo run found 26 pre-existing breaks:
  4 genuinely broken `#phase-0-already-shipped` anchors in ROADMAP.md (the
  em-dash heading slugs to a double hyphen — fixed), and 22 broken links in
  `docs/superpowers/` plans/specs. Maintainer decision: exempt
  `docs/superpowers/**` from Layer 1 (`SKIP_PREFIXES` + `in_scope()` in
  `check_doc_links.py`), matching the taxonomy exemption; spec amended in
  place. Frozen work orders link files that don't exist until implemented.
