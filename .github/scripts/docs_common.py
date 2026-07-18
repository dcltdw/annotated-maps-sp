"""Shared helpers for the documentation-accuracy checkers (ADR-0011)."""
import re
import subprocess
from pathlib import Path


def tracked_md_files() -> list[Path]:
    """Every tracked Markdown file, derived from git — never hand-maintained."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.splitlines() if p]


_OVERRIDE_RE = re.compile(r"^Docs-Checks-Override:[ \t]*(\S.*?)\s*$", re.MULTILINE)


def override_reason(body: str) -> str | None:
    """The PR-body escape hatch (ADR-0011). Overrides DEFER failures — main-push
    and scheduled runs ignore them — and require a non-empty reason."""
    m = _OVERRIDE_RE.search(body or "")
    return m.group(1) if m else None
