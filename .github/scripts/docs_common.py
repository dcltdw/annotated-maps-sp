"""Shared helpers for the documentation-accuracy checkers (ADR-0011)."""
import subprocess
from pathlib import Path


def tracked_md_files() -> list[Path]:
    """Every tracked Markdown file, derived from git — never hand-maintained."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.splitlines() if p]
