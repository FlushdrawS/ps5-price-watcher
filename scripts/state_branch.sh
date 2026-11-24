#!/usr/bin/env bash
# Persist the watcher's data directory (state.json + history/*.jsonl) on a
# separate branch (default: watcher-state).
#
#   scripts/state_branch.sh load   -> restores all files of the branch into $PS5W_DATA_DIR
#   scripts/state_branch.sh save   -> commits $PS5W_DATA_DIR as the branch content and force-pushes
#
# The branch always holds exactly ONE commit whose tree is the data directory,
# so git history never grows; the history *files* inside it keep growing (and
# are pruned by the app after `history_retention_days`). `main` is never touched.
# Uses git plumbing with a temporary index - no checkout, no working-tree changes.
set -euo pipefail

BRANCH="${STATE_BRANCH:-watcher-state}"
DIR="${PS5W_DATA_DIR:-data}"
REMOTE="${STATE_REMOTE:-origin}"

case "${1:-}" in
  load)
    mkdir -p "$DIR"
    if git fetch --quiet --depth=1 "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null; then
      git archive --format=tar FETCH_HEAD | tar -x -C "$DIR"
      echo "Loaded $(find "$DIR" -type f | wc -l) file(s) from branch '$BRANCH'"
    else
      echo "No '$BRANCH' branch yet - starting fresh"
    fi
    ;;
  save)
    if [ ! -f "$DIR/state.json" ]; then
      echo "No $DIR/state.json - nothing to save"
      exit 0
    fi
    export GIT_AUTHOR_NAME="ps5-watcher-bot" GIT_AUTHOR_EMAIL="ps5-watcher-bot@users.noreply.github.com"
    export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
    tmp_index="$(mktemp)"
    rm -f "$tmp_index"
    trap 'rm -f "$tmp_index"' EXIT
    # Only data files: state.json and history/*.jsonl (never anything else by accident).
    (
      cd "$DIR"
      find . -type f \( -name 'state.json' -o -path './history/*.jsonl' \) -print0
    ) | GIT_INDEX_FILE="$tmp_index" git --work-tree="$DIR" update-index --add -z --stdin
    tree=$(GIT_INDEX_FILE="$tmp_index" git write-tree)
    commit=$(git commit-tree "$tree" -m "watcher data $(date -u +%Y-%m-%dT%H:%MZ)")
    for attempt in 1 2 3; do
      if git push --quiet --force "$REMOTE" "$commit:refs/heads/$BRANCH"; then
        echo "Saved data to branch '$BRANCH'"
        exit 0
      fi
      echo "Push failed (attempt $attempt), retrying..." >&2
      sleep $((attempt * 5))
    done
    echo "Could not push data" >&2
    exit 1
    ;;
  *)
    echo "usage: $0 load|save" >&2
    exit 2
    ;;
esac
