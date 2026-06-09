#!/usr/bin/env python3
import subprocess
from pathlib import Path

# Files that ARE tracked in git but should NOT count toward "lines of code,
# configuration, and documentation." Pure dependency manifests / lockfiles get
# excluded; everything else tracked in git counts (source incl. tests, CI /
# Docker / render / tsconfig config, and docs incl. ADRs). Build artifacts and
# secrets (node_modules/, dist/, .env, __pycache__) are already untracked via
# .gitignore, so `git ls-files` never sees them.
IGNORE_FILES = {
    # Node manifest + lockfile
    'package.json',
    'package-lock.json',
    # Python (uv) project manifest + lockfile
    'pyproject.toml',
    'uv.lock',
}


# Source - https://stackoverflow.com/a/51495076
# Posted by Serhii, modified by community. See post 'Timeline' for change history
# Retrieved 2026-05-08, License - CC BY-SA 4.0
def is_binary(file_name):
    try:
        with open(file_name, 'tr') as check_file:  # try open file in text mode
            check_file.read()
            return False
    except:  # if fail then file is non-text (binary)
        return True


def examine_directory(path):
    results = subprocess.run(
        ['git', 'ls-files'],
        capture_output=True,
        text=True,
        cwd=str(path),
    ).stdout.split('\n')
    count = 0
    for fname in results:
        if fname == '':
            continue
        filename = path / fname
        if filename.name in IGNORE_FILES:
            continue
        if is_binary(str(filename)):
            continue
        # errors='replace' so a future binary commit (favicon, screenshot)
        # doesn't crash the count — those rows still get counted as 1+
        # lines but won't blow up.
        data = filename.read_text(errors='replace')
        count += len(data.splitlines())
    return count


def main():
    # Resolve to the repo root so the count is consistent regardless of the
    # caller's cwd. Script lives at scripts/count_lines.py; parent.parent
    # is the repo root.
    root = Path(__file__).resolve().parent.parent
    total_count = examine_directory(root)
    print(f"Lines of code, configuration, and documentation "
          f"(excluding manifests/lockfiles): {total_count}")


if __name__ == '__main__':
    main()
