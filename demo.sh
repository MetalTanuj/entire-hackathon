#!/usr/bin/env bash
# Entire Lakehouse Sentinel — end-to-end demo.
# Two commits that look nearly identical to git. One is safe. One takes out a
# dashboard. The audit tells them apart using live Lakehouse schema.
set -u
cd "$(dirname "$0")"
line() { printf '\n\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────────"; }

for BRANCH in tune-timeout drop-country; do
  git checkout -q "$BRANCH"
  line
  printf '\033[1m  CASE: %s\033[0m\n' "$BRANCH"
  line
  printf '\n  What git shows a reviewer:\n\n'
  git log -1 --format='    commit %h — %s'
  git diff main --stat | sed 's/^/    /'
  printf '\n  What the Sentinel shows:\n'
  .venv/bin/python -m sentinel.audit . main
done
git checkout -q main
