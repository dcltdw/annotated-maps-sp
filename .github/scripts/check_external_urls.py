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
