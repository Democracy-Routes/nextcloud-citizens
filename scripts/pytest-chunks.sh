#!/bin/sh
# Run the Python test suite the way the week's regressions ran it: in the
# citizens-test image, one container at a time, --memory 1200m, in six chunks
# each well under ten minutes — and against a SNAPSHOT of the tree, so editing
# while a chunk runs never changes what the container sees (R33).
#
#   sh scripts/pytest-chunks.sh            # all six chunks
#   sh scripts/pytest-chunks.sh 3 5        # chunks 3 and 5 only
#   LIVE=1 sh scripts/pytest-chunks.sh     # mount the tree itself (no snapshot)
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
SNAP=${SNAP:-/tmp/citizens-pytest-snapshot}
if [ -z "$LIVE" ]; then
  mkdir -p "$SNAP"
  rsync -a --delete --exclude node_modules --exclude .git --exclude frontend/node_modules "$REPO/" "$SNAP/"
  TREE=$SNAP
else
  TREE=$REPO
fi
cd "$TREE"
files=$(ls tests/integration/test_*.py | sort)
count=$(echo "$files" | wc -l)
chunk_files() {
  case "$1" in
    1) echo tests/unit ;;
    2) echo "$files" | sed -n '1,10p' ;;
    3) echo "$files" | sed -n '11,15p' ;;
    4) echo "$files" | sed -n '16,20p' ;;
    5) echo "$files" | sed -n '21,30p' ;;
    6) echo "$files" | sed -n "31,${count}p" ;;
  esac
}
chunks=${*:-"1 2 3 4 5 6"}
status=0
for n in $chunks; do
  paths=$(chunk_files "$n" | tr '\n' ' ')
  [ -z "$paths" ] && continue
  start=$(date +%s)
  echo "== chunk $n: $paths"
  docker run --rm --memory 1200m --user root -v "$TREE:/app" -w /app --entrypoint sh citizens-test \
    -c "pip install -q pytest ruff 2>/dev/null; python -m pytest -q -p no:cacheprovider --tb=short --show-capture=no $paths > /tmp/chunk.log 2>&1; rc=\$?; grep -v '^INFO\|^WARNING\|httpx\|Deprecat\|^  \|^$' /tmp/chunk.log | tail -15; exit \$rc" \
    || status=1
  echo "== chunk $n took $(( $(date +%s) - start )) s"
done
exit $status
