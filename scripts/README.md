# Dev scripts

Standalone helper scripts (stdlib-only Python). Run them from the repo root.

## `count_lines.py`

Counts tracked lines of code, configuration, and documentation (excluding dependency
manifests/lockfiles).

```bash
python scripts/count_lines.py
```

## `token_usage.py`

Summarizes Claude Code token usage for this project's session transcripts. Headlines the
two figures that reflect real effort/cost — **output** (generated) and **cache-write**
tokens — and shows the fuller breakdown (fresh input, cache read, grand total) for
context.

```bash
python scripts/token_usage.py              # totals for this project
python scripts/token_usage.py --per-file   # + a per-transcript breakdown
python scripts/token_usage.py --dir PATH   # a specific transcript directory
python scripts/token_usage.py --no-subagents   # exclude subagent transcripts
```

It reads Claude Code's transcript files under `~/.claude/projects/<mangled-cwd>/`
(auto-derived from the repo root; override with `--dir`).

**Caveat:** this relies on Claude Code's internal, undocumented transcript format and
on-disk layout, which may change without notice — it's a personal dev utility, not built
on a stable API. It emits only aggregate counts, never transcript content.

## Tests

```bash
python -m pytest scripts/test_token_usage.py
```
