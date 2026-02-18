#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/codex-autopilot.sh \"task prompt\""
  exit 2
fi

TASK="$1"
BRANCH="codex/$(date +%Y%m%d-%H%M)-autopilot"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "Not inside a git repo: $REPO_DIR"
  exit 3
}

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree not clean. Commit/stash first."
  exit 4
fi

git switch -c "$BRANCH"

echo "[codex] running on branch: $BRANCH"
codex exec --full-auto -C "$REPO_DIR" "$TASK"

echo
if command -v pytest >/dev/null 2>&1; then
  echo "[verify] pytest -q"
  pytest -q || true
fi

echo
cat <<EOF
Done. Next steps:
  git status
  git add -A
  git commit -m "feat: <summary>"
  # optional: git switch main && git merge --ff-only $BRANCH
EOF
