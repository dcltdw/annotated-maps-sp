#!/usr/bin/env python3
"""
Validate that a PR body contains all required sections and that they are filled in
(i.e., not empty and not left as the unfilled template placeholders).

Reads the PR body from the PR_BODY environment variable.
Exits 1 on failure, 0 on success.
"""

import os
import re
import sys

REQUIRED_SECTIONS = [
    "## Summary",
    "## Provenance",
    "## Reasoning",
    "## Testing",
    "## Risk & rollback",
]

# Lines that count as "unfilled" content — template comments and blank lines.
_COMMENT_RE = re.compile(r"^\s*<!--.*?-->\s*$")
_BLANK_RE = re.compile(r"^\s*$")


def _section_content(body: str, heading: str) -> list[str]:
    """Return non-trivial lines in the body that follow *heading* until the next ## heading."""
    lines = body.splitlines()
    inside = False
    content: list[str] = []
    for line in lines:
        if line.strip().lower().startswith(heading.lower()):
            inside = True
            continue
        if inside:
            if line.startswith("## "):
                break
            if not _BLANK_RE.match(line) and not _COMMENT_RE.match(line):
                content.append(line)
    return content


def main() -> None:
    body = os.environ.get("PR_BODY", "")

    if not body.strip():
        print("ERROR: PR_BODY is empty. A PR description is required.", file=sys.stderr)
        sys.exit(1)

    errors: list[str] = []

    for section in REQUIRED_SECTIONS:
        # Check the section heading is present (case-insensitive prefix match).
        found_heading = any(
            line.strip().lower().startswith(section.lower())
            for line in body.splitlines()
        )
        if not found_heading:
            errors.append(f"Missing required section: {section!r}")
            continue

        # Check that the section has at least some real content.
        content = _section_content(body, section)
        if not content:
            errors.append(f"Section {section!r} is present but appears unfilled (no real content).")

    if errors:
        print("PR body validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print("PR body validation passed.")


if __name__ == "__main__":
    main()
