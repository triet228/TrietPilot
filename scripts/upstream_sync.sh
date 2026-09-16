#!/usr/bin/env bash
# Keep TrietPilot current with commaai/openpilot.
#
#   scripts/upstream_sync.sh            fetch upstream, show how far behind we are and which
#                                       files both sides touched (the likely conflicts)
#   scripts/upstream_sync.sh --files    list every file this fork adds, changes or deletes
#   scripts/upstream_sync.sh --merge    merge upstream/master into the current branch
#
# Merging (not rebasing) is deliberate: the fork's history is already pushed and the
# device pulls it with a hard reset, so rewriting history would only cause trouble.
# See docs/TRIETPILOT.md for the full procedure and the conflict guide.
set -euo pipefail
cd "$(dirname "$0")/.."

UPSTREAM_URL="https://github.com/commaai/openpilot.git"
UPSTREAM_BRANCH="master"

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "adding upstream remote $UPSTREAM_URL"
  git remote add upstream "$UPSTREAM_URL"
fi
git fetch --quiet upstream "$UPSTREAM_BRANCH"

BASE="$(git merge-base HEAD "upstream/$UPSTREAM_BRANCH")"

if [ "${1:-}" = "--files" ]; then
  echo "# files this fork owns relative to upstream base ${BASE:0:9}"
  git diff --name-status "$BASE" HEAD | sort -k2
  exit 0
fi

BEHIND="$(git rev-list --count "HEAD..upstream/$UPSTREAM_BRANCH")"
AHEAD="$(git rev-list --count "upstream/$UPSTREAM_BRANCH..HEAD")"
echo "fork is $AHEAD commits ahead of and $BEHIND commits behind upstream/$UPSTREAM_BRANCH (base ${BASE:0:9})"

if [ "$BEHIND" -eq 0 ]; then
  echo "nothing to merge"
  exit 0
fi

echo
echo "# files changed by BOTH sides since the base, expect conflicts here:"
comm -12 \
  <(git diff --name-only "$BASE" HEAD | sort) \
  <(git diff --name-only "$BASE" "upstream/$UPSTREAM_BRANCH" | sort) || true

if [ "${1:-}" = "--merge" ]; then
  echo
  echo "merging upstream/$UPSTREAM_BRANCH..."
  if git merge --no-edit "upstream/$UPSTREAM_BRANCH"; then
    echo "merged cleanly. now run: python3 scripts/test_fork.py"
  else
    echo
    echo "conflicts. resolve them with docs/TRIETPILOT.md open, then:"
    echo "  git add -A && git commit && python3 scripts/test_fork.py"
    exit 1
  fi
else
  echo
  echo "run with --merge to merge, or --files to list what the fork owns"
fi
