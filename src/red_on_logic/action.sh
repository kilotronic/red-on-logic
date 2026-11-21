#!/usr/bin/env bash
# The GitHub Action's step: turn the inputs into red-on-logic's arguments and run it with
# the runner's python3 (3.10 or later; the check itself needs only the standard library).
set -euo pipefail

if [ -z "${BASE:-}" ]; then
  echo "red-on-logic: no base commit (this is not a pull request and no base input was given); nothing to check"
  exit 0
fi

if ! git cat-file -e "${BASE}^{commit}" 2>/dev/null; then
  git fetch --no-tags --quiet origin "$BASE" || {
    echo "red-on-logic: could not get the base commit $BASE: check out with fetch-depth: 0" >&2
    exit 2
  }
fi

# actions/checkout of a pull request checks out GitHub's merge commit. Its first parent is
# the base branch as merged, which may be newer than the event's base: judge against that
# parent, so other people's commits on the base branch are never swapped or read for a skip.
# Only when `base` was left at the event's base: an explicit one is used as given.
if [ -n "${PR_HEAD:-}" ] && [ "$BASE" = "${EVENT_BASE:-}" ] && [ "$(git rev-parse -q --verify 'HEAD^2' 2>/dev/null || true)" = "$PR_HEAD" ]; then
  BASE=$(git rev-parse 'HEAD^1')
fi

args=("--base=$BASE" "--runner=${RUNNER:-auto}")
[ -n "${PYTEST_CMD:-}" ] && args+=("--pytest=$PYTEST_CMD")
[ -n "${VITEST_CMD:-}" ] && args+=("--vitest=$VITEST_CMD")
[ -n "${JEST_CMD:-}" ] && args+=("--jest=$JEST_CMD")
[ -n "${NODE_CMD:-}" ] && args+=("--node=$NODE_CMD")
[ -n "${RUN_CMD:-}" ] && args+=("--command=$RUN_CMD")
[ -n "${WORKDIR:-}" ] && args+=("--working-directory=$WORKDIR")
while IFS= read -r pattern; do
  [ -n "$pattern" ] && args+=("--import-pattern=$pattern")
done < <(printf '%s\n' "${IMPORT_PATTERNS:-}")
while IFS= read -r glob; do
  [ -n "$glob" ] && args+=("--code-paths=$glob")
done < <(printf '%s\n' "${CODE_PATHS:-}" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
while IFS= read -r glob; do
  [ -n "$glob" ] && args+=("--test-paths=$glob")
done < <(printf '%s\n' "${TEST_PATHS:-}" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
while IFS= read -r label; do
  [ -n "$label" ] && args+=("--label=$label")
done < <(python3 -I -c 'import json, os; print("\n".join(json.loads(os.environ.get("LABELS") or "[]") or []))')
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && args+=("--summary=$GITHUB_STEP_SUMMARY")

ROL_SRC="$GITHUB_ACTION_PATH/src" exec python3 -I -c \
  'import os, sys; sys.path.insert(0, os.environ.pop("ROL_SRC")); from red_on_logic.cli import entry; entry()' \
  "${args[@]}"
