#!/usr/bin/env python3
"""Fact helper (ADR-0011): the M4 verification-run record quoted in
docs/for-reviewers.md. The createdAt bound freezes the set to the five
verification runs — later cron/dispatch runs must not shift this record."""
import json
import subprocess

# The createdAt filter below is the freeze, but it only works on runs the
# query actually returns: `gh run list` returns the N *most recent* runs, so a
# limit smaller than the lifetime run count would eventually push the frozen
# pre-2026-07-16 set off the end and silently shrink the record to runs=0.
# The limit therefore has to stay comfortably above the total number of
# demo-pipeline runs ever, which the monthly cron grows by ~1.
out = subprocess.run(
    ["gh", "run", "list", "--workflow", "demo-pipeline.yml", "--limit", "1000",
     "--json", "conclusion,createdAt"],
    capture_output=True, text=True, check=True,
).stdout
runs = [r for r in json.loads(out) if r["createdAt"] < "2026-07-16"]
red = [r for r in runs if r["conclusion"] == "failure"]
print(f"runs={len(runs)} red={len(red)}")
