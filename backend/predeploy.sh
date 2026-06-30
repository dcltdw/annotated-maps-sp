#!/usr/bin/env sh
# Render's preDeployCommand is not run through a shell, so it can't chain commands
# with `&&`. Keep the steps in this script (which sh executes in order) instead.
set -e
uv run python manage.py migrate
uv run python manage.py seed_demo --refresh
