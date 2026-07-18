"""Shared helpers for the documentation-accuracy checkers (ADR-0011)."""
import os
import re
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """The worktree root. The checkers speak repo-relative paths throughout —
    error messages, the LIVING set, fact commands like `yq '...' render.yaml` —
    so they anchor here rather than trusting the caller's cwd."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout
    return Path(out.strip())


def tracked_md_files() -> list[Path]:
    """Every tracked Markdown file, derived from git — never hand-maintained.
    Paths are repo-root-relative regardless of cwd: plain `git ls-files` run
    from a subdirectory lists only that subtree, which would silently shrink
    the checked set to almost nothing."""
    out = subprocess.run(
        ["git", "ls-files", "--full-name", "*.md"],
        capture_output=True, text=True, check=True, cwd=repo_root(),
    ).stdout
    return [Path(p) for p in out.splitlines() if p]


class DocReadError(Exception):
    """A doc could not be read. Carries a ready-to-print 'path: message'."""


def read_doc_text(path: Path) -> str:
    """Read a doc as UTF-8, turning the two expected I/O failures into a
    reportable error instead of a traceback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise DocReadError(
            f"{path}: not valid UTF-8 (byte {e.start}: {e.reason})"
        ) from e
    except FileNotFoundError as e:
        raise DocReadError(
            f"{path}: file not found — renamed or deleted without updating "
            "the checker that references it"
        ) from e


_OVERRIDE_RE = re.compile(r"^Docs-Checks-Override:[ \t]*(\S.*?)\s*$", re.MULTILINE)


def override_reason(body: str) -> str | None:
    """The PR-body escape hatch (ADR-0011). Overrides DEFER failures — main-push
    and scheduled runs ignore them — and require a non-empty reason."""
    m = _OVERRIDE_RE.search(body or "")
    return m.group(1) if m else None


def overridden(errors: list[str], allow: bool) -> bool:
    """Whether an accepted PR-body override should downgrade `errors` to
    warnings. Prints the deferral notice when it does. Shared by both
    checkers so the wording and the accept/reject rule cannot drift apart."""
    if not allow:
        return False
    reason = override_reason(os.environ.get("PR_BODY", ""))
    if not reason:
        return False
    print(f"OVERRIDDEN ({len(errors)} failure(s)) — reason: {reason}")
    print("Deferred, not erased: the main-push and scheduled runs ignore overrides.")
    for e in errors:
        print(f"  warning: {e}")
    return True
