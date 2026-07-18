#!/usr/bin/env python3
"""
Layer 1 of the documentation-accuracy practice (ADR-0011): every internal
link and #anchor in every tracked Markdown file outside the docs/superpowers/
archive must resolve. External URLs
are NOT checked here — they belong to the scheduled workflow, which cannot
gate a PR. `--list-external` prints them (diagnostic only; the scheduled
workflow derives its own living-docs URL set).

Exits 1 on failure, 0 on success.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from docs_common import tracked_md_files, override_reason

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")

SKIP_PREFIXES = ("docs/superpowers/",)  # frozen workflow artifacts (plans/specs) — they may link files that do not exist yet


def in_scope(path: Path) -> bool:
    return not str(path).startswith(SKIP_PREFIXES)

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
    for path in (p for p in tracked_md_files() if in_scope(p)):
        for _, target in links_in(path):
            if target.startswith(("http://", "https://")):
                urls.add(target)
    return sorted(urls)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-external", action="store_true",
                    help="print external URLs instead of checking internal links")
    ap.add_argument("--allow-override", action="store_true",
                    help="honor a Docs-Checks-Override line in $PR_BODY (PR runs only)")
    args = ap.parse_args()

    if args.list_external:
        print("\n".join(external_urls()))
        return

    files = [p for p in tracked_md_files() if in_scope(p)]
    errors: list[str] = []
    for path in files:
        errors += check_file(path)
    if errors:
        if args.allow_override:
            reason = override_reason(os.environ.get("PR_BODY", ""))
            if reason:
                print(f"OVERRIDDEN ({len(errors)} failure(s)) — reason: {reason}")
                print("Deferred, not erased: the main-push and scheduled runs ignore overrides.")
                for e in errors:
                    print(f"  warning: {e}")
                return

        print("Doc link check failed:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Doc link check passed ({len(files)} files).")


if __name__ == "__main__":
    main()
