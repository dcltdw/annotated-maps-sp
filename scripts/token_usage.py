#!/usr/bin/env python3
"""Summarize Claude Code token usage for this project's transcripts.

Reads Claude Code session transcripts (``~/.claude/projects/<mangled-cwd>/**/*.jsonl``,
subagent transcripts included) and sums the per-turn ``usage`` figures. The headline
numbers are *output* (generated) and *cache-write* tokens -- the two that reflect real
effort/cost. Cache *reads* re-read the same context every turn and are the cheapest
tier, so they dominate the gross count but mislead as a metric.

Usage:
    python scripts/token_usage.py [--dir PATH] [--per-file] [--no-subagents]

CAVEAT: this depends on Claude Code's internal, undocumented transcript format and
on-disk layout, which may change without notice. It is a personal dev utility, not
built on a stable API. It emits only aggregate counts, never transcript content.
"""

import argparse
import json
import re
from pathlib import Path

# usage label -> the JSON field it sums
FIELDS = {
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "input": "input_tokens",
    "cache_read": "cache_read_input_tokens",
}


def transcript_dir_for(project_path):
    """Map an absolute project path to its Claude Code transcript directory.

    Claude mangles the path into the directory name by replacing '/', '_' and '.'
    with '-' (e.g. /Users/x/Github/foo -> -Users-x-Github-foo).
    """
    mangled = re.sub(r"[/_.]", "-", str(project_path))
    return Path.home() / ".claude" / "projects" / mangled


def usage_of(record):
    """Return (message_id, usage_dict) for a record, or None if it has no usage block."""
    message = record.get("message") or {}
    usage = message.get("usage") or record.get("usage")
    if not isinstance(usage, dict):
        return None
    message_id = message.get("id") or record.get("uuid")
    return message_id, usage


def _output(usage):
    return usage.get("output_tokens") or 0


def tally(records):
    """Sum usage across records, deduping by message id.

    Keeps the largest-output usage per id so a streaming partial never shadows the
    final message. Records without a usage block are ignored; those without an id are
    each counted once. Returns a dict with a key per FIELDS label plus 'turns'.
    """
    by_id = {}
    anonymous = []
    for record in records:
        found = usage_of(record)
        if found is None:
            continue
        message_id, usage = found
        if message_id is None:
            anonymous.append(usage)
            continue
        previous = by_id.get(message_id)
        if previous is None or _output(usage) > _output(previous):
            by_id[message_id] = usage

    counted = list(by_id.values()) + anonymous
    totals = {label: 0 for label in FIELDS}
    for usage in counted:
        for label, field in FIELDS.items():
            totals[label] += usage.get(field) or 0
    totals["turns"] = len(counted)
    return totals


def _records_in(path):
    """Yield parsed JSON objects from a .jsonl transcript, skipping non-usage/junk lines."""
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or '"usage"' not in line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _add(into, other):
    for key, value in other.items():
        into[key] = into.get(key, 0) + value


def gather(transcripts_dir, include_subagents=True):
    """Tally every transcript file under *transcripts_dir*. Returns (totals, per_file)."""
    pattern = "**/*.jsonl" if include_subagents else "*.jsonl"
    totals = {label: 0 for label in FIELDS}
    totals["turns"] = 0
    per_file = []
    for path in sorted(transcripts_dir.glob(pattern)):
        file_totals = tally(_records_in(path))
        if file_totals["turns"] == 0:
            continue
        _add(totals, file_totals)
        per_file.append((path, file_totals))
    return totals, per_file


def humanize(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.2f}K"
    return str(n)


def format_report(transcripts_dir, totals, per_file, show_files):
    out = totals["output"]
    cw = totals["cache_write"]
    grand = out + cw + totals["input"] + totals["cache_read"]
    lines = [
        f"Transcripts: {transcripts_dir}",
        f"Files: {len(per_file)}    Turns: {totals['turns']}",
        "",
        f"  output (generated):   {humanize(out):>10}",
        f"  cache write:          {humanize(cw):>10}",
        f"  -- effort subtotal:   {humanize(out + cw):>10}   (output + cache-write)",
        "",
        f"  fresh input:          {humanize(totals['input']):>10}",
        f"  cache read:           {humanize(totals['cache_read']):>10}",
        f"  grand total touched:  {humanize(grand):>10}",
    ]
    if show_files:
        lines.append("")
        lines.append("Per file (by effort = output + cache-write):")
        rows = sorted(per_file, key=lambda p: -(p[1]["output"] + p[1]["cache_write"]))
        for path, t in rows:
            effort = t["output"] + t["cache_write"]
            lines.append(
                f"  {humanize(effort):>9}  out={humanize(t['output']):>8}  "
                f"cw={humanize(t['cache_write']):>8}  turns={t['turns']:>4}  {path.name}"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="transcript directory (default: auto-derived from the repo root)",
    )
    parser.add_argument(
        "--no-subagents",
        action="store_true",
        help="exclude subagent transcripts (top-level session files only)",
    )
    parser.add_argument("--per-file", action="store_true", help="show a per-file breakdown")
    args = parser.parse_args()

    if args.dir is not None:
        transcripts_dir = args.dir
    else:
        repo_root = Path(__file__).resolve().parent.parent
        transcripts_dir = transcript_dir_for(repo_root)

    if not transcripts_dir.is_dir():
        raise SystemExit(
            f"No transcripts found at {transcripts_dir}\n"
            "Pass --dir to point at a Claude Code project transcript directory."
        )

    totals, per_file = gather(transcripts_dir, include_subagents=not args.no_subagents)
    print(format_report(transcripts_dir, totals, per_file, args.per_file))


if __name__ == "__main__":
    main()
