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
