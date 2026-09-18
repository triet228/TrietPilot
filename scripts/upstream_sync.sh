#!/usr/bin/env bash
# Fetch new openpilot commits without restoring the original upstream ancestry.
set -euo pipefail
cd "$(dirname "$0")/.."

UPSTREAM_URL="https://github.com/commaai/openpilot.git"
UPSTREAM_BRANCH="master"
BASE_FILE="scripts/upstream_base.txt"
TARGET_FILE="$(git rev-parse --git-path upstream-sync-target)"

if [[ "${1:-}" == "--record" ]]; then
  if [[ ! -f "$TARGET_FILE" ]] || [[ -n "$(git status --porcelain)" ]] || [[ -f "$(git rev-parse --git-path CHERRY_PICK_HEAD)" ]]; then
    echo "finish the cherry-pick and leave a clean working tree before recording the sync" >&2
    exit 1
  fi
  cat "$TARGET_FILE" > "$BASE_FILE"
  git add "$BASE_FILE"
  git commit -m "Record upstream sync base"
  rm "$TARGET_FILE"
  exit 0
fi

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "$UPSTREAM_URL"
fi
git fetch --quiet upstream "$UPSTREAM_BRANCH"

BASE="$(tr -d '\r\n' < "$BASE_FILE")"
if ! git merge-base --is-ancestor "$BASE" "upstream/$UPSTREAM_BRANCH"; then
  echo "recorded upstream base is no longer on upstream/$UPSTREAM_BRANCH" >&2
  exit 1
fi

if [[ "${1:-}" == "--files" ]]; then
  git diff --name-status "upstream/$UPSTREAM_BRANCH" HEAD
  exit 0
fi

BEHIND="$(git rev-list --count "$BASE..upstream/$UPSTREAM_BRANCH")"
echo "$BEHIND new upstream commits since recorded base ${BASE:0:9}"
if [[ "$BEHIND" -eq 0 ]]; then
  exit 0
fi

echo
echo "# files changed by both the fork and new upstream commits:"
comm -12 \
  <(git diff --name-only "$BASE" HEAD | sort) \
  <(git diff --name-only "$BASE" "upstream/$UPSTREAM_BRANCH" | sort) || true

if [[ "${1:-}" != "--sync" && "${1:-}" != "--merge" ]]; then
  echo
  echo "run with --sync to apply the new commits, or --files to list fork differences"
  exit 0
fi

if [[ -n "$(git status --porcelain)" ]] || [[ -f "$TARGET_FILE" ]]; then
  echo "finish the prior sync and leave a clean working tree first" >&2
  exit 1
fi
if git log --format=%B "$BASE..upstream/$UPSTREAM_BRANCH" | grep -Eiq '^[[:space:]]*Co-[Aa]uthored-[Bb]y:.*(Claude|anthropic)'; then
  echo "new upstream commits contain Claude attribution; remove those trailers before updating the fork" >&2
  exit 1
fi

TARGET="$(git rev-parse "upstream/$UPSTREAM_BRANCH")"
printf '%s\n' "$TARGET" > "$TARGET_FILE"
if GIT_LFS_SKIP_SMUDGE=1 GIT_TERMINAL_PROMPT=0 git cherry-pick "$BASE..$TARGET"; then
  "$0" --record
else
  echo "resolve conflicts, run git cherry-pick --continue, then run scripts/upstream_sync.sh --record" >&2
  exit 1
fi
